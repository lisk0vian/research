---
name: paper-zenodo
description: >
  Upload paper experiments to Zenodo to obtain a DOI for code citation.
  Use whenever the user wants to archive code to Zenodo, get a DOI for
  their paper's code, upload experiments to a repository, publish a
  reproducibility package, or mentions "zenodo", "doi for code",
  "archive code", "cite code", "deposit", "subir código a zenodo",
  "publicar código", "obtener doi", or "reproducibility package".
  Also trigger when the user asks to update a Zenodo deposit with a
  new version of their code.
---

# paper-zenodo

Upload a paper's `experiments/` directory (and Colab notebook) to Zenodo to
obtain a DOI that can be cited in the paper's references.

## Prerequisites

1. **Zenodo account**: the user needs an account at https://zenodo.org (or
   https://sandbox.zenodo.org for testing).
2. **API token**: create one at
   - Production: https://zenodo.org/account/settings/applications/tokens/new/
   - Sandbox: https://sandbox.zenodo.org/account/settings/applications/tokens/new/

   Store it in `.env` at the repository root:
   ```
   ZENODO_TOKEN=<production-token>
   ZENODO_SANDBOX_TOKEN=<sandbox-token>
   ```
3. **Paper must exist**: `papers/<slug>/manifest.yaml` must be present with
   `paper`, `title`, and `authors` fields.
4. **Experiments directory**: `papers/<slug>/experiments/` must contain the
   pipeline code. The Colab notebook at `notebooks/experiments.ipynb` is
   included automatically if present.

## Workflow

### Step 1 — Verify prerequisites

Before running the script, check that:
- The paper exists (`papers/<slug>/manifest.yaml`)
- `experiments/` has files
- The user has a Zenodo token (ask if not found in `.env`)

If the user doesn't have a token, guide them:
1. Go to https://sandbox.zenodo.org/account/settings/applications/tokens/new/
2. Create a token with `deposit:write` and `deposit:actions` scopes
3. Copy it to `.env` as `ZENODO_SANDBOX_TOKEN`

### Step 2 — Dry run (always first)

```bash
python scripts/paper_zenodo.py --slug <slug>
```

This shows:
- Which files will be uploaded
- Total size
- Generated metadata (title, creators, description)
- Writes `experiments/zenodo.json` as a local record

Review the output with the user. They can edit the description by:
- Passing `--description path/to/description.html`
- Or editing `experiments/zenodo.json` before upload

### Step 3 — Draft first (recommended: review on Zenodo before publishing)

```bash
python scripts/paper_zenodo.py --slug <slug> --draft --yes
```

This creates an **unpublished draft** on Zenodo: visible in the owner's
dashboard for review, but NOT public and its DOI NOT active. The script prints
the draft URL — open it in the browser so the user can see the files and
metadata exactly as Zenodo holds them.

The draft is recorded in `manifest.yaml` (`zenodo_status: draft`,
`zenodo_deposit_id`, `zenodo_draft_url`). Re-running `--draft --yes`
refreshes the draft's files with the current set.

### Step 4 — Publish when the user approves

```bash
python scripts/paper_zenodo.py --slug <slug> --publish --yes
```

**This activates a permanent DOI.** Confirm with the user before running.
After publishing, the script:
- Updates `manifest.yaml` (`zenodo_status: published`, `zenodo_doi`, …)
- Adds/updates a `@software{}` entry in `paper/references.bib`
- Updates `experiments/zenodo.json` with the DOI

Verify the DOI resolves: open `https://doi.org/<doi>` in a browser.

### Shortcut — direct publish (skip the draft)

Experienced users who already reviewed the dry-run can publish in one step:

```bash
python scripts/paper_zenodo.py --slug <slug> --production --yes
```

Add `--production` to any of the above for real DOIs on `zenodo.org`
(default is the `sandbox.zenodo.org` test instance).

## What gets uploaded

| Included | Excluded |
|---|---|
| All files in `experiments/` | `.env*`, `.gitignore` |
| `notebooks/experiments.ipynb` | `__pycache__/`, `.ipynb_checkpoints/` |
| | `outputs/` (regenerable) |
| | `*.pkl`, `*.h5`, `*.pt` (heavy models) |
| | `zenodo.json`, `AGENTS.md` |

## New version vs new deposit

- If `manifest.yaml` already has `zenodo_doi`, the script creates a **new
  version** of the existing deposit (same DOI base, new version number).
- If no `zenodo_doi` exists, it creates a **new deposit** with a fresh DOI.

Use `--version` to set the version string (default: `1.0.0`).

## Common issues

| Problem | Solution |
|---|---|
| No token found | Set `ZENODO_SANDBOX_TOKEN` or `ZENODO_TOKEN` in `.env` |
| Empty experiments/ | Check that the pipeline code exists; use `--source` for a custom dir |
| HTTP 401 | Token is invalid or expired — create a new one |
| HTTP 403 | Token lacks required scopes — needs `deposit:write` and `deposit:actions` |
| HTTP 422 | Metadata is invalid — check the dry-run output |

## Examples

```bash
# Dry-run for c26-2026
python scripts/paper_zenodo.py --slug c26-2026

# Upload to sandbox
python scripts/paper_zenodo.py --slug c26-2026 --yes

# Upload to production with custom version
python scripts/paper_zenodo.py --slug c26-2026 --production --version 2.0.0 --yes

# Custom source directory
python scripts/paper_zenodo.py --slug c15-2026 --source notebooks --yes

# JSON output (for scripting)
python scripts/paper_zenodo.py --slug c26-2026 --yes --json
```