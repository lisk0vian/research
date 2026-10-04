# Timings — c20-2026

How long each process takes, and how long to expect. `expected` is the
median of the *fresh* measured runs when there is one, else the a-priori
estimate in `timings.yaml`; the two are never blended. A measurement
goes stale when the stage's key or code changes (`fresh` in the JSON), and
the expectation then falls back to the estimate until a run re-measures it.
`⚠` marks a last run outside its estimate range.

Updated: 2026-10-04T00:20:51+00:00. Full history in `timings.json`.

## full mode

| stage | expected | source | last | median | p90 | n | stale | unit | per unit | vs estimate |
|---|---|---|---|---|---|---|---|---|---|---|
| 00_verify_source | 10.0 | estimate | 5.3 | — | — | 0 | 5 | — | — | ×0.53 |
| 01_qc_hourly | 15.0 | estimate | 7.31 | — | — | 0 | 3 | — | — | ×0.49 |
| 02_aggregate_daily | 10.0 | estimate | 4.34 | — | — | 0 | 3 | — | — | ×0.43 |
| 03_climatology | 15.0 | estimate | 5.23 | — | — | 0 | 6 | — | — | ×0.35 |
| 04_make_issuances | 60.0 | estimate | 37.6 | — | — | 0 | 4 | — | — | ×0.63 |
| 05_features_local | 420.0 | estimate | 376.76 | — | — | 0 | 3 | — | — | ×0.9 |
| 06_features_largescale | 10.0 | estimate | 1.2 | — | — | 0 | 2 | — | — | ×0.12 |
| 06b_dynamical | 1200.0 | estimate | 100.94 ⚠ | — | — | 0 | 1 | date | 4 | ×0.08 |
| 07_models | 4200.0 | estimate | 4115.64 | — | — | 0 | 1 | target_fold | 200 | ×0.98 |
| 07b_deep | 800.0 | estimate | 741.92 | — | — | 0 | 1 | fold | 120 | ×0.93 |
| 07c_ensemble | 15.0 | estimate | 7.52 | — | — | 0 | 1 | — | — | ×0.5 |
| 07d_cfs_benchmark | 15.0 | estimate | 6.6 | — | — | 0 | 1 | — | — | ×0.44 |
| 08_metrics | 20.0 | estimate | 13.66 | — | — | 0 | 1 | — | — | ×0.68 |
| 09_inference | 180.0 | estimate | 135.82 | — | — | 0 | 1 | — | — | ×0.75 |
| 09b_calibration | 15.0 | estimate | 5.57 | — | — | 0 | 1 | — | — | ×0.37 |
| 09c_chronos_diagnostic | 500.0 | estimate | 450.68 | — | — | 0 | 1 | — | — | ×0.9 |
| 09d_chronos_sensitivity | 450.0 | estimate | 400.19 | — | — | 0 | 1 | — | — | ×0.89 |
| 10_tables_figures | 10.0 | estimate | 5.01 | — | — | 0 | 1 | — | — | ×0.5 |

## current run

no run recorded yet.

