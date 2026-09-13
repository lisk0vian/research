# Common render errors and fixes

Real errors seen when building freshly migrated papers, with the actual cause
and the fix. Map the Quarto/LaTeX message to this table before touching content.

## LaTeX / math

- **`\symbb allowed only in math mode`** or math showing up as escaped text
  (`y\_i = \mathbb{1}\left{[}...`):
  An equation is trapped inside a pandoc table (rows of `----- ---` around it),
  so pandoc escaped every character instead of treating it as display math.
  **Fix:** remove the surrounding table dashes and leave the `$$ ... $$` block as
  a normal paragraph with a blank line above and below.

- **`Missing $ inserted`**:
  Inline math not wrapped. **Fix:** wrap the symbol in `$...$`
  (e.g. `k=4` → `$k=4$` when it uses math symbols).

- **`Undefined control sequence`**:
  A LaTeX macro the journal class doesn't define. **Fix:** replace with a
  standard equivalent, or add the package via `include-in-header`.

- **Equation exported as an image** (`![](media/imageN.png)` where an equation
  should be):
  The Word source had a non-native equation. **Fix:** transcribe it to `$$...$$`
  LaTeX by reading the image. (This is what paper-migrate should do.)

## Bibliography / citations

- **`Citation 'key' undefined`** or **empty bibliography**:
  The `[@key]` in the text has no matching entry in `references.bib`, or
  `bibliography: references.bib` is missing from the front-matter.
  **Fix:** add the entry (or fix the key). Never invent a reference.

- **BibTeX `Warning--empty journal` / `empty year`**:
  The `.bib` is in biblatex format (`journaltitle`, `date`) but the style is
  classic BibTeX (`journal`, `year`). **Fix:** convert with the bib conversion
  step (journaltitle→journal, date→year). Not a build blocker, but the output
  references will be malformed.

## Fonts / engine

- **`fontspec`/`Font ... not found`**:
  Engine mismatch. Elsevier/IEEE formats may expect a specific engine. **Fix:**
  let the extension pick the engine; ensure TinyTeX is installed
  (`quarto install tinytex`).

## Structure / headings

- **Duplicated section numbers** (`1 I. Introduction`):
  The heading text still has manual numbering (`# I. Introduction`) while the
  journal class numbers automatically. **Fix:** strip the manual `I.`, `A.`
  prefixes from headings.

- **`.qmd` defaulting to HTML in plain pandoc**:
  Only relevant if bypassing Quarto — pandoc doesn't know `.qmd`. Use
  `quarto render`, or `pandoc -t markdown` if converting the other direction.
