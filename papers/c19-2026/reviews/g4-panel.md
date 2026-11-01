# G4 panel note — consolidated triage (2026-10-31)

- **Status:** submitted for human review; all majors closed; writing of
  `paper/main.qmd` authorised by the researcher on the condition that RQ2
  results are anchored as claims first (done, claim-9…claim-12).
- **Scope:** the final clean Colab run (session 22:35–23:17 UTC, 11 declared
  stages, `errors.log` empty) plus the repo's manuscript-side artefacts
  (`manifest.yaml`, `references.bib`, gate notes).
- **Panel:** rev-design, rev-refs, peer-plan, peer-results, peer-reach,
  gate-claims, consolidated by gate-merge. This note is the auditable record
  of that round (the raw reviewer outputs live in this session's chat; every
  finding below carries its reviewer id and the resolving evidence).

## 1. Majors — closed

| Finding | Resolution |
|---|---|
| r4-design-01 / r4-plan-11: ML-B amenable verdict mislabelled | `09_ml_checks` three-state verdict; output: `no_positive_contribution` (delta-Brier −0.00292, CI −0.00574 to −0.00012); claim-8 wording |
| r4-design-02: claim-5 inverted the cancer negative control | claim-5 rewritten: cancer shows the same small non-significant gradient → not access-specific |
| r4-design-03 / r1-results-01 / r4-claims-01: claim-2 CI and claim-3 14.4 % in no output | `osm_stratified.csv` now carries bootstrap CIs (non_amazon 0.850 [0.752–0.912], amazon 0.653 [0.489–0.790]); `calibrated_share.json` writes 12.5 %→14.4 % (>60) and 5.5 %→4.2 % (>120) with the district-level definition |
| r4-refs-01/02: 15 verified citations absent from the bib | 16 verified entries added (Weiss ×2, Luo & Wang, Luo & Qi, Nolte & McKee, Tobias & Yeh, Meara, Miranda-Chavez, Cameron & Miller, Liang & Zeger, Mundlak, Roberts, Ploton, Niculescu-Mizil, Grinsztajn) + SINADEF @misc |
| r4-refs-03/04/05: three broken entries | ref22 (wrong DOI), ref23, ref24 (unverifiable) removed |

## 2. Everything else the round changed

- **Plan v12:** H3b gains altitude (interaction p now 0.251, still null);
  completeness r-flag (r = −0.108, no flag); code-only sensitivity (n = 234,
  reported as a count); FP/coverage/GEE rule verdicts recorded
  (`fp_gate_passes=false`, coverage passes only at 1.2/1.5, GEE criterion
  fails); bootstrap CIs persisted; three-state ML-B verdict; calibrated
  shares; waivers declared for walking_time, grid_vs_centroid, M2 fidelity/
  Spearman, the 11-province exclusion and the min-located flag; GEE 50k
  subsample and the 200-permutation placebo declared.
- **Plan v13 (human decisions):** equity table by altitude band × Amazon basin
  added post hoc (descriptive, no new inference); sex reported as a limitation
  (district-level exposure); headline uncertainty = variant range
  (12.5–14.4 %), not a bootstrap CI; policy statements rest on RQ1/RQ2 only.
- **Claims:** claim-1 states the population-weighted vs district-weighted
  contrast explicitly (37.8 vs 91.6 min) and the 120-min caveat; claim-2 keeps
  the caution (overall rho 0.738; the outside-basin stratum passes 0.80 with
  the lower CI bound at 0.752; the stratum was defined after seeing the
  results — recorded); claim-3 carries both the 60- and 120-min shifts and the
  definition; claim-8 says "small, non-specific"; **claims 9–12 added for
  RQ2** (straight-line refutation criteria not met: 0.90/0.92 Spearman vs
  0.95, kappa 0.40/0.38 vs 0.90 → travel time changes the priority
  classification; destination sets invariant: Spearman 0.991–0.993, kappa
  0.978–0.990, Jaccard 0.98; 2SFCA reorders: Spearman 0.553/0.371, kappa 0.0;
  M5 371 districts / 739,935 people / 2.3 % with stability 97.3 % and Kendall
  0.729 caveat; M7 Moran 0.662 with cluster sets unstable across weight
  matrices, 67 % vs 25 % max → descriptive).
- **references.bib:** 64 entries; doi_validate.py `--check` PASS (0 errors);
  the 5 proposed additions (Carrasco-Escobar, Tatem, Delamater, Nelson,
  Vargas-Herrera) all validate — the human approves them after this
  script pass (decision recorded).
- **Gate notes:** G2 FCA Jaccards fixed (0.093/0.399) and "top-100" label;
  G3b `other` 1.053; G3 H3b p = 0.251 (with altitude); G1/G3b basin CI
  updated to the persisted values.

## 3. Pending for the writing phase (tracked, none gates the start)

1. Prune the legacy bib entries (~25, classifier design) once the draft cites
   its real set; add a URL/DOI to ref20 (LightGBM) or drop it.
2. Flip manifest claim statuses `draft` → `verified` only after drafting, when
   gate-claims re-runs clean.
3. Peer-reach majors, each with a scheduled writing-time action: uncertainty
   statements (variant range + kappa/FP caveats); Discussion comparison with
   Weiss 2020 and Carrasco-Escobar 2020; a policy paragraph grounded in
   RQ1/RQ2 (371 districts, 2.3 %, method-dependence); the post hoc equity
   table (altitude band × basin) per plan v13.
4. Figures: national choropleth, discordance map, RQ3 forest plot — from
   `district_access.csv`, `district_variants.csv`, 08/09 summaries; register
   in `manifest.yaml` `figures[]` (the inherited EXAMPLE entry is replaced).
5. `outputs/manifest_index.json` regenerated once outputs settle.
6. `osm_secondary.csv` / `sensitivity_misplaced.csv` re-synced from Drive
   (cosmetic by-products).
7. The two phantom Drive files (`06_evaluate_classifier.py`,
   `07_explain_shap.py` in `code/`) — delete from the Drive UI; they no longer
   run. `_probe_ml.py` stays (colab.yaml probes use it).
8. AI-use declaration and novelty check: paper-writing items, before
   submission; `paper-compliance` against the banked Applied Geography guide
   (guide is present under `templates/journals/applied-geography/guide/`).
9. Nothing is committed; the work lives in the tree and on Drive. Commit only
   on the researcher's order.

## 4. Verdict

All majors closed; claims now anchor RQ1, RQ2, RQ3 and ML A/B to
machine-readable outputs; the bibliography validates end-to-end. Writing
`main.qmd` (full rewrite of the inherited 859-line INVS draft) starts on the
researcher's signal.
