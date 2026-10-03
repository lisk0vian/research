# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Amendment A2 (post hoc): is Chronos' narrow daily spread technical or the model's?

09c showed that Chronos' daily sample paths are about six times too narrow
(daily 90 % coverage 0.20-0.21). Two technical causes are possible, both in how
07b calls the model:

- **Precision.** 07b loads the weights in bfloat16, which a T4 only emulates;
  coarser logits could reduce the diversity of the sampled tokens.
- **Input scale.** 07b gives Chronos daily anomalies, values around 0 °C.
  Chronos divides each context by its mean absolute value before tokenising, a
  scaling meant for series away from zero.

This stage re-runs Chronos on one dev fold (D3, so no blind data is used again)
under a 2 x 2 design: bfloat16 or float32 weights, anomalies or absolute
temperature as the context. Absolute paths are turned back into anomalies with
the same fold climatology (C2), so every variant is scored on the same anomaly
scale against the same outcomes. A technical cause shows as a variant whose
paths are much wider and cover much better; the model's own behaviour shows as
four variants that look alike.

This is a sensitivity analysis only: 07b, the Ensemble and M* keep the
pre-registered configuration whatever it finds. Writes
`outputs/tables/T11_chronos_sensitivity.csv`.
"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd

from _common import (
    TABLES,
    atomic_write_csv,
    checkpoints,
    ensure_dirs,
    load_config,
    paths_report,
    read_station_keyed,
    write_manifest,
)
from _harmonic import doy_fractional, eval_harmonic
from _panel import fast_mode, read_eval_index

TARGET = "TT_mean"
# v1: adds the CRPS of each variant (daily and per window), the net effect of
# calibration and median accuracy together.
RESULTS_VERSION = 1
FOLD = "D3"  # the last dev fold: nothing here touches the blind folds again
VARIANTS = [("bfloat16", "anomaly"), ("float32", "anomaly"),
            ("bfloat16", "absolute"), ("float32", "absolute")]


def crps_samples(samples: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS of a sample forecast, row by row: E|X - y| - E|X - X'| / 2.

    samples (n, S), y (n,). The second term uses the sorted-sample identity
    E|X - X'| = 2 / S^2 * sum_i (2i - S - 1) x_(i), exact for the empirical
    distribution and O(S log S) instead of O(S^2).
    """
    s = np.sort(samples, axis=1)
    m = s.shape[1]
    w = 2 * np.arange(1, m + 1) - m - 1
    spread = 2.0 / m ** 2 * (s * w).sum(axis=1)
    return np.abs(s - y[:, None]).mean(axis=1) - 0.5 * spread


def crps_daily_and_windows(paths: np.ndarray, obs: np.ndarray,
                           windows: dict[str, tuple[int, int]]) -> dict[str, float]:
    """Mean CRPS over the daily leads (finite outcomes) and per window mean."""
    out = {}
    ok = np.isfinite(obs)
    daily = [crps_samples(paths[ok[:, t], :, t], obs[ok[:, t], t]) for t in range(obs.shape[1])]
    out["daily"] = float(np.concatenate(daily).mean())
    for h, (a, b) in windows.items():
        full = ok[:, a - 1:b].all(axis=1)
        out[h] = float(crps_samples(paths[full, :, a - 1:b].mean(axis=2),
                                    obs[full, a - 1:b].mean(axis=1)).mean()) if full.any() else np.nan
    return out


def window_coverage(paths: np.ndarray, obs: np.ndarray, a: int, b: int) -> tuple[float, float]:
    """90 % coverage and median RMSE of the window mean, contexts with a full window."""
    wm = paths[:, :, a - 1:b].mean(axis=2)
    ow = obs[:, a - 1:b]
    ok = np.isfinite(ow).all(axis=1)
    if not ok.any():
        return float("nan"), float("nan")
    ow = ow[ok].mean(axis=1)
    lo, med, hi = (np.quantile(wm[ok], p, axis=1) for p in (0.05, 0.5, 0.95))
    return float(np.mean((ow >= lo) & (ow <= hi))), float(np.sqrt(np.mean((ow - med) ** 2)))


def variant_rows(label: str, paths: np.ndarray, obs: np.ndarray,
                 windows: dict[str, tuple[int, int]], d09c) -> list[dict]:
    rows = d09c.summarise(paths, obs, windows, label)
    for scope, value in crps_daily_and_windows(paths, obs, windows).items():
        rows.append({"role": label, "check": "crps", "scope": scope, "paths": value,
                     "observed": np.nan, "metric": "CRPS (degC; lower is better)"})
    for h, (a, b) in windows.items():
        cov, rmse = window_coverage(paths, obs, a, b)
        rows.append({"role": label, "check": "window", "scope": h, "paths": cov,
                     "observed": 0.90, "metric": "cov90 of window mean (nominal 0.90)"})
        rows.append({"role": label, "check": "window", "scope": h, "paths": rmse,
                     "observed": np.nan, "metric": "RMSE of window-mean median (degC)"})
    return rows


def load_pipeline(model_id: str, dtype_name: str):
    import torch
    import transformers
    from chronos import BaseChronosPipeline

    m07b = importlib.import_module("07b_deep")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = getattr(torch, dtype_name)
    return BaseChronosPipeline.from_pretrained(
        model_id, device_map=device, **{m07b.dtype_kwarg(transformers.__version__): dtype})


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    ccfg = cfg["models"]["chronos"]
    if not ccfg.get("enabled", True) or (fast_mode() and not cfg["models"]["fast"].get(
            "chronos_enabled", False)):
        print("Chronos disabled (config or fast mode): nothing to test")
        return
    import torch

    m07b = importlib.import_module("07b_deep")
    d09c = importlib.import_module("09c_chronos_diagnostic")
    windows = {h: (int(v[0]), int(v[1])) for h, v in cfg["target"]["horizons"].items()}
    horizon_len = max(b for _, b in windows.values())
    period = float(cfg["climatology"].get("period_days", 365.25))
    fold = {f["id"]: f for f in cfg["validation"]["folds"]}[FOLD]

    daily = read_station_keyed(m07b.DAILY_CSV, parse_dates=["date"])
    index = read_eval_index("temporal")
    block = index[(index["target"] == TARGET) & (index["fold"] == FOLD)] \
        .drop_duplicates(["station", "issue_date"])

    # Per station: anomalies (as 07b) and the C2 climatology they are taken against.
    anom, clim = {}, {}
    for st in block["station"].unique():
        meta = m07b.load_fold_meta(st, FOLD)
        a = m07b.station_daily_anomalies(daily[daily["station"] == st], meta, fold, cfg)["A_TT_mean"]
        anom[st] = a
        clim[st] = pd.Series(eval_harmonic(np.asarray(meta["coefficients"]["C2"]),
                                           doy_fractional(a.index), period), index=a.index)

    obs, leads = [], []
    for st, d in zip(block["station"], block["issue_date"]):
        lead = pd.date_range(d + pd.Timedelta(days=1), periods=horizon_len, freq="D")
        leads.append(lead)
        obs.append(anom[st].reindex(lead).to_numpy(float))
    obs = np.vstack(obs)

    ck = checkpoints("09d_chronos_sensitivity")
    bs = int(ccfg.get("batch_size", 64))
    rows: list[dict] = []
    for dtype_name, scale in VARIANTS:
        label = f"{dtype_name}/{scale}"
        unit = label.replace("/", "__")
        if ck.has(unit):
            paths = ck.load(unit)
            print(f"[{label}] loaded from checkpoint")
        else:
            pipe = load_pipeline(ccfg["model_id"], dtype_name)
            ctx = []
            for st, d in zip(block["station"], block["issue_date"]):
                s = anom[st] + (clim[st] if scale == "absolute" else 0.0)
                ctx.append(torch.tensor(s[s.index <= d].iloc[-int(ccfg["context_days"]):]
                                        .to_numpy("float32")))
            paths, bs = m07b.predict_paths(pipe, ctx, horizon_len, int(ccfg["num_samples"]), bs)
            if scale == "absolute":
                # Back to anomalies against the same climatology the outcomes use.
                c = np.vstack([clim[st].reindex(lead).to_numpy(float)
                               for st, lead in zip(block["station"], leads)])
                paths = paths - c[:, None, :]
            ck.save(unit, paths.astype("float32"))
            del pipe
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print(f"[{label}] {len(ctx)} contexts, batch size {bs}")
        rows += variant_rows(label, paths.astype(float), obs, windows, d09c)

    table = pd.DataFrame(rows).rename(columns={"role": "variant"})
    path = atomic_write_csv(table.round(4), TABLES / "T11_chronos_sensitivity.csv")
    show = table[table["metric"].str.startswith(("cov90", "path SD", "CRPS"))]
    print(show.pivot_table(index=["check", "scope", "metric"], columns="variant", values="paths")
          .round(3).to_string())
    write_manifest({"chronos_sensitivity_09d": {
        "amendment": "A2, post hoc; sensitivity only, 07b/M* unchanged",
        "table": "outputs/tables/T11_chronos_sensitivity.csv", "fold": FOLD,
        "variants": [f"{a}/{b}" for a, b in VARIANTS], "contexts": int(len(block)),
    }}, replace=("chronos_sensitivity_09d",))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
