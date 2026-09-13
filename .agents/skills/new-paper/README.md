# assets/ — Seed templates for new-paper

These are the LITERAL templates that the scaffold copies and fills. The script
substitutes `{{...}}` placeholders mechanically; the agent only decides the
VALUES (which authors, which journal), never rewrites the structure.

**Golden rule:** if a repo file has a fixed shape, its model is here. The agent
must NOT generate any of these from scratch — always start from the template.

## Placeholders and who fills them

| Placeholder | Filled by | Example |
|---|---|---|
| `{{SLUG}}` | user (paper argument) | `c15-2026` |
| `{{TITLE}}` | ask the user | `A Reproducible Framework for...` |
| `{{INTERNAL_CODE}}` | ask (empty if none) | `C15-2026` |
| `{{INSTITUTION}}` | ask / repo default | `SENATI` |
| `{{FUNDING}}` | ask | `This work was funded by SENATI...` |
| `{{JOURNAL_SLUG}}` | pick from templates/journals/ | `machine-learning-with-applications` |
| `{{JOURNAL_NAME}}` | from journal type.yaml | `Machine Learning with Applications` |
| `{{QUARTO_FORMAT}}` | from type.yaml (or `pdf`) | `elsevier-pdf` |
| `{{CITE_STYLE}}` | from type.yaml | `number` |
| `{{PUBLISHER}}` | from type.yaml | `elsevier` |
| `{{FORMAT}}` | from type.yaml | `latex` |
| `{{QUARTO_EXTENSION}}` | from type.yaml | `quarto-journals/elsevier` |
| `{{ISSN}}` | from type.yaml | `2666-8270` |
| `{{ABSTRACT}}` | placeholder or migrated | `TODO` |
| `{{KEYWORDS_BLOCK}}` | YAML list | see below |
| `{{AUTHORS_BLOCK}}` | built from authors/ | author: block of the qmd |
| `{{AUTHORS_MANIFEST_BLOCK}}` | id+role+order | authors: block of the manifest |
| `{{ROUND}}` | review round number | `1` |
| `{{AUTHOR_ID}}` `{{AUTHOR_NAME}}` etc. | when creating a new author | — |

## Multi-line blocks

`{{KEYWORDS_BLOCK}}` expands to a YAML list, two spaces + dash per item.

`{{AUTHORS_BLOCK}}` (in main.qmd) expands by reading each authors/<id>.yaml into
the Quarto author schema (name, orcid, email, affiliations).

`{{AUTHORS_MANIFEST_BLOCK}}` (in manifest.yaml) expands to id + role + order per
selected author.

## Files in this folder

- main.qmd.template — paper body with front-matter
- manifest.yaml.template — metadata + claims + figures
- references.bib.template — empty bib with a format reminder
- comments/responses/ai-review.yaml.template — reviews
- author.yaml.template — a catalog author entry
- journal-type.yaml.template — a journal catalog entry
- gitignore.template — copied to the repo root as .gitignore
