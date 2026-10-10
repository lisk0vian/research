---
name: paper-cover-letter
description: >
  Write or revise the cover letter that accompanies a paper's journal
  submission, following Elsevier's "What to include in a cover letter"
  tutorial: short and focused, aim and key findings, novelty and impact, fit
  with the journal's aims and scope, originality and conflicts of interest,
  and none of what belongs in the submission system (funding, author
  declarations, suggested or opposed reviewers). Use whenever the user asks
  for a cover letter, carta de presentación, letter to the editor for a new
  submission, or is preparing the files to submit a paper (title page,
  anonymized manuscript, cover letter), even if they only say "prepare the
  submission". Scaffolds papers/<slug>/paper/cover-letter.qmd with
  `scripts/paper_cover_letter.py --init`, writes the paragraphs from the
  manuscript, lints them with `--check` and renders them with
  `scripts/paper_build.py`. Not for responses to reviewers (that is a
  revision letter, under reviews/round-N/).
---

# paper-cover-letter

A cover letter is the editor's first contact with the paper. Its job is to
show, in under a page, that the work is authentic research and why it belongs
in *this* journal, much like a cover letter for a job. Editors read hundreds,
so a short, specific letter that states the problem, the finding and the fit
does more than a long one. Everything here serves that goal.

The letter is a source like `main.qmd`: `paper/cover-letter.qmd`, rendered by
`paper_build.py` into `build/<slug>-cover-letter.docx/.pdf`. It is never
anonymized (only the editor reads it), and it is written in English.

## 1. Read before writing

- `papers/<slug>/paper/main.qmd`: title, abstract, the contributions paragraph
  of the introduction, the main results, limitations and conclusions. The
  letter only restates what the manuscript already says.
- `papers/<slug>/manifest.yaml` and `authors/<id>.yaml`: the corresponding
  author signs the letter.
- `templates/journals/<journal>/type.yaml`: journal, publisher, and the Guide
  for Authors notes and `url`. **Check whether the guide says what the cover
  letter must contain.** If it does, that list overrides the default
  structure below (some journals ask for suggested reviewers, a statement on
  related submissions or a highlights summary in the letter). If the guide is
  not in the repo and the site blocks automated access (captcha), ask the user
  to save the page as HTML, as with `paper-journal`.
- The journal's aims and scope (Guide for Authors or the journal home page):
  the fit paragraph should echo its own words.

## 2. Ask only what metadata cannot answer

Keep it to one short round of questions:

1. Editor's name, if known. Look it up on the journal's editorial board page
   when you can reach it; never guess a name. Unknown -> "Dear Editor".
2. Was the paper invited, or is it for a special issue or article collection?
   (If so the letter says it in the first paragraph.)
3. Previous or concurrent submissions of this work, preprints (SSRN, arXiv),
   or a closely related paper by the same authors the editor should know about.
4. Do the authors confirm no conflicts of interest? If there is one, the
   standard sentence changes and the user must word it.
5. Any special consideration for the editor (sensitive data, embargo, a
   transferred manuscript), and the signer's position or title.

## 3. Scaffold

```bash
python scripts/paper_cover_letter.py --slug <slug> --init [--editor "Dr. Jane Doe"] [--date "October 12, 2026"]
```

It fills everything that comes from metadata (sender, affiliation, editor,
journal, publisher, date, quoted title, signature with e-mail) and leaves
`[WRITE: ...]` slots for the paragraphs. Use `--force` to rebuild an existing
letter, after showing the user what will be replaced.

## 4. Write the paragraphs

The structure is the tutorial's template; read
`references/elsevier-cover-letter.md` for its exact wording and the optional
items.

1. **Submission** (scaffolded): an original research paper, its exact title,
   the journal. Mention an invitation or special issue here.
2. **Problem, method, finding, significance**: "This paper addresses the
   problem of ... Studies have shown that ... However, it remains unclear
   whether ... Using ..., we show that ... Our findings are significant
   because ...". Two or three key numbers at most, copied verbatim from
   `main.qmd` (the checker rejects any number it cannot find there). Name the
   novelty plainly: what the paper does that previous work did not.
3. **Fit and relevance**: how the study's focus matches the journal's aims and
   scope, and why its readers will care (contribution or practical
   implications).
4. **Optional, only when it applies** (the tutorial's list for journals whose
   guide is silent): special considerations, a brief note on how the data were
   collected, previous or concurrent submissions, supporting information such
   as open data or confirmatory evidence. One or two sentences each; skip the
   paragraph entirely when none applies.
5. **Originality and conflicts of interest** (scaffolded).

Tone: sober and matched to the manuscript. Claim nothing the paper does not
show, keep the limitations' scope (a proxy is a proxy, an association is not
a cause), and avoid superlatives a reviewer could refute. Aim for 300-400
words in the letter body; the checker warns above 450.

## 5. What stays out, and why

The tutorial is explicit: the letter does not carry **funding**, **author
declarations** (CRediT, data availability, generative-AI use, ethics) or
**suggested or opposed reviewers**, unless the journal requests them. Those
have their own fields in Editorial Manager, and repeating them in the letter
only makes it longer and risks contradicting the forms. When the Guide for
Authors does ask for one, keep it and pass `--allow funding|declarations|reviewers`
to the checker.

## 6. Check, render, review

```bash
python scripts/paper_cover_letter.py --slug <slug> --check
python scripts/paper_build.py --slug <slug> --format all
```

Fix every `[FAIL]` (unfilled slot, title not quoted exactly, journal not
named, excluded content, a number missing from `main.qmd`) and judge each
`[warn]`. Then open `build/<slug>-cover-letter.pdf` and confirm it fits on
one page. Before reporting, reread the letter against the manuscript once:
it must represent the study accurately. Tell the user which answers from
step 2 you assumed, so they can confirm them before submitting.

## What this skill does NOT do

- Title page or anonymized manuscript: `paper-build` with
  `journal.formatting: doubleblind` produces both.
- Response to reviewers during a revision (`reviews/round-N/`).
- Upload anything to Editorial Manager.
