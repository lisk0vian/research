# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""The Guide-for-Authors bank: conversion, segmentation, links and the contract.

These tests never import an HTML library. `check` is what CI enforces, so it has
to stay stdlib-only; the converter is exercised through the built-in reader,
which is the path that always exists (markitdown is preferred when installed and
would otherwise be the untested one).

The fixtures are miniature Elsevier guides: chrome that must be dropped,
headings that must become separate files, and anchors that must survive the cut.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import journal_guide as jg  # noqa: E402

GUIDE_HTML = """<!DOCTYPE html>
<html><head><title>Guide for authors</title><style>.x{}</style></head>
<body>
<nav class="breadcrumb"><a href="/">Home</a></nav>
<div class="cookie-banner">We use cookies.</div>
<script>track();</script>
<main>
<h1>Guide for authors</h1>
<h2 id="before-you-begin">Before you begin</h2>
<p>You must have an account.</p>
<h2 id="types-of-paper">Types of paper</h2>
<p>Research papers and short communications.</p>
<ul><li>Research paper</li><li>Short communication</li></ul>
<h2 id="open-access">Open access</h2>
<p>See the <a href="https://www.elsevier.com/about/policies-and-standards/open-access">open access policy</a>.</p>
</main>
<footer>Copyright</footer>
</body></html>"""


@pytest.fixture
def guide_repo(mini_repo: Path) -> Path:
    """A mini repo whose test-journal has a *finished* guide.

    Finishing it (index, provenance, retrieval date) matters: almost every
    assertion below is about one specific violation, and a fixture that left the
    guide half-written would report that violation too and hide it.
    """
    src = mini_repo / "guide.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    jg.scaffold(mini_repo, "test-journal")
    jg.propose(mini_repo, "test-journal", src, "builtin")
    jg.apply(mini_repo, "test-journal", approved=True)

    jdir = mini_repo / "templates" / "journals" / "test-journal"
    gdir = jdir / "guide"
    listing = "\n".join(
        f"- [{s.stem}](sections/{s.name}) — what it covers."
        for s in sorted((gdir / "sections").glob("*.md"))
    )
    (gdir / "index.md").write_text(
        f"# Test Journal — Guide for Authors\n\n## Sections\n\n{listing}\n", encoding="utf-8"
    )
    (gdir / "SOURCES.md").write_text(
        "# Sources\n\n| what | url | retrieved | sha256 |\n|---|---|---|---|\n"
        "| guide-for-authors | https://example.org/guide | 2026-10-10 | deadbeef |\n",
        encoding="utf-8",
    )
    jg.set_type_field(jdir / "type.yaml", "guide_retrieved", "2026-10-10")
    return mini_repo


# --- conversion ------------------------------------------------------------


def test_builtin_reader_drops_chrome_and_reports_it(tmp_path: Path):
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    md, removed = jg.convert_html(src, engine="builtin")
    assert "cookie" not in md.lower()
    assert "breadcrumb" not in md.lower()
    assert "Copyright" not in md
    labels = " ".join(label for _tag, label in removed)
    assert "cookie-banner" in labels, removed
    # Reporting is the whole point: a silently dropped paragraph is the failure
    # this pipeline exists to make visible.
    assert any(tag in {"script", "style", "nav", "footer"} for tag, _ in removed)


def test_conversion_keeps_content_and_headings(tmp_path: Path):
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    md, _ = jg.convert_html(src, engine="builtin")
    assert "You must have an account." in md
    assert "## Before you begin" in md
    assert "[open access policy](https://www.elsevier.com/about/policies-and-standards/open-access)" in md
    assert "- Research paper" in md


def test_html_ids_become_explicit_anchors(tmp_path: Path):
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    md, _ = jg.convert_html(src, engine="builtin")
    assert '<a id="open-access"></a>' in md
    out = tmp_path / "g.md"
    out.write_text(md, encoding="utf-8")
    assert "open-access" in jg.read_anchors(out)


def test_the_default_engine_keeps_anchors(tmp_path: Path):
    """markitdown reads prettier but drops `<a id>` and keeps the chrome, and it
    reports having removed nothing. That combination would break every internal
    link in the guide silently, which is exactly the failure this bank prevents —
    so the default must be the reader that keeps them."""
    pytest.importorskip("markitdown")
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    default_md, _ = jg.to_markdown(src)
    pretty_md, _ = jg.to_markdown(src, engine="markitdown")
    assert '<a id="open-access"></a>' in default_md
    # If markitdown ever stops dropping anchors this stops being a reason to
    # avoid it; the point of the assertion is that the default is the safe one.
    if '<a id="open-access"></a>' not in pretty_md:
        assert '<a id="open-access"></a>' in default_md


def test_default_engine_is_builtin_not_markitdown():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "journal_guide.py"), "propose",
         "--help"],
        capture_output=True, text=True,
    )
    assert "builtin,markitdown" in proc.stdout.replace(" ", ""), proc.stdout


def test_safelinks_are_unwrapped_to_their_destination():
    """Elsevier's support addresses link through Outlook SafeLinks, which encodes
    the real target in `url=` plus a per-recipient token. Keeping the wrapper
    records a URL that is useless to a reader and different for every recipient."""
    wrapped = ("https://nam11.safelinks.protection.outlook.com/?url=http%3A%2F%2Fwww.ssrn.com%2F"
               "&data=05%7C02%7Cn.limerick%40elsevier.com%7Cdeadbeef&sdata=abc")
    assert jg.unwrap_redirect(wrapped) == "http://www.ssrn.com/"
    assert jg.normalise_url(wrapped) == "https://ssrn.com/"
    assert jg.unwrap_redirect("https://www.elsevier.com/x") == "https://www.elsevier.com/x"


def test_a_repeated_html_id_keeps_only_the_first_anchor(tmp_path: Path):
    """ScienceDirect repeats id="about-the-journal" on two elements. Two files
    carrying the same anchor would make the link to it ambiguous."""
    src = tmp_path / "dup.html"
    src.write_text(
        '<div id="about"><h3>About</h3><p>a</p></div>'
        '<div id="about"><h4>Special issues</h4><p>b</p></div>',
        encoding="utf-8",
    )
    md, _ = jg.convert_html(src, engine="builtin")
    assert md.count('<a id="about"></a>') == 1


def test_an_anchor_on_a_wrapping_div_belongs_to_the_heading(tmp_path: Path):
    """ScienceDirect puts the id on the wrapper <div>, not on the heading itself.
    Losing it would break every internal link in the guide."""
    src = tmp_path / "wrap.html"
    src.write_text('<div id="sec-a"><h4>Aims and scope</h4><p>x</p></div>', encoding="utf-8")
    md, _ = jg.convert_html(src, engine="builtin")
    assert '<a id="sec-a"></a>' in md
    assert "#### Aims and scope" in md


def test_empty_emphasis_tags_do_not_leave_stray_markers(tmp_path: Path):
    """<b></b> and <b> </b> are page chrome; emitting "**" for them leaves a
    "****" in the heading text."""
    src = tmp_path / "empty.html"
    src.write_text("<h4>Corresponding author<b> </b><br></h4><p>a<b></b>b</p>",
                   encoding="utf-8")
    md, _ = jg.convert_html(src, engine="builtin")
    assert "#### Corresponding author" in md
    assert "**" not in md
    assert "ab" in md


def test_unbalanced_list_tags_do_not_abort_the_conversion(tmp_path: Path):
    src = tmp_path / "lists.html"
    src.write_text("<ul><li>a</li></ul></li><ul><li>b</li></ul>", encoding="utf-8")
    md, _ = jg.convert_html(src, engine="builtin")
    assert "- a" in md and "- b" in md


def test_a_grouping_heading_is_cut_then_dropped_as_heading_only():
    """Elsevier groups its guide under headings ('Ethics and policies') that carry
    no text. It is a legitimate cut point, but a 3-line stub per grouping would
    swamp the real sections, so `propose` drops it and index.md keeps the grouping."""
    markdown = "## Ethics and policies\n\n### Authorship\n\nx\n\n### Funding\n\ny\n"
    sections, _ = jg.split_sections(markdown, split_level=3)
    assert [s.title for s in sections] == ["Ethics and policies", "Authorship", "Funding"]
    assert [s.title for s in sections if s.is_heading_only] == ["Ethics and policies"]
    assert [s.title for s in sections if not s.is_heading_only] == ["Authorship", "Funding"]


def test_a_step_heading_is_a_section_of_its_own(tmp_path: Path):
    """Springer puts an id on every `<h2>Step N …</h2>` and none on the headings
    beneath it. Cutting only on the deeper level would strand the step, its anchor
    and its introduction paragraphs in the previous step's last file."""
    src = tmp_path / "steps.html"
    src.write_bytes(
        b"<h2 id='Introduction'>Introduction</h2><h4>Before you start</h4><p>a</p>"
        b"<h2 id='Step 1 - Article types'>Step 1 - Article types</h2>"
        b"<p>choose the right type</p><h4>Research</h4><p>b</p>")
    md, _ = jg.convert_html(src, engine="builtin")
    sections, _ = jg.split_sections(md, split_level=4)
    step = next(s for s in sections if s.title.startswith("Step 1"))
    assert "choose the right type" in "\n".join(step.lines)
    assert "step-1-article-types" in step.anchors
    previous = next(s for s in sections if s.title == "Before you start")
    assert "step-1-article-types" not in previous.anchors


def test_an_empty_heading_holder_does_not_strand_the_anchor_above_it(tmp_path: Path):
    """Springer marks each step with an empty `<h3 id="Step 1 …_"></h3>`. Read as a
    bare `###` it would stop widen_to_anchor before it reached the step's anchor."""
    src = tmp_path / "holder.html"
    src.write_bytes(
        b"<h2 id='Step 1'>Step 1</h2><p>intro</p>"
        b"<h3 id='Step 1_'></h3><h4>Research</h4><p>b</p>")
    md, _ = jg.convert_html(src, engine="builtin")
    assert "\n###\n" not in md and not any(
        ln.strip().startswith("###") and not ln.strip(" #") for ln in md.splitlines())
    sections, _ = jg.split_sections(md, split_level=4)
    research = next(s for s in sections if s.title == "Research")
    # The holder's anchor now travels with the section it introduces instead of
    # being stranded behind a bare `###` in whatever came before.
    assert "Step 1_" in research.anchors, research.anchors
    step = next(s for s in sections if s.title == "Step 1")
    assert "Step 1" in step.anchors
    assert "Step 1_" not in step.anchors


def test_mailto_is_not_treated_as_a_missing_file():
    assert jg.is_external("mailto:software.impacts@elsevier.com")
    assert jg.is_external("https://elsevier.com/x")
    assert not jg.is_external("sections/01-about.md")
    assert not jg.is_external("../_shared/elsevier/open-access.md")


def test_http_and_https_are_the_same_page():
    assert jg.normalise_url("http://www.ssrn.com/") == jg.normalise_url("https://www.ssrn.com")


def test_a_proposed_section_is_never_heading_only(tmp_path: Path):
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    jg.scaffold(tmp_path, "j")
    jg.propose(tmp_path, "j", src, "builtin")
    jg.apply(tmp_path, "j", approved=True)
    for f in (tmp_path / "templates" / "journals" / "j" / "guide" / "sections").glob("*.md"):
        assert not jg.Section(0, "", f.read_text(encoding="utf-8").splitlines(), 0).is_heading_only


def test_apply_removes_sections_the_proposal_dropped(tmp_path: Path):
    """Re-cutting a guide leaves the previous cut's files behind. They are then
    orphans that `check` reports as errors with no obvious cause, and the index
    still lists sections that no longer correspond to anything."""
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    jg.scaffold(tmp_path, "j")
    jg.propose(tmp_path, "j", src, "builtin")
    jg.apply(tmp_path, "j", approved=True)
    dest = tmp_path / "templates" / "journals" / "j" / "guide" / "sections"
    assert len(list(dest.glob("*.md"))) == 3

    # A deeper cut produces a different, longer set of files.
    jg.propose(tmp_path, "j", src, "builtin", split_level=3, force=True)
    jg.apply(tmp_path, "j", force=True, approved=True)
    proposed = {p.name for p in (tmp_path / "templates" / "journals" / "j" / "guide"
                                / "_work" / "sections").glob("*.md")}
    assert {p.name for p in dest.glob("*.md")} == proposed


def test_a_list_item_wrapped_in_a_paragraph_stays_a_tight_list(tmp_path: Path):
    """ScienceDirect wraps each bullet in its own <p>. Emitting the block
    newlines anyway gives "-\\n\\ntext": a loose list, twice the lines."""
    src = tmp_path / "li.html"
    src.write_text("<ul><li><p>One</p></li><li><p>Two</p></li></ul>", encoding="utf-8")
    md, _ = jg.convert_html(src, engine="builtin")
    assert "- One\n\n- Two" in md, repr(md)


def _nested_guide(repo: Path) -> Path:
    """A guide whose References topic is a folder rather than one 150-line file."""
    jdir = repo / "templates" / "journals" / "j"
    jdir.mkdir(parents=True, exist_ok=True)
    # check_guide is opt-in: without `guide:` in type.yaml it reports nothing, so
    # the fixture has to declare it or every assertion below passes vacuously.
    (jdir / "type.yaml").write_text(
        'journal: "J"\npublisher: elsevier\nguide: guide/index.md\n'
        'guide_retrieved: "2026-10-10"\n', encoding="utf-8")
    jg.scaffold(repo, "j")
    guide = jdir / "guide"
    (guide / "sections" / "01-abstract.md").write_text("## Abstract\n\n250 words.\n", encoding="utf-8")
    ref = guide / "sections" / "02-references"
    ref.mkdir(parents=True)
    (ref / "index.md").write_text(
        "# References\n\n- [Style](style.md)\n- [Examples](examples.md)\n", encoding="utf-8")
    (ref / "style.md").write_text("## Reference style\n\nAPA 7.\n", encoding="utf-8")
    (ref / "examples.md").write_text("## Reference examples\n\nSeven of them.\n", encoding="utf-8")
    (guide / "index.md").write_text(
        "# Test\n\n- [Abstract](sections/01-abstract.md)\n"
        "- [References](sections/02-references/index.md)\n", encoding="utf-8")
    (guide / "SOURCES.md").write_text(
        "# Sources\n\n| what | url | retrieved | sha256 |\n|---|---|---|---|\n"
        "| g | https://x/y | 2026-10-10 | abc |\n", encoding="utf-8")
    return guide


def test_a_section_folder_counts_as_one_section(tmp_path: Path):
    guide = _nested_guide(tmp_path)
    res = jg.check_guide(tmp_path, "j")
    assert res.ok, [i.message for i in res.errors]


def test_a_broken_link_inside_a_section_folder_is_an_error(tmp_path: Path):
    """The whole point of validating a sub-index is that a broken link two levels
    down fails like any other. Otherwise splitting a topic into a folder would
    quietly create a place where nothing is checked."""
    _nested_guide(tmp_path)
    sub = tmp_path / "templates" / "journals" / "j" / "guide" / "sections" / "02-references"
    (sub / "index.md").write_text("# References\n\n- [Gone](missing.md)\n", encoding="utf-8")
    res = jg.check_guide(tmp_path, "j")
    assert any("missing.md" in i.message for i in res.errors), [i.message for i in res.errors]


def test_a_file_inside_a_section_folder_missing_from_its_index_is_an_error(tmp_path: Path):
    _nested_guide(tmp_path)
    sub = tmp_path / "templates" / "journals" / "j" / "guide" / "sections" / "02-references"
    (sub / "index.md").write_text("# References\n\n- [Style](style.md)\n", encoding="utf-8")
    res = jg.check_guide(tmp_path, "j")
    assert any("examples.md" in i.message for i in res.issues), [i.message for i in res.issues]


def test_a_section_folder_without_an_index_is_an_error(tmp_path: Path):
    _nested_guide(tmp_path)
    orphan = tmp_path / "templates" / "journals" / "j" / "guide" / "sections" / "03-loose"
    orphan.mkdir()
    (orphan / "thing.md").write_text("## Thing\n", encoding="utf-8")
    res = jg.check_guide(tmp_path, "j")
    assert any("must contain index.md" in i.message for i in res.errors)


def test_apply_copies_a_section_folder_and_clears_the_old_cut(tmp_path: Path):
    guide = _nested_guide(tmp_path)
    work = tmp_path / "templates" / "journals" / "j" / "guide" / "_work" / "sections"
    shutil.copytree(guide / "sections" / "02-references", work / "02-references")
    (work / "01-abstract.md").write_text("## Abstract\n\n250 words.\n", encoding="utf-8")
    jg.apply(tmp_path, "j", force=True, approved=True)
    assert (guide / "sections" / "02-references" / "style.md").is_file()
    # A file the proposal dropped must be gone, or `check` sees an orphan.
    (guide / "sections" / "99-stale.md").write_text("## Stale\n", encoding="utf-8")
    jg.apply(tmp_path, "j", force=True, approved=True)
    assert not (guide / "sections" / "99-stale.md").exists()


def test_markdown_and_text_sources_pass_through(tmp_path: Path):
    src = tmp_path / "g.md"
    src.write_text("# Title\n\nBody.\n", encoding="utf-8")
    md, removed = jg.to_markdown(src)
    assert md.strip() == "# Title\n\nBody."
    assert removed == []


def test_an_unsupported_source_says_what_to_do(tmp_path: Path):
    src = tmp_path / "g.docx"
    src.write_bytes(b"PK\x03\x04")
    with pytest.raises(SystemExit, match="Markdown or text"):
        jg.to_markdown(src)


# --- segmentation ----------------------------------------------------------


def test_sections_are_cut_on_h2():
    markdown = (
        "# Guide\n\n<a id=\"a\"></a>\n## Before you begin\n\nx\n\n"
        "<a id=\"b\"></a>\n## Types of paper\n\ny\n"
    )
    sections, _ = jg.split_sections(markdown)
    assert [s.title for s in sections] == ["Before you begin", "Types of paper"]
    assert jg.numbered([s.filename for s in sections]) == [
        "01-before-you-begin.md", "02-types-of-paper.md",
    ]


def test_an_anchor_belongs_to_the_section_it_names():
    markdown = (
        "## One\n\ntext\n\n<a id=\"two\"></a>\n## Two\n\nmore\n"
    )
    sections, _ = jg.split_sections(markdown)
    one, two = sections
    assert '<a id="two"></a>' in "\n".join(two.lines)
    assert '<a id="two"></a>' not in "\n".join(one.lines)


def test_an_oversized_section_is_recut_without_losing_its_lead_in():
    body = "\n".join(f"line {i}" for i in range(400))
    markdown = f"## Ethics\n\nThese are the policies.\n\n### Authorship\n\n{body}"
    sections, _ = jg.split_sections(markdown, split_level=2, max_lines=50)
    assert len(sections) > 1
    assert "These are the policies." in "\n".join(sections[0].lines)


def test_the_page_title_is_handed_back_not_cut_into_a_file():
    """An <h1> alone would become a one-line section file. It is neither kept as a
    section nor lost: it comes back for index.md, where a title belongs."""
    markdown = "# Guide for authors\n\n<a id=\"a\"></a>\n## One\n\nx\n"
    sections, title = jg.split_sections(markdown)
    assert title == ["Guide for authors"]
    assert [s.title for s in sections] == ["One"]


def test_a_real_preamble_before_the_first_section_is_kept():
    markdown = "# Guide\n\nThis journal publishes X.\n\n## One\n\nx\n"
    sections, title = jg.split_sections(markdown)
    assert title == []
    assert [s.title for s in sections] == ["preamble", "One"]
    assert "This journal publishes X." in "\n".join(sections[0].lines)


def test_apply_refuses_without_the_users_approval(tmp_path: Path):
    """The cut is a judgement call — merging topics, splitting one, dropping the
    page's own index — and it belongs to the user. `apply` is the only step that
    writes into guide/, so it is the only place the gate has to hold."""
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    jg.scaffold(tmp_path, "j")
    jg.propose(tmp_path, "j", src, "builtin")
    dest = tmp_path / "templates" / "journals" / "j" / "guide" / "sections"
    with pytest.raises(SystemExit) as err:
        jg.apply(tmp_path, "j")
    assert "NOT APPLIED" in str(err.value)
    assert "approval" in str(err.value)
    assert not list(dest.glob("*.md")), "a refused apply must leave guide/ untouched"
    jg.apply(tmp_path, "j", approved=True)
    assert list(dest.glob("*.md"))


def test_propose_does_not_touch_the_guide_and_apply_does(tmp_path: Path):
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    gdir = tmp_path / "templates" / "journals" / "j" / "guide"
    jg.scaffold(tmp_path, "j")
    jg.propose(tmp_path, "j", src, "builtin")
    work = gdir / "_work" / "sections"
    assert sorted(work.glob("*.md"))
    assert not list((gdir / "sections").glob("*.md")), "propose must not write the real guide"
    jg.apply(tmp_path, "j", approved=True)
    assert sorted((gdir / "sections").glob("*.md"))


def test_propose_refuses_to_silently_overwrite_a_reviewed_proposal(tmp_path: Path):
    src = tmp_path / "g.html"
    src.write_text(GUIDE_HTML, encoding="utf-8")
    jg.scaffold(tmp_path, "j")
    jg.propose(tmp_path, "j", src, "builtin")
    with pytest.raises(SystemExit, match="PROPOSAL|proposal"):
        jg.propose(tmp_path, "j", src, "builtin")


# --- links -----------------------------------------------------------------


def test_url_normalisation_absorbs_trailing_slash_and_tracking():
    assert jg.normalise_url("https://www.elsevier.com/open-access/") == jg.normalise_url(
        "https://elsevier.com/open-access?utm_source=x"
    )


def test_links_are_found_but_code_blocks_are_ignored():
    md = "See [x](a.md) and\n\n```\n[y](b.md)\n```\n"
    targets = [l.target for l in jg.find_links(md)]
    assert targets == ["a.md"]


def test_cites_finds_every_reference_in_the_bank(tmp_path: Path):
    gdir = tmp_path / "templates" / "journals" / "j" / "guide" / "sections"
    gdir.mkdir(parents=True)
    url = "https://elsevier.com/open-access"
    (gdir / "01-a.md").write_text(f"see [p]({url})\n", encoding="utf-8")
    (gdir / "02-b.md").write_text(f"see [p]({url}/)\n", encoding="utf-8")
    work = tmp_path / "templates" / "journals" / "j" / "guide" / "_work"
    work.mkdir()
    (work / "draft.md").write_text(f"[p]({url})\n", encoding="utf-8")
    (gdir.parent / "_raw").mkdir()
    (gdir.parent / "_raw" / "page.html").write_text(f"<a href='{url}'>", encoding="utf-8")
    hits = jg.cites(tmp_path, url)
    assert len(hits) == 2, "unpublished _work/ and raw _raw/ are not live references"


# --- the contract ----------------------------------------------------------


def test_a_journal_without_a_guide_is_opt_in(guide_repo: Path):
    # test-journal has one; a bare journal must report nothing at all.
    jg.scaffold(guide_repo, "other-journal")
    assert jg.check_guide(guide_repo, "other-journal").issues == []


def test_an_orphan_section_is_an_error(guide_repo: Path):
    gdir = guide_repo / "templates" / "journals" / "test-journal" / "guide"
    (gdir / "sections" / "99-ghost.md").write_text("## Ghost\n", encoding="utf-8")
    res = jg.check_guide(guide_repo, "test-journal")
    assert any("99-ghost.md is not listed" in i.message for i in res.errors)


def test_a_dangling_anchor_is_an_error(guide_repo: Path):
    sec = (guide_repo / "templates" / "journals" / "test-journal" / "guide" / "sections"
           / "01-before-you-begin.md")
    sec.write_text("## Before you begin\n\nSee [editorial manager](#editorial-manager).\n",
                   encoding="utf-8")
    res = jg.check_guide(guide_repo, "test-journal")
    assert any("broken anchor" in i.message for i in res.errors), res.errors


def test_a_broken_local_link_is_an_error(guide_repo: Path):
    sec = (guide_repo / "templates" / "journals" / "test-journal" / "guide" / "sections"
           / "01-before-you-begin.md")
    sec.write_text("## Before you begin\n\nSee [x](99-missing.md).\n", encoding="utf-8")
    res = jg.check_guide(guide_repo, "test-journal")
    assert any("broken link" in i.message for i in res.errors)


def test_missing_provenance_is_an_error(guide_repo: Path):
    (guide_repo / "templates" / "journals" / "test-journal" / "guide" / "SOURCES.md").unlink()
    res = jg.check_guide(guide_repo, "test-journal")
    assert any("SOURCES.md" in i.message for i in res.errors), res.errors


def test_a_stale_external_queue_is_a_warning(guide_repo: Path):
    """A shared page exists but the queue still says NOT MIRRORED: the classic
    half-finished promotion, and the one that leaves the bank pointing at a dead
    web page forever."""
    base = guide_repo / "templates" / "journals"
    (base / "_shared" / "elsevier").mkdir(parents=True)
    (base / "_shared" / "elsevier" / "open-access.md").write_text(
        "# Open access\n", encoding="utf-8"
    )
    ext = base / "test-journal" / "guide" / "external.md"
    ext.write_text(
        "# External\n\n| url | topic | state |\n|---|---|---|\n"
        "| https://www.elsevier.com/about/policies-and-standards/open-access | Open access | `NOT MIRRORED` |\n",
        encoding="utf-8",
    )
    res = jg.check_guide(guide_repo, "test-journal")
    assert any("stale queue" in i.message for i in res.warns)
    assert res.ok, "a half-finished promotion is not a broken bank yet"


def test_a_promoted_row_does_not_warn_about_being_uncited(guide_repo: Path):
    base = guide_repo / "templates" / "journals"
    (base / "_shared" / "elsevier").mkdir(parents=True)
    (base / "_shared" / "elsevier" / "open-access.md").write_text(
        "# Open access\n", encoding="utf-8"
    )
    (base / "test-journal" / "guide" / "external.md").write_text(
        "# External\n\n| url | topic | state |\n|---|---|---|\n"
        "| https://www.elsevier.com/about/policies-and-standards/open-access | Open access | mirrored: `../../../_shared/elsevier/open-access.md` |\n",
        encoding="utf-8",
    )
    res = jg.check_guide(guide_repo, "test-journal")
    assert not [i for i in res.warns if "no section links" in i.message]


def test_an_oversized_section_is_a_warning(guide_repo: Path):
    sec = (guide_repo / "templates" / "journals" / "test-journal" / "guide" / "sections"
           / "01-before-you-begin.md")
    sec.write_text("## Before you begin\n\n" + "\n".join(f"line {i}" for i in range(400)),
                   encoding="utf-8")
    res = jg.check_guide(guide_repo, "test-journal")
    assert any("over the" in i.message for i in res.warns)
    assert res.ok


def test_readding_a_journal_keeps_its_guide_pointers(mini_repo: Path):
    """`paper_journal.py --add-journal --force` rewrites type.yaml wholesale. If it
    dropped `guide:`, a routine journal update would leave the catalog pointing at
    a guide it no longer claims to describe."""
    import json

    from _repo import load_yaml
    from _structure import set_type_field

    type_yaml = mini_repo / "templates" / "journals" / "test-journal" / "type.yaml"
    set_type_field(type_yaml, "guide", "guide/index.md")
    set_type_field(type_yaml, "guide_retrieved", "2026-10-10")
    meta = mini_repo / "meta.json"
    meta.write_text(
        json.dumps({"journal": "Test Journal", "publisher": "Elsevier"}), encoding="utf-8"
    )
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "paper_journal.py"),
         "--root", str(mini_repo), "--add-journal", "test-journal", "--meta", str(meta),
         "--force"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    after = load_yaml(type_yaml)
    assert after["guide"] == "guide/index.md"
    assert after["guide_retrieved"] == "2026-10-10"


def test_the_shared_folder_is_named_after_the_publisher(tmp_path: Path):
    """Elsevier's open-access policy is not Springer Nature's. Filing them under
    one namespace would give a Springer page an Elsevier path, and the two would
    drift apart with nothing to notice."""
    import textwrap

    base = tmp_path / "templates" / "journals"
    for slug, publisher in (("j-springer", "Springer Nature"), ("j-elsevier", "Elsevier")):
        (base / slug).mkdir(parents=True)
        (base / slug / "type.yaml").write_text(
            f'journal: "J"\npublisher: {publisher}\n', encoding="utf-8")
    assert jg.shared_dir(tmp_path, "j-springer").name == "springer-nature"
    assert jg.shared_dir(tmp_path, "j-elsevier").name == "elsevier"


def test_a_stale_queue_points_at_the_right_publisher_folder(tmp_path: Path):
    """A Springer journal's half-finished promotion must look for its copy under
    _shared/springer-nature/, not under _shared/elsevier/."""
    base = tmp_path / "templates" / "journals"
    jdir = base / "j"
    jdir.mkdir(parents=True)
    (jdir / "type.yaml").write_text(
        'journal: "J"\npublisher: Springer Nature\nformat: latex\n'
        'cite_style: number\nguide: guide/index.md\n', encoding="utf-8")
    g = jdir / "guide"
    (g / "sections").mkdir(parents=True)
    (g / "sections" / "01-s.md").write_text("## S\n\nsee [p](https://x.test/oa)\n", encoding="utf-8")
    (g / "index.md").write_text("- [S](sections/01-s.md)\n", encoding="utf-8")
    (g / "SOURCES.md").write_text(
        "# S\n\n| what | url | retrieved | sha256 |\n|---|---|---|---|\n"
        "| g | https://x.test/g | 2026-10-10 | abc |\n", encoding="utf-8")
    (g / "external.md").write_text(
        "# E\n\n| url | topic | state |\n|---|---|---|\n"
        "| https://x.test/oa | Open access | `NOT MIRRORED` |\n", encoding="utf-8")
    # The copy exists, but under the other publisher's namespace: not a stale row.
    (base / "_shared" / "elsevier" / "open-access.md").parent.mkdir(parents=True)
    (base / "_shared" / "elsevier" / "open-access.md").write_text("# oa\n", encoding="utf-8")
    assert not [i for i in jg.check_guide(tmp_path, "j").warns if "stale" in i.message]
    # Put it where this journal would look, and now it is stale.
    (base / "_shared" / "springer-nature").mkdir(parents=True)
    (base / "_shared" / "springer-nature" / "open-access.md").write_text("# oa\n", encoding="utf-8")
    assert any("stale" in i.message for i in jg.check_guide(tmp_path, "j").warns)


def test_the_shared_folder_is_not_mistaken_for_a_journal(guide_repo: Path):
    """`_shared/` has no type.yaml by design; the validator must skip it."""
    import paper_validate

    (guide_repo / "templates" / "journals" / "_shared").mkdir()
    (guide_repo / "templates" / "journals" / "_shared" / "index.md").write_text(
        "# shared\n", encoding="utf-8"
    )
    report = paper_validate.validate_repo(guide_repo)
    assert not [e for e in report.errors if "_shared" in e], report.errors


# --- deduplication ---------------------------------------------------------


def _two_journal_repo(tmp_path: Path) -> Path:
    """Two Elsevier journals with one identical section and one that differs."""
    for slug in ("journal-a", "journal-b"):
        jdir = tmp_path / "templates" / "journals" / slug
        jdir.mkdir(parents=True)
        (jdir / "type.yaml").write_text(
            'journal: "J"\npublisher: Elsevier\nformat: latex\n'
            'cite_style: number\nguide: guide/index.md\n'
            'guide_retrieved: "2026-10-10"\n',
            encoding="utf-8",
        )
        jg.scaffold(tmp_path, slug)
        gdir = jdir / "guide"
        (gdir / "sections" / "01-ethics.md").write_text(
            "## Ethics\n\nSame words everywhere.\n", encoding="utf-8"
        )
        (gdir / "index.md").write_text(
            "# J\n\n- [Ethics](sections/01-ethics.md)\n", encoding="utf-8"
        )
        (gdir / "SOURCES.md").write_text(
            "# Sources\n\n| what | url | retrieved | sha256 |\n|---|---|---|---|\n"
            "| g | https://x.test/g | 2026-10-10 | abc |\n",
            encoding="utf-8",
        )
    other = "Same words everywhere."
    (tmp_path / "templates" / "journals" / "journal-b" / "guide" / "sections"
     / "02-limits.md").write_text(f"## Limits\n\nB says {other} plus more.\n", encoding="utf-8")
    (tmp_path / "templates" / "journals" / "journal-a" / "guide" / "sections"
     / "02-limits.md").write_text("## Limits\n\nA says something else entirely.\n", encoding="utf-8")
    for slug in ("journal-a", "journal-b"):
        gdir = tmp_path / "templates" / "journals" / slug
        index = gdir / "guide" / "index.md"
        index.write_text(index.read_text(encoding="utf-8")
                         + "- [Limits](sections/02-limits.md)\n", encoding="utf-8")
    return tmp_path


def test_normalization_ignores_provenance_and_whitespace():
    a = "<!-- guide section | source: full.md | heading: X | lines: 1-9 -->\n## X\n\nBody.   \n"
    b = "## X\n\nBody.\n"
    assert jg.section_hash(a) == jg.section_hash(b)
    assert jg.section_hash("## X\n\nBody plus one word.\n") != jg.section_hash(b)


def test_duplicate_groups_need_two_journals(tmp_path: Path):
    repo = _two_journal_repo(tmp_path)
    groups = jg.duplicate_groups(repo, "elsevier")
    assert len(groups) == 1, [(g["hash"][:8], g["files"]) for g in groups]
    assert {j for j, _ in groups[0]["files"]} == {"journal-a", "journal-b"}
    # A one-word difference is a different file: usually the journal's name.
    assert all("01-ethics.md" in str(p) for _, p in groups[0]["files"])


def test_duplicate_groups_stay_inside_one_publisher(tmp_path: Path):
    repo = _two_journal_repo(tmp_path)
    (repo / "templates" / "journals" / "journal-b" / "type.yaml").write_text(
        'journal: "J"\npublisher: Springer Nature\nformat: latex\n'
        'cite_style: number\nguide: guide/index.md\n',
        encoding="utf-8",
    )
    assert jg.duplicate_groups(repo, "elsevier") == []
    assert len(jg.duplicate_groups(repo, "springer-nature")) == 0


def test_promote_moves_one_copy_and_rewrites_both_indexes(tmp_path: Path):
    repo = _two_journal_repo(tmp_path)
    (repo / "templates" / "journals" / "journal-b" / "guide" / "external.md").write_text(
        "# E\n", encoding="utf-8")
    (repo / "templates" / "journals" / "journal-a" / "guide" / "external.md").write_text(
        "# E\n", encoding="utf-8")
    groups = jg.duplicate_groups(repo, "elsevier")
    dest = jg.promote_group(repo, groups[0])
    assert dest == repo / "templates" / "journals" / "_shared" / "elsevier" / "ethics.md"
    assert "origins:" in dest.read_text(encoding="utf-8").splitlines()[0]
    assert "Same words everywhere." in dest.read_text(encoding="utf-8")
    for slug in ("journal-a", "journal-b"):
        gdir = repo / "templates" / "journals" / slug / "guide"
        assert not (gdir / "sections" / "01-ethics.md").exists()
        assert "../../_shared/elsevier/ethics.md" in (gdir / "index.md").read_text(encoding="utf-8")
        assert jg.check_guide(repo, slug).ok, \
            [i.message for i in jg.check_guide(repo, slug).errors]
    assert jg.duplicate_groups(repo, "elsevier") == [], "the report must come back empty"


def test_promote_refuses_a_shared_name_collision(tmp_path: Path):
    repo = _two_journal_repo(tmp_path)
    taken = repo / "templates" / "journals" / "_shared" / "elsevier" / "ethics.md"
    taken.parent.mkdir(parents=True)
    taken.write_text("## Ethics\n\nEntirely different text.\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="different content"):
        jg.promote_group(repo, jg.duplicate_groups(repo, "elsevier")[0])


def test_remaining_duplicates_warn_but_do_not_fail(tmp_path: Path):
    repo = _two_journal_repo(tmp_path)
    for slug in ("journal-a", "journal-b"):
        (repo / "templates" / "journals" / slug / "guide" / "external.md").write_text(
            "# E\n", encoding="utf-8")
    res = jg.check_duplicates(repo)
    assert any("identical section in 2 guides" in i.message for i in res.warns)
    assert res.ok, "a fresh guide legitimately duplicates the boilerplate until promoted"


def test_a_broken_link_inside_a_shared_file_is_an_error(tmp_path: Path):
    repo = _two_journal_repo(tmp_path)
    shared = repo / "templates" / "journals" / "_shared" / "elsevier"
    shared.mkdir(parents=True)
    (shared / "ethics.md").write_text(
        "<!-- shared section | publisher: elsevier | origins: x | hash: y -->\n"
        "## Ethics\n\nSee [gone](missing.md).\n",
        encoding="utf-8",
    )
    res = jg.check_shared_files(repo)
    assert any("missing.md" in i.message for i in res.errors)


def test_a_url_cited_only_from_a_shared_file_still_counts_as_cited(tmp_path: Path):
    """After promotion the link lives in `_shared/`, not in `sections/`. The
    external queue must count it, or every promotion floods the queue with
    'no section links to it' warnings for URLs that are still linked."""
    repo = _two_journal_repo(tmp_path)
    for slug in ("journal-a", "journal-b"):
        (repo / "templates" / "journals" / slug / "guide" / "external.md").write_text(
            "# E\n\n| url | topic | state |\n|---|---|---|\n"
            "| https://x.test/shared-page | Shared page | `NOT MIRRORED` |\n",
            encoding="utf-8")
    # Hand-build the promoted state: the shared copy holds the link, the locals
    # are gone, both indexes point at the shared copy.
    shared = repo / "templates" / "journals" / "_shared" / "elsevier"
    shared.mkdir(parents=True)
    (shared / "ethics.md").write_text(
        "<!-- shared section | publisher: elsevier | origins: a b | hash: h -->\n"
        "## Ethics\n\nSee [p](https://x.test/shared-page).\n",
        encoding="utf-8")
    for slug in ("journal-a", "journal-b"):
        gdir = repo / "templates" / "journals" / slug / "guide"
        (gdir / "sections" / "01-ethics.md").unlink(missing_ok=True)
        (gdir / "index.md").write_text(
            "# J\n\n- [Ethics](../../_shared/elsevier/ethics.md)\n"
            "- [Limits](sections/02-limits.md)\n",
            encoding="utf-8")
    for slug in ("journal-a", "journal-b"):
        res = jg.check_guide(repo, slug)
        assert not [i for i in res.warns if "no section links" in i.message], \
            [i.message for i in res.warns]


def test_a_shared_section_and_a_shared_page_do_not_collide(tmp_path: Path):
    """The stale-queue check guesses `_shared/<topic>.md`. A promoted *section*
    with the same file name must not clear the queue for a *page* that was
    never mirrored."""
    repo = _two_journal_repo(tmp_path)
    for slug in ("journal-a", "journal-b"):
        (repo / "templates" / "journals" / slug / "guide" / "external.md").write_text(
            "# E\n\n| url | topic | state |\n|---|---|---|\n"
            "| https://x.test/transfer | Article Transfer Service | `NOT MIRRORED` |\n",
            encoding="utf-8")
    shared = repo / "templates" / "journals" / "_shared" / "elsevier"
    shared.mkdir(parents=True)
    (shared / "article-transfer-service.md").write_text(
        "<!-- shared section | publisher: elsevier | origins: a b | hash: h -->\n"
        "## Article Transfer Service\n\nA section, not the policy page.\n",
        encoding="utf-8")
    res = jg.check_guide(repo, "journal-a")
    assert not [i for i in res.warns if "stale queue" in i.message]


def test_a_shared_file_without_provenance_warns(tmp_path: Path):
    shared = tmp_path / "templates" / "journals" / "_shared" / "elsevier"
    shared.mkdir(parents=True)
    (shared / "orphan.md").write_text("## Orphan\n\nNo header.\n", encoding="utf-8")
    res = jg.check_shared_files(tmp_path)
    assert any("origins" in i.message for i in res.warns)
    assert res.ok