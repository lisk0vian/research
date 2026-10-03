"""Convert the portal's .xlsx dictionary and .docx metadata into plain Markdown.

Both formats are zip archives of XML, and both are read here with nothing but
the standard library. That is a deliberate constraint rather than a flourish:
this has to run on the Colab runtime, where `python-docx` is absent and
`openpyxl` is not guaranteed, and a converter that needs a package installed is
a converter that fails on the one machine the pipeline actually runs on.

`python-docx` and `openpyxl` would each be about thirty lines shorter. Neither
is worth a dependency for a one-shot document conversion.

The output is committed Markdown under `data/docs/`, so a reader never needs a
spreadsheet program or a word processor to know what the columns mean.

Usage
-----
    python portal_docs.py --xlsx path/to/dic.xlsx --docx path/to/meta.docx
    python portal_docs.py --package <dataset-id>      # fetch, then convert
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from _common import BASE, load_config, write_manifest

DOCS_DIR = BASE / "data" / "docs"
DICTIONARY_MD = DOCS_DIR / "data_dictionary.md"
METADATA_MD = DOCS_DIR / "metadata.md"

# Emails and long digit runs are the two things that leak into a public repo
# from a provider document, so they are removed rather than trusted.
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")

# Office namespace prefixes, stripped so tag names compare literally.
_NS = re.compile(r"^\{[^}]*\}")


def _tag(el) -> str:
    return _NS.sub("", el.tag)


def _clean(text: str) -> str:
    """Collapse whitespace and drop contact addresses.

    The portal's own metadata carries a contact mailbox. AGENTS.md forbids
    emails in a public repository, and a provider document is exactly how one
    gets in by accident, so the address is redacted here rather than by
    remembering to remove it later.
    """
    text = EMAIL_RE.sub("[contact redacted]", text)
    return re.sub(r"\s+", " ", text).strip()


# --- xlsx ------------------------------------------------------------------

def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root:
        # A rich-text cell splits its content across several <t> runs; joining
        # them without a separator would weld the words of a sentence together.
        out.append(_clean("".join(t.text or "" for t in si.iter()
                                  if _tag(t) == "t")))
    return out


def _column_index(ref: str) -> int:
    """'BC12' -> 54. Zero-based, so A is 0."""
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return 0
    n = 0
    for ch in letters.group(1):
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def xlsx_rows(path: Path) -> list[list[str]]:
    """First worksheet as a dense list of rows, blanks preserved."""
    with zipfile.ZipFile(path) as zf:
        shared = _shared_strings(zf)
        name = next((n for n in zf.namelist()
                     if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")),
                    None)
        if name is None:
            raise ValueError(f"{path} has no worksheet")
        root = ET.fromstring(zf.read(name))

    rows: list[list[str]] = []
    for row in root.iter():
        if _tag(row) != "row":
            continue
        cells: dict[int, str] = {}
        for cell in row:
            if _tag(cell) != "c":
                continue
            idx = _column_index(cell.get("r", ""))
            kind = cell.get("t", "")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter() if _tag(t) == "t")
            else:
                node = next((c for c in cell if _tag(c) == "v"), None)
                value = node.text if node is not None and node.text else ""
                if kind == "s" and value.isdigit() and int(value) < len(shared):
                    value = shared[int(value)]
            cells[idx] = _clean(value)
        width = max(cells, default=-1) + 1
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def _is_blank(row: list[str]) -> bool:
    return not any(c for c in row)


def render_dictionary(rows: list[list[str]], title: str, source: str) -> str:
    """Markdown for the variable dictionary.

    The sheet opens with a dataset-name row, a blank, then a header. The header
    is located by looking for the column that says Variable, because the layout
    is stable but the row index is not worth hardcoding against.
    """
    body = [r for r in rows if not _is_blank(r)]
    if not body:
        raise ValueError("dictionary sheet is empty")

    head_idx = next((i for i, r in enumerate(body)
                     if r and r[0].strip().lower() == "variable"), None)
    dataset_name = body[0][1] if len(body[0]) > 1 and body[0][1] else title
    if head_idx is None:
        raise ValueError(f"no 'Variable' header row found in {source}")

    header = body[head_idx]
    out = [
        "# Variable dictionary",
        "",
        f"**Dataset:** {dataset_name}",
        "",
        "Converted from the provider's spreadsheet into Markdown so it reads without a",
        "spreadsheet program. Regenerate with `python portal_docs.py --xlsx <file>` after",
        "fetching the portal resource; see `data/SOURCE.json` for where it came from.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in body[head_idx + 1:]:
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in row[:len(header)]) + " |")
    out.append("")
    return "\n".join(out)


# --- docx ------------------------------------------------------------------

def docx_blocks(path: Path) -> list[tuple[str, object]]:
    """Ordered ('p'|'tbl', content) blocks from the document body."""
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    body = next((el for el in root.iter() if _tag(el) == "body"), None)
    if body is None:
        raise ValueError(f"{path} has no body")

    blocks: list[tuple[str, object]] = []
    for el in body:
        kind = _tag(el)
        if kind == "p":
            text = _clean("".join(t.text or "" for t in el.iter() if _tag(t) == "t"))
            if text:
                blocks.append(("p", text))
        elif kind == "tbl":
            rows = []
            for tr in (r for r in el if _tag(r) == "tr"):
                cells = []
                for tc in (c for c in tr if _tag(c) == "tc"):
                    cells.append(_clean("".join(
                        t.text or "" for t in tc.iter() if _tag(t) == "t")))
                if any(cells):
                    rows.append(cells)
            if rows:
                blocks.append(("tbl", rows))
    return blocks


def docx_title(blocks: list[tuple[str, object]]) -> str:
    """The dataset title, from the document itself rather than the filename.

    The metadata opens with a paragraph naming the dataset, so the title is
    recoverable from the content. Using the filename instead put "meta" in the
    heading, which is not a fact anyone can check.
    """
    for kind, content in blocks:
        if kind != "p":
            continue
        text = str(content)
        for marker in ("Metadatos del dataset:", "Nombre del Dataset:"):
            if marker.lower() in text.lower():
                return text[text.lower().index(marker.lower()) + len(marker):].strip(" :")
        if len(text) > 30:
            return text
    return ""


def render_metadata(blocks: list[tuple[str, object]], title: str, source: str) -> str:
    out = [
        "# Dataset metadata",
        "",
        f"**Dataset:** {title}",
        "",
        "Converted from the provider's Word document into Markdown so it reads without a",
        "word processor. Regenerate with `python portal_docs.py --docx <file>`.",
        "",
        "Contact addresses are redacted: this repository is public and AGENTS.md forbids",
        "emails in it.",
        "",
    ]
    for kind, content in blocks:
        if kind == "tbl":
            width = max(len(r) for r in content)  # type: ignore[arg-type]
            header = content[0] + [""] * (width - len(content[0]))  # type: ignore[index]
            out.append("| " + " | ".join(header) + " |")  # type: ignore[arg-type]
            out.append("|" + "|".join(["---"] * width) + "|")
            for row in content[1:]:  # type: ignore[union-attr]
                padded = list(row) + [""] * (width - len(row))  # type: ignore[arg-type]
                out.append("| " + " | ".join(
                    c.replace("|", "\\|") for c in padded[:width]) + " |")
            out.append("")
        else:
            out.append(str(content))
            out.append("")
    return "\n".join(out).rstrip() + "\n"


# --- portal ----------------------------------------------------------------

def find_doc_resources(cfg: dict, timeout: int = 120) -> list[dict]:
    """The dictionary and metadata resources attached to the dataset."""
    import json
    import urllib.request

    from fetch_source import resolve_resource  # noqa: PLC0415 - avoids a cycle

    found = resolve_resource(cfg, timeout)
    pkg = found["package"]
    out = []
    for res in pkg.get("resources", []):
        name = (res.get("name") or "").lower()
        if res.get("format") in {".xlsx", "xlsx"} or "diccionario" in name:
            out.append({"role": "dictionary", **res})
        elif res.get("format") in {".docx", "docx"} or "metadato" in name:
            out.append({"role": "metadata", **res})
    if not out:
        raise SystemExit(
            "the package exposes no dictionary or metadata resource; pass "
            "--xlsx and --docx explicitly"
        )
    return out


def download_doc(url: str, dest: Path, timeout: int) -> Path:
    """Fetch a portal document.

    The portal sits behind a WAF that answers requests carrying a default
    script User-Agent with HTTP 418 and an interstitial page, so a browser
    User-Agent is required. That is not evasion: the same host serves the CSV
    fine, and the portal publishes these documents for anyone to read.
    """
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if len(body) < 512:
        raise SystemExit(f"{url} returned only {len(body)} bytes, which is not a document")
    dest.write_bytes(body)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsx", type=Path, help="variable dictionary to convert")
    ap.add_argument("--docx", type=Path, help="metadata document to convert")
    ap.add_argument("--package", action="store_true",
                    help="fetch both from the configured dataset and convert")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args(argv)
    if not any((args.xlsx, args.docx, args.package)):
        ap.error("give --xlsx, --docx or --package")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    if args.package:
        import tempfile

        cfg = load_config()
        for res in find_doc_resources(cfg, args.timeout):
            suffix = ".xlsx" if res["role"] == "dictionary" else ".docx"
            with tempfile.TemporaryDirectory() as tmp:
                local = download_doc(res["url"], Path(tmp) / f"doc{suffix}", args.timeout)
                if res["role"] == "dictionary":
                    text = render_dictionary(xlsx_rows(local), res.get("name", ""), res["url"])
                    DICTIONARY_MD.write_text(text, encoding="utf-8")
                    written.append(str(DICTIONARY_MD.relative_to(BASE)))
                else:
                    blocks = docx_blocks(local)
                    text = render_metadata(blocks, docx_title(blocks) or res.get("name", ""),
                                           res["url"])
                    METADATA_MD.write_text(text, encoding="utf-8")
                    written.append(str(METADATA_MD.relative_to(BASE)))
                print(f"[ok] {res['role']}: {res.get('name')} -> "
                      f"{'data_dictionary.md' if res['role'] == 'dictionary' else 'metadata.md'}")
    else:
        if args.xlsx:
            title = _title_from(xlsx_rows(args.xlsx))
            DICTIONARY_MD.write_text(
                render_dictionary(xlsx_rows(args.xlsx), title, str(args.xlsx)),
                encoding="utf-8")
            written.append(str(DICTIONARY_MD.relative_to(BASE)))
            print(f"[ok] {args.xlsx.name} -> data/docs/data_dictionary.md")
        if args.docx:
            blocks = docx_blocks(args.docx)
            METADATA_MD.write_text(
                render_metadata(blocks, docx_title(blocks) or args.docx.stem,
                                str(args.docx)),
                encoding="utf-8")
            written.append(str(METADATA_MD.relative_to(BASE)))
            print(f"[ok] {args.docx.name} -> data/docs/metadata.md")

    if written:
        write_manifest({"docs": {"generated": sorted(written)}})
    return 0


def _title_from(rows: list[list[str]]) -> str:
    for row in rows:
        for cell in row:
            if len(cell) > 20:
                return cell
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
