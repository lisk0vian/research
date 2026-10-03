# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for the PDF/DOCX parity tooling: the comparison levels of
scripts/paper_parity.py and the OOXML passes of the elsevier-cas
tools/cas_docx_post.py. Synthetic inputs only; no Word, LaTeX or PDF needed."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import paper_parity  # noqa: E402
from _pdfdiff import lines_of, norm  # noqa: E402

TOOLS = [
    REPO_ROOT / "templates" / "journals" / j / "quarto-extension" / "tools"
    for j in ("engineering-applications-of-artificial-intelligence",
              "information-sciences")
]


def _load_post():
    spec = importlib.util.spec_from_file_location(
        "cas_docx_post", TOOLS[0] / "cas_docx_post.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


post = _load_post()
W = post.W


def _page(*lines: str, y0: float = 60.0, pitch: float = 12.0):
    """Synthetic pdftotext page: one tuple per word, 5 pt per character."""
    words = []
    for i, line in enumerate(lines):
        x = 40.0
        for w in line.split():
            words.append((w, x, y0 + i * pitch - 10, x + 5 * len(w), y0 + i * pitch))
            x += 5 * len(w) + 3
    return words


# --- shared helpers ---------------------------------------------------------

def test_norm_ligatures_and_quotes():
    assert norm("ﬁle") == "file"
    assert norm("’s") == "'s"


def test_lines_of_splits_on_baseline_and_return():
    lines = lines_of(_page("one two", "three"))
    assert [[w[0] for w in ln] for ln in lines] == [["one", "two"], ["three"]]


def test_hyphenation_does_not_count_as_a_text_difference():
    tex = [_page("a long multi-", "algorithm text")]
    word = [_page("a long multialgorithm", "text")]
    lv = paper_parity.text_levels(tex, word)
    assert lv["word_coverage"] == 1.0
    assert lv["page_word_match"] == 1.0


def test_levels_report_words_moved_to_another_page():
    ref = [_page("alpha beta"), _page("gamma delta")]
    cand = [_page("alpha beta gamma"), _page("delta")]
    lv = paper_parity.text_levels(ref, cand)
    assert lv["page_word_match"] == 0.75
    assert lv["first_moved_word"]["word"] == "gamma"
    assert lv["line_match"] == 0.0


def test_identical_pages_have_zero_geometry_delta():
    pages = [_page("same words here", "and here")]
    lv = paper_parity.text_levels(pages, pages)
    assert lv["line_match"] == 1.0
    assert lv["word_delta_p95_pt"] == 0.0


def test_shifted_moves_printed_letter_sheet_back_to_the_page_box():
    pages = [[("w", 72.0, 10.0, 80.0, 20.0)]]
    assert paper_parity.shifted(pages, (33.875, 0.0))[0][0][1] == 72.0 - 33.875
    assert paper_parity.shifted(pages, None) is pages


def test_thresholds_merge_journal_parity_block(mini_repo: Path):
    (mini_repo / "papers" / "p1").mkdir()
    (mini_repo / "papers" / "p1" / "manifest.yaml").write_text(
        "paper: p1\njournal: test-journal\n", encoding="utf-8")
    t = mini_repo / "templates" / "journals" / "test-journal" / "type.yaml"
    t.write_text(t.read_text(encoding="utf-8")
                 + "parity:\n  docx:\n    line_match_min: 0.5\n", encoding="utf-8")
    th = paper_parity.thresholds(mini_repo, "p1")
    assert th["docx"]["line_match_min"] == 0.5
    assert th["docx"]["ink_xor_max_pct"] == paper_parity.DEFAULTS["docx"]["ink_xor_max_pct"]


# --- cas_docx_post ----------------------------------------------------------

def test_tools_are_identical_across_cas_journals():
    for name in ("cas_docx_post.py", "make_reference_docx.py"):
        a, b = (t / name for t in TOOLS)
        assert a.read_bytes() == b.read_bytes(), name


BBL = r"""\begin{thebibliography}{2}
%Type = Article
\bibitem[{Garc\'ia et~al.(2020)Garc\'ia, Smith and Lee}]{garcia2020}
\bibinfo{author}{Garc\'ia, A.}, \bibinfo{author}{Smith, B.},
  \bibinfo{author}{Lee, C.}, \bibinfo{year}{2020}.
\newblock \bibinfo{title}{A study---of things}.
\newblock \bibinfo{journal}{{\em J. Tests}} \bibinfo{volume}{3},
  \bibinfo{pages}{1--9}.
\newblock \DOIprefix\doi{10.1000/xyz}.
\bibitem[{Ord(1995)}]{ord1995}
\bibinfo{author}{Ord, K.}, \bibinfo{year}{1995}.
\newblock \bibinfo{title}{Local statistics}.
\end{thebibliography}
"""


def test_bbl_entries_labels_and_runs():
    entries = post.bbl_entries(BBL)
    assert [e["key"] for e in entries] == ["garcia2020", "ord1995"]
    g = entries[0]
    assert (g["short"], g["year"], g["long"]) == (
        "García et al.", "2020", "García, Smith and Lee")
    runs = post.bbl_runs(g["body"])
    text = "".join(t for t, _ in runs)
    assert text.startswith("García, A., Smith, B., Lee, C., 2020. A study—of things.")
    assert "doi:10.1000/xyz." in text
    assert any(f.get("italic") and t == "J. Tests" for t, f in runs)
    assert any(f.get("mono") and f.get("link") == "https://doi.org/10.1000/xyz"
               for _, f in runs)


def _body(xml: str) -> ET.Element:
    return ET.fromstring(f'<w:body xmlns:w="{W}">{xml}</w:body>')


def _cite(key: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="ref-{key}"><w:r><w:t>{label}</w:t></w:r>'
            '</w:hyperlink>')


def test_citations_use_long_names_first_then_short():
    body = _body("<w:p>" + _cite("garcia2020", "Garcia et al., 2020")
                 + _cite("garcia2020", "Garcia et al., 2020")
                 + _cite("ord1995", "Ord (1995)") + "</w:p>")
    post.fix_citations(body, post.bbl_entries(BBL))
    links = [post.text(h) for h in body.iter(post.q("hyperlink"))]
    assert links == ["García, Smith and Lee, 2020",
                     "García et al., 2020", "Ord (1995)"]


def test_heading_numbers_get_a_trailing_period_and_collapse_spacing():
    body = _body(
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>2. Work</w:t></w:r></w:p>'
        '<w:bookmarkStart w:id="1" w:name="x"/>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>2.1 Sub</w:t></w:r></w:p>')
    post.fix_headings(body, None)
    h2 = body.findall(post.q("p"))[1]
    assert post.text(h2) == "2.1. Sub"
    assert h2.find(f".//{post.q('spacing')}").get(post.q("before")) == "0"


def test_equation_number_moves_to_a_right_tab():
    m = post.M
    body = _body(
        f'<w:p xmlns:m="{m}"><m:oMathPara><m:oMath>'
        '<m:r><m:t>x</m:t></m:r><m:r><m:t> </m:t></m:r>'
        '<m:r><m:t>(</m:t></m:r><m:r><m:t>3</m:t></m:r><m:r><m:t>)</m:t></m:r>'
        '</m:oMath></m:oMathPara></w:p>')
    post.fix_equations(body)
    p = body.find(post.q("p"))
    assert p.find(post.q("oMathPara", m)) is None
    assert post.text(p).endswith("(3)")
    tabs = p.findall(f".//{post.q('tab')}")
    assert {t.get(post.q("val")) for t in tabs if t.get(post.q("val"))} == {"center", "right"}


def test_float_plan_marks_floats_with_no_text_above_as_top():
    pages = [
        [("Figure", 40, 80, 70, 90), ("1:", 72, 80, 80, 90), ("text", 40, 100, 60, 110)],
        [("body", 40, 60, 60, 70), ("Table", 40, 200, 70, 210), ("2", 72, 200, 76, 210)],
    ]
    plan = post.float_plan(pages)
    assert plan[("Figure", 1)] == (0, "top")
    assert plan[("Table", 2)] == (1, "here")


def test_normalize_orders_paragraph_properties():
    body = _body('<w:p><w:pPr><w:jc w:val="left"/><w:spacing w:before="0"/>'
                 '<w:pStyle w:val="X"/></w:pPr></w:p>')
    post.normalize(body)
    tags = [c.tag.split("}")[1] for c in body.find(f".//{post.q('pPr')}")]
    assert tags == ["pStyle", "spacing", "jc"]
