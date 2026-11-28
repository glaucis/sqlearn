---
type: question
tags: [static-dynamic, layers, fit-execution, query-count, classification, sqlearn]
summary: "Evidence review of how earlier attempts (ducklearn, Tomosius/sqlearn, v0.4, April, war room) defined and used static vs dynamic steps and layer boundaries in fi"
related: [docs/questions/archived/earlier-attempts/static-dynamic.md]
mdindex: [type=1f5087, tags=abbb88, summary=0ca4d4]
---
# Static and dynamic steps in the earlier attempts

Evidence gathered for one design decision: how fit executes, compiling all
learning into as few SQL runs as possible, where a "dynamic" step (such as
OneHotEncoder, whose output columns are unknown until it has learned its
categories) forces a new run because the SQL after it cannot be written
before its values are known.

Paths are relative to ROOT
(`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas`),
except `sqlearn_000:` (the earlier clone at
`/private/tmp/claude-501/-Users-tomas-coding-glaucis-sqlearn/5a6cd073-9d81-4030-b10c-ac9452cc20ff/scratchpad/sqlearn_000`)
and `NOTES:`
(`/Users/tomas/coding/glaucis/sqlearn/docs/questions/earlier-attempts/`).
Everything was read only; nothing was run. "Inference" marks a conclusion drawn
from the text rather than stated in it. No read hung.

## Summary

- Every attempt from ducklearn to the war room had a static/dynamic split.
  Until the war room it meant **"has a learn query"** (dynamic = learns
  something from data; static = SQL known from constructor arguments). The
  war room turned it into **"the step's SQL shape depends on learned
  values"**, so scalers and imputers moved from dynamic to static.
- The run (layer) boundary rule was the same from ducklearn to April: a new
  layer starts **after a step that is both dynamic and schema-changing**.
  The war room restated it as "dependency depth" of dynamic steps.
- Inside a layer, every learning step reads the **layer's input**, not the
  output of earlier learning steps. Imputer then StandardScaler learn the
  scale from un-imputed data in every design and in both codebases with
  layers. Only static upstream steps are seen, and only where substitution
  was built (Tomosius code, April spec; not v0.4).
- Classification was declared by the author and trusted for built-ins
  (proved by a CI test that compared the declaration with `discover()`),
  verified once for custom declared steps, and inferred conservatively for
  undeclared steps. Several steps set the class in `__init__` from their
  arguments (Clip, StringSplit, Bin, AutoDatetime, TimeSinceEvent).
- The rule "if it cannot be proved static, treat it as dynamic: a false
  static is silent data corruption, a false dynamic costs one query"
  appears verbatim in ducklearn, Tomosius, v0.4, April and the war room.
- Query-count promises were never measured on a real pipeline: "1–3", "2",
  "3–4", "3", "2k + 1", "1–2". The code's actual count is 1 per layer for
  scalars plus 1 query per set-valued column, plus a view per boundary.
- Recorded misclassifications: FrequencyEncode and GroupAggregate are
  "static" yet compute statistics from the data being transformed;
  documents disagree on whether Mean, FrequencyEncoder, EWM and Deduplicate
  are static; DropConstant (dynamic, schema-changing) never cuts a layer in
  the worked example that shows it.
- The war room's Ordinal idea shows that the class depends on how learned
  values travel: with categories embedded as literals Ordinal is dynamic;
  with the mapping kept as a CTE joined in SQL it becomes static. OneHot
  stays dynamic whatever is done, because its column count is learned.
- The August restarts and the autumn attempt have no static/dynamic concept;
  `sql_learn` contributes a measurement that `WITH` stages keep a staged fit
  in one query fast.
- Synthesis (below): three separate properties, not one label; a run ends
  only after a step whose output **shape** is learned, and every learning
  step in a run reads its true upstream output through `WITH` stages.

## ducklearn (March, design only)

1. **Definition.** "**Static transformer:** A step whose `expressions()` or
   `query()` output is fully determined by constructor arguments alone. It
   does NOT need to see any data to know what SQL to generate"; "**Dynamic
   transformer:** A step whose `expressions()` or `query()` output depends on
   values learned from the data. It MUST run aggregate queries during
   `fit()`" (`ducklearn/docs/03-architecture.md:L436-L444`).
   Schema-changing is a separate, "orthogonal" axis: DateParts is static and
   schema-changing, StandardScaler dynamic and schema-preserving
   (`L446-L451`). "**There is no third state.** Every step is either static or
   dynamic" (`L985`). "Static ≠ inline. Static means 'no fit query needed'"
   (`L1264-L1267`).
2. **How decided.** Three tiers (`L453-L465`): built-ins declare
   `_classification` and are "Trusted. Zero inspection. CI tests guarantee
   the declaration is correct"; custom declared steps are verified once at
   first `fit()` (`L586-L621`); undeclared steps are inspected every fit
   (`L626-L646`). Criteria S1–S5 / D1–D5: static only if `discover()` and
   `discover_sets()` return exactly `{}`, `fit()` is not overridden and
   nothing raised (`L961-L983`). Constructor-dependent class set in
   `__init__` (`L526-L567`), with CI tests for both branches (`L569-L580`,
   `L1310-L1325`). Runtime guard `_FrozenEmptyParams` raises
   `StaticViolationError` when a static step reads `params_`
   (`L1080-L1143`). `sq.custom()`: "`learn=` present → dynamic, else static"
   (`ducklearn/docs/02-api-design.md:L731`). The base default is
   `_classification = None` (`ducklearn/docs/03-architecture.md:L35`).
3. **Boundary rule.** "Layer boundary = after any schema-changing dynamic
   step" (`ducklearn/docs/04-compiler.md:L190-L193`); schema change detected
   conservatively ("if we can't tell, assume YES",
   `ducklearn/docs/03-architecture.md:L904-L915`). Layer 1 reads a temp view
   of layer 0's output (`ducklearn/docs/04-compiler.md:L228-L235`).
4. **Examples.** Static: Log, Sqrt, Power, arithmetic, string, DateParts,
   Rename, Cast, Drop, PolynomialFeatures, HashEncoder, Filter, Sample,
   Normalizer, all window steps, GroupFeatures, EWM, Deduplicate
   (`ducklearn/docs/03-architecture.md:L1212-L1262`). Dynamic: Imputer, all
   scalers, KBinsDiscretizer, OneHot, Ordinal, Target, Frequency, Binary
   encoders, the Drop* selectors, SelectKBest, OutlierHandler, AutoFeatures
   (`L1269-L1295`). Parameter-dependent: StringSplit (`max_parts`),
   AutoDatetime, AutoSplit, AutoNumeric, CyclicEncode, TimeSinceEvent
   (`reference="min"`), TargetTransform (`func`), Clip (`lower="p01"`)
   (`L1297-L1309`).
5. **How values reach later steps.** Not addressed: the layer-0 query reads
   `MEDIAN(price)`, `AVG(price)`, `STDDEV_POP(price)` all `FROM data`
   (`ducklearn/docs/04-compiler.md:L214-L226`), so the scaler learns from
   un-imputed values (inference). A later layer sees earlier output through
   the temp view. Static steps "contribute zero cost" (`L210-L212`).
6. **Query counts.** "Total fit: 3-4 queries for the entire pipeline"
   (`ducklearn/docs/04-compiler.md:L238`); "1-3 SQL queries total"
   (`L265`); "Total: 2 SQL queries" for a three-step example
   (`ducklearn/docs/03-architecture.md:L1523`); all-static → 0 aggregation
   queries (`ducklearn/docs/13-testing.md:L243`). Each `discover_sets()`
   entry is its own query, so OneHot on five columns is five queries
   (`ducklearn/docs/12-milestones.md:L566-L575`). No code, no measurement.
7. **Problems.** The hard rule and its cost asymmetry: "False-positive
   'static' = data corruption. False-positive 'dynamic' = one extra cheap
   query" (`ducklearn/docs/03-architecture.md:L648-L659`). Contradictions:
   the Tier 3 code swallows any `discover_sets()` exception as `{}`
   (`L845-L849`), against S5 "no exception during any check" (`L972`), so a
   failing set query can yield "static" (inference). EWM and Deduplicate are
   listed as static inside the "Declared Dynamic" table (`L1293-L1294`);
   CyclicEncode `period="auto"` sits in the dynamic column yet is "still
   static" (`L1305`). The worked example lists Log in layer 0's notes and in
   layer 1 (`ducklearn/docs/04-compiler.md:L205-L206`). The audit example
   puts DropConstant (dynamic, schema-changing) inside layer 1 with later
   steps, against the rule (`ducklearn/docs/03-architecture.md:L1186-L1191`).
   Decision 4 says "Static/dynamic auto-detected from `discover()`"
   (`ducklearn/docs/14-decisions.md:L47`) while decision 93b makes
   built-ins declared and trusted (`L140`).

## Tomosius/sqlearn (`sqlearn-desktop`, March–April, first build)

### The design folder, `sqlearn-desktop/architecture/design/`

All fifteen files read in full. The static/dynamic and layer rules live in
`static-dynamic.md`, `classification-impl.md`, `compiler.md` and
`base-class.md`; `cv-design.md` holds the most important adjacent idea
(learned values as a relation); `testing.md`, `custom-api.md`,
`api-design.md`, `pipeline.md` and `overview.md` add tests, the custom-step
rule, temp views and logging; `column-routing.md`, `error-hierarchy.md`,
`output-format.md`, `project-database.md` and `schema.md` only name the
errors or nothing at all.

- **`static-dynamic.md`** is ducklearn's section 4.3 copied: same
  definitions (`L15-L29`), three tiers (`L40-L43`), tier detection by module
  prefix `sqlearn.` (`L47-L58`), the CI test (`L78-L105`), conditional
  classes in `__init__` (`L107-L161`), Tier 2 verify-once-and-cache
  (`L163-L204`), Tier 3 every fit without cache (`L206-L225`), the hard rule
  (`L227-L238`), the full Tier 3 code (`L247-L481`), schema-change
  detection (`L483-L538`) and the S/D criteria with "There is no third
  state" (`L540-L565`).
- **`classification-impl.md`**: schema-preserving criteria SC1–SC4, "Any
  single failure → treated as schema-changing → forces a layer boundary"
  (`L7-L18`); validation of `discover()` values (`L20-L97`); the
  `_FrozenEmptyParams` guard (`L99-L162`); the audit trail with layers
  (`L164-L223`); the built-in tables (`L225-L328`); "The `_classification`
  in `__init__` and the `discover()` return value MUST agree" (`L395-L398`);
  the summary box (`L400-L436`); and a "Future: AST-Based Classification"
  from `ducklearn1` that uses the words in a **third sense**: "Static
  indicators (SQL returns exactly one row)" versus "Dynamic indicators (SQL
  returns multiple rows)", that is `DISTINCT`, `GROUP BY`, windows
  (`L438-L469`).
- **`compiler.md`** §5.3 "Fit Resolution: Layers" (`L188-L245`): the
  boundary rule (`L194-L197`), the five-step example (`L199-L212`), the
  layer-0 query over raw `data` (`L218-L230`), the temp view for layer 1
  (`L232-L240`), "Total fit: 3-4 queries" (`L242`) and "Key insight: layers
  only matter during fit. Transform is always one SQL query" (`L245`). §5.3b
  "Three-Phase Planner" describes an `is_static` flag per step and proposes
  to "combine multiple static fit queries into one multi-CTE query"
  (`L247-L304`), calling Imputer and StandardScaler "static steps"
  (`L271-L289`), against the definition. §5.4 promises "1-3 SQL queries
  total" (`L328`).
- **`base-class.md`**: `_classification = None` default (`L37-L39`);
  "If empty AND `discover_sets()` is empty, transformer is static" (`L46`);
  `sq.custom` sets the class from `learn` (`L370-L371`); first-fit
  validation raises `ClassificationError` on a lying static declaration
  (`L471-L479`); `discover()` must be idempotent because Tier 3 calls it
  twice (`L487-L492`); the "Fit Execution Flow" puts Imputer, StandardScaler
  and OneHot in layer 0 with every aggregate `FROM 'train.parquet'` and
  claims "Total: 2 SQL queries" (`L524-L592`); sets run after all scalars,
  one query per entry, optionally `UNION ALL`ed above three columns
  (`L700-L726`).
- **`cv-design.md`**: the two "compilation strategies" (`L7-L55`): *baked*
  literals for normal fit, and *self-contained* SQL where statistics stay a
  relation, `WITH stats AS (SELECT AVG(price) ...) ... CROSS JOIN stats`, so
  "No separate fit needed" (`L25-L38`). "Two-Phase Discovery" splits
  schema-affecting learning (set-valued, from all training data, once) from
  value-affecting learning (scalars, per fold) (`L70-L86`), justified as
  "structural information", not leakage (`L111-L115`).
- **`testing.md`**: classification tests per tier, runtime-guard tests and
  integration tests such as "Dynamic step treated as static (forced via test
  mock) → results differ from correct → proves conservative fallback is
  necessary", "Pipeline with 5 static + 1 dynamic → fit runs exactly 1
  aggregation query" and "all static steps → fit runs 0 aggregation
  queries" (`L288-L334`); set-query tests (`L336-L344`); "Pipeline with
  schema-changing steps interleaved with non-schema-changing → correct
  layers" (`L408`); combinatorial classifier tests (`L43-L84`).
- **`custom-api.md`**: "`learn=` makes the transform dynamic" (`L116-L119`,
  `L172`); Level 3 is required when "the SQL structure changes based on
  discovered data" (`L182`, `L192`); its custom set example reads
  `FROM __source__` (`L258`).
- **`api-design.md`**: layer materialisation uses temp views only, never
  tables (`L326-L332`).
- **`pipeline.md`**: fit logging names "classification, aggregation queries,
  layer resolution" and shows layer-0 queries (`L209-L240`).
- **`overview.md`**: `step_info.py` holds "static/dynamic, fitted, layer,
  schemas" (`L199`); HashEncoder "zero-fit" (`L233`).

### The seven points

1. **Definition.** As ducklearn, verbatim
    (`sqlearn-desktop/architecture/design/static-dynamic.md:L15-L29`). The
   code docstring: Tier 3 "The hard safety rule: if we can't prove static
   with 100% certainty, fall back to dynamic"
    (`sqlearn-desktop/src/sqlearn/core/compiler.py:L299-L302`).
2. **How decided.** Code: `classify_step` trusts built-ins with a
   declaration, verifies custom declared steps once (cached in
   `_classification_verified`) and inspects undeclared ones
    (`sqlearn-desktop/src/sqlearn/core/compiler.py:L135-L188`, `L293-L399`).
   Built-ins declare at class level
   (e.g. `sqlearn-desktop/src/sqlearn/scalers/standard.py:L83`,
   `sqlearn-desktop/src/sqlearn/encoders/hash.py:L101`); `sq.custom` sets it
   from `learn` (`sqlearn-desktop/src/sqlearn/custom.py:L189`); `Columns` is
   always dynamic (`sqlearn-desktop/src/sqlearn/core/columns.py:L100`).
3. **Boundary rule.** "Layer boundary: dynamic + schema-changing"
    (`sqlearn-desktop/src/sqlearn/core/compiler.py:L541-L552`); the design
   says so too, adding "Static schema-changing steps (e.g., DateParts ...)
   do NOT create layer boundaries" and "Adjacent same-schema dynamic steps
   share a layer"
    (`sqlearn-desktop/architecture/planning/performance.md:L125-L129`).
4. **Examples.** As ducklearn, with code values listed in
   `sqlearn-desktop/src/sqlearn/**`: FrequencyEncoder is dynamic
   (`sqlearn-desktop/src/sqlearn/encoders/frequency.py:L109`), unlike v0.4;
   windows, Filter, Sample, Deduplicate, Lookup static
   (`sqlearn-desktop/src/sqlearn/features/window.py:L127`,
   `sqlearn-desktop/src/sqlearn/ops/filter.py:L72`,
   `sqlearn-desktop/src/sqlearn/data/lookup.py:L116`). Parameter-dependent list
   in `sqlearn-desktop/architecture/design/classification-impl.md:L316-L328`.
5. **How values reach later steps.** The one attempt whose code substitutes
   static upstream expressions into later aggregates:
   `_substitute_columns` turns `AVG(price)` into `AVG(price * 2)`
    (`sqlearn-desktop/src/sqlearn/core/compiler.py:L572-L597`); static steps
   compose `running_exprs` forward, dynamic steps do not
   (`L705-L761`, especially `L736-L749`). Set queries get no substitution
   and read the raw layer source (`L749`, `L653-L700`). Design:
   `AVG(LN(price + 1))` in one query
    (`sqlearn-desktop/architecture/planning/performance.md:L56-L82`) and "All
   dynamic steps in the same layer share one aggregation query" reading raw
   `price` (`L84-L104`). A later learning step **does not** see an earlier
   learning step in the same layer (NOTES:`tomosius-sqlearn/notes/B-core.md`,
   "Dynamic then dynamic, same layer: **no**"). Static `query()` steps
   (Filter, Sample, Lag) are skipped in fit (`compiler.py:L741`), so they are
   invisible to their own layer's fit. Between layers, a
   `CREATE TEMPORARY VIEW __sq_layer_i__` of that layer's steps.
   The fix was written down and parked as an optimisation: "Cross-layer
   batching uses CTE subqueries to resolve dependencies: `WITH imputer_stats
   AS (SELECT MEDIAN(price) ...) SELECT AVG(COALESCE(price, (SELECT
   price_median FROM imputer_stats)))`"
    (`sqlearn-desktop/ideas/active/base-features.md:L197-L207`).
6. **Query counts.** "1-3 SQL queries" for a five-step fit
    (`sqlearn-desktop/architecture/planning/performance.md:L30`); "3-4"
    (`sqlearn-desktop/architecture/design/compiler.md:L242`); "2"
    (`sqlearn-desktop/architecture/design/base-class.md:L591`). Code: 1
   `DESCRIBE`, per layer 1 aggregate query plus 1 query per set key, L−1
   views (NOTES:`tomosius-sqlearn/notes/B-core.md`, "Query count"). Not
   measured.
7. **Problems.** The ordering defect was named here and rejected only for
   CV: "StandardScaler should learn mean/std from IMPUTED data, not raw
   source"
    (`sqlearn-desktop/ideas/rejected/query-template-single-pass.md:L13-L19`),
   while the layer rule keeps Imputer and StandardScaler in one layer
    (`sqlearn-desktop/architecture/design/compiler.md:L207-L226`). The code
   swallows a `discover_sets()` exception as `{}` in Tier 2 and Tier 3
    (`sqlearn-desktop/src/sqlearn/core/compiler.py:L247`, `L364`), so a custom
   set-valued step whose set query raises is classed static (inference; the
   design S5 says otherwise,
   `sqlearn-desktop/architecture/design/static-dynamic.md:L551`). The CI
   test asserts a dynamic built-in has a non-empty `discover()`
   (`static-dynamic.md:L96-L100`, `testing.md:L292`), which a set-only step
   like OneHot would fail (inference). Tier 2 caches and Tier 3 refuses to,
   for the same reason ("could change between calls", `L221-L225`).
   Windows and GroupFeatures are static and compute over whatever rows
   transform sees (`classification-impl.md:L268-L281`). The audit example
   breaks the boundary rule at DropConstant and counts "Pipeline(6 steps)"
   over seven steps (`classification-impl.md:L174-L214`).

## sqlearn v0.4 (`sqlearn-ecosystem_old/sqlearn`, 10–12 April, code)

1. **Definition.** "A transformer is either *static* (its SQL expression is
   fully known at pipeline construction time, no database scan needed) or
   *dynamic* (it must scan the training data to learn parameters — means,
   std devs, category lists)"
   (`sqlearn-ecosystem_old/sqlearn/src/sqlearn/compiler/classify.py:L3-L5`).
   Docs: "static (no data needed) or dynamic (must learn parameters)"
   (`sqlearn-ecosystem_old/sqlearn/docs/architecture/compiler.md:L245-L246`).
2. **How decided.** Three tiers in code (`classify.py:L42-L77`); Tier 2 is
   re-verified every call (no cache) and raises `ValueError` when a declared
   static step learns (`L170-L188`); inspection treats an exception from
   `discover()` *or* `discover_sets()` as dynamic (`L134-L167`), fixing the
   Tomosius hole. The probes call `discover(columns, schema)` without the
   target (`L135`, `L163`). The documented check "overrides `learn()` →
   dynamic" (`docs/architecture/compiler.md:L303`) is not in the code.
   Constructor-dependent: `Bin` is static only for `strategy="custom"`
   (`src/sqlearn/transforms/binning/bin.py:L55`); `custom()` and `SQL()` by
   `learn` (`transforms/custom.py:L74`, `transforms/sql.py:L77`);
   `TargetTransform` copies its inner step's class
   (`transforms/target_transform.py:L57`); `Union`, `Branch`, nested
   pipelines are dynamic if any child is (`transforms/union.py:L55-L63`,
   `transforms/branch.py:L60-L79`, `transforms/nested.py:L62-L79`).
3. **Boundary rule.** "split ONLY after a dynamic step that also changes the
   schema" (`src/sqlearn/compiler/layers.py:L203-L224`), with `changes_schema
   = output.columns != current_schema.columns` (`L131-L132`). Between layers
   `CREATE OR REPLACE TEMP VIEW __sqlearn_layer_{i}`
   (`src/sqlearn/compiler/compile.py:L100-L114`).
4. **Examples.** Static: arithmetic, string, datetime, Cyclical, Drop, Cast,
   Rename, Filter, Sample, Sort, Deduplicate, windows, Interaction,
   Polynomial, Ratio, Normalize, HashEncode, **FrequencyEncode**,
   **GroupAggregate**, Lookup, MissingIndicator, Fill. Dynamic: Impute, all
   scalers, OneHot, Ordinal, Binary, Count, Target encoders, Winsorize,
   OutlierHandler, DropCorrelated, DropLowVariance, SelectKBest/Percentile
   (`_classification` lines across `src/sqlearn/transforms/**`).
5. **How values reach later steps.** Every dynamic step's `discover()` is
   called with the layer's input schema and its aggregates run against the
   layer's source (`layers.py:L180-L201`); no substitution of upstream
   expressions, so even static prefixes are not seen
    (NOTES:`sqlearn-v04/notes/B-compiler.md`,
   Summary). A later layer reads the view; from the third layer on the view
   builder replays every fitted step from identity over the previous view
   (`compile.py:L240-L287`), so earlier steps are applied twice
    (NOTES:`sqlearn-v04/review.md:L68-L70`). The next layer's schema applies
   only the cutting step's change (`layers.py:L220`), losing a static
   `Drop` earlier in the layer (inference in
    NOTES:`sqlearn-v04/notes/B-compiler.md:L103-L106`).
6. **Query counts.** "1-3 queries for an entire pipeline"
   (`layers.py:L8-L9`); "3–4 queries ... regardless of step count"
   (`docs/architecture/compiler.md:L196`); "1–3 SQL queries total"
   (`L358`). Actual: 1 `DESCRIBE`, one aggregate query per layer, one
   `DISTINCT` per set parameter, N−1 views, plus lazy `GROUP BY` queries for
   TargetEncode; "1-3" holds only without set parameters
    (NOTES:`sqlearn-v04/notes/B-compiler.md:L149-L154`). Layer tests are
   planning-only, so the end-to-end count was never measured.
7. **Problems.** The hard rule: "If the compiler cannot prove with 100%
   certainty that a step is static, it MUST treat it as dynamic"; false
   static → "silent data corruption", false dynamic → "negligible"
   (`docs/architecture/compiler.md:L313-L322`). FrequencyEncode and
   GroupAggregate are "static" but compute statistics over the data being
   transformed (`transforms/encoders/frequency_encode.py:L53`,
   `transforms/group_aggregate.py:L74`;
    NOTES:`sqlearn-v04/notes/C-transformers.md:L98`,
   `L154`, `L281`). The docs still describe combining "Multiple static
   steps' aggregates" (`docs/architecture/compiler.md:L231-L232`). The review's
   verdict: "any step whose *values* a later dynamic step reads must be in
   an earlier stage, or the later step's aggregates must be composed over
   the upstream expressions"
    (NOTES:`sqlearn-v04/notes/B-compiler.md:L329-L334`).

## April planning repo (`sqlearn-ecosystem_old/sqlearn-private`, specs)

Paths below start
`sqlearn-ecosystem_old/sqlearn-private/_old/projects/sqlearn/`.

1. **Definition.** Specs use the v0.4 meaning: the tables are headed
   "Declared static (no fit query needed)" and "Declared dynamic (needs fit
   query)" (`src/compiler/classify.md:L310`, `L337`); "**Static** means 'no
   fit query needed'" with four quadrants against inline/CTE
    (`src/compiler/classify.md:L375-L388`). A **third tier, `hybrid`**, is a
   frontmatter value for six specs whose class depends on configuration or
   children: `custom`, `SQL` (by `learn=`), `Bin` (by strategy),
   `TargetTransform` ("inherits from the wrapped transformer"), `Union` and
   `Branch` ("If any branch is dynamic ... the Union is dynamic")
   (`src/transforms/custom.md:L5`, `L23-L24`; `src/transforms/sql.md:L5`,
   `L77-L83`; `src/transforms/binning/bin.md:L5`;
   `src/transforms/target_transform.md:L5`, `L64-L67`;
   `src/transforms/union.md:L5`, `L48-L51`; `src/transforms/branch.md:L5`,
   `L68`). Counts: 52 static, 19 dynamic, 6 hybrid
    (NOTES:`sqlearn-private-april/notes/C-transform-specs.md:L31-L32`).
2. **How decided.** The same three tiers and S1–S5 / D1–D5
    (`src/compiler/classify.md:L32-L190`), conditional classes in `__init__`
   (`L106-L150`), the guard (`L190`), and a CI "classification audit" that
   "walks every built-in transformer and verifies its `_classification`
   declaration matches the contract table" and fails when a new built-in is
   missing (`tests/src/_shared/classification_audit.md:L8-L26`).
3. **Boundary rule.** "A layer boundary is placed after a pipeline step **if
   and only if** both of these hold: 1. The step is **dynamic** ... AND 2. The
   step **changes the schema**"; "**Static schema-changing steps do NOT
   create a boundary**"; "**Dynamic non-schema-changing steps do NOT create a
   boundary.** `Impute`, `Scale`, `MinMaxScale` — ... Their contributions
   merge into the layer's single batched query"
    (`src/compiler/layers.md:L32-L52`).
   Test spec: "`is_dynamic AND output_schema_differs_from_input`", with
   `test_static_schema_changing_no_boundary` as "the counter-intuitive case"
   (`tests/src/compiler/layer_planning.md:L125-L148`). The v0.5 plan would
   have frozen this rule as must-pass tests
    (NOTES:`sqlearn-private-april/notes/A-direction.md:L41-L44`).
4. **Examples.** As v0.4. FrequencyEncode and GroupAggregate are `static` by
   frontmatter (`src/transforms/encoders/frequency_encode.md:L5`,
   `src/transforms/group_aggregate.md:L5`): "It's a **static** transformer
   because the frequency is computed from the data being transformed via a
   window function — no training scan is required"
   (`frequency_encode.md:L15-L19`). `CountEncode` is the learned, dynamic
   sibling (`src/transforms/encoders/count_encode.md:L5`).
5. **How values reach later steps.** Static-to-dynamic substitution is
   specified: "`AVG(price)` → `AVG(LN(price + 1))`" so "Both steps
   participate in one SQL pass" (`src/compiler/compose.md:L46-L65`), and
   static schema-changing steps need no boundary because of it
    (`src/compiler/layers.md:L150-L173`). "Within a layer, use substitution
   so every step's aggregates reference the composed input"
    (`src/compiler/compose.md:L156-L160`) can hold only for static upstream
   steps; the worked example still batches Impute and Scale in one query
    (`src/compiler/layers.md:L56-L77`). One spec does fit in stages as a CTE:
   a later step reads `collapsed`, the earlier step's output
    (NOTES:`sqlearn-private-april/notes/C-transform-specs.md:L351-L353`,
   `OLD:T/encoders/collapse_rare.md:L282-301`).
6. **Query counts.** "Total: **3 SQL queries** for a 5-step pipeline"
    (`src/compiler/layers.md:L79`); performance contract "All-static 0 ...
   k dynamic schema-changing steps 2k + 1 (approximate — each layer is at
   most 2 queries)" (`L84-L89`); against "**Total SQL queries for the entire
   pipeline: 2** ... regardless of how many steps"
    (`src/compiler/compile.md:L137-L141`). Neither was measured.
7. **Problems.** Hard rule: "If the compiler cannot prove with 100%
   certainty ..." and "false 'static' can corrupt data silently, false
   'dynamic' costs ..." (`src/compiler/layers.md:L97-L100`, `L177-L187`).
   Contradictions: `classify.md` lists `FrequencyEncode()` as dynamic
    (`src/compiler/classify.md:L351`) while its own spec is static; the
   summary output repeats the DropConstant layer error
    (`src/compiler/classify.md:L410-L430`). The review's reading:
   "static/dynamic/hybrid axis means 'has a fit query', not 'uses data
   statistics'" so the fit/transform leak is "built into the taxonomy"
    (NOTES:`sqlearn-private-april/notes/C-transform-specs.md:L40-L43`), and
   the label test "does not catch a mislabel that is consistent with the
   criteria" (`L360-L361`).

## sqlearn_000 (28–30 April, code) and its later commits

1. **Definition.** `Classification = Literal["static", "dynamic"]`:
   "`'static'` (no learn pass) or `'dynamic'`"
   (`sqlearn_000:src/sqlearn/core/step.py:L72-L73`). "Static steps are
   fitted from construction (their AST does not depend on data)"
   (`step.py:L311-L319`). "Aggregates always declare `'dynamic'`"
   (`step.py:L16-L17`, `L460-L471`).
2. **How decided.** Declared only, as a class attribute validated at class
   creation (`step.py:L142-L166`, `L236-L262`). No inference, no tiers.
   Only aggregates (Mean, Std, Min, Max, Median, Mode, Distinct) are
   dynamic; Log, Sqrt, Abs, MissingIndicator static
   (`sqlearn_000:src/sqlearn/transforms/log.py:L97`,
   `sqlearn_000:src/sqlearn/imputers/missing_indicator.py:L91`). A consuming
   step holds an aggregate as a parameter
    (NOTES:`sqlearn_000/review.md:L59-L66`).
3. **Boundary rule.** None: one learn pass, then one apply pass
   (`sqlearn_000:src/sqlearn/compiler/compose.py:L14-L30`).
4. **Examples.** Above; no dynamic schema-changing step was built.
5. **How values reach later steps.** Every aggregate runs against the raw
   input placeholder, `agg.apply(_input_table())`
   (`compose.py:L217-L225`); the learned scalar is cached on `result_` and
   inlined by the consuming step at apply. A later learner never sees an
   earlier step.
6. **Query counts.** "v0.1.0 executes one query per step. Independent
   aggregates can later be batched into a single query"
   (`sqlearn_000:src/sqlearn/backend/duckdb.py:L289-L290`). One query per
   aggregate, by design.
7. **Problems.** The aggregate specs said `"static"` (the war room's
   meaning) while the base class says `"dynamic"`: "aggregates/{max,min}.md
   claim `_classification = "static"`; release + base contract say
   `"dynamic"`" (`sqlearn_000:reports/2026-04-29-19-00.md:L18-L44`); closed
   as superseded, not fixed (NOTES:`sqlearn_000/review.md:L218-L230`). The
   six later commits in `sqlearn-ecosystem/sqlearn` add agent files that
   still teach the v0.4 meaning: "'static' means no database scan needed"
   (`sqlearn-ecosystem/sqlearn/.claude/agents/sqlearn-hardener.md:L223-L230`).

## War room (`sqlearn-ecosystem/sqlearn-private`, 26 April – 13 June, specs)

Paths below start `sqlearn-ecosystem/sqlearn-private/projects/sqlearn/`
unless they start `ideas/` or `plans/`.

1. **Definition.** "`kind` (static/dynamic) is about whether the step's AST
   *shape* depends on values learned at learn time"
   (`core/inspector.md:L192-L194`); "Static / dynamic is a property of how a
   step's AST shape relates to data values — it is **dialect-agnostic**"
   (`L46-L50`). A second axis, `emission` (`column-projection`, `row-filter`,
   `scoped-query`), is "independent" (`L186-L199`). Output cardinality:
   "**Static steps (output count known at construction)**" versus
   "**Dynamic steps (output count learned at learn time)**"
   (`core/step.md:L479-L488`). Ordinal shows the criterion is wider than
   schema: "Output schema (1 in → 1 out) is unchanged, but the AST
   construction itself depends on training-data values"
   (`encoders/ordinal.md:L13`). So static now means **the SQL can be written
   before the data is seen, even if it embeds learned scalars**: "scalar
   aggregates inside parameters do not disqualify a step from being static —
   they live inside the AST as nested CTEs / scalar subqueries"
   (`imputers/impute.md:L11`).
2. **How decided.** The three tiers again (`core/inspector.md:L99-L165`):
   built-ins trusted and checked in CI against Tier 3 "run on the same
   instance" (`L104-L106`); custom declared verified once (`L112-L136`); the
   Tier 3 checklist returns dynamic for a "variable schema (set-valued
   aggregate driving a downstream column-count expansion)", data-driven
   string sugar such as `bins="auto"`, an overridden `learn`, or an opaque
   `apply` (`L145-L165`). Runtime guard: `StaticViolationError` when a
   static step's apply AST references an aggregate "without a cached
   `result_` value" (`L307-L319`).
3. **Boundary rule.** "A layer is a maximal set of steps whose work can run
   in a single SQL query: the layer count is the dependency depth of the step
   graph after the inspector classifies each step as static or dynamic"
   (`core/pipeline.md:L128-L135`). All-static → one layer, "the static-only
   mega-AST" (`L146-L154`); with dynamic steps "typically 2 layers": a learn
   layer "covering every step's learning — static stats and dynamic
   categories aggregated together in one query", then an apply layer
   (`L156-L170`); "ten independent dynamic encoders is still 2 layers, not
   11" (`L168-L170`). Across `sq.Join`/`sq.Union` the depth is taken over
   the whole tree (`L172-L182`); "one SQL query per dependency-depth pass
   (Pass 1 = independent dynamics across the whole tree; Pass N = depth-N
   dynamics; final apply = ONE giant AST)" (`core/io.md:L1396-L1402`).
   A `row-filter` "never adds a layer" (`core/pipeline.md:L136-L144`).
4. **Examples.** Static: Impute, StandardScale, MinMaxScale (aggregate
   substeps inside) (`imputers/impute.md:L11`, `scalers/standard_scale.md:L11`),
   CyclicalEncode (`encoders/cyclical_encode.md:L13`), Log, filters
   ("row-filter static step", `filters/README.md:L1-L4`). Dynamic: OneHot
   ("output column count depends on data values", `encoders/one_hot.md:L13`),
   Ordinal (literal category list, `encoders/ordinal.md:L13`), and every
   aggregate (`aggregates/mean.md:L11`, `aggregates/quantile.md:L11`).
   Parameter-dependent: `bins="auto"` (`core/inspector.md:L157`). The
   class also depends on implementation: "Ordinal — JOIN-based rewrite to
   reclassify as static", with the mapping as a CTE joined at apply so "the
   AST is built from input schema alone" (`ideas/ordinal-join-rewrite.md:L2`,
   `L20-L44`); "OneHot remains dynamic regardless ... (its output column
   count = `|DISTINCT(col)|`, schema-changing)" (`L95-L98`).
5. **How values reach later steps.** Scalars: cached on the aggregate's
   `result_` and "substituted inline into Impute's apply AST", or kept in
   "nested CTEs / scalar subqueries" (`imputers/impute.md:L11`, `L40`,
   `L123-L127`). In fit, "the composer adds the aggregate to the layer's
   batched learn-pass query" (`L125-L127`), so Mean for the imputer and Std
   for the scaler are learned together on un-imputed input (inference;
    NOTES:`sqlearn-private-war-room/notes/C-step-specs.md:L60-L68`). Between
   layers: "In-database materialization" (a temporary table) by default,
   "CTE chaining across layers" as an optimisation for small pipelines
   (`core/compiler.md:L344-L358`).
6. **Query counts.** "one compilation per layer and one execution per layer.
   For typical pipelines (1–2 layers), that is 1–2 SQL queries total —
   independent of step count" (`core/pipeline.md:L320-L334`); for "impute,
   scale, encode, bin in any combination the layer count is 1 or 2"
   (`core/compiler.md:L128-L134`); all-static `learn_apply` is "a single
   combined query" (`core/step.md:L76-L86`). No code; never measured.
7. **Problems.** The asymmetric rule survives
   (`core/inspector.md:L167-L170`), though under the new meaning a false
   static means SQL written against an unknown shape. Contradictions: Mean
   is static in the inspector's reason string (`core/inspector.md:L218-L225`)
   and in `imputers/impute.md:L11`, `L40` ("substep aggregates are themselves
   static"), dynamic in `aggregates/mean.md:L11` and `core/io.md:L935-L938`.
   The aggregate specs call themselves dynamic "because their learned result
   feeds consuming steps' ASTs" (`aggregates/mean.md:L186`), the consumers
   static: "the taxonomy is inverted relative to April ... The
   classification now says nothing about whether the step needs a fit pass"
    (NOTES:`sqlearn-private-war-room/notes/C-step-specs.md:L122-L128`).
   "Pipelines of static steps collapse into a single learn_apply query"
   (`encoders/cyclical_encode.md:L13`) cannot hold when static steps read
   learned scalars (NOTES:`C-step-specs.md:L376-L379`). The Tier 3
   checklist checks only variable schema, so it would class Ordinal static
   (inference from `core/inspector.md:L145-L156` against
   `encoders/ordinal.md:L13`). The ordinal idea cites a "§ Classification"
   in `core/step.md` that was moved out (`core/step.md:L1323-L1324`).

## August restarts (`sql_learn_test`, `sql_learn_27.08.2026`, `sql_learn`)

1–4 and 7. **No static/dynamic concept.** No estimator was built in any of
the three; searches for the terms (static/dynamic step, `_classification`,
layer boundary, learn/fit pass, schema-changing) find only unrelated prose
(research reports on agent "information barriers"). See
NOTES:`sql_learn_test/review.md:L18-L19` and NOTES:`sql_learn/review.md`.

5. **How values reach later steps (evidence only).** `sql_learn` measured
that a chain of lazy DuckDB relations, each step reading its input twice
(statistics, then apply), grows its SQL text about four times per step
(2,916,231 characters at depth 14) and hung at depth 20
(`sql_learn/reports/research/2026-08-27-duckdb-relation-limits.md:L5-L9`,
`L19-L37`; `sql_learn/plans/review-estimator-contract.md:L90-L106`). Rechecked
on DuckDB 2.0.0 in this repository: `WITH` stages (default or
`MATERIALIZED`) stay at 0.005–0.010 s to depth 24, `NOT MATERIALIZED` ran
out of memory at depth 12 (NOTES:`sql_learn/review.md:L40-L66`).

6. No query-count promise.

## Autumn sqlearn (`sqlearn`, 30 September – 4 October)

No library code and nothing on fit execution
(NOTES:`sqlearn-autumn/notes/A-docs-code.md:L44`, `L208`). The only hit for
"static/dynamic" is Sphinx's static versus dynamic docstring analysis
(`sqlearn/records/archived/research_scout-docs_20260930-173519.md:L105`).
None of the seven points apply.

## How the meaning changed

| Attempt | "Static" means | "Dynamic" means | Third tier | Boundary |
|---|---|---|---|---|
| ducklearn, Tomosius, v0.4 | SQL from constructor args; no fit query | must learn from data | none ("no third state") | after dynamic AND schema-changing |
| `ducklearn1` idea (in Tomosius) | fit SQL returns one row | fit SQL returns many rows (`DISTINCT`, `GROUP BY`) | none | none |
| April | no fit query | has a fit query | `hybrid`: depends on args or children | same, "if and only if" |
| sqlearn_000 | no learn pass | aggregate (only aggregates) | none | none: one learn pass |
| War room | SQL shape known before data, scalars allowed inside | SQL shape (columns, literal lists) depends on learned values; also all aggregates | none (but `emission` axis) | dependency depth of dynamic steps |

Three shifts matter:

- **From "learns" to "shape depends on learning."** Through April, Impute
  and Scale were dynamic and the boundary needed a second condition
  (schema-changing) to stop them cutting layers. The war room moved that
  second condition into the definition, so dynamic alone cuts. The two
  rules pick the same boundaries for OneHot but differ for Ordinal (war room
  cuts, April does not) and for DropConstant/SelectKBest (both cut, because
  the schema change is learned).
- **Aggregates flipped twice.** In sqlearn_000 an aggregate is dynamic
  because it is the thing that learns; in the war room inspector it is
  static because its shape is fixed; in the war room aggregate specs it is
  dynamic again because "the learned scalar gets substituted into
  consumers". The same word described the producer in one file and the
  consumer in another.
- **"Static" never meant "uses no data statistics."** In every attempt,
  FrequencyEncode-style and window/group steps that compute statistics at
  apply time were static, because they need no fit query. That is a
  separate property (transductive steps) that the label hid.

What stayed constant: author declaration for built-ins, checked by CI;
conservative inference for custom steps; constructor arguments deciding
the class for some steps; composites taking the class of their children;
and, in every design with layers, learning steps in one layer reading the
layer's input, so a learner never saw an earlier learner.

## Synthesis

This section is my synthesis from the evidence above, not a position any
attempt took.

**Separate three properties instead of one label.**

- *Learns* — the step has learned state that some query must compute (April's
  "dynamic"). Impute, Scale, OneHot, Clip(`p01`), and also FrequencyEncode
  and GroupAggregate, whose apply-time statistics should be learned state.
- *Shape-learned* — the column set (names, count, order, types) of the
  step's output, or the structure of its SQL, cannot be written until
  learned values are known (the war room's "dynamic", narrowed). OneHot,
  Binary, AutoDatetime(`"auto"`), StringSplit(`max_parts="auto"`),
  DropConstant, DropCorrelated, VarianceThreshold, SelectKBest. Ordinal only
  if its categories are embedded as literals.
- *Row-changing* — Filter, Sample, Deduplicate, outlier removal (the war
  room's `row-filter` emission). Fit must see them; the Tomosius code did
  not.

**Best combined definition.** A step is **static** when the SQL for its
output, and therefore for every step after it, can be written before any
data is read, with any learned values referred to as relations (scalar
subqueries or CTE columns) rather than literals. A step is **dynamic**
when the shape of its output depends on learned values, so no later SQL
can be written until those values are fetched. Learning is orthogonal:
most learning steps are static under this definition.

**Run boundary rule.** A new run starts before the first step that reads
the output of a dynamic step. The dynamic step's own learning (for OneHot,
its `DISTINCT`) belongs in the run that ends there, together with every
other learning step whose input is already writable. The number of learn
runs is one plus the longest chain of dynamic steps that later learning
depends on (inference: a trailing OneHot, or one followed only by static
steps that learn nothing, adds no learn run; its categories are needed only
to build the apply SQL). This is the war room's "dependency depth", with
the correct definition of dynamic.

**Inside a run, every learning step reads its true upstream output.** The
evidence points to `WITH` stages: Impute's median as a stage, Scale's
statistics computed over `COALESCE(x, (SELECT median FROM stage))`
(Tomosius's parked idea,
`sqlearn-desktop/ideas/active/base-features.md:L197-L207`;
the self-contained CTE of
`sqlearn-desktop/architecture/design/cv-design.md:L25-L38`;
April's staged CollapseRare), with row-changing steps folded in as stages.
DuckDB materialises a stage read twice, which keeps this fast where chained
relations blew up (`sql_learn`). This removes the defect every layered
design had and makes "static" safe to batch.

**How the class is decided.** Declare for built-ins, with a CI test that
compares the declaration with what the step actually emits (both scalar
and set learning, which the Tomosius CI test missed); let constructor
arguments set it where they change the shape; take the strongest class of
the children for composites; for custom steps infer conservatively and
treat any exception (including from set learning) as dynamic. The cost
asymmetry changes form: under this definition a false static usually fails
loudly (SQL written against columns that do not exist yet) unless learned
values are inlined as stale literals, which is the case to forbid; a false
dynamic costs one extra run.

**Query counts.** Promise nothing until measured. The honest statement the
evidence supports is: runs = 1 + depth of dynamic steps that later
learning depends on, plus the apply. No attempt measured an end-to-end
count, and the code's real count (a query per set-valued column, a view
per boundary) exceeded every promise.

## Files read

ROOT:

- `ducklearn/docs/02-api-design.md` (classification passages),
  `ducklearn/docs/03-architecture.md` (§4.3 and fit flow),
  `ducklearn/docs/04-compiler.md` (§5.1–5.4), `ducklearn/docs/12-milestones.md`
  (§13e), `ducklearn/docs/13-testing.md` (line 243),
  `ducklearn/docs/14-decisions.md` (risk rows, decisions 4, 7, 93b, 103,
  114), `ducklearn/CLAUDE.md` (lines 40–48).
- `sqlearn-desktop/architecture/design/` in full: `api-design.md`,
  `base-class.md`, `classification-impl.md`, `column-routing.md`,
  `compiler.md`, `custom-api.md`, `cv-design.md`, `error-hierarchy.md`,
  `output-format.md`, `overview.md`, `pipeline.md`, `project-database.md`,
  `schema.md`, `static-dynamic.md`, `testing.md`.
- `sqlearn-desktop/architecture/planning/performance.md` (lines 20–135),
  `sqlearn-desktop/ideas/active/base-features.md` (lines 190–212),
  `sqlearn-desktop/ideas/rejected/query-template-single-pass.md` (lines
  1–45), `sqlearn-desktop/src/sqlearn/core/compiler.py` (lines 135–400,
  470–600, 705–768), `_classification` lines across
  `sqlearn-desktop/src/sqlearn/**`.
- `sqlearn-ecosystem_old/sqlearn/src/sqlearn/compiler/classify.py` (whole),
  `.../compiler/layers.py` (lines 1–30, 100–232), `.../compiler/compile.py`
  (lines 60–116, 238–290), `.../transforms/binning/bin.py` (lines 50–62),
  `.../transforms/union.py` (lines 55–85), `_classification` lines across
  `.../src/sqlearn/**`,
  `sqlearn-ecosystem_old/sqlearn/docs/architecture/compiler.md` (grep of
  classification and layer lines).
- `sqlearn-ecosystem_old/sqlearn-private/_old/projects/sqlearn/src/compiler/layers.md`
  (lines 25–176), `.../compiler/classify.md` (headings, lines 375–430),
  `.../compiler/compose.md` (lines 40–70, 156–160), `.../compiler/compile.md`
  (lines 135–142),
  `.../transforms/{target_transform,union,branch,sql,custom}.md` and
  `.../transforms/binning/bin.md` (classification lines),
  `.../transforms/encoders/frequency_encode.md` (lines 5, 15–20),
  `.../tests/src/_shared/classification_audit.md` (lines 8–26),
  `.../tests/src/compiler/layer_planning.md` (lines 125–148).
- `sqlearn-ecosystem/sqlearn/.claude/agents/sqlearn-author.md`,
  `.../sqlearn-hardener.md` (grep).
- `sqlearn-ecosystem/sqlearn-private/projects/sqlearn/core/inspector.md` (lines
  1–60, 100–200, 215–228, 305–320), `.../core/pipeline.md` (lines 128–182,
  320–334), `.../core/compiler.md` (lines 40–60, 128–135, 344–363),
  `.../core/step.md` (lines 76–88, 475–490, 1323), `.../core/io.md` (lines
  935–939, 1396–1403), `.../imputers/impute.md` (lines 11, 36–42, 123–128),
  `.../scalers/standard_scale.md`,
  `.../encoders/{one_hot,ordinal,cyclical_encode}.md`,
  `.../aggregates/{mean,distinct_values,quantile}.md`, `.../filters/README.md`
  (classification lines),
  `sqlearn-ecosystem/sqlearn-private/ideas/ordinal-join-rewrite.md` (lines
  1–110),
  `sqlearn-ecosystem/sqlearn-private/plans/2026-06-07-step-composability-plan-a.md`
  (lines 170–180).
- `sql_learn/reports/research/2026-08-27-duckdb-relation-limits.md` (lines
  1–40), `sql_learn/plans/review-estimator-contract.md` (lines 90–106); term
  searches over `sql_learn_test`, `sql_learn_27.08.2026`, `sql_learn` and
  `sqlearn`; `sqlearn/records/archived/research_scout-docs_20260930-173519.md`
  (grep).

`sqlearn_000:` clone: `src/sqlearn/core/step.py` (grep),
`src/sqlearn/compiler/compose.py` (lines 1–60, 175–240),
`src/sqlearn/backend/duckdb.py` (lines 281–322),
`src/sqlearn/aggregates/min.py` (lines 55–70),
`reports/2026-04-29-19-00.md` (grep), term search over the whole clone.

NOTES (leads): `README.md`; `ducklearn/`, `tomosius-sqlearn/notes/A-design.md`,
`tomosius-sqlearn/notes/B-core.md`, `sqlearn-v04/review.md`,
`sqlearn-v04/notes/A-design.md`, `sqlearn-v04/notes/B-compiler.md`,
`sqlearn-v04/notes/C-transformers.md`,
`sqlearn-private-april/notes/A-direction.md`,
`sqlearn-private-april/notes/B-core-specs.md`,
`sqlearn-private-april/notes/C-transform-specs.md`,
`sqlearn-private-war-room/notes/B-core-specs.md`,
`sqlearn-private-war-room/notes/C-step-specs.md`, `sqlearn_000/review.md`,
`sql_learn_test/review.md`, `sql_learn/review.md`, `sqlearn-autumn/review.md`,
`sqlearn-autumn/notes/A-docs-code.md` (all by grep and the passages quoted).

Skipped as instructed: `test/`, `_old_sqlearn/`, generated folders, `.env`
files.
