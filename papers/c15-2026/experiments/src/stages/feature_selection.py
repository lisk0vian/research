# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Feature Selection Stage — 6 methods with consensus vote over encoded features.

Method (declared in config.yaml, never fixed counts):
- Candidates are processed columns minus data.exclude_cols. The proxy target
  is built in-memory via _io.build_target (same thresholds as train) and is
  never a feature.
- Order: leakage/exclusions first, then the Pearson filter on numerics, then
  the Cramer V filter on categoricals (both fit on feature_selection_years).
  Each over-threshold pair keeps the member with higher MI vs the fit target
  (tie_break target_mi_train, earlier column wins exact ties).
- Deterministic encoding fit on train_full (split.train_years): categoricals
  with train nunique <= encoding.one_hot_max_cardinality go one-hot, the rest
  go frequency. split.py mirrors this rule exactly.
- Each of the 6 methods votes its top max(10, n_encoded // 3) encoded
  features (top_k_per_method third); votes >= consensus_threshold means
  selected, so the selected count is emergent, never fixed.
"""
import traceback
from pathlib import Path

import yaml

from src.paths import OUTPUT_DIR
from src.stages._io import (
    append_errors_entry,
    apply_encoding,
    build_target,
    fit_encoding_maps,
    load_upstream,
    log_line,
    new_run_log,
    read_manifest,
    resolve_context,
    write_manifest_atomic,
)
from src.stages.base import Stage
from src.stages.registry import register_stage


def _cramer_v(left, right) -> float:
    """Cramer V association between two categorical series (0..1).

    Returns 0.0 for degenerate tables (single row/column or empty input).
    """
    import pandas as pd
    from scipy.stats import chi2_contingency

    table = pd.crosstab(left.fillna("missing").astype(str), right.fillna("missing").astype(str))
    n_obs = int(table.to_numpy().sum())
    min_dim = min(table.shape[0] - 1, table.shape[1] - 1)
    if n_obs == 0 or min_dim <= 0:
        return 0.0
    chi2 = float(chi2_contingency(table, correction=False)[0])
    return float((chi2 / (n_obs * min_dim)) ** 0.5)


def _mutual_info_scores(matrix, target, discrete, seed) -> dict:
    """MI of each matrix column vs the target, returned as {name: score}."""
    from sklearn.feature_selection import mutual_info_classif

    scores = mutual_info_classif(matrix, target, discrete_features=discrete, random_state=seed)
    return {col: float(val) for col, val in zip(matrix.columns, scores)}


def _drop_redundant_pairs(columns, sim_fn, threshold, mi_scores) -> list:
    """Greedy pairwise drop over an ordered column list.

    When sim_fn(a, b) exceeds threshold, the member with lower MI vs the fit
    target is dropped; the earlier column wins exact MI ties (deterministic).
    Already-dropped columns never trigger further drops.
    """
    dropped = []
    dropped_set = set()
    for pos_a in range(len(columns)):
        for pos_b in range(pos_a + 1, len(columns)):
            col_a, col_b = columns[pos_a], columns[pos_b]
            if col_a in dropped_set or col_b in dropped_set:
                continue
            if abs(sim_fn(col_a, col_b)) <= threshold:
                continue
            if mi_scores.get(col_a, 0.0) >= mi_scores.get(col_b, 0.0):
                dropped.append(col_b)
                dropped_set.add(col_b)
            else:
                dropped.append(col_a)
                dropped_set.add(col_a)
    return dropped


def _take_top(ordered_names, top_k) -> set:
    """First top_k names of a deterministically pre-ordered list, as a set."""
    return set(list(ordered_names)[: max(int(top_k), 0)])


# NOTE: encoding rule lives in src.stages._io (fit_encoding_maps /
# apply_encoding) as the single source of truth shared with split.py.


@register_stage
class FeatureSelectionStage(Stage):
    name = "feature_selection"
    seccion_paper = "3.4 Feature Selection"
    output_dir = Path(OUTPUT_DIR, "tables").as_posix()
    manifest_filename = "feature_selection_manifest.json"
    votes_filename = "feature_selection_votes.csv"

    def is_done(self) -> bool:
        """Done only when our manifest parses with selected features and encoding."""
        manifest = read_manifest(self.output_dir, self.manifest_filename)
        if not isinstance(manifest, dict):
            return False
        selected = manifest.get("selected_features")
        encoding = manifest.get("encoding")
        votes = manifest.get("votes")
        if not isinstance(selected, list) or not selected:
            return False
        if not all(isinstance(item, str) for item in selected):
            return False
        if not isinstance(encoding, dict) or not isinstance(votes, dict):
            return False
        for key in ("one_hot_cols", "frequency_cols", "fitted_num_cols", "fitted_cat_cols"):
            if not isinstance(encoding.get(key), list):
                return False
        if not isinstance(encoding.get("n_encoded"), int):
            return False
        return True

    def run(self) -> dict:
        """Run filters, encoding, 6-method voting; write votes CSV + manifest."""
        log_path = new_run_log(self.name)
        ctx = resolve_context()
        log_line(log_path, f"context={ctx['context']} DATA_DIR={ctx['data_dir']} OUTPUT_DIR={ctx['output_dir']}")
        try:
            import numpy as np
            import pandas as pd
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.feature_selection import RFECV, chi2, f_classif
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import TimeSeriesSplit

            try:
                from boruta import BorutaPy
            except ImportError as exc:
                raise RuntimeError("boruta is required for the boruta method: pip install boruta (see requirements.txt)") from exc
            try:
                import pyarrow  # noqa: F401 — silver parquet IO
            except ImportError as exc:
                raise RuntimeError("pyarrow is required: pip install -r requirements.txt") from exc

            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            with open(cfg_path, encoding="utf-8") as handle:
                cfg = yaml.safe_load(handle)
            data_cfg = cfg.get("data") or {}
            fs_cfg = cfg.get("feature_selection") or {}
            split_cfg = cfg.get("split") or {}
            training_cfg = cfg.get("training") or {}

            expected_methods = ("mi", "anova", "chi2", "rf", "boruta", "rfecv")
            requested = list(fs_cfg.get("methods") or [])
            unknown = [m for m in requested if m not in expected_methods]
            if unknown:
                raise ValueError(f"feature_selection.methods has unknown entries {unknown}: expected {list(expected_methods)}")
            missing = [m for m in expected_methods if m not in requested]
            if missing:
                raise ValueError(f"feature_selection.methods is missing {missing}: all 6 methods are required")
            consensus_threshold = int(fs_cfg.get("consensus_threshold", 2))
            if consensus_threshold < 1:
                raise ValueError(f"consensus_threshold={consensus_threshold!r} must be a positive int")
            if str(fs_cfg.get("top_k_per_method", "third")) != "third":
                raise ValueError(f"top_k_per_method={fs_cfg.get('top_k_per_method')!r} unsupported (only 'third')")
            pearson_thr = float((fs_cfg.get("filters") or {})["pearson"])
            cramer_thr = float((fs_cfg.get("filters") or {})["cramer_v"])
            tie_rule = str(fs_cfg.get("tie_break", "target_mi_train"))
            max_card = int((fs_cfg.get("encoding") or {})["one_hot_max_cardinality"])
            params = fs_cfg.get("params") or {}
            rf_estimators = int(params.get("rf_estimators", 200))
            boruta_iter = int(params.get("boruta_max_iter", 50))
            cv_label = str(params.get("rfecv_cv", "timeseries_3")).strip().lower()
            try:
                n_cv_splits = int(cv_label.rsplit("_", 1)[1])
            except (ValueError, IndexError) as exc:
                raise ValueError(f"feature_selection.params.rfecv_cv={cv_label!r} must look like 'timeseries_3'") from exc
            if n_cv_splits < 2:
                raise ValueError(f"feature_selection.params.rfecv_cv={cv_label!r} needs at least 2 splits")
            seed = int((training_cfg.get("seeds") or {}).get("global", 42))

            exclude_cols = list(data_cfg.get("exclude_cols") or [])
            target_col = str(data_cfg.get("target_col", "riesgo_congestion"))
            fs_years = [int(y) for y in (split_cfg.get("feature_selection_years") or [])]
            train_years = [int(y) for y in (split_cfg.get("train_years") or [])]
            if not fs_years or not train_years:
                raise ValueError("split.feature_selection_years and split.train_years must be non-empty")
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            processed_path = load_upstream("preprocessing", key="artifact_path")
            log_line(log_path, f"loading processed artifact {processed_path}")
            print(f"[progress] feature_selection loading {processed_path}", flush=True)
            df = pd.read_parquet(processed_path)
            log_line(log_path, f"loaded rows={len(df)} cols={len(df.columns)}")

            # Proxy target built with the same thresholds as train; the target
            # column is created in-memory and never enters the candidate set.
            frame, y_all, q75_s, q25_t, train_prev = build_target(df, train_years, target_col)
            frame = frame.reset_index(drop=True)
            y_all_np = np.asarray(y_all).ravel()
            log_line(log_path, f"target q75_s={q75_s:.4f} q25_t={q25_t:.4f} train_prevalence={train_prev:.4f} (reference only)")
            print(f"[progress] target built q75_s={q75_s:.4f} q25_t={q25_t:.4f}", flush=True)

            # Step 1 — leakage/exclusions first: candidates exclude every
            # data.exclude_cols entry (operands, derived, collinear, metadata).
            excluded_set = set(exclude_cols)
            candidates = [c for c in df.columns if c not in excluded_set]
            excluded_cols = [c for c in df.columns if c in excluded_set]
            if not candidates:
                raise ValueError("no candidate columns left after data.exclude_cols")
            log_line(log_path, f"candidates={len(candidates)} excluded={len(excluded_cols)}")

            fit_series = frame["anio"].isin(fs_years)
            if not bool(fit_series.any()):
                raise ValueError(f"no rows in feature_selection_years={fs_years}")
            y_fit = y_all_np[fit_series.to_numpy()]
            if len(np.unique(y_fit)) < 2:
                raise ValueError(f"fit target is single-class in years={fs_years}: cannot rank features")
            n_candidates = len(candidates)

            num_candidates = [c for c in candidates if pd.api.types.is_numeric_dtype(frame[c])]
            cat_candidates = [c for c in candidates if c not in set(num_candidates)]

            # Step 2 — Pearson filter on numerics over fit rows; over-threshold
            # pairs keep the member with higher MI vs the fit target.
            print(f"[progress] pearson filter on {len(num_candidates)} numerics (thr={pearson_thr})", flush=True)
            if num_candidates:
                num_fit = frame.loc[fit_series, num_candidates].astype(float)
                num_fit = num_fit.fillna(num_fit.median()).fillna(0.0)
                corr_matrix = num_fit.corr(method="pearson").fillna(0.0)
                num_mi = _mutual_info_scores(num_fit, y_fit, discrete=False, seed=seed)

                def _pearson_sim(col_a, col_b):
                    return abs(float(corr_matrix.loc[col_a, col_b]))

                pearson_dropped = _drop_redundant_pairs(num_candidates, _pearson_sim, pearson_thr, num_mi)
            else:
                pearson_dropped = []
            log_line(log_path, f"pearson dropped={len(pearson_dropped)}: {pearson_dropped}")

            # Step 3 — Cramer V filter on categoricals over fit rows, same
            # MI tie-break rule against the fit target.
            print(f"[progress] cramer-v filter on {len(cat_candidates)} categoricals (thr={cramer_thr})", flush=True)
            if cat_candidates:
                cat_fit = frame.loc[fit_series, cat_candidates].fillna("missing").astype(str)
                codes = pd.DataFrame(
                    {c: pd.factorize(cat_fit[c], sort=True)[0] for c in cat_candidates},
                    index=cat_fit.index,
                )
                cat_mi = _mutual_info_scores(codes, y_fit, discrete=True, seed=seed)

                def _cramer_sim(col_a, col_b):
                    return _cramer_v(cat_fit[col_a], cat_fit[col_b])

                cramer_dropped = _drop_redundant_pairs(cat_candidates, _cramer_sim, cramer_thr, cat_mi)
            else:
                cramer_dropped = []
            log_line(log_path, f"cramer dropped={len(cramer_dropped)}: {cramer_dropped}")

            dropped_set = set(pearson_dropped) | set(cramer_dropped)
            survivors = [c for c in candidates if c not in dropped_set]
            if not survivors:
                raise RuntimeError("all candidates dropped by pearson/cramer filters: relax thresholds in config")
            surv_num = [c for c in survivors if c in set(num_candidates)]
            surv_cat = [c for c in survivors if c not in set(num_candidates)]
            log_line(log_path, f"survivors={len(survivors)} (num={len(surv_num)} cat={len(surv_cat)})")

            # Deterministic encoding, fit on the train_full block only.
            train_full_series = frame["anio"].isin(train_years)
            if not bool(train_full_series.any()):
                raise ValueError(f"no rows in train_years={train_years} for the encoding fit")
            one_hot_cols, one_hot_cats, freq_cols, freq_maps = fit_encoding_maps(
                frame, surv_cat, train_full_series, max_card
            )
            encoded_all = apply_encoding(frame, surv_num, one_hot_cols, one_hot_cats, freq_cols, freq_maps)
            n_encoded = int(encoded_all.shape[1])
            if n_encoded == 0:
                raise RuntimeError("encoding produced zero columns: check survivors and cardinality rule")
            log_line(log_path, f"encoding one_hot={len(one_hot_cols)} frequency={len(freq_cols)} n_encoded={n_encoded}")
            print(f"[progress] encoded n={n_encoded} (one_hot={len(one_hot_cols)} frequency={len(freq_cols)})", flush=True)

            X_fit_enc = encoded_all.loc[fit_series]
            top_k = max(10, n_encoded // 3)
            log_line(log_path, f"top_k_per_method=third -> top_k={top_k}")
            print(f"[progress] voting top_k={top_k} consensus_threshold={consensus_threshold}", flush=True)

            # Six complementary methods over the encoded fit rows. Score-based
            # methods order by (-score, name); rank-based methods (boruta,
            # rfecv) order by (rank, name); each votes its top_k.
            print("[progress] method 1/6 mi", flush=True)
            mi_scores = _mutual_info_scores(X_fit_enc, y_fit, discrete=False, seed=seed)
            mi_order = sorted(mi_scores, key=lambda c: (-mi_scores[c], c))

            print("[progress] method 2/6 anova", flush=True)
            anova_f, _ = f_classif(X_fit_enc, y_fit)
            anova_scores = {}
            for col, val in zip(X_fit_enc.columns, anova_f):
                stat = float(val)
                # NaN (constant column) ranks last; +inf (perfect separation)
                # keeps its natural top rank.
                anova_scores[col] = -1.0 if np.isnan(stat) else stat
            anova_order = sorted(anova_scores, key=lambda c: (-anova_scores[c], c))

            print("[progress] method 3/6 chi2", flush=True)
            col_min = X_fit_enc.min()
            X_chi = X_fit_enc.sub(col_min)  # chi2 needs non-negative input; shift keeps ranks
            chi_stats, _ = chi2(X_chi, y_fit)
            chi_scores = {}
            for col, val in zip(X_fit_enc.columns, chi_stats):
                stat = float(val)
                chi_scores[col] = -1.0 if np.isnan(stat) else stat
            chi_order = sorted(chi_scores, key=lambda c: (-chi_scores[c], c))

            print("[progress] method 4/6 rf", flush=True)
            forest = RandomForestClassifier(n_estimators=rf_estimators, random_state=seed, n_jobs=1)
            forest.fit(X_fit_enc, y_fit)
            rf_scores = {col: float(val) for col, val in zip(X_fit_enc.columns, forest.feature_importances_)}
            rf_order = sorted(rf_scores, key=lambda c: (-rf_scores[c], c))

            print("[progress] method 5/6 boruta", flush=True)
            boruta_forest = RandomForestClassifier(n_estimators=rf_estimators, random_state=seed, n_jobs=1)
            boruta_sel = BorutaPy(boruta_forest, n_estimators="auto", max_iter=boruta_iter, random_state=seed, verbose=0)
            boruta_sel.fit(X_fit_enc.to_numpy(), y_fit)
            boruta_order = sorted(
                range(n_encoded), key=lambda i: (int(boruta_sel.ranking_[i]), X_fit_enc.columns[i])
            )
            boruta_order = [X_fit_enc.columns[i] for i in boruta_order]

            print("[progress] method 6/6 rfecv", flush=True)
            fit_anios = frame.loc[fit_series, "anio"].to_numpy()
            chrono_order = np.argsort(fit_anios, kind="stable")
            X_rfecv = X_fit_enc.iloc[chrono_order]
            y_rfecv = y_fit[chrono_order]
            logit = LogisticRegression(solver="saga", max_iter=2000, random_state=seed)
            rfecv_sel = RFECV(estimator=logit, cv=TimeSeriesSplit(n_splits=n_cv_splits))
            rfecv_sel.fit(X_rfecv, y_rfecv)
            rfecv_order = sorted(
                range(n_encoded), key=lambda i: (int(rfecv_sel.ranking_[i]), X_rfecv.columns[i])
            )
            rfecv_order = [X_rfecv.columns[i] for i in rfecv_order]

            vote_sets = {
                "mi": _take_top(mi_order, top_k),
                "anova": _take_top(anova_order, top_k),
                "chi2": _take_top(chi_order, top_k),
                "rf": _take_top(rf_order, top_k),
                "boruta": _take_top(boruta_order, top_k),
                "rfecv": _take_top(rfecv_order, top_k),
            }
            votes = {feat: int(sum(1 for s in vote_sets.values() if feat in s)) for feat in encoded_all.columns}
            selected = [feat for feat in encoded_all.columns if votes[feat] >= consensus_threshold]
            if not selected:
                raise RuntimeError(
                    f"consensus is empty with threshold={consensus_threshold}: lower it or widen top_k in config"
                )
            log_line(log_path, f"votes>={consensus_threshold}: selected={len(selected)} of {n_encoded}")
            print(f"[progress] consensus selected={len(selected)} of {n_encoded}", flush=True)

            # Votes CSV: one row per encoded feature with per-method 0/1 flags.
            vote_rows = [
                {
                    "feature": feat,
                    "votes": votes[feat],
                    "consensus": bool(votes[feat] >= consensus_threshold),
                    "mi": int(feat in vote_sets["mi"]),
                    "anova": int(feat in vote_sets["anova"]),
                    "chi2": int(feat in vote_sets["chi2"]),
                    "rf": int(feat in vote_sets["rf"]),
                    "boruta": int(feat in vote_sets["boruta"]),
                    "rfecv": int(feat in vote_sets["rfecv"]),
                }
                for feat in sorted(encoded_all.columns, key=lambda c: (-votes[c], c))
            ]
            votes_path = Path(self.output_dir) / self.votes_filename
            votes_tmp = votes_path.with_suffix(".tmp")
            pd.DataFrame(
                vote_rows,
                columns=["feature", "votes", "consensus", "mi", "anova", "chi2", "rf", "boruta", "rfecv"],
            ).to_csv(votes_tmp, index=False, encoding="utf-8")
            votes_tmp.replace(votes_path)
            log_line(log_path, f"[ok] wrote {votes_path.as_posix()} rows={len(vote_rows)}")

            manifest = {
                "stage": self.name,
                "methods": requested,
                "consensus_threshold": consensus_threshold,
                "filters": {
                    "pearson_dropped": pearson_dropped,
                    "cramer_dropped": cramer_dropped,
                    "tie_break_rule": tie_rule,
                },
                "fit_block": fs_years,
                "votes": votes,
                "selected_features": selected,
                "encoding": {
                    "one_hot_cols": one_hot_cols,
                    "one_hot_categories": {c: [str(v) for v in one_hot_cats[c]] for c in one_hot_cols},
                    "frequency_cols": freq_cols,
                    "n_encoded": n_encoded,
                    "fit_block": "train_full",
                    "fitted_num_cols": surv_num,
                    "fitted_cat_cols": surv_cat,
                },
                "n_candidates": n_candidates,
            }
            write_manifest_atomic(self.output_dir, self.manifest_filename, manifest)
            append_errors_entry({"stage": self.name, "status": "ok"})
            log_line(log_path, "[ok] stage completed")
            print(f"[progress] feature_selection done selected={len(selected)}", flush=True)
            return manifest
        except Exception as e:
            tb = traceback.format_exc()
            log_line(log_path, f"[fail] {e}\n{tb}")
            append_errors_entry({"stage": self.name, "status": "fail", "error": str(e)[:500], "traceback": tb[-4000:]})
            print(f"[error] stage '{self.name}' failed: {e} — see {log_path} and OUTPUT_DIR/logs/errors.json")
            raise
