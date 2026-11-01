# Citation ledger — c19-2026 manuscript

Every citation in `paper/main.qmd` and `paper/supplementary.qmd`, with what the
text attributes to it and how that was checked (2026-11-01). Metadata: CrossRef
(`get_paper_by_id`) unless stated. Passages: the abstract or text read through
PubMed, Europe PMC/PMC, the publisher page (browser) or DataCite. "Known" marks a
classic method reference cited only for the method it introduced.

## Context and access concepts

| Key | Attributed in the text | Checked against |
|---|---|---|
| meara2015 | Timely access = share of the population reaching, within 2 h, a facility able to do caesarean delivery, laparotomy and treatment of open fracture | Full text, thelancet.com: "Proportion of the population that can access, within 2 h, a facility that can do caesarean delivery, laparotomy, and treatment of open fracture (the Bellwether Procedures)" |
| kruk2018 | Timely action is a component of competent care; access is a prerequisite for benefiting from care | Full text, PMC7734391: Table 1 lists "timely action" under competent care and systems; "access is a prerequisite for benefiting from health care" |
| weiss2020 | 8.9 % of the world population cannot reach a facility within 1 h motorized, 43.3 % on foot; 2020 motorized and walking-only surfaces | PubMed 32989313 abstract: "8.9% of the global population (646 million people) cannot reach healthcare within one hour"; "43.3% (3.16 billion people) ... by foot within one hour" |
| ouma2018 | 29.0 % of people in sub-Saharan Africa live more than 2 h from a public hospital | PubMed 29396220 abstract: "287 282 013 (29·0%) people" beyond 2 h; AccessMod cost-distance |
| florio2023 | Access falls from cities to villages and dispersed rural areas; impedance rather than facility density limits access | ScienceDirect abstract: >95 % within 30 min in cities, 65 % in villages and dispersed rural areas; "determined by high travel impedance, since overall spatial densities of HCF are comparable to European levels" |
| juran2018 | Combines travel time with the burden of surgical disease | CrossRef abstract: travel-time metrics of 30 min, 1 h and 2 h combined with fine-scale population to define burden of surgery |
| penchansky1981 | Access is multidimensional | Known (the five dimensions of access); metadata CrossRef |
| guagliardo2004, wang2012, neutens2015 | Spatial accessibility requires choices of metric, model, destinations and population unit; reviews ask that the choice be justified | Reviews of accessibility methods; metadata CrossRef |
| alcalde2011 | Separate networks in the Peruvian health system; extension of coverage is its main challenge | PubMed 21877089 abstract: "The main challenge confronted by the Peruvian health system is the extension of coverage"; the networks themselves are described from the RENIPRESS institutions, not from this source |

## Measurement and agreement between measures

| Key | Attributed in the text | Checked against |
|---|---|---|
| luo2003 | Definition of 2SFCA | CrossRef abstract (floating catchment and gravity measures, Chicago) |
| luo2009 | Distance-decay (enhanced) 2SFCA | Title and metadata; method reference |
| apparicio2008 | Montreal: centroid measures accurate overall but important errors for 5–10 % of tracts; Cartesian and network distances correlate > 0.95 | PubMed 18282284 abstract; Montréal CMA named in the figure caption |
| apparicio2017 | Errors of the same order (10 % of tracts); distance types correlate > 0.90; the choice of measure changes the assessment most | PubMed 28830461 abstract |
| hewko2002 | Aggregation error arises when one point represents a population; finer data on residents reduce it | SAGE abstract (Edmonton): "aggregation error does affect NSA indicators"; recommends "finer resolution data to indicate the spatial distribution of individuals within neighbourhoods" |
| delamater2012 | Raster and network models place limited-access areas alike but count different numbers of people | PubMed 22587023 abstract |
| openshaw1984, fotheringham1991 | Modifiable areal unit problem | Known (book, CATMOG 38); CrossRef abstract for Fotheringham and Wong |
| bhangdia2022 | Five measures correlate 0.78–0.99 in rural Haiti, yet straight-line distance overstates coverage | PubMed 35613799 abstract |
| nelson2019 | Global indicators were shorter than Google driving times (median −16.9 %) | CrossRef abstract: "median percentage difference of −16.9%" |
| rudolfson2020 | Self-reported journeys 1.49 times the modeled ones (rural Rwanda) | PubMed 32274536 abstract: "longer than GIS estimates by a factor of 1.49" |
| bankethomas2021 | Lagos: replicated drives median ~50 min vs 5 min friction surface and 11 min OSRM | PubMed 33495286 abstract |
| weiss2018 | Friction surfaces and accumulated cost | CrossRef metadata; method reference |
| carrasco2020 | Village-level times to public facilities of three levels; no population weighting; no comparison with other measures or observed journeys | Full text (frontiersin.org): "Future studies may consider population-weighted estimates"; no validation reported |
| bocanegra2025 | 42.4 % of the population cannot reach public neurosurgical care within 4 h | PubMed 40064145 abstract: "13,819,251 people (42.36 %) could lack neurosurgical access within 4 h" |
| perez2026 | Spain: longer car travel time to hospitals associated with higher mortality, most among older adults and time-sensitive causes; mortality outcome | ScienceDirect abstract and methods (census-section car travel time; mortality microdata 2010–2019) |
| stevens2015 | Dasymetric disaggregation behind WorldPop | Title and metadata |
| barry2003 | High altitude 2,500–3,500 m, very high 3,500–5,800 m | Full text PMC1125825, Box 1 |
| kwan2012 | Uncertain geographic context problem | Known; metadata CrossRef |
| robinson1950 | Ecological fallacy | Known; metadata CrossRef |

## Place of death and the outcome

| Key | Attributed in the text | Checked against |
|---|---|---|
| gomes2006 | Among people with cancer, home death associated with low functional status, preference, home care and family support | PubMed 16467346 abstract (six factors) |
| cordoba2026 | Latin America: home death associated with older age, lower education and, in some countries, rural residence | Full text (ssph-journal.org); rural residence OR 1.39–2.53 in three studies |
| mirandachavez2026 | Peru 2017–2024: 41.3 % of deaths at home; differences by insurance, education, ethnicity and department | Springer abstract (browser) |
| nolte2003 | Concept of amenable mortality (the cause list is adapted, not copied) | CrossRef abstract |
| vargas2018 | National roll-out of the online death certificate system | Title and metadata (CrossRef: 8 authors, p. 505) |

## Methods and software

| Key | Attributed in the text | Checked against |
|---|---|---|
| dijkstra1959, virtanen2020 | Shortest-path accumulated cost (scipy.sparse.csgraph.dijkstra) | Code (`experiments/_access.py`); metadata CrossRef |
| cohen1960 | Kappa | Known; metadata CrossRef |
| anselin1995, benjamini1995, rey2022 | Local Moran, false discovery rate, PySAL | CrossRef abstracts; code (`06_spatial_stats.py`) |
| cameron2015, mundlak1978, liang1986 | Cluster-robust SEs, fixed effects, GEE | Metadata CrossRef; plan `outcome.estimator_citations` |
| morris2019 | Simulation design and Monte Carlo SEs | CrossRef abstract (ADEMP) |
| roberts2017, ploton2020 | Spatially blocked validation (leave one department out) | Metadata CrossRef; verified in the plan (decision 0001) |
| seabold2010, pedregosa2011 | statsmodels, scikit-learn | Metadata CrossRef; JMLR 12:2825–2830 |

## Data

| Key | What | Checked against |
|---|---|---|
| renipress2026 | RENIPRESS, October 2026 edition | `data/SOURCES.md` §1 (URL, sha256) |
| inei2026 | Census 2025 district tables | `data/SOURCES.md` §2 |
| bondarenko2025, tatem2017 | WorldPop R2025A constrained grid | DataCite 10.5258/SOTON/WP00839 (title, creators, 2025) |
| ocha2025 | COD-AB Peru (HDX) | `data/SOURCES.md` §9 |
| esa2021 | Copernicus DEM GLO-30 | DOI 10.5270/ESA-c5d3d65 resolves to the Copernicus Data Space COP-DEM page |
| lehner2013 | HydroBASINS | CrossRef abstract; `data/SOURCES.md` §7 |
| luxen2011, osm2026 | OSRM and OpenStreetMap data (demo server) | `data/SOURCES.md` §8 |
| sinadef2026 | SINADEF death certificates to 2025-11-30 | `data/SOURCES.md` §4 |

## Numbers in the text that come from the literature (not from outputs/)

8.9 % and 43.3 % (weiss2020); 29.0 % (ouma2018); 0.78–0.99 (bhangdia2022);
5–10 % (apparicio2008); −16.9 % (nelson2019); 1.49 (rudolfson2020); 50, 5 and
11 minutes (bankethomas2021); 41.3 % (mirandachavez2026); 42.4 % (bocanegra2025);
2,500 and 3,500 m (barry2003); two hours (meara2015). Every other number is a
claim in `manifest.yaml`.

## DOI audit (`scripts/doi_validate.py --slug c19-2026`, 2026-11-01)

60 entries: 49 DOIs verified against CrossRef, 8 entries without a DOI (datasets,
the Openshaw book, JMLR, and Alcalde-Rabanal 2011 with PMID 21877089) and three
warnings, each checked by hand:

- `bondarenko2025`: DataCite DOI (10.5258/SOTON/WP00839), absent from CrossRef by
  design; title, creators and year checked on the DataCite API.
- `esa2022`: CrossRef registers the title "Copernicus DEM" (European Space Agency,
  2022); the bib title adds "[dataset]" as the guide asks for data references.
- `penchansky1981`: CrossRef stores only "The Concept of Access"; the bib keeps
  the full published title with its subtitle.
