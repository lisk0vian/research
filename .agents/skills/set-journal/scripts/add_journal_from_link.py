#!/usr/bin/env python3
"""
add_journal_from_link.py — create/update templates/journals/<slug>/type.yaml
from metadata gathered off a journal link.

This script does NOT fetch the web itself (the agent does the fetching, since it
has web tools). The agent passes what it found as a JSON file; this script maps
the publisher to the Quarto extension (see references/publisher-extensions.md)
and writes a well-formed type.yaml.

Usage:
    python add_journal_from_link.py --repo-root . --slug <journal-slug> \
        --meta meta.json [--force]

meta.json shape (agent fills from the link + page):
{
  "journal": "Machine Learning with Applications",
  "publisher": "Elsevier",          # human name; mapping is case-insensitive
  "issn": "2666-8270",
  "url": "https://www.sciencedirect.com/journal/machine-learning-with-applications",
  "cite_style": "",                 # optional; if the guide states one, put it here
  "notes": "APC USD 2460; highlights and graphical abstract encouraged."
}
"""

import argparse
import json
import sys
from pathlib import Path

# publisher (lowercased) -> (extension, quarto_format, default_cite_style, format)
PUBLISHER_MAP = {
    "elsevier": ("quarto-journals/elsevier", "elsevier-pdf", "number", "latex"),
    "ieee": ("quarto-journals/ieee", "ieee-pdf", "number", "latex"),
    "mdpi": ("quarto-journals/mdpi", "mdpi-pdf", "numbername", "latex"),
    "acm": ("quarto-journals/acm", "acm-pdf", "number", "latex"),
    "acs": ("quarto-journals/acs", "acs-pdf", "number", "latex"),
    "plos": ("quarto-journals/plos", "plos-pdf", "number", "latex"),
    "agu": ("quarto-journals/agu", "agu-pdf", "authoryear", "latex"),
    "springer": ("", "pdf", "numbername", "latex"),
    "springer nature": ("", "pdf", "numbername", "latex"),
    "frontiers": ("", "pdf", "authoryear", "latex"),
    "taylor & francis": ("", "pdf", "authoryear", "latex"),
    "taylor and francis": ("", "pdf", "authoryear", "latex"),
    "wiley": ("", "pdf", "authoryear", "latex"),
}

# domain hint -> publisher key (fallback if agent didn't set publisher)
DOMAIN_HINTS = {
    "sciencedirect.com": "elsevier",
    "elsevier.com": "elsevier",
    "ieee.org": "ieee",
    "mdpi.com": "mdpi",
    "acm.org": "acm",
    "acs.org": "acs",
    "plos.org": "plos",
    "springer.com": "springer",
    "springeropen.com": "springer",
    "frontiersin.org": "frontiers",
    "tandfonline.com": "taylor & francis",
    "wiley.com": "wiley",
}


def resolve_publisher(meta: dict) -> str:
    pub = (meta.get("publisher") or "").strip().lower()
    if pub in PUBLISHER_MAP:
        return pub
    # try domain hint from url
    url = (meta.get("url") or "").lower()
    for domain, key in DOMAIN_HINTS.items():
        if domain in url:
            return key
    return pub  # may be "" or unknown -> handled below


def esc(s: str) -> str:
    return (s or "").replace('"', '\\"')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing type.yaml")
    args = ap.parse_args()

    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    repo = Path(args.repo_root)
    jdir = repo / "templates" / "journals" / args.slug
    out = jdir / "type.yaml"

    if out.exists() and not args.force:
        sys.exit(f"EXISTS: {out} already exists. Re-run with --force to update.")

    pub_key = resolve_publisher(meta)
    if pub_key in PUBLISHER_MAP:
        ext, qformat, default_cite, fmt = PUBLISHER_MAP[pub_key]
    else:
        ext, qformat, default_cite, fmt = ("", "pdf", "number", "latex")
        print(f"  WARN: unknown publisher '{meta.get('publisher')}' — "
              "extension left empty, using generic pdf.")

    cite = meta.get("cite_style") or default_cite

    jdir.mkdir(parents=True, exist_ok=True)
    content = f'''journal: "{esc(meta.get("journal", ""))}"
publisher: {pub_key or "unknown"}
format: {fmt}
extension: "{ext}"
quarto_format: {qformat}
cite_style: {cite}
issn: "{esc(meta.get("issn", ""))}"
url: "{esc(meta.get("url", ""))}"
notes: >
  {esc(meta.get("notes", "")) or "TODO"}
'''
    out.write_text(content, encoding="utf-8")
    action = "updated" if args.force else "created"
    print(f"  {action} {out}")
    if not ext:
        print("  NOTE: no official Quarto extension for this publisher — "
              "final PDF needs a manual template / reference-doc.")
    else:
        print(f"  extension: {ext}  (install later with `quarto add {ext}`)")


if __name__ == "__main__":
    main()
