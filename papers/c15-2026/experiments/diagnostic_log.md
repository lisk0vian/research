# Diagnostic Log (append-only, local-only, never uploaded to Drive)

## 2026-09-16 — Lote-2: quality_gate check missing in train.py (C2)

What was tested:
- Loaded `config.yaml:quality_gates` (pre Lote-1: `min: CALIBRAR_TRAS_PRIMERA_CORRIDA` unquoted string; post Lote-1: `min: 0.0` placeholder with TODO).
- Inspected `src/stages/train.py:40,93-100`: `quality_gates = cfg.get(...)` is only archived into `manifest["quality_gates"]`; no numeric comparison, no `quality_check` key, no `errors.json`, no raise/warning.
- Inspected `../outputs/tables/train_manifest.json`: stale manifest still holds string gates and removed `lightgbm_optuna` model; metrics are placeholders `f1_macro: 0.0`.
- Checked `diagnostic_log.md` (missing) and `../outputs/logs/` (empty, no `errors.json`).

What happened:
- With string gates, any `metrics[m] < gates[m]` comparison would raise `TypeError` (str vs float). No check runs, so pipeline silently passes with placeholder metrics.
- With Lote-1 numeric placeholder `0.0`, placeholders pass trivially (`0.0 >= 0.0`) but must be flagged as uncalibrated, not treated as real pass.

What is discarded next:
- Discarded: lowering `quality_gate` to make check pass (forbidden by AGENTS.md:4). Placeholder `0.0` is loosest possible and explicitly marked TODO, not a calibrated threshold.
- Discarded: crashing the run on gate failure for now; placeholders would fail any real gate, blocking Colab readiness. Decision: non-blocking warning + `manifest["quality_check"]` + `outputs/logs/errors.json`, to be tightened after first real run.
- Next: implement `quality_check()` in `train.py` (numeric range check per model/metric, placeholder-aware), write `errors.json` on failure, add `quality_check` to manifest, then re-run train validation.

## 2026-09-16 — Lote-2 verification: quality_check implemented and green

What was tested:
- Unit cases for `check_quality_gates`: placeholder pass (0.0 vs 0.0-1.0), string-gate fail without crash, out-of-range fail, missing-model fail, real-value pass with placeholders=False. All 5 passed.
- Forced `TrainStage().run()` + `actualizar_indice(train)`: manifest now holds `quality_check: {passed:true, failures:[], placeholders:true}`, models list without `lightgbm_optuna`, numeric gates from Lote-1 config.

What happened:
- Run prints `[warn] quality_gate passed on placeholder metrics (0.0); calibrate gates after first real run` — non-blocking as designed.
- `../outputs/tables/train_manifest.json` refreshed (old stale string gates + lightgbm_optuna gone).
- `../outputs/manifest_index.json#train.manifest` now includes `quality_check`.
- `../outputs/logs/errors.json` written with `{stage:train, quality_check:{passed:true,...}}`.

What is discarded next:
- Discarded: treating placeholder pass as calibrated success. Gates stay at `0.0 TODO_CALIBRAR` until first real Colab metrics populate f1_macro/roc_auc; then set numeric mins with justification here, never as shortcut.
- Next (Lote-3, not started): skills/scripts/env/output_dir mapping per Q11/Q13.

## 2026-09-16 — Lote-3: skills/scripts/env/output_dir (Q11/Q13/Q7)

What was tested:
- `validate_stage.py` (hardened AST) on all 6 stages: single_class, register_stage, inherits Stage, name/seccion/output_dir present, output_dir uses OUTPUT_DIR env, is_done/run present, run->dict. All OK.
- `validate_colab.py`: 13/13 OK including no_dotenv_file and no_hardcoded_id.
- `diff_stages.py`: registry 6 stages in sync with notebook, config models without lightgbm_optuna.
- Registry duplicate raises ValueError; `.env.example` has no IDs; `notebook.cells.json` uses `load_dotenv()`; `update_changelog.py` local-only with dict keys; `generate_stage.py` single-replace `, 1)`.

What happened:
- output_dir: 5 stages use `Path(OUTPUT_DIR, "tables").as_posix()` via `src.paths.OUTPUT_DIR`; train uses `Path(OUTPUT_DIR, "models").as_posix()`. Migrated `tables/train_manifest.json` + `train_metrics.csv` to `models/`; reindexed train to `../outputs/models`; all `is_done()` True, no backslashes.
- `notebook.cells.json`: `load_dotenv("experiments/.env")` -> `load_dotenv()` (aligns with sync denylist + validate_colab).
- `update_changelog.py`: removed OUTPUT_DIR copy (local-only per AGENTS.md:8), fixed `[:1]` truncation to full stage list, skip only on explicit `passed:false`/failures (errors.json always exists post-train).
- `.env.example`: IDs replaced with PASTE_ID_HERE, Drive URL comment removed.
- `config-editor/SKILL.md`: tgrep contradiction resolved (guardian uses tgrep internally), quality_gates docs updated to numeric 0.0 TODO + quality_check.
- `registry.py`: duplicate name now raises ValueError instead of silent overwrite.
- `validate_stage.py`: real AST checks instead of substring `str` heuristic.
- `generate_stage.py`: replace only output_dir subfolder `, "tables")` once.
- `sync_notebook.py` canonical/mirror headers added (scripts/ canonical, skills copy differs only in parents depth).

What is discarded next:
- Discarded: changing `--config` default in generate_stage.py (out of agreed scope).
- Discarded: rewriting missing-ref docs (README_Drive_MCP.md, ensure_drive.py, paper/manifest.yaml) beyond Lote-3 scope; left for follow-up audit.
- Next: final `main.py --stage all` re-run is optional (all is_done True, would skip); recommend `CHANGELOG.md` update from manifest diff on next success.

## 2026-09-16 — Skills redo: exp-{config,stages,notebook,docs} via skill-creator

What was tested:
- exp-config (1/4): temp-copy edits (test_year/external_year/consensus), new scripts/validate_config.py green on live config; old skill had no validator.
- exp-stages (2/4): new validate_stage.py 6/6 OK; generated probe scaffold uses posix Path(OUTPUT_DIR).as_posix() (old template used os.getenv inline); broken stage correctly rejected.
- exp-notebook (3/4): new validate_colab.py 13/13 OK; diff_stages in sync; canonical cells use bare load_dotenv(), no banned strings.
- exp-docs (4/4): denylist aborts token paths; --help fixed (ascii arrow broke cp1252); enable_plugins=False x2.

What happened:
- Canonical skills in .agents/skills/exp-{config,stages,notebook,docs}/, SKILL.md 47-71 lines each with chain frontmatter (step/total/prev/next) and pushy descriptions; references/ + scripts/ load on demand.
- .claude/skills/exp-* are symlinks (references, zero copies); .opencode/skills/ is a shim (MOVED.md) pending deletion.
- AGENTS.md:9 + Quick References updated to canonical locations.
- Fixed convert_to_markdown.py ascii arrow (also in experiments/scripts/ mirror) that crashed --help on Windows.

What is discarded next:
- Discarded: skill.sh installer file (user: use skills.sh directory/CLI references instead); numeric step in skill names (order lives in description + chain.next).
- Discarded: full skill-creator benchmark viewer (qualitative inline review sufficed for internal skills).
- Next: description optimization via skills.sh trigger evals (optional); delete .opencode/skills shim after one commit.

## 2026-09-16 — AGENTS.md rewrite: lifecycle + auditor + recipes (grilled Q1-Q11)

What was tested:
- Lifecycle §0 written from user description (config intent -> resumable stage-cells -> Colab -> outputs -> auditor -> diagnose -> redo; interruption + inter-cell-deps sub-loops).
- Stale claims fixed: registry duplicate now raises ValueError (was "silently overwrites"); output_dir posix via src.paths; train->models; quality_check exists; skills exp-* chain; line-number refs removed.
- Budget check: AGENTS.md 108 -> 129 lines (cap 130). English throughout.

What happened:
- New §0 Lifecycle, §9 Auditor (role .opencode/agents/auditor.md, aggregation+sampling contract, placeholders FAIL), §10 Change Recipes table (stage/model/metric/gate), §11 Skills & Agents.
- Created .opencode/agents/auditor.md (least-privilege bash set); Claude Code ref via npx skills (shell cannot create symlinks here — note in AGENTS.md:11).
- Removed path-guardian: deleted .opencode/agents/path-guardian.md, dropped opencode.jsonc task block, scrubbed delegation lines from exp-config/exp-stages/exp-notebook/exp-docs (direct tgrep/grep instead). Frozen .opencode/skills shim + this log keep historical mentions only.
- Removed stale .claude/skills/exp-* copies (MSYS cp fallback had duplicated content); .claude refs provision via npx skills, zero copies.

What is discarded next:
- Discarded: skill.sh installer file (user: skills.sh directory/CLI instead); c15-* prefix (user: exp-* reflecting experimentos); numeric step in names; review-q1/output-review/results-auditor names (user: job-role "auditor").
- Discarded: README_Drive_MCP.md resurrection (still missing; AGENTS.md now points at experiments/opencode.jsonc only).
- Next: delete .opencode/skills shim after one commit; optional skills.sh trigger-eval description optimization.

## 2026-09-16 — /exp validate: article-readiness audit (FAIL, culprit train)

What was checked:
- Read whole `outputs/manifest_index.json` (6 stages) + whole `outputs/logs/errors.json`.
- Aggregated `outputs/models/train_metrics.csv` (describe, counts, top/worst by f1_macro/roc_auc, NULLs) + `tables/*.csv` shapes; `figures/` + `predictions/` listed; no whole-CSV dump, no figure read (no anomaly needing visual context).
- Re-ran `train.py:check_quality_gates` numerically (min <= value <= max); ran `validate_config.py` (OK); verified `manifest_index.json#train.manifest` equals `models/train_manifest.json`.
- Checked manifest schema drift via grep for quality_check/quality_gates consumers (only train.py produces/consumes; no downstream break).

Aggregates observed:
- train_metrics.csv: 5 rows (logreg, svm_linear, xgboost, lightgbm, catboost); f1_macro mean 0.0 std 0.0 min 0.0 max 0.0; roc_auc identical; accuracy identical; NULLs 0; top/worst tie at 0.0.
- quality_check repro: {passed: true, failures: [], placeholders: true}; errors.json matches.
- quality_gates live: lightgbm f1_macro [0.0, 1.0], roc_auc [0.0, 1.0], numeric with TODO_CALIBRAR placeholder comment.
- feature_selection_votes.csv: 5 rows x 3 cols, votes=2 each, consensus True (threshold 2/6); split_map.csv 13 rows, 6 temporal keys intact; preprocessing_preview.csv 20x13 with 14 NULLs in especializada (pre-imputation, expected); feature_engineering_preview.csv 10x1; consolidation skipped:true, 9593 rows, 8 files; preprocessing leakage_check pass; feature_engineering 1 derived (ubigeo_pjfs_zscore).
- figures/: 0 files; predictions/: 0 files (expected pre-real-run; train.py creates dirs but writes no predictions/figures on placeholder path).
- validate_config.py: OK (9 keys, gates numeric, source_of_truth resolves). Index==disk for train: True.

Verdict:
- FAIL+diagnosis: uncalibrated, re-run training (culprit stage: train). Placeholder metrics 0.0 + placeholders:true are never PASS for the article per auditor contract, even though check_quality_gates passed:true technically.
- No schema drift; no config edit made here.

What is discarded next:
- Discarded: lowering quality_gate to pass (forbidden); marking placeholders as PASS (forbidden); dumping whole CSVs or reading figures without anomaly.
- Discarded: treating validate_stage.py FAILs (all 6 stages FAIL current hardened AST on uses_stage_io/logs_run_file/has_traceback/writes_manifest_atomically) as article-blocking here; that is stage-code debt for /exp update, not outputs evidence. Left for follow-up.
- Next: first real Colab run with optuna installed to populate f1_macro/roc_auc, then calibrate gates via /exp update with justification here + commit message. Proposed patch printed in audit output, not applied.

## 2026-09-16 — Lote-4: first real train run (P75/P25, blind replication)
- Implemented real TrainStage (temporal proxy target, randomized search on 2023,
  91-grid calibration on 2024, per-model manifests + sqlite-ready checkpoints).
  Config: data.target + leakage/collinear/metadata groups, paper-faithful
  optimizers (randomized base, TPE lgbm variant declared), trials 30 first-run,
  active [logreg, lightgbm], seeds 42.
- Tested: validate_config OK, validate_stage train 17/17 OK, diff/val colab green.
- Happened: local run `main.py --stage train --force` OK. Target q75_s=11.0,
  q25_t=0.9153, train prevalence 0.1376 (paper Table IV reports 14.0/14.4/20.2
  for train/test/ext; ours 13.8/14.2/20.1 — external check, never asserted).
  LightGBM test f1_macro 0.730 / roc_auc 0.837 / tau 0.74; logreg near-random
  (roc 0.48). quality_check {passed:true, placeholders:false}.
- Next (needs approval, not applied): calibrate quality_gates.lightgbm from this
  run (e.g. f1_macro min ~0.65, roc_auc min ~0.75) with this entry as
  justification; scale trials 30->100 + full active set (config-only).
- Debt: sklearn 1.9 deprecates penalty= in LogisticRegression — l1 trials may
  have run as l2 (UserWarning); map penalty->l1_ratio before the 100-trial run.

## 2026-09-16 — Lote-5: warnings fix + progress (post Colab run 195425)
- Colab run pulled to local mirror: quality {passed:true, placeholders:false};
  lightgbm test f1 0.7195/roc 0.834 tau 0.77 (local was 0.7299/0.837/0.74 —
  version drift sklearn 1.6.1 vs 1.9.1, lgbm 4.6 vs 4.7, seeds equal).
  Target prevalence 13.76% both. LogReg search-valid F1 0.1171 (saga
  ConvergenceWarning hurt it badly on Colab).
- Fix in train.py: StandardScaler fit on search_train only (saved
  models/train_scaler.pkl) + penalty->l1_ratio mapping for sklearn>=1.8 +
  live [progress] prints per trial/model/summary. Validated 17/17; smoke run
  in temp OUTPUT_DIR (mirror untouched): logreg test roc 0.483->0.686,
  f1 0.471->0.549 — convergence recovered.
- train.py synced to Drive code/ (in place). Next: Colab re-run WITH --force
  (per-model manifests exist, plain run would skip), then compare.

## 2026-09-16 — Lote-6: fixes reflected into config.yaml (declarative method)
- training.encoding {categorical: frequency_train_only, numeric:
  median_train_only, scale: standard_scaler_train_only}, training.compat
  {sklearn_penalty_to_l1_ratio: true}, training.progress
  {print_every_trial: true}. No paper numbers in config (blind replication).
- train.py consumes all three (scaler conditional w/ fail-fast on unknown
  method; l1_ratio mapping gated by flag + version detection; per-trial prints
  gated, model start/done/summary always). validate_config OK,
  validate_stage 17/17 OK, smoke run (temp OUTPUT_DIR, mirror untouched):
  logreg search F1 0.117->0.52 range, streaming [progress] confirmed.
- Synced config.yaml + train.py to Drive code/ (in place). Next: Colab
  re-run WITH --force.

## 2026-09-16 — Lote-7: --force did not force per-model resume (design gap)
- Tested: 3 Colab runs (20:15:20/20:15:41/20:17:05Z) executed NEW code
  (encoded+scaled line present) but logged resume skip for both models and
  rewrote the global manifest with OLD results. Root cause: main.py --force
  bypassed stage is_done but per-model resume inside train.py still skipped.
- Fix: main.py propagates STAGE_FORCE=1 on --force (single stage);
  train.py recomputes models when set (logged). Validated 17/17; smoke with
  primed manifests + STAGE_FORCE=1 recomputed both (no skips).
- Synced main.py + train.py to Drive code/ (in place). Next: Colab re-run
  SAME --force command; per-trial [progress] will stream this time.

## 2026-09-16 — Lote-8: force run trained on defaults, search silently skipped
- Tested: Colab 20:21Z run with STAGE_FORCE recomputed both models, but
  best_params={} in manifests. Root cause: STAGE_FORCE bypassed per-model
  manifest resume but NOT the trials-history resume (randomized) / sqlite
  study resume (optuna): full history meant 0 trials executed, best left as
  init defaults. Metrics were still real (defaults+scaler: logreg 0.574/0.687,
  lgbm 0.712/0.832) but NOT searched — misreported as searched.
- Fix: force clears trials history + optuna db; best always = argmax over full
  history (never init defaults). Validated 17/17; primed+forced smoke ran
  trial 1/30..30/30 per model with non-empty best_params.
- Synced train.py to Drive code/ (in place). Next: Colab re-run SAME --force;
  expect per-trial [progress] lines this time, then pull + verify.

## 2026-09-16 — Lote-9: first genuinely searched Colab run (20:26Z)
- Run log shows force-cleared histories + 30/30 trials per model, best from
  argmax. best_params recorded (lgbm: n_est 100/lr 0.18/leaves 20; logreg:
  C 0.001/l2). quality {passed:true, placeholders:false}; index==disk.
- LightGBM searched: valid F1-macro 0.7677/ROC 0.8862, test 0.6903/0.8330
  (tau 0.77), ext 0.7508/0.8601. LogReg test 0.5422/0.6815.
- External read (never asserted): ROC 0.886/0.833/0.860 vs paper Table
  0.897/0.798/0.866 — order + magnitude reproduced; test remains weakest in
  both. Search-valid best (0.7254) overestimates test (0.6903): honest gap,
  selection year does not fully transfer.
- Next (needs approval): calibrate gates from this run; scale trials->100 +
  full active set incl. lightgbm_optuna TPE + voting/stacking (config-only).

## 2026-09-16 — Lote-10: scale-up modules (gates + 100 trials + ensembles + notebook)
- Config: quality_gates.lightgbm calibrated from Lote-9 searched run
  (test f1 0.6903/roc 0.8330, valid 0.7677/0.8862) to f1 min 0.60 / roc min
  0.75 — floors below test with margin; this entry is the justification,
  never to be lowered. trials 30->100, active full 8 (6 base + voting +
  stacking), training.ensembles {voting, stacking, top_n 5, excl [svm_linear]}.
- train.py ensembles (subagent, integrated+reviewed): voting soft-average
  reusing base .pkls (no refit); stacking meta-logreg on 4 expanding
  YEAR-boundary OOF folds (fixed subagent TimeSeriesSplit row-chunk drift),
  per-fold checkpoints, atomic manifests train_voting/stacking_manifest.json.
  Resume/force/progress same contract. validate_stage 17/17.
- Notebook: pre-flight cell (lib versions + disk) + read-only progress table
  cell (manifests/trials/checkpoints) before train cell. validate_colab +
  diff green, denylist clean.
- Synced config.yaml + train.py + notebook to Drive code/ (in place). Next:
  Colab preflight -> train --force (expect ~1-3h; checkpoints resumable).

## 2026-09-16 — Lote-11: mixed snapshot in Colab + stale metrics CSV
- Tested: 20:40Z Colab run used NEW config (trials 100, active 8) but STALE
  train.py (log shows pre-ensemble skip line, gone locally). Likely causes:
  mount before sync finished, or Drive-Colab read-after-write cache lag.
  Mitigation stands: mount-cell freshness print (train.py size ~56KB+);
  if stale, wait 2-3 min and re-run mount.
- Same run exposed a real gap: train_metrics.csv was never rewritten by the
  new code (placeholder-era 5x0.0 survived). Fix: aggregate CSV rewritten
  every run from live metrics_test (atomic tmp+replace). Validated 17/17 +
  targeted CSV proof. Synced train.py to Drive code/ (in place).
- Real partial results kept: svm 0.567/0.687, xgb 0.701/0.832, lgbm_optuna
  0.715/0.830, catboost 0.702/0.841 (100 trials each). logreg/lightgbm still
  30-trial versions. No voting/stacking yet.
- Next: Colab mount (verify freshness) -> train --force (full 100-trial set
  + ensembles) -> pull + verify.

## 2026-09-16 — Lote-12: full scale-up verified (100 trials + ensembles)
- Colab 20:50Z run with fresh code: 6 base (svm/xgb/lgbm_optuna/catboost at
  100 trials; logreg/lightgbm kept 30-trial manifests via resume) + voting +
  stacking with YEAR-boundary OOF folds (n_valid 1142/1252/1272/1214 =
  2020/2021/2022/2023, exact year blocks). metrics CSV rewritten live (8 rows).
- Test: lgbm_optuna 0.715/0.830 (best F1), catboost 0.702/0.841, voting
  0.695/0.841 (tau 0.68), stacking 0.668/0.842 (tau 0.82, best ROC).
  quality {passed:true, placeholders:false}; gates (0.60/0.75) hold.
- Honest gaps: ensembles do NOT beat best base on test F1 (voting 0.695 <
  0.715; stacking 0.668); stacking trades F1 for ROC. Members top-5 excl svm
  matches paper selection. logreg/lightgbm still 30-trial versions.
- External read: ROC order+magnitude still tracks paper Table (0.897/0.798/
  0.866); test weakest in both worlds.
- Optional next: --force full re-run so logreg/lightgbm also train at 100
  trials (consistency); figures/ for the article (reliability diagram etc.).

## 2026-09-16 — Lote-13: phase 2.0 datalake (silver layer)
- Config storage block {raw_dir, silver_dir, silver_format, gold_dir,
  gold_format, dictionary} (method only, validator green). requirements.txt
  gains pyarrow (Colab pip cell covers it).
- consolidation.py rewritten to stage contract (_io logging, atomic manifest,
  strict is_done on silver). Writes data/silver/consolidated.parquet
  (9593x17, 67KB vs 1.4MB csv) + freezes 8 raw hashes + dictionary sha in
  data/checksums.json (warn-only on raw drift). Reuses consolidated.csv when
  present (skipped:true); dummy-CI path kept.
- Validator refined: own {stage}_preview.csv writes allowed (was false FAIL);
  sibling laterals still require load_upstream. consolidation + train 17/17.
- Tested: local --force run green. Deviation noted: gold matrices land in
  2.1 with real encoding (split needs it); 2.0 lays storage + silver only.
- Synced config.yaml + consolidation.py + requirements.txt to Drive code/
  (in place). Drive silver/ materializes on next Colab consolidation run
  (fast cell; batch with 2.1 or run anytime).
