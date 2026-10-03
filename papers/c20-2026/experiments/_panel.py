"""The modelling panel and the prediction contract shared by stages 07-10.

One row of the panel is one (station, fold, issue_date, horizon, kind): the
issuance and its targets from 04, the local predictors from 05, the large-scale
predictors from 06 joined as-of the issue date, and the station's static
descriptors from config. `kind == "train"` rows are the embargoed daily training
pool of that fold; `kind == "eval"` rows are the weekly evaluation issuances.

Prediction contract
-------------------
Every model writes `outputs/models/preds_<experiment>_<model>.csv` with
`KEY_COLUMNS + ["model", "mean", q05..q95]`. The observation, the window
climatology and the tercile thresholds live once, in
`outputs/models/eval_index_<experiment>.csv`, keyed the same way, so a model can
never score itself against a different truth than the others. Fixed filenames:
a Drive file id per artefact that never changes (AGENTS.md §3).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from _common import OUTPUTS, PROCESSED, atomic_write_csv, read_station_keyed
from _scores import quantile_columns

ISSUANCES_CSV = PROCESSED / "issuances.csv"
FEATURES_DIR = PROCESSED / "features"
LARGESCALE_CSV = PROCESSED / "largescale_daily.csv"
MODELS_DIR = OUTPUTS / "models"

# target name -> (anomaly column, validity column, window-climatology column)
TARGETS = {
    "TT_mean": ("A_C2_target", "valid_target", "C2_target"),
    "TT_min": ("A_C2_target_TT_min", "valid_target_TT_min", "C2_target_TT_min"),
    "TT_max": ("A_C2_target_TT_max", "valid_target_TT_max", "C2_target_TT_max"),
}
KEY_COLUMNS = ["experiment", "target", "station", "fold", "role", "issue_date", "horizon"]
META_COLUMNS = {"fold", "role", "issue_date", "weekday", "kind", "horizon", "lag_start",
                "lag_end", "target_start", "target_end", "n_days", "n_valid_days",
                "n_train_days", "station"}
G_COLUMNS = ["nino34_anom", "nino12_anom", "romi1", "romi2", "romi_amp"]
# R4 sensitivity: Takahashi E/C replace the Niño pair; ROMI is kept.
EC_COLUMNS = ["e_index", "c_index"]
MJO_COLUMNS = ["romi1", "romi2", "romi_amp"]
STATIC_COLUMNS = ["elev_m", "lat", "lon"]


def fast_mode() -> bool:
    """Smoke-run switch (`EXP_FAST=1`, exported by `run_all.py --fast`)."""
    return os.environ.get("EXP_FAST", "").strip().lower() in {"1", "true", "yes"}


def quantile_levels(cfg: dict) -> list[float]:
    return [float(q) for q in cfg["models"]["quantiles"]]


def qcols(cfg: dict) -> list[str]:
    return quantile_columns(quantile_levels(cfg))


# --- assembly ---------------------------------------------------------------

def static_frame(cfg: dict) -> pd.DataFrame:
    from _common import normalize_ubigeo
    rows = [{"station": normalize_ubigeo(s["ubigeo"]), "elev_m": float(s["elev_m"]),
             "lat": float(s["lat"]), "lon": float(s["lon"])}
            for s in cfg.get("stations") or []]
    return pd.DataFrame(rows, columns=["station", *STATIC_COLUMNS])


def join_panel(issuances: pd.DataFrame, features: pd.DataFrame,
               largescale: pd.DataFrame | None, static: pd.DataFrame) -> pd.DataFrame:
    """Pure join, unit-tested: issuances x features x G (as-of) x static."""
    keys = ["station", "fold", "issue_date", "kind", "horizon"]
    feat_cols = [c for c in features.columns if c not in META_COLUMNS or c in keys]
    panel = issuances.merge(features[feat_cols], on=keys, how="left", validate="one_to_one")
    if largescale is not None and not largescale.empty:
        g = largescale[["date", *[c for c in G_COLUMNS + EC_COLUMNS if c in largescale.columns]]]
        panel = panel.merge(g.rename(columns={"date": "issue_date"}), on="issue_date", how="left")
    panel = panel.merge(static, on="station", how="left")
    mid = panel["issue_date"] + pd.to_timedelta((panel["lag_start"] + panel["lag_end"]) / 2, unit="D")
    panel["target_mid"] = mid.dt.normalize()
    panel["quarter"] = ((panel["issue_date"].dt.month % 12) // 3).astype(int)
    return panel


def load_panel(cfg: dict) -> pd.DataFrame:
    """Read 04/05/06 outputs and join them. Fails loudly on a missing stage."""
    for path in (ISSUANCES_CSV, FEATURES_DIR):
        if not path.exists():
            raise SystemExit(f"ERROR: {path} not found — run stages 04 and 05 first")
    issuances = read_station_keyed(ISSUANCES_CSV,
                                   parse_dates=["issue_date", "target_start", "target_end"])
    parts = [read_station_keyed(p, parse_dates=["issue_date"])
             for p in sorted(FEATURES_DIR.glob("*/*.csv"))]
    if not parts:
        raise SystemExit(f"ERROR: no feature files under {FEATURES_DIR}")
    features = pd.concat(parts, ignore_index=True)
    largescale = None
    if LARGESCALE_CSV.is_file():
        largescale = pd.read_csv(LARGESCALE_CSV, parse_dates=["date"])
    else:
        print(f"WARNING: {LARGESCALE_CSV} missing — LG models will equal L models; run 06")
    return join_panel(issuances, features, largescale, static_frame(cfg))


def feature_sets(panel: pd.DataFrame) -> dict[str, list[str]]:
    """Local, large-scale and static feature columns actually present with data."""
    exclude = META_COLUMNS | {"target_mid", "quarter", *STATIC_COLUMNS, *G_COLUMNS, *EC_COLUMNS}
    exclude |= {c for spec in TARGETS.values() for c in spec}
    local = [c for c in panel.columns if c not in exclude
             and pd.api.types.is_numeric_dtype(panel[c]) and panel[c].notna().any()]
    present = lambda cols: [c for c in cols if c in panel.columns and panel[c].notna().any()]
    g = present(G_COLUMNS)
    ec = present(EC_COLUMNS)
    # The E/C set only exists when both indices arrived; ROMI rides along so the
    # sensitivity changes the ENSO description and nothing else.
    g_ec = (ec + present(MJO_COLUMNS)) if len(ec) == len(EC_COLUMNS) else []
    static = [c for c in STATIC_COLUMNS if c in panel.columns]
    return {"L": local, "G": g, "G_EC": g_ec, "static": static}


def target_rows(panel: pd.DataFrame, target: str, kind: str) -> pd.DataFrame:
    """Rows of `kind` whose `target` is valid (targets are never imputed)."""
    a, v, _ = TARGETS[target]
    if a not in panel.columns:
        return panel.iloc[0:0]
    sel = (panel["kind"] == kind) & panel[v].fillna(False).astype(bool) & panel[a].notna()
    return panel[sel]


# --- climatological sample (Clim model and tercile thresholds) --------------

def _circular_doy_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = np.abs(a[:, None] - b[None, :])
    return np.minimum(d, 365.25 - d)


def climatology_sample(train: pd.DataFrame, evals: pd.DataFrame, target: str,
                       window: int = 15, min_n: int = 10) -> list[np.ndarray]:
    """For each eval row, the training targets of the same station and horizon
    whose target midpoint falls within +/- `window` days of day-of-year.

    This is the empirical climatological distribution of the *period-mean*
    anomaly, which is narrower than that of a daily anomaly; using daily
    thresholds would mis-place the terciles for every horizon but W1.
    """
    a = TARGETS[target][0]
    out: list[np.ndarray] = [np.array([])] * len(evals)
    evals = evals.reset_index(drop=True)
    for (st, h), idx in evals.groupby(["station", "horizon"]).groups.items():
        pool = train[(train["station"] == st) & (train["horizon"] == h)]
        if pool.empty:
            continue
        dist = _circular_doy_distance(evals.loc[idx, "target_mid"].dt.dayofyear.to_numpy(float),
                                      pool["target_mid"].dt.dayofyear.to_numpy(float))
        values = pool[a].to_numpy(float)
        for row, i in enumerate(idx):
            # Widen the window only when the declared one holds too few targets
            # (a short training record, or a gap in the season): a NaN reference
            # would silently drop the row from every skill score.
            for w in (window, 2 * window, 4 * window, 183):
                sample = values[dist[row] <= w]
                if len(sample) >= min_n:
                    break
            out[i] = sample
    return out


def build_eval_index(panel: pd.DataFrame, experiment: str, target: str,
                     folds: list[str] | None = None, window: int = 15) -> pd.DataFrame:
    """Observation, climatology and tercile thresholds for every eval row."""
    a, _, c = TARGETS[target]
    frames = []
    for fold, block in panel.groupby("fold", sort=False):
        if folds is not None and fold not in folds:
            continue
        train = target_rows(block, target, "train")
        evals = target_rows(block, target, "eval").reset_index(drop=True)
        if evals.empty:
            continue
        sample = climatology_sample(train, evals, target, window)
        t1 = [np.percentile(s, 100 / 3) if len(s) >= 10 else np.nan for s in sample]
        t2 = [np.percentile(s, 200 / 3) if len(s) >= 10 else np.nan for s in sample]
        frames.append(pd.DataFrame({
            "experiment": experiment, "target": target,
            "station": evals["station"], "fold": evals["fold"], "role": evals["role"],
            "issue_date": evals["issue_date"], "horizon": evals["horizon"],
            "lag_start": evals["lag_start"], "lag_end": evals["lag_end"],
            "quarter": evals["quarter"],
            "nino34_anom": evals["nino34_anom"] if "nino34_anom" in evals else np.nan,
            "romi_amp": evals["romi_amp"] if "romi_amp" in evals else np.nan,
            "obs": evals[a].to_numpy(float),
            "clim": evals[c].to_numpy(float) if c in evals else np.nan,
            "t1": t1, "t2": t2,
        }))
    if not frames:
        return pd.DataFrame(columns=KEY_COLUMNS)
    return pd.concat(frames, ignore_index=True)


# --- prediction IO ----------------------------------------------------------

def pred_frame(rows: pd.DataFrame, experiment: str, target: str, model: str,
               quantiles: np.ndarray, mean: np.ndarray, cfg: dict) -> pd.DataFrame:
    out = pd.DataFrame({
        "experiment": experiment, "target": target,
        "station": rows["station"].to_numpy(), "fold": rows["fold"].to_numpy(),
        "role": rows["role"].to_numpy(), "issue_date": rows["issue_date"].to_numpy(),
        "horizon": rows["horizon"].to_numpy(), "model": model,
        "mean": np.asarray(mean, dtype="float64"),
    })
    q = np.asarray(quantiles, dtype="float64")
    for j, col in enumerate(qcols(cfg)):
        out[col] = q[:, j]
    return out


def preds_path(experiment: str, model: str) -> Path:
    return MODELS_DIR / f"preds_{experiment}_{model}.csv"


def eval_index_path(experiment: str) -> Path:
    return MODELS_DIR / f"eval_index_{experiment}.csv"


def write_preds(frames: list[pd.DataFrame], experiment: str, model: str) -> Path | None:
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return None
    return atomic_write_csv(pd.concat(frames, ignore_index=True), preds_path(experiment, model))


def read_preds(experiment: str | None = None) -> pd.DataFrame:
    pattern = f"preds_{experiment}_*.csv" if experiment else "preds_*.csv"
    parts = [read_station_keyed(p, parse_dates=["issue_date"])
             for p in sorted(MODELS_DIR.glob(pattern))]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def read_eval_index(experiment: str) -> pd.DataFrame:
    path = eval_index_path(experiment)
    if not path.is_file():
        raise SystemExit(f"ERROR: {path} not found — run 07_models.py first")
    return read_station_keyed(path, parse_dates=["issue_date"])
