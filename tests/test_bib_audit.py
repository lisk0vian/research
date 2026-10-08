# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""DOI parsing in scripts/_bib_audit.py (used by doi_validate.py). Offline."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import _bib_audit as audit  # noqa: E402


def test_sici_doi_keeps_its_angle_brackets():
    """AMS journals before ~2005 use SICI DOIs; cutting at '<' breaks them."""
    doi = "10.1175/1520-0493(1988)116<2417:SSBOTM>2.0.CO;2"
    assert audit.clean_doi(doi) == doi.casefold()


def test_url_prefix_and_trailing_punctuation_are_stripped():
    assert audit.clean_doi("https://doi.org/10.1029/2017JD027923.") == "10.1029/2017jd027923"
    assert audit.clean_doi("doi: 10.1561/2200000101") == "10.1561/2200000101"


def test_text_without_a_doi_gives_empty():
    assert audit.clean_doi("no identifier here") == ""
