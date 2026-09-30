# Slug naming convention

The slug is the folder name under `papers/<slug>/` and the identifier used
across the whole pipeline. Keep it stable — renaming later breaks references.

## Rule

1. **Institutional/internal code exists** (e.g. `C15-2026`, assigned by the
   funding institution): use it **lowercased** as the slug.
   - `C15-2026` → `papers/c15-2026/`
   - Rationale: it is already unique, short, and is the same identifier used in
     the journal submission system and the cover letter. Folder and official
     reference stay in sync with nothing new to remember.

2. **No code**: a short **2-4 word kebab-case** descriptive slug combining
   topic + method. Never the full title.
   - "Application of FAMD and K-Means for Carrión disease clustering" →
     `carrion-clustering`
   - "Wholesale price forecasting of Canchán potato" →
     `potato-price-forecasting`

## Constraints

- Lowercase letters, numbers, and hyphens only.
- No spaces, no underscores, no accents.
- Must not already exist under `papers/`.