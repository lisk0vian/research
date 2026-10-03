# Experiments for papers/c20-2026 (design v3.0, five SENAMHI stations)

All modules read `config.yaml`. No hardcoded constants. Nothing here edits the
manuscript; numbers go to `../outputs/` as CSV/JSON only. The design is in
[`../METHODOLOGY.md`](../METHODOLOGY.md); the reasons for each choice in
[`../DESIGN_DECISIONS.md`](../DESIGN_DECISIONS.md).

**Where things run.** Every stage runs on Colab through
`notebooks/experiments.ipynb`. Locally only the test suite runs (about 50 s, no
real data, no model training); nobody waits on a pipeline run on a laptop.

## Order

| Stage | Writes | Runs on |
|---|---|---|
| `fetch_source.py` (not a stage) | `data/raw/senamhi.csv` + `data/SOURCE.json` | CPU |
| `00_verify_source` | `outputs/tables/T1_completeness.csv` (V1–V6) | CPU |
| `01_qc_hourly` | `data/processed/hourly_qc.csv` | CPU |
| `02_aggregate_daily` | `data/processed/daily.csv` | CPU |
| `03_climatology` | `daily_clim.csv`, `outputs/climatology/<station>/<fold>.json` (TT_mean, TT_min, TT_max) | CPU |
| `04_make_issuances` | `data/processed/issuances.csv` | CPU |
| `05_features_local` | `data/processed/features/<station>/<fold>.csv` | CPU |
| `06_features_largescale` | `data/processed/largescale_daily.csv` (Niño 3.4/1+2, ROMI, as-of) | CPU, network |
| `07_models` | `outputs/models/preds_<exp>_<model>.csv`, `eval_index_<exp>.csv` | CPU |
| `07b_deep` | LSTM_LG and Chronos predictions | **GPU** |
| `07c_ensemble` | Ensemble predictions, `outputs/models/primary_model.json` (M*) | CPU |
| `08_metrics` | `outputs/models/scored_<exp>.csv`, `outputs/tables/metrics_long.csv` | CPU |
| `09_inference` | `T2_blind_skill.csv`, `T3_hypotheses.csv`, `T5_loso_gap.csv` | CPU |
| `10_tables_figures` | `T4_murphy.csv`, `T6_secondary_targets.csv`, `T7_conditional_skill.csv`, `outputs/figures/F1-F6.png` | CPU |

Sensitivity models carry an `@` suffix: `Ridge_LG@EC` and `GBM_LG@EC` (E/C
indices, R4), and in LOSO `@elev` and `@none` (static descriptors, R2). They
are scored and reported but never enter M* or the ensemble.

`run_all.py --fast` runs everything with tiny budgets (20 trees, one LSTM
epoch, 50 bootstrap replicates, no Chronos) to prove the wiring end to end; its
numbers are never cited. `--skip-dl` leaves out `07b_deep`.

Shared modules: `_common.py` (paths, config, IO, logging), `_harmonic.py`
(climatology maths), `_panel.py` (the modelling panel and the prediction
contract), `_scores.py` (CRPS, PIT, RPS, Murphy).

## Anti-leakage

- Climatologies, scalers, ridge alphas, residual SDs and every model are fitted
  on the fold's own training rows; the fold's test window is never seen.
- Training issuances are embargoed 28 days before the test window, so no
  training target reaches it.
- Large-scale predictors are joined as known on the issue date (Niño d−7,
  ROMI d−1). ONI, ICEN and OMI are excluded (centred filters read the future).
- LOSO trains on the other stations *and* on dates before the test window.
- Ensemble weights and M* come from the dev folds and are frozen in
  `primary_model.json` before 08-10 read any blind score.

## Status

All stages are implemented and covered by the light test suite
(`tests/test_v3_contracts.py`, `tests/test_models_pipeline.py`). No stage has
yet run on the real file under design v3; the first Colab run produces the
numbers. The notes below were measured on the superseded single-station
Huancayo data and are kept for their reasoning, not their values.

## Notes from the v2 (Huancayo) runs

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

## Daily workflow

The loop is: edit locally, check locally, commit, push to Drive, run in Colab
without reloading the notebook. Each step is one command.

**1. Edit and check locally.** Only the tests run here; they use in-memory
synthetic fixtures and finish in under a minute:

```
python -m pytest papers/c20-2026/tests -q
```

`_sample_data.py` can still write a synthetic `senamhi.csv` for a Colab smoke
run, but the pipeline itself is not run on a laptop.

**2. Commit.**

**3. Push only what changed.** From the repo root:

```
python scripts/paper_drive_sync.py --slug c20-2026                    # what changed
python scripts/paper_drive_sync.py --slug c20-2026 --print-calls      # the uploadFile args
# ...the agent calls those through the gdrive MCP...
python scripts/paper_drive_sync.py --slug c20-2026 --mark-uploaded <remotes...>
```

`--mark-uploaded` is a separate, deliberate step. This script cannot call the
MCP, so it never learns whether an upload succeeded; only the agent that ran the
calls knows. Marking optimistically would let one failed upload make a stale
file look current forever. `--all` forces a full re-upload and ignores the
recorded hashes.

**4. Run in Colab, no reload.** The notebook is generated by `build_notebook.py`
and never hand-edited. Run the refresh cell (it re-copies `code/` from Drive),
then use `paso()`:

```python
paso("03")                       # one stage
paso("03", "05")                 # several
paso(desde="03", hasta="05")      # inclusive range
```

Each stage is a subprocess, so the kernel holds no state between them and a
runtime recycle costs nothing but the pip install, which cell 9 skips once it
has run in that runtime.

**5. Read the result.** `outputs/run_meta.json` records which stages ran, from
which commit, with which library versions actually imported, and how long each
took. Per-stage logs are in `outputs/logs/<stage>.log` with the exit code and
elapsed time in the footer, and they survive the recycle because they live on
Drive.

### What works and what does not yet

| Piece | State |
|---|---|
| `run_all.py --only / --from / --to / --config` | works, prefixes resolved when unique |
| Atomic artefact writes | works; a crash mid-write leaves the previous file, not half a CSV |
| `EXP_ENV` validation, `EXP_CONFIG` override | works |
| `outputs/run_meta.json` | works, fixed filename |
| Synthetic local dataset | works, both schemas |
| Drive sync hashing, `--mark-uploaded` | works |
| `paso()` in the notebook, pip marker | works |
| Skip completed stages / `--force` | **not implemented.** Refused rather than shipped inert: a flag that silently does nothing is worse than a missing one. |
| `outputs/<run_id>/` per run | deferred; conflicts with the fixed-filename Drive contract |
| Data cache to `/content` | deferred to the multi-station work |
| Per-station output layout | deferred to the multi-station work |

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

### Logs: two contracts, one file

Every run of `run_all.py` writes `outputs/logs/<stage>.log`. Two kinds of log exist, and it matters which is which:

| | Where | Survives | Good for |
|---|---|---|---|
| Stage log | `outputs/logs/<stage>.log` on Drive | yes, past the runtime | reading a run you did not watch |
| Console | the notebook output | no — Colab recycles it | watching a run in progress |

The stage log is the one to trust later. It has a header (stage, command, start timestamp, `paths_report()`), the child's complete merged stdout/stderr, and a footer carrying the **exit code and elapsed time**. Read off Drive through the MCP, with no notebook and no console, you can tell which stage failed, why, and whether it was fast or slow.

`run_all.log` aggregates every stage of the current run. It is rewritten at the start of a full run and appended to by `--only`.

**The filename is fixed and the file is overwritten each run.** That is deliberate: a timestamped name would mint a new Drive file per run, and a new Drive file means a new Colab URL and a new runtime session, which the account caps. `scripts/paper_drive_sync.py` lists only the logs that exist, so a fresh clone syncs code only and a partly-run pipeline syncs exactly what it produced.

### Why the runner is Python and not `tee`

The obvious design is `python stage.py 2>&1 | tee outputs/logs/stage.log`, then an `echo "exit=$?"` footer. That does not work. The footer is written to the shell's stdout, which sits *downstream* of `tee`, so it never reaches the file; a footer written before the pipeline runs cannot know the exit code; and bash reports only the last command in a pipe unless `pipefail` is set.

So `_common.run_stage` owns the whole file. It streams the child's merged output line by line: ordinary lines go to the terminal verbatim and to the log with carriage returns collapsed and ANSI stripped; `#PROG` event lines are routed instead (below). That split is what keeps the file on Drive clean text while the console stays live.

Windows makes this non-obvious: the child's stdout is in text mode, so every newline arrives as `\r\n`, and a bare `\r` looks identical until you read the next byte. `_TerminalLineSplitter` treats `\r\n` as one terminator and a bare `\r` as a redraw, holding an unclassifiable trailing `\r` until the next chunk decides it. Getting this backwards does not error — it silently empties the log.

### Progress: children emit, readers draw

Every stage runs as a subprocess, and a pipe is not a TTY, so a `tqdm` bar drawn by the child cannot stay fixed in Colab's captured output: each `\r` refresh lands as its own line. Tuning bar arguments cannot fix that; the bytes are fine, the renderer is not.

The child therefore never draws. It emits machine-readable lines on stdout:

```
#PROG {"level": "fold", "n": 3, "total": 5, "desc": "D2", "unit": "fold"}
```

and whoever reads draws: the notebook cell with `tqdm.notebook` (fixed widgets), a local terminal with `tqdm.std`, the log with plain phase markers (`# progress D2: 3/5`). One protocol, three backends; `tqdm` is only ever a drawing library, never the source of truth. The contract lives in `experiments/_progress.py` and its tests in `tests/test_progress.py`.

Levels are `stage` (run_all over stages), `fold` (a stage over folds) and `step` (sub-fold work such as a per-model fit loop). The reader keeps one widget per level and reuses it across phases with a live `desc`, so many short phases become one bar that says where it is. Emission is throttled like `tqdm`'s `mininterval`: first event, `desc` changes and completion always go through.

`EXP_PROGRESS=off` silences the whole protocol (tests, CI). `config.progress` selects which levels get a bar; phase markers still reach the log for every level, so hiding a bar never hides the diagnosis.

### Provenance: `fetch_source.py`

Run it before stage 00. It resolves the source through the catalogue API rather
than pinning a URL, because the portal republishes these packages under new links
and a pinned link rots between submission and camera-ready.

It writes `data/SOURCE.json`: the package id, the exact resource URL, a sha256,
the byte count, the download timestamp, and a **station inventory read out of the
file itself**. The inventory is derived, never hardcoded — hardcoding five
station codes is how a provenance record starts disagreeing with the bytes it
claims to describe. The inventory records `ubigeo_raw` next to the padded
`ubigeo`, because the portal serves that column as a float and codes below
100000 arrive as `40514.0` with the leading zero already gone.

It also records what `config.yaml` *declares* next to what the file *contains*.
A mismatch between the declared station count or coverage and the real file is a
finding about the data, not a formatting detail, and the only way to notice is to
have both sides written down.

The CSV lands in `data/raw/` (gitignored, ~400k rows). `SOURCE.json` sits one
level up in `data/`, which is tracked: provenance is small and reviewable, data
is not.

```
python fetch_source.py            # download if missing, verify if present
python fetch_source.py --check    # verify the local file, no network
python fetch_source.py --force    # re-download regardless
```

`--check` is the one to use in CI or after a manual copy: it hashes the file and
compares against `SOURCE.json`, exiting non-zero on a mismatch. It never touches
the network, which is what makes it safe to run anywhere.

A download is atomic: bytes land on a `.part` name and are renamed only once
complete. A truncated CSV that looks present is worse than one that is absent,
because the next run hashes it, matches it against itself, and calls it good.

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
