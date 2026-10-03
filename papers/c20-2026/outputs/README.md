# outputs/

Machine-readable results (CSV/JSON/PNG only, no .xlsx). The pipeline writes them
on Drive (`MyDrive/c20-2026/outputs/`) when it runs on Colab; the files below are
copied back here as the numbers of record for the manuscript, so every claim in
`../manifest.yaml` points at a file in git.

| Path | Written by | Content |
|---|---|---|
| `tables/T1_completeness.csv` | 00 | source checks V1-V6 (V3 reviewed in METHODOLOGY.md §3) |
| `tables/metrics_long.csv` | 08 | every metric: experiment x target x model x horizon x role x scope |
| `tables/T2_blind_skill.csv` | 09 | blind skill per model and horizon, block-bootstrap 95 % CI |
| `tables/T3_hypotheses.csv` | 09 | H1-H4 tests, raw and Holm-adjusted p |
| `tables/T4_murphy.csv` | 10 | Murphy decomposition, blind |
| `tables/T5_loso_gap.csv` | 09 | leave-one-station-out gap (station-trained models only) |
| `tables/T6_secondary_targets.csv` | 10 | TT_min / TT_max and frost |
| `tables/T7_conditional_skill.csv` | 10 | skill by season, ENSO phase, MJO activity |
| `tables/T8_cfs_calibration.csv` | 07d | CFSv2 calibration (A1) |
| `tables/T9_calibration.csv` | 09b | M* spread recalibration and ensemble without Chronos (A2, post hoc) |
| `tables/T10_chronos_diagnostic.csv` | 09c | Chronos daily paths: calibration, persistence, aggregation (A2) |
| `tables/T11_chronos_sensitivity.csv` | 09d | Chronos precision x input scale on D3, with CRPS (A2) |
| `figures/F1-F6*.png` | 10 | the manuscript figures |
| `models/primary_model.json` | 07c | M*, its dev CRPS and the ensemble weights, frozen before the blind folds |
| `manifest_index.json` | all | per-stage summaries and the paths above |
| `run_meta.json` | run_all | what the last run executed, with library versions |

Kept on Drive only (large or regenerable): per-model predictions and scored
rows (`models/preds_*.csv`, `models/scored_*.csv`, ~50 MB), stage logs,
resume state (`_state/`, `_checkpoints/`) and the per-fold climatologies.

CSV files are ignored by the repository's `.gitignore`; the tables here are
added with `git add -f`. To refresh them after a new Colab run, copy the same
files from Drive again.
