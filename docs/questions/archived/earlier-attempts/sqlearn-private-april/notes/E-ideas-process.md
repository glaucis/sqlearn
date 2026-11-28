---
type: note
tags: [planning, process, ideas, reports, retrospective]
summary: "Batch E review of April 2026 sqlearn-private ideas, reports and process, judging relevance to the new project and what to avoid."
related: []
mdindex: [type=edb465, tags=162eda, summary=094536]
---
# Batch E: ideas, reports and process (April planning repo)

Source: `OLD` = `sqlearn-ecosystem_old/sqlearn-private` (ROOT of the folder of
attempts), GitHub `glaucis/sqlearn-private`, 9-24 April 2026, 593 commits.
Citations are `OLD:path:Lnn` (path relative to OLD) or short shas from the
commit log (`private-april-git-log.txt`). Statements marked *inference* are
mine, not the source's. Nothing under `OLD/_old_sqlearn/` was read.

Reading depth is stated per file in **Files covered**. The two long ideas
files (launch strategy, README draft) and the larger v2 reports were read
by section, not line by line. `_old_standards/` holds only `raw/` (there is
no `unprocessed/` folder).

## Summary

- **593 commits in 16 days produced no library code.** From `8e8cc95`
  (12 Apr) the repo was declared "documentation-only"; the v0.4 code lived
  elsewhere and was imported read-only as `_old_sqlearn/` (`a43ce53`). The
  only code written here was hooks, validators and scripts for the documents
  themselves (`e1f5ec9`, `d3e1f18`).
- **About two thirds of the commits were process** (keyword count 392 of
  593; *inference*, crude): plan ticking, archiving, templates, indexes,
  skills, agents, hooks, cascade validators. About 150 are plan bookkeeping
  alone (`docs(plans)`, `chore(plan)`, `chore(archive)`); 91 are literal
  "tick box" or "mark Part N" commits.
- **The process was torn down on 23 April** (`7b9d8f9`, `99a8cd6`): pipeline
  enforcement, protocols, agents, memories and the changelog scaffolding were
  removed, three days after the orchestration pipeline was built (`dd20a9b`,
  20 Apr). The last commits promote single files back out of
  `_old_standards/raw/` (`16115b0`, `1416b6d`, `055eef0`).
- **A philosophy rewrite ("v2") on 21 April invalidated about 80 files**
  (`OLD:reports/archived/2026-04-21-v2-synthesis.md:L63`): the `option=`
  cascade, the three safety tiers and `settings.md` (drained 19 Apr, deleted
  21 Apr, `9d76963` then `16e978c`) were removed within two days of being
  finished. Docs written at speed, then rewritten.
- **The reports are where failure surfaces, and they are mostly about the
  process itself**: self-contradicting plan checklists, validation boxes that
  cannot be ticked, an audit that found nothing to change, a CLAUDE.md that
  grew to 690 lines. No report found a defect in a transformer, because none
  was ever built (`v2-test-validation-impact.md:L63`: tests and validations
  folders are "pure README stubs").
- **The fit defect in the baseline is present and undiscussed.** The README
  draft shows the fitted state of `Impute` and `Scale` on one column learned
  together (`median` and `mean` side by side, `ideas/sqlearn-readme-draft.md
  :L245`); the design is "learn, bake literals, apply" with no step ordering
  for learning (`ideas/launch-strategy-and-marimo-wedge.md:L1666`).
- **Ideas that bear on the core** are few and small: NULL-preserving
  default, teaching errors with three remedies, a determinism rule for
  expressions, `order_by` plus a row-identity column for window steps,
  outputs that are only known after fit (`multi-output-rename`), and a
  predicate-expression API question. The rest is positioning (Free/Pro,
  marimo, AutoML, MCP) that conflicts with the new project's agreed shape.
- **Positions that contradict the new project**: MIT licence and a
  proprietary Pro tier, preprocessing only (no models), no GUI in the free
  library, pandas "for exploration", Rust rewrite "permanently rejected",
  sqlglot multi-database as the identity.
- **Confirmed baseline items**: renamed API plus parked bridge
  (`as_sklearn`), `y` as a column name, `__`-keyed learned state, sqlglot
  everywhere, a strong validation method with zero validators drained,
  bursts then stalls, status kept by hand in many places.
- **What the new workflow must guard against**: process that outgrows the
  product, status in more than one place, philosophy rewrites after
  drafting at scale, checkbox plans, skills duplicated in two trees,
  unmeasured effort estimates, and agents that skim (the repo added a "RULE
  0, read files completely" on 23 April, `f375faa`).

## Ideas

One line each: proposal, then relevance to the new project's parts
(3.2 core, 3.3 breadth, 3.6 EDA, 3.7 editor, 3.8 validation, 3.9
benchmarks).

- `sklearn-compat-adapter` (`OLD:ideas/sklearn-compat-adapter.md:L6`):
  `pipe.as_sklearn()` wraps a renamed API (`learn`/`apply`) as an estimator;
  parked behind an own `sq.Search`. Core: with ADR 0003 the bridge is
  unnecessary, but its row-count point stands (L53): a transform that drops
  rows breaks scikit-learn's contract, so the core should say whether steps
  may change row count.
- `multi-output-rename` (`OLD:ideas/multi-output-rename.md:L26`):
  `out_column=[...]` for encoders; the number of outputs is known only after
  learning, so the check must happen at fit. Core and editor: declared
  outputs are not always static data; the node-editor requirement
  ("outputs as data") needs a "known after fit" state.
- `python-expression-dsl` (`OLD:ideas/python-expression-dsl.md:L14`):
  `col("x") > 0` predicates beside SQL strings, both converging on one AST.
  Core: a decision on `where=` style (string vs expression) is needed;
  expression form also suits the editor. Parked in the source.
- `window-functions` (`OLD:ideas/window-functions.md:L35`): Lag, Lead,
  Rolling, Cumulative, Rank; `order_by` required, tie-break lists,
  fallback to a row-identity column `__sqlearn_rid__` (L44). Core: the data
  model needs a stable row identity; breadth: time-series area.
- `collapse-rare` (`OLD:ideas/collapse-rare.md:L36`): schema-preserving
  step that keeps categories with `min_count` and maps the rest to a
  sentinel; learned keep-set; NULL counts as a value. Breadth
  (preprocessing); also an example of a learned set that must be a relation.
- `group-by-hierarchical` (`OLD:ideas/group-by-hierarchical.md:L24`):
  per-group statistics falling back city to region to global when a group is
  small. Breadth; shows `group_by` as a first-class concept (inference: the
  core should allow per-group learned state).
- `federated-dtype-resolution` (`OLD:ideas/federated-dtype-resolution.md
  :L8`): `dtype=` when one pipeline reads several engines (Postgres,
  Snowflake, CSV). Only matters for the open multi-engine question; parked.
- `decimal-precision-mode` (`OLD:ideas/decimal-precision-mode.md:L8`):
  a Python arbitrary-precision runtime mode when `dtype="DECIMAL(...)"`;
  concluded `dtype=` is a CAST hint, no separate engine (L78). Precision:
  confirms "DuckDB DECIMAL is the engine's job"; the arbitrary-precision
  work belongs in the validation references (part 3.8).
- `mcp-server` (`OLD:ideas/mcp-server.md:L10`): MCP only after the product
  ships and demand shows; tools `profile/suggest/build/compile/apply/
  explain`. MCP: deferred, as in the new project (nothing committed).
- `plugin-architecture` (`OLD:ideas/plugin-architecture.md:L15`): build
  features in; third-party PyPI plugins only as a fallback with a stable
  extension contract. Plugins: do not design the extension surface early.
- `nlp-support` (`OLD:ideas/nlp-support.md:L10`): text features out of
  scope (not SQL-native except regex and counts). Breadth: a scope line to
  copy.
- `rust-hot-paths-post-v1` (`OLD:ideas/rust-hot-paths-post-v1.md:L18`):
  rewrite in Rust permanently rejected; PyO3 hot path only with profiling
  proof and demand. Rust: no case for it while DuckDB does the work.
- `gpu-post-v2` (`OLD:ideas/gpu-post-v2.md:L10`): CPU only; GPU (wgpu, MLX,
  Metal) maybe after v2. GPU: nothing to do; DuckDB is CPU.
- `post-v1-profiling-pass` (`OLD:ideas/post-v1-profiling-pass.md:L62`):
  what to measure once stable: Python compile overhead (sub-second for 30
  steps), the Python/backend/conversion split of apply time (targets: Python
  under 5%, backend over 90%, L87), a per-fold-cached cross-validation
  benchmark, validator cost; tools pyinstrument, line_profiler, scalene,
  py-spy, memray, pytest-benchmark (L333). Benchmarks (3.9): a ready list.
- `launch-strategy-and-marimo-wedge`
  (`OLD:ideas/launch-strategy-and-marimo-wedge.md:L39`): commercial and
  launch analysis. Four "walls" (memory, grid-search waste, deployment
  boundary, lazy-optimiser fragility); marimo as distribution channel;
  Pyodide-compatible as a design goal (L1970); notebooks as docs (L1984);
  canvas as a marimo widget before any standalone app (L2019); `pipe.python()`
  export to dependency-free Python (L697); elimination-first AutoML for Pro
  (L929); MCP agent integration for Pro (L1722); "zero data custodianship"
  (L1471); Ibis stalled on fit/apply (L1628); a 9-month estimate (L434).
  Relevance: launch strategy, editor (canvas), MCP, Pyodide/WASM; mostly
  contradicts the new shape (see Contradicts).
- `sqlearn-readme-draft` (`OLD:ideas/sqlearn-readme-draft.md:L88`): a
  combined public Free README and private Pro README; "What sqlearn is NOT"
  (L543), five principles (L1151), validation philosophy (L1057), pricing
  and licence-enforcement sections. Launch strategy; the "NOT" list is a
  useful model for a scope page.
- `rejected/design` (`OLD:ideas/rejected/design.md:L22`): Cython or Rust
  core rewrite rejected: Python is not the bottleneck, wheels per platform,
  Pyodide breaks, contributor barrier, debugging; real lever is better SQL
  (L107). Rust/performance.
- `rejected/design-adopted` (`OLD:ideas/rejected/design-adopted.md:L23`):
  two ideas closed because the v2 rewrite adopted them (constitution
  critique; domain validity and safe variants: error with three remedies, no
  silent swaps). Core: the "domain violation is an error with three ways
  out" rule.
- `rejected/docs-infra-portable-pattern`
  (`OLD:ideas/rejected/docs-infra-portable-pattern.md:L42`): a reusable skill
  that bootstraps a Postgres-backed keyword docs index plus MCP search in any
  repo. Process: the new repo already has a docs index (`qmd`, `mdindex`);
  note that the original plan was cut back the same day (`0c1756c`, "pivot to
  frontmatter-only schema; remove MCP/validator infra").
- `README.md`, `rejected/README.md`: folder rules (open ideas flat,
  rejected ones moved with a reason and a revisit trigger so they are not
  re-proposed). Process; see Worth keeping.

## Reports

All in `OLD:reports/archived/`; dates are the file dates.

- `2026-04-14-consolidate-grep-check` (L29): a plan check "grep returns zero
  hits" could not be ticked because the plan itself and a history note
  contain the string; the fix was a new anti-pattern section in the workflow
  skill. Failure of checklist-style validation.
- `2026-04-17-audit-standards` (L47): 16 standards audited; no splits; 11
  missing descriptions added; dead links to a `CONSTITUTION.md` that did not
  exist yet. A document set already out of step with itself, 8 days in.
- `2026-04-17-audit-protocols` (L77): 6 protocols audited; the "mirror gap"
  (skill copies promised for four protocols) was reframed as "a different
  repo's job". A gap closed by redefining it.
- `2026-04-19-cascade-audit` (L20): a validator now requires every document
  to declare `read_also:` reaching `CONSTITUTION.md`; initial state 71 files
  missing, 25 broken, 8 unreachable; 53 orphans left. Success measured as a
  structural property of documents, not of product.
- `2026-04-19-drainage-part18-close-step-contradiction` (L14): Part 18's
  "close" steps contradicted its own "mark done" footer; boxes left unticked
  by hand. Plans with checkboxes fight their own rules.
- `2026-04-19-context-baseline` (L21): `/context` snapshot, 38.2k of 1M
  tokens; memory files 12.3k (CLAUDE.md alone 10.2k); 70 MCP tools. The
  instruction file was the largest fixed cost.
- `2026-04-19-wave-2-delta` (L29): removing two user-level MCP servers saved
  an estimated 820-3,280 tokens; "categorical" estimate, not measured (L125).
- `2026-04-20-orchestration-dryrun` (L55): the commit-gate hook that forces
  rebuilt skills into the same commit as a standards edit passed 4 mock
  fires; end-to-end dispatch was untested because subagents cannot spawn
  subagents (L46). Tooling verified by itself.
- `2026-04-20-agent-tool-audit` (L81): all six agents had minimal tool
  lists; "no changes needed"; steps 4-9 of the plan took the "no commit"
  path. An audit that found nothing, as plan steps.
- `2026-04-20-main-orchestrator-classification` (L16): CLAUDE.md was 690
  lines; 9 sections stay, 2 move, 2 compress; target ~578 lines (L79).
- `2026-04-20-archival-design-investigation` (L29): why a finished plan is
  not archived automatically: the rule never named who archives; inferred
  from negative limits on two agents. A role gap found by an investigation
  report, fixed in two further plans (`a34e837`, `6f00e97`).
- `2026-04-21-distillation-v2-philosophy` (L1): staged-standards report for
  the v2 migration: 16 standards changed, 4 skills rebuilt, edge-case table
  8 to 10 rows, rule catalogue 23 to 20 entries.
- `2026-04-21-v2-standards-impact` (exec summary): 40 standards files: 2
  deleted, 1 moved to Pro, 5 shrunk, 9 rewritten, 11 minor edits, 12 intact.
- `2026-04-21-v2-arch-doc-impact` (exec summary): 38 files; 31 are empty
  stubs "blocked on drainage", 2 must be rewritten; Pro has only two stub
  READMEs.
- `2026-04-21-v2-process-ecosystem-impact` (exec summary): 64 files scanned,
  13 impacted (5 must-rewrite) across skills, agents, templates.
- `2026-04-21-v2-hidden-edges` (L49): the long tail: root docs, memories
  that carried now-wrong "cross-session decisions", `OVERVIEW.md` §8 a
  130-line walkthrough of a dead feature (L59-L70); no repo-level fixture
  proves old saved pipelines load (L695).
- `2026-04-21-v2-test-validation-impact` (L60): five test and validation
  edits in one 1,500-line `release-contract.md`; `projects/*/tests` and
  `validations` hold zero specs (stubs); pro-tier "auto-rewrite equals typed
  sibling" has no test home.
- `2026-04-21-v2-safety-tier-analysis` (exec summary): the three-tier
  framework (free, guarded, forbidden) cannot survive removal of `option=`;
  about 20 files reorganise.
- `2026-04-21-v2-synthesis` (L53): seven-commit migration plan, 14 actions,
  five risks, the largest being a claim about saved-pipeline compatibility
  that "cannot be verified from this repo" (L105-L110).

## History

593 commits by day: 9 Apr 15; 10 Apr 14; 11 Apr 33; 12 Apr 99; 13 Apr 61;
14 Apr 52; 15 Apr 2; 16 Apr 8; 17 Apr 58; 18 Apr 3; 19 Apr 100; 20 Apr 92;
21 Apr 46; 22 Apr 2; 23 Apr 6; 24 Apr 2. Two peaks (12 Apr; 19-20 Apr) and a
near stop on 15 and 18 Apr.

1. **9-10 Apr, scaffold (1816d09 to ac817bb, 29 commits).** Phased
   scaffolding plan with each phase ticked in its own commit (`079539f`,
   `6f88cd9`, `be9f428`...); ADRs 001-005 (`c229cc9`), v0.1 API spec
   (`781edfc`), open-core spec and ADRs 006-007 (`6d293ae`).
2. **11 Apr, ideas flood (1feb662 to 08c1965, 33).** About 20 idea commits
   (smart sampler, precision cascade, AutoML search, model knowledge base),
   elimination-first philosophy added to the vision (`d847b63`, `4117a0c`),
   "full evaluation of all 44 ideas" (`e714361`), feature matrix
   (`faa4136`), v0.3 spec and 12-phase plan (`108aa95`, `fafe72c`).
3. **12 Apr, restructure and v0.5 mining (c16f533 to 97017b3, 99).** The
   repo redefined as a "war room orchestrator" (`c16f533`), v0.4 marked
   shipped (`bf6580d`), a v0.5 spec set (`2ab29bc`), then 21 batches
   mining the old project into a "findings buffer" (`115a151` to `6da14d0`,
   about 25 commits), a second restructure to "documentation-only 2-project
   design" (`8e8cc95`, `7fe049e`), bulk move of everything into `_old/`
   (`be928b4`), and documentation of v0.1 to v0.4 APIs as hundreds of new
   files (`61cf9be`, `67a3019`, `3c385e9`, `72b3ad0`), then v0.5-v1.0
   "pillars" as architecture and test specs (`7485ef1` to `02e6b23`).
4. **13 Apr, draining and design (faea60d to 56bcc87, 61).** 13 more
   findings batches (`f98a2a4` to `4c4c764`); "drain" commits emptying
   `_old/` (`b61b53d` to `f3b0141`); open-core standard (`fff304d`),
   federated spec (`c529e98`), validation framework (`9fbb6f8`), the
   hardener super-agent (`6593f7a`), universal parameters and class
   hierarchy (`b81e80a`), constitution (`78e2bf1`), a feature-flag system
   (`551e333`) simplified to one `option=` within the day (`1cb4470`,
   `2692d97`, `6754f5e`), and the authoring Rule 0 catalogue (`56bcc87`).
5. **14 Apr, brainstorm closure and rewrite (93dbab2 to 8f88edc, 52).**
   Themes A to H of the brainstorm resolved one commit each (`93dbab2` to
   `392cea1`), documentation strategy (`4e0ca07`), then "chore(rewrite)":
   park everything to `_old/`, import the old Python project as
   `_old_sqlearn/` (`241a23b`, `a43ce53`), force-loaded workflow skill
   (`ec70728`), tag `prep-complete` (`0fd4ef7`), four small plans that each
   were written, executed and archived (drain-standards, consolidate
   templates, prevent grep footgun), and a 15-phase drainage roadmap
   (`8f88edc`).
6. **15-16 Apr, strategy writing (a6acd82 to b7e8b28, 10).** Launch
   strategy (`a6acd82`), README draft (`fce5051`), one-file overview
   (`5034de6`), Cython rejected (`7d7e954`), profiling plan (`3cb1902`), a
   docs-infrastructure-plus-MCP plan with a Postgres backend (`59f1a2e`,
   `9a08b43`) amended twice.
7. **17 Apr, tooling and re-splitting (e52c69f to 25c4446, 58).**
   Standards split into standards plus protocols (`016648b`, `91b2ccf`,
   `1ce0c45`), a template validator with hooks (`e1f5ec9`, `0ed6b78`),
   then the Postgres/MCP idea dropped for "frontmatter-only schema"
   (`0c1756c`), a drain-function agent written and rescoped (`4691ff5`,
   `d854db5`), protocols converted to "recipes" (`f6857f4`), a commit whose
   subject is a warning (`baec18c`, "This diff is not atomic").
8. **18-19 Apr, standards drainage (c0c2b0f to 97f1a37, 103).** A 19-part
   plan: archive standards to `_old_standards` (`3d8d228`), then Parts 1-19
   each as a "start" and a "close" plan commit plus one content commit
   (`131a7ff` to `d3e1f18`); cascade validator and pre-commit hook
   (`d3e1f18`, `31bb11a`); an immediate "verification wave" that found zero
   gaps (`9bea5ac` to `1214929`); `_old_standards` removed (`e4d3f54`).
9. **19-20 Apr, context and infrastructure waves (eb92905 to 8de91d0,
   about 90).** Wave 1-10 sub-plans (`eb92905` to `3f1968a`): measure
   context cost, evict MCP servers, add session-end skill-audit hook
   (`aa0491a`), rename every INDEX to README (`3d1d685`), structural-edit
   reminders (`a6eccaf`), drop the docs-maintenance skill just built
   (`7e39347`), demote the parallel-read rule to advisory (`43b0fe0`),
   release-system shape (`f3fd23d`), then 20 Apr: protocols mirrored to
   `.claude/` (`e85243e`), `release-contract.md` absorbs four standards
   (`c8e3d2b`, `1848503`), three skills and a memory hook installed, a
   five-agent orchestration pipeline plus commit gate (`d0d883a` to
   `dd20a9b`), a main-orchestrator skill (`c23a718` to `67fa2f6`).
10. **20-21 Apr, process on process (ec6ece0 to 3fa8423, about 45).**
    Plans to codify who archives (`23745e9`), an "N/A" marker for boxes
    never to be ticked (`6f00e97`), a fix to the pre-commit validator's
    archive filter with smoke fixtures added and removed (`4d8a566`,
    `31066e3`).
11. **21-22 Apr, v2 philosophy (619ab2a to bcea2af, 14).** `safety-tiers.md`
    extracted (`2c12125`), then rationale corpus (`619ab2a`), impact reports
    (`3b6b569`), a multi-part plan (`87d8f4a`), `settings.md` deleted
    (`16e978c`), migration applied in one commit (`462b2fc`) and shipped
    (`1b88197`).
12. **23-24 Apr, teardown (7b9d8f9 to 055eef0, 8).** "Teardown pipeline
    enforcement and obsolete scaffolding" (`7b9d8f9`), `OVERVIEW.md` deleted
    (`aae95c7`), protocols, agents, memories and changelog removed
    (`99a8cd6`), "RULE 0 - read files completely" (`f375faa`), then two
    promotions from `_old_standards/raw/` (`16115b0`, `1416b6d`).

What the spending shows (*inference* from subjects): the same material was
moved, split or re-homed repeatedly: standards were drained from `_old/`
(14 Apr), archived to `_old_standards` (19 Apr), drained again (19 Apr),
absorbed into `release-contract.md` (20 Apr), shrunk again (21 Apr), and
re-promoted from the buffer (23-24 Apr). Templates were consolidated on
14 Apr and re-made per type on 17 Apr. The `INDEX.md` convention was
renamed to `README.md` on 19 Apr (`3d1d685`) after an index refresh on 12
Apr (`e6872f6`). No commit adds a transformer.

## Standards and templates

`OLD:_old_standards/raw/` (25 files, the 19 Apr drain, re-archived 23 Apr)
and `OLD:_old_templates/raw/` (26 templates). What each is:

- `README.md`: folder index (L1-L60), roles for 17 files plus an inline
  "chain-reaction procedure" every agent must run on edit.
- `authoring.md` (1,000+ lines): Rule 0, a catalogue of 23 mandatory
  questions per function (`OLD:_old_standards/raw/authoring.md:L98`), later
  20; options matrix; nine transformer rules; per-surface sections for
  helpers, compilers, validators. The most elaborate and the most ceremony.
- `release-contract.md` (1,800+ lines, `L60-L1828`): commits, linting,
  formatting, typing, testing (three "waves"), validation, waivers, Python
  and Svelte rules. Four earlier standards merged into one.
- `cross-fit.md` (`L24`): `cv=K` cross-fitted imputation, `.help()` bundled
  docs, `target_model=` static compatibility table (~20 model families:
  needs scaling, handles nulls, handles categoricals; L238).
- `config-api.md`, `documentation.md`, `documentation-strategy.md`:
  verbosity levels and first-use messages; docstring rules; an eight-layer
  site plan (Svelte). Superseded in scope by the new project's ADRs.
- `transformers/` (18 files): 17 families each with a fixed layout (what it
  does, default, parameters, universal-parameter behaviour, worked
  examples). Real content for scaler, imputer, encoder, binner, arithmetic,
  outlier, datetime, string, interaction, composition, row_op, escape_hatch,
  target_transform; `window`, `aggregator`, `lookup`, `column_op` are stubs
  "reserved for v0.7+/v0.9+". The README holds a family-by-parameter matrix
  (L133) that the v2 report called per-cell judgment work.
- Templates (26): `_meta.md` (a frontmatter contract: `docs_type`,
  `description`, `read_also` required on every file), per-type templates
  for plan, report, idea, standard, skill, agent, recipe, release, version,
  test-spec, validator-spec, function-arch, memory, todo/conversation
  entries, `tldr`, `orient`, `changelog`, `readme`, `root-doc`, `index-file`,
  `intake-form`, `template`, `INDEX`, and `drain-function-plan` (a plan type
  for one agent).
- `.claude/` (4 files): `settings.json` is `{}`; `settings.local.json` is a
  7 KB permission allowlist (skimmed, nothing copied); skills
  `sqlearn-workflow` (a 700-line task cycle: conversation, todo, plan,
  execute, report, archive; section 6.3 five plan-validation anti-patterns)
  and `idea-triage` (a feature lifecycle: capture, park, promote, ship,
  reject).

Worth carrying over from the standards: the validation method (arbitrary
precision canonical from a primary source, tolerance classes in ULPs, a
written waiver paragraph per waived function:
`release-contract.md:L813`, `L1306`), the `.help()` idea (docs bundled with
the installed package, no network), `target_model=` as a data table, and the
fixed layout of a "family" page. The rest (Rule 0 catalogue, cascade rules,
recipe mirrors, template zoo) is process for a docs-only repo.

## New against the baseline

- **A written fit/apply argument** that is wrong for DuckDB. The Ibis
  section (`ideas/launch-strategy-and-marimo-wedge.md:L1628-L1690`) says a
  fused single query "breaks" for training statistics applied to new data,
  so statistics must be collected and baked in as literals. The baseline
  checked that a staged `WITH` fit works and that learned state can be a
  relation. This is the origin of the "literals only" assumption (*inference*
  that it never considered statistics as a joined relation).
- **Null-preserving default** (v2 Group 2): a step never drops rows silently;
  statistics fit on non-null values; dropping is an explicit step or flag
  (`OLD:reports/archived/2026-04-21-v2-test-validation-impact.md:L74`).
- **Domain violations are errors with three remedies**, not warnings or
  silent swaps: use the signed sibling class, pass a per-trigger keyword, or
  filter upstream (`ideas/rejected/design-adopted.md:L68-L83`).
- **Determinism rule**: expressions that call `RANDOM`, `NOW`, `UUID` are
  rejected at construction (`_old_standards/raw/transformers/row_op.md`
  description; `escape_hatch.md`).
- **Fold assignment is deterministic** from `cv` and a hash of the input
  (`_old_standards/raw/cross-fit.md:L87`), saved with the pipeline.
- **A static table of downstream-model needs** (`target_model=`).
- **`pipe.python()` idea**: export a fitted pipeline as dependency-free
  Python, aimed at serving, Pyodide and air-gapped targets
  (`launch-strategy...md:L697`). Related to the baseline's "serialise graph".
- **Pyodide/WASM as a design constraint**, including DuckDB WASM
  (`launch-strategy...md:L1970`). Not in the baseline; ties to the open
  front-end question.
- **A measurement habit for tooling cost**: `/context` before and after
  (`reports/archived/2026-04-19-context-baseline.md`).
- **Rejected-idea registry with revisit triggers** (`ideas/rejected/README
  .md:L8`).
- **Elimination-first AutoML** (choose models by data properties and give
  reasons; `launch-strategy...md:L972`): relevant only for a later models
  area (3.3), not for the core.
- **A concrete failure of "checkbox plans"**: self-contradicting close steps
  and unticked boxes (`2026-04-19-drainage-part18-...:L14`).

## Contradicts the baseline

- "Learned state as a relation" and "a staged fit can be one query": the
  source asserts literals are the only portable form
  (`ideas/sqlearn-readme-draft.md:L965-L990`: "no placeholders, no UDFs").
  Different goal (portable to any dialect) from the new project's (DuckDB).
- "Multi-engine is an open question": here it is the identity ("Portable to
  any SQL dialect", L990; Postgres, Snowflake, BigQuery rows in L94 and
  L179). The new ADR 0002 makes DuckDB the engine.
- "Tomosius/sqlearn and the later attempts kept scikit-learn names": this
  repo's API uses `learn`/`apply`, `sq.Scale`, `target_column` (renamed from
  `y_column`, `8c908db`). Agrees with v0.4, against ADR 0003.
- Licence: MIT with a proprietary Pro tier
  (`ideas/sqlearn-readme-draft.md:L1344`, L2189) against ADR 0004 (Apache-2.0,
  paid things as separate packages). Hosted-execution and enterprise
  licence-enforcement sections are outside ADR 0006's spirit only in tone;
  the "no hosted execution, local first" constraints (L1843-L1860) agree.
- Scope: preprocessing only, "does NOT train models" (README draft L549),
  no GUI in the free library (L590), "does NOT replace pandas for
  exploration" (L576). The new overview agrees to models (3.3), an EDA app
  (3.6) and a node editor (3.7).
- Dependency: DuckDB hard versus optional is left open
  (`launch-strategy...md:L2403`) against ADR 0005 (duckdb required).
- Rust and Cython: rejected for the core, allowed in Pro hot paths
  (`rejected/design.md:L69`); the new project has not ruled Rust in or out.
- The reports contradict "plans, standards, skills outgrew the product" only
  in one respect: here the plan was *deliberately* documentation-only, so
  the product could not be late (it was absent).

## Confirms the baseline

- **Process**: bursts then near stops (12 Apr 99 commits, 15 Apr 2, 18 Apr 3,
  19 Apr 100); plans, standards, skills and tooling outgrew the product
  (the whole log); status kept by hand and drifting (the 91 tick commits,
  the Part 18 contradiction, `2026-04-14-consolidate-grep-check`); a review
  sweep after the burst found real problems every time (the 17 Apr audits,
  the v2 impact reports).
- **Docs with hand-typed numbers were wrong**: the README draft's example
  output and fitted state are hand-written (`:L245-L282`); `CLAUDE.md`
  line counts and the "23 entries" catalogue shifted to 20 in the v2 report
  within two days; the impact reports count files that other reports count
  differently (`v2-synthesis.md:L162-L276`).
- **Learned state failures**: `median_income__median` style keys with `__`
  (`ideas/sqlearn-readme-draft.md:L245`); inlined literals with an
  `equivalent` string for the SQL (L255-L282).
- **Fit defect**: the README example fits `Impute` and `Scale` of one
  column in one pass (median and mean together) and applies
  `(median_income_imputed - 3.97) / 1.89` (L260-L266); the mean 3.97 is
  plausibly the raw-column mean (*inference*, the draft does not say).
- **sqlglot everywhere**: expression API converges on `sqlglot.exp`
  (`python-expression-dsl.md:L22`); dialect-correct CAST via sqlglot
  (`federated-dtype-resolution.md:L29`).
- **Validation method strong, never enforced**: "arbitrary precision
  canonical", ULP tolerance classes, mandatory waiver paragraph
  (`release-contract.md:L813`); yet validations were README stubs on
  21 Apr (`v2-test-validation-impact.md:L63`). No whole-pipeline comparison
  with scikit-learn: the README draft says it "does NOT guarantee numerical
  identity with sklearn" (L639).
- **`y` as a column name** (`pipe.learn(data, target="churn")`,
  `_old_standards/raw/cross-fit.md:L222`).
- **Bridge back to scikit-learn after a rename**: `as_sklearn()` parked
  (`ideas/sklearn-compat-adapter.md:L6`).
- **Offline and local**: "no hosted execution", "local-first", zero data
  custodianship (README draft L1843-L1876) agree with ADR 0006.
- **Python is not the bottleneck; the work is in the engine**
  (`rejected/design.md:L35`), which supports ADR 0002.

## Worth keeping

1. The **ideas lifecycle in miniature**: one short file per idea with a
   "why parked" and a numbered "trigger to revisit"; rejected ideas kept
   with the reason so they are not re-proposed (`ideas/README.md`,
   `rejected/README.md`). Far smaller than the TBC/IDX system built around
   it.
2. **Plan-check anti-patterns** (`.claude/skills/sqlearn-workflow/SKILL.md
   :L248-L335`): no repo-wide "zero hits" greps; no "all tests pass"; name a
   command and an exit code; no "nobody will miss X".
3. **Null-preserve default, three-remedy domain errors, determinism rule,
   deterministic fold assignment**, as candidate core rules for the library
   spec.
4. **Validation method** and the **waiver paragraph** (already in overview
   3.8): formula from a primary source, exact reference, per-library error
   table, written reason for each waiver.
5. **The profiling targets and tool list** (`post-v1-profiling-pass.md
   :L58-L343`) for part 3.9: Python under 5% of apply time, compile under
   1 s for 30 steps, grid-search benchmark with per-fold cached statistics.
6. **`target_model=` knowledge table** and **bundled `.help()`**, as later
   breadth items.
7. **Context-cost measurement** before adding agents, hooks and skills.
8. **The "What X is NOT" page** as a scope document (README draft L543-L657).
9. **`window-functions` parameter contract** (order required, tie-break
   list, stable row identity) when the time-series area starts.
10. **Pyodide/WASM question**: whether the library and the front end can
    run in a browser; feed it into `docs/questions/application-front-end.md`
    (*suggestion*).

## Guard against

- **Process outgrowing the product.** 593 commits, no library. Rule of
  thumb for the new workflow: no new agent, skill, hook, template or index
  without a recurring need already seen twice (agrees with the workflow
  page's proposed rule, `docs/architecture/workflow.md`).
- **Status in many places.** Plan checkboxes, `TODO.md`, `CONVERSATION.md`,
  `MEMORIES.md`, `CHANGELOG.md`, `MAP.md`, indexes, frontmatter `status:`.
  The new project keeps status in one place (the plan page) and issues.
- **Checkbox plans that need their own plans.** The archival role, the
  `[N/A]` marker and the archive-filter fix each became a plan
  (`23745e9`, `6f00e97`, `af0d89d`). Prefer short plans with command-based
  checks.
- **Rewrites of philosophy after documents are drafted at scale.** v2 hit
  about 80 files (`v2-synthesis.md:L63`). Decide the contested rules (null
  handling, domain errors, tiers) in the spec before writing standards.
- **Documentation for features that do not exist.** The "documented v0.1
  to v0.4 API" commits (`61cf9be`..`72b3ad0`) added hundreds of files and
  were all moved aside or deleted within days.
- **Duplicate trees** (`protocols/` mirrored in `.claude/`, byte-identical
  copies audited by a report, `2026-04-20-agent-tool-audit.md:L65`).
- **Instruction files that grow.** `CLAUDE.md` reached 690 lines and was
  the largest fixed context cost (`2026-04-19-context-baseline`,
  `2026-04-20-main-orchestrator-classification`). Keep the root file short
  and measure it.
- **Audits whose result is "no change".** Not every step needs a report
  (`2026-04-20-agent-tool-audit.md:L81`).
- **Unmeasured estimates.** The 8-12 week estimate to a v1.0 ("635 hours",
  `launch-strategy...md:L462`) was written on day 6 from document output;
  15 days later there was no code (*inference*).
- **Tooling verifying itself.** Hooks tested by mock-fires, validators
  that check that documents link to a constitution, a verification wave
  that checks the drain just made. None test the product.
- **Agents that skim.** The repo's last meaningful addition was a rule to
  read files completely (`f375faa`). Keep the "read in full" instruction
  in briefs, as this batch's brief does.
- **A strategy file standing in for a decision.** The launch strategy
  document is described as "guidance, not a plan" (L26) and its "CV floor,
  money upside" section (L2349) shows the project's goals shifting between
  product, portfolio and business; settle goals in ADRs, not essays.
- **Fixed reading-order cascades.** `read_also:` reaching one root document
  from every file made every edit expensive; the rule was demoted to
  "advisory" within a day (`43b0fe0`).

## Files covered

Legend: [x] read in full (or all but formatting); [~] skimmed or read by
section.

### OLD/ideas/ (17 + 4)

- [x] `ideas/README.md`: folder rules, open versus rejected.
- [x] `ideas/sklearn-compat-adapter.md`: `as_sklearn()` parked.
- [x] `ideas/plugin-architecture.md`: plugin fallback only.
- [x] `ideas/nlp-support.md`: text out of scope.
- [x] `ideas/federated-dtype-resolution.md`: cross-engine `dtype=` policy.
- [~] `ideas/sqlearn-readme-draft.md`: 2,192 lines; read headings, intro,
  fit/apply, validation, constraints, "NOT" list, tail.
- [~] `ideas/post-v1-profiling-pass.md`: read first 120 and last 100
  lines, tool matrix; middle (tool recommendations) skipped.
- [x] `ideas/window-functions.md`: window family and `order_by`.
- [x] `ideas/mcp-server.md`: MCP deferred.
- [x] `ideas/multi-output-rename.md`: list-valued `out_column`.
- [x] `ideas/rust-hot-paths-post-v1.md`: Rust only with evidence.
- [x] `ideas/python-expression-dsl.md`: `col()` predicates parked.
- [x] `ideas/decimal-precision-mode.md`: CAST hint, no engine.
- [x] `ideas/collapse-rare.md`: rare-category collapse.
- [x] `ideas/group-by-hierarchical.md`: hierarchical fallback.
- [~] `ideas/launch-strategy-and-marimo-wedge.md`: 2,594 lines; read TL;DR,
  timeline, python export, elimination/Ibis, MCP, tactical plays, phases,
  concerns, revisit list; competitor profiles and changelog skipped.
- [x] `ideas/gpu-post-v2.md`: GPU maybe later.
- [x] `ideas/rejected/README.md`: rejection categories.
- [x] `ideas/rejected/design-adopted.md`: two ideas absorbed by v2.
- [~] `ideas/rejected/docs-infra-portable-pattern.md`: first 100 of ~300
  lines (pitch and transferable table).
- [x] `ideas/rejected/design.md`: Cython/Rust rejection.

### OLD/reports/archived/ (19)

- [x] `2026-04-14-consolidate-grep-check.md`: zero-hits check unfulfillable.
- [x] `2026-04-17-audit-protocols.md`: protocols audit, mirror reframed.
- [x] `2026-04-17-audit-standards.md`: standards audit, links fixed.
- [~] `2026-04-19-cascade-audit.md`: first 127 lines (validator, passes).
- [~] `2026-04-19-context-baseline.md`: first 120 lines (token counts).
- [~] `2026-04-19-wave-2-delta.md`: first 140 lines.
- [x] `2026-04-19-drainage-part18-close-step-contradiction.md`: plan
  contradiction.
- [~] `2026-04-20-archival-design-investigation.md`: first 108 lines.
- [~] `2026-04-20-orchestration-dryrun.md`: first 115 lines.
- [x] `2026-04-20-agent-tool-audit.md`: six agents, no change.
- [~] `2026-04-20-main-orchestrator-classification.md`: table and
  projection read.
- [~] `2026-04-21-distillation-v2-philosophy.md`: first 190 lines.
- [~] `2026-04-21-v2-synthesis.md`: first 300 of ~900 lines.
- [~] `2026-04-21-v2-standards-impact.md`: executive summary and top of
  table.
- [~] `2026-04-21-v2-arch-doc-impact.md`: executive summary.
- [~] `2026-04-21-v2-process-ecosystem-impact.md`: executive summary.
- [~] `2026-04-21-v2-hidden-edges.md`: headings and executive summary.
- [~] `2026-04-21-v2-test-validation-impact.md`: headings, executive
  summary.
- [~] `2026-04-21-v2-safety-tier-analysis.md`: executive summary.

### OLD/_old_standards/raw/ (25)

- [~] `README.md`: first 60 lines (index and roles).
- [~] `authoring.md`: headings plus Rule 0 opening.
- [~] `config-api.md`: headings only.
- [~] `cross-fit.md`: first 285 lines read; tail skipped.
- [~] `documentation.md`: headings only.
- [~] `documentation-strategy.md`: headings only.
- [~] `release-contract.md`: headings, testing and validation openings,
  waivers.
- [~] `transformers/README.md`: description and headings.
- [~] `transformers/imputer.md`: description and headings.
- [~] `transformers/scaler.md`: description and headings.
- [~] `transformers/escape_hatch.md`: description and headings.
- [~] `transformers/target_transform.md`: description and headings.
- [~] `transformers/window.md`: description and headings (stub).
- [~] `transformers/aggregator.md`: description and headings (stub).
- [~] `transformers/lookup.md`: description and headings (stub).
- [~] `transformers/column_op.md`: description and headings (stub).
- [~] `transformers/row_op.md`: description and headings.
- [~] `transformers/composition.md`: description and headings.
- [~] `transformers/binner.md`: not opened; size only, plus the v2 impact
  table.
- [~] `transformers/string.md`: not opened; size only, plus the v2 impact
  table.
- [~] `transformers/datetime.md`: not opened; size only, plus the v2 impact
  table.
- [~] `transformers/outlier.md`: not opened; size only, plus the v2 impact
  table.
- [~] `transformers/interaction.md`: not opened; size only, plus the v2
  impact table.
- [~] `transformers/arithmetic.md`: not opened; size only, plus the v2
  impact table.
- [~] `transformers/encoder.md`: not opened; size only, plus the v2 impact
  table.

### OLD/_old_templates/raw/ (26)

All skimmed by `description:` line; `_meta.md` (first 50 lines),
`drain-function-plan.md` (first 60 lines) and `function-arch.md` (headings)
read further. None is worth keeping beyond the idea of a minimal frontmatter.

- [~] `INDEX.md`, [~] `_meta.md`, [~] `agent.md`, [~] `changelog.md`,
  [~] `conversation-entry.md`, [~] `drain-function-plan.md`,
  [~] `function-arch.md`, [~] `idea.md`, [~] `index-file.md`,
  [~] `intake-form.md`, [~] `memory.md`, [~] `orient.md`, [~] `plan.md`,
  [~] `readme.md`, [~] `recipe.md`, [~] `release.md`, [~] `report.md`,
  [~] `root-doc.md`, [~] `skill.md`, [~] `standard.md`, [~] `template.md`,
  [~] `test-spec.md`, [~] `tldr.md`, [~] `todo-entry.md`,
  [~] `validator-spec.md`, [~] `version.md`.

### OLD/.claude/ (4)

- [x] `.claude/settings.json`: `{}`.
- [~] `.claude/settings.local.json`: permission allowlist; matched lines
  only; nothing copied.
- [~] `.claude/skills/sqlearn-workflow/SKILL.md`: headings, section 6.3,
  self-improvement.
- [~] `.claude/skills/idea-triage/SKILL.md`: first 60 lines, headings.

### History (1)

- [x] `private-april-git-log.txt`: all 593 lines (short sha, date, subject).
