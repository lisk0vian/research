# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Run the pipeline stages in order: python run_all.py [--mode smoke] [--only 03] [--force]

Stages are exactly those declared in `colab.yaml` `stages:` (the spec is the
source of truth, not a glob of this folder), each run as a subprocess with its
own log in outputs/logs/<stage>.log. Unchanged stages are skipped, every
failure goes to outputs/logs/errors.log, and outputs/logs/status.json records
what each stage did. The rules are in COLAB.md at the repo root; the
implementation is the shared scripts/_colab_runtime.py.

After the stages, outputs/run_meta.json records the code hashes and package
versions of the session, which scripts/paper_review.py checks against the repo.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:  # on Colab the runtime sits next to this file (code/_colab_runtime.py)
    import _colab_runtime as rt
except ImportError:  # locally it lives in the repo's scripts/
    sys.path.insert(0, str(HERE.parents[2] / "scripts"))
    import _colab_runtime as rt


def declared_stages() -> list[str]:
    """The stage names colab.yaml declares; empty when the file declares none."""
    import yaml

    spec = yaml.safe_load((HERE / "colab.yaml").read_text(encoding="utf-8")) or {}
    return list(spec.get("stages") or [])


def _normalized_hash(path: Path) -> str:
    """sha256 with CRLF normalized to LF, so a Windows edit and its Colab copy match."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def code_hashes() -> dict[str, str]:
    """sha256 per experiments/*.py plus config.yaml, keyed as the repo names them.

    The runtime copied in from scripts/ is not part of experiments/ and is left out.
    """
    out = {f"experiments/{p.name}": _normalized_hash(p)
           for p in sorted(HERE.glob("*.py")) if p.name != "_colab_runtime.py"}
    cfg = HERE / "config.yaml"
    if cfg.is_file():
        out["experiments/config.yaml"] = _normalized_hash(cfg)
    return out


def _run(*cmd: str) -> str | None:
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=120)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def write_run_meta(exit_code: int) -> Path:
    """outputs/run_meta.json: what ran, from which code, under which packages.

    On Colab there is no git checkout, so git_commit is None and traceability
    rests on code_hashes. Fixed file name on purpose: one Drive id per file.
    """
    outputs = Path(os.environ.get("OUTPUT_DIR", HERE.parent / "outputs"))
    status = outputs / "logs" / "status.json"
    freeze = _run(sys.executable, "-m", "pip", "freeze")
    payload = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exit_code": exit_code,
        "python": sys.version.split()[0],
        "git_commit": _run("git", "rev-parse", "--short", "HEAD"),
        "code_hashes": code_hashes(),
        "packages": freeze.splitlines() if freeze else [],
        "status": json.loads(status.read_text(encoding="utf-8")) if status.is_file() else None,
    }
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / "run_meta.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    code = rt.stages_main(HERE, stages=declared_stages() or None)
    write_run_meta(int(code or 0))
    raise SystemExit(code)
