# External references — applied-geography

Pages this guide links to that are **not** part of it. A row marked
`NOT MIRRORED` means the text is not in the bank and the URL is where to get it.

Most are Elsevier-wide policies: the same page appears in every journal's guide,
so a mirrored one belongs in `_shared/elsevier/` and every journal points at
that single copy.

To promote a row: download the page, hand it over as a file (or paste the text),
file it into `_shared/elsevier/<topic>.md`, then

```
python scripts/journal_guide.py cites --url "<the url>"    # every file that links here
```

rewrite each one to the local path, mark the row `mirrored:`, and run `cites`
again — it must print nothing. That zero is the proof nothing was left behind.

| url | topic | state |
|---|---|---|
| https://www.elsevier.com/reviewer/what-is-peer-review | peer review (first cited in `05-peer-review.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/publishing-ethics#2-duties-of-editors | editor duties (first cited in `05-peer-review.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/editorial-decision-appeals-policy | Appeal Policy (first cited in `05-peer-review.md`) | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/science/journal/01436228/publish/open-access-options | open access information page (first cited in `07-open-access.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/publishing-ethics#4-duties-of-authors | publishing ethics policies (first cited in `08-publishing-ethics.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies/publishing-ethics#Authors | multiple, redundant, or concurrent publication (first cited in `09-submission-declaration.md`) | `NOT MIRRORED — download to add` |
| https://legacyfileshare.elsevier.com/gfa/authorship-change-request-form.pdf | Authorship Change Request form (first cited in `13-changes-to-authorship.md`) | `NOT MIRRORED — download to add` |
| https://declarations.elsevier.com/ | declarations tool (first cited in `14-declaration-of-competing-interests.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals | GenAI policies for journals (first cited in `16-declaration-of-generative-ai-use.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies/sharing | article sharing policy (first cited in `17-preprints.md`) | `NOT MIRRORED — download to add` |
| https://researchintegrityjournal.biomedcentral.com/articles/10.1186/s41073-016-0007-6/tables/1 | Sex and Gender Equity in Research (SAGER) guidelines (first cited in `19-reporting-sex-and-gender-based-analyses.md`) | `NOT MIRRORED — download to add` |
| https://ease.org.uk/wp-content/uploads/2023/01/EASE-SAGER-Checklist-2022.pdf | SAGER checklist (first cited in `19-reporting-sex-and-gender-based-analyses.md`) | `NOT MIRRORED — download to add` |
| https://doi.org/10.1186/s41073-016-0007-6 | use of the SAGER guidelines (first cited in `19-reporting-sex-and-gender-based-analyses.md`) | `NOT MIRRORED — download to add` |
| https://www-staging.elsevier.com/about/policies-and-standards/article-withdrawal#0-policy-overview | Article Correction, Retraction and Removal Policy (first cited in `23-withdrawal-correction-or-retraction.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/reviewer/what-is-peer-review#2--types-of-peer-review | peer review (first cited in `27-double-anonymized-peer-review.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/tools-and-resources/highlights | article highlights (first cited in `30-highlights.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/authors/journal-authors/graphical-abstract | graphical abstract guidelines (first cited in `31-graphical-abstract.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions | artwork and media instructions (first cited in `34-figures-images-and-other-artwork.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-faq | adding captions to your submission (first cited in `35-captions.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/policies-and-guidelines/artwork-and-media-instructions/media-specifications | recommended file formats (first cited in `40-video.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/policies-and-guidelines/artwork-and-media-instructions/media-overview | submitting video content to be included in the body of an article (first cited in `40-video.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/research-data | research data policy (first cited in `41-research-data.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/tools-and-resources/research-data | sharing research data (first cited in `41-research-data.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/tools-and-resources/research-data/data-guidelines | research data guidelines (first cited in `41-research-data.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/tools-and-resources/research-data/data-statement | data statement (first cited in `42-data-statement.md`) | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/journal/data-in-brief | Data in Brief (first cited in `44-co-submission-of-related-data-methods-or-protocols.md`) | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/journal/methodsx | MethodsX (first cited in `44-co-submission-of-related-data-methods-or-protocols.md`) | `NOT MIRRORED — download to add` |
| https://legacyfileshare.elsevier.com/promis_misc/data-in-brief-article-template.docx | Data in Brief (first cited in `44-co-submission-of-related-data-methods-or-protocols.md`) | `NOT MIRRORED — download to add` |
| https://legacyfileshare.elsevier.com/promis_misc/MethodsX-Method-Article-Template.docx | MethodsX (first cited in `44-co-submission-of-related-data-methods-or-protocols.md`) | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/journal/methodsx/publish/open-access-options | MethodsX (first cited in `44-co-submission-of-related-data-methods-or-protocols.md`) | `NOT MIRRORED — download to add` |
| https://www.sciencedirect.com/journal/data-in-brief/publish/open-access-options | Data in Brief (first cited in `44-co-submission-of-related-data-methods-or-protocols.md`) | `NOT MIRRORED — download to add` |
| https://service.elsevier.com/app/answers/detail/a_id/38509/c/10528/supporthub/publishing/track/1POZUAo0Dv8E~YnLGiAa~yKg54Uqty75Mv_d~zj~PP9U/ | co-submission Researcher Support page (first cited in `44-co-submission-of-related-data-methods-or-protocols.md`) | `NOT MIRRORED — download to add` |
| https://credit.niso.org/ | CRediT (Contributor Roles Taxonomy) (first cited in `45-article-structure.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/policies-and-guidelines/credit-author-statement | more about CRediT and view an example of a CRediT author statement (first cited in `45-article-structure.md`) | `NOT MIRRORED — download to add` |
| https://apastyle.apa.org/products/publication-manual-7th-edition | Publication Manual of the American Psychological Association, Seventh Edition (2020) (first cited in `46-references.md`) | `NOT MIRRORED — download to add` |
| https://citationstyles.org/ | Citation Style Language (CSL) (first cited in `46-references.md`) | `NOT MIRRORED — download to add` |
| https://www.mendeley.com/reference-management/reference-manager/ | Mendeley Reference Manager (first cited in `46-references.md`) | `NOT MIRRORED — download to add` |
| https://service.elsevier.com/app/answers/detail/a_id/26093/ | remove all field codes (first cited in `46-references.md`) | `NOT MIRRORED — download to add` |
| https://submit.elsevier.com/JAPG | submit your paper (first cited in `48-submit-online.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper/submit-and-revise/article-transfer-service | Article Transfer Service (first cited in `49-article-transfer-service.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper/submit-and-revise/article-transfer-service/managing-editors | in-house scientific managing editor (first cited in `49-article-transfer-service.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies/copyright | policies related to copyright (first cited in `50-publishing-agreement.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/policies-and-standards/open-access-licenses | open access user license options (first cited in `51-license-options.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.support/publishing/news/journal-author-guide-to-alt-text-for-images | alt text guide (first cited in `54-proof-correction.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/about/accessibility | page about improving accessibility (first cited in `54-proof-correction.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper/sharing-and-promoting-your-article/share-link | Share Link (first cited in `55-sharing-your-published-article.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper/sharing-and-promoting-your-article | responsibly share and promote your article (first cited in `56-responsible-sharing.md`) | `NOT MIRRORED — download to add` |
| https://researcheracademy.elsevier.com/ | Elsevier Researcher Academy (first cited in `57-elsevier-researcher-academy.md`) | `NOT MIRRORED — download to add` |
| https://webshop.elsevier.com/language-editing-services/language-editing | English Language Editing service (first cited in `58-language-and-editing-services.md`) | `NOT MIRRORED — download to add` |
| https://service.elsevier.com/app/home/supporthub/publishing | Journal Article Publishing Support Center (first cited in `59-author-support.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.com/researcher/author/submit-your-paper | Step-by-step guide to publishing (first cited in `59-author-support.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.support/publishing/answer/video-guide-five-presubmission-tips-for-elsevier-authors-in-editorial-manager | Five pre-submission tips (first cited in `59-author-support.md`) | `NOT MIRRORED — download to add` |
| https://service.elsevier.com/app/answers/detail/a_id/29155/supporthub/publishing/kw/status+submitted+article/ | How can I track the status of my submitted article? (first cited in `59-author-support.md`) | `NOT MIRRORED — download to add` |
| https://www.elsevier.support/publishing/answer/when-will-my-article-be-published | When will my article be published? (first cited in `59-author-support.md`) | `NOT MIRRORED — download to add` |
