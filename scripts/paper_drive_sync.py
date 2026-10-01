#!/usr/bin/env python3
"""paper_drive_sync.py — push a paper's Colab assets to Drive, in place.

The notebook and the pipeline code must be updated **in place** on Drive, not
recreated. Uploading with `parentFolderId` mints a new Drive file, which changes
its ID, which produces a new Colab URL and a new runtime session. With a limit
on concurrent Colab sessions that leaks them until the account refuses new ones.

So this script resolves every target to a Drive file ID first and always uploads
with `fileId`:

    local path            ->  Drive file ID (from .drive_ids.json)
    no entry, no clash    ->  create once, record the ID, never again
    no entry, name taken  ->  refuse (see "Refusing to duplicate" below)

Transport is per file through the MCP: a Python script cannot call MCP tools, so
this script emits the exact calls (or prints them) and the agent executes them.
`--print-calls` gives the literal JSON for each upload, keyed by file ID.

Usage:
    python scripts/paper_drive_sync.py --slug c20-2026            # plan
    python scripts/paper_drive_sync.py --slug c20-2026 --print-calls
    python scripts/paper_drive_sync.py --slug c20-2026 --record <relpath> <file-id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root  # noqa: E402

SCRIPT_REPO = Path(__file__).resolve().parents[1]

# MIME type Drive must report for Colab to recognise a notebook. Uploading
# without it yields application/octet-stream and Colab fails with
# "unexpected value md!" while parsing the file as something else.
NOTEBOOK_MIME = "application/x-ipynb+json"

# Files that go to Drive/<folder>/code/, mirrored into /content by the notebook.
CODE_SUFFIXES = {".py", ".yaml", ".yml", ".txt", ".md", ".jsonc", ".json"}
EXCLUDED_NAMES = {".env", ".env.example", ".sync_history.json"}
EXCLUDED_PARTS = {"__pycache__", ".ipynb_checkpoints", ".git"}
SKIP_PREFIXES = (".env", ".gitignore", "opencode.jsonc")

NB_REMOTE_NAME = "experiments.ipynb"
NB_REMOTE_DIR = ""  # notebook sits at the Drive folder root


def ids_path(paper: Path) -> Path:
    return paper / ".drive_ids.json"


def load_ids(paper: Path) -> dict:
    path = ids_path(paper)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: {path} must contain a JSON object")
    return data


def save_ids(paper: Path, ids: dict) -> None:
    ids_path(paper).write_text(
        json.dumps(ids, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def collect_code_files(paper: Path) -> list[Path]:
    """Files under experiments/ that belong in Drive <folder>/code/."""
    exp = paper / "experiments"
    out: list[Path] = []
    for p in sorted(exp.rglob("*")):
        if not p.is_file():
            continue
        if EXCLUDED_PARTS & set(p.relative_to(exp).parts):
            continue
        if p.name in EXCLUDED_NAMES:
            continue
        if p.name.startswith(SKIP_PREFIXES):
            continue
        if p.suffix not in CODE_SUFFIXES:
            continue
        out.append(p)
    return out


def target_specs(paper: Path) -> list[dict]:
    """Everything that must live on Drive, in upload order."""
    specs: list[dict] = []
    nb = paper / "notebooks" / NB_REMOTE_NAME
    if nb.is_file():
        specs.append({
            "remote": NB_REMOTE_NAME,
            "remote_dir": NB_REMOTE_DIR,
            "local": nb,
            "mime_type": NOTEBOOK_MIME,
            "is_notebook": True,
        })
    for p in collect_code_files(paper):
        specs.append({
            "remote": f"code/{p.relative_to(paper / 'experiments').as_posix()}",
            "remote_dir": "code",
            "local": p,
            "mime_type": None,
            "is_notebook": False,
        })
    return specs


def plan(paper: Path, remote_names: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Split targets into (updates, clashes).

    `remote_names` maps remote path -> Drive file id as Drive currently reports it,
    including repeats when two files share a name (only the MCP can list Drive,
    so the agent passes the raw listFolder result in via --remote-names). A target
    whose recorded id is not the id Drive actually holds is a *stale* record: the
    manifest points at a file that was replaced or deleted, and uploading with it
    would fail or write to the wrong place.

    Pass None to skip the checks.
    """
    ids = load_ids(paper)
    if remote_names is not None and not isinstance(remote_names, dict):
        remote_names = {name: None for name in remote_names}
    updates: list[dict] = []
    clashes: list[dict] = []
    stale: list[dict] = []
    for spec in target_specs(paper):
        file_id = ids.get(spec["remote"])
        entry = {**spec, "file_id": file_id}
        if remote_names is not None:
            live = remote_names.get(spec["remote"])
            present = spec["remote"] in remote_names
            if file_id and live and live != file_id:
                entry["live_id"] = live
                stale.append(entry)
                continue
            if file_id and not present:
                # Recorded but absent from the listing: the file is gone.
                entry["live_id"] = None
                stale.append(entry)
                continue
            if not file_id and present:
                clashes.append(entry)
                continue
        if file_id:
            updates.append(entry)
            continue
        updates.append(entry)
    return updates, clashes + stale


def print_calls(paper: Path, updates: list[dict], folder_id: str | None) -> None:
    """Emit the literal uploadFile arguments, one JSON object per target."""
    for spec in updates:
        args: dict = {"localPath": str(spec["local"])}
        if spec["file_id"]:
            # In place: keeps the Drive ID, hence the Colab session.
            args["fileId"] = spec["file_id"]
        else:
            args["parentFolderId"] = spec.get("parent_override") or folder_id
            args["name"] = spec["remote"].rsplit("/", 1)[-1]
            if spec["mime_type"]:
                args["mimeType"] = spec["mime_type"]
        print(json.dumps({"tool": "uploadFile", "arguments": args}))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--root", default=None, help="repo root (default: this repo)")
    ap.add_argument("--print-calls", action="store_true",
                    help="print the uploadFile JSON for each target")
    ap.add_argument("--record", nargs=2, metavar=("REMOTE", "FILE_ID"),
                    help="record an existing Drive file id in the manifest")
    ap.add_argument("--folder-id", default=None,
                    help="Drive folder id, defaults to $GDRIVE_FOLDER_ID")
    ap.add_argument("--remote-names", default=None,
                    help='JSON object of remote path -> file id as Drive holds it '
                         '(from listFolder), used to refuse duplicates and to '
                         'detect stale ids in the manifest')
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else (
        SCRIPT_REPO if (SCRIPT_REPO / "papers").is_dir() else find_repo_root())
    paper = repo / "papers" / args.slug
    if not paper.is_dir():
        raise SystemExit(f"ERROR: {paper} not found")

    if args.record:
        remote, file_id = args.record
        ids = load_ids(paper)
        ids[remote] = file_id
        save_ids(paper, ids)
        print(f"recorded {remote} -> {file_id} ({len(ids)} entries)")
        return 0

    folder_id = args.folder_id
    if not folder_id:
        import os
        folder_id = os.environ.get("GDRIVE_FOLDER_ID", "")

    remote_names = None
    if args.remote_names:
        raw = json.loads(args.remote_names)
        remote_names = dict(raw) if isinstance(raw, dict) else {n: None for n in raw}
        print(f"checking against {len(remote_names)} remote entry(ies) from Drive")

    updates, clashes = plan(paper, remote_names)
    print(f"paper: {paper}")
    print(f"manifest: {ids_path(paper)} ({len(load_ids(paper))} entries)")
    print(f"targets: {len(updates)} to sync")

    in_place = sum(1 for u in updates if u["file_id"])
    print(f"  in place (fileId): {in_place}")
    print(f"  new files:         {len(updates) - in_place}")

    if clashes:
        print("\nRefusing to proceed:")
        for spec in clashes:
            if spec.get("live_id"):
                print(f"  {spec['remote']}: stale id in manifest "
                      f"({spec['file_id']}), Drive now holds {spec['live_id']}")
            else:
                print(f"  {spec['remote']}: exists on Drive but no id in the manifest")
        print("\nEither case would leave a duplicate or a broken pointer: a new")
        print("Drive file mints a new Colab url and a new runtime session, and two")
        print("files with one name make the notebook's copytree pick arbitrarily.")
        print("Fix with:")
        print("  python scripts/paper_drive_sync.py --slug %s --record <remote> <file-id>"
              % args.slug)
        print("or delete the Drive copy first if it is genuinely obsolete.")
        return 1

    if args.print_calls:
        print()
        print_calls(paper, updates, folder_id)
    else:
        print("\nre-run with --print-calls to emit the uploadFile arguments")
        print("(MCP tools are called by the agent, not from Python)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())