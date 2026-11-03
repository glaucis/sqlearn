---
type: note
tags: [war-room, rules, process, design-review, sqlearn]
summary: "Batch E review of the sqlearn war room's rules, ideas and process: which rules to keep or drop, revisions, and process lessons for the new project."
related: [rules/errors.md, rules/revisions/step-composability.md, rules/revisions/, "OLD:rules/errors.md", "OLD:.claude/settings.json:L9", "OLD:scripts/check-spec-refs.py:L11-14", "OLD:handoff.md:L27", "OLD:TODO.md:L87-100"]
mdindex: [type=edb465, tags=12e9ce, summary=1096a6, related=2c88ee]
---
# E. Rules, ideas and process (war room, 26 April - 13 June 2026)

Batch E of the war room (`glaucis/sqlearn-private`, 410 commits). OLD is
`sqlearn-ecosystem/sqlearn-private` under ROOT. Citations are `OLD:path:Lnn`
or short shas; "(inference)" marks my reading, not a quoted fact. Everything
was read-only. `OLD/.claude/settings.local.json` was not opened (it may hold
local permissions or tokens); only its size was listed.

## Summary

- The war room produced 410 commits and no library code. 115 commits touch
  specs, 78 are `docs(todo)`, 119 are process machinery (TODO, skill, agents,
  handoff, checker) and about 63 mention a sweep, cleanup or drift fix. Of
  the 410, one is a revert. It is the same shape as the April planning repo
  (593 commits, no code): the product was documented, never built.
- The rules are an extraordinary amount of text: 32 files, `errors.md` alone
  2,200 lines (`OLD:rules/errors.md`). Most are specific to an open-core,
  multi-repo, multi-dialect product that the new project is not. A small
  core is worth carrying: honest names, teaching errors, explicit defaults,
  JSON-not-pickle with a round-trip test, ULP-based expected precision, a
  loosening-needs-a-reason rule, deterministic reference checks.
- Revisions show design locked too early and amended within days: the
  output-naming parameter was renamed twice on 1 May, `out=` became
  `output=`, a "data flows through verbs only" lock was scoped down two days
  later, and a "flat tests" layout was reversed after one release plan. The
  loosening-paragraph rule worked as designed but four of the eight revision
  files record a loosening, so it did not slow churn.
- Process outgrew product again. A 42 KB orchestrator skill is cat-ed at
  every session start (`OLD:.claude/settings.json:L9`); ten narrow agents,
  nine of them on the top model; an 80 KB `TODO.md`; a handoff command; six
  rounds of LLM cross-reference "verifier" passes that never converged, which
  ended in a deterministic checker script (`40d02de`, 7 June).
- The one process idea that clearly paid: when drift is a deterministic
  property, check it with a script, not with agents. `check-spec-refs.py`
  said so itself (`OLD:scripts/check-spec-refs.py:L11-14`).
- Ideas that bear on the core: parameterise steps by aggregates rather than
  one class per variant; step decomposition into composites; the 9-mode
  output enum and lazy modes; fold-id columns for cross-validation; engine
  and version dispatch; search engines. Pro, canvas, pricing, GPU, Rust,
  dbt and distributed ideas are product strategy and out of scope.
- New against the baseline: a primary-key invariant column injected at every
  entry; a `natives` per-dialect dispatch table; a warnings subsystem; a
  gettext layer at v0.1.0; and the fold design in `sq-search-engines` Mode A
  (see "Contradicts").
- Contradicts the baseline: the search idea runs each fold by filtering one
  already-learned apply query, i.e. statistics learned on all rows; the
  baseline's per-fold `FILTER (WHERE fold != k)` design is the opposite
  (inference, see below). The rules also treat sqlglot-based multi-dialect
  support as a v0.1.0 goal after the baseline found it never tested.
- Work stopped on 13 June because the session ended ("will start fresh
  session", `OLD:handoff.md:L27`), with 8 commits unpushed and no focus row
  (`OLD:handoff.md:L18`, `L31`); `TODO.md` shows a search-engine arc started
  on 24 June and never committed (`OLD:TODO.md:L87-100`). No decision to stop
  is written down. The August `sql_learn` restarts follow; this batch does
  not read them.
- The new workflow should guard against: documents as the main output,
  status held by hand in many places, specs that outrun code, rules that
  need an agent to enforce, and agent fan-out used as a substitute for a
  checker.

## Rules

One line each: rule (file), keep or drop, why. "Keep" means carry the idea, not
the file. Sources are `OLD:rules/<file>` read in full unless marked skimmed.

- `README.md` (index of 20 rules): drop. An index of rules; the new project
  has ADRs and `docs/architecture/`.
- `document-revisions.md`: keep the idea. Tightening is free, loosening needs
  a written paragraph, no retroactive application (`L6-23`). The new ADR
  process covers it; the separate `rules/revisions/` folder is drop (git and
  ADRs hold history).
- `versioning.md` (semver per project, release `type:`): drop. Release files
  and `affects_projects` frontmatter are a multi-repo device; its own open
  questions are unanswered (`L35-40`).
- `ecosystem-constraints.md`: keep #1 and #2 (data stays local, local-first);
  they restate ADR 0006. Constraint #3 (MIT, Python not required, "wholesale
  port" allowed, `L16-21`) is open-core framing; drop.
- `sqlearn-principles.md`: keep 1 to 5 (allow what the user asks, explicit
  errors, same call means same meaning, docs are the contract, honest names),
  the "undocumented defaults" ban including structured defaults (`L125-133`),
  and "NULL is a value" (`L143-149`). Drop 6 and 7 as written: "implementation
  complexity is cheap" and "do not cut corners" (`L79-103`) are the license
  that grew `errors.md` to 2,200 lines (inference).
- `sqlearn-api.md` ("everything is a Step", three execution modes): keep the
  vocabulary as one candidate for the core's step contract; drop the Join /
  Union / PK / data-reference clauses (`L57-167`), which belong to a later
  part.
- `sqlearn-tiers.md` (free is the product; pro is a coding agent; same data
  output in both): drop. Open-core is not in ADR scope. Skimmed.
- `content-boundary.md` (private war room versus public repos, a grep leak
  check): drop. The new repo is single and public-shaped; the one-way-door
  idea (public to private is easy, private to public is not) is worth a
  sentence if the repository ever holds private notes. Skimmed.
- `non-goals.md`: keep the format, drop most rows. A short table of firm
  rejections (hosted execution, real-time scoring, online learning, model
  training, engine-knob wrapping) makes triage a lookup (`L1-30`, rows
  1 to 7). Rows 3 and 5 are good candidates for the new overview. Skimmed.
- `naming.md`: keep "names follow English grammar", folders plural and classes
  singular, modifier-before-base (`SignedLog`), canonical parameter names;
  drop the cross-project hyphen rules. Note ADR 0010 already fixes spelling.
  Skimmed.
- `parameter-shapes.md` (collection, role, map, structural): keep. A compact
  rule that decides when a scalar means a list; it needed two documented
  exceptions within five weeks (`new_column=`, `where=` and friends,
  `OLD:rules/revisions/step-composability.md:L3-30`), so keep it as guidance
  with the exceptions listed, not as law. Skimmed.
- `api-checklist.md` (one page to run before any new public name): keep the
  idea as a short PR checklist, adapted to ADR 0003 (it forbids
  `random_state`, `X`, which ADR 0003 may want). Skimmed.
- `siblings.md` (every restricted-domain step ships its full-domain sibling
  in the same PR): keep as an idea for transforms only (`Log` and
  `SignedLog`); the cohort bureaucracy (drain together, versioned together)
  is drop. Skimmed.
- `errors.md` (message template, `to_dict()`, taxonomy, "three routes
  forward"): keep the template and `to_dict()`; drop "exactly three routes
  every time" (`L18-40`) as a mechanical rule, since some errors have one
  honest fix; drop the 2,000-line class taxonomy (IO, pipeline-construction,
  connection, adapter) written before any code existed. Skimmed by
  headings.
- `warnings.md` (class naming, severity ladder, `doc_url`, `code` dot.path):
  drop for now; the hierarchy and display API (`core/warnings.md`) were
  designed with no emitter. Reconsider when the first real warning exists.
  Skimmed.
- `i18n.md` (every user string in `_()` from v0.1.0, gettext, `.pot`
  regenerated in each PR): drop. A merge-gate on `.pot` files for a library
  with no users; it cost a 9-agent audit and 20+ commits on 2 May
  (inference from the log, `3395cc4`..`6d14688`). Revisit after release.
- `serialization.md`: keep. JSON not pickle, load is a pure function, static
  class names, round-trip test, add-field-is-free and remove-field-is-
  forbidden (`L26-60`, `L94-110`). It matches the baseline's finding that
  `Tomosius/sqlearn` pickled and v0.4 used JSON. The 3-release rename cycle
  is drop pre-1.0. The cross-tier clauses are drop.
- `validation.md`: keep the principle, not the machinery. Expected precision
  is derived from the operation (0 ULP for counts, ~1 ULP for `log`, document
  the variance algorithm; `L95-123`), references come from primary sources,
  and a step that needs no validator says "Not applicable" (`L57-73`). Drop
  the per-dialect polyfill validation matrix and the upstream-reporting
  mission. It still compares one step at a time to a library, never a whole
  pipeline (inference from the sections read).
- `benchmarks.md`: drop. A stub (`L5-9`), "activates at 5 validated steps".
- `coding.md` (strictest tools per language, source markers `# CHANGED:` and
  `# GOTCHA:`, test file size band, security): keep "max strict by default,
  suppression names its reason" (`L14-35`), mirror-source test layout and the
  400 to 500 line band (`L214-292`), the secrets and trust-model sections.
  Drop `# CHANGED:` markers (history belongs in git; a marker that must not
  be removed in the same commit is process for its own sake, `L130-176`) and
  everything TypeScript, Svelte, CSS, accessibility. Keep `# GOTCHA:`.
- `release-gate.md`: keep the "no warning tier: every check blocks or is not
  in the gate" idea (`L114-121`) and "a suppression needs a recorded reason
  after the second occurrence" (`L132-137`). The new `just verify` already is
  this gate. Drop the i18n, accessibility, cross-project and content-boundary
  rows.
- `deprecation.md` (two-minor window, migration guide): drop pre-1.0; the
  mechanics are fine later. Skimmed.
- `connection-management.md` (a connection arrives only inside `data`; the
  caller owns the lifecycle; sqlearn never closes it): keep as one candidate
  rule for the later IO design (`L1-30`); the error taxonomy is drop. Skimmed.
- `version-handling.md` (detect the engine's version attribute-first,
  user can pin when detection fails): keep as an idea for later; do not
  confuse with release semver (`L14-30`, the file says so itself). Skimmed.

Revisions folder: `rules/revisions/*.md` (8 files); see next section.

## Rule revisions

Eight files, 11 dated entries. What changed and why, in one line each.

- `ecosystem-constraints` 2026-04-27: "pure Python and MIT" loosened to
  "MIT, other languages allowed", because the real intent was to forbid a
  paywalled rewrite, not native acceleration (`OLD:rules/revisions/ecosystem-
  constraints.md:L3-12`). Friction: none; a one-day correction.
- `naming` 2026-04-29: test layout flat to mirror-source. v0.1.0 had 21+ test
  files and "flat is fine at 10, hostile past 20" (`revisions/naming.md:L15-
  22`). Cause: the first rule assumed a small `src/`.
- `naming` 2026-05-04: `sq.sql()` allowed as a data helper, carved out of a
  "no function names that match an output mode" rule. A new feature (Q-IO-2)
  collided with a naming rule written a week earlier.
- `step` 2026-05-01 (two entries): `out_column=` renamed `new_column=` and,
  the same day, widened from a string to a string or list, to remove a
  step-specific `out_columns=` dict on one encoder (`revisions/step.md:L3-46`).
  The earlier "use selectors and separate steps" rule pushed boilerplate onto
  users. Two renames in one day.
- `api-surface` 2026-05-01: `out=` renamed `output=` (collided visually with
  `out_column=`) and a "run-now" constructor mode added (`revisions/api-
  surface.md:L3-30`).
- `impute` 2026-05-01: string sugar `value="mean"` removed because it silently
  turned a literal `'mean'` category into a mean aggregate (`revisions/
  impute.md:L3-50`). A real bug found in a design document. Keep the lesson:
  closed vocabularies in value positions collide with data.
- `sqlearn-api` 2026-05-04 (amendment): "data flows through verbs, not
  constructors" scoped to top-level pipelines two days after the lock,
  because child pipelines inside `Join` and `Union` need constructor data
  (`revisions/sqlearn-api.md:L3-50`). A lock that did not survive the next
  feature.
- `step-composability` 2026-06-07: `where=`, `group_by=`, `order_by=` and
  `drop_nulls=` widened to accept a step instance (`revisions/step-
  composability.md:L3-30`). The second "one parameter, one shape" exception
  after `new_column=`.
- `errors` 2026-06-13: the interim warning taxonomy (authored as a temporary
  home) moved to `core/warnings.md`; `AliasSubstitutionInfo` renamed
  `AliasSubstitutionWarning` and its substitution field changed from a dict to
  a `Literal` (`revisions/errors.md:L3-60`). The "Info" suffix tied severity to
  the class name, so a severity tweak would have been a breaking rename.
- Pattern (inference): 7 of 11 entries are renames or scope-downs of locks made
  days earlier. Dates in the revision files are hand-typed and drift from
  git: `errors.md` says the interim section was written on 8 May, but the log
  has no commits between 7 May and 7 June; the composability entry says
  7 June, the commits are 8 June.
- The rule worked in one respect: every loosening has an old-wording quote and
  a reason. It did not reduce churn, which came from locking API shapes before
  any code existed to use them.

## Ideas

One line each: proposal, relevance. 52 files, 3 rejected. Core means the
library core (part 3.2); "later" means the explorer, editor, or beyond;
"no" means product strategy the new project does not have.

- `parameterize-by-aggregate`: one `Impute`, `Scale`, `Clip` class taking
  aggregates or literals instead of ~30 variants (`ideas/parameterize-by-
  aggregate.md:L14-40`). Core, high. Fits SQL (aggregate emits its own CTE)
  and cross-validation (each fold needs its own aggregate values, `L155`).
  It also bears on how fit runs: `Scale(center=Mean)` after `Impute` is the
  exact case of the fit defect.
- `step-composability`: internal decomposition of a step into smaller steps,
  with a `decomposes_into` manifest (locked 2026-06-07). Core, high. This is
  how a composite step gets one fit order.
- `semantic-role-system`: a second layer tagging columns Numeric, Categorical,
  Cyclical (storage and role independent). Core, medium; the war room locked a
  hybrid "Option C" (`6c7e73e`, `893eb06`). Later for the full form.
- `lazy-output-modes`: a 9-mode `output=` enum already includes DuckDB
  relation, polars lazy, and arrow stream; more modes deferred. Core,
  medium; feeds data larger than memory.
- `sq-search-engines` and `automl-elimination-search`, `auto-tuning`: grid
  default, pluggable engines, fold-id columns (`_sq_fold_id`, repeat and
  nested variants, `L155-179`), and two fold-execution modes (`L181-235`).
  Core, high for the fold columns; the elimination search and engine zoo are
  later.
- `sq-join`, `sq-union`, `predicate-joins`, `ordinal-join-rewrite`,
  `dag-pipelines`: multi-source steps and DAG pipelines (reusing one step at
  several positions). Later; the core first needs a linear pipeline.
- `flow-api`, `method-chained-pipeline`, `schema-typed-api`,
  `api-verbosity-spectrum`, `website-api-toggle`: five alternative surfaces
  (`>>` chains, `sq.on(cols).step()`, semantic types). No: ADR 0003 stands;
  the one lasting point is "line count is not the only axis"
  (`api-verbosity-spectrum.md:L5-8`).
- `rejected/flow-smart`: column inference by `accepts` already covers it; one
  mechanism for standalone, pipeline and flow (`flow-smart.md:L217-229`). Keep
  the lesson: one inference mechanism.
- `cross-dialect-primitive-lowering`, `alias-purity-tiers`,
  `per-step-engine-optimization-audit`, `per-step-database-version-classes`,
  `version-aware-dispatch`, `resolver-ast-caching`,
  `resolver-cycle-detection-bookkeeping`, `dialect-specific-compilation`:
  engine and version dispatch for MEDIAN, MODE and friends. Relevant to
  multi-engine support (open question), not the core. All assume sqlglot.
- `native-multi-connection`, `federated-execution`, `distributed-execution-
  via-dbt`, `distributed-model-fitting`, `async-connections`: reach other
  databases directly or in parallel. Later; the baseline's route (DuckDB
  `ATTACH`) is simpler, and `native-multi-connection` itself states that
  `ATTACH` is the v0.1.0 path (`L1-20`).
- `db-reader-convenience`, `db-storage-migration`, `db-memory-orchestration`,
  `streaming-batch-delivery`: `from_csv()`, persist and load, memory `SET`
  suggestions, batched delivery to trainers. Core adjacent, low; data larger
  than memory matters (streaming, persistence).
- `sql-native-models`: linear regression via normal equations, k-means via
  iterative aggregates. Later; this extends the aim to "ML in SQL".
- `nlp-support`, `external-tool-adapters`, `gpu-support`, `plugin-
  architecture`, `rust-library-hot-paths`: text steps, glue recipes, GPU,
  plugins, Rust. No for the core; plugin surface may return later.
- `parameter-typo-tolerance`: accept `Col=`, `column=` and `OneHotEncoder` and
  warn (`parameter-typo-tolerance.md:L10-25`). No: it contradicts
  "one canonical spelling" (principle 6) and hides mistakes.
- `i18n-error-messages`: the gettext design. No for now (see Rules).
- `smart-defaults`, `auto-rewrite`, `risk-warnings`, `llm-assistance`,
  `deployment-recipes`, `visual-canvas`, `pro-free-access`,
  `pro-pricing-model`, `rust-agent-acceleration`, `rejected/enterprise-tier`,
  `rejected/pipeline-cloud-sync`: the pro tier (coding agent, canvas,
  pricing, cloud sync). No. `visual-canvas` is the only link to the planned
  node-based editor, and is a two-line stub.

## History

Commits per day: 26 Apr 4; 27 Apr 7; 28 Apr 31; 29 Apr 26; 30 Apr 64; 1 May
12; 2 May 125 (the peak); 3 May 18; 4 May 24; 6 May 18; 7 May 35; then none
until 7 June 30; 8 June 6; 13 June 10. Eleven active days in 7 weeks.
Counts below are from the log; phase names are mine.

1. **Rules and ideas first, 26-27 Apr** (`ee46801`..`d04b040`, 11 commits):
   repo initialised, 17 rules written in one day (`baba225`), tiers and
   content-boundary rewritten the next, 12 ideas seeded, two rejected.
2. **First specs and the orchestrator, 28-29 Apr** (`abe9ece`..`109549d`):
   `core/step.md`, `core/pipeline.md`, per-category step specs (aggregates,
   transforms, scalers, imputers, encoders), release plans v0.1.0 and v0.1.1
   (`9e47aa1`, `046eef7`), the orchestrator skill with four agents
   (`5c1cf43`), the triage agent (`ae1883b`), five releases archived
   (`527c8b8`). Scope: "DuckDB-only for v0.1.0" (`ff48d3e`, 29 Apr).
3. **Multi-dialect redesign, 30 Apr** (`bd28d09`..`272bccb`, 64 commits):
   reversed the previous day's scope (DuckDB, Postgres, MySQL, SQLite);
   active and archived releases and reports were wiped (`1e9b03b`,
   `aa2d4ae`, `427524f`); `core/resolver`, `compiler`, `polyfills`,
   `dtypes`, `selectors`, `api-surface` and four backend specs; the
   `TODO.md` parking lot was added (`272bccb`).
4. **Track A, i18n and P7 sweeps, 1-2 May** (`c632a7a`..`92d27a1`): output
   naming unified; "R1-R7 of the P7 sweep" (seven API additions in six
   commits); gettext design; nine-agent parallel audit; `TODO_SPEC.md`,
   handoff commands (`b334720`); principles 6 and 7 codified (`30b4fa5`).
5. **Engine_alias and coverage redesign, 2-3 May** (`617b93c`..`7ba9fd9`):
   a 3-plan arc replaced the polyfill catalogue with per-step `natives`
   (`0303398`); ten aggregate specs migrated, four backend specs migrated;
   22 stale cross-references retargeted (`890dfb1`); plans archived. One
   revert pair (`4d368ee` / `26051c1`).
6. **Connections and IO design questions, 3-6 May** (`28723ca`..`a1b8bea`):
   about 55 `docs(todo): lock Q-...` commits, each locking one decision:
   Q-CONN-1 to 10 (connections), Q-IO-1 to 5 (PK invariant, verb signature,
   output enum, `sq.Merge` renamed `sq.Join`, `sq.Union`). Scope narrowed to
   DuckDB and SQLite (`7b45d80`, 3 May), after the 30 April four-dialect
   redesign.
7. **Q-IO Phase 2 sweep, 6-7 May** (`1aaeb64`..`162b156`, ~40 commits): a
   15-section briefing pack, 5 plan-writer slices, 6 verifier rounds,
   "cleanup-1 to cleanup-6", each finding residual drift. The last commit
   records a "meta-convergence concern" (`162b156`).
8. **Stall, 8 May - 6 June.** No commits for 31 days (inference: the verifier
   loop did not converge, and nothing else was pending; the reason is not
   written down).
9. **Checker, connections and ClickHouse, 7 June** (`40d02de`..`a20c821`, 30
   commits): `check-spec-refs.py` (`40d02de`, `6a3cb99`), Q-IO residue
   fix-pass, a 13-file connections layer, ClickHouse spec added as tier 2.
10. **Composability and warnings, 8 and 13 June** (`44284ae`..`bb80f14`):
    step composability authored (`51fa7b7`..`df3cc81`), backlog audit (10
    rows drained, `9819ec2`), warnings subsystem designed and written in one
    day (`800d37a`..`bb80f14`, ~28 agents per `OLD:handoff.md:L25`).

How much was process: 119 of 410 commits by subject (29%). Add the sweep and
cleanup commits and the `Q-` lock commits (documentation of decisions, not
code) and it is nearer two thirds, as in the April repo (inference).
Rework: the 30 April wipe of releases and reports; the 28 Apr to 3 May scope
swing (DuckDB-only, then four dialects, then two); the polyfill catalogue
built 30 April and deleted 2 May (`34e5932` then `890dfb1`, `5513db9`);
`flow-smart` proposed 28 April and rejected 2 May (`7bbbd63`).

Stop on 13 June: `bb80f14` (21:14) closed the warnings arc with no active
focus; `handoff.md` records 8 unpushed commits (`800d37a..bb80f14`) and that
the user wrapped without authorising a push (`OLD:handoff.md:L18`). "User
said will start fresh session" (`L27`). Candidate next work was the search
engine spec and sqlearn-side items (coverage CSV generator, CI) that need
code (`L31`). `TODO.md` was changed on 24 June (a "search arc" with locks
such as `engine="grid"` default, `OLD:TODO.md:L87-100`) without a commit.
Why work stopped and what came next are not stated in OLD; the August
`sql_learn` restarts are the next attempts (per the README plan, not read
here). Inference: the first work that would have needed real code (search,
coverage generator) was reached and the war room had no code repo to put it
in.

## New against the baseline

- **Primary-key invariant.** Every entry wraps input in a VIEW with
  `_sqlearn_primary_key = row_number() OVER ()`, refreshed at each Join and
  Union, stripped on output (`OLD:rules/sqlearn-api.md:L79-110`). The
  baseline has row order only as a fold design detail. Inference to verify
  on DuckDB: `row_number() OVER ()` without `ORDER BY` is only stable if
  insertion order is preserved; the rule relies on "outermost ORDER BY on
  the PK" for scikit-learn row-order parity.
- **`natives` dispatch table.** Each step declares per dialect which SQL node
  forms exist (`high_node`, `low_node`, `alias_node`, `unsupported`), replacing
  a polyfill catalogue (`0303398`, `OLD:rules/revisions/errors.md:L30-36`).
  Useful only if the new project goes multi-engine.
- **Warnings as structured records** with severity as a field, not a class
  name (`OLD:rules/revisions/errors.md:L36-45`). Small and sound; premature.
- **Closed vocabulary in a value slot is a bug** (the `value="mean"` case,
  `OLD:rules/revisions/impute.md`): add to the API survey.
- **Teaching-error template** with a fixed shape and `to_dict()`; the idea is
  portable and cheap; the three-routes rule is not.
- **Deterministic checker over agent verifiers.** Six LLM rounds failed to
  prove convergence; the script enumerates drift exhaustively
  (`OLD:scripts/check-spec-refs.py:L11-14`). The baseline says a separate
  review sweep found real bugs each time; this adds that sweeps on
  documents do not converge.
- **Agent set and cost shape.** Ten agents, nine on `model: opus`
  (`OLD:.claude/agents/*.md:L5`), a stage-gated plan-writer and reviewer,
  "gather, analyse, write", "background only", about 28 agents in a day.
- **Handoff discipline.** `/handoff` writes a thin note and refuses if the
  inbox is not drained (`OLD:.claude/commands/handoff.md`). The new project
  keeps state in GitHub Issues and plan files instead.

## Contradicts the baseline

- **Per-fold statistics.** The baseline records a per-fold `FILTER (WHERE
  fold != k)` design that gives each fold its own statistics in one scan.
  The war room's default Mode A "holds the compiled apply AST ... plus the
  learned values from `learn()`", wrapping it with `WHERE _sq_fold_id != N`
  with "no state re-fetching" (`OLD:ideas/sq-search-engines.md:L186-206`).
  Read literally, statistics come from all rows and only the filter changes,
  which leaks validation rows into training statistics (inference; the idea
  file does not say how learned values are recomputed). Mode B materialises
  fold tables but is for "stable preprocessing". Treat the war-room fold
  design as a counter-example.
- **Multi-engine scope.** The baseline: sqlglot transpilation is "syntactic,
  not semantic", portability untested. The war room committed to four
  dialects on 30 April (`bd28d09`..`b49eda5`), then two on 3 May (`7b45d80`),
  then ClickHouse on 7 June (`13ee9d3`), still all unvalidated: the
  per-dialect validation plan in `validation.md:L33-55` requires running real
  engines, which never happened (no code). More evidence for ADR 0002/0004
  keeping DuckDB the only engine at first.
- **Deliberate non-scikit-learn names.** `learn`/`apply`/`summary` are
  justified as "not `fit`/`transform`: those carry in-memory semantics"
  (`OLD:rules/sqlearn-principles.md:L40-50`). ADR 0003 says the API follows
  scikit-learn. This confirms the baseline's note that the April repo
  settled on `learn`/`apply` and that v0.4 and `sqlearn_000` used them; the
  war-room rationale is new evidence for the departure ADR, not a reason to
  change ADR 0003.
- **Target as a column name and data as a source**: `target=` is a role
  parameter (`parameter-shapes.md` table), `learn(data)` takes a data
  reference. This matches the baseline's "every attempt did this"; no
  contradiction, but the war room never excluded the target from default
  columns (no rule found in the parts read).

## Confirms the baseline

- Process outgrew product, with status held in many places (`TODO.md`,
  handoff, inbox, plans, release files) and drifting (dates, row counts:
  `0e92839` corrects "38 files" to 56; `e4943b2` corrects "error #9").
- Docs with hand-typed numbers were wrong: counts of errors, files and
  anchors needed repeated fixes (`04e1b7c`: "9 to 8", "4 to 3").
- A separate review sweep finds real bugs every time; here it also never
  stops finding them (six rounds, `ba46c09`..`162b156`).
- The April repo's pattern repeated with a new twist: no code at all, again.
- Validation was specified in great detail and applied per step, not per
  pipeline; no whole-pipeline scikit-learn comparison (parts read).
- sqlglot throughout; `ADR 0004` caution holds. The `natives` redesign was
  needed because sqlglot's transpiler alone was not enough for MEDIAN, MODE
  and variance aliases (`cdec830`, `896a1f1`: DuckDB `STDDEV` alias direction
  was wrong in two specs on the first attempt).
- JSON for saved state, with a round-trip test (`rules/serialization.md`).

## Worth keeping

- One-page deterministic checker pattern (token residue, dead links, anchors)
  for docs; the new repo's `just check` is the home.
- Teaching-error template and `to_dict()`, trimmed.
- Serialization invariants and the round-trip test.
- Expected-precision table by operation type, DuckDB as the reference engine.
- "Closed vocabulary values collide with data" (`value="mean"`).
- Non-goals table as triage lookup.
- Parameterise-by-aggregate and composite decomposition as core design inputs.
- Fold-id columns for cross-validation, as columns injected in a CTE.
- "Show the diff first, then write" for rule-file edits (cheap), the
  "loosening needs a paragraph" idea (as ADR text).
- Thin handoff: a refusal to hand off with an unsorted inbox.

## Guard against

- A document corpus larger than the code that will use it. Rule: no spec for a
  part until the previous part has code and passing tests (the new
  `workflow.md` already orders parts; enforce it).
- Locking API shapes before code exists; the revision log is evidence
  (7 of 11 entries). Prefer spikes (prototype skill) before locks.
- Status in more than one place. One tracker (GitHub Issues), one plan file
  per part; no `TODO.md` with a focus emoji, section state headers and a
  circuit breaker (`OLD:.claude/TODO_SPEC.md:L416-430`).
- Agent fan-out as a way to find drift. Use a deterministic script first; an
  agent verifier only where a script cannot decide.
- Per-session startup cost: a 42 KB skill printed into every session
  (`OLD:.claude/settings.json:L9`).
- Rules enforced by hand: "background only", "capture before any next
  action", "three consecutive edits means dispatch" are all behavioural rules
  that needed repeated fixes (`26fa09d`, `e97609c`, `8b99abf`).
- Scope swings recorded as new design (DuckDB-only, four dialects, two,
  ClickHouse in 10 days). Write the scope in an ADR and hold it.
- Pausing for a month with the real next step (build) never taken. A short
  "stop reason" line in the plan when a session ends.
- Principle 7-style "complexity is cheap" language: it licensed unbounded
  taxonomy (25+ error classes, 15 warning locks) without users.
- Unpushed commits left at session end (8 in `handoff.md`); push policy
  should be explicit in the repo instructions.

## Files covered

Legend: [x] read in full or the sections that matter; [~] skimmed (first 15
to 30 lines, headings, targeted greps).

Git log:

- [x] `war-room-git-log.txt` (410 lines): read in full.

Rules (32):

- [x] `rules/README.md`: index of 20 rules and how to use them.
- [x] `rules/document-revisions.md`: tightening free, loosening needs a
  paragraph.
- [x] `rules/versioning.md`: semver per project, unanswered open questions.
- [x] `rules/ecosystem-constraints.md`: three constraints.
- [x] `rules/sqlearn-principles.md`: seven principles, forbidden, required.
- [x] `rules/sqlearn-api.md`: step, three modes, PK invariant, verbs.
- [x] `rules/release-gate.md`: merge and release gates, no warning tier.
- [~] `rules/sqlearn-tiers.md`: free versus pro, same output contract.
- [~] `rules/content-boundary.md`: private versus public content.
- [~] `rules/non-goals.md`: rejection tables (first 110 lines).
- [~] `rules/siblings.md`: sibling cohorts (first 100 lines).
- [x] `rules/serialization.md`: JSON, pure load, round trip.
- [~] `rules/validation.md`: headings, scope, ULP table.
- [~] `rules/coding.md`: headings, quality bar, markers, test layout.
- [~] `rules/naming.md`: first 28 lines and headings.
- [~] `rules/parameter-shapes.md`: four shapes, first 28 lines.
- [~] `rules/api-checklist.md`: first 28 lines.
- [~] `rules/errors.md`: headings, template, taxonomy sections.
- [~] `rules/warnings.md`: first 28 lines.
- [~] `rules/i18n.md`: first 28 lines.
- [~] `rules/version-handling.md`: first 28 lines.
- [~] `rules/connection-management.md`: first 28 lines.
- [~] `rules/deprecation.md`: first 28 lines.
- [~] `rules/benchmarks.md`: stub, first 28 lines.
- [x] `rules/revisions/ecosystem-constraints.md`: loosening to MIT-only.
- [x] `rules/revisions/impute.md`: string sugar removed.
- [x] `rules/revisions/naming.md`: flat to mirror-source tests; `sq.sql()`.
- [x] `rules/revisions/step.md`: `new_column=` entries (first 60 lines).
- [~] `rules/revisions/api-surface.md`: `out=` to `output=`.
- [x] `rules/revisions/sqlearn-api.md`: `data=` scoping amendment.
- [x] `rules/revisions/step-composability.md`: step-instance kwargs.
- [~] `rules/revisions/errors.md`: warning taxonomy relocation (lines 30-62).

Ideas (55):

- [x] `ideas/README.md`: lifecycle and file shape.
- [~] `ideas/alias-purity-tiers.md`: richer alias substitution, v0.2+.
- [~] `ideas/api-verbosity-spectrum.md`: line count is not readability.
- [~] `ideas/async-connections.md`: async reserved for v0.2+.
- [~] `ideas/auto-rewrite.md`: pro risky-step rewrite.
- [~] `ideas/auto-tuning.md`: pro per-column tuning.
- [~] `ideas/automl-elimination-search.md`: pro successive halving.
- [~] `ideas/cross-dialect-primitive-lowering.md`: two-layer lowering.
- [~] `ideas/dag-pipelines.md`: step reuse as a DAG.
- [~] `ideas/db-memory-orchestration.md`: phase-aware `SET` suggestions.
- [~] `ideas/db-reader-convenience.md`: `from_csv()` and friends.
- [~] `ideas/db-storage-migration.md`: persist and load.
- [~] `ideas/deployment-recipes.md`: pro dbt and Airflow output.
- [~] `ideas/dialect-specific-compilation.md`: per-dialect optimisation.
- [~] `ideas/distributed-execution-via-dbt.md`: shards through dbt.
- [~] `ideas/distributed-model-fitting.md`: Dask and Spark trainers.
- [~] `ideas/external-tool-adapters.md`: chaining recipes.
- [~] `ideas/federated-execution.md`: pro cross-source planner.
- [~] `ideas/flow-api.md`: second pipeline API with `>>`.
- [~] `ideas/gpu-support.md`: GPU backends.
- [~] `ideas/i18n-error-messages.md`: gettext design.
- [~] `ideas/lazy-output-modes.md`: lazy and streaming outputs.
- [~] `ideas/llm-assistance.md`: pro LLM features.
- [~] `ideas/method-chained-pipeline.md`: `sq.on(cols).step()`.
- [~] `ideas/native-multi-connection.md`: direct multi-database access.
- [~] `ideas/nlp-support.md`: text steps.
- [~] `ideas/ordinal-join-rewrite.md`: ordinal as a static step.
- [~] `ideas/parameter-typo-tolerance.md`: accept near-miss names.
- [~] `ideas/parameterize-by-aggregate.md`: one class, aggregate parameters.
- [~] `ideas/per-step-database-version-classes.md`: nested version classes.
- [~] `ideas/per-step-engine-optimization-audit.md`: per-engine tuning.
- [~] `ideas/plugin-architecture.md`: third-party steps.
- [~] `ideas/predicate-joins.md`: predicate join form, deferred.
- [~] `ideas/pro-free-access.md`: student and OSS access.
- [~] `ideas/pro-pricing-model.md`: per-seat model.
- [~] `ideas/resolver-ast-caching.md`: cache resolved AST.
- [~] `ideas/resolver-cycle-detection-bookkeeping.md`: cycle bookkeeping.
- [~] `ideas/risk-warnings.md`: pro diagnostics.
- [~] `ideas/rust-agent-acceleration.md`: Rust for pro agent.
- [~] `ideas/rust-library-hot-paths.md`: Rust for compiler hot paths.
- [~] `ideas/schema-typed-api.md`: semantic column types.
- [~] `ideas/semantic-role-system.md`: role layer over dtypes.
- [~] `ideas/smart-defaults.md`: pro automatic preprocessing.
- [~] `ideas/sq-join.md`: join step, locked v0.1.0.
- [x] `ideas/sq-search-engines.md`: fold columns and fold modes (lines 140-235
  read; rest skimmed).
- [~] `ideas/sq-union.md`: union step, locked v0.1.0.
- [~] `ideas/sql-native-models.md`: linear regression and k-means in SQL.
- [~] `ideas/step-composability.md`: composite decomposition status.
- [~] `ideas/streaming-batch-delivery.md`: batch delivery to trainers.
- [~] `ideas/version-aware-dispatch.md`: engine version sniffing.
- [~] `ideas/visual-canvas.md`: pro node editor, stub.
- [~] `ideas/website-api-toggle.md`: docs surface toggle.
- [~] `ideas/rejected/enterprise-tier.md`: third tier, rejected.
- [~] `ideas/rejected/pipeline-cloud-sync.md`: cloud sync, rejected.
- [x] `ideas/rejected/flow-smart.md`: rejected, with the reason (lines 217-229).

Templates (5):

- [~] `templates/README.md`: do not edit in place; copy.
- [~] `templates/release.md`: release file frontmatter (status, theme,
  `affects_projects`).
- [~] `templates/report.md`: issue-report template (severity, status).
- [~] `templates/triage-report.md`: triage bundle template.
- [~] `templates/step-spec.md`: per-step spec template, classification and
  validation sections (first 20 lines and greps; 20 KB).

Scripts (2):

- [x] `scripts/check-spec-refs.py`: docstring and constants read; tokens,
  links, anchors checks; not executed.
- [~] `scripts/spec-refs-allow.txt`: allow-list of known-future refs.

.claude (16):

- [x] `.claude/settings.json`: SessionStart hook cats the skill; broad allow
  list including `git push`.
- [~] `.claude/settings.local.json`: not opened (local permissions, may hold
  secrets); size only.
- [~] `.claude/TODO_SPEC.md`: TODO system design; sections 1 and 12 read.
- [x] `.claude/skills/war-room-orchestrator/SKILL.md`: rituals, dispatch tree,
  TODO mechanics, agent table (first 150 lines of 42 KB).
- [~] `.claude/commands/handoff.md`: thin handoff, preconditions.
- [~] `.claude/commands/handoff-resume.md`: read handoff and TODO, resume.
- [~] `.claude/agents/architectural-spec-writer.md`: opus, writes machinery
  specs.
- [~] `.claude/agents/formula-researcher.md`: opus, finds canonical formula.
- [~] `.claude/agents/library-implementation-researcher.md`: opus, which
  libraries implement a step.
- [~] `.claude/agents/plan-reviewer.md`: opus, six review modes.
- [~] `.claude/agents/plan-writer.md`: opus, one slice of a plan.
- [~] `.claude/agents/release-author.md`: opus, writes release files.
- [~] `.claude/agents/report-triage.md`: opus, triages issue reports.
- [~] `.claude/agents/spec-auditor.md`: opus, five-dimension audit.
- [~] `.claude/agents/spec-writer.md`: opus, step specs from the template.
- [~] `.claude/agents/war-room-investigator.md`: sonnet, read-only survey.

Also read for context, not in the batch: `OLD:handoff.md`, `OLD:WORKFLOWS.md`,
`OLD:CLAUDE.md` (first 90 lines), `OLD:inbox.md` (first 50 lines),
`OLD:TODO.md` (lines 1-10 and 87-122), `OLD:.gitignore`, `OLD:.git/logs/HEAD`
(last 3 lines, for the final commit time).
