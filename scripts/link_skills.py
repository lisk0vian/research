#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""link_skills.py — mirror .agents/skills/* into .claude/skills/* as links.

The canonical skills live in `.agents/skills/`. Claude reads them from
`.claude/skills/`, so instead of duplicating the files we point each entry at
the canonical folder:

    .claude/skills/<name>  ->  ../../.agents/skills/<name>

A junction is used on Windows (the same mechanism the `skills` CLI uses, since
real NTFS symlinks need admin/Developer Mode) and a relative symlink elsewhere.
The generated links are machine-local and gitignored, so every clone runs this
once:

    python scripts/link_skills.py

Usage:
    python scripts/link_skills.py            # create/refresh the links
    python scripts/link_skills.py --check    # verify only; exit 1 if missing/stale
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root  # noqa: E402


def lexists(path: Path) -> bool:
    """True if the path exists, without following a broken link."""
    return os.path.lexists(path)


def is_link(path: Path) -> bool:
    if not lexists(path):
        return False
    if path.is_symlink():
        return True
    try:
        os.readlink(path)
        return True
    except (OSError, ValueError):
        pass
    if os.name == "nt":
        st = os.lstat(path)
        return bool(getattr(st, "st_reparse_tag", 0))
    return False


def remove_link(path: Path) -> None:
    """Remove a symlink or junction (never a real populated folder)."""
    try:
        path.unlink()
        return
    except (FileNotFoundError, IsADirectoryError):
        pass
    try:
        os.rmdir(path)  # junctions and empty dirs
    except OSError:
        shutil.rmtree(path)


def make_link(source: Path, dest: Path) -> str:
    """Create dest -> source.

    Mirrors the `skills` CLI's own behaviour (src/installer.ts):
      - Windows: a junction with an absolute target (Node fs.symlink type
        'junction'). Real NTFS symlinks need admin/Developer Mode, so neither
        skills.sh nor this script uses them.
      - POSIX: a relative symlink, so the link survives a repo move.

    Returns the mechanism used ('symlink'|'junction').
    """
    source_abs = Path(source).resolve()
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dest), str(source_abs)],
            check=True,
            capture_output=True,
            text=True,
        )
        return "junction"
    relative = os.path.relpath(source_abs, Path(dest).parent)
    os.symlink(relative, dest, target_is_directory=True)
    return "symlink"


def main() -> int:
    ap = argparse.ArgumentParser(description="Link .agents/skills into .claude/skills.")
    ap.add_argument("--root", default=None)
    ap.add_argument("--force", action="store_true", help="replace an existing real folder")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="report missing/stale links and exit 1 without changing anything")
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    src_dir = repo / ".agents" / "skills"
    dest_dir = repo / ".claude" / "skills"
    if not src_dir.is_dir():
        raise SystemExit(f"ERROR: {src_dir} not found")

    wanted = {p.name for p in src_dir.iterdir() if p.is_dir()}

    if args.check:
        missing = [
            name for name in sorted(wanted)
            if not (dest_dir / name / "SKILL.md").is_file()
        ]
        stale = []
        if dest_dir.is_dir():
            stale = sorted(
                p.name for p in dest_dir.iterdir()
                if p.name not in wanted and lexists(p)
            )
        if missing:
            print(f"missing Claude links for: {', '.join(missing)}")
        if stale:
            print(f"stale Claude links: {', '.join(stale)}")
        if missing or stale:
            print("run: python scripts/link_skills.py")
            return 1
        print(f"OK: {len(wanted)} skill link(s) present in {dest_dir}")
        return 0

    print(f"Linking {src_dir} -> {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    return_code = 0

    for name in sorted(wanted):
        src = src_dir / name
        dest = dest_dir / name
        if lexists(dest):
            if is_link(dest):
                if not args.dry_run:
                    remove_link(dest)
            elif args.force:
                if not args.dry_run:
                    shutil.rmtree(dest)
            else:
                print(f"  skip {name}: real folder exists (use --force)")
                continue
        if args.dry_run:
            print(f"  would link {name}")
            continue
        try:
            how = make_link(src, dest)
            print(f"  linked {name} ({how})")
        except subprocess.CalledProcessError as exc:
            return_code = 1
            print(f"  FAILED {name}: {exc.stderr or exc}")

    # Remove stale links (target skill no longer exists).
    for dest in sorted(dest_dir.iterdir()):
        if dest.name in wanted or not lexists(dest):
            continue
        if is_link(dest) or args.force:
            print(f"  removing stale {dest.name}")
            if not args.dry_run:
                remove_link(dest)

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
