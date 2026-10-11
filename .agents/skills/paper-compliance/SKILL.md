---
name: paper-compliance
description: >-
  Check a paper's manuscript against its journal's Guide for Authors and report
  desk-reject risks with fix recommendations. Use whenever the user asks to
  validate a paper, check compliance, verify submission requirements, or says
  "does my paper meet the journal", "is the manuscript ready to submit",
  "check the abstract/keywords/highlights limits", "desk-reject check",
  "pre-submission check", "what must I change before submitting", or names a
  papers/<slug>/ manuscript together with journal rules. Reads only the guide
  sections each check needs — never the whole guide — and reports in chat by
  default.
---

# paper-compliance

Compare `papers/<slug>/paper/main.qmd` against the journal's banked Guide for
Authors and report what would get the manuscript sent back. The report goes to
**chat only** — no files are written. Fixes to `main.qmd` happen only when the
user explicitly asks for them, and only the mechanical ones.

The failure this skill exists to prevent is a confident paraphrase of a limit
the guide states differently. Quote the guide file and line for every verdict;
never answer a limits question from memory.

## Step 0 — Resolve the paper and its journal

1. Read `papers/<slug>/manifest.yaml` — `journal:` names the journal slug.
2. Read `templates/journals/<journal-slug>/type.yaml` — note `guide:`,
   `guide_retrieved:`, and `notes:` (second-hand summary, not the guide).
3. Read the guide map: `templates/journals/<journal-slug>/guide/index.md`
   (roughly 30–100 lines, one line per section). This map — not a full
   directory listing — tells you which section owns each check.

If the journal declares no `guide:`, that is opt-in, not an error: answer from
`type.yaml` notes labelled as second-hand, mark every such verdict `WARN`,
and offer to file the real guide with `paper-guide`. Never silently
generalise from a sibling journal's guide; a sibling limit is a hint about
the publisher's ceiling, never a verdict.

## Step 1 — Extract the manuscript features (measure, do not eyeball)

Read `papers/<slug>/paper/main.qmd` once: front-matter first, then the body
structure (headings, tables, figures, statements — not the full prose).

Compute the countable limits with code. Word and character counts are
deterministic; eyeballing them is how a 257-word abstract ships as "about
250":

```bash
python3 -c "
import re, pathlib
try:
    import yaml
    have_yaml = True
except ImportError:
    have_yaml = False
t = pathlib.Path('papers/<slug>/paper/main.qmd').read_text(encoding='utf-8')
fm = re.match(r'^---\s*\n(.*?)\n---\s*', t, re.S).group(1)
abs_m = re.search(r'^abstract:\s*\|?\s*\n((?:[ ] .*\n?)+)', fm, re.M)
abs_text = re.sub(r'^  ', '', abs_m.group(1), flags=re.M) if abs_m else ''
print('abstract_words:', len(abs_text.split()))
if have_yaml:
    d = yaml.safe_load(fm)
    hl = d.get('highlights', None)
    if hl is None and isinstance(d.get('journal'), dict):
        hl = d['journal'].get('highlights', [])
    print('keywords:', len(d.get('keywords', []) or []))
    for i, h in enumerate(hl or [], 1):
        print(f'highlight_{i}_chars:', len(h))
else:
    print('PyYAML missing: count keywords/highlights by hand from the front-matter')
"
```

Record: title, abstract text, keywords list, highlights list (top-level
`highlights:` **or** `journal.highlights:` — this repo keeps them under
`journal:` so the CAS docx filter can build the Word front matter), author /
affiliation / corresponding blocks, title-page statements (funding,
competing interests), section headings and numbering, appendix labels,
figure/table captions and file references, data/AI/ethics statements and
where they sit relative to the references.

## Step 2 — Read only the sections each check needs

Open **only** the section that owns each check, following the guide's own
`index.md`. A typical full pass needs 6–8 sections, never the whole bank.
The map below is the Elsevier default — always prefer the journal's actual
index headings when they differ (Springer journals do):

| Check | Guide section |
|---|---|
| Abstract limit, stand-alone, references, abbreviations | Abstract |
| Keyword count and form | Keywords |
| Highlight count (3–5) and 85-char limit | Highlights |
| Graphical abstract required vs encouraged, size | Graphical abstract |
| Numbered sections, appendices, CRediT, acknowledgements, footnotes | Article structure |
| Reference style, in-text citation form | References (+ `article-structure` notes) |
| Resolution, naming, color, captions | Figures/artwork, Formats, Captions |
| Tables editable, notes below body, no vertical rules | Tables |
| Funding, competing interests, AI declaration placement, ethics | Funding sources, Declaration of competing interests, Declaration of generative AI use, Ethics in publishing |
| Data statement wording, linking, repository | Data statement, Research data, Data linking |
| Submission readiness, title page, corresponding author | Submission checklist, Title page, Corresponding author |

Rules for reading:

- Quote the source, then judge: `guide` file + line for the rule,
  `paper/main.qmd` line for the manuscript fact.
- If a rule lives in `external.md` as `NOT MIRRORED`, the text is genuinely
  not in the bank — mark the check `NOT CHECKED`, give the URL, and offer
  to file it via `paper-guide`. Do not invent the rule.
- If `guide_retrieved` is old, say so when you quote it. Publisher pages
  change without notice and a two-year-old limit may be historical.
- Never edit anything under `templates/journals/` — the guide is verbatim
  and audited. `main.qmd` is the only manuscript source (per `AGENTS.md`).

## Step 3 — Report in chat (no files)

Use this exact shape so the report scans the same way every time:

```markdown
## Compliance — papers/<slug>/ vs <Journal> (guide <YYYY-MM-DD>)

**X pass, Y fail, Z warn, W not checked.** <One sentence: submittable, or
the N things that would send it back.>

| # | Check | Verdict | Guide rule | Manuscript fact | Fix |
|---|---|---|---|---|---|
| 1 | Abstract ≤ 250 words | FAIL | `abstract.md:5` — max 250 | `main.qmd:60` — 268 words | Trim 18 words; candidate cuts: … |
| 2 | Keywords 1–7 | PASS | `keywords.md:5` — 1 to 7 | `main.qmd:61-66` — 5 | — |

### Recommended changes (desk-reject risk first)
1. … (each with the exact lines to touch in `main.qmd`)
2. …

### Not checked
- … (rule not in the bank + URL from `external.md`, or no guide yet)
```

Verdict meanings:

- **PASS** — manuscript fact satisfies the quoted rule.
- **FAIL** — quoted rule is violated; a fix is required before submission.
- **WARN** — rule is second-hand (`type.yaml` notes), the guide is stale,
  or the check needed judgement (e.g. "stand-alone abstract", undefined
  abbreviation). Say which.
- **NOT CHECKED** — the rule is not in the bank. Never upgrade this to a
  pass on the basis of another journal.

Order the recommendations by desk-reject risk: counts and required
statements first (abstract, keywords, highlights, funding, competing
interests, AI declaration, data statement), structure and artwork second,
style polish last.

## Step 4 — Fixes (only on explicit request)

Report-only is the default. When the user asks for fixes after seeing the
report:

- Edit **only** `papers/<slug>/paper/main.qmd`. Never a build artefact,
  never the guide, never `experiments/`.
- Apply mechanical fixes directly: missing front-matter keys, keyword
  count, highlight count, statement placement (e.g. AI declaration before
  references), caption/attribute scaffolding.
- Propose — do not silently apply — any fix that rewrites prose: trimming
  an abstract to the word limit, rewording a highlight to fit 85
  characters, writing the funding/competing-interests/data sentences. Show
  the replacement text and wait for approval.
- After fixing, re-run the counts from Step 1 and confirm the verdict
  flipped. Say which checks remain open.

## What this skill does NOT do

- It does not replace peer review or a `/review` panel — this is an
  editorial-options check, not a scientific one.
- It does not build (`paper-build`), audit data or code, or verify that
  numbers trace to `outputs/` — that is the review panel's job.
- It does not maintain the bank — adding, refreshing, or promoting guide
  pages is `paper-guide`.
- It does not check repository structure — that is `paper-validate`.
