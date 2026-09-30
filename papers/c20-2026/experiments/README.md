# Experiments for papers/c20-2026 (design v2.0, single station Huayao)

All modules read `config.yaml`. No hardcoded constants. Nothing here edits the
manuscript; numbers go to `../outputs/` as CSV/JSON only.

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

Environment is declared in `requirements-experiments.txt` (not installed yet).
Do not run the pipeline until the author confirms D2/D3/D4 defaults.
