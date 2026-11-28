---
type: note
tags: [sqlearn, redesign, multi-dialect, war-room, fit, sqlglot]
summary: "Analysis of the April-June 2026 sqlearn war-room work: why the multi-dialect redesign happened, how fit layers, learned state and engine aliases were decided, a"
related: []
mdindex: [type=edb465, tags=f903a9, summary=f95dff]
---
# Batch A: direction and the redesign

The war room is GitHub `glaucis/sqlearn-private` from 26 April to 13 June
2026 (ROOT `sqlearn-ecosystem/sqlearn-private`, called OLD). This batch read
its root files, the three top-level sqlearn specs, the five archived plans,
the `sqlearn-pro` and `sqlearn-website` folders, and `releases/`,
`reports/` and `coverage/`. No git command was run, so dates come from the
files themselves. Inference is marked as such. Some answers below lean on
two passages of `core/pipeline.md` and `core/inspector.md`, which belong to
batch B; they are cited but not listed under **Files covered**.

## Summary

- **The redesign was a change of scope, not a set of fixes.** On 30 April a
  war-room conversation decided to rewrite sqlearn "from a DuckDB-only system to
  a multi-dialect system"; the `sqlearn_000` code "is being wiped by the user
  separately", and its four open reports were to be flipped to `superseded`
  (`OLD:plans/archived/2026-04-30-sqlearn-multi-dialect-redesign.md:L3-L5`,
  `L376-L387`, `L434-L435`).
- **Fit keeps the old layer rule.** A layer ends only at a "dynamic" step,
  one whose SQL *shape* depends on learned values. Scalers are "static",
  so `Impute` then `StandardScale` learn in one layer, and the guide
  promises that "the layer planner batches all aggregates into one
  learn-pass query". This is the fit defect again (inference).
- **Learned state stays as Python values on the step objects**, inlined
  as SQL literals and saved as JSON. `Aggregate.ast` returns "the cached
  scalar lifted to a sqlglot `Literal`".
- **sqlglot stays at the centre, now distrusted.** On 2 May the war room
  found that sqlglot is "a syntax translator, not a semantics synthesizer"
  (MySQL `STDDEV` is population, DuckDB's is sample). It moved dispatch into
  each step: a `natives` dict per dialect picks `high_node` (native),
  `low_node` (decomposition into primitives) or `alias_node` (the engine's
  own spelling, used only when `engine_alias=True`).
- **The dialect list grew while no code existed.** It went from 4 to 5
  (ClickHouse, 7 June), with 6 more "Tier 1" engines and 3 more "Tier 2"
  engines named.
- **The API keeps the renamed verbs** (`learn`, `apply`, `learn_apply`,
  verb class names such as `StandardScale`, `OneHot` and `Impute`). It
  claims scikit-learn parity for `get_feature_names_out`, child access and
  the `numpy` default, and drops `get_params`, `set_params` and `clone`
  (`clone` is deferred to v0.2.0).
- **Validation is a per-step "Validator" agent role** (mpmath, other
  libraries, a precision file). There is still no pipeline-level
  comparison, and a dataset plan names the Kaggle API, which needs the
  network.
- **No code was written against these specs.** On 2 May releases were
  dropped because "sqlearn will be refactored and rewritten from scratch".
  Every arc that followed ends with "code implementation downstream". The
  coverage CSV says it is "generated, never hand-edited", but its generator
  "doesn't exist yet".
- **May to June was all specs.** Track A (custom steps), i18n, engine
  alias, IO and connections (8 May to 7 June), ClickHouse, step
  composability, then a warnings subsystem on 13 June. The work was
  driven by up to 28 agents a session.
- **It ended with an open backlog**: 48 pending clean-ups and a half-made
  search-engine spec. The last handoff (13 June) has no focus, holds a push,
  and says the user "will start fresh session". TODO entries continue to
  24 June.

## The redesign and why

**What triggered it.** The plan is the record of a war-room conversation on 29
and 30 April
(`OLD:plans/archived/2026-04-30-sqlearn-multi-dialect-redesign.md:L11`). Its
goal: "Rewrite sqlearn from a DuckDB-only system to a multi-dialect system with
capability-aware compilation, recursive polyfill substitution, standalone-step
execution, and pluggable backends" (`L5`). It covers the war-room specs only;
"the code in `sqlearn/` is being wiped by the user separately" (`L3`, again at
`L435`). The API spec names what it replaced: a "DuckDB-only" framing from
commit `ff48d3e`, which polyfills now supersede for "the problematic functions
that originally motivated the tightening"
(`OLD:projects/sqlearn/api-surface.md:L297-L303`). Inference: the April code
repo had narrowed to DuckDB because some functions did not port, and the
redesign reversed that narrowing instead of fixing those functions.

**How it closed the code repo's reports.** Task 5.2 flips the four active
`sqlearn_000` reports (`2026-04-29-18-26`, `18-40`, `19-00`, `20-00`) to
`status: superseded`, `resolved_by: sqlearn-multi-dialect-redesign`. It also
marks the war-room triage `2026-04-29-22-19-triage.md` superseded, its
proposed releases B1, U1 and U2 "moot under the redesign"
(`L376-L387`, `L434`). The plan leaves those boxes unticked; the
`sqlearn_000` review shows the flip was made in that repository (`a4fc0d6`).
None of the four defects (`load` dropping fields, the static/dynamic drift,
`LN` raising) was fixed in code. The redesign reworded the aggregate specs
from `"static"` to `"dynamic"` (`L348`) and documented the `LN` raise
(`L347`).

**What was locked.** Twelve decisions, "not up for re-litigation"
(`L15-L55`): one `BaseStep` base class for steps and `Pipeline`; methods
`learn_ast`/`apply_ast`, `learn`/`apply`/`learn_apply`, `inspect_dialect`,
`explain` and an `input_dialect` class attribute; three authoring flavours
(AST, SQL string, CTE string); standalone execution as `Pipeline([step])`;
"fresh learn = clean slate"; a recursive polyfill rewriter; per-dialect
support matrices; three dialect tiers; DuckDB as a fallback engine through
scanner extensions; polyfills as "sqlglot expression-tree builders, not
string templates" (`L48`); and "three dialects in play at runtime".
The plan specified about 60 file changes and dispatched spec-writer agents
for each (`L431-L436`).

**How the redesign itself was redesigned (2–3 May).** Within three days
the dispatch model changed. The 30 April design consulted each backend's
`supported_functions` list. The foundation plan of 2 May found that three
aggregate specs relied on a "free sqlglot rewrite" that does not exist:
"Sqlglot's `transpile()` is a syntax translator, not a semantics
synthesizer"
(`OLD:plans/archived/2026-05-02-engine-alias-foundation.md:L33-L74`).
Its evidence: MySQL `STDDEV` aliases `STDDEV_POP` while DuckDB's means
`STDDEV_SAMP`; MySQL has no `CORR`; SQLite's `MEDIAN` arrived only in 3.51.0;
DuckDB's `MEAN` is `AVG` elsewhere (`L48-L68`). The migration plan adds that
sqlglot 30.6.0 emits `PERCENTILE_CONT(col, 0.5)` with no `WITHIN GROUP` on
MySQL and SQLite, which those engines reject
(`OLD:plans/archived/2026-05-03-engine-alias-migration.md:L33-L36`). Three
plans followed, foundation, migration and follow-up, 28 commits in one
session (`OLD:TODO.md:L388`). The central `core/polyfills.md` catalog,
written on 30 April, was deleted on 3 May
(`OLD:projects/sqlearn/README.md:L84-L87`).

## Fit, state, SQL representation

**How fit runs.** The 30 April lock (TBD-2) is "one AST per execution
layer". A static-only pipeline is one "mega-AST", learn and apply merged
through CTEs in a single query. A pipeline with dynamic steps "typically"
takes two layers: one learn query "covering all steps including dynamics'
aggregates", then one apply query. "Independent dynamics share a layer;
layer count = dependency depth"
(`OLD:plans/archived/2026-04-30-sqlearn-multi-dialect-redesign.md:L64`).
Layer planning is the same on every dialect, and polyfills never add a
layer (`L65`). The batch B spec it points to says the learn layer has
"static stats and dynamic categories aggregated together in one query"
(`OLD:projects/sqlearn/core/pipeline.md:L158-L170`). "Dynamic" means the
step's AST *shape* depends on learned values
(`OLD:projects/sqlearn/core/inspector.md:L193`). Scalers and `Impute` are
"static" even though they learn, while every aggregate is "dynamic"
(`OLD:projects/sqlearn/README.md:L133-L136`, `L176-L190`). The custom-step
guide promises that "the layer planner batches all aggregates into one
learn-pass query"
(`OLD:projects/sqlearn-website/guides/custom-steps.md:L191-L194`,
`L449-L455`). Inference: in `Pipeline([Impute(value="mean"),
StandardScale()])` neither step adds a layer, so the scaler's mean is
learned in the same query as the imputer's and does not see the imputed
values. This is the April rule unchanged: a layer ends at a change of
shape, not at a value an earlier step changed. The guide even offers
`Impute(Median, where=…)` followed by `Impute(Mean)` "fills any remaining
NULLs" (`custom-steps.md:L1104-L1108`) without saying which data the second
mean is learned from. A pipeline of two steps standing in for one custom
step (`L1083-L1091`) is claimed equal with no test that it is.

**Who sees whose output.** Nothing in this batch states that a learning
step's aggregates read the previous steps' transform SQL. `row-filter`
steps "fold into the input of whichever layer consumes it"
(`core/pipeline.md:L137-L144`), so filters do reach fit. Inference:
fit sees row filters but not earlier column transforms.

**Learned state.** After the learn query runs, "learned values are
distributed onto the child step instances as `result_`"
(`core/pipeline.md:L162-L164`),
and the apply layer "uses those learned literals". Track A makes the
`Aggregate` class expose the value in three ways (`__format__` for f-strings,
`.ast`, `.result_`), all raising `NotLearnedError` before fit. `.ast` returns
"the *cached scalar* lifted to a sqlglot `Literal` node … NOT the original
AVG-expression formula"
(`OLD:plans/archived/2026-05-01-track-a-custom-step-authoring.md:L61-L72`).
Multi-column steps keep a dict, for example
`Impute.value.result_ == {"price": 12.50, "qty": 4.0}`
(`OLD:projects/sqlearn/api-surface.md:L699-L707`). Saving is JSON with
"per-step `params_`, learned state, and per-step `input_dialect`". sqlglot
expressions are serialised through a node-tagged sub-schema, pickle is
forbidden, and classes resolve at load time (`api-surface.md:L633-L657`).
The sub-schema is deferred "once a real `sq.save()` round-trip surfaces
friction" (`OLD:TODO.md:L295`). State on the step objects is what broke
cross-validation in the April repo. Here `sq.Search` "wraps the pipeline
and injects fold-id columns internally" (`api-surface.md:L164-L171`), and
`README.md:L36` promises a "run cache (learned values + apply AST per
fold)". Neither says where per-fold state lives apart from the steps
(inference: unresolved). Saved pipelines are dialect-neutral: "train on
DuckDB, deploy to Postgres" (TBD-4,
`2026-04-30-sqlearn-multi-dialect-redesign.md:L66`).

**SQL representation and the "engine alias".** All SQL is a sqlglot AST in an
`input_dialect`, default `"duckdb"`, transpiled to the target at the end
(`OLD:projects/sqlearn/redesign-overview.md:L9-L18`, `L20-L33`). From 2 May each
step declares
`natives: dict[dialect, "high_node" | "low_node" | "alias_node" | "unsupported"]`.
The resolver consults that dict, not the backend's function list
(`redesign-overview.md:L140-L166`;
`OLD:plans/archived/2026-05-02-engine-alias-foundation.md:L115-L147`):

- `high_node`: the step's own preferred node, used as is (`MEDIAN` on
  DuckDB).
- `low_node`: a decomposition into portable primitives, written inline in
  the step's spec, never in a shared helper ("P-strict",
  `OLD:plans/archived/2026-05-03-engine-alias-migration.md:L113-L126`).
- `alias_node`: the engine's own different spelling of the same operation
  (`PERCENTILE_CONT(0.5) WITHIN GROUP` for `MEDIAN` on Postgres). It is used
  only when the user passes `engine_alias=True`, a universal keyword that
  cascades from `Pipeline` to steps with `None` meaning "inherit", and it
  emits an `info` warning (`engine-alias-foundation.md:L115-L139`,
  `L554-L573`). An alias whose semantics differ from the step's is rejected
  by the step's author, so `Std` never uses MySQL's `STDDEV` (`L204-L220`).
- The resolver recurses until a fixed point and then calls sqlglot only
  "for syntax-shape transpilation" (`redesign-overview.md:L163-L186`).

The consequences are on file. With the default `engine_alias=False`,
`Median` on Postgres runs the `ROW_NUMBER` decomposition rather than the
engine's native ordered-set aggregate. `Median`, `Mode` and `Quantile` read
`alias_node` for Postgres (`OLD:coverage/coverage.csv:L6-L8`). SQLite
"always polyfill[s]" percentiles, "never native, even on 3.51+", at a
stated ~1.5× cost (`engine-alias-migration.md:L127-L142`). `Mean` and `Avg`
became two separate steps, so that DuckDB users see `MEAN` and others `AVG`
(`L143-L160`). Every step must list every supported dialect explicitly,
checked against a `FRAMEWORK_SUPPORTED_DIALECTS` constant at class
definition (`engine-alias-foundation.md:L587-L611`). New dialects arrive
by pull request to the core, never as plugins, because a plugin dialect
would have no `natives` entries (`L613-L632`).

## API surface

Every `BaseStep`, `Pipeline` and standalone step exposes `learn(data)`
("populate state, return self"), `apply(data, *, output="numpy")`,
`learn_apply`, `inspect_dialect(target)` (never raises) and `explain()`
(`OLD:projects/sqlearn/api-surface.md:L127-L157`). `learn_apply` is
"sklearn's `fit_transform` equivalent"
(`OLD:plans/archived/2026-04-30-sqlearn-multi-dialect-redesign.md:L23`). So
the April renaming stands: `learn`/`apply`, verb class names "`Scale`, not
`Scaler`; `OneHot`, not `OneHotEncoder`" (`api-surface.md:L101-L104`),
`BaseStep` in place of `BaseEstimator`, and `summary`
(`OLD:projects/sqlearn/README.md:L33`). The scikit-learn features kept are
called "parity": `get_feature_names_out()` plus an `output_columns`
property, `pipe[0]`, `pipe["name"]`, `pipe.steps` and `named_steps`
(`api-surface.md:L944-L958`), `numpy` as the default output because
"sklearn parity is the primary driver" (`L372-L386`), and fresh-learn
"matches sklearn `pipe.fit()`"
(`OLD:projects/sqlearn/redesign-overview.md:L98-L101`).
`get_params`, `set_params` and `clone` do not appear; `pipeline.clone()` is
a v0.2.0 helper (`api-surface.md:L896-L898`).

There is no `y`: `learn(data)` takes one data reference. Train and
validation splits are `sq.Search`'s concern (`L164-L171`), and the
pipeline's `target_` became "polymorphic (str OR list)"
(`2026-04-30-sqlearn-multi-dialect-redesign.md:L158`). Other additions:
run-now constructors (`sq.Mean(data, "price")` runs at once,
`api-surface.md:L173-L198`); a four-form value ladder (`value=42`,
`"mean"`, `sq.Mean()`, `sq.Quantile(q=0.5)`, `L675-L697`); 11 selectors with
`|`, `&` and `~` (`L725-L776`); nine output modes (`L355-L370`);
`sq.Join` and `sq.Union` (`L466-L586`); `sq.Search` with pluggable engines
(`L404-L464`, grid default locked on 24 June, `OLD:TODO.md:L90-L92`); and
29 public error classes (`api-surface.md:L801-L828`). The default custom
step is six lines, with a framework-owned `__init__` and `setup()`, and
`accepts=ANY` by default (`track-a-custom-step-authoring.md:L45-L53`).
Pairwise multi-column keywords and per-pair `where=` "ship v0.1.0 — no v0.2
deferral. Per principle 7" (`L85-L100`).

`OLD:CLAUDE.md:L12-L34` explains this growth: "Principle 7 — Every user
matters; implementation complexity is cheap … 500 lines of framework code
that solve a real user need is not a price worth refusing to pay". If a
recommendation leans toward "only X% need this", the instruction is to
"STOP". A sweep on 1 May found 22 "violation candidates" of this principle
across the specs (`OLD:TODO.md:L212-L216`).

## Validation

This batch says little about validation; `rules/validation.md` belongs to batch
E. The development loop has three agents per step: an Author, a Hardener that
adds adversarial tests but "does NOT modify step behavior", and a Validator
("smaller model OK, e.g. Sonnet") that writes "canonical impl in mpmath,
comparison harness against the named libraries, expected-precision file, JSON
report" (`OLD:WORKFLOWS.md:L15-L37`). The same three roles ran in `sqlearn_000`.
The migration plan leans on "the validator's expected-precision row" to cover
numerical drift once shared helpers are gone, and the SQLite polyfill's
correctness (`engine-alias-migration.md:L113-L142`). Cross-engine equality is
never tested: nothing compares a step's `low_node` with its `high_node` on real
engines. The follow-up plan's "end-to-end verification" checks only that spec
files mention each other
(`OLD:plans/archived/2026-05-03-engine-alias-followup.md:L884-L930`). Its
scenario calls `pipe.learn(conn, dialect="postgres")` (`L894-L899`), which the
API spec forbids: `learn` takes a data reference and has no `dialect=`
(`api-surface.md:L127-L141`, `redesign-overview.md:L53-L56`). Open gaps include
"Dataset access mechanism — kaggle API setup, download/cache directory"
(`OLD:inbox.md:L101-L104`), which would need the network.

## May to June

The war room's own record of completed arcs (`OLD:TODO.md:L374-L390`) and
its plans give this sequence:

| Dates | Arc | Output |
|---|---|---|
| 29–30 Apr | Multi-dialect redesign | overview, core, backend and polyfill specs; 16 leaf specs swept |
| 1 May | Track A, custom-step authoring | 5 specs, a 1,710-line tutorial (`track-a…:L19-L27`) |
| 1–2 May | Principle-7 sweep; i18n sweep | 22 violation candidates; `_()` wrapping everywhere |
| 2–3 May | Engine alias, 3 plans | `natives`, `engine_alias`, `coverage.csv`; polyfill catalog deleted |
| 3 May | Universal step contract; composability brainstorm | 8 agents |
| 6 May – 7 Jun | IO (Q-IO) plans, execution, six verification rounds, a link checker | ~2,900 lines across 47 files (`L383-L384`) |
| 7 Jun | Connections layer; ClickHouse | 13 files; 5th dialect (`L381-L382`) |
| 8 Jun | Step composability A and B | filter steps, `decomposes_into` (`L380`) |
| 13 Jun | Backlog audit; warnings subsystem | 17 investigators, 15 locks, 8 commits (`L378-L379`) |
| 24 Jun | Search-engine spec (open) | grid default locked (`L90-L97`) |

**Was code written?** Not in this repository, which says "no Python here,
ever" (`OLD:README.md:L212`), and no plan shows code. On 2 May release
authoring was removed "per user direction — releases are off-table because
sqlearn will be refactored and rewritten from scratch"
(`OLD:plans/archived/2026-05-03-engine-alias-followup.md:L31-L36`;
`OLD:TODO.md:L292`). The release lifecycle that the operating model is
built around (`OLD:README.md:L146-L178`) therefore never ran: `releases/`
holds only two READMEs. Track A's code is "pending … tracked in the
`sqlearn/` code repo" (`track-a-custom-step-authoring.md:L3`, `L29-L39`).
The IO plans were "FROZEN for downstream execution-session dispatch against
sqlearn code repo" (`OLD:TODO.md:L384`). The warnings handoff repeats that
"the sqlearn CODE implementation is downstream/separate, as with every
prior arc" (`OLD:handoff.md:L19`). The coverage tool and its CI check
are two open TODO rows "sqlearn-side" (`OLD:TODO.md:L112-L121`). The CSV
that claims to be generated (`OLD:coverage/README.md:L11-L20`) has no
generator: "`generate_coverage.py` doesn't exist yet" (`OLD:TODO.md:L132`).
Inference: it was written by hand, and has no ClickHouse column for the
same reason. Whether the six commits that `sqlearn-ecosystem/sqlearn` has
beyond `sqlearn_000` hold code is step 8's question.

**How it ended.** The last handoff, dated 13 June, says: no active focus;
eight commits unpushed, "push is HELD"; the user drove with "go go go" and
"≈28 agents this session"; and the user "will start fresh session" and is
"context-switching" (`OLD:handoff.md:L1-L27`). `TODO.md` goes on to 24 June.
On that day the warnings commits were pushed (`L378`), and a new focus
opened on the search-engine spec, with grid as the default engine
(`L90-L97`, `L110-L111`). The file ends with 48 pending clean-ups (`L124`),
11 open Principle-7 items (`L214-L239`) and a deferred, never-run audit of
the whole core spec layout (`L299-L358`). Nothing marks a decision to stop.
Inference: the war room was left mid-arc, and the next attempt
(`sql_learn_test`) began on 21 August.

## New against the baseline

- The redesign's cause was a change of scope (multi-dialect) decided in
  conversation, not the reports; the reports were closed by reclassifying
  them (`multi-dialect-redesign.md:L3-L5`, `L376-L387`).
- A per-step dispatch table, `natives`, with three node kinds and an opt-in
  `engine_alias` keyword: the most worked-out multi-engine design of any
  attempt (`engine-alias-foundation.md:L115-L220`).
- Measured sqlglot failures: MySQL `STDDEV` is population; MySQL has no
  `CORR`; sqlglot 30.6.0 drops `WITHIN GROUP`; SQLite `MEDIAN` arrives in
  3.51.0 (`engine-alias-foundation.md:L48-L68`,
  `engine-alias-migration.md:L33-L60`). Not rechecked here.
- An alias whose semantics differ is rejected by the step author, and opting
  in is "a preference, not a requirement"
  (`engine-alias-foundation.md:L204-L220`).
- Static or dynamic is now the *shape* question; aggregates are "dynamic",
  scalers and imputers "static". Layers count dependency depth among dynamic
  steps only.
- A run-now constructor, a four-form value ladder, multi-column pairing
  forms and a six-line custom step (`track-a-custom-step-authoring.md`).
- Warnings designed as a subsystem: three message forms, five verbosity
  levels, a severity ladder (`engine-alias-followup.md:L1064-L1122`).
- Explicit tiers: free MIT core, a paid `sqlearn-pro` with an agent and a
  "ComfyUI-style" canvas (`OLD:projects/sqlearn-pro/README.md:L5-L12`).
- A deterministic link and anchor checker replaced LLM sweeps for drift.
  The war room's own finding was that "drift never converges" because a
  "deterministic property [was] hunted with probabilistic LLM sampling"
  (`OLD:TODO.md:L383`).

## Contradicts the baseline

- The baseline says the April repo "declared `learn`/`apply` settled"
  and implies the matter was then open. The war room kept the renaming and
  added "sklearn parity" only where convenient; no bridge back to `fit`
  was specified.
- The baseline's federated design reached other engines through DuckDB
  `ATTACH`. Here DuckDB-as-engine is only a fallback; the main path is
  native SQL per dialect, and ClickHouse has "no DuckDB fallback"
  (`OLD:TODO.md:L381`).
- Inside the war room: the CSV says "generated", but no generator exists
  (`coverage/README.md:L11` against `TODO.md:L132`). The follow-up's
  scenario uses `learn(conn, dialect=…)`, which the API forbids. The
  redesign overview's lead still describes the deleted
  `supported_functions` dispatch (`redesign-overview.md:L9-L18` against
  `L140-L150`; flagged at `TODO.md:L173-L175`). The plan says six "Tier 1"
  dialects need "no polyfills" (`redesign-overview.md:L288`), yet Postgres
  defaults to `low_node` for `Mean` (`coverage.csv:L5`).
- Against this repository: the core licence is MIT (`OLD:WORKFLOWS.md:L13`;
  ADR 0004 is Apache-2.0); a dataset plan uses the Kaggle API (ADR 0006);
  the website allows anonymous page-view analytics
  (`OLD:projects/sqlearn-website/non-goals.md:L60-L70`); and the node
  editor is a paid tier, where the overview plans a local application.

## Confirms the baseline

- The fit defect persists: shape-change layers, all aggregates batched
  into one learn pass (inference from `core/pipeline.md:L158-L170` and
  `custom-steps.md:L191-L194`).
- Learned state is Python values on the step objects, inlined as literals
  and saved as JSON (`track-a…:L72`, `api-surface.md:L633-L657`).
- sqlglot is used everywhere, and transpilation is "syntactic, not
  semantic", now written down as machinery
  (`engine-alias-foundation.md:L70-L74`).
- Portability was never executed: the coverage CSV and the "end-to-end
  verification" are both on paper.
- There is no pipeline-level parity test; validation is per step, by an
  agent role.
- `y` is not a separate argument and the target is not excluded from
  the default columns (`api-surface.md:L127-L171`).
- Process outgrew product: 410 commits and no code; status was kept in
  `TODO.md`, `handoff.md`, plans and tombstones; agent fan-outs reached 28
  agents a session.

## Worth keeping

- The finding that sqlglot translates names, not semantics, and that each
  operation must own its per-engine form. If multi-engine ever returns,
  the `natives` table with `high_node`/`low_node` is the shape, and it is
  reportable as one coverage table.
- Rejecting an engine alias whose semantics differ (MySQL `STDDEV`). An
  opt-in is a preference, never a requirement.
- `inspect_dialect()` that never raises against an execution path that
  does; structured warning records shown through Python's `warnings`.
- A deterministic checker for cross-references instead of agent sweeps.
- Run-now constructors (`sq.Mean(data, "price")`) for exploration, if
  they do not break scikit-learn's constructor rule.
- As a warning: specifications at this scale (12 dialects named, 29
  errors, 9 output modes) with no running code to test them. The design
  changed three times in a week and was never executed.

## Files covered

Root:

- [x] `CLAUDE.md`: operating rules; Principles 6 and 7; show-first rule.
- [x] `README.md`: war-room model, release and report loop, no code here.
- [x] `TODO.md`: live state to 24 June; arc tombstones; the "rewrite from
  scratch" deferral.
- [x] `WORKFLOWS.md`: three-agent loop (Author, Hardener, Validator); rest
  "TBD".
- [x] `handoff.md`: 13 June handoff; push held; no focus.
- [x] `inbox.md`: empty idea area; missing-documentation list (Kaggle,
  row identity).

`projects/sqlearn/`:

- [x] `README.md`: spec index; scope; static and dynamic classes per
  family.
- [x] `redesign-overview.md`: seed architecture; resolver cascade; tiers.
- [x] `api-surface.md`: the v0.1.0 public surface, in full.

`plans/archived/`:

- [x] `2026-04-30-sqlearn-multi-dialect-redesign.md`: the redesign plan,
  12 locks, TBD-2 to 4, report supersession.
- [x] `2026-05-01-track-a-custom-step-authoring.md`: 22 custom-step locks;
  code pending.
- [~] `2026-05-02-engine-alias-foundation.md`: reasoning, why, 13 locks,
  scope and resolved locks read; phase task lists skimmed.
- [~] `2026-05-03-engine-alias-migration.md`: reasoning, why, locks 14–17
  and the `median` entry read; other per-step entries skimmed by heading.
- [~] `2026-05-03-engine-alias-followup.md`: reasoning, CSV contract,
  Phase F and the warnings origin read; sweep phases B to D skimmed by
  heading.

Other projects:

- [x] `projects/sqlearn-pro/README.md`: paid tier stub (agent, canvas,
  notebook export).
- [x] `projects/sqlearn-website/README.md`: website scope; one guide.
- [x] `projects/sqlearn-website/non-goals.md`: static site, no PII,
  anonymous analytics allowed.
- [~] `projects/sqlearn-website/guides/custom-steps.md`: headings,
  Tier 1, the substep and layer-planner passages, Tier 3a and the
  cross-references read; the gallery skimmed.

`releases/`, `reports/`, `coverage/`:

- [x] `releases/README.md`: release lifecycle; no release files exist.
- [x] `releases/archived/README.md`: empty archive stub.
- [x] `reports/README.md`: issue and triage report model; no reports exist.
- [x] `reports/archived/README.md`: empty archive stub.
- [x] `coverage/README.md`: "generated, never hand-edited"; four CI
  invariants.
- [x] `coverage/coverage.csv`: 10 aggregate rows, 4 dialects.

No read hung or failed.
