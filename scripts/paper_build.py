#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_build.py — verify the environment and render paper/main.qmd.

Two phases, both explicit and re-runnable:

  1. check  — verify quarto, the LaTeX engine (for PDF), the journal's Quarto
              extension and the bibliography. Never installs anything; reports
              the exact command to run when something is missing.
  2. render — `quarto render` to PDF and/or DOCX from a scratch copy in
              papers/<slug>/build/render/, rename the output to
              <slug>.pdf / <slug>.docx, and package the LaTeX submission
              source (tex + class/style/bst + figures + bib/bbl +
              highlights.txt) as <slug>-latex.zip next to the pdf.
              Submission documents go next to them: <slug>-title-page.docx/.pdf
              when journal.formatting anonymizes the manuscript (built from
              main.qmd's own front matter), and <slug>-cover-letter.docx/.pdf
              when paper/cover-letter.qmd exists.
              Each figure is also copied to build/figures/Figure_N.<ext>.

Usage:
    python scripts/paper_build.py --slug c15-2026 --format all
    python scripts/paper_build.py --slug c15-2026 --check-only
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900)
        return out.returncode, (out.stdout + out.stderr).strip()
    except Exception as exc:  # pragma: no cover
        return 1, str(exc)


def resolve_format(repo: Path, slug: str, paper_dir: Path) -> tuple[str, str, list[str], list[str]]:
    """Return (quarto_format, extension, ok_lines, problems)."""
    ok: list[str] = []
    problems: list[str] = []
    extension = ""
    quarto_format = "pdf"

    manifest = paper_dir.parent / "manifest.yaml"
    journal = ""
    if manifest.is_file():
        journal = str(load_yaml(manifest).get("journal") or "")
    if journal:
        type_yaml = repo / "templates" / "journals" / journal / "type.yaml"
        if type_yaml.is_file():
            tj = load_yaml(type_yaml)
            quarto_format = tj.get("quarto_format") or "pdf"
            extension = tj.get("extension") or tj.get("quarto_extension") or ""
            ok.append(f"journal: {journal} (quarto_format={quarto_format})")
        else:
            problems.append(f"journal '{journal}' not in templates/journals/")
    else:
        problems.append("no journal set in manifest.yaml (run scripts/paper_journal.py)")

    return quarto_format, extension, ok, problems


def extension_source(repo: Path, paper_dir: Path) -> tuple[Path | None, str]:
    """Canonical extension directory (templates/journals/<journal>/quarto-extension/_extensions).

    Returns (None, "") when the journal or its extension is not set up yet.
    """
    journal = ""
    manifest = paper_dir.parent / "manifest.yaml"
    if manifest.is_file():
        journal = str(load_yaml(manifest).get("journal") or "")
    if not journal:
        return None, ""
    src = repo / "templates" / "journals" / journal / "quarto-extension" / "_extensions"
    return (src if src.is_dir() else None), journal


def prepare_render_dir(paper_dir: Path, build_dir: Path) -> Path:
    """Copy the paper sources into a fresh build/render/ (scratch render dir).

    Rendering from there keeps paper/ pristine: Quarto flattens the
    extension's format-resources (cls/sty/bst/jpg), copies _extensions/ and
    writes the LaTeX intermediates next to the *input* document, so the
    input must be this copy rather than the tracked source folder.
    """
    render_dir = build_dir / "render"
    if render_dir.exists():
        shutil.rmtree(render_dir, ignore_errors=True)
    render_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.qmd", "*.bib"):
        for file in sorted(paper_dir.glob(pattern)):
            shutil.copy2(file, render_dir / file.name)
    media = paper_dir / "media"
    if media.is_dir():
        shutil.copytree(media, render_dir / "media", dirs_exist_ok=True)
    return render_dir


def sync_extension(repo: Path, paper_dir: Path, dest: Path) -> tuple[bool, str]:
    """Copy the journal's canonical extension into dest/_extensions.

    paper_dir is only used to resolve the journal (manifest.yaml); the copy
    goes to dest, which is build/render/ during a build, so the tracked
    paper/ folder never holds build-time copies. The single source of truth
    stays under templates/journals/. Returns (synced, message).
    """
    src, journal = extension_source(repo, paper_dir)
    if src is None:
        return False, "no canonical extension under templates/journals/ for this journal"
    dst = dest / "_extensions"
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        # cas-common.sty includes the 8pt footnote icons as
        # thumbnails/<file>.jpeg, but quarto's format-resources copy
        # FLATTENS that subdirectory into the working directory. The class
        # runs with cwd = the render dir and expects the layout restored
        # there: copy them from <ext>/thumbnails (namespace/<name>/thumbnails).
        icon_dirs = sorted(src.glob("*/*/thumbnails"))
        for icons in icon_dirs:
            shutil.copytree(icons, dest / "thumbnails", dirs_exist_ok=True)
    except Exception as exc:
        return False, f"extension sync failed: {exc}"
    n_ext = len(list(dst.rglob("_extension.yml")))
    msg = f"synced from templates/journals/{journal}/quarto-extension ({n_ext} extension(s))"
    if not icon_dirs:
        msg += " [warn] no <ext>/thumbnails found — icons will be missing"
    return True, msg


def docx_target(repo: Path, paper_dir: Path) -> str:
    """`<ext>-docx` when the journal extension contributes a docx format,
    plain `docx` otherwise (pandoc default)."""
    src, _journal = extension_source(repo, paper_dir)
    if src is None:
        return "docx"
    for yml in sorted(src.glob("*/*/_extension.yml")):
        data = load_yaml(yml)
        formats = (data.get("contributes") or {}).get("formats") or {}
        if "docx" in formats:
            return yml.parent.name + "-docx"
    return "docx"


def qmd_front_matter(paper_dir: Path) -> dict:
    """Parsed YAML front matter of paper/main.qmd ({} when absent/invalid)."""
    qmd = paper_dir / "main.qmd"
    if not qmd.is_file():
        return {}
    text = qmd.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---") or text.count("---") < 2:
        return {}
    try:
        import yaml  # PyYAML is a repo dependency (see scripts/_repo.py)

        data = yaml.safe_load(text.split("---", 2)[1]) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def short_in_text_citations(paper_dir: Path) -> bool:
    """True when the paper drops natbib's longnamesfirst.

    cas.lua: journal.natbib-options replaces the default
    'authoryear,longnamesfirst', so a non-empty value without longnamesfirst
    makes the PDF use "X et al." from the first citation (e.g. EAAI's
    cas-model2-names-etal). The docx path mirrors that policy.
    """
    journal = qmd_front_matter(paper_dir).get("journal")
    if not isinstance(journal, dict):
        return False
    natbib = str(journal.get("natbib-options") or "")
    return bool(natbib) and "longnamesfirst" not in natbib


def is_blind(paper_dir: Path) -> bool:
    """True when main.qmd sets journal.formatting to singleblind/doubleblind.

    cas-sc.cls then hides authors, affiliations and CRediT in the PDF,
    cas-docx.lua does the same in the docx, and the identifying data move to
    a separate title page (render_title_page).
    """
    journal = qmd_front_matter(paper_dir).get("journal")
    if not isinstance(journal, dict):
        return False
    return str(journal.get("formatting") or "").endswith("blind")


def _letters(n: int) -> str:
    """0 -> a, 25 -> z, 26 -> aa (Elsevier affiliation marks)."""
    out = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("a") + rem) + out
    return out


def title_page_markdown(front: dict) -> str:
    """Elsevier title page built from main.qmd's own front matter.

    Title, authors in order with a lower-case superscript letter per
    affiliation, each affiliation with its full postal address and country,
    and the corresponding author(s) with e-mail. Built from main.qmd so the
    title page can never drift from the manuscript.
    """
    def esc(text: object) -> str:
        return re.sub(r"([\\`*_{}\[\]<>#+!|^~])", r"\\\1", str(text or "").strip())

    affs = [a for a in front.get("affiliations") or [] if isinstance(a, dict)]
    letter = {str(a.get("id")): _letters(i) for i, a in enumerate(affs)}
    names, corresponding = [], []
    for author in front.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = author.get("name")
        name = name.get("literal") if isinstance(name, dict) else name
        refs = [r.get("ref") if isinstance(r, dict) else r
                for r in author.get("affiliation") or author.get("affiliations") or []]
        marks = [letter[str(r)] for r in refs if str(r) in letter]
        cas = author.get("cas") if isinstance(author.get("cas"), dict) else {}
        if cas.get("cormark") or author.get("corresponding"):
            marks.append("\\*")
            corresponding.append((name, author.get("email"), author.get("phone")))
        sup = f"^{','.join(marks)}^" if marks else ""
        names.append(f"{esc(name)}{sup}")

    def address(aff: dict) -> str:
        parts = [aff.get("name"), aff.get("department"), aff.get("address"),
                 " ".join(str(p) for p in (aff.get("postal-code"), aff.get("city")) if p),
                 aff.get("region"), aff.get("country")]
        return ", ".join(esc(p) for p in parts if p)

    lines = [
        "---",
        "format:",
        "  docx: default",
        "  pdf:",
        "    papersize: a4",
        "    geometry: margin=2.5cm",
        "    pagestyle: empty",
        "---",
        "",
        "**Title page**",
        "",
        f"## {esc(front.get('title'))}",
        "",
        ", ".join(names),
        "",
    ]
    for aff in affs:
        lines += [f"^{letter[str(aff.get('id'))]}^ {address(aff)}", ""]
    for name, email, phone in corresponding:
        tel = f" Telephone: {esc(phone)}." if phone else ""
        lines += [f"^\\*^ Corresponding author: {esc(name)}. E-mail: {esc(email)}.{tel}", ""]
    # What the anonymized manuscript must leave out moves here (Elsevier's
    # double-anonymized guidelines): main.qmd's top-level `title-page:` block.
    extra = front.get("title-page") if isinstance(front.get("title-page"), dict) else {}
    for key, heading in (("acknowledgements", "Acknowledgements"),
                         ("funding", "Funding"),
                         ("competing-interests", "Declaration of competing interest")):
        text = str(extra.get(key) or "").strip()
        if text:
            lines += [f"**{heading}**", "", text, ""]
    return "\n".join(lines)


def running_heads(repo: Path, paper_dir: Path) -> tuple[str, str]:
    """(short title, first author full name) for the docx header/footer.

    short-title: main.qmd top-level journal.short-title (fallback: title,
    truncated). first author: manifest authors[0] -> authors/<id>.yaml name,
    or "" when journal.formatting is singleblind/doubleblind (anonymized).
    """
    data = qmd_front_matter(paper_dir)
    journal = data.get("journal")
    short = str(journal.get("short-title") or "") if isinstance(journal, dict) else ""
    title = str(data.get("title") or "")
    if not short:
        short = (title[:60] + "…") if len(title) > 60 else title
    if is_blind(paper_dir):
        return short or "Short title", ""
    first = "Author"
    manifest = paper_dir.parent / "manifest.yaml"
    if manifest.is_file():
        authors = load_yaml(manifest).get("authors") or []
        if authors and isinstance(authors[0], dict) and authors[0].get("id"):
            person = load_yaml(repo / "authors" / f"{authors[0]['id']}.yaml")
            first = str(person.get("name") or first)
    return short or "Short title", first


def submission_highlights(paper_dir: Path) -> list[str]:
    """journal.highlights from main.qmd, for the submission zip.

    EAAI asks for highlights as a separate file whose name contains
    "highlights" (3-5 bullets, each <= 85 characters).
    """
    journal = qmd_front_matter(paper_dir).get("journal")
    items = journal.get("highlights") if isinstance(journal, dict) else None
    out = [str(item) for item in items or []]
    long = [h for h in out if len(h) > 85]
    if long:
        print(f"  [warn] {len(long)} highlight(s) exceed 85 chars (EAAI limit)")
    return out


def make_latex_zip(render_dir: Path, build_dir: Path, slug: str,
                   highlights: list[str] | None = None) -> tuple[bool, str]:
    """Package the LaTeX submission source as build/<slug>-latex.zip.

    EAAI takes editable sources only (.tex, not PDF), so the zip carries
    everything needed to compile main.tex standalone: the class/style/bst
    files quarto flattened, the figures, the icon thumbnails the class
    includes, the .bib and the compiled .bbl — plus highlights.txt written
    from journal.highlights (the guide wants it as a separate file).
    Aux/log files and the flattened root-level icon duplicates stay out.
    """
    if not (render_dir / "main.tex").is_file():
        return False, "main.tex missing in render dir (render the pdf first)"
    # quarto deletes the aux files after a successful render; rebuild the
    # minimal set (one latex pass + bibtex) to ship the compiled .bbl that
    # Elsevier expects alongside the .bib. Non-fatal: if anything fails the
    # zip still goes out and the reviewer can run bibtex on references.bib.
    if not (render_dir / "main.bbl").is_file():
        engine = next(
            (e for e in ("pdflatex", "xelatex", "lualatex") if shutil.which(e)),
            None,
        )
        if engine:
            run([engine, "-interaction=nonstopmode", "main.tex"],
                cwd=render_dir)
            if (render_dir / "main.aux").is_file():
                run(["bibtex", "main"], cwd=render_dir)
    entries: list[Path] = [Path("main.tex")]
    for pattern in ("*.cls", "*.sty", "*.bst", "*.bib", "*.bbl"):
        entries += sorted(
            p.relative_to(render_dir) for p in render_dir.glob(pattern))
    for folder in ("media", "thumbnails"):
        base = render_dir / folder
        if base.is_dir():
            entries += sorted(
                p.relative_to(render_dir) for p in base.rglob("*")
                if p.is_file())
    zip_path = build_dir / f"{slug}-latex.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in entries:
            z.write(render_dir / rel, rel.as_posix())
        if highlights:
            z.writestr("highlights.txt", "".join(f"{h}\n" for h in highlights))
    size_kb = zip_path.stat().st_size // 1024
    extra = 1 if highlights else 0
    note = "" if (render_dir / "main.bbl").is_file() else " — no .bbl (bibtex did not run)"
    return True, (f"zip {zip_path.name}: {len(entries) + extra} files, "
                  f"{size_kb} KB{note}")


def patch_docx_heads(repo: Path, paper_dir: Path, docx: Path) -> None:
    """Rewrite the placeholder running heads of the built docx (the committed
    reference.docx carries static placeholders by design)."""
    src, _journal = extension_source(repo, paper_dir)
    tool = (src.parent / "tools" / "make_reference_docx.py") if src else None
    if tool is None or not tool.is_file():
        print("  running heads: [warn] make_reference_docx.py not found")
        return
    short, first = running_heads(repo, paper_dir)
    rc, out = run([
        sys.executable, str(tool), "--patch-running-heads", str(docx),
        "--short-title", short, "--first-author", first,
    ])
    if rc == 0:
        footer = f"'{first} et al.'" if first else "anonymized"
        print(f"  running heads: header '{short[:40]}…' / footer {footer}"
              if len(short) > 40 else
              f"  running heads: header '{short}' / footer {footer}")
    else:
        print("  running heads: [warn] patch failed")
        print("  " + "\n  ".join(out.splitlines()[-8:]))
    # cas layout pass (floats, equation numbers, lists, notes): the OOXML that
    # neither the reference doc nor the Lua filter can reach.
    post = tool.parent / "cas_docx_post.py"
    if post.is_file():
        cmd = [sys.executable, str(post), str(docx)]
        pdf = docx.with_suffix(".pdf")
        if pdf.is_file():
            # floats go to the PDF's pages (render the pdf first: --format all)
            cmd += ["--pdf", str(pdf)]
        latex_zip = docx.with_name(docx.stem + "-latex.zip")
        if latex_zip.is_file():
            # references and citations from the PDF's .bbl (identical text)
            cmd += ["--latex-zip", str(latex_zip)]
        if short_in_text_citations(paper_dir):
            # the PDF uses short citations from the first citation; keep the
            # docx in step with it.
            cmd += ["--short-citations"]
        rc, out = run(cmd)
        print("  layout: cas_docx_post applied" if rc == 0 else
              "  layout: [warn] cas_docx_post failed\n  "
              + "\n  ".join(out.splitlines()[-8:]))


def check(repo: Path, slug: str, fmt: str, paper_dir: Path) -> tuple[list[str], list[str], list[str], str, str]:
    need_pdf = fmt in ("pdf", "all")
    ok: list[str] = []
    warnings: list[str] = []
    problems: list[str] = []

    if shutil.which("quarto"):
        rc, ver = run(["quarto", "--version"])
        ok.append(f"quarto {ver.splitlines()[0] if ver else '?'}")
    else:
        problems.append("quarto not on PATH — https://quarto.org/docs/get-started/")

    qmd = paper_dir / "main.qmd"
    if not qmd.is_file():
        problems.append(f"main.qmd missing at {qmd} (run paper-new / paper-migrate first)")
    else:
        ok.append("main.qmd present")

    bib = paper_dir / "references.bib"
    has_entries = bib.is_file() and any(
        line.strip().startswith("@") for line in bib.read_text(encoding="utf-8", errors="ignore").splitlines()
    )
    if has_entries:
        ok.append("references.bib has entries")
    else:
        warnings.append("references.bib empty or has no @entries — bibliography will be blank")

    quarto_format, extension, fok, fprob = resolve_format(repo, slug, paper_dir)
    ok += fok
    problems += fprob

    if need_pdf and extension:
        ext_dir = paper_dir / "_extensions"
        installed = ext_dir.is_dir() and any(ext_dir.rglob("_extension.yml"))
        src, _journal = extension_source(repo, paper_dir)
        if installed:
            ok.append(f"Quarto extension present ({extension})")
        elif src is not None:
            ok.append(
                f"Quarto extension not yet installed — synced from templates/journals/ at render"
            )
        else:
            problems.append(
                f"Quarto extension '{extension}' has no canonical copy in "
                f"templates/journals/ and is not installed in papers/{slug}/paper/_extensions"
            )

    if need_pdf:
        has_engine = any(shutil.which(e) for e in ("xelatex", "pdflatex", "lualatex"))
        tinytex_ok = False
        if shutil.which("quarto"):
            _, tools = run(["quarto", "list", "tools"])
            tinytex_ok = "tinytex" in tools.lower() and "installed" in tools.lower()
        if has_engine or tinytex_ok:
            ok.append("LaTeX engine available")
        else:
            problems.append("no LaTeX engine for PDF. Install: quarto install tinytex")

    return ok, warnings, problems, quarto_format, extension


FIGURE_REF = re.compile(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)\{#fig-")


def export_figures(paper_dir: Path, build_dir: Path) -> str:
    """Copy every figure, in order of appearance, to build/figures/Figure_N.<ext>.

    Elsevier asks for each figure as a separate file with a logical name
    (Figure_1, Figure_2, ...) besides the editable manuscript. The files are
    the manuscript's own sources, so they cannot differ from what it shows.
    """
    qmd = paper_dir / "main.qmd"
    sources = FIGURE_REF.findall(qmd.read_text(encoding="utf-8")) if qmd.is_file() else []
    out = build_dir / "figures"
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    if not sources:
        return "figures: none in main.qmd"
    out.mkdir(parents=True)
    missing = []
    for n, rel in enumerate(sources, start=1):
        src = paper_dir / rel
        if src.is_file():
            shutil.copy2(src, out / f"Figure_{n}{src.suffix.lower()}")
        else:
            missing.append(rel)
    msg = f"figures: {len(sources) - len(missing)} file(s) -> {out}"
    return msg + (f" [warn] missing: {', '.join(missing)}" if missing else "")


def render_submission_docs(paper_dir: Path, render_dir: Path, build_dir: Path,
                           slug: str, wants: list[str]) -> int:
    """Render the title page (anonymized papers) and the cover letter.

    Both are plain pandoc docx/pdf, not the journal format: they are
    separate submission files that the editor reads, never typeset.
    """
    docs: list[tuple[str, str]] = []
    if is_blind(paper_dir):
        page = render_dir / "title-page.qmd"
        page.write_text(title_page_markdown(qmd_front_matter(paper_dir)), encoding="utf-8")
        docs.append(("title-page", page.name))
    if (render_dir / "cover-letter.qmd").is_file():
        docs.append(("cover-letter", "cover-letter.qmd"))
    rc_total = 0
    for name, source in docs:
        for kind in wants:
            rc, out = run(["quarto", "render", source, "--to", kind, "--output-dir", ".."],
                          cwd=render_dir)
            produced = build_dir / f"{Path(source).stem}.{kind}"
            final = build_dir / f"{slug}-{name}.{kind}"
            if rc == 0 and produced.is_file():
                produced.replace(final)
                print(f"  rendered {final}")
            else:
                rc_total = 1
                print(f"  FAILED {name} {kind} (quarto render {source} --to {kind})")
                print("  " + "\n  ".join(out.splitlines()[-15:]))
    return rc_total


def render(repo: Path, slug: str, fmt: str, quarto_format: str, extension: str) -> int:
    paper_dir = repo / "papers" / slug / "paper"
    build_dir = repo / "papers" / slug / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    render_dir = prepare_render_dir(paper_dir, build_dir)
    synced, msg = sync_extension(repo, paper_dir, render_dir)
    print(f"  extension: {msg}" if synced else f"  extension: [warn] {msg}")
    wants = ["pdf", "docx"] if fmt == "all" else [fmt]
    rc_total = 0
    for kind in wants:
        target = quarto_format if kind == "pdf" else docx_target(repo, paper_dir)
        if kind == "pdf" and not extension:
            target = "pdf"
        extra: list[str] = []
        if kind == "docx":
            etal_csl = Path("_extensions/quarto-journals/elsevier-cas/elsevier-harvard-etal.csl")
            if short_in_text_citations(paper_dir) and (render_dir / etal_csl).is_file():
                # short in-text citations from the first citation, as the PDF
                # renders them (citeproc fallback path; cas_docx_post relabels
                # from the .bbl when it is available).
                extra = ["-M", f"csl:{etal_csl.as_posix()}"]
        rc, out = run(
            ["quarto", "render", "main.qmd", "--to", target, "--output-dir", "..", *extra],
            cwd=render_dir,
        )
        produced = build_dir / f"main.{kind}"
        final = build_dir / f"{slug}.{kind}"
        if rc == 0 and produced.is_file():
            if final.exists():
                final.unlink()
            produced.rename(final)
            print(f"  rendered {final}")
            if kind == "pdf":
                zip_ok, zip_msg = make_latex_zip(
                    render_dir, build_dir, slug, submission_highlights(paper_dir))
                print(f"  {zip_msg}" if zip_ok else f"  [warn] {zip_msg}")
            if kind == "docx":
                patch_docx_heads(repo, paper_dir, final)
        elif rc == 0 and final.is_file():
            print(f"  rendered {final} (already named)")
            if kind == "pdf":
                zip_ok, zip_msg = make_latex_zip(
                    render_dir, build_dir, slug, submission_highlights(paper_dir))
                print(f"  {zip_msg}" if zip_ok else f"  [warn] {zip_msg}")
            if kind == "docx":
                patch_docx_heads(repo, paper_dir, final)
        else:
            rc_total = 1
            print(f"  FAILED {kind} (quarto render --to {target})")
            print("  " + "\n  ".join(out.splitlines()[-15:]))
    rc_total |= render_submission_docs(paper_dir, render_dir, build_dir, slug, wants)
    print(f"  {export_figures(paper_dir, build_dir)}")
    return rc_total


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify and render a paper.")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--format", default="all", choices=["pdf", "docx", "all"])
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    paper_dir = repo / "papers" / args.slug / "paper"
    if not paper_dir.is_dir():
        raise SystemExit(f"ERROR: papers/{args.slug}/paper not found")

    ok, warnings, problems, quarto_format, extension = check(repo, args.slug, args.format, paper_dir)

    print("=== build environment check ===")
    print(f"paper: {args.slug}   format: {args.format}\n")
    for line in ok:
        print(f"  [ok]   {line}")
    for line in warnings:
        print(f"  [warn] {line}")
    for line in problems:
        print(f"  [MISS] {line}")

    if problems:
        print("\nRESULT: missing required components — fix the [MISS] items above.")
        return 1

    if args.check_only:
        print("\nRESULT: environment OK.")
        return 0

    print("\nRendering ...")
    return render(repo, args.slug, args.format, quarto_format, extension)


if __name__ == "__main__":
    raise SystemExit(main())
