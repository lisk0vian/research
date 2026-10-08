# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Amendment A3.1: Chronos configured correctly, on every fold.

A2 (T10, T11) traced Chronos' six-times-too-narrow spread to the input form
07b gave it, anomalies around 0 °C. A3 registered two variants, run here on
the temporal experiment, all five folds, TT_mean:

- `Chronos@abs`: 07b's Chronos (chronos-t5-small, 512-day context, 100
  samples, bfloat16, window mean along each path) with absolute daily
  temperature as the context; each path is turned back into anomalies by
  subtracting the fold's C2 climatology over its lead days.
- `ChronosBolt`: amazon/chronos-bolt-small. It returns quantiles, not paths,
  so a window cannot be rebuilt from days; instead it forecasts at the
  target's own resolution. The context is the absolute series averaged over
  consecutive L-day blocks ending on the issue date (L = window length), and
  the window is the step-(a-1)/L+1 forecast: W1 and W2 from 7-day blocks, W3_4
  from 14-day blocks. A block counts with the target's validity rule. The C2
  window mean is subtracted. Bolt's levels are 0.1-0.9; levels between them are
  interpolated linearly and 0.05 / 0.95 come from a normal with the median and
  the 0.1-0.9 spread.

Writes `preds_temporal_Chronos@abs.csv` and `preds_temporal_ChronosBolt.csv`,
which 08-10 score like any other model. The pre-registered Chronos, Ensemble
and M* are untouched.
"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd

from _common import checkpoints, ensure_dirs, load_config, paths_report, primary_target, \
    read_station_keyed, write_manifest
from _harmonic import doy_fractional, eval_harmonic
from _panel import fast_mode, pred_frame, quantile_levels, read_eval_index, write_preds
from _scores import _norm_ppf, rearrange

TARGET = primary_target()
BOLT_ID = "amazon/chronos-bolt-small"
BOLT_LEVELS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
Z90 = 2 * _norm_ppf(0.9)  # (q90 - q10) of a standard normal, 2.563


# --- pure helpers (tested without torch) ------------------------------------------

def block_step(a: int, b: int) -> tuple[int, int]:
    """Window [a, b] -> (block length L, forecast step) for a block-resolution series."""
    length = b - a + 1
    if (a - 1) % length:
        raise ValueError(f"window {a}-{b} does not start on a {length}-day block boundary")
    return length, (a - 1) // length + 1


def block_means(daily: pd.Series, length: int, min_valid: int) -> pd.Series:
    """Trailing `length`-day mean at every date; NaN with fewer than `min_valid` days.

    `daily` must be on a gap-free daily index (missing days as NaN), as 07b's
    anomaly series are. Computed once per station and block length.
    """
    return daily.rolling(length, min_periods=min_valid).mean()


def block_series(means: pd.Series, issue: pd.Timestamp, length: int, n_blocks: int) -> np.ndarray:
    """Consecutive `length`-day block means ending on `issue`, oldest first."""
    ends = pd.DatetimeIndex([issue - pd.Timedelta(days=length * k) for k in range(n_blocks)])
    # Materialised: the reversed view has a negative stride, which torch refuses
    # ("tensors with negative strides are not currently supported").
    return np.ascontiguousarray(means.reindex(ends).to_numpy(float)[::-1])


def expand_levels(q_bolt: np.ndarray, levels: list[float]) -> np.ndarray:
    """(n, 9) quantiles at 0.1..0.9 -> (n, K) on `levels`.

    Inside 0.1-0.9: linear in the level. Outside: a normal with the 0.5
    quantile as centre and sigma = (q90 - q10) / 2.563.
    """
    q_bolt = np.sort(np.asarray(q_bolt, dtype=float), axis=1)
    med = q_bolt[:, BOLT_LEVELS.index(0.5)]
    sigma = np.maximum(q_bolt[:, -1] - q_bolt[:, 0], 0.0) / Z90
    out = np.empty((len(q_bolt), len(levels)))
    for j, tau in enumerate(levels):
        if BOLT_LEVELS[0] <= tau <= BOLT_LEVELS[-1]:
            out[:, j] = [np.interp(tau, BOLT_LEVELS, row) for row in q_bolt]
        else:
            out[:, j] = med + sigma * _norm_ppf(tau)
    return rearrange(out)


def min_valid_days(length: int, cfg: dict) -> int:
    """The target's validity rule: >= 5/7 days, >= 10/14 days (METHODOLOGY §2)."""
    rule = {7: 5, 14: 10}
    return rule.get(length, int(np.ceil(length * 5 / 7)))


# --- model runs -------------------------------------------------------------------

def station_series(m07b, daily: pd.DataFrame, st: str, fid: str, fold: dict, cfg: dict):
    """(anomaly, C2 climatology) daily series of one station against one fold."""
    meta = m07b.load_fold_meta(st, fid)
    anom = m07b.station_daily_anomalies(daily[daily["station"] == st], meta, fold, cfg)["A_TT_mean"]
    period = float(cfg["climatology"].get("period_days", 365.25))
    clim = pd.Series(eval_harmonic(np.asarray(meta["coefficients"]["C2"]),
                                   doy_fractional(anom.index), period), index=anom.index)
    return anom, clim


def frames_for(block: pd.DataFrame, keys: pd.DataFrame, per_h: dict, model: str,
               cfg: dict) -> list[pd.DataFrame]:
    """Prediction frames for the rows the eval index holds (as 07b)."""
    base = block[["station", "fold", "role", "issue_date"]].reset_index(drop=True)
    out = []
    for h, (q, mu) in per_h.items():
        part = base.assign(horizon=h, _pos=np.arange(len(base))).merge(
            keys, on=["station", "fold", "issue_date", "horizon"])
        sel = part["_pos"].to_numpy()
        out.append(pred_frame(part, "temporal", TARGET, model, rearrange(q[sel]), mu[sel], cfg))
    return out


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    ccfg = cfg["models"]["chronos"]
    if not ccfg.get("enabled", True) or (fast_mode() and not cfg["models"]["fast"].get(
            "chronos_enabled", False)):
        print("Chronos disabled (config or fast mode): no variants to run")
        return
    import torch
    import transformers
    from chronos import BaseChronosPipeline

    m07b = importlib.import_module("07b_deep")
    levels = quantile_levels(cfg)
    windows = {h: (int(v[0]), int(v[1])) for h, v in cfg["target"]["horizons"].items()}
    horizon_len = max(b for _, b in windows.values())
    folds = {f["id"]: f for f in cfg["validation"]["folds"]}
    context_days = int(ccfg["context_days"])

    daily = read_station_keyed(m07b.DAILY_CSV, parse_dates=["date"])
    index = read_eval_index("temporal")
    index = index[index["target"] == TARGET]
    keys = index[["station", "fold", "issue_date", "horizon"]]
    evals = index.drop_duplicates(["station", "fold", "issue_date"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dkw = m07b.dtype_kwarg(transformers.__version__)
    ck = checkpoints("07e_chronos_variants")
    out: dict[str, list[pd.DataFrame]] = {"Chronos@abs": [], "ChronosBolt": []}

    series = {}
    for fid, block in evals.groupby("fold"):
        for st in block["station"].unique():
            series[(fid, st)] = station_series(m07b, daily, st, fid, folds[fid], cfg)

    # Chronos@abs -------------------------------------------------------------------
    pipe = BaseChronosPipeline.from_pretrained(ccfg["model_id"], device_map=device,
                                               **{dkw: torch.bfloat16 if device == "cuda"
                                                  else torch.float32})
    bs = int(ccfg.get("batch_size", 64))
    for fid, block in evals.groupby("fold"):
        unit = f"abs__{fid}"
        if ck.has(unit):
            out["Chronos@abs"] += ck.load(unit)
            print(f"[Chronos@abs/{fid}] loaded from checkpoint")
            continue
        ctx, clim_leads = [], []
        for st, d in zip(block["station"], block["issue_date"]):
            anom, clim = series[(fid, st)]
            s = (anom + clim)[lambda x: x.index <= d].iloc[-context_days:]
            ctx.append(torch.tensor(s.to_numpy("float32")))
            lead = pd.date_range(d + pd.Timedelta(days=1), periods=horizon_len, freq="D")
            clim_leads.append(clim.reindex(lead).to_numpy(float))
        paths, bs = m07b.predict_paths(pipe, ctx, horizon_len, int(ccfg["num_samples"]), bs)
        paths = paths - np.vstack(clim_leads)[:, None, :]
        frames = frames_for(block, keys, m07b.window_quantiles(paths, windows, levels),
                            "Chronos@abs", cfg)
        ck.save(unit, frames)
        out["Chronos@abs"] += frames
        print(f"[Chronos@abs/{fid}] {len(ctx)} contexts, batch size {bs}")
    del pipe
    if device == "cuda":
        torch.cuda.empty_cache()

    # ChronosBolt --------------------------------------------------------------------
    bolt = BaseChronosPipeline.from_pretrained(BOLT_ID, device_map=device,
                                               **{dkw: torch.float32})
    for fid, block in evals.groupby("fold"):
        unit = f"bolt__{fid}"
        if ck.has(unit):
            out["ChronosBolt"] += ck.load(unit)
            print(f"[ChronosBolt/{fid}] loaded from checkpoint")
            continue
        per_h = {}
        for h, (a, b) in windows.items():
            length, step = block_step(a, b)
            n_blocks = max(1, context_days // length)
            means = {st: block_means(series[(fid, st)][0] + series[(fid, st)][1], length,
                                     min_valid_days(length, cfg))
                     for st in block["station"].unique()}
            ctx, clim_w = [], []
            for st, d in zip(block["station"], block["issue_date"]):
                anom, clim = series[(fid, st)]
                ctx.append(torch.tensor(block_series(means[st], d, length, n_blocks),
                                        dtype=torch.float32))
                lead = pd.date_range(d + pd.Timedelta(days=a), d + pd.Timedelta(days=b), freq="D")
                clim_w.append(float(clim.reindex(lead).mean()))
            q, mean = bolt.predict_quantiles(ctx, prediction_length=step,
                                             quantile_levels=BOLT_LEVELS)
            q = q[:, step - 1, :].float().cpu().numpy() - np.array(clim_w)[:, None]
            mu = mean[:, step - 1].float().cpu().numpy() - np.array(clim_w)
            per_h[h] = (expand_levels(q, levels), mu)
        frames = frames_for(block, keys, per_h, "ChronosBolt", cfg)
        ck.save(unit, frames)
        out["ChronosBolt"] += frames
        print(f"[ChronosBolt/{fid}] {len(block)} contexts")

    for model, frames in out.items():
        write_preds(frames, "temporal", model)
    write_manifest({"chronos_variants_07e": {
        "amendment": "A3.1", "models": list(out),
        "chronos_abs": {"model_id": ccfg["model_id"], "num_samples": int(ccfg["num_samples"]),
                        "context_days": context_days},
        "chronos_bolt": {"model_id": BOLT_ID, "levels": BOLT_LEVELS,
                         "tails": "normal from median and (q90-q10)/2.563"},
    }}, replace=("chronos_variants_07e",))
    print("done")


if __name__ == "__main__":
    main()
