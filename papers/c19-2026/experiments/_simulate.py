# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Known-truth simulation for the RQ3 model (M8, stage 08).

Generates district-level death counts with a planted odds ratio per +60 min of
travel time, so the estimator can be checked for bias, coverage and false
positives against a truth the data cannot provide. Fitting belongs to the
outcome stage; this module only plants the truth.
"""

from __future__ import annotations

import numpy as np


def simulate_outcomes(times: np.ndarray, deaths: np.ndarray,
                      or_per_60: float = 1.0, baseline_odds: float = 0.1,
                      sd_district: float = 0.0, seed=None) -> np.ndarray:
    """Deaths outside a facility per district under a known access effect.

    P(outside) = expit(logit(baseline_odds) + log(or_per_60) * minutes/60 + u),
    u ~ N(0, sd_district). `deaths` are the district denominators.
    """
    times = np.asarray(times, dtype=float)
    deaths = np.asarray(deaths, dtype=int)
    if times.shape != deaths.shape:
        raise ValueError("times and deaths must have the same length")
    rng = np.random.default_rng(seed)
    logit = np.log(baseline_odds) + np.log(or_per_60) * (times / 60.0)
    if sd_district:
        logit = logit + rng.normal(0.0, sd_district, size=logit.size)
    p = 1.0 / (1.0 + np.exp(-logit))
    return rng.binomial(deaths, p)


def empirical_or(times: np.ndarray, deaths: np.ndarray,
                 cases: np.ndarray) -> float:
    """Crude OR between the upper and lower half of the time distribution.

    Used by the tests: with times 0 vs 60 and no district noise, it estimates
    the planted `or_per_60` directly.
    """
    times = np.asarray(times, dtype=float)
    deaths = np.asarray(deaths, dtype=float)
    cases = np.asarray(cases, dtype=float)
    high = times >= np.median(times)
    a = cases[high].sum()
    b = deaths[high].sum() - a
    c = cases[~high].sum()
    d = deaths[~high].sum() - c
    if b <= 0 or c <= 0:
        return float("nan")
    return float((a * d) / (b * c))


def death_level_outcome(times: np.ndarray, or_per_60: float,
                        baseline_odds: float = 0.1, seed=None) -> np.ndarray:
    """Binary outcome for each row, using that row's own exposure `times`."""
    rng = np.random.default_rng(seed)
    logit = np.log(baseline_odds) + np.log(or_per_60) * np.asarray(times, float) / 60.0
    return rng.binomial(1, 1.0 / (1.0 + np.exp(-logit)))


def run_validation(base: "pd.DataFrame", reps: int = 500,
                   or_values=(1.0, 1.1, 1.2, 1.5), seed: int = 42):
    """Fit the RQ3 estimator on known-truth replicates of `base`.

    Kept for the unit tests; the stage uses `run_design_validation`, which
    reuses one design matrix and is fast enough for 500+ replicates.
    """
    import pandas as pd

    from _outcome import fit_logit

    rows = []
    for value in or_values:
        for rep in range(reps):
            base["outside"] = death_level_outcome(
                base["mean_min"].to_numpy(), value, seed=seed + rep)
            result = fit_logit(base)
            rows.append({"or_planted": value, "rep": rep, **result})
    return pd.DataFrame(rows)


def run_cell_validation(cells, X, groups, reps=500,
                        or_values=(1.0, 1.1, 1.2, 1.5), district_sd: float = 0.5,
                        baseline_odds: float | None = None, seed: int = 42,
                        progress=None):
    """Known-truth simulation on aggregated cells, full size.

    Cells keep the real district x age x sex x cause denominators; the outcome
    adds a district random intercept with `district_sd` and uses the real
    baseline odds unless given. Same estimator as the main model.
    """
    import gc

    import pandas as pd

    from _outcome import fit_cell_design

    deaths = cells["deaths"].to_numpy(dtype=float)
    if baseline_odds is None:
        cases = float(cells["cases"].sum())
        baseline_odds = cases / max(deaths.sum() - cases, 1.0)
    districts = cells["ubigeo"].astype(str).unique()
    rng = np.random.default_rng(seed)
    if isinstance(reps, dict):
        plan = [(v, int(reps.get(v, reps.get("default", 500)))) for v in or_values]
    else:
        plan = [(v, int(reps)) for v in or_values]
    total = sum(n for _, n in plan)
    rows = []
    n = 0
    for value, n_rep in plan:
        for rep in range(n_rep):
            u = pd.Series(rng.normal(0.0, district_sd, len(districts)), index=districts)
            u_cell = cells["ubigeo"].astype(str).map(u).to_numpy()
            logit = (np.log(baseline_odds) + np.log(value) * cells["mean_min"].to_numpy() / 60.0
                     + u_cell)
            p = 1.0 / (1.0 + np.exp(-logit))
            cases = rng.binomial(deaths.astype(int), p)
            result = fit_cell_design(X, cases, deaths, groups)
            rows.append({"or_planted": value, "rep": rep, **result})
            n += 1
            if n % 50 == 0:
                gc.collect()
            if progress:
                progress(n, total)
    return pd.DataFrame(rows)
