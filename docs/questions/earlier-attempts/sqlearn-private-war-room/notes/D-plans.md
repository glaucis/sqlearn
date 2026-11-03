---
type: note
tags: [sqlearn, war-room, planning, spec-corpus, retrospective]
summary: "Retrospective of batch D: live war-room plans (Q-IO phase 2, ClickHouse, connections, step composability) that were executed as spec edits."
related: [TODO.md, core/io.md, core/warnings.md, backend/clickhouse.md, connections/clickhouse.md, core/inspector.md, core/connections/, connections/]
mdindex: [type=edb465, tags=0fc93e, summary=8f1cab, related=4d057e]
---
# Batch D: live plans of the war room

Source: OLD is
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sqlearn-ecosystem/sqlearn-private`.
Citations read `OLD:plans/<file>:Lnn` (paths are relative to OLD; `TODO.md` and
spec paths are outside the batch and were read only to find out whether plans
ran). Inference is marked **(inf.)**. No file in the batch hung or was skipped.

## Summary

- Every plan in this batch is a plan to edit or write **specification
  Markdown**, not a plan to build library code. The "product" of the war room
  is a spec corpus (26,197 lines under `OLD/projects/`); OLD has no `src/` and
  no package **(inf.** from `ls` of OLD root: `CLAUDE.md README.md TODO.md
  WORKFLOWS.md coverage handoff.md ideas inbox.md plans projects releases
  reports rules scripts templates`; the only code is `scripts/`).
- All five arcs were executed as spec edits: Q-IO phase 2, connections,
  ClickHouse, step composability and warnings each have a "COMPLETE/SHIPPED"
  tombstone with commit ranges (`OLD:TODO.md:L378-L384`) and the target files
  exist (`core/io.md` 1,470 lines, `core/warnings.md` 476,
  `backend/clickhouse.md` 594, 10 `connections/` files, 4 `filters/` files).
  None of the 24 plan files has a single tick box; status lives in frontmatter
  and in `TODO.md`.
- The lettered plans are 17,622 lines for roughly 8,000 lines of new spec
  plus edits. The process was briefing pack, parallel plan-writers, a
  meta-review, a frozen "execution addendum", then spec-authors, then a
  deterministic checker. It worked in the narrow sense that every arc landed
  and `check-spec-refs.py --strict` ended clean, but it produced prose about
  prose with no executable behaviour behind it.
- Fit execution: the war room's model is layered execution, "layer count =
  dependency depth of the step graph"
  (`OLD:plans/2026-05-06-q-io-phase-2-plan-b.md:L732`), with children of
  `sq.Join`/`sq.Union` fitting before the parent
  (`OLD:plans/2026-05-06-q-io-phase-2-plan-a.md:L781`). That is a staged fit,
  and it confirms the baseline's "learning step reads a value an earlier step
  changed" boundary in spirit; these plans never state the boundary rule itself
  (it lives in `core/inspector.md`, not in this batch).
- Learned state: the plans still write each learned value back onto the step
  instance via `cte_index_map` keyed on `id(step)`
  (`OLD:plans/2026-05-06-q-io-phase-2-plan-b.md:L897-L899`) and save it with
  the pipeline. That is the shared-step-object design the baseline says breaks
  cross-validation.
- Engines: five dialects (DuckDB, SQLite, Postgres, MySQL, ClickHouse) through
  a per-step `natives` dict with tiers `high_node`/`low_node`/`alias_node`/
  `unsupported`, plus sqlglot transpilation. ClickHouse is the first dialect
  with an honest "no DuckDB scanner exists" gap
  (`OLD:plans/2026-06-07-clickhouse-integration.md:L35`).
- Connections: a connection travels **inside the data argument**
  (`sq.table(conn, ...)`, `sq.sql(conn, ...)`), never as a `conn=` kwarg; an
  adapter protocol with isinstance detection, version detection, BYO
  connection ownership, per-call auto-default DuckDB.
- Step composability is two small things: filters as ordinary steps with
  three call forms (kwarg, standalone step, step-as-value), and composite
  steps that declare their constituents so per-dialect support is derived.
  It does not touch the fit-order defect.
- Repeated failure modes: names and paths decided late and renamed in sweeps
  (`core/connections/` to `connections/`, `AliasSubstitutionInfo` to
  `...Warning`, aggregate `Distinct` to `DistinctValues`), hand-typed counts
  and line numbers that drifted, and "verify, don't assume" corrections after
  agents were dispatched on wrong assumptions.
- Best things to reuse: the briefing, slices, meta-review, frozen addendum
  and deterministic reference checker as a pattern; the ClickHouse routing
  table and dtype facts; the filter-scope rule; the warnings class model.

## Plans

### Q-IO phase 2 (6 May 2026): briefing and plans a to e

- **Goal.** Propagate the already-locked "Q-IO" decisions (PK column, the
  `learn(data)` verb signature, output modes, `sq.Join`, `sq.Union`) into
  every spec that still described the pre-lock state: "~100+ edits across 42
  distinct files" (`OLD:plans/2026-05-06-q-io-phase-2-briefing.md:L36`). Plan
  a writes one new file (`core/io.md`); b edits ten core files; c edits
  rules; d patches backends, family READMEs, step specs and the template; e
  splits `ideas/multi-source-merge.md` into `sq-join.md` and `sq-union.md` and
  patches eight idea files (`...briefing.md:L167-L265`).
- **Why.** The locks lived only in one giant `TODO.md` line (L95) and
  sub-sections; the canonical specs contradicted them
  (`...briefing.md:L36`).
- **Design decisions carried.**
  - A framework column `_sqlearn_primary_key` is injected at every IO entry as
    `row_number() OVER ()` in a view, replaced fresh at every Join/Union
    boundary, and stripped at output; output is ordered by it
    (`OLD:plans/2026-05-06-q-io-phase-2-plan-a.md:L424-L470`). Rationale for
    dropping child keys: "learned-state is statistical, not row-level" (L452
    area).
  - One positional `data` argument carries connection, dialect and version;
    no `conn=` on verbs (`...briefing.md:L54`).
  - Nine `output=` modes (numpy default, pandas, polars, polars.lazy, arrow,
    arrow.stream, duckdb, sql, json); `duckdb` and `arrow.stream` route through
    DuckDB even on other engines (the "alpha auto-imply" rule,
    `...plan-a.md:L539-L580`). `dialect=` only with `output="sql"`.
  - `engine="duckdb"` runs the whole pipeline in DuckDB with the user's
    database attached (`...plan-d.md:L240-L268`).
  - Recursive AST composition: one `_sqlearn_<N>` CTE counter across the whole
    tree, "children fit pre-Join, parent fits post-Join", an all-static tree
    is 0 learn passes plus one combined `learn_apply` query
    (`...plan-a.md:L770-L795`, `...plan-b.md:L896-L960`).
  - Twelve IO error classes, stated as a lineage 2 to 3 to 4 to 8 to 10 to 12
    (`...briefing.md:L77-L99`).
- **Executed?** Yes. `core/io.md` exists (1,470 lines) and the tombstone says
  "5 plans executed (~2900 lines across 47 files) ... 6 verification rounds + 6
  cleanup commits ... `0a40d24..133834f`" (`OLD:TODO.md:L383`). All six plan
  files still say `status: draft (awaiting review)`
  (`...plan-a.md:L4` and the same line in b to e), so frontmatter was never
  updated after the fact. The plan set was frozen on 8 May after "19 plan-author
  OQs resolved" (`OLD:TODO.md:L384`).
- **What got in the way.** The briefing's file count disagreed with itself (44
  files at L17, 42 at L36; later 47 in TODO), and each plan cited different
  `TODO.md` line ranges for the same sub-sections (plan-a L10-L27 says
  L312-L451, plan-b L10-L26 says L339-L478 and "row body (L122)"). The dispatch
  model in the briefing (5 parallel plus 2 chained, "7 Opus runs") was
  superseded the next day by a "stage-gated max-paranoia" model of 9 to 15 runs
  (`...briefing.md:L450`). Verification "never converged" until a script
  replaced agent sampling (see Size and adherence).

### Clickhouse integration (7 June)

- **Goal.** Make ClickHouse a real fifth dialect: new `backend/clickhouse.md`,
  `"clickhouse"` entries in per-step `natives` dicts, fixes to the already
  shipped `connections/clickhouse.md`, a coverage column
  (`OLD:plans/2026-06-07-clickhouse-integration.md:L5-L8`).
- **Decisions.** Tier 2; dialect key `"clickhouse"`; floor 23.8 LTS;
  `on_older: error`; no DuckDB-as-engine route (L1 to L9, L25-L40). Three
  gaps need `low_node` window polyfills: median, quantile and mode (L47-L49).
  Dtype unwrap of `Nullable(T)` and `LowCardinality(T)` recursively (L37).
  Quirks: `LOG` is natural log, bare `STDDEV` is sample, no `VARIANCE` alias,
  quantile/median approximate by default (L53, L79).
- **Executed?** Yes: tombstone "ClickHouse dialect, full integration COMPLETE",
  four commits `13ee9d3..a20c821`, tier 2 user-ratified, 10 aggregate `natives`
  dicts edited, 13 cross-reference rows (`OLD:TODO.md:L381`).
- **What got in the way.** Section 0 is a block of "post-dispatch corrections":
  the briefing assumed things the corpus did not have (non-aggregate steps have
  no `natives` dicts; `coverage.csv` is generated, not hand-edited; README
  files have no per-dialect table; `mean` is `low_node` not `high_node`;
  `distinct` is set extraction not `COUNT(DISTINCT)`) (L12-L21). So the plan
  was wrong on its own subject before the agents ran, and a correction block
  was patched on top rather than the body being fixed.

### Connections layer authoring (7 June)

- **Goal.** Thirteen spec files for the connection-adapter layer: protocol
  contract `connection.md`, `_template.md`, five dialect adapters, SQLAlchemy
  and jupysql middleware, a raw DB-API fallback, two rules, and an `errors.md`
  section (`OLD:plans/2026-06-07-connections-layer-authoring.md:L10-L14`).
- **Decisions.** Tiered protocol: required `dialect`, `version`, `execute()`
  plus capability mixins `SupportsAttach/Copy/Streaming/ServerSideAggregation`
  (L135). isinstance detection returning an `(adapter, dialect, version)`
  triple; sync and async registries, async deferred to v0.2 (L136-L137, L147).
  Entry-point plugin API `register_adapter` (L138). Auto-default: per-call
  ephemeral DuckDB if installed else stdlib `sqlite3`, one advisory, disabled
  by `SQLEARN_NO_AUTO_CONN` (L139). Connection scope: no `conn=` kwarg, it
  rides inside `data` (L140). Version detection by attribute first, soft-fail,
  `VersionConstraint` with a floor (L141-L142). BYO ownership: never close
  the user's connection (L143). Native driver recommended, SQLAlchemy
  "compat-not-default" (L175-L180). 7 runtime errors, 2 warnings, plus
  `AdapterRegistrationError` outside the count (L105-L120). No `natives`
  section on adapters (L55).
- **Executed?** Yes: "Phase A/B/C COMPLETE", 11 commits `8e775e4..7bd529c`
  (`OLD:TODO.md:L382`). The plan itself still says "DRAFT, awaiting approval; NO
  spec is written until this plan is approved"
  (`...connections-layer-authoring.md:L4`).
- **What got in the way.** The plan's own text records the same lock being
  written wrongly twice: P1 "CORRECTED 2026-06-07 from the lock body" because
  its first proposal contradicted the lock (L81-L87), and the `conn=`-kwarg
  design was "SUPERSEDED" by Q-IO-2 and caught only when "the un-blinded
  checker" found a token violation at `connection.md:473`, so "both new files
  [were] sent back for correction" (L140). The folder itself moved from
  `core/connections/` to `connections/` after a 4-agent vote (L7, L63).

### Step composability (7 June): briefing, addendum, plans a to g

- **Goal.** Direction A (user-visible): turn kwargs into standalone steps and
  add a `filters/` family (`Filter`, `DropNulls`, `Distinct`). Direction B
  (framework-internal): composite-step decomposition
  (`OLD:plans/2026-06-07-step-composability-authoring-briefing.md:L24-L30`).
  Slices: a pipeline/inspector/step/parameter-shapes; b `filters/` (4 new
  files); c `dtypes.md` + `substeps.md`; d errors/surface/template; e retire
  three idea files; f orphan cross-reference fixes plus resolver key; g rename
  the aggregate `Distinct` (`...briefing.md:L132-L163, L229-L260`).
- **Why.** The need came from a brainstorm: filters and group-by had no
  first-class form, and a `Distinct` existed only as a set-of-values aggregate.
  The briefing says "All design locks are RESOLVED (this is execution, not
  decision)" (L12).
- **Executed?** Yes: "Direction A + B SHIPPED (2026-06-08)", "4 spec commits + 1
  plan-pack commit `44284ae..f23bb86`" (`OLD:TODO.md:L380`). The addendum is
  `dispatch-ready (pending user freeze-go)` (`...execution-addendum.md:L4`);
  plan e is the only plan marked `dispatch-ready`, the rest `draft`.
- **Obstacles.** A name collision was found after plans were written: the new
  filter and the existing aggregate were both `sq.Distinct`, resolved by
  renaming the aggregate (briefing section 7, L229-L240). Plan g then missed
  call sites, found by the reviewer, one of them a dead link that would fail the
  checker (`...addendum.md:L20-L27`). Plans written before section 7 "carry
  stale OQ text" (addendum L64-L66). Commits had to be ordered C, A, D, G, B, E,
  F with same-commit couplings (addendum L92-L111).

### Warnings subsystem (13 June): spec, addendum, plans a to e

- **Goal.** One subsystem for non-fatal warnings: the briefing is both design
  and authoring brief with 15 locks LD-W1..W15
  (`OLD:plans/2026-06-13-warnings-subsystem.md:L5-L9, L59-L70`). Slices: a new
  `core/warnings.md`; b `errors.md` + new `rules/warnings.md`; c resolver and
  inspector; d templates, website guide, api-surface, README, checklist; e 14
  files of cross-reference repoints.
- **Decisions.** `SqlearnWarning(UserWarning)` hierarchy, one object is both
  the Python category and the structured record; three real subclasses
  (`AliasSubstitutionWarning`, `AmbiguousVersionWarning`,
  `PreReleaseVersionWarning`); base fields step, dialect, reason, severity,
  message, template, format args, code, path, source; stdlib suppression and
  dedup; severity ladder `info/advisory/warning`; `doc_url` derived; display API
  with `Warning`/`Warnings`, five verbosity levels, `show()`; mean-to-avg
  substitution is silent (L149-L157). Two channels kept apart: resolver
  `plan["warnings"]` and inspector `StepClassification.warnings` (L205-L206).
- **Executed?** Yes: "Q-WARNINGS COMPLETE (2026-06-13)", `core/warnings.md`
  and `rules/warnings.md` exist (476 and 204 lines) (`OLD:TODO.md:L378`). The
  addendum says commits are "gated on explicit user ask" and execution "applies
  to the working tree" (`...execution-addendum.md:L89-L90`).
- **Obstacles.** The plan reconciles a brainstorm from 3 May that predated the
  connection arc (L15-L20): the earlier "anonymous record plus dot.path code"
  model lost to named classes (L29-L32). The meta-review caught spelling drift
  in the severity literal; the addendum pins it as "SPACED after commas" and
  pins a heading all 15 cross-references hit (`...addendum.md:L11-L50`).

## Step composability

- **What problem it solved.** Not the fit problem. Two ergonomics and
  architecture problems:
  1. *A step in three forms.* `where=`, `group_by=`, `order_by=` and
     `drop_nulls=` become `str | step-instance`; a `Filter` is also a plain
     pipeline step; mixing dissolves because one kwarg takes one value, so there
     is no `where_step=` (`...authoring-briefing.md:L63-L69`). Standalone
     `GroupBy`/`OrderBy` are rejected when the `Pipeline` is built, not at
     compile (L58-L62).
  2. *Composite steps.* An optional `decomposes_into` manifest of constituent
     classes lets a composite's per-dialect `natives` slot be derived as the
     "most degraded" constituent slot ("logical AND"), at class-definition
     time in `BaseStep.__init_subclass__`; an explicit `natives=` overrides;
     `inspect_dialect()` gains a `decomposition` field for composites only
     (L97-L119, L237-L240).
- **Filter scope rule (new design).** A filter scopes the later steps of its
  own pipeline. A nested pipeline without `data=` inherits the parent's
  filtered stream and ANDs its own; one with `data=` (Join/Union children)
  reads its own source, so parent filters do not reach it
  (`...briefing.md:L48-L56`; worked rule `...plan-a.md:L237-L300`). A filter
  is `kind=static` and a new emission category `row-filter`; it never adds a
  layer (`...plan-a.md:L30-L55, L284-L286`).
- **Distinct filter.** `keep="first"|"last"|"none"`, ordered by the framework
  PK; PK excluded from comparison; NULL equals NULL; `subset=[]` is an error
  (`...briefing.md:L81-L95`). SQL is `row_number()` or `count()` windows per
  partition (`...plan-b.md:L848-L900`).
- **Why it does not touch the baseline defect.** No plan here discusses the
  order in which learning steps read each other's output. Direction B is about
  *what a composite is made of*, not *what it fits on*. The one related residue
  is an open question kept alive: "AST de-dup across composite siblings"
  (`...plan-e.md:L434-L440`), i.e. the same aggregate being computed twice by
  `Std` and `Var`. The war room calls the duplication "P-strict" and defers it.
  **(inf.)** This is the one place the war room reached the "share a statistic"
  question and punted.
- **Obstacle in practice.** The plan-reviewer found 12 shared anchors matching
  byte for byte (`...addendum.md:L11-L12`), which shows the cost of
  specification by cross-plan string agreement: names (`row-filter`,
  `decomposes_into`, `StandaloneModifierError`) had to be policed across seven
  plans.

## Engines: ClickHouse and connections

- **Representation.** SQL is built as sqlglot ASTs and transpiled per dialect;
  each step's `natives` dict picks per dialect between `high_node` (native
  function), `low_node` (portable polyfill, e.g. median by `ROW_NUMBER`),
  `alias_node` (engine-specific alias, Postgres `PERCENTILE_CONT`) and
  `unsupported` (`...clickhouse-integration.md:L83-L110`;
  `...warnings-subsystem.md:L115`). `engine_alias` is a cascading opt-in that
  chooses the alias path and warns (`...q-io-phase-2-briefing.md:L112-L113`).
- **ClickHouse facts worth keeping.** Native: sum/avg/count/min/max,
  `stddevPop`, `varPop`, `corr`, `covarPop`, windows since 21.8 (L45).
  Approximate-by-default `quantile`/`median`; `topK`/`anyHeavy` are not a mode
  (L48-L49). Type map (L57-L77). No DuckDB `clickhouse_scanner` in core or
  community; only read-only table functions (`chsql`, `chsql_native`); the MySQL
  wire workaround fails on `START TRANSACTION` with Code 62;
  `clickhouse-connect` is the only route (L35). `chdb` is a future note.
- **Engine model.** Execute on the user's database through its driver; if the
  dialect lacks something, either polyfill with `low_node` or run the whole
  pipeline in DuckDB with the user's database attached (`engine="duckdb"`,
  needs a scanner) (`...plan-d.md:L240-L268`). ClickHouse is the first dialect
  where the second route does not exist, so it is "native-compilation-only"
  (`...clickhouse-integration.md:L125`).
- **Connections.** See Plans above. Two points worth noting. First, the
  connection rides in the data object, so `sq.Join` of data from two engines
  "falls out for free" through DuckDB attach (`...plan-d.md:L255-L258`); this
  matches the April federated spec the baseline names. Second, a `DataRef`
  holds a live connection and is "unpicklable", so `Pipeline.save` strips it
  and `load` returns a pipeline with `data=None` until rebound
  (`...q-io-phase-2-plan-b.md:L795-L803`), one more cost of coupling data and
  fitted pipeline.
- **Never tested.** Nothing here ran against ClickHouse or any engine. Five
  "integration-test-gated" open questions remain (OQ1 to OQ6: sqlglot emission
  of `quantile(p)(x)`, `STDDEV_POP` alias, `covarSamp` alias, tz detection, the
  `LowCardinality(Nullable)` unwrap order)
  (`...clickhouse-integration.md:L135-L140`).

## Size and adherence

| Plan set | Plan lines | Spec delivered (inf. from OLD) | Ticked |
|---|---|---|---|
| Q-IO phase 2 (6 files) | 7,915 | `core/io.md` 1,470; ~2,900 lines over 47 files | none |
| Clickhouse | 198 | `backend/clickhouse.md` 594 | none |
| Connections | 260 | 10 files, 3,822, plus 2 rules 359 | none |
| Step composability (9 files) | 5,777 | `filters/` 1,093 plus edits | none |
| Warnings (7 files) | 3,472 | `core/warnings.md` 476, `rules/warnings.md` 204 | none |

- Whole batch 17,622 lines. Of the 24 files, 22 are plans for edits, and a
  typical entry is "Edit B-3.4: current state, new state, rationale, cross-refs
  created" (e.g. `...q-io-phase-2-plan-b.md:L896-L901`). Plan-e of the
  warnings arc is 606 lines to repoint one cross-reference row in each of 13
  files (`...warnings-subsystem-plan-e.md:L245-L360`).
- Adherence to *its own method* was high (anchors byte-matched, checker clean,
  addendum overrides respected). Adherence to *plan text* was lower: plans were
  "frozen" and then amended by addenda ("this addendum wins",
  `...warnings-subsystem-execution-addendum.md:L6-L8`; "overrides any stale plan
  text", `...step-composability-execution-addendum.md:L8`), and no plan was
  updated to match. The stale plan text is the record.
- The deterministic checker is the best outcome. After 6 verification rounds a
  11-agent "done and intact" probe could not settle whether drift was real; a
  script then settled it, with the lesson "it was a tool mismatch
  (deterministic property hunted with probabilistic LLM sampling)"
  (`OLD:TODO.md:L383`). That is a transferable finding.
- Plan size against product: the plans (17.6k lines) are about twice the new
  spec text they produced, and the spec text is itself about the whole
  deliverable. No executable behaviour was produced in this batch.
  **(inf.)** a reader who wants to know what the code should do reads the
  specs, never the plans, which would have made the plans a pure cost once the
  specs landed.
- Agent cost: briefings count agents by the dozen (7 Opus runs, then 9 to 15;
  17 investigators in 3 waves for warnings; 4+2+4 for ClickHouse)
  (`...q-io-phase-2-briefing.md:L444-L450`;
  `...warnings-subsystem.md:L22-L27`; `OLD:TODO.md:L381`).

## New against the baseline

- **The war room's output was spec text only.** The baseline says the April
  repo made "593 commits and no code"; this batch shows the same condition
  persisted through June (26 Apr to 13 Jun, per the task brief) with a larger
  corpus and a script as the only code.
- **Filter scope by data ownership.** Whether a nested pipeline inherits the
  parent's `WHERE` is decided by "does the child own `data=`", not by "does it
  hold a filter" (`...briefing.md:L48-L56`). Relevant to how fit sees rows.
- **Composite support derivation.** A composite is supported on a dialect only
  if every constituent is, derived at class definition
  (`...briefing.md:L107-L116`). Small, cheap, and useful for engine coverage.
- **Warnings model.** One class is both Python warning category and record,
  with a stable declared `code`, a derived `doc_url`, a silent-vs-warn rule for
  pure-equivalence substitutions, and a hard line between display config and
  suppression (`...warnings-subsystem.md:L149-L168`).
- **The honest-gap pattern.** Engine specs have a section that states what a
  dialect cannot do (ClickHouse has no DuckDB route) rather than a fictional
  path (`...clickhouse-integration.md:L35, L125, L184`).
- **Output-mode contract.** Nine named output modes, with `duckdb` and
  `arrow.stream` forcing DuckDB execution, is a design for "larger than
  memory" that the baseline does not record.
- **Zero-pass fit rule.** An all-static tree runs as one combined query with 0
  learn passes (`...plan-a.md:L781`). The baseline records the one-query
  property only for learning steps.

## Contradicts the baseline

- **Fit statistics on written-back step instances.** The baseline says fitted
  state "must live apart" from step objects. These plans keep the opposite:
  the compiler "writes each value to the step instance"
  (`...q-io-phase-2-plan-b.md:L897`), keyed by `id(step)`, and saving keeps
  the learned state with the step.
- **The staged fit is already a design, with a caveat.** The baseline says the
  boundary rule had to be invented as "a learning step reads a value an
  earlier step changed". The war room's text has an equivalent layer rule
  ("dependency depth of the step graph after the inspector classifies each step
  as static or dynamic", `...step-composability-plan-a.md:L176-L177`), so the
  idea is older than the baseline implies. **(inf.)** The defect may be a
  matter of how the inspector defines "dependency", which is not in this batch.
- **sqlglot "syntactic, not semantic".** The baseline says portability was never
  tested beyond parsing. This batch is consistent but adds a nuance: tiers
  (`high_node`/`low_node`/`alias_node`) are an explicit attempt at *semantic*
  portability, e.g. exact median by window versus ClickHouse's approximate
  `quantile` (`...clickhouse-integration.md:L48`). They were still specified
  rather than run, so the claim stands for evidence, not for intent.
- **Ordering rows by a created key.** The baseline lists no such concept. The
  PK-as-`row_number() OVER ()` rule means output order is only meaningful for
  a deterministic source; `keep="first"` relies on it
  (`...step-composability-plan-b.md:L848-L870`). That is a hidden dependency of
  Direction A on an unordered window, nothing the plan tests.

## Confirms the baseline

- **Process outgrew the product.** 17,622 lines of plan, no tick boxes, and a
  checker script as the only code; "plans, standards, skills and tooling
  outgrew the product" is shown here at sharper scale.
- **Status kept by hand and drifting.** Plans left at `draft`, TODO line numbers
  cited three different ways, file counts 44/42/47, "four dialects" stale after
  the fifth (`...clickhouse-integration.md:L21`) are all hand-typed numbers that
  went wrong.
- **Review sweeps find real bugs.** The plan-reviewer found a dead-link failure
  in plan g (`...step-composability-execution-addendum.md:L20-L27`); the
  un-blinded checker found a `conn=` token violation
  (`...connections-layer-authoring.md:L140`); the severity literal drifted
  between slices (`...warnings-subsystem-execution-addendum.md:L11-L16`).
- **`y`/target and sklearn-parity.** Not touched here: no plan mentions
  scikit-learn comparison tests, parity gates, or `y` handling. **(inf.)** The
  validation gap in the baseline holds: "validation" in these plans means
  link and token checking of Markdown.
- **sqlglot everywhere, cross-engine through DuckDB.** The ATTACH route to
  other databases is the same federated idea the April repo had.

## Worth keeping

- **Pattern:** briefing pack with locked decisions and non-overlapping file
  ownership per slice, a meta-review checking shared names byte for byte, a
  frozen addendum, commits per dependency order, a deterministic checker run
  before every commit (`...step-composability-execution-addendum.md:L92-L120`).
  Keep the discipline, drop the volume.
- **Deterministic reference checker** (dead links, banned tokens, heading
  anchors) as the single gate. Adopt for `docs/` early.
- **ClickHouse facts:** support table, type map, quirks, gap disclosure, and
  the open questions to test on a live server
  (`...clickhouse-integration.md:L45-L79, L135-L140`).
- **Connection design points:** BYO ownership, connection in the data object,
  isinstance detection, version floor with `on_older`, no `natives` on adapters.
- **Filter scope rule** and its `data=` ownership lever; **Distinct** semantics
  (PK excluded from comparison, NULL equals NULL).
- **Warnings class model:** declared stable code, structured record equals
  category, stdlib suppression (no private registry).
- **Corrections block pattern:** a short authoritative "post-dispatch
  corrections" at the top of a briefing is easier to audit than silently
  rewriting (`...clickhouse-integration.md:L12-L21`), but fix the body next.
- **Plan-time check of a premise:** "verify, don't assume" before dispatch (the
  ClickHouse sweep disproved four assumptions).

## Guard against

- A plan whose product is a spec of a spec. New workflow: a plan task must end
  in a test that fails first, not a cross-reference that resolves.
- Plans never closed: no ticks, `draft` forever, addenda that "win". Update or
  delete the plan when work lands (the new workflow already puts plans in
  `docs/plans/` per `docs/architecture/workflow.md`).
- Parallel plan-writers that restate one lock in seven files and then need a
  meta-reviewer to byte-match 12 anchors. One document per decision.
- Locking before checking. The `conn=` kwarg, `core/connections/` path,
  `AliasSubstitutionInfo`, `sq.Distinct`, and the ClickHouse assumptions were
  all changed after being "locked" and sometimes after plans were written.
- Hand-typed counts, line numbers and dialect counts in plans and docs.
  Generate or omit.
- Probabilistic review of a deterministic property (six rounds). Write the
  script first.
- Learned values written back to shared step objects and saved with them;
  live connections inside a saved object.
- Specifying SQL by prose for six dialects with nothing executed. Run one
  dialect (DuckDB) before writing tiers for the others.
- Silent fit-time assumptions in filters: stating the scope rule without a test
  that statistics are computed on the filtered stream.

## Files covered

Legend: [x] read in full; [~] read by goals, headings, reasoning, open
questions and selected edits (lettered plans are mostly edit blueprints).

- [x] `OLD:plans/2026-05-06-q-io-phase-2-briefing.md` (450): 12-class error
  lineage, 7 invariants, slicing, out-of-scope list.
- [~] `OLD:plans/2026-05-06-q-io-phase-2-plan-a.md` (1359): `core/io.md`
  greenfield; PK lifecycle, 9 outputs, Join/Union fit-time read.
- [~] `OLD:plans/2026-05-06-q-io-phase-2-plan-b.md` (1396): ten core files;
  compiler distribute step, save/load `data=` wart read.
- [~] `OLD:plans/2026-05-06-q-io-phase-2-plan-c.md` (1514): rules and error
  taxonomy edits; headings and open questions only.
- [~] `OLD:plans/2026-05-06-q-io-phase-2-plan-d.md` (1401): backends, READMEs,
  template; reasoning and backend template edits read.
- [~] `OLD:plans/2026-05-06-q-io-phase-2-plan-e.md` (1795): idea-file split
  and patches; headings and reasoning only.
- [x] `OLD:plans/2026-06-07-clickhouse-integration.md` (198)
- [x] `OLD:plans/2026-06-07-connections-layer-authoring.md` (260)
- [x] `OLD:plans/2026-06-07-step-composability-authoring-briefing.md` (270)
- [x] `OLD:plans/2026-06-07-step-composability-execution-addendum.md` (120)
- [~] `OLD:plans/2026-06-07-step-composability-plan-a.md` (624): filter
  mechanics; reasoning and Filter-step semantics read.
- [~] `OLD:plans/2026-06-07-step-composability-plan-b.md` (1194): `filters/`
  family; headings, learned-state edit and Distinct AST read.
- [~] `OLD:plans/2026-06-07-step-composability-plan-c.md` (555): Direction B;
  reasoning and locked-decision section read.
- [~] `OLD:plans/2026-06-07-step-composability-plan-d.md` (878): error classes
  and surfaces; reasoning and headings only.
- [~] `OLD:plans/2026-06-07-step-composability-plan-e.md` (574): idea-file
  retirement; reasoning and one edit read.
- [~] `OLD:plans/2026-06-07-step-composability-plan-f.md` (632): orphan
  cross-reference fixes; reasoning and headings only.
- [~] `OLD:plans/2026-06-07-step-composability-plan-g.md` (930): aggregate
  rename; reasoning and headings only.
- [x] `OLD:plans/2026-06-13-warnings-subsystem.md` (359)
- [x] `OLD:plans/2026-06-13-warnings-subsystem-execution-addendum.md` (110)
- [~] `OLD:plans/2026-06-13-warnings-subsystem-plan-a.md` (609): headings only.
- [~] `OLD:plans/2026-06-13-warnings-subsystem-plan-b.md` (649): headings only.
- [~] `OLD:plans/2026-06-13-warnings-subsystem-plan-c.md` (424): headings only.
- [~] `OLD:plans/2026-06-13-warnings-subsystem-plan-d.md` (715): headings and
  frontmatter only.
- [~] `OLD:plans/2026-06-13-warnings-subsystem-plan-e.md` (606): headings and
  frontmatter only.

Outside the batch, read for execution evidence only: `OLD:TODO.md:L376-L384`,
directory listings of `OLD/projects/sqlearn/` and line counts of the spec
files named above.
