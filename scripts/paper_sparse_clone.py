#!/usr/bin/env python3
"""paper_sparse_clone.py — shallow clone of this repo limited to one paper.

`git clone` of the whole repo pulls every tracked folder (the legacy projects
`C20-202610-temperature/`, `C25-...`, `C26-...`, plus `templates/` and
`.agents/`). On Colab that is wasted time and disk for a run that only needs
the pipeline code.

`sparse-checkout` materialises just the requested paths, and `--depth 1` drops
the history, which is where the weight actually is (~159 MB on GitHub vs ~484
tracked files). `--filter=blob:none` keeps the objects lazy so unrelated blobs
are never fetched.

Everything here is per-clone client state (`core.sparseCheckout` in
`.git/config` + `.git/info/sparse-checkout`). It is NOT committeable, so this
script is the reproducible way to get a trimmed checkout. Run it on a fresh
clone (Colab, CI scratch dir) — never on a working repo, because enabling
sparse-checkout there removes the other folders from the worktree.

    python scripts/paper_sparse_clone.py --slug c20-2026 --dest /content/research

Data is not covered: `papers/*/data/raw/*` and `*.csv` are gitignored
(.gitignore), so `dataset.csv` must come from Drive or an upload.

Usage:
    python scripts/paper_sparse_clone.py --slug <slug> [--dest <dir>]
    python scripts/paper_sparse_clone.py --slug <slug> --check    # verify only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root  # noqa: E402

# The repo that owns this script. Used as the default because the clone
# destination is usually outside the repo (e.g. /content on Colab), so
# walking up from the cwd would not find it.
SCRIPT_REPO = Path(__file__).resolve().parents[1]

# Paths that a pipeline run needs. `paper/` is intentionally excluded: it is
# only needed to write the manuscript, not to run the code.
SPARSE_TEMPLATES = ("papers/{slug}/experiments", "papers/{slug}/notebooks")

# Present after a correct sparse clone; proves the checkout actually landed.
SENTINELS = ("experiments/config.yaml",)


def repo_slug(repo: Path) -> str:
    """Read the GitHub `owner/name` slug from the `origin` remote."""
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo, capture_output=True, text=True,
    )
    url = proc.stdout.strip()
    if not url:
        raise SystemExit("ERROR: no 'origin' remote found")
    url = url.removesuffix(".git")
    if url.startswith("git@github.com:"):
        return url.split("git@github.com:", 1)[1]
    if "github.com" in url:
        return url.split("github.com/", 1)[1]
    raise SystemExit(f"ERROR: cannot parse a GitHub slug from remote: {url}")


def sparse_paths(slug: str) -> list[str]:
    return [t.format(slug=slug) for t in SPARSE_TEMPLATES]


def clone_url(slug_from_remote: str) -> str:
    """HTTPS clone URL. The repo is public, so no token is involved."""
    return f"https://github.com/{slug_from_remote}.git"


def verify(dest: Path, slug: str) -> list[str]:
    """Return a list of problems; empty means the checkout is usable."""
    problems: list[str] = []
    if not (dest / ".git").is_dir():
        return [f"{dest} is not a git checkout"]
    paper = dest / "papers" / slug
    for rel in SENTINELS:
        if not (paper / rel).is_file():
            problems.append(f"missing sentinel: papers/{slug}/{rel}")
    for template in SPARSE_TEMPLATES:
        if not (dest / template.format(slug=slug)).is_dir():
            problems.append(f"missing sparse path: {template.format(slug=slug)}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", required=True, help="paper folder under papers/")
    ap.add_argument("--dest", default=None, help="clone destination (default: ./research-<slug>)")
    ap.add_argument("--root", default=None,
                    help="repo root to read the remote from (default: this repo)")
    ap.add_argument("--branch", default=None, help="branch to clone (default: remote HEAD)")
    ap.add_argument("--check", action="store_true",
                    help="verify an existing clone without cloning")
    args = ap.parse_args()

    if args.root:
        repo = Path(args.root).resolve()
    elif (SCRIPT_REPO / ".git").exists() and (SCRIPT_REPO / "papers").is_dir():
        repo = SCRIPT_REPO
    else:
        repo = find_repo_root()
    dest = Path(args.dest).resolve() if args.dest else (Path.cwd() / f"research-{args.slug}")

    if args.check:
        problems = verify(dest, args.slug)
        for p in problems:
            print(f"ERROR: {p}")
        if problems:
            print(f"run: python scripts/paper_sparse_clone.py --slug {args.slug} --dest {dest}")
            return 1
        print(f"OK: sparse checkout present for {args.slug} at {dest}")
        return 0

    if (dest / ".git").is_dir():
        print(f"already a checkout: {dest}")
        print("fetching + applying sparse paths")
        subprocess.run(["git", "fetch", "--depth", "1", "origin"], cwd=dest, check=True)
    else:
        slug_remote = repo_slug(repo)
        url = clone_url(slug_remote)
        print(f"cloning {url} (shallow, blobless) -> {dest}")
        cmd = ["git", "clone", "--filter=blob:none", "--sparse", "--depth", "1"]
        if args.branch:
            cmd += ["--branch", args.branch]
        cmd += [url, str(dest)]
        subprocess.run(cmd, check=True)

    paths = sparse_paths(args.slug)
    print(f"sparse-checkout set {' '.join(paths)}")
    subprocess.run(["git", "sparse-checkout", "set", *paths], cwd=dest, check=True)

    problems = verify(dest, args.slug)
    for p in problems:
        print(f"ERROR: {p}")
    if problems:
        return 1

    print(f"OK: {dest} has papers/{args.slug}/experiments and notebooks only")
    print(f"NOTE: data/raw/dataset.csv is gitignored and not part of this clone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())