# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""The canonical contract for a paper folder.

Single place that defines what "correct structure" means. Both `paper_new.py`
(creates it) and `paper_validate.py` (checks it) import from here, so the
scaffold and the validator can never drift apart. Edit this file to change the
rules, not the scripts.
"""

from __future__ import annotations

# --- Naming ------------------------------------------------------------------
# Institutional code lowercased (c15-2026) or a short kebab-case slug.
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# --- Directories -------------------------------------------------------------
# Created by the scaffold. `.gitkeep` is written in the empty ones.
PAPER_DIRS = [
    "paper",
    "paper/media",
    "data",
    "data/raw",
    "data/processed",
    "experiments",
    "notebooks",
    "build",
    "legacy",
    "reviews",
    "reviews/round-1",
]

# A paper is invalid if any of these is missing (data/raw and data/processed are
# NOT required: papers that started from a migrated docx use data/ directly).
REQUIRED_DIRS = ["paper", "data", "experiments", "notebooks", "build"]

# --- Files -------------------------------------------------------------------
# main.qmd is required UNLESS a migration is still pending.
MIGRATION_MARKER = "paper/MIGRATION_PENDING.txt"
REQUIRED_PAPER_FILES = ["manifest.yaml", "paper/references.bib"]
REVIEW_FILES = ["comments.yaml", "responses.yaml", "ai-review.yaml"]

# --- Review panel (paper-review skill, /review command) -----------------------
# v2 rounds: packet.yaml + raw/<object>.yaml + consolidated.yaml/.md +
# triage.yaml alongside the three legacy human files (comments, responses,
# legacy ai-review). Strict content checks apply only when schema_version
# == 2 is present, so existing rounds keep warning-only behavior. In a v2
# round the legacy ai-review.yaml is an error (two sources of truth).
REVIEW_SCHEMA_VERSION = 2
REVIEW_PACKET_FILE = "packet.yaml"
REVIEW_TRIAGE_FILE = "triage.yaml"
REVIEW_RAW_DIR = "raw"
REVIEW_REJECTED_DIR = "rejected"
REVIEW_CONSOLIDATED_YAML = "consolidated.yaml"
REVIEW_CONSOLIDATED_MD = "consolidated.md"
REVIEW_LEGACY_AI_REVIEW = "ai-review.yaml"
REVIEW_SCOPES = ("code-only", "full")
REVIEW_SEVERITIES = ("major", "minor")
REVIEW_KINDS = ("presence", "absence")
REVIEW_BASES = ("demonstrable", "normative")
REVIEW_DECISIONS = ("accept", "reject", "defer")
REVIEW_PENDING = "pending"
REVIEW_MAX_FINDINGS = 15
REVIEW_TITLE_MAX = 140
REVIEW_WARRANT_MAX = 280
REVIEW_FIX_MAX = 280
REVIEW_QUOTE_MAX = 600
REVIEW_EVIDENCE_MAX = 2
# Selectors for /review <slug> <selector>: groups, presets, and the 8 objects.
REVIEW_GROUPS = {
    "paper": ("rev-design", "rev-refs", "rev-style"),
    "code": ("peer-plan", "peer-results", "peer-reach"),
    "gate": ("gate-claims",),
}
REVIEW_PRESETS = {
    "plan": ("peer-plan",),
    "code": ("peer-plan", "peer-results", "peer-reach"),
    "manuscript": ("rev-design", "rev-refs", "rev-style"),
    "claims": ("gate-claims",),
    "full": (
        "rev-design", "rev-refs", "rev-style",
        "peer-plan", "peer-results", "peer-reach", "gate-claims",
    ),
}
REVIEW_OBJECTS = (
    "design", "refs", "style", "plan", "results", "reach", "claims", "merge",
)

# Extensions a paper may never keep as a data-of-record artefact. Numbers must
# live in CSV/JSON so they are diffable and auditable in CI.
FORBIDDEN_ARTEFACT_EXTENSIONS = {".xlsx", ".xls"}
# Paths where that ban applies (data/ is exempt: source dictionaries may be xlsx).
ARTEFACT_SCOPE_DIRS = ["paper", "outputs", "experiments"]

# --- Skills registry ---------------------------------------------------------
# The documented skill set. Extra folders are reported as a warning, not an
# error, so third-party skills can still be experimented with.
SKILL_REGISTRY = [
    "paper-new",
    "paper-build",
    "paper-journal",
    "paper-validate",
    "paper-colab",
    "paper-search",
    "paper-humanize",
    "paper-review",
    "util-docx",
    "util-office-to-md",
    "util-search",
    "grilling",
    "paper-zenodo",
    "paper-cover-letter",
    "paper-title-page",
]

# Files matching these are never committed (scanned via `git ls-files`).
SECRET_PATTERNS = [
    "*.pem",
    "*.key",
    "credentials.json",
    "*token*",
    "*secret*",
]


def format_block_from_type(type_meta: dict) -> str:
    """Render the `format:` block of main.qmd from a journal's type.yaml.

    One function for `paper_new` and `paper_journal` so the front-matter is
    always written the same way. Falls back to generic pdf + docx when the
    journal has no official Quarto extension. The optional `model` and
    `formatting` keys of type.yaml are forwarded to the `journal:` block, which
    the extension turns into class options; `quarto_docx_format` names the docx
    target the extension contributes (elsevier-cas-docx), so that Word goes
    through the journal's own docx filter instead of pandoc's default.
    """
    quarto_format = type_meta.get("quarto_format") or type_meta.get("quarto_extension") or "pdf"
    extension = type_meta.get("extension") or type_meta.get("quarto_extension") or ""
    name = type_meta.get("journal", "")
    cite = type_meta.get("cite_style", "number")
    docx_format = type_meta.get("quarto_docx_format") or ""
    # layout options the extension turns into class options (elsarticle: 1p/3p/5p,
    # preprint/review/doubleblind); emitted only when the journal declares them.
    layout = "".join(
        f"  {key}: {value}\n"
        for key, value in (
            ("model", type_meta.get("model")),
            ("formatting", type_meta.get("formatting")),
        )
        if value
    )

    if extension and quarto_format != "pdf":
        docx_block = f"  {docx_format}: {{}}\n" if docx_format else "  docx: default\n"
        return (
            "format:\n"
            f"  {quarto_format}:\n"
            "    keep-tex: true\n"
            f"{docx_block}"
            # journal.* sits at the TOP level, not under a single format, so that
            # every target sees it: the PDF template reads $journal.*$ and the
            # journal's docx filter (cas-docx.lua) builds the Word front matter
            # (highlights, corresponding author) from it.
            "journal:\n"
            f'  name: "{name}"\n'
            f"  cite-style: {cite}\n"
            f"{layout}"
        )
    return (
        "format:\n"
        "  pdf: default\n"
        "  docx: default\n"
        f"  # NOTE: {name or 'the journal'} has no Quarto extension in the catalog.\n"
        "  # Final PDF needs the journal template / a docx reference-doc.\n"
    )
