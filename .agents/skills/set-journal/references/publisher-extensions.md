# Publisher → Quarto extension mapping

The journal's website never states its Quarto extension (that's a Quarto-ecosystem
fact, not an editorial one). We deduce it from the publisher. This table is the
source of truth for that deduction.

| Publisher (detected) | Quarto extension | quarto_format | Default cite_style | format |
|---|---|---|---|---|
| Elsevier | `quarto-journals/elsevier` | `elsevier-pdf` | number | latex |
| IEEE | `quarto-journals/ieee` | `ieee-pdf` | number | latex |
| MDPI | `quarto-journals/mdpi` | `mdpi-pdf` | numbername | latex |
| ACM | `quarto-journals/acm` | `acm-pdf` | number | latex |
| ACS | `quarto-journals/acs` | `acs-pdf` | number | latex |
| PLOS | `quarto-journals/plos` | `plos-pdf` | number | latex |
| AGU | `quarto-journals/agu` | `agu-pdf` | authoryear | latex |
| Springer / Springer Nature | `""` (none official) | `pdf` | numbername | latex |
| Frontiers | `""` (none official) | `pdf` | authoryear | latex |
| Taylor & Francis | `""` (interact class, no official ext) | `pdf` | authoryear | latex |
| Wiley | `""` (none official) | `pdf` | authoryear | latex |
| Unknown / other | `""` | `pdf` | number | latex |

## Notes

- An empty extension (`""`) means there is no official `quarto-journals/*`
  package. In that case the paper uses generic `pdf` + `docx`, and the final
  submission PDF needs the journal's own template manually (a `reference-doc`
  for Word, or a raw LaTeX bundle in `templates/journals/<slug>/raw-bundle/`).
- `cite_style` here is a sensible DEFAULT; the journal's Guide for Authors wins
  if it specifies otherwise. When scraping, if the page states a citation style,
  prefer that and note it.
- Springer has community templates but no official quarto-journals package, so we
  treat it as "none" to avoid pointing `quarto add` at something that may break.

## How the publisher is detected

From the link's domain and page text:

- `sciencedirect.com`, `elsevier.com` → Elsevier
- `ieee.org`, `ieeexplore.ieee.org` → IEEE
- `mdpi.com` → MDPI
- `dl.acm.org`, `acm.org` → ACM
- `pubs.acs.org` → ACS
- `journals.plos.org` → PLOS
- `link.springer.com`, `springer.com`, `springeropen.com` → Springer
- `frontiersin.org` → Frontiers
- `tandfonline.com` → Taylor & Francis
- `onlinelibrary.wiley.com` → Wiley

If the domain is not recognized, read the page for a publisher name; if still
unknown, ask the user and leave the extension empty.
