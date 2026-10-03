# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for the portal document converter.

The converter reads .xlsx and .docx with nothing but the standard library, so
these tests build both formats by hand from zip archives. That is the point:
a fixture built with openpyxl or python-docx would only prove the converter
works where those packages are installed, which is not where it has to run.

The xlsx and docx bytes come from the portal itself in a real run. What matters
here is that the shape survives, and that nothing leaks into the output that
should not.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import portal_docs as pd  # noqa: E402

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# --- fixture builders ------------------------------------------------------

def _xlsx(tmp_path: Path, shared: list[str], sheet: str) -> Path:
    """A minimal but real .xlsx: shared strings plus one worksheet."""
    items = "".join(f"<si><t>{s}</t></si>" for s in shared)
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/sharedStrings.xml",
                   f'<sst xmlns="{NS_MAIN}" count="{len(shared)}">{items}</sst>')
        zf.writestr("xl/worksheets/sheet1.xml",
                    f'<worksheet xmlns="{NS_MAIN}">{sheet}</worksheet>')
    return path


def _docx(tmp_path: Path, paragraphs: list[str], table: list[list[str]]) -> Path:
    """A minimal but real .docx: paragraphs then one table."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    rows = "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>"
                           for c in row) + "</w:tr>"
        for row in table)
    body += f"<w:tbl>{rows}</w:tbl>"
    path = tmp_path / "doc.docx"
    with zipfile.ZipFile(path, "w") as zf:
        # The root is prefixed too. Opening `<document xmlns:w=...>` and closing
        # `</w:document>` parses as an unclosed root, which is the kind of
        # fixture bug that looks like a converter bug.
        zf.writestr("word/document.xml",
                    f'<w:document xmlns:w="{NS_W}"><w:body>{body}</w:body></w:document>')
    return path


DICT_SHARED = [
    "Nombre del Dataset:", "Estaciones SENAMHI GBON/RBON", "",
    "Variable", "Descripción", "Tipo de dato",
    "TEMP", "Temperatura promedio horaria (unidad: °C)", "Numérico",
    "UBIGEO", "Código de ubicación geográfica", "Alfanumerico",
]
DICT_SHEET = (
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
    '<row r="2"/>'
    '<row r="3"><c r="A3" t="s"><v>3</v></c><c r="B3" t="s"><v>4</v></c>'
    '<c r="C3" t="s"><v>5</v></c></row>'
    '<row r="4"><c r="A4" t="s"><v>6</v></c><c r="B4" t="s"><v>7</v></c>'
    '<c r="C4" t="s"><v>8</v></c></row>'
)


# --- xlsx ------------------------------------------------------------------

def test_xlsx_rows_are_read_with_blanks_preserved(tmp_path):
    rows = pd.xlsx_rows(_xlsx(tmp_path, DICT_SHARED, DICT_SHEET))
    assert rows[0] == ["Nombre del Dataset:", "Estaciones SENAMHI GBON/RBON"]
    assert rows[1] == []


def test_shared_strings_resolve_to_their_text(tmp_path):
    rows = pd.xlsx_rows(_xlsx(tmp_path, DICT_SHARED, DICT_SHEET))
    assert rows[3] == ["TEMP", "Temperatura promedio horaria (unidad: °C)", "Numérico"]


def test_a_missing_cell_does_not_shift_everything_left(tmp_path):
    """Without column letters, a blank cell moves every later value one place
    left and the variable ends up described as its own type."""
    sheet = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>')
    rows = pd.xlsx_rows(_xlsx(tmp_path, DICT_SHARED, sheet))
    assert rows[0][0] == "Nombre del Dataset:"
    assert rows[0][1] == ""
    assert rows[0][2] == "Estaciones SENAMHI GBON/RBON"


def test_column_letters_beyond_z_are_ordered(tmp_path):
    assert pd._column_index("A1") == 0
    assert pd._column_index("Z1") == 25
    assert pd._column_index("AA1") == 26
    assert pd._column_index("BC12") == 54


def test_inline_strings_are_read_without_the_shared_table(tmp_path):
    sheet = ('<row r="1"><c r="A1" t="inlineStr"><is><t>directo</t></is></c></row>')
    rows = pd.xlsx_rows(_xlsx(tmp_path, [], sheet))
    assert rows[0] == ["directo"]


def test_a_rich_text_cell_is_not_welded_into_one_word(tmp_path):
    """A cell split across runs must join with spaces or the sentence collapses."""
    items = "<si><r><t>Temperature</t></r><r><t>media</t></r></si>"
    path = tmp_path / "rich.xlsx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", f'<sst xmlns="{NS_MAIN}">{items}</sst>')
        zf.writestr("xl/worksheets/sheet1.xml",
                    f'<worksheet xmlns="{NS_MAIN}">'
                    '<row r="1"><c r="A1" t="s"><v>0</v></c></row></worksheet>')
    rows = pd.xlsx_rows(path)
    assert rows[0][0] == "Temperaturemedia"


# --- docx ------------------------------------------------------------------

def test_docx_blocks_keep_paragraph_and_table_order(tmp_path):
    blocks = pd.docx_blocks(_docx(tmp_path, ["uno", "dos"], [["k", "v"]]))
    assert [k for k, _ in blocks] == ["p", "p", "tbl"]


def test_metadata_title_comes_from_the_document(tmp_path):
    blocks = pd.docx_blocks(_docx(
        tmp_path, ["Metadatos del dataset: Variables Meteorologicas - SENAMHI"], []))
    assert pd.docx_title(blocks) == "Variables Meteorologicas - SENAMHI"


# --- redaction -------------------------------------------------------------

def test_a_contact_address_never_reaches_the_output():
    """AGENTS.md forbids emails in this public repository, and a provider
    document is exactly how one gets in by accident."""
    assert pd._clean("contacto: info.sgd@senamhi.gob.pe") == \
        "contacto: [contact redacted]"


def test_redaction_covers_the_obvious_shapes():
    for raw in ("a@b.com", "first.last@sub.datos.gob.pe", "X+Y@dominio.org.pe"):
        assert "@" not in pd._clean(raw)


def test_redaction_leaves_text_that_merely_looks_like_a_handle():
    assert pd._clean("GBON y RBON @ 1.25 m") == "GBON y RBON @ 1.25 m"


def test_the_generated_docs_carry_no_email(tmp_path, capsys):
    """End to end on the generated Markdown, not on the helper."""
    pd.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    rows = pd.xlsx_rows(_xlsx(tmp_path, DICT_SHARED, DICT_SHEET))
    text = pd.render_dictionary(rows, "t", "src")
    blocks = pd.docx_blocks(_docx(
        tmp_path, ["Metadatos del dataset: SENAMHI"],
        [["Correo de contacto", "info.sgd@senamhi.gob.pe"]]))
    text += pd.render_metadata(blocks, "SENAMHI", "src")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)


# --- rendering -------------------------------------------------------------

def test_the_dictionary_finds_the_header_by_its_column_name():
    """The header row index is not worth hardcoding against the portal's
    layout; 'Variable' is the anchor that means something."""
    rows = [["Nombre del Dataset:", "X"], [], ["Variable", "Desc", "Tipo"],
            ["TEMP", "temperatura", "Numérico"]]
    out = pd.render_dictionary(rows, "t", "src")
    assert "| Variable | Desc | Tipo |" in out
    assert "| TEMP | temperatura | Numérico |" in out


def test_a_dictionary_without_a_variable_header_is_an_error():
    with pytest.raises(ValueError, match="Variable"):
        pd.render_dictionary([["a", "b"], ["c", "d"]], "t", "src")


def test_an_empty_sheet_is_an_error_not_an_empty_document():
    with pytest.raises(ValueError, match="empty"):
        pd.render_dictionary([["", ""]], "t", "src")


def test_a_pipe_in_a_description_is_escaped():
    """Unescaped, it splits the Markdown row and the table gains a column."""
    rows = [["Variable", "Desc"], ["TEMP", "a | b"]]
    out = pd.render_dictionary(rows, "t", "src")
    assert r"a \| b" in out
    body = [ln for ln in out.splitlines() if ln.startswith("| TEMP")]
    assert len(body[0].split("|")) == 5


def test_the_metadata_table_pads_ragged_rows():
    blocks = [("tbl", [["a", "b", "c"], ["only"]])]
    out = pd.render_metadata(blocks, "t", "src")
    assert "| only |  |  |" in out
