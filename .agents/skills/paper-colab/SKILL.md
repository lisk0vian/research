---
name: paper-colab
description: >
  Create, change, sync or debug a paper's Colab notebook and pipeline run. Use
  whenever the task touches notebooks/experiments.ipynb, experiments/colab.yaml,
  run_all.py, Drive sync of pipeline code, a Colab run that failed, errors.log
  or status.json, or the user says "Colab", "notebook", "run all", "ejecutar
  todo", "the pipeline failed", or asks for the Colab URL. Reads COLAB.md first;
  the rules live there, not here.
---

# paper-colab

**Read `COLAB.md` at the repo root before doing anything.** It is the single
source for how the notebooks work and the rules for changing them (§7) and for
the pipeline (§7, "The pipeline contract"). This skill only lists the commands.

## Change a notebook

The notebook is generated. Never edit the `.ipynb`.

```bash
# edit papers/<slug>/experiments/colab.yaml (or scripts/paper_notebook.py for every paper)
python scripts/paper_notebook.py --slug <slug>           # regenerate notebook + README
python scripts/paper_notebook.py --slug <slug> --check   # exit 1 on drift
```

## Before syncing

```bash
pytest -m "not slow"
python scripts/paper_notebook.py --slug <slug> --check
python scripts/paper_validate.py
```

## Sync to Drive (in place)

```bash
python scripts/paper_drive_sync.py --slug <slug>                 # what changed
python scripts/paper_drive_sync.py --slug <slug> --print-calls   # uploadFile args
# run each call with the gdrive MCP uploadFile tool, then:
python scripts/paper_drive_sync.py --slug <slug> --mark-uploaded <remote> ...
```

- A new file is created once and its id recorded:
  `--record <remote> <file-id>`.
- New code files need the Drive `code/` folder id, recorded once as
  `--record code/ <folder-id>` (find it with `listFolder` on the project folder).
- Never upload anything under `outputs/`.
- Finish by giving the user the Colab URL, which `paper_notebook.py` prints.

## After the user's run

1. Read `MyDrive/<slug>/outputs/logs/status.json`, then `errors.log`, with the
   gdrive MCP (`listFolder` on `outputs/logs`, then `readTextFile`).
2. Empty `errors.log` means a clean session. Otherwise each block names its
   source (preflight, stage, report, notebook cell) and carries the traceback.
3. Open a stage log (`outputs/logs/<stage>.log`) only when `errors.log` points
   to it. Do not ask the user to paste notebook output.
