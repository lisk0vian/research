# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Deep and foundation models (design v3 §5): pooled LSTM and zero-shot Chronos.

`LSTM_LG`
    One network per fold, pooled over the five stations. Input: the last
    `seq_len` days of daily anomalies (TT_mean/TT_min/TT_max against the fold's
    own climatologies, HR against a harmonic fitted on the fold's training
    window, log1p rain, a validity flag), plus the issue-date large-scale
    predictors, the station's static descriptors and the issue day-of-year.
    Output: the 19 grid quantiles for all three horizons at once, trained with
    the pinball loss (masked where a target is invalid), crossings fixed by
    rearrangement. Early stopping on the last `val_fraction` of training issue
    dates, separated from the rest by the embargo. In LOSO the held-out station
    is removed from training entirely.

`Chronos`
    `amazon/chronos-t5-small`, zero-shot: no parameter is fitted on this data.
    The context is the station's daily TT_mean anomaly up to the issue date;
    100 sample paths of 28 days are drawn, each path is averaged over every
    horizon window, and the grid quantiles are taken across paths. Being
    station-agnostic by construction, its LOSO predictions are its temporal
    predictions on the blind folds.

GPU is used when present; on CPU the stage still runs, slowly, and says so.
`EXP_FAST=1` trains one tiny epoch and skips Chronos.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from _common import (
    OUTPUTS,
    PROCESSED,
    ensure_dirs,
    fold_windows,
    load_config,
    paths_report,
    progress,
    read_station_keyed,
    write_manifest,
)
from _harmonic import doy_fractional, eval_harmonic, fit_harmonic
from _panel import (
    G_COLUMNS,
    STATIC_COLUMNS,
    fast_mode,
    load_panel,
    pred_frame,
    quantile_levels,
    read_eval_index,
    target_rows,
    write_preds,
)
from _scores import rearrange

DAILY_CSV = PROCESSED / "daily.csv"
CLIM_DIR = OUTPUTS / "climatology"
SEQ_VARS = ["A_TT_mean", "A_TT_min", "A_TT_max", "A_HR_mean", "log1p_RR", "valid"]
TARGET = "TT_mean"


# --- daily anomaly sequences ---------------------------------------------------

def station_daily_anomalies(daily: pd.DataFrame, meta: dict, fold: dict, cfg: dict) -> pd.DataFrame:
    """Daily inputs for one (station, fold), against that fold's climatologies."""
    period = float(cfg["climatology"].get("period_days", 365.25))
    k = int(cfg["climatology"].get("harmonics_K", 3))
    train_lo, train_hi, _, _ = fold_windows(fold, cfg)
    d = daily.sort_values("date").set_index("date")
    full = pd.date_range(d.index.min(), d.index.max(), freq="D")
    d = d.reindex(full)
    doy = doy_fractional(full)
    out = pd.DataFrame(index=full)
    valid = d["valid"].fillna(False).astype(bool).to_numpy()
    out["A_TT_mean"] = d["TT_mean"].to_numpy(float) - eval_harmonic(
        np.asarray(meta["coefficients"]["C2"]), doy, period)
    for var in ("TT_min", "TT_max"):
        sec = (meta.get("secondary_targets") or {}).get(var)
        out[f"A_{var}"] = (d[var].to_numpy(float) - eval_harmonic(np.asarray(sec["C2"]), doy, period)
                           if sec else np.nan)
    train = (full >= train_lo) & (full <= train_hi) & np.isfinite(d["HR_mean"].to_numpy(float))
    if train.sum() > 2 * k + 2:
        coef = fit_harmonic(doy[train], d["HR_mean"].to_numpy(float)[train], k, period)
        out["A_HR_mean"] = d["HR_mean"].to_numpy(float) - eval_harmonic(coef, doy, period)
    else:
        out["A_HR_mean"] = np.nan
    out["log1p_RR"] = np.log1p(d["RR_sum"].to_numpy(float))
    for col in SEQ_VARS[:-1]:
        out.loc[~valid, col] = np.nan
    out["valid"] = valid.astype(float)
    return out


def load_fold_meta(station: str, fold_id: str) -> dict:
    path = CLIM_DIR / station / f"{fold_id}.json"
    if not path.is_file():
        raise SystemExit(f"ERROR: {path} not found — run 03_climatology.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def build_sequences(seq_by_station: dict[str, pd.DataFrame], rows: pd.DataFrame,
                    seq_len: int) -> np.ndarray:
    """(n, seq_len, n_vars) windows ending at each row's issue date (inclusive)."""
    out = np.full((len(rows), seq_len, len(SEQ_VARS)), np.nan, dtype="float32")
    for i, (st, d) in enumerate(zip(rows["station"], rows["issue_date"])):
        frame = seq_by_station[st]
        end = frame.index.searchsorted(d, side="right")
        block = frame.iloc[max(0, end - seq_len):end][SEQ_VARS].to_numpy("float32")
        out[i, seq_len - len(block):] = block
    return out


def issue_samples(panel_fold: pd.DataFrame, kind: str, horizons: list[str]) -> pd.DataFrame:
    """One sample per (station, issue_date) with the three horizon targets as columns."""
    rows = panel_fold[panel_fold["kind"] == kind]
    a, v = "A_C2_target", "valid_target"
    rows = rows.assign(y=np.where(rows[v].fillna(False).astype(bool), rows[a], np.nan))
    wide = rows.pivot_table(index=["station", "issue_date"], columns="horizon", values="y",
                            aggfunc="first", dropna=False)
    wide = wide.reindex(columns=horizons)
    tab_cols = [c for c in [*G_COLUMNS, *STATIC_COLUMNS] if c in rows.columns]
    first = rows.drop_duplicates(["station", "issue_date"]).set_index(["station", "issue_date"])
    wide = wide.join(first[tab_cols + ["fold", "role"]])
    return wide.reset_index()


# --- LSTM -----------------------------------------------------------------------

def _torch():
    import torch
    return torch


def make_net(n_seq: int, n_tab: int, n_out: int, hidden: int, layers: int, dropout: float):
    torch = _torch()
    nn = torch.nn

    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(n_seq, hidden, num_layers=layers, batch_first=True,
                                dropout=dropout if layers > 1 else 0.0)
            self.head = nn.Sequential(nn.Linear(hidden + n_tab, hidden), nn.ReLU(),
                                      nn.Dropout(dropout), nn.Linear(hidden, n_out))

        def forward(self, seq, tab):
            _, (h, _) = self.lstm(seq)
            return self.head(torch.cat([h[-1], tab], dim=1))
    return Net()


def pinball_loss(pred, y, taus):
    """pred (n, H, K), y (n, H) with NaN where invalid, taus (K,)."""
    torch = _torch()
    mask = torch.isfinite(y)
    y0 = torch.where(mask, y, torch.zeros_like(y)).unsqueeze(-1)
    diff = y0 - pred
    loss = torch.maximum(taus * diff, (taus - 1) * diff)
    loss = loss * mask.unsqueeze(-1)
    return loss.sum() / (mask.sum() * pred.shape[-1]).clamp(min=1)


def _prep(seq: np.ndarray, tab: np.ndarray, stats: dict | None):
    """Standardise with training statistics; missing -> 0 (the training mean)."""
    if stats is None:
        flat = seq.reshape(-1, seq.shape[-1])
        stats = {"sm": np.nanmean(flat, 0), "ss": np.nanstd(flat, 0),
                 "tm": np.nanmean(tab, 0) if tab.size else np.zeros(0),
                 "ts": np.nanstd(tab, 0) if tab.size else np.zeros(0)}
        for k in ("ss", "ts"):
            stats[k][~np.isfinite(stats[k]) | (stats[k] == 0)] = 1.0
        for k in ("sm", "tm"):
            stats[k][~np.isfinite(stats[k])] = 0.0
    s = np.nan_to_num((seq - stats["sm"]) / stats["ss"]).astype("float32")
    t = np.nan_to_num((tab - stats["tm"]) / stats["ts"]).astype("float32") if tab.size else tab
    return s, t, stats


def fit_predict_lstm(tr: pd.DataFrame, ev: pd.DataFrame, seqs: dict, horizons: list[str],
                     levels: list[float], cfg: dict, seed: int,
                     static: list[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Returns (n_eval, H, K) quantiles and (n_eval, H) means.

    `static` picks the station descriptors fed to the head (None = all of
    STATIC_COLUMNS); the LOSO variants pass `["elev_m"]` or `[]`.
    """
    torch = _torch()
    lcfg = dict(cfg["models"]["lstm"])
    if fast_mode():
        lcfg.update(epochs=int(cfg["models"]["fast"]["lstm_epochs"]),
                    hidden=int(cfg["models"]["fast"]["lstm_hidden"]))
    torch.manual_seed(seed)
    np.random.seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    seq_len = int(lcfg["seq_len"])
    static_cols = STATIC_COLUMNS if static is None else static
    tab_cols = [c for c in [*G_COLUMNS, *static_cols] if c in tr.columns]
    doy = lambda f: np.column_stack([np.sin(2 * np.pi * f["issue_date"].dt.dayofyear / 365.25),
                                     np.cos(2 * np.pi * f["issue_date"].dt.dayofyear / 365.25)])

    tr = tr[tr[horizons].notna().any(axis=1)].sort_values("issue_date").reset_index(drop=True)
    embargo = int(cfg["validation"].get("embargo_days", 28))
    cut = tr["issue_date"].quantile(1 - float(lcfg.get("val_fraction", 0.15)))
    fit_rows = tr[tr["issue_date"] < cut - pd.Timedelta(days=embargo)]
    val_rows = tr[tr["issue_date"] >= cut]
    if len(fit_rows) < 50 or len(val_rows) < 20:
        fit_rows, val_rows = tr, tr.iloc[0:0]

    def arrays(frame, stats=None):
        seq = build_sequences(seqs, frame, seq_len)
        tab = np.column_stack([frame[tab_cols].to_numpy(float), doy(frame)]) if len(frame) \
            else np.zeros((0, len(tab_cols) + 2))
        return _prep(seq, tab, stats)

    s_fit, t_fit, stats = arrays(fit_rows)
    y_fit = fit_rows[horizons].to_numpy("float32")
    taus = torch.tensor(levels, dtype=torch.float32, device=device)
    H, K = len(horizons), len(levels)
    net = make_net(len(SEQ_VARS), t_fit.shape[1], H * K, int(lcfg["hidden"]),
                   int(lcfg["layers"]), float(lcfg["dropout"])).to(device)
    opt = torch.optim.Adam(net.parameters(), lr=float(lcfg["lr"]))

    def tensor(x):
        return torch.tensor(x, device=device)

    if len(val_rows):
        s_val, t_val, _ = arrays(val_rows, stats)
        y_val = tensor(val_rows[horizons].to_numpy("float32"))
    best, best_state, wait = np.inf, None, 0
    bs = int(lcfg["batch_size"])
    for epoch in range(int(lcfg["epochs"])):
        net.train()
        order = np.random.permutation(len(s_fit))
        for start in range(0, len(order), bs):
            b = order[start:start + bs]
            pred = net(tensor(s_fit[b]), tensor(t_fit[b])).view(-1, H, K)
            loss = pinball_loss(pred, tensor(y_fit[b]), taus)
            opt.zero_grad()
            loss.backward()
            opt.step()
        if len(val_rows):
            net.eval()
            with torch.no_grad():
                vl = float(pinball_loss(net(tensor(s_val), tensor(t_val)).view(-1, H, K),
                                        y_val, taus))
            if vl < best - 1e-5:
                best, wait = vl, 0
                best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
            else:
                wait += 1
                if wait >= int(lcfg["patience"]):
                    break
    if best_state is not None:
        net.load_state_dict(best_state)

    s_ev, t_ev, _ = arrays(ev, stats)
    net.eval()
    with torch.no_grad():
        out = net(tensor(s_ev), tensor(t_ev)).view(-1, H, K).cpu().numpy().astype("float64")
    q = rearrange(out)
    return q, q.mean(axis=-1)


def explode(ev: pd.DataFrame, q: np.ndarray, mu: np.ndarray, horizons: list[str],
            index: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """(station, issue_date) samples x horizons -> one row per eval-index row."""
    base = ev[["station", "issue_date", "fold", "role"]].reset_index(drop=True)
    long = pd.concat([base.assign(horizon=h, _pos=np.arange(len(base)) + j * len(base))
                      for j, h in enumerate(horizons)], ignore_index=True)
    Q = np.vstack([q[:, j, :] for j in range(len(horizons))])
    M = np.concatenate([mu[:, j] for j in range(len(horizons))])
    long = long.merge(index[["station", "fold", "issue_date", "horizon"]],
                      on=["station", "fold", "issue_date", "horizon"])
    sel = long["_pos"].to_numpy()
    return long.drop(columns="_pos"), Q[sel], M[sel]


# --- Chronos -------------------------------------------------------------------

def chronos_pipeline(model_id: str):
    import torch
    from chronos import BaseChronosPipeline
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    return BaseChronosPipeline.from_pretrained(model_id, device_map=device, torch_dtype=dtype)


def window_quantiles(paths: np.ndarray, windows: dict[str, tuple[int, int]],
                     levels: list[float]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """paths (n, S, 28) daily -> per horizon (n, K) quantiles and (n,) means.

    The window mean is taken along each sample path first, then the quantiles
    across paths: the order matters, because daily errors are correlated.
    """
    out = {}
    for h, (a, b) in windows.items():
        wm = paths[:, :, a - 1:b].mean(axis=2)
        out[h] = (np.quantile(wm, levels, axis=1).T, wm.mean(axis=1))
    return out


def run_chronos(panel: pd.DataFrame, seqs_by_fold: dict, index: pd.DataFrame,
                cfg: dict, levels: list[float]) -> list[pd.DataFrame]:
    import torch
    ccfg = cfg["models"]["chronos"]
    windows = {h: (int(v[0]), int(v[1])) for h, v in cfg["target"]["horizons"].items()}
    horizon_len = max(b for _, b in windows.values())
    pipe = chronos_pipeline(ccfg["model_id"])
    frames = []
    evals = index.drop_duplicates(["station", "fold", "issue_date"])
    for fold, block in progress(list(evals.groupby("fold")), desc="07b chronos",
                                unit="fold", level="fold"):
        ctx = []
        for st, d in zip(block["station"], block["issue_date"]):
            s = seqs_by_fold[fold][st]["A_TT_mean"]
            s = s[s.index <= d].iloc[-int(ccfg["context_days"]):]
            ctx.append(torch.tensor(s.to_numpy("float32")))
        paths = []
        bs = int(ccfg.get("batch_size", 64))
        for start in range(0, len(ctx), bs):
            out = pipe.predict(ctx[start:start + bs], prediction_length=horizon_len,
                               num_samples=int(ccfg["num_samples"]))
            paths.append(out.float().cpu().numpy())
        paths = np.concatenate(paths, axis=0)
        wq = window_quantiles(paths, windows, levels)
        base = block[["station", "fold", "role", "issue_date"]].reset_index(drop=True)
        keys = index[["station", "fold", "issue_date", "horizon"]]
        for h, (q, mu) in wq.items():
            # Keep only rows the eval index holds (valid targets for this horizon),
            # carrying each row's position in `paths` along.
            part = base.assign(horizon=h, _pos=np.arange(len(base))).merge(
                keys, on=["station", "fold", "issue_date", "horizon"])
            sel = part["_pos"].to_numpy()
            frames.append(pred_frame(part, "temporal", TARGET, "Chronos", rearrange(q[sel]),
                                     mu[sel], cfg))
        print(f"[chronos/{fold}] {len(block)} contexts")
    return frames


# --- driver ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-lstm", action="store_true")
    ap.add_argument("--skip-chronos", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    try:
        torch = _torch()
    except ImportError:
        raise SystemExit("ERROR: torch is not installed; run the notebook's install cell")
    print(f"torch {torch.__version__} | cuda={torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("WARNING: no GPU; the LSTM will be slow and Chronos very slow. "
              "In Colab: Runtime > Change runtime type > GPU.")

    levels = quantile_levels(cfg)
    horizons = list(cfg["target"]["horizons"].keys())
    panel = load_panel(cfg)
    daily = read_station_keyed(DAILY_CSV, parse_dates=["date"])
    folds = {f["id"]: f for f in cfg["validation"]["folds"]}
    stations = sorted(panel["station"].unique())
    seqs_by_fold = {
        fid: {st: station_daily_anomalies(daily[daily["station"] == st],
                                          load_fold_meta(st, fid), fold, cfg)
              for st in stations}
        for fid, fold in folds.items()
    }
    index_t = read_eval_index("temporal")
    index_t = index_t[index_t["target"] == TARGET]
    summary: dict = {"fast_mode": fast_mode(), "cuda": bool(torch.cuda.is_available())}
    seed = int(cfg.get("seeds", {}).get("lstm", 0))

    if not args.skip_lstm:
        t_frames, l_frames = [], {}
        for fid in progress(list(folds), desc="07b lstm", unit="fold", level="fold"):
            block = panel[panel["fold"] == fid]
            tr = issue_samples(block, "train", horizons)
            ev = issue_samples(block, "eval", horizons)
            t0 = time.perf_counter()
            q, mu = fit_predict_lstm(tr, ev, seqs_by_fold[fid], horizons, levels, cfg, seed)
            rows, Q, M = explode(ev, q, mu, horizons, index_t[index_t["fold"] == fid])
            t_frames.append(pred_frame(rows, "temporal", TARGET, "LSTM_LG", Q, M, cfg))
            print(f"[lstm/temporal/{fid}] train={len(tr)} eval={len(ev)} "
                  f"({time.perf_counter() - t0:.1f}s)")
        write_preds(t_frames, "temporal", "LSTM_LG")

        index_l = read_eval_index("loso")
        # R2: same network with all, elevation-only and no static descriptors.
        variants = {str(k or ""): list(v or []) for k, v in
                    (cfg["validation"].get("loso", {}).get("static_variants")
                     or {"": list(STATIC_COLUMNS)}).items()}
        for fid in cfg["validation"].get("loso", {}).get("folds", ["B1", "B2"]):
            block = panel[panel["fold"] == fid]
            tr_all = issue_samples(block, "train", horizons)
            ev_all = issue_samples(block, "eval", horizons)
            for st in stations:
                tr, ev = tr_all[tr_all["station"] != st], ev_all[ev_all["station"] == st]
                if ev.empty:
                    continue
                idx = index_l[(index_l["fold"] == fid) & (index_l["station"] == st)]
                for variant, static in variants.items():
                    name = f"LSTM_LG@{variant}" if variant else "LSTM_LG"
                    q, mu = fit_predict_lstm(tr, ev, seqs_by_fold[fid], horizons, levels, cfg,
                                             seed, static=static)
                    rows, Q, M = explode(ev, q, mu, horizons, idx)
                    l_frames.setdefault(name, []).append(
                        pred_frame(rows, "loso", TARGET, name, Q, M, cfg))
                print(f"[lstm/loso/{fid}] held out {st} ({len(variants)} static variants)")
        for name, frames in l_frames.items():
            write_preds(frames, "loso", name)
        summary["lstm"] = "done"

    chronos_on = bool(cfg["models"]["chronos"].get("enabled", True)) and not args.skip_chronos
    if fast_mode() and not cfg["models"]["fast"].get("chronos_enabled", False):
        chronos_on = False
    if chronos_on:
        try:
            frames = run_chronos(panel, seqs_by_fold, index_t, cfg, levels)
        except ImportError:
            raise SystemExit("ERROR: chronos-forecasting is not installed; run the install cell")
        write_preds(frames, "temporal", "Chronos")
        loso_folds = cfg["validation"].get("loso", {}).get("folds", ["B1", "B2"])
        loso = [f[f["fold"].isin(loso_folds)].assign(experiment="loso") for f in frames]
        write_preds(loso, "loso", "Chronos")
        summary["chronos"] = cfg["models"]["chronos"]["model_id"]
    else:
        print("Chronos skipped (disabled, --skip-chronos or fast mode)")
    write_manifest({"models_07b": summary}, replace=("models_07b",))
    print("done")


if __name__ == "__main__":
    main()
