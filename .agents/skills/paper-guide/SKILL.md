---
name: paper-guide
description: >-
  Consult and maintain the local bank of Elsevier journal "Guide for Authors" pages
  stored under templates/journals/<slug>/guide/ — offline, because the publisher's
  site is behind a captcha. Use this whenever a question touches a journal's
  submission rules or editorial policy: abstract/keyword/highlights word or count
  limits, article structure, figure and table specifications, reference style,
  data availability and statements, ethics, authorship, AI-use declarations, review
  model (single/double anonymized), desk-reject gates, submission checklists,
  APC and open access, title pages and author guidelines — and also when the user
  says "the guide says", "according to the journal", "what does <journal> require",
  "check the guidelines for <journal>", hands over a downloaded guide page (HTML,
  Markdown or pasted text) to file into the bank, or asks to add, refresh, update
  or link a guide. Use it even when the user names no journal and just asks "how
  long can the abstract be for this paper": the answer lives in that paper's
  journal's guide, not in memory. Do not answer these questions from memory —
  publisher limits change, and a wrong word count is a desk reject.
---

# Journal guide — the offline bank

Elsevier's Guide-for-Authors pages sit behind a captcha, so the only copy that
will ever exist is the one the user downloads and hands over. This skill is how
those copies get filed into a bank you can consult, and how the bank stays
trustworthy.

**Never answer a journal-rules question from memory.** These are exactly the
numbers that drift — a 250-word abstract that became 200, a highlights count that
went from 3-5 to 3-6 — and a confidently wrong limit is worse than no answer,
because the author will trust it and the desk editor will not.

## The layout

```
templates/journals/
├── _shared/elsevier/                 pages that apply to EVERY journal
│   ├── index.md                        open access, editorial policies, rights…
│   └── open-access.md
└── <journal-slug>/
    ├── type.yaml                      guide: guide/index.md, guide_retrieved: "YYYY-MM-DD"
    └── guide/
        ├── index.md                   the map: one line per section + its link
        ├── SOURCES.md                 url + retrieval date + sha256 of the raw page
        ├── external.md                pages this guide links to but does not contain
        ├── sections/                  01-before-you-begin.md, 02-types-of-paper.md…
        ├── _raw/                      gitignored: the download, as handed over
        └── _work/                     gitignored: a proposal, before it is applied
```

Each section is one page of the guide, verbatim, small enough to read whole.
That is the entire point: answering "how many keywords?" must not cost 2000
lines of context.

## Part 1 — Answering a question (the common case)

Start at `type.yaml` for the journal (`guide:` points at `index.md`). Read
`index.md` — roughly 30 lines, one line per section — and open **only** the
section that owns the question. Do not read the whole `guide/`.

| The question is about | Read |
|---|---|
| what the journal publishes, article types | the About / Types of paper section |
| review model, title page, blind/anonymised review | Peer review + Title page |
| abstract length, keywords, highlights, graphical abstract | Writing / Abstract / Keywords / Highlights |
| figure, table, artwork, dpi, resolution | Artwork / Figures / Tables |
| reference style, in-text citation format | References |
| data availability, repository, data statement | Research data |
| ethics, authorship, competing interests, AI declaration | Ethics / Publishing ethics |
| "am I ready to submit?", submission checklist | Submission checklist |
| open access, APC, licence, funder mandates | `_shared/elsevier/open-access.md` |

Rules:

- **Quote the source, then answer.** Give the file and the line so the user can
  check. `sections/06-writing.md` is worth more than a confident paraphrase.
- **Say which source you used.** A verbatim section of `sections/` is the guide.
  A line in `type.yaml`'s `notes:` is a *curated summary* someone wrote by hand —
  useful, and second-hand. When that is all you have, say so: "the repo records
  200 in `type.yaml` notes, but the guide itself is not in the bank yet."
- **If the answer is not in the bank, say so plainly** and point at `external.md`.
  A `NOT MIRRORED` row means the text is genuinely not here — the URL is where it
  lives. Offer to have the user download it; then do Part 2 for that page.
- **Never silently generalise from another journal.** Elsevier journals share the
  boilerplate, but each guide overrides it: one allows 250 words, the next 200,
  one bans a single-column manuscript. Use `_shared/` only for the pages that
  genuinely are shared; anything journal-specific comes from that journal's guide.
  A sibling journal's limit is a *hint* about Elsevier's ceiling, never an answer.
- **If `guide_retrieved` is old**, say so when you quote it. These pages are
  revised without notice and a two-year-old limit may be a historical one.

### When the journal has no guide yet

Plenty of journals in the catalog have no `guide/` at all. That is opt-in, not an
error. When you find yourself answering from `type.yaml` alone:

1. Answer, clearly labelled as coming from the curated `notes:`.
2. Check whether a *sibling* journal in the catalog has the page mirrored — that
   confirms Elsevier's generic ceiling, which is the useful fallback when the
   journal's own limit is unknown.
3. Offer to file the real guide (Part 2) so the next question is a citation
   rather than an inference.

Do not fill the gap with a remembered number. If neither the guide nor a curated
note states it, the honest answer is "the bank does not record this, and I cannot
reach the page" — followed by the URL, so the user can fetch it.

## Part 2 — Filing a new guide

The user hands over a downloaded page: an `.html`/`.htm` file, a Markdown file,
or text pasted straight into the chat. **Save it first** — pasted text goes to
`guide/_raw/<date>.txt`, an HTML file is copied there too. `SOURCES.md` records
the sha256 of that file, so never skip it: the raw page may be the only copy in
existence, and the provenance is what makes a future re-conversion verifiable.

```bash
# 1. scaffold (once per journal)
python scripts/journal_guide.py scaffold --journal <slug>

# 2. see the structure and decide where to cut
python scripts/journal_guide.py outline --source guide/_raw/<file>

# 3. write the proposal — this does NOT touch guide/
python scripts/journal_guide.py propose --journal <slug> --source guide/_raw/<file>

# 4. READ guide/_work/outline.md and the proposed files. Fix the cut by hand.
#    Then SHOW THE PROPOSAL TO THE USER and get their approval.  <-- not optional
#    They have to see the cut, because the cut is a decision, not a computation.

# 5. publish — refused without --approved
python scripts/journal_guide.py apply --journal <slug> --approved

# 6. provenance
python scripts/journal_guide.py sources --journal <slug> --what guide-for-authors \
    --url "<the page's url>" --retrieved <YYYY-MM-DD> --raw guide/_raw/<file> --set-type-date

# 7. write index.md and external.md by hand, then verify
python scripts/journal_guide.py check --journal <slug>
```

Steps 4 and 7 are yours. The script cannot do them, and that is by design.

### The approval gate is not a formality

`apply` refuses to write anything without `--approved`, and the flag is not yours
to add on your own initiative. It records that the user looked at the cut and
agreed. Adding it unasked writes decisions into the bank that nobody made: which
topics became separate files, which two were merged, whether the page's own index
of contents was dropped as navigation.

Showing the user a proposal and then applying it without waiting is the exact
failure this gate exists to prevent. Present the cut, wait for the answer.

What to show them: `guide/_work/outline.md` is the whole cut in order — file,
heading, line count — plus any decision that is not self-evident from it (a
level you chose because the page's own headings were groupings, navigation you
dropped, a link you had to rewrite). They approve the *shape*, not 58 files.

**Use the default engine.** `convert`/`propose` use the built-in reader, which
keeps the page's `<a id>` attributes. markitdown reads more prettily but drops
those ids and keeps the navigation and cookie banner while reporting nothing
removed — every internal link would then point at an anchor that no longer
exists. Only reach for `--engine markitdown` if the built-in reader mangles a
page, and add the anchors back by hand if you do.

### How to choose the cut (step 4)

`propose` cuts on `##` headings and re-cuts anything over 300 lines on its
sub-headings. It will be wrong sometimes, and these are the judgement calls:

- **Merge** two tiny adjacent sections that nobody would ever look up separately
  ("Short communications" + "Case studies").
- **Split** a large one even when it is under the cap, if it answers two
  unrelated questions ("Ethics" holds authorship, competing interests, AI
  declarations and preprints — four files beat one).
- **Name from the publisher's own heading**, slugified: `Data statement`, not
  `data-03`. The official wording is what someone greps for, and Elsevier's
  headings are the vocabulary the journal itself uses when it rejects a paper.
- **Never rewrite the prose.** Cut, keep, file. If the guide is 2000 lines, the
  answer is more, smaller files — not a shorter guide. A summary is only ever as
  good as the model that wrote it, and these limits are precisely what must not
  drift.

Two things `propose` hands you on purpose:

- **A stripped-element report.** Check it before accepting the cut. If the
  removed list contains something that looks like content rather than chrome,
  the conversion ate it.
- **The page title.** `propose` will not turn the `<h1>` into a one-line file; it
  prints it so you can use it as the guide's title in `index.md`. That is the
  title of the publisher's page, not a section.

Before you `apply`, prove the text survived. Diffing the word set of the source's
content region against the proposed files takes a minute and is the only way to
know you did not quietly drop a paragraph:

```bash
python - <<'PY'
import re, pathlib
html = pathlib.Path("guide/_raw/<file>.html").read_text(encoding="utf-8")
region = re.search(r"<main[^>]*>(.*?)</main>", html, re.S)   # or the body
words = [w for w in re.split(r"\s+", re.sub(r"<[^>]+>", " ", region)) if w.strip()]
bank = "".join(p.read_text(encoding="utf-8")
               for p in pathlib.Path("templates/journals/<slug>/guide/sections").glob("*.md"))
print("missing:", [w for w in words if w not in bank])
PY
```

A short list of missing words is normal (markup words, a split hyphenation). A
missing sentence is not: go back to `_raw/` and fix the cut.

### The three kinds of reference

This is the part that decides whether the bank is usable offline.

1. **Same page** — a link like `#data-statement`. Point it at the file that
   holds that heading: `sections/08-data-statement.md#data-statement`. Each
   section's anchor is carried over automatically from the page's `id`
   attributes, so these links keep working after the cut.
2. **External, not yet downloaded** — leave the absolute URL, and add a row to
   `external.md`: `| <url> | <topic> | \`NOT MIRRORED — download to add\` |`. The
   text is not in the bank and the reader must know that.
3. **External, already in the bank** — point at
   `../../_shared/elsevier/<topic>.md` and mark the row
   `mirrored: <path>`. These pages are identical for every journal, so they live
   once: mirroring a fifth journal's open-access policy would just be a fifth
   copy to keep in sync.

## Part 3 — Promoting an external page

When the user downloads a page that `external.md` lists as `NOT MIRRORED`:

```bash
python scripts/journal_guide.py cites --url "<the url>"     # who links to it, everywhere
```

That list is the work order. Rewrite **every** entry to the local path, update
the row to `mirrored:`, then run `cites` again: **it must print nothing.** That
zero is the proof the promotion is complete. A link missed here survives for
years, pointing at a page that needs a captcha to open — and nobody notices until
a co-author follows the link and gives up.

Do not skip the second `cites`. The first one tells you what to do; the second
one tells you whether you finished.

## Part 4 — Deduplicating identical sections

Elsevier repeats its boilerplate word for word across journals. When two or
more guides hold byte-identical section files, they live once under
`templates/journals/_shared/<publisher>/` and every guide index points at the
single copy. One identical file in one guide is fine; the same bytes in two
guides is already two copies to keep in sync by hand.

```bash
# 1. report — lists every group, nothing moves
python scripts/journal_guide.py dedup --publisher elsevier

# 2. SHOW THE REPORT TO THE USER and get their approval.  <-- not optional
#    Merging N copies into one shared file is a judgement call, same as `apply`.

# 3. promote — refused without --approved
python scripts/journal_guide.py dedup --publisher elsevier --promote --approved

# 4. verify — the report must come back empty, and check must be clean
python scripts/journal_guide.py dedup --publisher elsevier
python scripts/paper_validate.py
```

Rules:

- **Identical means identical.** The comparison strips only the per-download
  provenance comment, trailing whitespace and line endings. A file that differs
  in a single word — usually the journal's name — is a different file and stays
  local. Never "generalise" two near-identical sections into one.
- **Never mix publishers.** Groups are per `_shared/<namespace>/` folder, derived
  from each journal's own `publisher` in `type.yaml`. Elsevier boilerplate is
  not Springer Nature boilerplate.
- **Folder `index.md` files stay local.** They are maps with journal-specific
  numbering, not content. Only the files they list are candidates.
- **The shared copy carries its provenance.** Its header lists every guide it
  came from plus the content hash. A shared file nobody can trace back to its
  downloads is a file nobody can refresh.

## Why the script is only half the work

`journal_guide.py` does what a program can do without judgement: read the page,
drop the navigation and cookie banners, report every element it dropped, cut on
headings, resolve links, check the result. It cannot decide where a section
really ends, whether two headings are the same topic, or whether a link points at
something we should mirror. Those are yours.

That split is deliberate. The failure mode this bank exists to prevent is a
condensed guide that quietly says 250 when the page says 200. A deterministic
cut is auditable; an interpreted one is not. So the script proposes and you
adjudicate — and `check` verifies the result, in CI and before every commit.