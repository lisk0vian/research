# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Access engine for c19-2026: accumulated cost, population allocation, summaries.

Pure numpy/scipy so the synthetic tests need no rasters, no network and no real
data. Cost surfaces use the MAP convention: minutes per metre travelled. The
grid engine answers "minutes from each cell to the nearest destination"; the
population functions keep the census total exactly; the stability functions
compare two rankings.

The graph is the full 8-neighbour grid (~3.4 M cells, ~27 M edges at 30 arcsec
for Peru). Weights are float32 and indices int32 to keep the peak in a standard
Colab runtime.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.stats import kendalltau, spearmanr


def grid_graph(cost: np.ndarray, pixel_m: float,
               lats: np.ndarray | None = None) -> coo_matrix:
    """8-neighbour graph; edge weight = mean pixel cost x distance (minutes).

    `lats` gives the latitude of each row; the east-west pixel width is then
    `pixel_m * cos(lat)`, so the metric bias is not left in the graph.
    """
    cost = np.asarray(cost, dtype=float)
    h, w = cost.shape
    idx = np.arange(h * w).reshape(h, w)
    flat = cost.ravel()
    dy = float(pixel_m)
    if lats is None:
        dx = np.full(h, dy)
    else:
        dx = dy * np.cos(np.radians(np.asarray(lats, dtype=float)))
        if dx.shape != (h,):
            raise ValueError("lats must have one value per row")

    def edges(a, b, dist):
        c = 0.5 * (flat[a] + flat[b])
        ok = np.isfinite(c)
        return (a[ok].astype(np.int32), b[ok].astype(np.int32),
                (c[ok] * dist[ok]).astype(np.float32))

    diag = np.sqrt(dx ** 2 + dy ** 2)
    parts = [
        edges(idx[:, :-1].ravel(), idx[:, 1:].ravel(), np.repeat(dx, w - 1)),
        edges(idx[:-1, :].ravel(), idx[1:, :].ravel(), np.full((h - 1) * w, dy)),
        edges(idx[:-1, :-1].ravel(), idx[1:, 1:].ravel(), np.repeat(diag[:-1], w - 1)),
        edges(idx[:-1, 1:].ravel(), idx[1:, :-1].ravel(), np.repeat(diag[:-1], w - 1)),
    ]
    rows = np.concatenate([p[0] for p in parts])
    cols = np.concatenate([p[1] for p in parts])
    data = np.concatenate([p[2] for p in parts])
    return coo_matrix((data, (rows, cols)), shape=(h * w, h * w)).tocsr()


def accumulated_cost(cost: np.ndarray, sources, pixel_m: float = 1000.0,
                     lats: np.ndarray | None = None) -> np.ndarray:
    """Minutes from every cell to the nearest source, multi-source Dijkstra.

    `sources` are flat indices into the grid. Unreachable cells stay `inf`.
    `min_only=True` gives the multi-source minimum in one pass.
    """
    cost = np.asarray(cost, dtype=float)
    src = np.asarray(sources, dtype=np.int32).ravel()
    if src.size == 0:
        return np.full(cost.shape, np.inf)
    graph = grid_graph(cost, pixel_m, lats=lats)
    best = dijkstra(graph, directed=False, indices=src, min_only=True)
    return np.asarray(best).reshape(cost.shape)


def allocate_population(grid: np.ndarray, districts: np.ndarray,
                        totals: dict[int, float]) -> tuple[np.ndarray, dict]:
    """Dasymetric allocation: rescale each district's grid to its census total.

    Exact by construction (the factor makes the district sum equal the total).
    A district with no population in the grid is reported, never invented.
    """
    grid = np.asarray(grid, dtype=float)
    districts = np.asarray(districts)
    out = np.zeros_like(grid)
    report: dict[int, dict] = {}
    for did, total in totals.items():
        mask = districts == did
        raw = float(grid[mask].sum())
        if raw <= 0:
            report[int(did)] = {"raw": raw, "total": float(total), "status": "no_population"}
            continue
        factor = float(total) / raw
        out[mask] = grid[mask] * factor
        report[int(did)] = {"raw": raw, "total": float(total), "factor": factor, "status": "ok"}
    return out, report


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """Weighted quantile (linear interpolation of the weighted CDF)."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cw = np.cumsum(w) - 0.5 * w
    cw = cw / w.sum()
    return float(np.interp(q, cw, v))


def district_summary(times: np.ndarray, population: np.ndarray,
                     districts: np.ndarray, ids=None) -> pd.DataFrame:
    """Person-weighted travel time per district, plus a district-weighted view.

    Unreachable cells count as deficient in the shares, but are excluded from
    the mean and the median; they are reported in `share_unreachable`.
    """
    times = np.asarray(times, dtype=float)
    population = np.asarray(population, dtype=float)
    districts = np.asarray(districts)
    rows = []
    for did in (np.unique(districts) if ids is None else ids):
        if int(did) <= 0:
            continue
        mask = districts == did
        t, w = times[mask], population[mask]
        total = float(w.sum())
        finite = np.isfinite(t)
        row = {"district": int(did), "population": total}
        if total <= 0:
            row.update(mean_min=np.nan, median_min=np.nan, share_over_60=np.nan,
                       share_over_120=np.nan, share_unreachable=np.nan)
        else:
            row["share_over_60"] = float(w[(t > 60) | ~finite].sum() / total)
            row["share_over_120"] = float(w[(t > 120) | ~finite].sum() / total)
            row["share_unreachable"] = float(w[~finite].sum() / total)
            ok = finite & (w > 0)
            if ok.any():
                tw, ww = t[ok], w[ok]
                row["mean_min"] = float((tw * ww).sum() / ww.sum())
                row["median_min"] = weighted_quantile(tw, ww, 0.5)
            else:
                row.update(mean_min=np.nan, median_min=np.nan)
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["district_weighted_mean_min"] = frame["mean_min"].mean()
    return frame


def _kappa(a: np.ndarray, b: np.ndarray) -> float:
    po = float((a == b).mean())
    pa, pb = float(a.mean()), float(b.mean())
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def _worst(x: np.ndarray, k: int) -> set | None:
    """Indices of the k largest values, or None when ties straddle the k-th value."""
    cut = np.sort(x)[-k]
    if int((x >= cut).sum()) > k:
        return None
    return set(np.flatnonzero(x >= cut).tolist())


def _matched_flags(x: np.ndarray, n_target: int) -> np.ndarray:
    """Flag the n_target largest values of x; ties at the cut are all flagged."""
    if n_target <= 0:
        return np.zeros(x.size, dtype=bool)
    return x >= np.sort(x)[-n_target]


def stability(a: np.ndarray, b: np.ndarray, k: int = 100,
              thresholds: tuple[float, ...] = (60.0, 120.0),
              b_minutes: bool = True) -> dict:
    """Agreement between the main travel time `a` and a variant `b`.

    Both must be oriented so that a higher value means worse access (negate a
    2SFCA score before calling). The "worst" set is the top-k by descending
    value. Deficient access is `a > thr` minutes. A variant in minutes uses
    the same threshold; a variant in any other unit (km, negated 2SFCA) flags
    the same number of districts as `a` does (quantile matching), because a
    minute threshold has no meaning in km or in hospitals per 10,000 people.
    Ties at a cut are all flagged, so the flagged counts are returned too. The
    top-k overlap is None when ties make the worst set ambiguous.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size < 3:
        raise ValueError("stability needs at least 3 finite districts")
    kk = min(k, a.size)
    wa, wb = _worst(a, kk), _worst(b, kk)
    out = {
        "spearman": float(spearmanr(a, b).statistic),
        "kendall": float(kendalltau(a, b).statistic),
        "jaccard_top": (len(wa & wb) / len(wa | wb)) if wa is not None and wb is not None else None,
        "n": int(a.size),
    }
    for thr in thresholds:
        da = a > thr
        db = b > thr if b_minutes else _matched_flags(b, int(da.sum()))
        tag = int(thr)
        out[f"kappa_{tag}"] = _kappa(da.astype(int), db.astype(int))
        out[f"flagged_main_{tag}"] = int(da.sum())
        out[f"flagged_variant_{tag}"] = int(db.sum())
    return out


def weighted_by_district(values: np.ndarray, population: np.ndarray,
                         districts: np.ndarray, ids) -> np.ndarray:
    """Person-weighted mean of a grid value per district (NaN without people)."""
    d = np.asarray(districts).ravel().astype(np.int64)
    w = np.asarray(population, dtype=float).ravel()
    v = np.asarray(values, dtype=float).ravel()
    keep = (d > 0) & np.isfinite(v) & (w > 0)
    size = int(max(d.max(), max(ids))) + 1
    num = np.bincount(d[keep], weights=(v * w)[keep], minlength=size)
    den = np.bincount(d[keep], weights=w[keep], minlength=size)
    ids = np.asarray(ids, dtype=np.int64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den[ids] > 0, num[ids] / den[ids], np.nan)


def bootstrap_spearman(a: np.ndarray, b: np.ndarray, n_boot: int = 1000,
                       seed: int = 42) -> tuple[float, float]:
    """Percentile bootstrap CI of Spearman over districts."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(n_boot):
        idx = rng.integers(0, a.size, a.size)
        values.append(spearmanr(a[idx], b[idx]).statistic)
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))
