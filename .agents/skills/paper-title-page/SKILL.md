---
name: paper-title-page
description: >
  Prepare the separate title page (hoja de título) that an anonymized
  submission needs, with verified, never invented, data: exact author names
  and order, affiliations with lower-case superscript letters and full postal
  address with country, the corresponding author with e-mail, and the
  statements Elsevier moves out of the anonymized manuscript (funding,
  declaration of competing interest, acknowledgements). Use whenever the user
  mentions a title page, hoja de título, double-anonymized or double-blind
  review, an anonymized or blinded manuscript, author details for the
  submission system, or is preparing the files to submit a paper, even if
  they only say "prepare the submission". Sets journal.formatting, fills
  main.qmd's author/affiliations/title-page blocks from authors/<id>.yaml and
  checked sources, verifies them with `scripts/paper_title_page.py` and
  renders build/<slug>-title-page.docx/.pdf with `scripts/paper_build.py`.
---

# paper-title-page

Under double-anonymized review the reviewers must not learn who wrote the
paper, while the editor must. Elsevier solves this with **two separate
files**: a title page that "will remain separate from the manuscript
throughout the peer review process and will not be sent to the reviewers",
and an anonymized manuscript. Everything that identifies the authors goes on
the first and nowhere in the second. `references/elsevier-double-anonymized.md`
has the official wording and sources.

A title page is short, but every line on it is a fact the journal will
publish or use to contact the authors, and the names must match the
submission system exactly. So the whole point of this skill is that each value
is copied from a record or a source someone can check, never reconstructed
from memory. A wrong postal code or a guessed e-mail is worse than a visible
gap, because nobody notices it until it is in print.

## How it is built

There is no separate title-page source to keep in sync. `paper_build.py`
writes `build/<slug>-title-page.docx/.pdf` from `main.qmd`'s own front matter
whenever `journal.formatting` ends in `blind`, and in the same build the CAS
template hides the authors in the PDF and the Word manuscript. Your job is to
make that front matter true and complete:

```yaml
journal:
  formatting: doubleblind          # anonymized manuscript + separate title page
author:                            # manifest order; values from authors/<id>.yaml
  - name: Full Name                # exactly as in the submission system
    email: name@institution.edu
    orcid: "0000-0000-0000-0000"
    affiliation: [{ref: aff-1}]
    cas:
      cormark: 1                   # the one corresponding author
affiliations:
  - id: aff-1                      # printed as superscript "a", "b", ... in order
    name: Institution (ACRONYM)
    address: Street and number, district
    postal-code: "00000"
    city: City
    country: Country
title-page:                        # what the anonymized manuscript must not carry
  acknowledgements: "..."          # omit the key when there are none
  funding: "This work was supported by ..."   # or the no-specific-grant sentence
  competing-interests: "The authors declare ..."
```

An author's `phone:` is printed next to the e-mail when present; add it only
if the user gives it or the journal asks for it.

## Workflow

1. **Read the records.** `manifest.yaml` (author ids, order, role),
   `authors/<id>.yaml` (name, e-mail, ORCID, affiliation), the current
   `main.qmd` front matter, and the journal's `type.yaml` notes (some journals
   want more on the title page, such as phone or present addresses).
2. **Confirm the review mode.** If the user or the journal asks for an
   anonymized manuscript, set `journal.formatting: doubleblind`. A
   single-anonymized journal without that request keeps the authors in the
   manuscript and needs no separate title page; say so instead of making one.
3. **Fill the front matter from the records,** never from memory:
   - names, e-mails and ORCIDs exactly as in `authors/<id>.yaml`, in manifest
     order; if a record looks wrong (two e-mails disagree, a typo), ask the
     user and fix the record, not just the paper;
   - the corresponding author is the manifest's `role: corresponding`;
   - the postal address comes from the institution's official site or from
     the user. Cite where it came from in a YAML comment. When you cannot
     verify it (site unreachable, several campuses, conflicting sources),
     write your best candidate with a `# TODO: verify ...` comment and tell
     the user: the checker fails on it, which is the intent;
   - funding: use `manifest.yaml`'s `funding`, in the journal's phrasing
     ("This work was supported by ..."); if the paper had no specific funding,
     the standard sentence is "This research did not receive any specific
     grant from funding agencies in the public, commercial, or not-for-profit
     sectors.";
   - competing interests: Elsevier's standard sentence is "The authors declare
     that they have no known competing financial interests or personal
     relationships that could have appeared to influence the work reported in
     this paper." Use it only after the user confirms there is nothing to
     declare; otherwise ask them for the wording;
   - acknowledgements: only what the user provides.
4. **Check:**

   ```bash
   python scripts/paper_title_page.py --slug <slug>
   ```

   It fails on a mismatch with `authors/`, a wrong or missing corresponding
   author, an incomplete address, a missing declaration, any TODO left on the
   author, affiliations or title-page blocks, and identifying data (names,
   e-mails, ORCIDs, institution name or acronym, street) found in the
   manuscript body or in the built anonymized docx. A leak in the body is
   usually an acknowledgement, a funding sentence or "our previous work":
   move it to `title-page:` or rewrite self-citations in the third person.
5. **Build and look:**

   ```bash
   python scripts/paper_build.py --slug <slug> --format all
   python scripts/paper_title_page.py --slug <slug>
   ```

   Re-run the check after the build so it also inspects the built docx, then
   open `build/<slug>-title-page.pdf` and the first page of `build/<slug>.pdf`
   (no names under the title). Report what you verified, what is still a
   TODO and who must confirm it.

## What this skill does NOT do

- The cover letter (`paper-cover-letter`); it is not anonymized either.
- Look inside figures: check by eye that no figure shows a logo or an
  institution name, since the guidelines require that too.
- Upload anything. In Editorial Manager the title page goes in its own
  "Title Page" item, separate from the manuscript.
