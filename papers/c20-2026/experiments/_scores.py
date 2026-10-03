"""Scoring primitives shared by 07 (model selection), 08 (metrics) and 09 (tests).

Every model, deterministic or not, is stored on the same 19-level quantile grid
(`config.models.quantiles`), and every probabilistic score is computed from that
grid. Scoring Gaussian models analytically and quantile models numerically would
compare two different approximations of CRPS; one grid for all is what makes
the CRPSS columns comparable (METHODOLOGY §7).

Numpy only, so the metrics stage runs without any modelling dependency.
"""

from __future__ import annotations

import math

import numpy as np

QUANTILE_COLS_FMT = "q{:02d}"


def quantile_columns(levels) -> list[str]:
    """[0.05, 0.10, ...] -> ['q05', 'q10', ...]."""
    return [QUANTILE_COLS_FMT.format(int(round(float(q) * 100))) for q in levels]


def rearrange(q: np.ndarray) -> np.ndarray:
    """Fix quantile crossing by sorting along the last axis (Chernozhukov et al. 2010).

    Sorting is the rearrangement estimator: it never worsens the quantile score
    and leaves non-crossing predictions untouched.
    """
    return np.sort(np.asarray(q, dtype="float64"), axis=-1)


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, |err| < 1.2e-9)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > hi:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def gaussian_quantiles(mu, sigma, levels) -> np.ndarray:
    """(n,) means and SDs -> (n, K) quantiles on the grid."""
    z = np.array([_norm_ppf(float(q)) for q in levels])
    mu = np.asarray(mu, dtype="float64")[:, None]
    sigma = np.asarray(sigma, dtype="float64")[:, None]
    return mu + sigma * z[None, :]


def pinball(y, q, levels) -> np.ndarray:
    """(n,) obs, (n, K) quantiles -> (n, K) pinball losses."""
    y = np.asarray(y, dtype="float64")[:, None]
    tau = np.asarray(levels, dtype="float64")[None, :]
    diff = y - np.asarray(q, dtype="float64")
    return np.maximum(tau * diff, (tau - 1) * diff)


def crps_quantile(y, q, levels) -> np.ndarray:
    """CRPS approximated by twice the mean pinball loss over the grid.

    CRPS = 2 * integral_0^1 QS_tau dtau; the 19-level grid is the quadrature.
    It is not exact (about 5 % off the Gaussian closed form, tested), but it is
    the same rule for every model, which is what skill scores need.
    """
    return 2.0 * pinball(y, q, levels).mean(axis=1)


def cdf_from_quantiles(x, q, levels) -> np.ndarray:
    """F(x) by linear interpolation of the quantile function, row by row.

    Outside the grid the CDF is clamped halfway into the tail (0.025 / 0.975):
    the grid carries no information about how far the tail extends.
    """
    x = np.asarray(x, dtype="float64")
    q = np.asarray(q, dtype="float64")
    levels = np.asarray(levels, dtype="float64")
    lo_tail, hi_tail = levels[0] / 2, 1 - (1 - levels[-1]) / 2
    out = np.empty(len(x))
    for i in range(len(x)):
        row = q[i]
        if not np.isfinite(x[i]) or not np.all(np.isfinite(row)):
            out[i] = np.nan
        elif x[i] < row[0]:
            out[i] = lo_tail
        elif x[i] > row[-1]:
            out[i] = hi_tail
        else:
            # np.interp needs increasing xp; ties (a degenerate forecast) are
            # resolved by taking the middle of the tied band.
            out[i] = float(np.interp(x[i], row, levels))
    return out


def tercile_probs(t1, t2, q, levels) -> np.ndarray:
    """(n, 3) probabilities below t1, between, above t2."""
    p1 = cdf_from_quantiles(t1, q, levels)
    p2 = cdf_from_quantiles(t2, q, levels)
    return np.column_stack([p1, p2 - p1, 1 - p2])


def rps_terciles(probs: np.ndarray, obs_cat: np.ndarray) -> np.ndarray:
    """Ranked probability score for three ordered categories (0, 1, 2)."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(obs_cat)), obs_cat.astype(int)] = 1.0
    return np.sum((np.cumsum(probs, axis=1) - np.cumsum(onehot, axis=1)) ** 2, axis=1)


def murphy(f, o) -> dict[str, float]:
    """MSSS decomposition against the sample mean (Murphy 1988).

    MSSS = r^2 - (r - s_f/s_o)^2 - ((m_f - m_o)/s_o)^2: correlation, conditional
    bias and unconditional bias. Reported apart from MSSS_clim, whose reference
    is the out-of-sample climatology and therefore includes drift.
    """
    f = np.asarray(f, dtype="float64")
    o = np.asarray(o, dtype="float64")
    ok = np.isfinite(f) & np.isfinite(o)
    f, o = f[ok], o[ok]
    if len(f) < 3 or np.std(o) == 0:
        return {"r": np.nan, "cond_bias": np.nan, "uncond_bias": np.nan, "msss_sample": np.nan}
    so, sf = np.std(o), np.std(f)
    r = float(np.corrcoef(f, o)[0, 1]) if sf > 0 else 0.0
    cond = (r - sf / so) ** 2
    uncond = ((f.mean() - o.mean()) / so) ** 2
    return {"r": r, "cond_bias": float(cond), "uncond_bias": float(uncond),
            "msss_sample": float(r ** 2 - cond - uncond)}


def overlap_order(lag_start: int, lag_end: int, step_days: int = 7) -> int:
    """How many consecutive issuances share target days (HAC bandwidth floor)."""
    return max(0, int(math.ceil((lag_end - lag_start + 1) / step_days)) - 1)
