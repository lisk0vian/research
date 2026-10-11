# External references — engineering-applications-of-artificial-intelligence

Pages this guide links to that are **not** part of it. A row marked
`NOT MIRRORED` means the text is not in the bank and the URL is where to get it.

Most are Elsevier-wide policies: the same page appears in every journal's guide,
so a mirrored one belongs in `_shared/elsevier/` and every journal points at
that single copy. The last table holds the ones specific to this journal, an
IFAC title.

To promote a row: download the page, hand it over as a file (or paste the text),
file it into `_shared/elsevier/<topic>.md`, then

```
python scripts/journal_guide.py cites --url "<the url>"    # every file that links here
```

rewrite each one to the local path, mark the row `mirrored:`, and run `cites`
again — it must print nothing. That zero is the proof nothing was left behind.

## Elsevier-wide

| url | topic | state |
|---|---|---|
| https://www.elsevier.com/about/policies-and-standards/publishing-ethics | publishing-ethics-policy | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/reviewer/what-is-peer-review | what-is-peer-review | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/editorial-decision-appeals-policy | editorial-decision-appeals-policy | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/science/journal/09521976/publish/open-access-options | open-access-options | `NOT MIRRORED — download to add` |
| https://www.journals.elsevier.com/software-impacts | software-impacts | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/journal/software-impacts/publish/guide-for-authors | software-impacts-guide | `NOT MIRRORED — download to add` |
| https://legacyfileshare.elsevier.com/gfa/authorship-change-request-form.pdf | authorship-change-request-form | `NOT MIRRORED — download to add` |
| https://declarations.elsevier.com/ | declarations-tool | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals | generative-ai-policies-for-journals | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies/sharing | article-sharing-policy | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/open-science | open-science | `NOT MIRRORED — download to add` |
| https://www.ssrn.com/ | ssrn | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/article-withdrawal | article-correction-retraction-removal | `NOT MIRRORED — download to add` |
| https://doi.org/10.1186/s41073-016-0007-6 | sager-guidelines | `NOT MIRRORED — download to add` |
| https://ease.org.uk/wp-content/uploads/2023/01/EASE-SAGER-Checklist-2022.pdf | sager-checklist | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/latex | elsevier-latex | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/tools-and-resources/highlights | article-highlights | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/authors/journal-authors/graphical-abstract | graphical-abstract-guidelines | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions | artwork-and-media-instructions | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-faq | artwork-faq | `NOT MIRRORED — download to add` |
| https://www.w3.org/WAI/perspective-videos/contrast/ | colour-contrast-accessibility | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/policies-and-guidelines/artwork-and-media-instructions/media-specifications | media-specifications | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/policies-and-guidelines/artwork-and-media-instructions/media-overview | media-overview | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/research-data | research-data-policy | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/tools-and-resources/research-data/data-statement | data-statement-guidance | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/tools-and-resources/research-data/data-base-linking | data-base-linking | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/journal/data-in-brief | data-in-brief | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/journal/methodsx | methodsx | `NOT MIRRORED — download to add` |
| https://credit.niso.org/ | credit-taxonomy | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/policies-and-guidelines/credit-author-statement | credit-author-statement | `NOT MIRRORED — download to add` |
| https://citationstyles.org/ | citation-style-language | `NOT MIRRORED — download to add` |
| https://www.mendeley.com/reference-management/reference-manager/ | mendeley-reference-manager | `NOT MIRRORED — download to add` |
| https://submit.elsevier.com/EAAI | eaai-submission-system | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper/submit-and-revise/article-transfer-service | article-transfer-service | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies/copyright | copyright-policies | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/open-access-licenses | open-access-licenses | `NOT MIRRORED — download to add` |
| https://www.elsevier.support/publishing/news/journal-author-guide-to-alt-text-for-images | alt-text-guide | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/accessibility | accessibility | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper/sharing-and-promoting-your-article | sharing-and-promoting-your-article | `NOT MIRRORED — download to add` |
| https://webshop.elsevier.com/language-editing-services/language-editing | language-editing-services | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper | step-by-step-guide-to-publishing | `NOT MIRRORED — download to add` |
| https://service.elsevier.com/app/home/supporthub/publishing | elsevier-support-centre | `NOT MIRRORED — download to add` |

## Specific to this journal (IFAC)

| url | topic | state |
|---|---|---|
| https://www.ifac-control.org/ | ifac-home | `NOT MIRRORED — download to add` |
| https://www.theiet.org/publishing/inspec/inspec-content-coverage/inspec-classification/ | inspec-classification | `NOT MIRRORED — download to add` |
| https://portal.issn.org/ltwa | ltwa-abbreviations | `NOT MIRRORED — download to add` |

## Not listed above

The guide also links to per-question support pages (`service.elsevier.com/app/answers/detail/a_id/...`),
the PID registries (handle.net, scicrunch, ASCL, swMath, Software Heritage, ARK),
file downloads (`legacyfileshare.elsevier.com`, `assets.ctfassets.net`) and the
Data in Brief / MethodsX templates. They were left as absolute URLs in the
sections rather than queued here: none states a rule the guide does not already
state.

## Two defects in this page, kept verbatim in the notes

- The page links to `https://www-staging.elsevier.com/about/policies-and-standards/article-withdrawal`
  — Elsevier's **staging** server. It was rewritten to the production URL
  (`www.elsevier.com/...`), the row at the top of the Elsevier-wide table. This is
  the only edit made to the guide's text; the same defect is in the Machine
  Learning with Applications guide.
- The page repeats four `id` attributes (`about-the-journal`,
  `writing-and-formatting-research-data`, `writing-and-formatting-article-structure`,
  `submitting-your-manuscript`). The bank keeps the first occurrence; the second
  is dropped so no two sections answer to the same link.