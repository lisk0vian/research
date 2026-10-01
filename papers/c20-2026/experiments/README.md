# Experiments for papers/c20-2026 (design v2.0, single station Huayao)

All modules read `config.yaml`. No hardcoded constants. Nothing here edits the
manuscript; numbers go to `../outputs/` as CSV/JSON only.

> **This folder is single-station and will be refactored.** The design of record
> is five SENAMHI stations (2015–2024) with a station loop on top; see
> [`../DESIGN_DECISIONS.md`](../DESIGN_DECISIONS.md) §6 for the exact list of
> hardcoded locations and why the 112 tests here can survive the change. Stages
> `00`–`05` below ran on the Huancayo record and will have to run again.

## Order

1. `00_verify_source.py` — V1–V6 source checks (§2.1).
2. `01_qc_hourly.py` — hourly QC flags (§3.1), no target imputation.
3. `02_aggregate_daily.py` — local-day aggregation (§3.2) to `data/processed/`.
4. `03_climatology.py` — C2 primary + C1/C3 sensitivity, `sigma_h,q`, terciles (§7.1).
5. `04_make_issuances.py` — weekly eval issuances + daily training pool, 28-day embargo (§6, §12.2).
6. `05_features_local.py` — `X_L` anomalies (§7.2).
7. `06_features_largescale.py` — `G` with realistic latencies (§7.2).
8. `07_models.py` — Clim/Damp/Pers/Ridge_L/LG/GBM_L/LG, direct per horizon (§8).
9. `08_metrics.py` — MSSS/Murphy/CRPS grid/CRPSS/RPSS/PIT/reliability/coverage (§10).
10. `09_inference.py` — H1 CW + block bootstrap, H2, H3, Holm (§11).
11. `10_tables_figures.py` — contract T1–T4/F1–F4 (§14) from `outputs/` only.
12. `run_all.py` — ordered orchestrator; freezes `M*` + hyperparameters before B1–B2.

## Anti-leakage (§12)

Train-only climatologies/scalers/PCA/Damp coeffs per fold; 28-day embargo
including inner validation; predictors dated ≤ d plus §7.2 latencies; no ONI/ICEN;
a-priori C2, G list, quantile grid, bootstrap blocks, horizons; frozen `M*`.

## Stubs

- `secondary/` — §13 descriptive analyses (empty).
- `extensions/` — E1–E5 disabled via `extensions_enabled` (empty).

Environment is declared in `requirements-experiments.txt`.
Do not run stages 03+ until the author confirms D2/D3/D4 defaults.

## Status of stages 00-02 (implemented)

| Stage | Output | Result on the real dataset |
|---|---|---|
| `00_verify_source.py` | `outputs/tables/T1_completeness.csv` | V1-V6 run; V1 resolves `tz_of_source` as local civil |
| `01_qc_hourly.py` | `data/processed/hourly_qc.csv` | 700 `missing_source`, 9 `precip_event`, 0 destroyed by QC |
| `02_aggregate_daily.py` | `data/processed/daily.csv` | 2922 days, 2886 valid by `min_hours`, 36 rejected |
| `03_climatology.py` | `data/processed/daily_clim.csv` + `outputs/climatology/<fold>.json` | C2/C1/C3 per fold, variance explained 0.41-0.46 |
| `04_make_issuances.py` | `data/processed/issuances.csv` | 27742 rows: 52/51 weekly eval issuances per fold + embargoed daily training rows |
| `05_features_local.py` | `data/processed/features_<fold>.csv` | 22 local predictors, one row per (issue_date, horizon, fold) |

Findings that resolve open config questions:

- **V1 (timezone)**: the TT diurnal cycle peaks at 14:00 and troughs at 05:00,
  amplitude 12.97 degC. That is a local-civil cycle, so `tz_of_source` is
  resolved and **no UTC-to-local shift is applied** in `02`. If the series had
  been UTC, the trough would fall near 10:00-11:00; `00` flags that case as
  `REVIEW_shift_required`.
- **V3 (missing)**: gaps are **row-wise** (700 empty rows across all six
  variables at once, 91 distinct days), so they are provider gaps, not sensor
  faults. No sentinel codes are present.
- **QC does not destroy data**: the 9 events exceeding `step_TT_max_degC` are
  convective storms (TT drops ~9 degC while RR rises and HR jumps ~30 points),
  labelled `precip_event` and kept. Only `out_of_range` and `spike` zero a value.
- **V4**: 2018-01-01 to 2025-12-31, no day with fewer than 24 hourly records,
  and both blind years (2024, 2025) are fully present.

### The harmonic climatology leaves a seasonal residual out of sample

Measured on the Huancayo record, as the variance of the monthly-mean residual
over the total residual variance:

| | in sample | D1 2021 | D2 2022 | D3 2023 | B1 2024 | B2 2025 |
|---|---|---|---|---|---|---|
| C2 (K=3) | 0.012 | 0.097 | 0.110 | **0.235** | 0.137 | 0.110 |
| C3 (K=3 + trend) | 0.012 | 0.102 | 0.111 | 0.237 | 0.137 | **0.242** |
| K=1 | 0.149 | 0.154 | 0.283 | 0.425 | 0.290 | 0.242 |

Three consequences for how C2 and C3 are reported:

- **K=3 is justified by evidence, not convention.** K=1 leaves 0.149 in sample —
  the cycle at this site is flat through JJA, which one harmonic cannot carry.
  K=5 buys nothing over K=3.
- **C3 is not a neutral sensitivity.** It matches C2 in sample and is worse out of
  sample, sharply on B2 (0.242 against 0.110). The degradation is extrapolation:
  a linear trend over a short window extrapolates badly onto a test year.
  Report it as a bound on extrapolation error, not as an equal alternative.
- **The residual is a phase shift, not noise.** In D3 the monthly anomaly runs
  from −0.95 °C (June) to +0.99 °C (October). This is why
  `doy_sin_target_midpoint` reaches −0.48 against the D3 target: the model is
  reconstructing seasonal shape the harmonic missed. It is not a leak — `doy` is
  known far in advance and the fit is train-only — but it is not forecast skill
  either, and must not be reported as such.

Full evidence and the consequences for model choice are in
[`../DESIGN_DECISIONS.md`](../DESIGN_DECISIONS.md) §3.1–3.2.

### Climatologies are fitted per fold, never globally

`03` fits C2, C1 and C3 separately on each fold's own training window (D1 trains
2018-2020, B2 trains 2018-2024). A single global fit would let the blind years
enter the reference they are scored against and inflate MSSS_clim, which is why
`experiments/README.md` §12 requires train-only fitting per fold.

`data/processed/daily_clim.csv` therefore contains **only the evaluation years**
(2021-2025, one row per day, each row climatologised by the fold that tests it).
`daily.csv` is left untouched so the observed series and the reference stay
separable. Fold coefficients, `sigma_h,q` and tercile thresholds go to
`outputs/climatology/<fold>.json`.

### Issuances: one rule for dev and blind folds

`04_make_issuances.py` writes one row per `(issue_date, horizon, fold)`. Evaluation
issuances are weekly on `config.issuance.weekday` inside the fold's test year;
training issuances are daily and embargoed by `config.validation.embargo_days`.

An evaluation issuance whose target window ends after the fold's test year is
**dropped for every fold, dev and blind alike**. The late-December Monday is the
usual case: its W3-4 window lands in January. Dev folds used to keep such rows
with `n_valid_days = 0` while blind folds dropped them, which made the two
incomparable and inflated the row counts of the dev folds.

Anti-leakage is checked exhaustively: no target day is at or before its own
issuance, and no training target reaches the test year.

### Local predictors: one climatology per variable

`05_features_local.py` writes `data/processed/features_<fold>.csv`, one row per
`(issue_date, horizon, fold)`. Two properties carry the anti-leakage contract:

- **Trailing windows only.** Every window ends at `d` and looks backwards, so no
  feature can read its own target. `tests/test_features_local.py` asserts this by
  corrupting all observations after a cutoff date and checking the earlier
  features do not move: a forward leak would show up as suspiciously good skill
  and nothing else.
- **Per-fold anomalies, per variable.** Each variable gets its own harmonic fit
  on the fold's training window. DTR runs from ~10 degC in January to ~19 degC in
  July at this station with a different phase from temperature, so subtracting
  the *temperature* climatology would leave a seasonal artefact that reads as
  skill. Only `TT_mean` reuses `03`'s coefficients, verbatim, so the target built
  by `04` and the lags built here share one reference.

`A0_7d` is the trailing 7-day anomaly mean (METHODOLOGY §2). `config.yaml` lists
it separately from `TT_anom_mean_7_14_30`, but the 7-day member is the same
quantity, so it is emitted once under the `A0_7d` name rather than as two
perfectly collinear columns.

`config.predictors.min_window_coverage` (0.5) sets how much of a trailing window
must be valid for its mean to be used. Short windows become NaN; neither the
target nor its predictors are ever imputed.

## Running on Colab (Drive-only, update in place)

Code, notebook and data all live in Drive under the `c20-2026` folder. **Update,
never recreate**: uploading with `parentFolderId` mints a new Drive file, hence a
new Colab URL and a new runtime session, and accounts cap concurrent sessions.
Two files with the same name in `Drive/c20-2026/code/` are worse still: the
notebook copies that folder with `copytree`, so a stale stub can shadow the
implementation without any visible error.

Drive file ids live in `../.drive_ids.json` (gitignored; see
`.drive_ids.json.example`). Sync from the repo root:

```
python scripts/paper_drive_sync.py --slug c20-2026
python scripts/paper_drive_sync.py --slug c20-2026 --print-calls
```

The script emits the `uploadFile` arguments; the agent calls them through the
`gdrive` MCP (a Python script cannot call MCP tools). Every target with a known
id is uploaded with `fileId`, so the notebook keeps its URL and the Colab session
survives. If Drive already holds a file whose name matches a target but the
manifest has no id for it, the script refuses and prints the `--record` command
to fix it, instead of silently creating a duplicate.

MIME matters too: the notebook must be uploaded with
`application/x-ipynb+json`. With the default `application/octet-stream` Colab
does not treat it as a notebook and fails with `unexpected value md!`.

### Alternative: code by git sparse clone

If you prefer the code to come from git rather than Drive, a sparse shallow
clone also works. `papers/*/data/raw/*` and `*.csv` are gitignored, so
`dataset.csv` **never** comes from git and Drive is still needed for the data.

Measured on this repo: full shallow clone 48 MB, sparse clone 213 KB.

Cell order in the notebook:

1. Clone (from the local checkout of the repo):

   ```
   python scripts/paper_sparse_clone.py --slug c20-2026 --dest /content/research
   ```

   Or inline in Colab, without the script:

   ```
   git clone --filter=blob:none --sparse --depth 1 \
       https://github.com/lisk0vian/research.git /content/research
   cd /content/research
   git sparse-checkout set papers/c20-2026/experiments papers/c20-2026/notebooks
   ```

   The repo is public, so no token or Colab Secret is needed. `--depth 1` drops
   the history (159 MB on GitHub); `--filter=blob:none` keeps blobs lazy.

2. `pip install -r /content/research/papers/c20-2026/experiments/requirements-experiments.txt`

3. `drive.mount('/content/drive')` and copy `dataset.csv` into
   `<folder>/c20-2026/data/raw/` — already done in Drive (folder `c20-2026`).

4. Run `00` → `02` from `/content/research/papers/c20-2026/experiments`.

Never enable `sparse-checkout` on a full working repo: it removes the other
folders (`C26-…`, `templates/`, `.agents/`) from the worktree. The script only
creates fresh clones.
