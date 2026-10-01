"""Train Stage — real temporal training on gold matrices from split.

Method (declared in config.yaml, never paper numbers):
- X/y come from the split stage gold layer (selected+encoded features,
  P75/P25 target) via manifest_index.json — train never touches raw data.
- Search on the internal validation block, threshold calibration on the
  calib year (91-grid max F1), honest metrics on test + external years.
- Scaling fit on search_train only; class_weight=balanced, no resampling.
- Per-model manifests allow resume: re-running skips finished models.
"""
import json
import pickle
import traceback
from pathlib import Path

import yaml

from src.paths import DATA_DIR, OUTPUT_DIR
from src.stages._io import (
    append_errors_entry,
    get_data_dir,
    get_output_base,
    load_upstream,
    log_line,
    new_run_log,
    read_manifest,
    resolve_context,
    update_checkpoint_manifest,
    write_manifest_atomic,
)
from src.stages.base import Stage
from src.stages.registry import register_stage


def check_quality_gates(metrics: dict, gates: dict) -> dict:
    """Compare placeholder/real metrics against numeric quality_gates.

    Returns {"passed": bool, "failures": [...], "placeholders": bool}.
    Never raises on bad config: non-numeric gate bounds are reported as failures.
    Placeholder metrics (all zeros) pass only when gate min is 0.0 (uncalibrated).
    """
    failures = []
    placeholders = True
    for model, per_metric in gates.items():
        if not isinstance(per_metric, dict):
            failures.append(f"{model}: gate block is not a dict")
            continue
        model_metrics = metrics.get(model, {})
        if not isinstance(model_metrics, dict):
            failures.append(f"{model}: missing metrics")
            continue
        for metric, bounds in per_metric.items():
            if not isinstance(bounds, dict):
                failures.append(f"{model}.{metric}: bounds not a dict")
                continue
            lo, hi = bounds.get("min"), bounds.get("max")
            val = model_metrics.get(metric)
            if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                failures.append(f"{model}.{metric}: non-numeric gate bounds min={lo!r} max={hi!r}")
                continue
            if not isinstance(val, (int, float)):
                failures.append(f"{model}.{metric}: non-numeric metric value {val!r}")
                continue
            if val != 0.0:
                placeholders = False
            if not (lo <= val <= hi):
                failures.append(f"{model}.{metric}: {val} outside [{lo}, {hi}]")
    # Detect all-zero placeholders across gated models
    if placeholders:
        gated_vals = [
            metrics.get(m, {}).get(met)
            for m, per in gates.items()
            if isinstance(per, dict)
            for met in per
        ]
        if gated_vals and not all(v == 0.0 for v in gated_vals if isinstance(v, (int, float))):
            placeholders = False
    return {"passed": not failures, "failures": failures, "placeholders": placeholders}


# Module default; run() overrides from config training.compat (keeps builders
# usable without run context, e.g. unit checks).
_COMPAT_PENALTY_TO_L1 = True


def _load_config():
    cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sample_space(search_space: dict, rng, log):
    """Draw one hyperparameter dict from the declarative search_space."""
    import math

    params = {}
    for name, spec in (search_space or {}).items():
        if isinstance(spec, dict) and spec.get("type") == "loguniform":
            lo, hi = float(spec["low"]), float(spec["high"])
            params[name] = float(math.exp(rng.uniform(math.log(lo), math.log(hi))))
        elif isinstance(spec, list):
            params[name] = spec[int(rng.integers(0, len(spec)))]
        else:
            log(f"WARN unknown search_space spec for {name}={spec!r}, using as-is")
            params[name] = spec
    # Cast numpy scalars to plain python for JSON manifests (numpy is a hard
    # dependency of this stage, imported in run(); no guard needed here).
    import numpy as np

    clean = {}
    for k, v in params.items():
        if isinstance(v, np.generic):
            v = v.item()
        clean[k] = v
    return clean


def _build_estimator(model_name: str, params: dict, seed: int):
    """Build the sklearn-compatible estimator for a model name."""
    if model_name == "logreg":
        from sklearn.linear_model import LogisticRegression

        import inspect

        penalty = params.get("penalty", "l2")
        # sklearn>=1.8 deprecates penalty= in favor of l1_ratio (saga ignores
        # penalty=l1 otherwise, hurting convergence and scores). Gated by
        # config training.compat.sklearn_penalty_to_l1_ratio; version-detected.
        use_ratio = _COMPAT_PENALTY_TO_L1 and "l1_ratio" in inspect.signature(LogisticRegression).parameters
        kwargs = {
            "C": float(params.get("C", 1.0)),
            "solver": "saga",
            "class_weight": "balanced",
            "max_iter": 5000,
            "random_state": seed,
        }
        if use_ratio:
            kwargs["l1_ratio"] = 1.0 if penalty == "l1" else 0.0
        else:
            kwargs["penalty"] = penalty
        return LogisticRegression(**kwargs)
    if model_name == "svm_linear":
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.svm import LinearSVC

        base = LinearSVC(
            C=float(params.get("C", 1.0)),
            class_weight="balanced",
            max_iter=5000,
            random_state=seed,
        )
        return CalibratedClassifierCV(base, method="sigmoid", cv=3)
    if model_name == "xgboost":
        from xgboost import XGBClassifier

        n_pos = params.get("_n_pos", 1)
        n_neg = params.get("_n_neg", 1)
        return XGBClassifier(
            n_estimators=int(params.get("n_estimators", 100)),
            learning_rate=float(params.get("learning_rate", 0.1)),
            max_depth=int(params.get("max_depth", 6)),
            scale_pos_weight=n_neg / max(n_pos, 1),
            random_state=seed,
            n_jobs=1,
            eval_metric="logloss",
        )
    if model_name in ("lightgbm", "lightgbm_optuna"):
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            n_estimators=int(params.get("n_estimators", 100)),
            learning_rate=float(params.get("learning_rate", 0.1)),
            num_leaves=int(params.get("num_leaves", 31)),
            class_weight="balanced",
            random_state=seed,
            n_jobs=1,
            verbose=-1,
        )
    if model_name == "catboost":
        from catboost import CatBoostClassifier

        return CatBoostClassifier(
            iterations=int(params.get("iterations", 100)),
            learning_rate=float(params.get("learning_rate", 0.1)),
            depth=int(params.get("depth", 6)),
            auto_class_weights="Balanced",
            random_seed=seed,
            verbose=False,
            thread_count=1,
        )
    raise ValueError(f"unknown model '{model_name}' (no estimator mapping)")


def _estimator_for(model_name: str, params: dict, seed: int, y_fit):
    """Build an estimator, injecting class-balance counts for xgboost."""
    import numpy as np

    owned = dict(params)
    if model_name == "xgboost":
        yy = np.asarray(y_fit).ravel()
        owned["_n_pos"] = int((yy == 1).sum())
        owned["_n_neg"] = int((yy == 0).sum())
    return _build_estimator(model_name, owned, seed)


def _fit_predict_proba(estimator, X_train, y_train, X_eval):
    import numpy as np
    import pandas as pd

    if not isinstance(X_train, pd.DataFrame):
        X_train = pd.DataFrame(X_train)
    if not isinstance(X_eval, pd.DataFrame):
        X_eval = pd.DataFrame(X_eval)
    estimator.fit(X_train, np.asarray(y_train).ravel())
    if hasattr(estimator, "predict_proba"):
        return np.asarray(estimator.predict_proba(X_eval))[:, 1]
    scores = np.asarray(estimator.decision_function(X_eval), dtype=float)
    lo, hi = scores.min(), scores.max()
    if hi <= lo:
        return np.full(scores.shape, 0.5)
    return (scores - lo) / (hi - lo)


def _metrics_at_threshold(y_true, y_proba, tau: float) -> dict:
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

    import numpy as np

    y_true = np.asarray(y_true).ravel()
    y_proba = np.asarray(y_proba).ravel()
    y_pred = (y_proba >= tau).astype(int)
    out = {
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_binary": float(f1_score(y_true, y_pred, average="binary", zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "tau": float(tau),
        "n": int(len(y_true)),
        "prevalence": float(y_true.mean()) if len(y_true) else 0.0,
    }
    try:
        out["roc_auc"] = float(roc_auc_score(y_true, y_proba))
    except ValueError as e:
        out["roc_auc"] = 0.0
        out["roc_auc_error"] = str(e)[:200]
    return out


def _resolve_ensemble_options(training_cfg: dict) -> dict:
    """Resolve ensemble switches from training config with safe defaults.

    Reads training.ensembles when present, otherwise both ensembles stay
    enabled with a ranked shortlist. All sizes come from config, never from
    fixed dataset counts.
    """
    ensembles_cfg = (training_cfg or {}).get("ensembles")
    if not isinstance(ensembles_cfg, dict):
        ensembles_cfg = {}
    voting_enabled = bool(ensembles_cfg.get("voting", True))
    stacking_enabled = bool(ensembles_cfg.get("stacking", True))
    raw_top_n = ensembles_cfg.get("select_top_n", 5)
    try:
        select_top_n = int(raw_top_n)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"training.ensembles.select_top_n={raw_top_n!r} must be a positive int") from exc
    if select_top_n <= 0:
        raise ValueError(f"training.ensembles.select_top_n={select_top_n!r} must be positive")
    raw_exclude = ensembles_cfg.get("exclude_from_voting", ["svm_linear"])
    if raw_exclude is None:
        raw_exclude = []
    if isinstance(raw_exclude, str):
        exclude_names = [raw_exclude]
    else:
        try:
            exclude_names = [str(item) for item in list(raw_exclude)]
        except TypeError as exc:
            raise ValueError(f"training.ensembles.exclude_from_voting={raw_exclude!r} must be a list") from exc
    return {
        "voting_enabled": voting_enabled,
        "stacking_enabled": stacking_enabled,
        "select_top_n": select_top_n,
        "exclude_names": exclude_names,
    }


def _select_ensemble_members(output_dir, exclude_names, select_top_n, log_path):
    """Collect ranked base candidates with valid manifests and params.

    Scans train_<member>_manifest.json files, keeps entries whose best_params
    is a non-empty dict, drops placeholders and excluded names, ranks by
    best_search_f1, and returns the top slice. Uses whatever is available
    when fewer exist; raises with a rerun hint when none qualify.
    """
    skipped = {"dummy", "voting", "stacking"}
    excluded = set(exclude_names or [])
    out = Path(output_dir)
    found = []
    for manifest_path in sorted(out.glob("train_*_manifest.json")):
        if manifest_path.name == "train_manifest.json":
            continue
        member = manifest_path.name[len("train_") : -len("_manifest.json")]
        if member in skipped or member in excluded:
            continue
        manifest = read_manifest(output_dir, manifest_path.name)
        if not isinstance(manifest, dict):
            continue
        best_params = manifest.get("best_params")
        if not isinstance(best_params, dict) or not best_params:
            continue
        raw_score = manifest.get("best_search_f1", -1.0)
        try:
            score = float(raw_score)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"candidate '{member}' has non-numeric best_search_f1={raw_score!r}") from exc
        found.append({"name": member, "best_params": dict(best_params), "best_search_f1": score})
    found.sort(key=lambda item: item["best_search_f1"], reverse=True)
    ranked = found[: max(int(select_top_n), 0)]
    if log_path is not None:
        names = [item["name"] for item in ranked]
        log_line(log_path, f"ensemble candidates ranked={len(found)} selected={names}")
    if not ranked:
        raise RuntimeError(
            "no base candidates with valid train_<model>_manifest.json and best_params: "
            "run base models first (main.py --stage train)"
        )
    return ranked


def _proba_from_fitted(estimator, x_eval):
    """Return positive-class proba from a fitted estimator without refit."""
    import numpy as np
    import pandas as pd

    if not isinstance(x_eval, pd.DataFrame):
        x_eval = pd.DataFrame(x_eval)
    if hasattr(estimator, "predict_proba"):
        return np.asarray(estimator.predict_proba(x_eval))[:, 1]
    scores = np.asarray(estimator.decision_function(x_eval), dtype=float)
    low, high = float(scores.min()), float(scores.max())
    if high <= low:
        return np.full(scores.shape, 0.5, dtype=float)
    return (scores - low) / (high - low)


def _member_proba_matrix(output_dir, member_names, x_eval):
    """Load fitted base pickles and stack their probas column-wise."""
    import pickle

    import numpy as np

    cols = []
    for member in member_names:
        pkl_path = Path(output_dir) / f"train_{member}.pkl"
        if not pkl_path.exists():
            raise FileNotFoundError(
                f"fitted pickle missing for candidate '{member}': {pkl_path.as_posix()} "
                "(run base models first)"
            )
        try:
            with open(pkl_path, "rb") as handle:
                estimator = pickle.load(handle)
        except (OSError, pickle.PickleError, ValueError) as exc:
            tb = traceback.format_exc()
            raise RuntimeError(f"cannot load fitted pickle for '{member}': {exc}\n{tb}") from exc
        proba = _proba_from_fitted(estimator, x_eval)
        cols.append(np.asarray(proba, dtype=float).ravel())
    if not cols:
        raise RuntimeError("no members to score: candidate list is empty (run base models first)")
    return np.column_stack(cols)


def _write_ensemble_proba_csv(split_block, y_true, y_proba, tau_star, csv_path):
    """Write anio,y_true,y_proba,y_pred CSV atomically via tmp plus rename."""
    import numpy as np
    import pandas as pd

    frame = split_block[["anio"]].copy()
    frame["y_true"] = np.asarray(y_true).ravel().astype(int)
    frame["y_proba"] = np.asarray(y_proba, dtype=float).ravel()
    frame["y_pred"] = (frame["y_proba"] >= float(tau_star)).astype(int)
    tmp_path = csv_path.with_suffix(".tmp")
    frame.to_csv(tmp_path, index=False, encoding="utf-8")
    tmp_path.replace(csv_path)
    return csv_path


def _tune_tau_on_calib(y_true, y_proba, taus):
    """Select the threshold maximizing macro F1 over the calibration grid."""
    import numpy as np
    from sklearn.metrics import f1_score

    y_true = np.asarray(y_true).ravel()
    y_proba = np.asarray(y_proba).ravel()
    scored = []
    for tau in taus:
        tau_f = float(tau)
        pred = (y_proba >= tau_f).astype(int)
        score = float(f1_score(y_true, pred, average="macro", zero_division=0))
        scored.append((tau_f, score))
    if not scored:
        raise RuntimeError("empty calibration grid: check calibration.grid in config")
    return max(scored, key=lambda item: item[1])[0]


def _run_voting_ensemble(
    output_dir,
    preds_dir,
    member_infos,
    x_splits,
    y_splits,
    split_blocks,
    taus,
    seed_global,
    seed_sampler,
    versions,
    log_path,
    force_recompute,
):
    """Build the soft-average voting ensemble from fitted base pickles.

    Averages member probas on calibration, test, and external splits, tunes
    one shared threshold on calibration, and persists the manifest plus both
    proba CSVs. Honors resume and force semantics like base models.
    """
    import numpy as np

    member_names = [info["name"] for info in member_infos]
    done = None if force_recompute else read_manifest(output_dir, "train_voting_manifest.json")
    if (
        isinstance(done, dict)
        and isinstance(done.get("tau_star"), (int, float))
        and isinstance(done.get("metrics_test"), dict)
        and isinstance(done.get("params"), dict)
    ):
        log_line(log_path, "resume skip 'voting' (per-model manifest valid)")
        print("[progress] voting skipped (manifest valid, resume)", flush=True)
        summary = done.get("summary", {}) if isinstance(done.get("summary"), dict) else {}
        metrics_entry = {k: done.get("metrics_test", {}).get(k, 0.0) for k in ("f1_macro", "roc_auc", "accuracy")}
        return summary, metrics_entry
    if force_recompute:
        log_line(log_path, "force recompute 'voting' (STAGE_FORCE=1, ignoring per-model manifest)")
    print(f"[progress] voting members={member_names} averaging probas", flush=True)
    log_line(log_path, f"voting members={member_names}")
    proba_calib_matrix = _member_proba_matrix(output_dir, member_names, x_splits["calib"])
    voting_calib = np.asarray(proba_calib_matrix.mean(axis=1), dtype=float).ravel()
    tau_star = _tune_tau_on_calib(y_splits["calib"], voting_calib, taus)
    m_valid = _metrics_at_threshold(y_splits["calib"], voting_calib, tau_star)
    print(f"[progress] voting calibrated tau={tau_star:.2f} f1_calib={m_valid['f1_macro']:.4f}", flush=True)
    log_line(log_path, f"voting calibrated tau={tau_star:.2f} f1_calib={m_valid['f1_macro']:.4f}")
    proba_test_matrix = _member_proba_matrix(output_dir, member_names, x_splits["test"])
    voting_test = np.asarray(proba_test_matrix.mean(axis=1), dtype=float).ravel()
    m_test = _metrics_at_threshold(y_splits["test"], voting_test, tau_star)
    proba_ext_matrix = _member_proba_matrix(output_dir, member_names, x_splits["external"])
    voting_ext = np.asarray(proba_ext_matrix.mean(axis=1), dtype=float).ravel()
    m_ext = _metrics_at_threshold(y_splits["external"], voting_ext, tau_star)
    _write_ensemble_proba_csv(
        split_blocks["test"], y_splits["test"], voting_test, tau_star, preds_dir / "train_voting_test_proba.csv"
    )
    _write_ensemble_proba_csv(
        split_blocks["external"],
        y_splits["external"],
        voting_ext,
        tau_star,
        preds_dir / "train_voting_external_proba.csv",
    )
    summary = {"tau_star": tau_star, "f1_test": m_test["f1_macro"], "roc_auc_test": m_test["roc_auc"]}
    manifest = {
        "stage": "train",
        "model": "voting",
        "params": {"method": "soft_average", "members": member_names},
        "tau_star": tau_star,
        "metrics_valid": m_valid,
        "metrics_test": m_test,
        "metrics_external": m_ext,
        "seeds": {"global": seed_global, "sampler": seed_sampler},
        "versions": versions,
        "summary": summary,
    }
    write_manifest_atomic(output_dir, "train_voting_manifest.json", manifest)
    update_checkpoint_manifest("voting", "done", {"tau_star": tau_star, "f1_test": m_test["f1_macro"]})
    log_line(log_path, f"voting done tau={tau_star:.2f} f1_test={m_test['f1_macro']:.4f} roc_test={m_test['roc_auc']:.4f}")
    print(f"[progress] voting done tau={tau_star:.2f} f1_test={m_test['f1_macro']:.4f} roc_test={m_test['roc_auc']:.4f}", flush=True)
    metrics_entry = {k: m_test[k] for k in ("f1_macro", "roc_auc", "accuracy")}
    return summary, metrics_entry


def _run_stacking_ensemble(
    output_dir,
    preds_dir,
    member_infos,
    x_splits,
    y_splits,
    split_blocks,
    taus,
    seed_global,
    seed_sampler,
    versions,
    log_path,
    force_recompute,
):
    """Build the temporal stacking ensemble with an expanding-fold meta model.

    Fits each candidate on expanding chronological folds of the full training
    block to collect out-of-fold probas, trains a balanced logistic meta
    model on those probas, then scores calibration, test, and external splits
    through the fitted base pickles plus the meta model. One checkpoint per
    fold keeps long runs resumable at the log level.
    """
    import pickle

    import numpy as np
    from sklearn.linear_model import LogisticRegression

    member_names = [info["name"] for info in member_infos]
    done = None if force_recompute else read_manifest(output_dir, "train_stacking_manifest.json")
    if (
        isinstance(done, dict)
        and isinstance(done.get("tau_star"), (int, float))
        and isinstance(done.get("metrics_test"), dict)
        and isinstance(done.get("params"), dict)
    ):
        log_line(log_path, "resume skip 'stacking' (per-model manifest valid)")
        print("[progress] stacking skipped (manifest valid, resume)", flush=True)
        summary = done.get("summary", {}) if isinstance(done.get("summary"), dict) else {}
        metrics_entry = {k: done.get("metrics_test", {}).get(k, 0.0) for k in ("f1_macro", "roc_auc", "accuracy")}
        return summary, metrics_entry
    if force_recompute:
        log_line(log_path, "force recompute 'stacking' (STAGE_FORCE=1, ignoring per-model manifest)")
    # Expanding year-boundary folds over the training block (never equal row
    # chunks): fold k fits on years[:k] and validates on years[k]. Fold count
    # derives from the block itself (5 years -> 4 folds), nothing hardcoded.
    block_years = sorted(int(v) for v in split_blocks["train_full"]["anio"].unique().tolist())
    year_folds = [(block_years[:k], block_years[k]) for k in range(1, len(block_years))]
    if not year_folds:
        raise RuntimeError("stacking needs >=2 distinct years in the training block for out-of-fold splits")
    n_oof_splits = len(year_folds)
    print(f"[progress] stacking members={member_names} oof splits={n_oof_splits} starting", flush=True)
    log_line(log_path, f"stacking members={member_names} oof splits={n_oof_splits}")
    anio_vals = split_blocks["train_full"]["anio"].to_numpy()
    order = np.argsort(anio_vals, kind="stable")
    x_full = x_splits["train_full"].iloc[order]
    y_full = np.asarray(y_splits["train_full"]).ravel()[order]
    n_rows = int(len(y_full))
    n_members = len(member_names)
    oof_matrix = np.zeros((n_rows, n_members), dtype=float)
    validated_mask = np.zeros(n_rows, dtype=bool)
    splitter = year_folds
    for fold_number, (fold_train_years, fold_valid_year) in enumerate(splitter, start=1):
        fold_mask_train = np.isin(anio_vals[order], fold_train_years)
        fold_mask_valid = anio_vals[order] == fold_valid_year
        train_idx = np.flatnonzero(fold_mask_train)
        valid_idx = np.flatnonzero(fold_mask_valid)
        if len(train_idx) == 0 or len(valid_idx) == 0:
            raise RuntimeError(f"stacking fold {fold_number} empty: train_years={fold_train_years} valid_year={fold_valid_year}")
        print(f"[progress] stacking fold {fold_number}/{n_oof_splits} train_years={fold_train_years} valid_year={fold_valid_year} fitting {n_members} candidates", flush=True)
        x_fold_train = x_full.iloc[train_idx]
        y_fold_train = y_full[train_idx]
        x_fold_valid = x_full.iloc[valid_idx]
        for col, info in enumerate(member_infos):
            fold_est = _estimator_for(info["name"], info["best_params"], seed_global, y_fold_train)
            proba_valid = _fit_predict_proba(fold_est, x_fold_train, y_fold_train, x_fold_valid)
            oof_matrix[valid_idx, col] = np.asarray(proba_valid, dtype=float).ravel()
        validated_mask[valid_idx] = True
        update_checkpoint_manifest(
            "stacking",
            f"fold_{fold_number}",
            {"members": member_names, "fold": fold_number, "n_valid": int(len(valid_idx))},
        )
        log_line(log_path, f"stacking checkpoint fold_{fold_number} n_valid={len(valid_idx)}")
        print(f"[progress] stacking fold {fold_number}/{n_oof_splits} done", flush=True)
    if not bool(validated_mask.any()):
        raise RuntimeError("stacking out-of-fold produced no validation rows: check the training block size")
    x_meta = oof_matrix[validated_mask]
    y_meta = y_full[validated_mask]
    meta = LogisticRegression(solver="saga", class_weight="balanced", max_iter=5000, random_state=seed_global)
    solver_used = "saga"
    try:
        meta.fit(x_meta, y_meta)
    except Exception as exc_saga:
        tb_saga = traceback.format_exc()
        log_line(log_path, f"stacking meta saga failed, retrying lbfgs ({exc_saga})\n{tb_saga[-2000:]}")
        print("[progress] stacking meta saga failed, retrying lbfgs", flush=True)
        try:
            meta = LogisticRegression(solver="lbfgs", class_weight="balanced", max_iter=5000, random_state=seed_global)
            meta.fit(x_meta, y_meta)
            solver_used = "lbfgs"
        except Exception as exc_lbfgs:
            tb_lbfgs = traceback.format_exc()
            log_line(log_path, f"[fail] stacking meta lbfgs also failed ({exc_lbfgs})\n{tb_lbfgs}")
            raise
    print(f"[progress] stacking meta fitted solver={solver_used} rows={len(y_meta)}", flush=True)
    log_line(log_path, f"stacking meta fitted solver={solver_used} rows={len(y_meta)}")
    meta_path = Path(output_dir) / "train_stacking.pkl"
    tmp_meta = meta_path.with_suffix(".tmp")
    with open(tmp_meta, "wb") as handle:
        pickle.dump({"meta": meta, "members": member_names, "solver": solver_used}, handle)
    tmp_meta.replace(meta_path)

    def _stacked_proba(x_eval):
        base_matrix = _member_proba_matrix(output_dir, member_names, x_eval)
        return np.asarray(meta.predict_proba(base_matrix))[:, 1]

    print("[progress] stacking scoring calibration/test/external splits", flush=True)
    proba_calib = np.asarray(_stacked_proba(x_splits["calib"]), dtype=float).ravel()
    tau_star = _tune_tau_on_calib(y_splits["calib"], proba_calib, taus)
    m_valid = _metrics_at_threshold(y_splits["calib"], proba_calib, tau_star)
    print(f"[progress] stacking calibrated tau={tau_star:.2f} f1_calib={m_valid['f1_macro']:.4f}", flush=True)
    proba_test = np.asarray(_stacked_proba(x_splits["test"]), dtype=float).ravel()
    m_test = _metrics_at_threshold(y_splits["test"], proba_test, tau_star)
    proba_ext = np.asarray(_stacked_proba(x_splits["external"]), dtype=float).ravel()
    m_ext = _metrics_at_threshold(y_splits["external"], proba_ext, tau_star)
    _write_ensemble_proba_csv(
        split_blocks["test"], y_splits["test"], proba_test, tau_star, preds_dir / "train_stacking_test_proba.csv"
    )
    _write_ensemble_proba_csv(
        split_blocks["external"],
        y_splits["external"],
        proba_ext,
        tau_star,
        preds_dir / "train_stacking_external_proba.csv",
    )
    summary = {"tau_star": tau_star, "f1_test": m_test["f1_macro"], "roc_auc_test": m_test["roc_auc"]}
    manifest = {
        "stage": "train",
        "model": "stacking",
        "params": {
            "method": "temporal_oof_logreg",
            "members": member_names,
            "n_oof_splits": n_oof_splits,
            "meta": {"solver": solver_used, "class_weight": "balanced"},
        },
        "tau_star": tau_star,
        "metrics_valid": m_valid,
        "metrics_test": m_test,
        "metrics_external": m_ext,
        "seeds": {"global": seed_global, "sampler": seed_sampler},
        "versions": versions,
        "summary": summary,
    }
    write_manifest_atomic(output_dir, "train_stacking_manifest.json", manifest)
    update_checkpoint_manifest("stacking", "done", {"tau_star": tau_star, "f1_test": m_test["f1_macro"]})
    log_line(log_path, f"stacking done tau={tau_star:.2f} f1_test={m_test['f1_macro']:.4f} roc_test={m_test['roc_auc']:.4f}")
    print(f"[progress] stacking done tau={tau_star:.2f} f1_test={m_test['f1_macro']:.4f} roc_test={m_test['roc_auc']:.4f}", flush=True)
    metrics_entry = {k: m_test[k] for k in ("f1_macro", "roc_auc", "accuracy")}
    return summary, metrics_entry


@register_stage
class TrainStage(Stage):
    name = "train"
    seccion_paper = "4 Results"
    output_dir = Path(OUTPUT_DIR, "models").as_posix()
    manifest_filename = "train_manifest.json"

    def is_done(self) -> bool:
        """Done only when the global manifest is valid AND every active model has one."""
        if read_manifest(self.output_dir, self.manifest_filename) is None:
            return False
        try:
            cfg = _load_config()
            active = ((cfg.get("training") or {}).get("active_models") or [])
            for model in active:
                if read_manifest(self.output_dir, f"train_{model}_manifest.json") is None:
                    return False
        except OSError:
            return False
        return True

    def run(self) -> dict:
        log_path = new_run_log(self.name)
        ctx = resolve_context()
        log_line(log_path, f"context={ctx['context']} DATA_DIR={ctx['data_dir']} OUTPUT_DIR={ctx['output_dir']}")
        try:
            import numpy as np
            import pandas as pd

            from sklearn.metrics import f1_score

            cfg = _load_config()
            data_cfg = cfg["data"]
            models_cfg = cfg["models"]
            calib_cfg = cfg["calibration"]
            gates = cfg.get("quality_gates", {})
            training_cfg = cfg.get("training") or {}
            active = list(training_cfg.get("active_models") or [])
            if not active:
                raise ValueError("training.active_models is empty: nothing to train")
            seeds = training_cfg.get("seeds") or {}
            seed_global = int(seeds.get("global", 42))
            seed_sampler = int(seeds.get("sampler", 42))
            ckpt_cfg = training_cfg.get("checkpoint") or {}
            cadence = int(ckpt_cfg.get("cadence_trials", 5))
            enc_cfg = training_cfg.get("encoding") or {}
            compat_cfg = training_cfg.get("compat") or {}
            progress_cfg = training_cfg.get("progress") or {}
            scale_method = enc_cfg.get("scale", "standard_scaler_train_only")
            print_every_trial = bool(progress_cfg.get("print_every_trial", True))
            global _COMPAT_PENALTY_TO_L1
            _COMPAT_PENALTY_TO_L1 = bool(compat_cfg.get("sklearn_penalty_to_l1_ratio", True))

            out_dir = Path(self.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            preds_dir = get_output_base() / "predictions"
            preds_dir.mkdir(parents=True, exist_ok=True)
            (get_output_base() / "figures").mkdir(parents=True, exist_ok=True)

            # Gold matrices from split: the single source of truth for X/y.
            # Encoding + target were built upstream (selection/split); train
            # only scales (training.encoding.scale) and learns.
            try:
                import pyarrow  # noqa: F401 — gold parquet IO
            except ImportError:
                raise RuntimeError("pyarrow is required for gold matrices: pip install -r requirements.txt")
            split_thresholds = load_upstream("split", key="thresholds")
            split_gold = load_upstream("split", key="gold_paths")
            split_features = load_upstream("split", key="feature_list")
            if not isinstance(split_thresholds, dict) or not isinstance(split_gold, dict):
                raise RuntimeError("split manifest lacks thresholds/gold_paths — run split first (main.py --stage split)")
            if not isinstance(split_features, list) or not split_features:
                raise RuntimeError("split manifest lacks feature_list — run split first (main.py --stage split)")
            q75_s = float(split_thresholds.get("q75_s", float("nan")))
            q25_t = float(split_thresholds.get("q25_t", float("nan")))
            feature_list = [str(c) for c in split_features]
            X, y, yframes = {}, {}, {}
            for block_name in ("search_train", "search_valid", "train_full", "calib", "test", "external"):
                x_path = Path(str(split_gold.get(f"X_{block_name}", "")))
                y_path = Path(str(split_gold.get(f"y_{block_name}", "")))
                if not x_path.exists() or not y_path.exists():
                    raise RuntimeError(f"gold matrices missing for '{block_name}' — re-run split first (main.py --stage split)")
                x_mat = pd.read_parquet(x_path)
                y_frame = pd.read_parquet(y_path)
                if list(x_mat.columns) != feature_list:
                    raise RuntimeError(f"gold columns drifted for '{block_name}' — re-run split first (main.py --stage split)")
                if y_frame.shape[0] != x_mat.shape[0]:
                    raise RuntimeError(f"gold X/y row mismatch for '{block_name}' — re-run split first")
                target_col = str(data_cfg.get("target_col", "riesgo_congestion"))
                if target_col not in y_frame.columns or "anio" not in y_frame.columns:
                    raise RuntimeError(f"gold y file lacks columns for '{block_name}' — re-run split first")
                X[block_name] = x_mat.astype(float)
                yframes[block_name] = y_frame
                y[block_name] = y_frame[target_col].to_numpy(dtype=int)
            train_prev = float(y["train_full"].mean())
            log_line(log_path, f"gold loaded features={len(feature_list)} blocks=" + ", ".join(f"{k}:{len(v)}" for k, v in y.items()))
            log_line(log_path, f"target P75/P25 from split q75_s={q75_s:.4f} q25_t={q25_t:.4f} train_prevalence={train_prev:.4f}")
            print(f"[progress] gold loaded features={len(feature_list)} target prevalence={train_prev:.4f}", flush=True)
            # Standardize per config training.encoding.scale (fit block is
            # search_train only — leakage-safe). saga/LBFGS converge poorly on
            # raw frequency features (see ConvergenceWarning).
            import pandas as pd

            scaler = None
            if scale_method == "standard_scaler_train_only":
                from sklearn.preprocessing import StandardScaler

                scaler = StandardScaler()
                scaler.fit(X["search_train"])
                X = {
                    k: pd.DataFrame(scaler.transform(mat), index=mat.index, columns=mat.columns)
                    for k, mat in X.items()
                }
                with open(Path(self.output_dir) / "train_scaler.pkl", "wb") as f:
                    pickle.dump(scaler, f)
            elif scale_method != "none":
                raise ValueError(f"training.encoding.scale={scale_method!r} unsupported (standard_scaler_train_only|none)")
            n_features = int(X["search_train"].shape[1])
            log_line(log_path, f"gold features={n_features} (selected+encoded upstream, scaled here)")
            print(f"[progress] gold features={n_features} (scaler fit on search_train only)", flush=True)

            # Calibration grid from config (maximize F1 on calib year).
            grid = calib_cfg.get("grid", [0.05, 0.95, 91])
            lo_g, hi_g, n_g = float(grid[0]), float(grid[1]), int(grid[2])
            taus = np.linspace(lo_g, hi_g, n_g)

            try:
                import sklearn

                versions = {"sklearn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__}
            except ImportError:
                versions = {}
            for lib in ("optuna", "lightgbm", "xgboost", "catboost"):
                try:
                    mod = __import__(lib)
                    versions[lib] = getattr(mod, "__version__", "installed")
                except ImportError:
                    versions[lib] = "missing"

            per_model_summary = {}
            metrics_test = {}
            ensemble_requested = []
            for model_name in active:
                if model_name == "dummy":
                    log_line(log_path, "skip placeholder entry 'dummy' (no direct fit)")
                    continue
                if model_name in ("voting", "stacking"):
                    log_line(log_path, f"defer ensemble '{model_name}' until base models finish")
                    if model_name not in ensemble_requested:
                        ensemble_requested.append(model_name)
                    continue
                mc = models_cfg.get(model_name)
                if not isinstance(mc, dict):
                    raise ValueError(f"models.{model_name} missing in config.yaml")
                optimizer = mc.get("optimizer")
                trials_total = int(mc.get("trials", 30))
                space = mc.get("search_space", {})

                # Resume: finished per-model manifest means skip, unless the
                # orchestrator propagates --force via STAGE_FORCE (code-fix
                # re-runs must recompute, never silently reuse old models).
                import os

                force_models = os.environ.get("STAGE_FORCE") == "1"
                done = None if force_models else read_manifest(self.output_dir, f"train_{model_name}_manifest.json")
                if force_models:
                    log_line(log_path, f"force recompute '{model_name}' (STAGE_FORCE=1, ignoring per-model manifest)")
                if done and isinstance(done.get("best_params"), dict):
                    log_line(log_path, f"resume skip '{model_name}' (per-model manifest valid)")
                    per_model_summary[model_name] = done.get("summary", {})
                    tm = done.get("metrics_test", {})
                    metrics_test[model_name] = {k: tm.get(k, 0.0) for k in ("f1_macro", "roc_auc", "accuracy")}
                    continue

                rng = np.random.default_rng(seed_sampler + abs(hash(model_name)) % 100000)
                X_tr, y_tr = X["search_train"], y["search_train"]
                X_va, y_va = X["search_valid"], y["search_valid"]
                print(f"[progress] model {model_name} ({optimizer}, {trials_total} trials) starting", flush=True)
                if optimizer == "optuna_tpe":
                    try:
                        import optuna
                    except ImportError:
                        raise RuntimeError("optuna is required for optimizer optuna_tpe: pip install -r requirements.txt")
                    ckpt_dir = get_output_base() / "checkpoints"
                    ckpt_dir.mkdir(parents=True, exist_ok=True)
                    db_path = ckpt_dir / f"optuna_{model_name}.db"
                    if force_models and db_path.exists():
                        # Fresh search under --force: stale studies would report
                        # 0 remaining trials and silently reuse old best params.
                        db_path.unlink()
                        log_line(log_path, f"force cleared optuna storage for '{model_name}'")
                    storage = optuna.storages.RDBStorage(url=f"sqlite:///{db_path.as_posix()}")
                    study = optuna.create_study(
                        study_name=f"{model_name}_search",
                        storage=storage,
                        load_if_exists=True,
                        direction="maximize",
                        sampler=optuna.samplers.TPESampler(seed=seed_sampler),
                    )
                    done_n = len(study.trials)

                    def _objective(trial):
                        trial_params = {}
                        for pname, spec in (space or {}).items():
                            if isinstance(spec, dict) and spec.get("type") == "loguniform":
                                import math

                                trial_params[pname] = trial.suggest_float(pname, float(spec["low"]), float(spec["high"]), log=True)
                            elif isinstance(spec, list):
                                trial_params[pname] = trial.suggest_categorical(pname, spec)
                        est = _estimator_for(model_name, trial_params, seed_global, y_tr)
                        proba = _fit_predict_proba(est, X_tr, y_tr, X_va)
                        return float(f1_score(y_va, (proba >= 0.5).astype(int), average="macro", zero_division=0))

                    remaining = max(trials_total - done_n, 0)
                    while remaining > 0:
                        chunk = min(cadence, remaining)
                        study.optimize(_objective, n_trials=chunk)
                        done_n = len(study.trials)
                        remaining = max(trials_total - done_n, 0)
                        update_checkpoint_manifest(model_name, f"trial_{done_n}", {"best_value": float(study.best_value), "trials_done": done_n})
                        log_line(log_path, f"{model_name} checkpoint trial_{done_n} best_f1={study.best_value:.4f}")
                        if print_every_trial:
                            print(f"[progress] {model_name} trial {done_n}/{trials_total} best_f1={study.best_value:.4f}", flush=True)
                    best_params = dict(study.best_params)
                    best_search_f1 = float(study.best_value)
                elif optimizer == "randomized_search":
                    # Deterministic sequence upfront; history file allows resume.
                    seq = [_sample_space(space, rng, lambda m: log_line(log_path, m)) for _ in range(trials_total)]
                    hist_path = Path(self.output_dir) / f"train_{model_name}_trials.json"
                    if force_models and hist_path.exists():
                        # Fresh search under --force: a full history would make
                        # the loop below execute 0 trials and leave best empty.
                        hist_path.unlink()
                        log_line(log_path, f"force cleared trials history for '{model_name}'")
                    history = []
                    if hist_path.exists():
                        try:
                            history = json.loads(hist_path.read_text(encoding="utf-8"))
                            if not isinstance(history, list):
                                history = []
                        except (json.JSONDecodeError, OSError) as e:
                            log_line(log_path, f"WARN corrupt trials history for {model_name}, restarting ({e})")
                            history = []
                    best_params, best_search_f1 = {}, -1.0
                    for i in range(len(history), trials_total):
                        params = seq[i]
                        est = _estimator_for(model_name, params, seed_global, y_tr)
                        proba = _fit_predict_proba(est, X_tr, y_tr, X_va)
                        score = float(f1_score(y_va, (proba >= 0.5).astype(int), average="macro", zero_division=0))
                        history.append({"params": params, "f1_search_valid": score})
                        if score > best_search_f1:
                            best_search_f1, best_params = score, params
                        if (i + 1) % cadence == 0 or (i + 1) == trials_total:
                            tmp = hist_path.with_suffix(".tmp")
                            tmp.write_text(json.dumps(history, indent=2), encoding="utf-8")
                            tmp.replace(hist_path)
                            update_checkpoint_manifest(model_name, f"trial_{i + 1}", {"best_f1": best_search_f1, "trials_done": i + 1})
                            log_line(log_path, f"{model_name} checkpoint trial_{i + 1} best_f1={best_search_f1:.4f}")
                        if print_every_trial:
                            print(f"[progress] {model_name} trial {i + 1}/{trials_total} f1={score:.4f} best={best_search_f1:.4f}", flush=True)
                    if not history:
                        raise RuntimeError(f"search produced no trials for '{model_name}'")
                    # Best always derives from the full history (never empty
                    # defaults): covers both fresh runs and resumed ones.
                    best_entry = max(history, key=lambda h: h.get("f1_search_valid", -1.0))
                    best_params, best_search_f1 = dict(best_entry.get("params", {})), float(best_entry.get("f1_search_valid", -1.0))
                    log_line(log_path, f"{model_name} search complete trials={len(history)} best_f1={best_search_f1:.4f}")
                else:
                    raise ValueError(f"models.{model_name}.optimizer={optimizer!r} unsupported (randomized_search|optuna_tpe)")

                # Refit best on the full training block, calibrate tau on calib year.
                final_est = _estimator_for(model_name, best_params, seed_global, y["train_full"])
                proba_calib = _fit_predict_proba(final_est, X["train_full"], y["train_full"], X["calib"])
                scored = [(float(tau), float(f1_score(y["calib"], (proba_calib >= tau).astype(int), average="macro", zero_division=0))) for tau in taus]
                tau_star = max(scored, key=lambda kv: kv[1])[0]
                m_valid = _metrics_at_threshold(y["calib"], proba_calib, tau_star)
                proba_test = _fit_predict_proba(final_est, X["train_full"], y["train_full"], X["test"])
                m_test = _metrics_at_threshold(y["test"], proba_test, tau_star)
                proba_ext = _fit_predict_proba(final_est, X["train_full"], y["train_full"], X["external"])
                m_ext = _metrics_at_threshold(y["external"], proba_ext, tau_star)

                # Persist model + test/external predictions (auditor-readable, small).
                with open(Path(self.output_dir) / f"train_{model_name}.pkl", "wb") as f:
                    pickle.dump(final_est, f)
                for split_name, proba, yy in (("test", proba_test, y["test"]), ("external", proba_ext, y["external"])):
                    import pandas as pd

                    frame = yframes[split_name][["anio"]].copy()
                    frame["y_true"] = yy
                    frame["y_proba"] = np.asarray(proba, dtype=float)
                    frame["y_pred"] = (frame["y_proba"] >= tau_star).astype(int)
                    frame.to_csv(preds_dir / f"train_{model_name}_{split_name}_proba.csv", index=False, encoding="utf-8")

                model_manifest = {
                    "stage": self.name,
                    "model": model_name,
                    "optimizer": optimizer,
                    "trials": trials_total,
                    "seeds": {"global": seed_global, "sampler": seed_sampler},
                    "versions": versions,
                    "best_params": best_params,
                    "best_search_f1": best_search_f1,
                    "tau_star": tau_star,
                    "metrics_valid": m_valid,
                    "metrics_test": m_test,
                    "metrics_external": m_ext,
                    "n_features": n_features,
                    "feature_cols": list(X["search_train"].columns),
                    "summary": {"tau_star": tau_star, "f1_test": m_test["f1_macro"], "roc_auc_test": m_test["roc_auc"]},
                }
                write_manifest_atomic(self.output_dir, f"train_{model_name}_manifest.json", model_manifest)
                update_checkpoint_manifest(model_name, "done", {"tau_star": tau_star, "f1_test": m_test["f1_macro"]})
                log_line(log_path, f"{model_name} done tau={tau_star:.2f} f1_test={m_test['f1_macro']:.4f} roc_test={m_test['roc_auc']:.4f}")
                print(f"[progress] {model_name} done tau={tau_star:.2f} f1_test={m_test['f1_macro']:.4f} roc_test={m_test['roc_auc']:.4f}", flush=True)
                per_model_summary[model_name] = model_manifest["summary"]
                metrics_test[model_name] = {k: m_test[k] for k in ("f1_macro", "roc_auc", "accuracy")}

            if ensemble_requested:
                import os

                force_ensembles = os.environ.get("STAGE_FORCE") == "1"
                ensemble_opts = _resolve_ensemble_options(training_cfg)
                enabled_map = {
                    "voting": bool(ensemble_opts["voting_enabled"]),
                    "stacking": bool(ensemble_opts["stacking_enabled"]),
                }
                needs_members = any(enabled_map.get(name, False) for name in ensemble_requested)
                member_infos = []
                if needs_members:
                    print(
                        f"[progress] ensembles selecting top {ensemble_opts['select_top_n']} "
                        f"excluding {ensemble_opts['exclude_names']}",
                        flush=True,
                    )
                    member_infos = _select_ensemble_members(
                        self.output_dir,
                        ensemble_opts["exclude_names"],
                        ensemble_opts["select_top_n"],
                        log_path,
                    )
                    print(f"[progress] ensemble members={[m['name'] for m in member_infos]}", flush=True)
                for ensemble_name in ensemble_requested:
                    if not enabled_map.get(ensemble_name, False):
                        log_line(log_path, f"skip ensemble '{ensemble_name}' (training.ensembles.{ensemble_name}=false)")
                        print(f"[progress] {ensemble_name} skipped (ensembles flag false)", flush=True)
                        continue
                    if ensemble_name == "voting":
                        summary, entry = _run_voting_ensemble(
                            self.output_dir,
                            preds_dir,
                            member_infos,
                            X,
                            y,
                            yframes,
                            taus,
                            seed_global,
                            seed_sampler,
                            versions,
                            log_path,
                            force_ensembles,
                        )
                    else:
                        summary, entry = _run_stacking_ensemble(
                            self.output_dir,
                            preds_dir,
                            member_infos,
                            X,
                            y,
                            yframes,
                            taus,
                            seed_global,
                            seed_sampler,
                            versions,
                            log_path,
                            force_ensembles,
                        )
                    per_model_summary[ensemble_name] = summary
                    metrics_test[ensemble_name] = entry

            manifest = {
                "stage": self.name,
                "target": {"primary": (cfg["data"].get("target") or {}).get("primary", "P75/P25"), "q75_s": q75_s, "q25_t": q25_t, "train_prevalence": train_prev},
                "models": list(models_cfg.keys()),
                "active_models": active,
                "seeds": {"global": seed_global, "sampler": seed_sampler},
                "versions": versions,
                "n_features": n_features,
                "metrics": metrics_test,
                "per_model": per_model_summary,
                "calibration": calib_cfg,
                "quality_gates": gates,
                "quality_check": check_quality_gates(metrics_test, gates),
                "note": "real metrics from temporal training; gates calibrate from this run with justification, never lowered to pass",
            }
            if not manifest["quality_check"]["passed"]:
                log_line(log_path, f"gate_fail failures={manifest['quality_check']['failures']}")
                print(f"[warn] quality_gate failures: {manifest['quality_check']['failures']}")
                print("Flow: fail -> diagnostic_log.md -> fix code -> re-run stage -> verify (never lower the gate).")
            elif manifest["quality_check"].get("placeholders"):
                log_line(log_path, "gate passed on placeholder metrics (0.0); calibrate gates after first real run")
                print("[warn] quality_gate passed on placeholder metrics (0.0); calibrate gates after first real run")

            # Aggregate metrics CSV for the auditor (one row per scored model).
            # Rewritten every run from live metrics_test: never stale zeros.
            import csv as _csv

            metrics_csv_tmp = Path(self.output_dir) / "train_metrics.csv.tmp"
            metrics_csv_path = Path(self.output_dir) / "train_metrics.csv"
            with open(metrics_csv_tmp, "w", encoding="utf-8", newline="") as f:
                writer = _csv.DictWriter(f, fieldnames=["model", "f1_macro", "roc_auc", "accuracy"])
                writer.writeheader()
                for model_name in metrics_test:
                    tm = metrics_test[model_name] or {}
                    writer.writerow(
                        {
                            "model": model_name,
                            "f1_macro": tm.get("f1_macro", 0.0),
                            "roc_auc": tm.get("roc_auc", 0.0),
                            "accuracy": tm.get("accuracy", 0.0),
                        }
                    )
            metrics_csv_tmp.replace(metrics_csv_path)
            log_line(log_path, f"[ok] wrote {metrics_csv_path.as_posix()} rows={len(metrics_test)}")

            write_manifest_atomic(self.output_dir, self.manifest_filename, manifest)
            append_errors_entry({"stage": self.name, "status": "ok", "quality_check": manifest["quality_check"]})
            log_line(log_path, "[ok] stage completed")
            print("[progress] stage train summary (test split, frozen tau):", flush=True)
            for model_name in active:
                tm = metrics_test.get(model_name, {})
                print(f"[progress]   {model_name}: f1_macro={tm.get('f1_macro', 0.0):.4f} roc_auc={tm.get('roc_auc', 0.0):.4f} acc={tm.get('accuracy', 0.0):.4f}", flush=True)
            return manifest
        except Exception as e:
            tb = traceback.format_exc()
            log_line(log_path, f"[fail] {e}\n{tb}")
            append_errors_entry({"stage": self.name, "status": "fail", "error": str(e)[:500], "traceback": tb[-4000:]})
            print(f"[error] stage '{self.name}' failed: {e} — see {log_path} and OUTPUT_DIR/logs/errors.json")
            raise
