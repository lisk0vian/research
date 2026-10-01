# EAAI Guide for Authors — Markdown (condensed)

> Source: Engineering Applications of Artificial Intelligence, ISSN 0952-1976, Elsevier (IFAC journal).
> URL: https://www.sciencedirect.com/journal/engineering-applications-of-artificial-intelligence/publish/guide-for-authors
> Converted: 2026-09-30 from pasted PDF text (22 pp). Full text lives in user message; this file is the operational checklist + reference style for `papers/c20-2026/`.
> Method: `util-office-to-md` (markitdown) equivalent — PDF text already extracted, restructured to Markdown, no tables lost (artwork table kept below).

## 0. Four desk-reject gates (no review if violated)

1. No novel metaphor-based metaheuristics (rarely accepted; if claimed: standard optimization terminology + novel/useful concepts + scientific metaphor motivation + fair SOTA benchmark).
2. Abstract must state AI contribution + engineering application.
3. No undefined acronyms in title/abstract.
4. Single-column format. Max 50 pages, manuscript <100 MB.

## 1. About / article types

- IFAC journal. Novel AI for real-world engineering + validation on public datasets for replicability.
- Types: Original Research, Short Communications (IFAC EAAI Forum), Survey/Tutorials, Case Studies / Software Reviews.
- Software co-submission to Software Impacts encouraged (reviewed, DOI). IFAC conference papers must be substantially extended + cited/discussed.

## 2. Peer review

- Double anonymized, >=2 reviewers, editor decides. One appeal max.
- Submit title page SEPARATE from anonymized manuscript.
- Title page: title, authors (order = system), affiliations (lower-case superscript letter + full postal + country), corresponding author (email published), present/permanent address (arabic numeral footnote), acknowledgements (only here), competing interests (if no separate file), corresponding full address+email.
- Anonymized manuscript: body + references + tables, no names/affiliations/acknowledgements (also in supplements).

## 3. Ethics

- Elsevier Publishing Ethics. Submission declaration: not published before (preprint/abstract/thesis/lecture/registered report ok), not under consideration elsewhere, all authors + authorities approve, no duplicate publication; screening tools may check.
- Authorship: substantial contribution to (1) conception/design or data acquisition/analysis, (2) drafting/critical revision, (3) final approval; accountable for all aspects. Single corresponding author (affiliation determines publishing-agreement eligibility). No post-acceptance authorship changes; pre-acceptance only via Authorship Change Request form + all-author written consent; review may pause.
- Competing interests: declarations tool always; `.doc/.docx` upload, no signatures. Funding: disclose role in design/collection/analysis/writing/decision; format `Funding: This work was supported by ... [grant ...]` or `This research did not receive any specific grant ...`.
- Generative AI: may support, never substitute human judgment, human oversight required; authors accountable (verify sources — AI refs can be fabricated; edit for original contribution; image accuracy/attribution; transparency; data privacy/IP). Never list AI as author. Declare at end before references: section `Declaration of generative AI and AI-assisted technologies in the manuscript preparation process` with tool + reason + reviewed/edited + responsibility. Grammar/spelling checkers and accessibility assistive tech exempt.
- Preprints: allowed, not prior publication; free SSRN posting after desk review (preprint DOI, link to version of record); needs all-author approval.
- Inclusive language, SAGER sex/gender guidance, image-manipulation ban (no enhance/obscure/move/remove; brightness/contrast only if no info loss; gamma disclosed; no AI-created primary-data images), jurisdictional neutrality (maps: bounding box only + "map lines delineate study areas..."; affiliations verifiable).

## 4. Writing / formatting

- Editable sources only (`.doc/.docx`, `.tex`); PDF not acceptable. Word single-column (LaTeX may be double). No strikethrough/underline. Spell/grammar check. LaTeX template encouraged.
- Abstract: <=250 words, purpose + procedures + main findings (stats if applicable) + conclusions + novelty; stand-alone; avoid refs (if essential: author+year full); define non-standard abbreviations at first mention.
- Keywords: 1-6, English, avoid "and"/"of" phrases, abbreviations only if established.
- Highlights (encouraged, separate file with "highlights" in name): 3-5 bullets, each <=85 chars incl. spaces.
- Graphical abstract (encouraged, separate file TIFF/EPS/PDF/Office): 531x1328 px (h x w) readable at 5x13 cm; GenAI must follow GenAI Policies.
- Units: SI + equivalents; up to 6 Inspec codes. Math: editable text, inline simple `X/Y` with solidus, italics variables, `exp`, display numbered consecutively.
- Tables: editable text, near text or end, cite all, numbered consecutively, captions + notes below body, no vertical rules/shading, sparing/non-duplicative.
- Figures: separate files `Figure_1...`; cite all, numbered in order; text graphics may embed (LaTeX ok); captions = brief title (not on figure) + description, minimal text, explain symbols. Formats:

| Image type | Recommended | Requirements |
|---|---|---|
| Vector drawings | EPS, PDF | Embed font / text as graphics |
| Photographs | TIFF, JPG, PNG | >=300 dpi (single col >=1063 px; full page >=2244 px) |
| Bitmapped line drawings | TIFF, JPG, PNG | >=1000 dpi (single col >=3543 px; full page >=7480 px) |
| Charts / large shaded tables | XLS, XLSX | Clearly readable |
| Annotated images | PPT, PPTX | Legible annotations; embedded >=300 dpi |

Do not submit: low-res, unreadable small text, combined multi-images (except before/during/after comparisons). Color online if usable; accessible palettes. GenAI: ok for flowcharts/schematics and data-derived plots via reproducible methods; forbidden for primary observed data; disclose per-caption + general statement.
- Supplementary: cite all, submit with manuscript (add/replace only at revision), caption each, appears as-is. Video: note placement in text, related filename, recommended format, <=150 MB/file <=1 GB total, stills + descriptive text for accessibility.
- Research data (Option C, required): deposit in repository + cite/link in article, or explain why not. Data statement required at submission (appears on ScienceDirect). Linking: dataset link at submission, repository banner, or `Database: 12345` identifiers in text. Co-submission to Data in Brief / MethodsX encouraged (mandatory templates, auto-forward, APC after acceptance).

## 5. Article structure

Numbered `1, 1.1, 1.1.1`; cross-ref by number; headings separate line; abstract not numbered. Introduction (objectives, adequate background, no detailed review/results). Methods (reproducible; summarize+cite published; quote with marks; describe mods). Results (clear/concise/reproducible). Discussion (significance, no repeat, avoid extensive lit). Conclusion (stand-alone or subsection). CRediT required (Conceptualization, Data curation, Formal analysis, Funding acquisition, Investigation, Methodology, Project administration, Resources, Software, Supervision, Validation, Visualization, Writing - original draft, Writing - review and editing). Appendices `A, B` with `Eq. (A.1)`, `Table A.1`, `Fig. A.1`.

## 6. References (authoryear, alphabetical then chronological)

- Every in-text citation in list and vice versa; abstract refs full; correct/complete; real sources only; DOIs where available; avoid unpublished/personal comms (if used: replace date with phrase); `in press` = accepted.
- At submission any consistent style ok if complete (authors, journal/book/chapter/article titles, year, volume, article no./pagination). Journal style applied at proof.
- In-text: single `Allan, 2020a, 2020b`; two `Allan and Jones, 2019`; 3+ `Kramer et al., 2023`; direct or parenthetical; groups alphabetical then chronological or vice versa. List alphabetical then chronological; same author+year `a,b,c`. Journal names LTWA abbreviated.
- Examples (from guide):
  - Journal: `Van der Geer, J., Handgraaf, T., Lupton, R.A., 2020. The art of writing a scientific article. J. Sci. Commun. 163, 51–59. https://doi.org/10.1016/j.sc.2020.00372.`
  - Journal e00205: `Van der Geer, J., Handgraaf, T., Lupton, R.A., 2022. ... Heliyon. 19, e00205. https://doi.org/10.1016/j.heliyon.2022.e00205.`
  - Book: `Strunk Jr., W., White, E.B., 2000. The Elements of Style, fourth ed. Longman, New York.`
  - Chapter: `Mettam, G.R., Adams, L.B., 2023. How to prepare ..., in: Jones, B.S., Smith, R.Z. (Eds.), Introduction to the Electronic Age. E-Publishing Inc., New York, pp. 281–304.`
  - Website: `Cancer Research UK, 2023. Cancer statistics reports for the UK. http://... (accessed 13 March 2023).`
  - Dataset: `[dataset] Oguro, M., Imahiro, S., Saito, S., Nakashizuka, T., 2015. Mortality data ... [dataset]. Mendeley Data, v1. https://doi.org/10.17632/xwj98nb39r.1.` (add `[dataset]` before ref; not published).
  - Software: `Coon, E., ... & Molins, S., 2020. Advanced Terrestrial Simulator (ATS) v0.88 (Version 0.88) [software]. Zenodo. https://doi.org/10.5281/zenodo.3727209.` Include creator, title, venue (archive with PID), date, identifier (DOI preferred), version, type if needed; cite paper + software separately.
- Web refs: full URL + accessed date minimum. Data refs: author, title, repository, version, year, PID. Software: FORCE11 essentials. Preprints: mark `preprint`/server + DOI; prefer formal version if available. CSL/Mendeley template + remove field codes.

## 7. Submission checklist

Corresponding author + contacts current; all files (artwork/video/supplements, tables, footnotes, captions); spell/grammar; refs bidirectional; copyright permissions; APC understood; 4 gates pass. System builds single review PDF; editable sources required for typesetting. After decision: Transfer Service opt-in, publishing agreement, OA license choice, permissions form, pre-proof (DOI, citable, unedited disclaimer), 2-day proof corrections, Share Link 50 days, responsible sharing. Language: American or British (not mixed).
