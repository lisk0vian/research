# COLAB.md: running a paper's pipeline on Colab

This guide is for the people who run the notebooks and for the AI agents that
change them. It is the single source for both: the `paper-colab` skill reads it
and repeats nothing. It applies to every paper: each one has an
`experiments/colab.yaml` (c15, c20, c21 and c26 today), and `paper_new.py`
creates it, with a ready `run_all.py`, for every new paper (`--no-colab` opts
out). `paper_validate.py` warns about a paper without one.

Each paper also has a short page, `papers/<slug>/notebooks/README.md`, with its
GPU requirement, what runs before the pipeline, and what every stage writes.

---

## 1. How to run a paper on Colab

1. Open the notebook from Drive: `MyDrive/<slug>/experiments.ipynb`, or the
   direct link the agent gives after every sync. Avoid Colab's "Recent" list;
   it can open an old copy.
2. If the paper needs a GPU: **Runtime → Change runtime type → T4 GPU → Save.**
   The notebook asks Colab for one already, but check it: without a GPU the
   notebook stops in cell 2 and says so.
3. **Runtime → Run all.** That is the whole procedure.

What to expect:

- The pipeline runs **once**. Only one cell launches it.
- Stages that already finished, with the same code, config and inputs, are
  **skipped**. After a disconnect, Run all picks up where the run stopped.
- The last cell prints the results, then either "no errors in this session" or
  the full error text, and stops with a red error.

## 2. What each cell does

Every notebook has the same six cells. They are generated, so they never drift
from one paper to another.

| Cell | What it does | Under "Run all" |
|---|---|---|
| 0. How to run | The three steps above. | read only |
| 1. Load the latest code from Drive | Mounts Drive, copies `code/` into the runtime, starts a new error log, prints the newest file and its time. **Re-run it after every agent sync.** | runs |
| 2. Check the runtime | GPU, dependencies (installed once per runtime), data download, quick probes. Any failure stops here, in seconds. | runs |
| 3. Run the pipeline | The only cell that runs the pipeline. Form fields: `MODE` (full / smoke) and `FORCE`. | runs once |
| 4. Run one step | Defines `step()` and `step_range()`. Every call is commented out. | runs nothing |
| 5. Results and errors | Text report, figures, then `errors.log`. | runs, raises if there were errors |

Running a single stage by hand: in cell 4, uncomment a line (`step("03")`), run
that cell, then comment it again. `step()` always re-runs the stages you name;
`step_range("07", "10")` skips the ones that are still current.

## 3. When something fails

Read one file: **`MyDrive/<slug>/outputs/logs/errors.log`**.

- It is emptied when cell 1 starts a session, and every failure of that session
  is appended to it: a failed check in cell 2, a stage that exited non-zero
  (with the end of its log, where the traceback is), the report, and any
  exception raised by a notebook cell.
- **Empty file = the last session had no errors.**
- `outputs/logs/status.json` says what each stage did (`ok`, `skipped`,
  `failed`, `not_run`) and which one failed. It tells a session that never
  started from one that ran clean.
- The full log of one stage is `outputs/logs/<stage>.log`; `errors.log` names it.

Options in cell 3:

- `FORCE`: re-run every stage even if it is current. Use it when an input
  changed in a way the fingerprint cannot see, such as a file edited by hand on
  Drive.
- `MODE = smoke`: tiny model budgets, to check the wiring end to end. Its numbers
  are never cited. A smoke run never counts as "done" for a full run from
  `smoke_from` (in `colab.yaml`) onward, the first stage whose work changes in
  smoke mode; the stages before it are shared, so a full run after a smoke run
  only redoes the stages that smoke actually cut short.

What "skipped" means: each successful stage leaves
`outputs/_state/<stage>.json` with a fingerprint of the stage file, the shared
modules (`shared_modules` in `colab.yaml`, by default `_*.py` and
`config.yaml`), the declared inputs (`state_inputs`), the mode (from
`smoke_from` on), and the previous stage's fingerprint. A change anywhere
upstream re-runs everything after it. A failed stage loses its state and so do
all stages after it. Deleting `outputs/_state/` forces a full run.

## 4. How the notebook is built

- `papers/<slug>/experiments/colab.yaml` declares the paper: title, Drive
  folder, GPU, pip packages, setup commands, probes, the run and report
  commands, and the stage list.
- `python scripts/paper_notebook.py --slug <slug>` writes
  `notebooks/experiments.ipynb` and `notebooks/README.md` from it.
  `--check` fails when either differs, and both `paper_validate.py` and
  `paper_drive_sync.py` run that check.
- `scripts/_colab_runtime.py` is the shared runtime behind cells 1–5 and the
  pipeline's resume and error log. There is one copy in the repo;
  `paper_drive_sync.py` uploads it as `code/_colab_runtime.py`.
- The sync updates every Drive file **in place**, by its file id. A new Drive
  file means a new Colab URL and a new runtime session, and the account caps
  concurrent sessions. Ids live in `papers/<slug>/.drive_ids.json`
  (gitignored), including `code/`, the folder new code files are created in.

## 5. Using Colab day to day

- **Open from Drive**, always the same file. Two notebooks with one name, or a
  copy opened from "Recent", is how a run ends up on stale code.
- **After an agent sync:** re-run cell 1 and check the "newest" line, which
  names the file and time the agent just uploaded. Then run cell 3, or Run all.
- **Read cell 2's output** the first time on a new runtime: it confirms the GPU,
  the dependencies and the data before anything long starts.
- **Disconnects:** reconnect, then Run all. Cell 1 re-copies the code and the
  pipeline skips the finished stages. Outputs, logs and state are on Drive, so
  nothing is lost with the runtime.
- **Quotas:** free Colab disconnects an idle session after about 90 minutes and
  any session after about 12 hours, and GPU time is rationed per account (Pro
  raises both). Google changes these numbers without notice. A long pipeline is
  split by resume, not by keeping one session alive forever.
- **Do not** run cells out of order on a fresh runtime: cell 3 needs cells 1
  and 2. Run all does the right thing.

## 6. Keeping the session alive (`KeepClicking`)

Some long runs outlast the idle timeout. This snippet clicks Colab's connect
button every minute so the session does not count as idle:

```js
function KeepClicking(){
  console.log("Clic para mantener viva la sesión");
  document.querySelector("colab-connect-button")
    ?.shadowRoot?.querySelector("#connect")?.click();
}
setInterval(KeepClicking, 60000);
```

**How to use it:** in the Colab tab, press F12 (or Ctrl+Shift+I) → Console →
paste → Enter. Chrome may ask you to type `allow pasting` first. It prints the
message once a minute. To stop it, run `clearInterval(<id>)` with the number
`setInterval` printed, or reload the tab.

**What it does and does not do:**

- It prevents the **idle** disconnect only.
- It does **not** lift the maximum session length (about 12 h free), GPU quotas,
  or a runtime that Google recycles for its own reasons.
- On a runtime that already disconnected, the click may open a new one, but a
  new runtime is empty: nothing re-runs until you run the cells.

**Limitations:**

- It only works while that browser tab stays open and the computer stays awake.
  Sleep, a closed lid or a closed tab stops it.
- It depends on Colab's page structure (`colab-connect-button`, `#connect`).
  When Google changes it, the snippet fails silently: no error, it just stops
  helping. Check that the console keeps printing.

**Risks:**

- Colab's terms discourage keeping runtimes alive without interaction.
  Accounts that do it a lot can get lower GPU priority or shorter quotas.
- On Pro, a forgotten tab keeps burning compute units.
- Use it only for a long run you are actually watching, and stop it when the
  run ends. The real protection against a lost session is resume plus
  `errors.log`: reconnect and Run all.

## 7. Rules for changing a notebook or a pipeline

For people and agents alike. `paper_validate.py` enforces the ones a script can
check.

1. **Never edit `experiments.ipynb` by hand.** Edit `colab.yaml` (or the skeleton
   in `scripts/paper_notebook.py`, which changes every paper), then regenerate.
2. **One run cell.** No other cell may launch the pipeline (`run_pipeline`,
   `run_all.py`, `%%bash`, `!python`). Optional actions are commented out or sit
   behind a form field that defaults to off.
3. **Keep the refresh cell (1) and the one-step cell (4).** They are part of
   the standard.
4. **Every cell must survive Run all** on a fresh runtime and on a recycled one:
   idempotent, and every read tolerates a file that is not there yet.
5. **Markdown is operational only**, in English: how to run, what a cell does.
   No methodology (it belongs in `METHODOLOGY.md` / `main.qmd`), no design
   history, no agent instructions.
6. **Preconditions fail hard in cell 2**: GPU, data, network, file formats. A
   long stage that depends on something fragile gets a probe in `colab.yaml`.
   Nothing is a warning.
7. **`outputs/` belongs to Colab.** Never upload logs, tables or state from a
   local machine over the Drive copy; it erases the record of the real run.
   `paper_drive_sync.py` does not offer them.
8. **No agent instructions in `experiments/`**: `AGENTS.md` and `CLAUDE.md` go
   in the paper folder. Everything in `experiments/` is copied to Drive and
   into the runtime; the sync skips local config (`.env`, `opencode.jsonc`),
   but keep secrets out of it anyway.
9. **Before a sync:** `pytest -m "not slow"`, then
   `python scripts/paper_notebook.py --slug <slug> --check`, then
   `python scripts/paper_validate.py`.
10. **Sync in place** with `paper_drive_sync.py` (§3 of AGENTS.md), then give the
    user the Colab URL (`paper_notebook.py` prints it).
11. **After the user's run, read `status.json` and `errors.log` first** through
    the gdrive MCP, then only the stage log they name. Do not ask the user to
    copy errors from the notebook.

### The pipeline contract

The command in `colab.yaml` `run` (normally `run_all.py`) must:

- accept `--mode full|smoke`, `--force`, `--only STAGE...` (always re-runs the
  named stages) and `--from/--to` (an inclusive range that skips current
  stages);
- run each stage as a subprocess with its own log in `outputs/logs/<stage>.log`;
- use `_colab_runtime.StageState` to skip current stages, and
  `_colab_runtime.RunLog` to append failures to `errors.log` and keep
  `status.json`, appending to the notebook's session when `COLAB_SESSION_ID` is
  set;
- print progress as `#PROG {json}` lines (level, n, total, desc), which the
  notebook draws as a live text bar per level (count, %, rate, time left) that
  keeps its last state when saved. Never print widget bars: they are saved at
  0 % and hide what ran;
- never keep every downloaded or computed chunk in memory until the end of a
  loop; release each one once written (Colab free has ~12 GB of RAM);
- stop at the first failed stage and mark the rest `not_run`.

**Don't write this yourself:** `_colab_runtime.stages_main()` implements the
whole contract. How each paper uses it:

| Paper | `run` | Stages |
|---|---|---|
| new papers, c21 | `run_all.py` from `templates/paper/run_all.py.template` (three lines) | every `NN_name.py` in `experiments/`, in filename order |
| c15 | `run_all.py`, an adapter | `main.py --stage <name>`, one per registered stage |
| c26 | `colab_run.py`, an adapter | the whole package as one stage, `pipeline` |
| c20 | `run_all.py`, its own (older, richer logs) | `NN_name.py`, through `_common.run_stage` |

An adapter only passes `stages`, `command(stage, force)` and `stage_file(stage)`
to `stages_main`. A new paper adds stages by adding `NN_name.py` files.
