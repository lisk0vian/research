# Timings — c26-2026

How long each process takes, and how long to expect. `expected` is the
median of the *fresh* measured runs when there is one, else the a-priori
estimate in `timings.yaml`; the two are never blended. A measurement
goes stale when the stage's key or code changes (`fresh` in the JSON), and
the expectation then falls back to the estimate until a run re-measures it.
`⚠` marks a last run outside its estimate range.

Updated: 2026-10-04T00:20:51+00:00. Full history in `timings.json`.

## full mode

| stage | expected | source | last | median | p90 | n | stale | unit | per unit | vs estimate |
|---|---|---|---|---|---|---|---|---|---|---|
| pipeline | 1800.0 | estimate | 1812.39 | — | — | 0 | 1 | etapa | 8.8 | ×1.01 |

## current run

no run recorded yet.

