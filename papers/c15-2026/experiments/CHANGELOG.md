# Changelog

All notable changes to this project are documented in this file, in English
(Keep a Changelog style). This file is local-only and is never uploaded to
Drive `code/` (Drive holds runtime files only).

## [Unreleased]

### Changed
- Colab execution is now Drive-only: the notebook loads the runtime code
  snapshot from Drive `code/` (`shutil.copytree` to `/content/experiments`)
  instead of `git clone`/`git pull` via `GITHUB_TOKEN`.
- Retired `stage-generator/scripts/commit_push.sh` (moved to `scripts/legacy/`);
  Colab never runs `git`/`GITHUB_TOKEN`/`userdata` anymore.
- Added `scripts/sync_code_to_drive.py` (allowlist + denylist + `--dry-run`,
  local `.sync_history.json` for timestamp-only version correlation with
  Drive `outputs/logs/run-*.log` + `manifest_index.json`).
- Hardened denylist in `sync_notebook.py` and extended `validate_colab.py`
  with Drive-only asserts (`no_git`, `no_github_token`, `no_userdata`,
  `no_dotenv_file`, `single_drive_mount`, `uses_drive_code_snapshot`).
