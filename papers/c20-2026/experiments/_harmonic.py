"""Harmonic climatology primitives, shared by 03 (fitting) and 04 (applying).

`03` fits the coefficients and stores them per fold; `04` reconstructs the same
curve for training years that are absent from `daily_clim.csv`. Both must use
byte-identical maths, so the implementation lives here only once.

The design matrix evaluates the annual cycle on its own period (365.25 by
default), which is why `doy_fractional` may return 365 for Dec 31: day 365 and
day 0 are adjacent on the cycle, and the caller only needs continuity within a
year, not alignment to the period.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PERIOD_DAYS = 365.25


def doy_fractional(dates: pd.Series | pd.DatetimeIndex,
                   period: float = PERIOD_DAYS) -> np.ndarray:
    """Fractional day-of-year in [0, 366), counted from Jan 1 of its own year."""
    idx = pd.DatetimeIndex(dates)
    start = pd.to_datetime(dict(year=idx.year, month=1, day=1))
    return (idx - start).dt.total_seconds().to_numpy() / 86400.0


def design_matrix(doy: np.ndarray, k: int, period: float = PERIOD_DAYS,
                  trend: bool = False) -> np.ndarray:
    """Columns [1, sin(2pi m doy/p), cos(2pi m doy/p) for m in 1..k, (doy)]."""
    cols = [np.ones_like(doy)]
    for m in range(1, k + 1):
        cols.append(np.sin(2 * np.pi * m * doy / period))
        cols.append(np.cos(2 * np.pi * m * doy / period))
    if trend:
        cols.append(doy)
    return np.column_stack(cols)


def infer_k_and_trend(coef: np.ndarray) -> tuple[int, bool]:
    """Recover (K, has_trend) from a coefficient vector.

    Without a trend the length is 1 + 2K (odd); with a trend it is 2 + 2K (even).
    """
    n = len(coef)
    has_trend = (n - 1) % 2 == 1
    k = int((n - 1 - (1 if has_trend else 0)) // 2)
    return k, has_trend


def fit_harmonic(doy: np.ndarray, values: np.ndarray, k: int,
                 period: float = PERIOD_DAYS, trend: bool = False) -> np.ndarray:
    """Least-squares coefficients; NaN rows are dropped, never imputed."""
    mask = np.isfinite(doy) & np.isfinite(values)
    X = design_matrix(doy[mask], k, period, trend)
    coef, *_ = np.linalg.lstsq(X, values[mask], rcond=None)
    return coef


def eval_harmonic(coef: np.ndarray, doy: np.ndarray,
                  period: float = PERIOD_DAYS) -> np.ndarray:
    """Evaluate fitted coefficients."""
    k, has_trend = infer_k_and_trend(coef)
    return design_matrix(doy, k, period, has_trend) @ coef