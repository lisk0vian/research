# Experiments for papers/c20-2026 (design v2.0, single station Huayao)

All modules read `config.yaml`. No hardcoded constants. Nothing here edits the
manuscript; numbers go to `../outputs/` as CSV/JSON only.

> **This folder is single-station and will be refactored.** The design of record
> is five SENAMHI stations (2015–2024) with a station loop on top; see
> [`../DESIGN_DECISIONS.md`](../DESIGN_DECISIONS.md) §6 for the exact list of
> hardcoded locations and why the 112 tests here can survive the change. Stages
> `00`–`05` below ran on the Huancayo record and will have to run again.

## Order

1. `fetch_source.py` — download the raw CSV and record provenance (not a stage: `run_all.py` never calls it).
2. `00_verify_source.py` — V1–V6 source checks (§2.1).
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
| `04_make_issuances.py` | `data/processed/issuances.csv` | 27721 rows: 51/51/51/52/51 weekly eval issuances per fold (D1/D2/D3/B1/B2) + embargoed daily training rows |
| `05_features_local.py` | `data/processed/features_<fold>.csv` | 22 local predictors, one row per (issue_date, horizon, fold) |
| `run_all.py` | `outputs/logs/<stage>.log` + `run_all.log` | orchestrator 00→10; writes a header/footer log per stage |

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

## Daily workflow

The loop is: edit locally, check locally, commit, push to Drive, run in Colab
without reloading the notebook. Each step is one command.

**1. Edit and check locally.** The pipeline runs against a synthetic dataset, so
no stage needs the real 5 MB file:

```
cd papers/c20-2026/experiments
python _sample_data.py --years 2            # writes data/raw/dataset.csv (synthetic)
python run_all.py --to 05                   # full chain, seconds not minutes
python -m pytest ../tests -q                # the real check: 179 tests
```

The synthetic file is regenerated, never edited, and never cited. Its schema
comes from `config.sample_data.schema`; switching to the SENAMHI contract after
the multi-station migration is a config change, not a code change.

Use Python 3.12 locally, the version Colab runs. On 3.14 some dependencies have
no wheel and compile from source (`lxml` needs Visual C++), so a green local run
does not prove a green Colab run.

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
