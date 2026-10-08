#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_zenodo.py — upload paper experiments to Zenodo and get a DOI.

Creates a Zenodo deposit from a paper's ``experiments/`` directory (plus the
Colab notebook), publishes it, and records the DOI in ``manifest.yaml`` and
``references.bib``.

Three actions (dry-run is the default for all of them):

- **dry-run** (default): generates metadata, lists files, shows total size.
  Nothing is uploaded until ``--yes`` is passed.
- **draft** (``--draft --yes``): creates an unpublished deposit and uploads
  the files. It is visible in the owner's Zenodo dashboard for review, but it
  is NOT public and its DOI is NOT active. Repeat to refresh the files.
- **publish** (``--yes`` or ``--publish --yes``): publishes the deposit,
  activates the DOI, and records it in ``manifest.yaml`` + ``references.bib``.

Sandbox is the safe default.  ``--production`` publishes a real DOI.

Tokens are read from ``.env`` at the repository root (gitignored)::

    ZENODO_SANDBOX_TOKEN=<your-sandbox-token>
    ZENODO_TOKEN=<your-production-token>

Usage::

    python scripts/paper_zenodo.py --slug c26-2026                      # dry-run, sandbox
    python scripts/paper_zenodo.py --slug c26-2026 --yes                # upload + publish, sandbox
    python scripts/paper_zenodo.py --slug c26-2026 --production --yes   # upload + publish, production
    python scripts/paper_zenodo.py --slug c26-2026 --production --draft --yes    # draft only
    python scripts/paper_zenodo.py --slug c26-2026 --production --publish --yes  # publish the draft
    python scripts/paper_zenodo.py --slug c26-2026 --delete-draft --yes        # delete the draft
    python scripts/paper_zenodo.py --slug c26-2026 --source notebooks   # custom source dir
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402

SCRIPT_REPO = Path(__file__).resolve().parents[1]

# --- Zenodo endpoints --------------------------------------------------------

SANDBOX_BASE = "https://sandbox.zenodo.org"
PRODUCTION_BASE = "https://zenodo.org"

# --- File collection ---------------------------------------------------------

EXCLUDED_NAMES = {
    ".env", ".env.example", ".sync_history.json", ".drive_ids.json",
    "AGENTS.md", "CLAUDE.md", "zenodo.json",
}
EXCLUDED_PREFIXES = (".env", ".gitignore", "opencode.jsonc")
EXCLUDED_PARTS = {"__pycache__", ".ipynb_checkpoints", ".git", "outputs"}
HEAVY_EXTENSIONS = {".pkl", ".h5", ".pt", ".pth", ".onnx", ".bin", ".ckpt"}
NOTEBOOK_NAME = "experiments.ipynb"


# --- Helpers -----------------------------------------------------------------


def _dotenv_path(repo: Path) -> Path:
    return repo / ".env"


def _read_dotenv(repo: Path) -> dict[str, str]:
    """Read ``.env`` and return a dict of key=value pairs."""
    path = _dotenv_path(repo)
    if not path.is_file():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("\"'")
    return env


def _get_token(repo: Path, production: bool) -> str:
    """Resolve the Zenodo API token from env / .env."""
    env = _read_dotenv(repo)
    if production:
        token = os.environ.get("ZENODO_TOKEN") or env.get("ZENODO_TOKEN", "")
    else:
        token = (
            os.environ.get("ZENODO_SANDBOX_TOKEN")
            or env.get("ZENODO_SANDBOX_TOKEN", "")
        )
    return token


def _api_base(production: bool) -> str:
    return PRODUCTION_BASE if production else SANDBOX_BASE


def _api_request(
    method: str,
    url: str,
    token: str,
    *,
    json_body: dict | None = None,
    data: Any = None,
    files: Any = None,
    retries: int = 3,
) -> dict | list | None:
    """Make an API request with automatic retry on network errors.

    Uses stdlib ``urllib`` to avoid a ``requests`` dependency.
    """
    import urllib.error
    import urllib.request

    headers = {"Authorization": f"Bearer {token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            if files:
                # Multipart upload
                import io

                boundary = f"----PythonBoundary{int(time.time()*1000)}"
                headers.pop("Content-Type", None)
                body = io.BytesIO()
                for field_name, (filename, file_bytes, content_type) in files.items():
                    body.write(f"--{boundary}\r\n".encode())
                    body.write(
                        f'Content-Disposition: form-data; name="{field_name}"; '
                        f'filename="{filename}"\r\n'.encode()
                    )
                    body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
                    body.write(file_bytes)
                    body.write(b"\r\n")
                body.write(f"--{boundary}--\r\n".encode())
                headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
                req = urllib.request.Request(
                    url, data=body.getvalue(), headers=headers, method=method
                )

            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                if raw:
                    return json.loads(raw)
                return None

        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(
                f"Zenodo API error {exc.code}: {exc.reason}\n{error_body}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  retry {attempt + 1}/{retries} in {wait}s... ({exc})")
                time.sleep(wait)
            else:
                raise SystemExit(
                    f"Zenodo API failed after {retries} attempts: {last_error}"
                ) from last_error
    return None  # unreachable


# --- Metadata generation -----------------------------------------------------


def _load_authors(repo: Path, manifest: dict) -> list[dict]:
    """Resolve author details from ``authors/*.yaml``."""
    creators = []
    for entry in manifest.get("authors", []):
        author_id = entry.get("id", "")
        author_path = repo / "authors" / f"{author_id}.yaml"
        if not author_path.is_file():
            print(f"  WARNING: authors/{author_id}.yaml not found, skipping")
            continue
        author = load_yaml(author_path)
        creator: dict[str, str] = {"name": author.get("name", author_id)}
        if author.get("orcid") and author["orcid"] != "TODO":
            creator["orcid"] = author["orcid"]
        if author.get("affiliation"):
            creator["affiliation"] = author["affiliation"]
        creators.append(creator)
    return creators


def _auto_description(manifest: dict, paper_dir: Path) -> str:
    """Generate a basic HTML description from the manifest."""
    title = manifest.get("title", manifest.get("paper", "Research paper"))
    journal = manifest.get("journal", "")
    internal = manifest.get("internal_code", "")
    parts = [
        f"<p>Reproducibility package for the paper "
        f"<em>{title}</em>",
    ]
    if journal:
        parts[0] += f", submitted to <em>{journal}</em>"
    parts[0] += ".</p>"
    if internal:
        parts.append(
            f"<p>Internal code: {internal}. "
            f"Contains the analysis pipeline, Colab notebook, and experiment "
            f"configuration.</p>"
        )
    parts.append(
        "<p>A full run is reproducible via the included Colab notebook or "
        "local Python environment.</p>"
    )
    return "\n".join(parts)


def build_metadata(
    repo: Path,
    paper_dir: Path,
    manifest: dict,
    version: str = "1.0.0",
    description: str | None = None,
) -> dict:
    """Build the Zenodo deposit metadata dict."""
    creators = _load_authors(repo, manifest)
    title = manifest.get("title", manifest.get("paper", "Research code"))
    desc = description or _auto_description(manifest, paper_dir)
    year = datetime.now(timezone.utc).strftime("%Y")

    metadata: dict[str, Any] = {
        "title": title,
        "upload_type": "software",
        "version": version,
        "description": desc,
        "creators": creators,
        "license": "MIT",
        "keywords": [
            "reproducibility",
            "research code",
            manifest.get("journal", "academic"),
        ],
        "language": "eng",
        "access_right": "open",
        "publication_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # Enrich keywords from manifest if available
    if manifest.get("internal_code"):
        metadata["keywords"].append(manifest["internal_code"])

    return metadata


# --- File collection ---------------------------------------------------------


def collect_files(paper_dir: Path, source_dir: str = "experiments") -> list[Path]:
    """Collect files to upload from the source directory + notebook."""
    source = paper_dir / source_dir
    if not source.is_dir():
        raise SystemExit(
            f"ERROR: {source} not found.\n"
            f"Use --source <dir> to specify a different source directory."
        )

    files: list[Path] = []

    # Collect from source directory
    for p in sorted(source.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(source)
        # Check excluded parts in path
        if EXCLUDED_PARTS & set(rel.parts):
            continue
        if p.name in EXCLUDED_NAMES:
            continue
        if any(p.name.startswith(pref) for pref in EXCLUDED_PREFIXES):
            continue
        if p.suffix.lower() in HEAVY_EXTENSIONS:
            continue
        if p.stat().st_size == 0:
            continue  # Zenodo rejects empty files (.gitkeep placeholders)
        files.append(p)

    # Add the Colab notebooks if they exist (the pipeline one and, when a paper
    # declares it, the second notebook of paper_notebook.NOTEBOOKS).
    for name in (NOTEBOOK_NAME, "figures.ipynb"):
        nb = paper_dir / "notebooks" / name
        if nb.is_file() and nb not in files:
            files.append(nb)

    # The shared Colab runtime lives once in scripts/ and is imported by every
    # pipeline with a colab.yaml (run_all.py fails without it), so a package
    # of such a pipeline must carry it, as paper_drive_sync.py does for Drive.
    runtime = paper_dir.parents[1] / "scripts" / "_colab_runtime.py"
    if (source / "colab.yaml").is_file() and runtime.is_file() and runtime not in files:
        files.append(runtime)

    return files


def total_size(files: list[Path]) -> int:
    return sum(f.stat().st_size for f in files)


def _format_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


# --- BibTeX ------------------------------------------------------------------


def _bibtex_key(manifest: dict) -> str:
    """Generate a BibTeX key from the paper slug."""
    slug = manifest.get("paper", manifest.get("slug", "code"))
    return f"{slug}-code"


def _resolve_author_names(repo: Path, manifest: dict) -> str:
    """Build an 'and'-separated author string for BibTeX."""
    names = []
    for entry in manifest.get("authors", []):
        author_path = repo / "authors" / f"{entry['id']}.yaml"
        if author_path.is_file():
            author = load_yaml(author_path)
            names.append(author.get("name", entry["id"]))
    return " and ".join(names)


def update_references_bib(
    paper_dir: Path, manifest: dict, doi: str, repo: Path
) -> Path:
    """Add or update the Zenodo entry in references.bib."""
    bib_path = paper_dir / "paper" / "references.bib"
    key = _bibtex_key(manifest)
    authors_str = _resolve_author_names(repo, manifest)
    year = datetime.now(timezone.utc).strftime("%Y")
    title = manifest.get("title", "Research code")

    entry = (
        f"@software{{{key},\n"
        f"  title     = {{{title}}},\n"
        f"  author    = {{{authors_str}}},\n"
        f"  year      = {{{year}}},\n"
        f"  publisher = {{Zenodo}},\n"
        f"  doi       = {{{doi}}},\n"
        f"  url       = {{https://doi.org/{doi}}},\n"
        f"  howpublished = {{Zenodo}},\n"
        f"}}\n"
    )

    if bib_path.is_file():
        content = bib_path.read_text(encoding="utf-8")
        if key in content:
            # Replace existing entry
            import re

            pattern = rf"@software\{{{key},.*?\n\}}\n?"
            content = re.sub(pattern, entry + "\n", content, flags=re.DOTALL)
            bib_path.write_text(content, encoding="utf-8")
            return bib_path
        # Append
        with bib_path.open("a", encoding="utf-8") as f:
            f.write("\n" + entry + "\n")
    else:
        bib_path.write_text(entry + "\n", encoding="utf-8")

    return bib_path


# --- Manifest update ---------------------------------------------------------


def _set_manifest_keys(
    paper_dir: Path, updates: dict[str, Any], remove: list[str] | None = None
) -> None:
    """Set top-level keys in manifest.yaml, preserving everything else.

    A load/dump round-trip would strip comments and reformat the file, so each
    key is replaced in place (or appended at the end when missing). Only
    top-level ``key: value`` lines are touched; nested blocks are never parsed.
    """
    import re

    import yaml as _yaml

    remove = remove or []
    manifest_path = paper_dir / "manifest.yaml"
    lines = manifest_path.read_text(encoding="utf-8").splitlines(keepends=True)
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        match = re.match(r"^([A-Za-z0-9_]+):", line)
        if not match:
            out.append(line)
            continue
        key = match.group(1)
        if key in remove:
            continue  # drop stale key, keep the rest of the file untouched
        if key in pending:
            rendered = _yaml.dump(
                {key: pending.pop(key)},
                allow_unicode=True,
                default_flow_style=False,
            ).strip()
            newline = "\n" if line.endswith("\n") else ""
            out.append(rendered + newline)
        else:
            out.append(line)
    for key, value in pending.items():
        rendered = _yaml.dump(
            {key: value}, allow_unicode=True, default_flow_style=False
        ).strip()
        out.append(rendered + "\n")
    manifest_path.write_text("".join(out), encoding="utf-8")


def update_manifest_draft(
    paper_dir: Path,
    *,
    deposit_id: int,
    draft_url: str,
    reserved_doi: str,
    version: str,
) -> None:
    """Record an unpublished draft deposit in manifest.yaml."""
    updates: dict[str, Any] = {
        "zenodo_status": "draft",
        "zenodo_deposit_id": deposit_id,
        "zenodo_draft_url": draft_url,
        "zenodo_version": version,
    }
    if reserved_doi:
        updates["zenodo_reserved_doi"] = reserved_doi
    _set_manifest_keys(paper_dir, updates)


def update_manifest_published(
    paper_dir: Path,
    *,
    doi: str,
    record_id: int,
    record_url: str,
    version: str,
) -> None:
    """Record a published deposit in manifest.yaml."""
    _set_manifest_keys(
        paper_dir,
        {
            "zenodo_status": "published",
            "zenodo_doi": doi,
            "zenodo_deposit_id": record_id,
            "zenodo_record_url": record_url,
            "zenodo_version": version,
        },
        # Draft-only keys go stale the moment the DOI activates.
        remove=["zenodo_draft_url", "zenodo_reserved_doi"],
    )


# --- Deposit workflow --------------------------------------------------------


def _zenodo_filename(file: Path, paper_dir: Path, source_dir: str) -> str:
    """Build the name for a file inside the Zenodo deposit.

    Preserves the relative path structure with forward slashes.
    """
    source = paper_dir / source_dir
    if file.parent == paper_dir / "notebooks":
        return file.name          # notebooks sit at the deposit root
    try:
        return str(file.relative_to(source)).replace("\\", "/")
    except ValueError:
        return file.name          # shared files from outside the source (the runtime)


def _draft_browser_url(production: bool, draft_id: int) -> str:
    """URL to view or edit an unpublished deposit in the browser."""
    return f"{_api_base(production)}/deposit/{draft_id}"


def _reserved_doi(deposit: dict) -> str:
    """DOI Zenodo reserves for a draft (it activates only on publish)."""
    return (deposit.get("metadata") or {}).get("prereserve_doi", {}).get("doi", "")


def get_deposit(api: str, token: str, draft_id: int) -> dict:
    """Fetch a deposit by id, with a clear error if it is gone."""
    try:
        return _api_request("GET", f"{api}/deposit/depositions/{draft_id}", token)
    except SystemExit as exc:
        raise SystemExit(
            f"ERROR: cannot open deposit {draft_id}.\n"
            f"It may have been deleted, or its id in manifest.yaml is stale.\n{exc}"
        ) from exc


def _create_fresh_draft(api: str, token: str, metadata: dict, *, quiet: bool = False) -> dict:
    if not quiet:
        print("\n  Creating new deposit...")
    return _api_request(
        "POST",
        f"{api}/deposit/depositions",
        token,
        json_body={"metadata": metadata},
    )


def _create_new_version(
    api: str, token: str, record_id: int, *, quiet: bool = False
) -> dict:
    if not quiet:
        print(f"\n  Creating new version of deposit {record_id}...")
    resp = _api_request(
        "POST",
        f"{api}/deposit/depositions/{record_id}/actions/newversion",
        token,
    )
    # The new version starts as a draft; its id is in latest_draft.
    draft_id = resp.get("latest_draft", {}).get("id") or resp.get("id")
    if not quiet:
        print(f"  New version draft: {draft_id}")
    return get_deposit(api, token, draft_id)


def _upload_files(
    api: str,
    token: str,
    draft_id: int,
    *,
    paper_dir: Path,
    source_dir: str,
    files: list[Path],
    quiet: bool = False,
) -> None:
    if not quiet:
        print(f"  Uploading {len(files)} file(s)...")
    for i, fpath in enumerate(files, 1):
        fname = _zenodo_filename(fpath, paper_dir, source_dir)
        file_bytes = fpath.read_bytes()
        if not quiet:
            print(f"    [{i}/{len(files)}] {fname} ({_format_size(len(file_bytes))})")
        _api_request(
            "POST",
            f"{api}/deposit/depositions/{draft_id}/files",
            token,
            files={"file": (fname, file_bytes, "application/octet-stream")},
        )


def _set_metadata(
    api: str,
    token: str,
    draft_id: int,
    metadata: dict,
    version: str,
    *,
    quiet: bool = False,
) -> None:
    if not quiet:
        print("  Updating metadata...")
    metadata["version"] = version
    _api_request(
        "PUT",
        f"{api}/deposit/depositions/{draft_id}",
        token,
        json_body={"metadata": metadata},
    )


def delete_draft(api: str, token: str, draft_id: int, *, quiet: bool = False) -> None:
    """Delete an unpublished draft deposit (published records cannot be deleted)."""
    if not quiet:
        print(f"  Deleting draft {draft_id}...")
    _api_request("DELETE", f"{api}/deposit/depositions/{draft_id}", token)


def clear_draft_files(api: str, token: str, draft_id: int, *, quiet: bool = False) -> int:
    """Delete every file in a draft deposit. Returns how many were removed."""
    deposit = get_deposit(api, token, draft_id)
    remote = deposit.get("files", [])
    if not quiet:
        print(f"  Clearing {len(remote)} file(s) from draft {draft_id}...")
    for entry in remote:
        _api_request(
            "DELETE",
            f"{api}/deposit/depositions/{draft_id}/files/{entry['id']}",
            token,
        )
    return len(remote)


def publish_draft(api: str, token: str, draft_id: int, *, quiet: bool = False) -> dict:
    """Publish a draft deposit. Returns the published record."""
    if not quiet:
        print(f"  Publishing draft {draft_id}...")
    try:
        return _api_request(
            "POST",
            f"{api}/deposit/depositions/{draft_id}/actions/publish",
            token,
        )
    except SystemExit as exc:
        raise SystemExit(
            f"ERROR: could not publish draft {draft_id}.\n"
            f"It may already be published from the browser "
            f"(then its DOI is final: find it in your Zenodo dashboard).\n{exc}"
        ) from exc


def upload_to_zenodo(
    *,
    paper_dir: Path,
    manifest: dict,
    files: list[Path],
    metadata: dict,
    token: str,
    production: bool,
    version: str,
    source_dir: str,
    publish: bool = True,
    quiet: bool = False,
) -> dict:
    """Create (or reuse) a deposit, upload files, optionally publish.

    - Fresh paper: creates a new deposit.
    - ``zenodo_deposit_id`` set but no ``zenodo_doi``: an unpublished draft is
      waiting, so its files are replaced with the current set.
    - ``zenodo_doi`` set: starts a new version of the published record.

    With ``publish=False`` the deposit stays a draft: visible in the owner's
    Zenodo dashboard for review, but not public and its DOI not activated.
    """
    base = _api_base(production)
    api = f"{base}/api"
    existing_doi = manifest.get("zenodo_doi")
    existing_id = manifest.get("zenodo_deposit_id")

    if existing_doi and existing_id:
        if not publish:
            raise SystemExit(
                "ERROR: this paper is already published "
                f"({existing_doi}).\n"
                "--draft only prepares the FIRST deposit; new versions are "
                "published directly with --yes."
            )
        deposit = _create_new_version(api, token, existing_id, quiet=quiet)
        draft_id = deposit["id"]
        clear_draft_files(api, token, draft_id, quiet=quiet)
    elif existing_id and not existing_doi:
        deposit = get_deposit(api, token, existing_id)
        draft_id = deposit["id"]
        if not quiet:
            print(f"\n  Reusing unpublished draft {draft_id}...")
        clear_draft_files(api, token, draft_id, quiet=quiet)
    else:
        deposit = _create_fresh_draft(api, token, metadata, quiet=quiet)
        draft_id = deposit["id"]
        try:
            _upload_files(
                api, token, draft_id,
                paper_dir=paper_dir, source_dir=source_dir, files=files, quiet=quiet,
            )
            _set_metadata(api, token, draft_id, metadata, version, quiet=quiet)
        except SystemExit:
            # A failed upload must not leave an orphan draft behind: only an
            # unpublished deposit can be deleted, and this one just failed
            # before publishing, so removing it is always safe here.
            delete_draft(api, token, draft_id, quiet=quiet)
            raise

    if existing_id:
        _upload_files(
            api, token, draft_id,
            paper_dir=paper_dir, source_dir=source_dir, files=files, quiet=quiet,
        )
        _set_metadata(api, token, draft_id, metadata, version, quiet=quiet)

    deposit = get_deposit(api, token, draft_id)
    result: dict = {
        "deposit_id": draft_id,
        "draft_url": _draft_browser_url(production, draft_id),
        "reserved_doi": _reserved_doi(deposit),
        "file_count": len(files),
        "published": False,
    }

    if publish:
        record = publish_draft(api, token, draft_id, quiet=quiet)
        doi = record.get("doi", "") or result["reserved_doi"]
        record_id = record.get("record_id", draft_id)
        record_url = record.get("links", {}).get("html", f"{base}/record/{record_id}")
        result.update(
            {
                "doi": doi,
                "record_id": record_id,
                "record_url": record_url,
                "published": True,
            }
        )

    return result


# --- Main --------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--slug", required=True, help="paper slug (e.g. c26-2026)")
    ap.add_argument("--root", default=None, help="repo root (default: auto-detect)")
    ap.add_argument(
        "--source",
        default="experiments",
        help="source directory relative to paper (default: experiments)",
    )
    ap.add_argument(
        "--sandbox",
        action="store_true",
        default=True,
        help="use sandbox.zenodo.org (default)",
    )
    ap.add_argument(
        "--production",
        action="store_true",
        help="use zenodo.org (real DOI)",
    )
    ap.add_argument("--yes", action="store_true", help="execute upload (default: dry-run)")
    ap.add_argument(
        "--draft",
        action="store_true",
        help="create/refresh an unpublished draft instead of publishing",
    )
    ap.add_argument(
        "--publish",
        action="store_true",
        help="publish the draft recorded in manifest.yaml (needs --yes)",
    )
    ap.add_argument(
        "--delete-draft",
        action="store_true",
        help="delete the unpublished draft from Zenodo and clear manifest.yaml (needs --yes)",
    )
    ap.add_argument("--version", default="1.0.0", help="deposit version (default: 1.0.0)")
    ap.add_argument(
        "--description",
        default=None,
        help="path to HTML description file (default: auto-generate)",
    )
    ap.add_argument("--quiet", action="store_true", help="minimal output")
    ap.add_argument("--json", action="store_true", help="output result as JSON")
    args = ap.parse_args()

    production = args.production
    if production:
        args.sandbox = False

    # --- Resolve paths -------------------------------------------------------
    repo = Path(args.root).resolve() if args.root else (
        SCRIPT_REPO if (SCRIPT_REPO / "papers").is_dir() else find_repo_root()
    )
    paper_dir = repo / "papers" / args.slug
    if not paper_dir.is_dir():
        raise SystemExit(f"ERROR: paper not found: {paper_dir}")

    manifest = load_yaml(paper_dir / "manifest.yaml")
    if not manifest:
        raise SystemExit(f"ERROR: empty or missing manifest.yaml in {paper_dir}")

    if sum([args.draft, args.publish, args.delete_draft]) > 1:
        raise SystemExit(
            "ERROR: --draft, --publish and --delete-draft are mutually exclusive."
        )

    instance = "production" if production else "sandbox"
    if not args.quiet:
        print(f"paper:   {paper_dir}")
        print(f"source:  {paper_dir / args.source}")
        print(f"zenodo:  {instance} ({_api_base(production)})")

    # --- Publish an existing draft (no file collection needed) ---------------
    if args.publish:
        return _publish_flow(repo, paper_dir, manifest, production, args)

    # --- Delete an unpublished draft -----------------------------------------
    if args.delete_draft:
        return _delete_draft_flow(repo, paper_dir, manifest, production, args)

    # --- Load description if provided ----------------------------------------
    description = None
    if args.description:
        desc_path = Path(args.description)
        if not desc_path.is_file():
            raise SystemExit(f"ERROR: description file not found: {desc_path}")
        description = desc_path.read_text(encoding="utf-8")

    # --- Collect files -------------------------------------------------------
    files = collect_files(paper_dir, args.source)
    if not files:
        raise SystemExit(
            f"ERROR: no files found in {paper_dir / args.source}.\n"
            f"Check that the directory exists and is not empty."
        )

    size = total_size(files)
    if not args.quiet:
        print(f"\nfiles ({len(files)}):")
        for f in files:
            source = paper_dir / args.source
            if f.parent == paper_dir / "notebooks":
                rel = f"notebooks/{f.name}"
            else:
                try:
                    rel = str(f.relative_to(source)).replace("\\", "/")
                except ValueError:
                    rel = f"{f.name} (shared, from scripts/)"
            print(f"  {rel} ({_format_size(f.stat().st_size)})")
        print(f"\ntotal: {_format_size(size)}")

    # --- Build metadata ------------------------------------------------------
    metadata = build_metadata(
        repo, paper_dir, manifest,
        version=args.version, description=description,
    )

    existing_doi = manifest.get("zenodo_doi")
    if existing_doi:
        if not args.quiet:
            print(f"\nexisting DOI: {existing_doi}")
            print("  → will create a new version")
    elif manifest.get("zenodo_deposit_id"):
        if not args.quiet:
            print(f"\nexisting draft: {manifest.get('zenodo_draft_url')}")
            print("  → will refresh its files")

    # --- Save zenodo.json (always, even in dry-run) --------------------------
    zenodo_json = {
        "metadata": metadata,
        "files": [
            _zenodo_filename(f, paper_dir, args.source) for f in files
        ],
        "total_size_bytes": size,
        "instance": instance,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    zenodo_json_path = paper_dir / args.source / "zenodo.json"
    zenodo_json_path.write_text(
        json.dumps(zenodo_json, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if not args.quiet:
        print(f"\nzenodo.json written to: {zenodo_json_path}")

    # --- Dry-run: stop here --------------------------------------------------
    if not args.yes:
        print("\n--- DRY RUN ---")
        print("Review the metadata and files above.")
        print("  --yes              upload + publish")
        print("  --draft --yes      upload as an unpublished draft (review on Zenodo first)")
        if manifest.get("zenodo_deposit_id") and not manifest.get("zenodo_doi"):
            print("  --publish --yes    publish the draft recorded in manifest.yaml")
        if not production:
            print("To use real DOIs, add --production")
        return 0

    # --- Upload --------------------------------------------------------------
    token = _require_token(repo, production)

    if not args.quiet:
        action = "DRAFT" if args.draft else "UPLOADING"
        print(f"\n--- {action} TO {instance.upper()} ---")

    result = upload_to_zenodo(
        paper_dir=paper_dir,
        manifest=manifest,
        files=files,
        metadata=metadata,
        token=token,
        production=production,
        version=args.version,
        source_dir=args.source,
        publish=not args.draft,
        quiet=args.quiet,
    )

    if args.draft:
        if not args.quiet:
            print(f"\n  Updating manifest.yaml with draft {result['deposit_id']}...")
        update_manifest_draft(
            paper_dir,
            deposit_id=result["deposit_id"],
            draft_url=result["draft_url"],
            reserved_doi=result["reserved_doi"],
            version=args.version,
        )
        zenodo_json.update(
            {
                "status": "draft",
                "deposit_id": result["deposit_id"],
                "draft_url": result["draft_url"],
                "reserved_doi": result["reserved_doi"],
            }
        )
        zenodo_json_path.write_text(
            json.dumps(zenodo_json, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n{'='*60}")
            print("  DRAFT saved (NOT published, DOI not active)")
            print(f"  Review it at:")
            print(f"  {result['draft_url']}")
            if result["reserved_doi"]:
                print(f"  Reserved DOI (activates on publish): {result['reserved_doi']}")
            print(f"  Files:  {result['file_count']}")
            print(f"  Size:   {_format_size(size)}")
            print(f"{'='*60}")
            print("\nTo publish when ready:")
            print(f"  python scripts/paper_zenodo.py --slug {args.slug}"
                  + (" --production" if production else "")
                  + " --publish --yes")
        return 0

    return _finish_published(
        repo, paper_dir, manifest, production, args,
        result=result, size=size, zenodo_json=zenodo_json,
        zenodo_json_path=zenodo_json_path,
    )


def _require_token(repo: Path, production: bool) -> str:
    """Resolve the Zenodo API token or fail with setup instructions."""
    token = _get_token(repo, production)
    if not token:
        env_key = "ZENODO_TOKEN" if production else "ZENODO_SANDBOX_TOKEN"
        raise SystemExit(
            f"ERROR: no Zenodo token found.\n"
            f"Set {env_key} in .env or as an environment variable.\n"
            f"Get your token at: {_api_base(production)}/account/settings/applications/tokens/new/"
        )
    return token


def _publish_flow(
    repo: Path, paper_dir: Path, manifest: dict, production: bool, args: argparse.Namespace
) -> int:
    """Publish the draft deposit recorded in manifest.yaml."""
    deposit_id = manifest.get("zenodo_deposit_id")
    if manifest.get("zenodo_doi"):
        raise SystemExit(
            f"ERROR: already published ({manifest['zenodo_doi']}).\n"
            "To release a new version, re-run with --yes (without --publish)."
        )
    if not deposit_id:
        raise SystemExit(
            "ERROR: no draft deposit recorded in manifest.yaml.\n"
            "Create one first with --draft --yes."
        )
    draft_url = manifest.get("zenodo_draft_url") or _draft_browser_url(production, deposit_id)

    if not args.yes:
        print("\n--- DRY RUN ---")
        print(f"Would publish draft {deposit_id}:")
        print(f"  {draft_url}")
        print("Re-run with --yes to publish (the DOI activates).")
        return 0

    token = _require_token(repo, production)
    base = _api_base(production)
    record = publish_draft(f"{base}/api", token, deposit_id, quiet=args.quiet)
    doi = record.get("doi", "") or manifest.get("zenodo_reserved_doi", "")
    record_id = record.get("record_id", deposit_id)
    record_url = record.get("links", {}).get("html", f"{base}/record/{record_id}")
    version = manifest.get("zenodo_version", args.version)

    result = {
        "doi": doi,
        "record_id": record_id,
        "record_url": record_url,
        "deposit_id": record_id,
        "file_count": None,
        "published": True,
    }

    if not args.quiet:
        print(f"\n  Updating manifest.yaml with DOI {doi}...")
    update_manifest_published(
        paper_dir, doi=doi, record_id=record_id,
        record_url=record_url, version=version,
    )

    _update_bib(paper_dir, manifest, doi, repo, quiet=args.quiet)

    # The local record keeps the full history of what was published.
    zenodo_json_path = paper_dir / args.source / "zenodo.json"
    zenodo_json: dict = {}
    if zenodo_json_path.is_file():
        try:
            zenodo_json = json.loads(zenodo_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            zenodo_json = {}
    zenodo_json.update(
        {
            "status": "published",
            "doi": doi,
            "deposit_id": record_id,
            "record_url": record_url,
        }
    )
    zenodo_json_path.write_text(
        json.dumps(zenodo_json, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _print_published(result, manifest, as_json=args.json)
    return 0


# Every zenodo_* key the script may write, so a delete leaves no stale trace.
ZENODO_MANIFEST_KEYS = [
    "zenodo_status",
    "zenodo_doi",
    "zenodo_deposit_id",
    "zenodo_draft_url",
    "zenodo_reserved_doi",
    "zenodo_record_url",
    "zenodo_version",
]


def _delete_draft_flow(
    repo: Path, paper_dir: Path, manifest: dict, production: bool, args: argparse.Namespace
) -> int:
    """Delete the unpublished draft from Zenodo and clear the local record."""
    deposit_id = manifest.get("zenodo_deposit_id")
    if manifest.get("zenodo_doi"):
        raise SystemExit(
            f"ERROR: already published ({manifest['zenodo_doi']}).\n"
            "Published records cannot be deleted through the API."
        )
    if not deposit_id:
        raise SystemExit(
            "ERROR: no draft deposit recorded in manifest.yaml. Nothing to delete."
        )
    draft_url = manifest.get("zenodo_draft_url") or _draft_browser_url(production, deposit_id)

    if not args.yes:
        print("\n--- DRY RUN ---")
        print(f"Would delete unpublished draft {deposit_id}:")
        print(f"  {draft_url}")
        print("and remove the zenodo_* keys from manifest.yaml.")
        print("Re-run with --yes to delete.")
        return 0

    token = _require_token(repo, production)
    base = _api_base(production)
    delete_draft(f"{base}/api", token, deposit_id, quiet=args.quiet)

    if not args.quiet:
        print("  Removing zenodo_* keys from manifest.yaml...")
    _set_manifest_keys(paper_dir, {}, remove=ZENODO_MANIFEST_KEYS)

    zenodo_json_path = paper_dir / args.source / "zenodo.json"
    if zenodo_json_path.is_file():
        zenodo_json_path.unlink()
        if not args.quiet:
            print(f"  Removed {zenodo_json_path} (it referenced the deleted draft)...")

    if args.json:
        print(json.dumps({"deleted_draft": deposit_id}, indent=2))
    else:
        print(f"\nDraft {deposit_id} deleted. The paper is back to pre-upload state.")
    return 0


def _update_bib(
    paper_dir: Path, manifest: dict, doi: str, repo: Path, *, quiet: bool = False
) -> None:
    """Add or refresh the Zenodo @software entry in references.bib."""
    bib_path = paper_dir / "paper" / "references.bib"
    if bib_path.is_file() or (paper_dir / "paper").is_dir():
        if not quiet:
            print(f"  Updating {bib_path}...")
        update_references_bib(paper_dir, manifest, doi, repo)


def _finish_published(
    repo: Path,
    paper_dir: Path,
    manifest: dict,
    production: bool,
    args: argparse.Namespace,
    *,
    result: dict,
    size: int,
    zenodo_json: dict,
    zenodo_json_path: Path,
) -> int:
    """Record a freshly published deposit in manifest, bib and zenodo.json."""
    doi = result["doi"]
    record_id = result["record_id"]
    record_url = result["record_url"]

    if not args.quiet:
        print(f"\n  Updating manifest.yaml with DOI {doi}...")
    update_manifest_published(
        paper_dir, doi=doi, record_id=record_id,
        record_url=record_url, version=args.version,
    )

    _update_bib(paper_dir, manifest, doi, repo, quiet=args.quiet)

    zenodo_json.update(
        {
            "status": "published",
            "doi": doi,
            "deposit_id": record_id,
            "record_url": record_url,
        }
    )
    zenodo_json_path.write_text(
        json.dumps(zenodo_json, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _print_published(result, manifest, size=size, as_json=args.json)
    return 0


def _print_published(
    result: dict, manifest: dict, *, size: int | None = None, as_json: bool = False
) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return
    print(f"\n{'='*60}")
    print(f"  DOI:    {result['doi']}")
    print(f"  URL:    {result['record_url']}")
    print(f"  ID:     {result['record_id']}")
    if result.get("file_count") is not None:
        print(f"  Files:  {result['file_count']}")
    if size is not None:
        print(f"  Size:   {_format_size(size)}")
    print(f"{'='*60}")
    print("\nCite this code:")
    print(f"  {_bibtex_key(manifest)} (see references.bib)")


if __name__ == "__main__":
    raise SystemExit(main())