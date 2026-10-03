# AGENTS.md — Contracts for AI Agents

> Moved here from `experiments/` (everything in `experiments/` is synced to Drive
> `code/`). Relative paths below are relative to `experiments/`. The notebook now
> follows the repo-wide Colab standard: **`COLAB.md` at the repo root supersedes
> the "one Colab cell per stage" and notebook-sync parts of this file.** The
> notebook is generated from `experiments/colab.yaml`; stages run through
> `experiments/run_all.py`.

Subfolder of a larger research project. Scope here is **Colab-executable code only**
(training, verification, metrics) plus its validation. The Q1 article lives outside
and consumes `outputs/`; never write paper content here. English for AI efficiency.

## 0. Lifecycle (the loop this repo serves)

`config.yaml` (intent, AI-readable) -> stages (one Colab cell each, resumable) -> Colab executes ->
`outputs/` + manifests -> auditor reviews (article-ready?) -> diagnose -> redo. Sub-loops: (a) **interruption**:
free Colab drops the tab, the stage logs to `outputs/logs/`, AI fixes, resume skips done stages via `is_done()`;
(b) **inter-cell deps**: cells resolve data paths via `config.yaml` + `manifest_index.json`, never hardcoded routes;
code/notebook uploads and edits go through the `gdrive` MCP only.

## 1. Stage Contract (`src/stages/base.py`)

```python
from abc import ABC, abstractmethod
class Stage(ABC):
    name: str            # unique registry key
    seccion_paper: str   # paper section (e.g., "3.1 Preprocessing")
    output_dir: str      # posix path as str via src.paths.OUTPUT_DIR, Stage creates dir if missing
    @abstractmethod
    def is_done(self) -> bool:
        """True if output exists on disk. If True, main.py skips (no recompute)."""
    @abstractmethod
    def run(self) -> dict:
        """Execute analysis. Return dict saved as manifest JSON and indexed."""
```

Rules (inherit `Stage` + `@register_stage`; `name` unique or `ValueError`):
- `output_dir` is posix `str` as `Path(OUTPUT_DIR, "<sub>").as_posix()` (`train` -> `models`,
  rest -> `tables`); `run()` returns a JSON-serializable `dict` (the manifest).

## 2. Metrics Convention

- Metric names always `snake_case`, consistent across runs (`accuracy`, `f1_macro`, `roc_auc`;
  never `Accuracy`, `F1-Macro`, `ROC AUC`). Applies to manifest keys, CSV columns, `quality_gates`.

## 3. Manifest Schema — No New Keys Without Downstream Update

- If Stage A produces `manifest["new_key"]`, all Stages B, C, ... reading A's manifest must be updated in same commit/PR to handle (or explicitly ignore) that key.
- `manifest_index.json` (`src/stages/indexer.py:actualizar_indice()`, dict `{stage: {seccion_paper, output_dir, manifest}}`)
  is the single source of truth for inter-stage communication. Never use fixed counts as truth.

## 4. TDD & Quality Gates

Thresholds in `config.yaml:quality_gates` are pipeline asserts, compared numerically by
`train.py:check_quality_gates` (never string bounds); results land in `manifest["quality_check"]` + `errors.json`.

When a model fails `quality_check`:

1. **Diagnose BEFORE touching code** (`train.py` or any training Stage), log in `diagnostic_log.md`
   (free text, append-only: tested / happened / discarded-next), then modify code.
2. **Never lower `quality_gate` to pass.** Placeholder `0.0` + TODO only until the first real run;
   calibrated gates change only with justification in `diagnostic_log.md` + commit message.
Flow: `fail quality_gate -> diagnostic_log.md -> fix train.py -> re-run stage -> verify quality_gate`

## 5. Configurable Paths (`src/paths.py`, `main.py`)

- Both do `load_dotenv()` and export `DATA_DIR`, `OUTPUT_DIR`, `GDRIVE_FOLDER_ID`, `GDRIVE_NOTEBOOK_ID`,
  `GDRIVE_NOTEBOOK_NAME` (default `experiments.ipynb`), `GDRIVE_PROJECT_ID` via `os.getenv` (defaults
  `../data`, `../outputs`). `GDRIVE_NOTEBOOK_NAME` is filename for `../notebooks/${GDRIVE_NOTEBOOK_NAME}`
  and Drive display name. Never duplicate `data/`/`outputs/`, never `gdrive://`, never hardcode the notebook name.
- Colab override only: `drive.mount('/content/drive')` -> `PROJECT_DIR=...` -> set `DATA_DIR`/`OUTPUT_DIR`
  envs **before** importing `src.stages`, then copy `code/` to `/content/experiments` + `pip install -r requirements.txt`.
  Drive-only: no `git`/`GITHUB_TOKEN`/`userdata`, no `load_dotenv(".env")` (secrets stay local-only, never uploaded).

## 6. Drive MCP (Client-Agnostic, Env-Centralized)

- MCP server `gdrive` is stdio `npx -y @piotr-agier/google-drive-mcp` (scope `drive` write) with env vars from
  `experiments/.env` (gitignored, see `.env.example`); verification is per-client (`opencode mcp list`, `claude mcp list`).
- Never hardcode IDs in docs/code — read them from `.env`. Transport per file, agent-side via MCP (a `.py` script cannot call MCP tools): runtime code to `code/` preserving relative paths (`parentFolderId:${GDRIVE_FOLDER_ID}/code` first, then `fileId`), notebook in place at Drive root via `fileId:${GDRIVE_NOTEBOOK_ID}` with no `parentFolderId`
  (allowlist `main.py`, `config.yaml`, `requirements.txt`, `src/**/*.py`, notebook; `.agents/skills/*/scripts/*.py` are local tooling, never uploaded; denylist `.env`,
  `CHANGELOG.md`, `diagnostic_log.md`, `*token*`, `*credential*`, `gcp-oauth*`). Pull is `Drive outputs/ -> local` mirror only. Invariant: Drive never pushes. Pipeline writes filesystem `outputs/`.
- Credentials: OAuth Desktop `~/.config/google-drive-mcp/gcp-oauth.keys.json` + `tokens.json` (scope `drive`, no billing).
  Drive changes are not manifests; document Drive-sourced data in `config.yaml` + `diagnostic_log.md`.

## 7. Pipeline Semantics (Declarative, No Fixed Counts)

- `feature_engineering.derive: auto`, `feature_selection` (6 methods, `consensus_threshold: 2`),
  `split` (6 temporal keys walk-forward) — counts are dynamic, published to the index.
  Never fix counts like 14/69/433. Selection-inside-train overlap is documented controlled overlap.
- `models` — `optuna_tpe trials:100` (except `dummy: null`), declarative `search_space`, `voting`/`stacking` ensembles.
- `outputs` — CSV tables, JSON manifests/metrics, PNG figures, PKL models. No XLSX.
  `source_of_truth: outputs/manifest_index.json#<stage>.manifest` (real registry name).

## 8. Logging & Gated Commits

- Logs -> `outputs/logs/run_*.log` + `errors.json` (under `OUTPUT_DIR`, MCP readable). Checkpoints for resume.
- Drive-only, no git in Colab: sync local edits to Drive `code/` via MCP `uploadFile` (emulated `--dry-run` first via `listFolder`/`search`; the server has no native flag).
  Timestamp-only version correlation (`.sync_history.json` + local `CHANGELOG.md` <-> Drive logs/index); on failure write logs + `diagnostic_log.md`, **do not sync**.
- `CHANGELOG.md` (English, Keep a Changelog) updated only on success from `manifest_index.json` diff.

## 9. Auditor (Outputs Reviewer, Job Role)

- After Colab returns `outputs/`, the **auditor** (`.opencode/agents/auditor.md`; Claude Code via `npx skills`)
  verdicts PASS or FAIL+diagnosis — never full CSVs (aggregates + index/`errors.json` whole + ≤50-row samples).
  Placeholders (`0.0`) are FAIL (uncalibrated), never PASS.
- Verdict appends to `diagnostic_log.md`; FAIL relaunches the loop at the culprit stage with the diagnosis attached.

## 10. Change Recipes (automate add/modify/update)

| Change | Touch | Run |
|---|---|---|
| New stage | `config.yaml` (if new keys) + `src/stages/<name>.py` | `exp-config` -> `exp-stages` (generate+validate) -> `exp-notebook` (sync cells) |
| New model | `config.yaml:models` + `train.py` metrics | `exp-config` (validate) -> `main.py --stage train` -> auditor |
| New metric | `train.py` + `config.yaml:quality_gates` + consumers | `exp-stages` (validate) -> train -> auditor; schema rule §3 applies |
| New gate | `config.yaml:quality_gates` (+ justification) | `exp-config` (validate) -> train (`quality_check`) -> auditor |

## 11. Skills & Agents (Project-Only)

- Skills canonical `.agents/skills`, chain `exp-config` (1/4) -> `exp-stages` (2/4) -> `exp-notebook` (3/4) -> `exp-docs` (4/4 terminal);
  `git-commits` is standalone (dependency-ordered commits, no chain step).
  References (zero copies) in `.claude/skills` via `npx skills`. `.opencode/skills` is a deprecated shim (`MOVED.md`).
- Agent `auditor` canonical `.opencode/agents/auditor.md` (Claude Code via `npx skills`; shell cannot create symlinks here).
  Notebook sync: local `../notebooks/${GDRIVE_NOTEBOOK_NAME}` -> Drive `GDRIVE_NOTEBOOK_ID` via MCP (`fileId`, in place at Drive root); pull is `Drive outputs/ -> local` mirror only, via MCP, never push from Drive.

| Component | File |
|---|---|
| Stage Registry | `src/stages/registry.py` (`@register_stage` raises on duplicate) |
| Global Index | `src/stages/indexer.py` (`actualizar_indice()`) -> `outputs/manifest_index.json` |
| Paths | `src/paths.py` (`DATA_DIR`, `OUTPUT_DIR` via `os.environ`) |
| Orchestrator | `main.py` (`--stage all \| <name>`) |
| Config | `config.yaml` (intent) + `manifest_index.json` (runtime truth) |
| MCP Drive | `experiments/opencode.jsonc` (`gdrive`) |
| Notebook | `../notebooks/${GDRIVE_NOTEBOOK_NAME}` <-> Drive `GDRIVE_NOTEBOOK_ID` |
| Skills | `.agents/skills/exp-{config,stages,notebook,docs}` + `git-commits` (standalone) |
| Auditor | `.opencode/agents/auditor.md` |
| Logs | `outputs/logs/` + `diagnostic_log.md` (+ local `CHANGELOG.md`) |
