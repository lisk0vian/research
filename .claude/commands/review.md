---
description: Review a paper's code or manuscript with peer subagents (asks scope, chat by default)
argument-hint: "<slug> <selector: paper | code | gate | <agent> | plan | full>"
---

0. SLUG is mandatory. Take it from $ARGUMENTS (`/review <slug>
   <selector>`). If present and matching papers/*, use it WITHOUT
   asking — write SLUG=<slug> and continue. Only if absent or
   invalid, ask with the real papers/* list and wait. Everything
   below runs on papers/<slug>/ only.

1. Resolve SELECTOR to an explicit agent list FIRST. If present
   and valid (group, agent, list or preset below), use it WITHOUT
   asking — write RESOLVED=[...] and continue. Only if absent,
   invalid or ambiguous, ask with options (recommended first;
   max 2 rounds):
   paper=[rev-design,rev-refs,rev-style]
   code=[peer-plan,peer-results,peer-reach]
   gate=[gate-claims] (+gate-merge only if >=2 reports total)
   <agent>=[that one]   a,b=[a,b]
   presets: plan=[peer-plan] manuscript=[rev-design,rev-refs,rev-style]
   claims=[gate-claims] full=[all 7]+gate-merge last.
   Launch ONLY those lines from step 4, in parallel.
   Nothing resolved = nothing launched.

2. Read papers/<slug>/ context FIRST: DESIGN_DECISIONS.md,
   METHODOLOGY.md, experiments/config.yaml, manifest.yaml
   (whichever exist). State what you read. Classify and say so:
   SIMPLE (recommendation + minimal plan the user validates and
   applies) vs COMPLEX (propose round: scope + agents, wait yes).
   Ask the path with options via the session question tool only
   for what step 0-1 left unresolved (missing/invalid/ambiguous)
   or for the SIMPLE-vs-ROUND decision — never re-ask what the
   user already stated explicitly.

3. CHAT (default): return each verdict here. Write NO files.
   ROUND (explicit only): paper_review.py --slug S --round N
   --scope code-only|full [--only ...]; save each final YAML to
   raw/ only after ALL finish; render consolidated.md; pre-fill
   triage.yaml in pending; validate; hand triage over (no major
   in pending/undecided to close; max 3 rounds). code-only defers
   manuscript checks + gate-claims explicitly; full without
   main.qmd errors out.

4. Launch lines (use ONLY the RESOLVED ones, parallel, isolated —
   no reviewer reads another report or reviews/). Spawn each as a
   SUBAGENT by name with its task prompt (native mechanism:
   subagent/task tool in OpenCode, Task(subagent_type=...) in
   Claude Code; @ means file reference, never agents):

   Task(subagent_type=rev-design) — Methodology examiner. Read paper/main.qmd +
   manifest.yaml (+METHODOLOGY.md if any). Major only if it
   invalidates a named conclusion or blocks reproduction.
   Return YAML findings, ids rN-design-nn.

   Task(subagent_type=rev-refs) — Literature reviewer. Read paper/main.qmd +
   paper/references.bib. Flag unsupported central claims.
   Return YAML findings, ids rN-refs-nn.

   Task(subagent_type=rev-style) — Clarity + journal guide. Read paper/main.qmd.
   Blocking editorial issues only. YAML, ids rN-style-nn.

   Task(subagent_type=peer-plan) — Colleague. Read experiments/, config.yaml,
   outputs/, manifest.yaml. Does the pipeline answer the
   question and support the hypotheses? YAML, rN-plan-nn.

   Task(subagent_type=peer-results) — Colleague. Same inputs. Do outputs suffice
   to write and support conclusions, or what is missing?
   YAML, rN-results-nn.

   Task(subagent_type=peer-reach) — Colleague. Same inputs + journal target.
   Q1 level (novelty, rigor, fit) and exactly what is missing.
   YAML, rN-reach-nn.

   Task(subagent_type=gate-claims) — Comptroller. packet.yaml + manifest claims +
   paper/main.qmd + outputs/. Every number equals its source;
   code_hashes rule. YAML, ids rN-claims-nn, two-sided evidence.

   Task(subagent_type=gate-merge) — Managing editor, LAST, only if >=2 reports.
   Read raw/*.yaml + packet.yaml (+ prior rounds). Deduplicate,
   keep contradictions visible, discard failed evidence with
   reason. Return consolidated.yaml content (merged_from +
   discarded, never addressed). Writes nothing itself.

5. Finding contract: severity major|minor; kind presence|absence;
   MVP: major requires demonstrable (normative always minor);
   title<=140; location path:line; evidence max 2 verbatim
   (evidence[0] inside cited lines, hash-anchored); absence needs
   searched (existing) + expected; warrant<=280 (none => no major);
   fix<=280; max 15 + omitted_count; English. Never invent evidence.
