# External references — discover-artificial-intelligence

Pages this submission-guidelines page links to that are **not** part of it. A
row marked `NOT MIRRORED` means the text is not in the bank and the URL is where
to get it.

This is a **Springer Nature** journal, not an Elsevier one. Its shared pages are
not interchangeable with the Elsevier ones filed under
`_shared/elsevier/`, and anything mirrored from here belongs in
`_shared/springer-nature/`.

To promote a row: download the page, hand it over as a file (or paste the text),
file it into `_shared/springer-nature/<topic>.md`, then

```
python scripts/journal_guide.py cites --url "<the url>"    # every file that links here
```

rewrite each one to the local path, mark the row `mirrored:`, and run `cites`
again — it must print nothing. That zero is the proof nothing was left behind.

## Journal- and publisher-specific

| url | topic | state |
|---|---|---|
| https://link.springer.com/brands/discover/policies | discover-editorial-policies | `NOT MIRRORED — download to add` |
| https://www.surveymonkey.com/r/HYBMNWT?smsubject=%5Bsmsubject_value%5D | open-access-survey | `NOT MIRRORED — download to add` |
| https://media.springer.com/full/springer-instructions-for-authors-assets/docx/Data-note-template-Discover.docx | data-note-template | `NOT MIRRORED — download to add` |
| https://media.springer.com/full/springer-instructions-for-authors-assets/pdf/Matters-arising-guidelines-Discover.pdf | matters-arising-guidelines | `NOT MIRRORED — download to add` |
| https://media.springer.com/full/springer-instructions-for-authors-assets/pdf/Registered-report-guidelines-Discover.pdf | registered-report-guidelines | `NOT MIRRORED — download to add` |

## Springer Nature-wide

| url | topic | state |
|---|---|---|
| https://www.springernature.com/gp/snapp | snapp-submission-system | `NOT MIRRORED — download to add` |
| https://link.springer.com/journal/44163/how-to-publish-with-us | how-to-publish-with-us | `NOT MIRRORED — download to add` |
| https://www.springernature.com/gp/authors/research-data-policy/recommended-repositories | recommended-data-repositories | `NOT MIRRORED — download to add` |
| https://www.springernature.com/gp/policies/editorial-policies/third-party-permissions | third-party-permissions | `NOT MIRRORED — download to add` |
| https://www.springernature.com/gp/open-science/policies/journal-policies/licensing-and-copyright | licensing-and-copyright | `NOT MIRRORED — download to add` |
| https://www.springernature.com/gp/authors/campaigns/writing-in-english | writing-in-english | `NOT MIRRORED — download to add` |
| https://www.springernature.com/gp/authors/campaigns/latex-author-support | latex-author-support | `NOT MIRRORED — download to add` |
| https://authorservices.springernature.com/go/sn/ | author-services | `NOT MIRRORED — download to add` |
| https://www.nlm.nih.gov/bsd/uniform_requirements.html | uniform-requirements-for-manuscripts | `NOT MIRRORED — download to add` |

## Same guide, different anchor

The page links to itself several times — `…/submission-guidelines#top` — in the
Snapp instructions and elsewhere. Those resolve within this guide; the anchors
are carried over from the page's own `id` attributes, so `sections/…#step-4`
points at the right file.

## Not listed above

The page's navigation also links to a **Pre-submission checklist**
(`link.springer.com/pre-submission?journalId=44163`) and a *Mistakes to avoid
during manuscript preparation* page. Those are site navigation rather than
references from the guidelines, so they were not queued here — but the checklist
is author-facing and worth mirroring if you want it offline.