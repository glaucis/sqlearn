---
type: note
tags: [planning, sqlearn, v2-migration, free-pro-split, decisions]
summary: "Batch A summary of the April 2026 sqlearn planning repo covering direction, version timeline, the free/pro split and the eight v2 rationale documents."
related: [docs/questions/archived/earlier-attempts/sqlearn-private-april/notes/A-direction.md]
mdindex: [type=edb465, tags=1c0bb6, summary=b4a244, related=2e05e8]
---
# A. Direction and decisions

Batch A of the April planning repo, `sqlearn-ecosystem_old/sqlearn-private`
(called OLD below; GitHub `glaucis/sqlearn-private`, 9 to 24 April 2026). It
covers the root files, `rationale/`, `projects/`, `releases/`, `intake/` and,
in `_old/`, the root files, `versions/`, `ideas/`, `intake/` and `templates/`.
Citations are `OLD:path:Lnn`. Inference is marked as such. Nothing in OLD was
run; one DuckDB check was made in a scratch folder (below, under SQL
representation).

## Summary

- **A documentation-only "war room" that never held code.** It planned two
  products, free `sqlearn` (MIT) and paid `sqlearn_pro`, plus a Svelte site,
  and fed "releases" to a separate code repository
  (`OLD:README.md:L8-L10`, `OLD:README.md:L83-L102`).
- **It ran alongside v0.4 and then turned on it.** It recorded v0.1 to v0.4 as
  shipped (9 to 12 April), planned v0.5 to verify and lock v0.4's compiler, and
  on 13 April decided to rename the v0.4 code to "legacy" and restart
  greenfield, because the code "predates ~80% of the current architecture"
  (`OLD:_old/TODO.md:L424-L441`).
- **The "v2" direction (21 April) is a philosophy, not an engine design:**
  "user typed it, user gets it". The `option=` safety cascade, the three
  safety tiers and the free risk warnings were deleted; NULL is preserved by
  default; domain errors name three fixes; risk analysis moves to pro
  (`OLD:releases/archived/2026-04-21-general-0.3.0.md:L116-L151`).
- **The free/pro line is mechanical:** anything that inspects data at run time
  or calls an AI is pro; free has every capability
  (`OLD:rationale/v2-free-pro-line.md:L22-L43`). Free's own domain checks
  inspect data, which the rule does not account for (inference).
- **The engine model is "every transformer is one standalone CTE", composition
  "correct by construction", validated per CTE only** (`OLD:README.md:L14-L79`).
  This is the opposite of the baseline's main lesson.
- **On fit, the plans locked in the defect.** v0.5's critical tests froze v0.4's
  boundary rule (`is_dynamic AND schema_changes`) and its "1–3 queries per
  `learn()`" promise (`OLD:_old/versions/sqlearn/0.5.0.md:L55-L161`). Yet the
  prose examples assume the right answer: "Scale fits on the filled column"
  (`OLD:projects/sqlearn/src/transforms/composition/drop_null.md:L158-L160`).
- **The naming review left every decision blank.** Fifteen open questions with
  recommendations; all `DECISION:` lines are empty
  (`OLD:_old/NAMING-REVIEW.md:L246`). The `learn`/`apply` renaming was called
  settled.
- **Validation was designed thoroughly and never run:** arbitrary-precision
  canonicals, twelve baseline cases, ULP reporting, a five-layer tolerance
  cascade with guessed starting values, an agent escalation ladder. It was per
  function only, with no pipeline comparison
  (`OLD:_old/templates/validator.py:L1-L30`).
- **Process outgrew product again:** rules 0 to 4, a `read_also` cascade, hooks,
  five orchestration subagents and release files for a repo with no code; on
  22 April four of six hooks were switched off because the stack "produced
  chaos rather than clarity" (`OLD:CONVERSATION.md:L94-L104`).
- **Much of the live tree points at files that are not there:**
  `CONSTITUTION.md` and every `standards/*.md` cited by MAP and the rationale
  are missing from this copy (`standards/` and `templates/` are empty folders)
  while the repo was "being rebuilt" (`OLD:CLAUDE.md:L21-L25`).

## Direction and versions

Order of events, from the dated files:

1. **9 to 12 April: v0.1 to v0.4 shipped in the code repo.** OLD wrote one
   version file per release afterwards: v0.1 "Foundation" (16 symbols, new
   names `learn`/`apply`/`sql`), v0.2 "SQL-Native Power + Safety" (about 80
   symbols), v0.3 "Complete Preprocessing Library" (about 100), v0.4 "Deep
   Analysis & Search" (about 125, `sq.explore()` with k-fold CV)
   (`OLD:_old/versions/sqlearn/INDEX.md:L12-L24`,
   `OLD:_old/versions/sqlearn/0.1.0.md:L10-L22`). All four are "grandfathered":
   no validators (`OLD:_old/versions/sqlearn/0.1.0.md:L112-L123`).
2. **12 April: restructure and naming review.** The repo was reorganised into
   `projects/`, `versions/`, `standards/`, `ideas/`, `intake/`
   (`OLD:_old/report.md:L13-L26`); the pro vision was widened to "one
   ComfyUI-level canvas" (`OLD:_old/report.md:L284-L301`) with a $10 a month
   price as "current thinking" (`OLD:_old/report.md:L319-L321`).
3. **12 to 14 April: v0.5 to v1.0 planned.** v0.5 "Foundation" is
   verification of the existing compiler plus an error hierarchy
   (`OLD:_old/versions/sqlearn/0.5.0.md:L12-L33`); v0.6 observability and
   fit-time warnings; v0.7 search caching; v0.8 a DECIMAL precision mode and
   20 debt fixes including an SQL injection; v0.9 connections and
   concurrency; v1.0 `freeze()`, `audit()`, `sq.check()`
   (`OLD:_old/versions/sqlearn/0.8.0.md:L46-L47`,
   `OLD:_old/versions/sqlearn/1.0.0.md:L66-L68`). The parking lots hold about
   80 free items and a dozen pro bundles
   (`OLD:_old/versions/sqlearn/TBC.md:L22-L100`,
   `OLD:_old/versions/sqlearn-pro/TBC.md:L24-L165`).
4. **13 April: greenfield.** Brownfield hardening of v0.4 was replaced by a
   plan to rename it `sqlearn-legacy`, reset `main` and rebuild from OLD's
   specs, with an Opus "hardener" agent per function
   (`OLD:_old/TODO.md:L293-L330`, `OLD:_old/TODO.md:L424-L530`). The legacy
   code stays as reference for edge cases and numbers
   (`OLD:_old/TODO.md:L532-L555`).
5. **13 to 14 April: semantics designed in brainstorms.** Universal
   parameters (`where=` semantics by transformer category, SQL three-valued
   logic with an opt-in "pandas" NULL policy, a config cascade, educational
   first-use messages) (`OLD:_old/TODO.md:L1111-L1170`); a transformer class
   hierarchy (`OLD:_old/TODO.md:L760-L838`).
6. **20 April: process releases.** "general 0.1.0" (a release contract, a
   reverse index of standards to skills, a memory-redirect hook) and "general
   0.2.0" (five subagents and a commit gate that makes the "chain reaction"
   mechanical) (`OLD:releases/archived/2026-04-20-general-0.1.0.md:L77-L105`,
   `OLD:releases/archived/2026-04-20-general-0.2.0.md:L42-L77`).
7. **21 to 22 April: v2 philosophy migration** ("general 0.3.0", eight
   rationale files) (`OLD:releases/archived/2026-04-21-general-0.3.0.md`).
8. **22 to 24 April: reset of the tree.** The README was rewritten as the
   foundation everything is "rebuilt from" (`OLD:README.md:L229-L230`); old
   standards are walked one at a time (`OLD:CLAUDE.md:L21-L25`); the 24 April
   universal-parameters walk left the enforcement mechanism open
   (`OLD:CONVERSATION.md:L119-L148`). The repo ends there.

The code repo it addressed is `~/coding/sqlearn-ecosystem/sqlearn`, which
was to implement `drop_nulls=`, `InvalidInputDomainError` and the sibling
classes (`OLD:releases/archived/2026-04-21-general-0.3.0.md:L210-L217`). That
is the folder whose history starts with `sqlearn_000` (inference from the
attempts map), so `sqlearn_000` was the greenfield consumer of these plans.

**The free/pro split.** First form (13 to 14 April): "free = engine, pro =
cockpit", "free users never hit a wall", capability free and assistance paid,
four firm constraints (no hosted execution, local first, core pure Python and
MIT, engine/cockpit), default to free, tiebreaker "would a solo data
scientist expect this in a free library?" (`OLD:_old/CLAUDE.md:L122-L196`).
The same constraints allow an "optional cloud service" for licences,
pipeline sync, LLM reasoning over schemas and "opt-in telemetry"
(`OLD:_old/CLAUDE.md:L160-L162`). Pro's centre is the node canvas
(`OLD:_old/versions/sqlearn-pro/TBC.md:L27`); the rest is smart MCP tools,
deployment generators (dbt, Airflow, stored procedures), AutoML, a federated
planner and validated multi-dialect deployment
(`OLD:_old/versions/sqlearn-pro/TBC.md:L24-L29`,
`OLD:_old/versions/sqlearn-pro/TBC.md:L162-L165`). v2 sharpened the line into
the mechanical test (next section). The current project has no paid tier;
the pro canvas and the free dtale-style explorer correspond to the overview's
two later local applications (inference).

## Rationale documents

All eight dated 21 April 2026, written as the "source of truth" for the v2
migration (`OLD:MAP.md:L143-L146`).

- **`v2-option-cascade-removal`.** Decision: delete `option=` and its
  six-level cascade (transformer, pipeline, session, environment variable,
  TOML, default); every error names a sibling, a per-transformer kwarg and an
  upstream `sq.Filter` (`OLD:rationale/v2-option-cascade-removal.md:L27-L39`).
  Reason: six sources of truth for one line, silent auto-delegation of `Log`
  to `LogSigned`, two code paths in every transformer, about 850 lines of
  standard, and one toggle silencing both structural errors and risk
  heuristics (`L41-L78`).
- **`v2-null-preserve-default`.** Decision: preserve NULL by default; drop
  only on `drop_nulls=True`, `drop_nulls=[cols]` or `sq.DropNull()`; every
  `drop_nulls` declaration joins one `AND` `WHERE` at the end of the query,
  "deferred, not sequential", while `sq.Filter` is sequential and does change
  what later steps fit on (`OLD:rationale/v2-null-preserve-default.md:L26-L39`,
  `L187-L197`). Reason: the 14 April drop-by-default design needed hidden
  `WHERE` clauses, row-drift metadata and keep-masks, and rejected
  `drop_null=False` on Scale with a false claim that NULL-aware statistics are
  "mathematically impossible" (`L41-L68`); deferred dropping makes fitted
  values independent of step order (the Box-Cox worked example, `L98-L161`).
- **`v2-signed-sibling-rule`.** Decision: every restricted-domain transformer
  ships a named safe sibling in the same change (`Log`/`LogSigned`,
  `BoxCox`/`YeoJohnson`, `Exp`/`ClippedExp`…), plus per-trigger kwargs
  (`negative=True`, `zero=True`…), and raises `InvalidInputDomainError` with
  the three-route message; no auto-delegation
  (`OLD:rationale/v2-signed-sibling-rule.md:L24-L37`). Reason: a name says
  what maths runs; per-trigger kwargs give granularity without a class per
  combination (`L49-L84`, `L179-L200`).
- **`v2-universal-params-no-cascade`.** Decision: of `where=`, `group_by=`,
  `order_by=`, `drop_nulls=`, `dtype=`, only `drop_nulls` cascades from the
  pipeline; the seven `group_by` heuristics move to pro; non-determinism
  (`RANDOM()`, `NOW()`) stays a hard error in free
  (`OLD:rationale/v2-universal-params-no-cascade.md:L24-L38`). Reason: a
  pipeline-level `where=` hides each step's fit scope from its reader
  (`L40-L91`); `drop_nulls` is a policy, the others change semantics
  (`L93-L115`); YAGNI (`L117-L142`).
- **`v2-free-pro-line`.** Decision: "Does this feature require runtime data
  inspection or AI inference? Yes → pro"
  (`OLD:rationale/v2-free-pro-line.md:L26-L43`). Reason: it applies §5 of the
  constitution without a debate per feature; sibling hints in errors stay free
  because they are author-time metadata; federated runtime free, federated
  planner pro (`L45-L126`).
- **`v2-smart-level`.** Decision: pro alone gets an integer `smart_level`
  0 to 3 (risk warnings, suggestions, fit-time auto-rewrite to a sibling,
  quiet rewrite) (`OLD:rationale/v2-smart-level.md:L26-L68`). Reason: a
  graded dial instead of a binary toggle; five guardrails keep it safe: set
  per pipeline or session only, at fit only, recorded in the saved pipeline,
  announced loudly, and visible in `pipe.sql()` (`L99-L183`).
- **`v2-constitution-rewrite`.** Decision: seven edits, chiefly §2 "we warn
  loudly about known risks" becomes "errors are explicit, with a menu of
  fixes", §3 loses its `option=` paragraph, "every column is data, including
  NULL" becomes a required bullet, the microwave metaphor now "refuses to run
  if the door can't close" (`OLD:rationale/v2-constitution-rewrite.md:L24-L44`).
  Reason: keep a stance against silent degradation but limit it to what
  cannot compile; risk analysis is assistance (`L46-L97`, `L300-L309`).
- **`v2-safety-tier-collapse`.** Decision: FREE / GUARDED / FORBIDDEN becomes
  compiles / rejects; every GUARDED case goes to free, to a reject with the
  three-route error, or to pro
  (`OLD:rationale/v2-safety-tier-collapse.md:L25-L41`, `L112-L179`). Reason: the
  other v2 changes removed GUARDED's knob, its carriers and its constitutional
  source; GUARDED also hid mislabelled correctness rules (`L43-L80`,
  `L293-L297`).

The decisions moved three times in eight days on one question, `Log` on
negative data: safe by default with a warning (13 April,
`OLD:_old/TODO.md:L1505-L1546`), a config-driven alias resolved through
`option=` (14 April, `OLD:_old/TODO.md:L1533-L1546`), then strict with an
error (21 April).

## Fit, state, SQL representation

**How fit runs.**

- The 23 April README model: each transformer is one CTE with a known input
  and output schema; a "detector" classifies static and dynamic steps and is
  "the only whole-chain reasoner"; `learn` "merges [dynamic queries] via
  sqlglot into the minimum number of round-trips"; `apply` builds "one massive
  AST" (`OLD:README.md:L14-L36`, `L57-L60`). It never says what input a
  dynamic step's learning query reads (inference: per-step CTEs would give
  sequential fit for free if each query read its predecessor, but the
  "minimum round-trips" merge is exactly what broke this before).
- v0.5 Pillar E was to audit v0.4's compiler and lock, as must-pass tests,
  the layer boundary rule `is_dynamic AND schema_changes`, batching "five
  dynamic same-schema steps into one query, not five", substitution of
  static steps' expressions, and byte-exact SQL snapshots
  (`OLD:_old/versions/sqlearn/0.5.0.md:L55-L161`). Those tests are ported from
  the earlier attempt (`L173-L183`). This would have frozen the Impute-then-
  Scale defect.
- Fit semantics stated in prose elsewhere are the correct ones: the DropNull
  example has `Scale` fitting "on the filled column" after `Impute`
  (`OLD:projects/sqlearn/src/transforms/composition/drop_null.md:L149-L163`);
  `sq.Filter` "reshapes data flow" and affects fit
  (`OLD:rationale/v2-null-preserve-default.md:L189-L197`); `sq.check()` would
  flag "Scale before Filter" as an ordering mistake
  (`OLD:_old/versions/sqlearn/1.0.0.md:L68`). v0.4 ignored `Filter` while
  fitting (v0.4 review), so plan and code disagreed.
- `drop_nulls` is deliberately excluded from fit: "fits are always SQL-native
  per-column, independent of drop ordering"
  (`OLD:releases/archived/2026-04-21-general-0.3.0.md:L134-L138`). Each
  statistic is learned over its own column's non-NULL rows, not over
  complete cases.
- `where=` on a statistics step limits only the fit scope, compiled as an
  aggregate `FILTER (WHERE …)`, and the fitted values apply to every row;
  on `Impute`/`Fill`/`Replace` it is a row condition at apply time
  (`OLD:_old/TODO.md:L793-L813`, `L1128-L1136`).
- `group_by=` treats NULL keys as their own group, as SQL `GROUP BY` does
  (`OLD:projects/sqlearn/src/warnings/group_by_rules.md:L142-L179`).
- Free `cv=K` cross-fitting: "the stats used on row R are always fit on rows
  that exclude R's fold"
  (`OLD:projects/sqlearn_pro/src/modeling_correctness.md:L286-L292`; the
  standard itself, `standards/cross-fit.md`, is absent). This is out-of- fold
  application at transform time, a step beyond per-fold statistics.
- Fold and split as columns: `__sq_fold__` and `__sq_dataset__`, filtered as
  `WHERE __sq_dataset__ = 'train' AND __sq_fold__ != :k`
  (`OLD:_old/versions/sqlearn/TBC.md:L66`).

**Learned state.**

- `params_` (scalars) and `sets_` (set values) as dicts, replacing
  scikit-learn's `mean_`, `categories_` and so on
  (`OLD:_old/NAMING-REVIEW.md:L159-L168`); every value a JSON primitive, "no
  numpy arrays, no sqlglot AST nodes" (`OLD:_old/CLAUDE.md:L336-L344`).
- `FitSnapshot` (parked): an immutable record per `learn()` with params,
  sets, SQL, schemas, source, fold and a hash over the SQL AST. Its reason is
  a new failure: "CV overwrites fold N-1's values when fitting fold N"
  because state lives on the transformer instances
  (`OLD:_old/versions/sqlearn/TBC.md:L55`).
- Saved pipelines record concrete classes, so a pro rewrite loads in free
  (`OLD:rationale/v2-smart-level.md:L129-L148`, `L244-L265`).
- `pipe.reproduce_check(data)` refits and compares learned values, to catch
  drift from sqlglot or DuckDB upgrades
  (`OLD:_old/versions/sqlearn/TBC.md:L63`).

**SQL representation and dialects.**

- sqlglot is assumed throughout: "chains compile through sqlglot into a
  single AST"; free targets "any sqlglot dialect"
  (`OLD:README.md:L3-L6`, `L175-L176`); a `where=` predicate is parsed with
  sqlglot and rewritten for the "pandas" NULL policy
  (`OLD:_old/TODO.md:L1020-L1033`).
- Portability claims contradict each other. v0.2's notes say `MEDIAN`, `MODE`,
  `QUANTILE`, `CORR`, `STDDEV_POP` "are tested across DuckDB, Postgres, MySQL,
  Snowflake, BigQuery" (`OLD:_old/versions/sqlearn/0.2.0.md:L152-L155`); the pro
  parking lot says transpilation "is syntactic, not semantic" and that users
  "discover these failures in production"
  (`OLD:_old/versions/sqlearn-pro/TBC.md:L165`).
- Multi-source work by DuckDB `ATTACH`, not a coordinator: distributed execution
  was rejected on 13 April (`OLD:_old/ideas/rejected/scope.md:L34-L75`), then a
  pro federated push-down planner was designed the next day
  (`OLD:_old/versions/sqlearn-pro/TBC.md:L162`).
- `to_python()` export was cut to "DuckDB-mirror only" to reduce the test
  surface about sixfold (`OLD:_old/versions/sqlearn/TBC.md:L89`).
- Invariant: `pipe.sql()` is Python-free (no UDFs)
  (`OLD:_old/CLAUDE.md:L346-L353`).
- Parked `compile_mode="debug"`: one CTE per step with a comment naming it;
  the default stays one flat `SELECT` (`OLD:_old/versions/sqlearn/TBC.md:L38`).
- The DropNull sweep's SQL refers to output aliases in `WHERE`
  (`region_US IS NOT NULL`)
  (`OLD:projects/sqlearn/src/transforms/composition/drop_null.md:L40-L53`).
  Checked on DuckDB 2.0.0: it runs, because DuckDB accepts aliases in `WHERE`
  and prefers the input column when an alias shadows one; standard SQL engines
  reject it (inference for other engines). The one-hot indicators are never
  NULL, so the sweep keeps rows whose category was NULL. The sketch builds the
  clause with an f-string and no quoting (`L131-L135`).

## API and naming

`_old/NAMING-REVIEW.md` (12 April) is a side-by-side of scikit-learn and
sqlearn, meant to be decided and folded into `standards/api-naming.md`
(`OLD:_old/NAMING-REVIEW.md:L1-L29`).

- **"Settled, do not revisit"**: `learn(data, target=None)` for `fit`,
  `apply(data)` for `transform` and `predict`, `sql()`, `summary()`; verb
  class names (`Scale`, `Impute`, `OneHot`); `data`/`target`/`columns`
  instead of `X`/`y`/features; trailing-underscore fitted state; no `fit` or
  `transform` on `Pipeline`, an `as_sklearn()` adapter instead
  (`OLD:_old/NAMING-REVIEW.md:L32-L77`). `fit_transform` was dropped as
  "overloaded"; `get_params` became `to_config()` and `set_params` became
  `from_config()` (a rebuild); `seed` replaces `random_state`; `n_jobs` and
  `verbose` dropped (`L83-L157`). `target` is a column name, not an array
  (`L148`).
- **Fifteen open questions, all undecided** (`L193-L746`). Recommendations:
  rename `discover`/`discover_sets` to `learn_scalars`/`learn_sets` (Q1);
  `target` on the contract too (Q2); keep `OneHot`/`Ordinal` but
  `TargetEncode` (Q3); rename `Expression` to `Compute` (Q4); keep `apply`,
  because `transform` is "lying" (Q5); `Columns` (the `ColumnTransformer`
  equivalent) to `Route` (Q10); keep `Union` (Q11); `apply()` returns an
  `ApplyResult` with `.as_pandas()` (Q13); `sq.quick()` to `sq.auto()` (Q15).
  Deferred: `>>` for composition, `Filter` against `Where` (`L770-L785`).
- **Still unresolved on 22 April:** whether the public surface is three verbs
  (`learn`, `apply`, `summary`) or the longer list (`sql`, `to_config`,
  `save`, `clone`, `is_fitted`, `validate`, `as_sklearn`)
  (`OLD:CONVERSATION.md:L52-L63`), and how a transformer declares which
  universal parameters it accepts (class flags, the detector, or an explicit
  `accepts:` set) (`OLD:CONVERSATION.md:L119-L148`).
- The plans still mention `get_params()` ("MRO walk still works") after it
  was renamed away (`OLD:_old/TODO.md:L838`), and `pipe.clone()` returns in
  v0.9 (`OLD:_old/versions/sqlearn/0.9.0.md:L69`): the bridges back to
  scikit-learn that the baseline describes.
- Under ADR 0003, every row marked SETTLED above is a departure that would
  need its own ADR. The table itself is a ready checklist for the API survey.

## Validation

- **Three gates per CTE**: code and tests on inline synthetic data;
  hardening (fuzz, property tests, review); validation against a canonical
  on real downloaded datasets, where the canonical is a hand-written formula
  reference when a formula exists and otherwise scikit-learn or pingouin
  pinned by version (`OLD:README.md:L135-L167`). The README's argument is
  that per-CTE correctness makes every chain correct, so there is no
  pipeline gate (`OLD:README.md:L46-L79`).
- **Validator template**: one file per formula; canonical from a primary
  source in 40-digit `Decimal` or `mpmath` at 200 bits, never from a compared
  library; twelve baseline cases (float32, int promotion, NULL, empty, single
  value, constant, a million rows, extreme magnitudes, NaN and Inf, mixed
  signs); error in absolute, relative and ULP terms per library; JSON output
  against a schema (`OLD:_old/templates/validator.py:L1-L30`, `L85-L233`).
  Libraries not installed are "silently skipped" (`L66-L69`).
- **Tolerance cascade**: by function, operation, library, dtype, default
  (`OLD:_old/templates/tolerances.toml:L8-L14`). Starting values are set by
  reasoning, not measurement, and are to be "adjusted empirically"; every
  change is a commit with old value, new value, reason and run; "never loosen
  a tolerance without investigating" (`L1-L26`).
- **Iterative fits**: the one example loosens Box-Cox (fitted by Brent's
  method) to 1e-10 relative until seeding is deterministic
  (`OLD:_old/templates/tolerances.toml:L227-L237`): a looser bound with a
  dated re-evaluation, not a separate method.
- **Escalation**: three Sonnet attempts, three Opus attempts, then a human
  picks an option, which may be a tolerance change or a waiver
  (`OLD:_old/templates/validation-escalation.md:L198-L267`).
- **Exact arithmetic in the product**: a planned `precision="decimal38"` mode
  making linear transforms bit-exact, checked against a 50-digit Decimal
  ground truth (`OLD:_old/versions/sqlearn/0.8.0.md:L46`).
- **What validation is not**: it proves computational correctness, not that a
  pipeline is statistically sound
  (`OLD:projects/sqlearn_pro/src/modeling_correctness.md:L58-L107`).
- **Divergence on degenerate input**: the template expects NULL output for a
  constant column (`OLD:_old/templates/validator.py:L195-L202`), where
  scikit-learn's `StandardScaler` returns 0 (inference from scikit-learn's
  documented behaviour; not rerun here).
- Nothing was implemented: the framework is a TODO of empty boxes
  (`OLD:_old/TODO.md:L114-L284`).

## New against the baseline

- The planning repo answered v0.4 by deciding a greenfield rewrite on
  13 April (`OLD:_old/TODO.md:L424-L441`).
- The prose specs assume sequential fit (`Scale` on imputed values, `Filter`
  shaping fit) while the planned v0.5 tests freeze the batched layer rule.
- `drop_nulls` is designed to leave fit untouched; only `Filter` changes fit
  scope (`OLD:rationale/v2-null-preserve-default.md:L187-L197`).
- `where=` on a statistics step is a fit-scope `FILTER (WHERE …)` only
  (`OLD:_old/TODO.md:L1128-L1136`).
- Per-fold state was overwritten on transformer instances during CV
  (`OLD:_old/versions/sqlearn/TBC.md:L55`).
- Free `cv=K` out-of-fold cross-fitting at transform time
  (`OLD:projects/sqlearn_pro/src/modeling_correctness.md:L286-L292`).
- Restricted-domain steps raise at fit after scanning data, with a
  three-route error, and pro's design says the fitted pipeline raises at
  apply on new invalid data (`OLD:rationale/v2-smart-level.md:L115-L127`):
  a data check inside transform (inference).
- The planning repo itself said dialect transpilation is syntactic only
  (`OLD:_old/versions/sqlearn-pro/TBC.md:L165`).
- Multi-source through DuckDB `ATTACH` rather than transpiling
  (`OLD:_old/ideas/rejected/scope.md:L57-L63`).
- Validation planned in arbitrary precision with a ULP report and dated
  tolerance changes; the open question's "precision" point has a concrete
  earlier answer (40-digit `Decimal`, `mpmath` at 200 bits).
- The free/pro split and its three oscillations on `Log`'s default.
- An optional cloud service with opt-in telemetry was within the planned
  constraints (`OLD:_old/CLAUDE.md:L160-L162`); ADR 0006 now rules it out.

## Contradicts the baseline

- The baseline found portability "never tested beyond parsing"; v0.2's notes
  claim five engines were tested
  (`OLD:_old/versions/sqlearn/0.2.0.md:L152-L155`). The planning repo's own pro
  row and the v0.4 review support the baseline; the claim is unsupported.
- The baseline's lesson is that composition is where fit fails; the README
  holds that composition "introduces no new failure modes" and validates per
  CTE only (`OLD:README.md:L50-L79`).

## Confirms the baseline

- The fit boundary rule was `is_dynamic AND schema_changes`, and the plan
  was to lock it (`OLD:_old/versions/sqlearn/0.5.0.md:L83`, `L133-L161`).
- Learned state as flat dicts of JSON primitives
  (`OLD:_old/CLAUDE.md:L336-L344`).
- sqlglot chosen for many dialects (`OLD:README.md:L175-L176`).
- No pipeline-level comparison with scikit-learn was ever planned; validators
  are per formula (`OLD:_old/templates/validator.py:L11`).
- A strong validation method written and never enforced
  (`OLD:_old/TODO.md:L114-L284`).
- Renamed scikit-learn API with bridges back (`as_sklearn`, `get_params`,
  `clone`) (`OLD:_old/NAMING-REVIEW.md:L73-L77`, `OLD:_old/TODO.md:L838`).
- `y` as a column name (`OLD:_old/NAMING-REVIEW.md:L148`); target-in-features
  known, as a later `sq.check()` item
  (`OLD:_old/versions/sqlearn/1.0.0.md:L68`).
- Process outran product, status kept by hand in many places, docs citing
  files that do not exist (`OLD:CONVERSATION.md:L94-L104`, `OLD:MAP.md:L51`).

## Worth keeping

- **Two row primitives with stated contracts:** a sequential `Filter` that
  later steps fit on, and an output-only drop that fit ignores, with the
  De Morgan note that "drop if any is NULL" is `AND … IS NOT NULL`
  (`OLD:rationale/v2-null-preserve-default.md:L163-L197`).
- **NULL preserved by default and SQL-native NULL handling in aggregates**
  (`OLD:rationale/v2-null-preserve-default.md:L70-L78`), checked against
  scikit-learn's NaN handling before adoption (inference).
- **Signed siblings and the three-route error** (sibling, per-trigger kwarg,
  upstream filter), and a name that always means one formula
  (`OLD:rationale/v2-signed-sibling-rule.md:L24-L84`). Where the check runs
  needs a decision, since transform must not query data (inference: an
  in-SQL guard, such as DuckDB's `error()` in a `CASE`, would keep it in the
  query).
- **Reject non-deterministic expressions** (`RANDOM()`, `NOW()`) in arguments
  and predicates (`OLD:rationale/v2-universal-params-no-cascade.md:L170-L187`).
- **No settings that change what a step means**: no global flag or environment
  variable alters `sq.Log` (`OLD:rationale/v2-constitution-rewrite.md:L83-L97`).
- **Learned state per fold as immutable records**, keyed by fold
  (`OLD:_old/versions/sqlearn/TBC.md:L55`).
- **Fold and split as columns** filtered in SQL
  (`OLD:_old/versions/sqlearn/TBC.md:L66`).
- **Validator shape**: canonical from a primary source in arbitrary
  precision, twelve baseline cases, ULP report, tolerances changed only by a
  commit that records the reason (`OLD:_old/templates/validator.py:L85-L233`,
  `OLD:_old/templates/tolerances.toml:L19-L26`); with the pipeline-level
  comparison added and missing libraries failing, not skipping.
- **The computational/modelling distinction** for the site's validation pages
  (`OLD:projects/sqlearn_pro/src/modeling_correctness.md:L58-L107`).
- **`pipe.sql()` with no Python dependency** (`OLD:_old/CLAUDE.md:L346-L353`).
- **DuckDB `ATTACH` for other sources** and a DuckDB-only first export as
  precedents for keeping one engine (`OLD:_old/ideas/rejected/scope.md:L57-L63`,
  `OLD:_old/versions/sqlearn/TBC.md:L89`).
- **The NAMING-REVIEW side-by-side** as raw input to the API survey, read
  against ADR 0003 rather than its "settled" labels.

Guard against: a design model that declares composition safe by
construction; tests that lock current behaviour before it is checked against
a reference; decisions that swing on one question within days; rules,
cascades, hooks and release machinery for documents before any code exists;
maps that list files that are not on disk.

## Files covered

Root:

- [x] `CLAUDE.md`: war-room rules 0 to 4, two products, IP boundary, workflow.
- [x] `CONVERSATION.md`: three open items of 22 to 24 April (verbs, detector,
  hooks, parameter enforcement).
- [x] `MAP.md`: map of structural docs, many absent from this copy.
- [x] `README.md`: 23 April foundation: one CTE per transformer, three verbs,
  four projects, three gates.
- [x] `TODO.md`: one cross-repo item.

`rationale/`:

- [x] `v2-constitution-rewrite.md`: seven constitution edits.
- [x] `v2-free-pro-line.md`: runtime inspection or AI means pro.
- [x] `v2-null-preserve-default.md`: preserve NULL, deferred `drop_nulls`.
- [x] `v2-option-cascade-removal.md`: `option=` deleted.
- [x] `v2-safety-tier-collapse.md`: three tiers to two outcomes.
- [x] `v2-signed-sibling-rule.md`: siblings and the three-route error.
- [x] `v2-smart-level.md`: pro's graded rewrite dial.
- [x] `v2-universal-params-no-cascade.md`: only `drop_nulls` cascades.

`projects/` (40 files):

- [x] `projects/README.md`: empty stub.
- [x] `projects/sqlearn/README.md`: stub.
- [x] `projects/sqlearn_pro/README.md`: stub.
- [x] `projects/sqlearn_website/README.md`: empty stub.
- [x] `projects/sqlearn/src/README.md`: empty stub.
- [x] `projects/sqlearn/tests/README.md`: empty stub.
- [x] `projects/sqlearn/validations/README.md`: empty stub.
- [x] `projects/sqlearn/src/core/README.md`: empty stub.
- [x] `projects/sqlearn/src/compiler/README.md`: empty stub.
- [x] `projects/sqlearn/src/errors/README.md`: empty stub.
- [x] `projects/sqlearn/src/helpers/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/README.md`: empty stub.
- [x] `projects/sqlearn/src/warnings/README.md`: index of the two rules files.
- [x] `projects/sqlearn/src/warnings/arithmetic_rules.md`: eight domain rules.
- [x] `projects/sqlearn/src/warnings/group_by_rules.md`: two NULL info rules.
- [x] `projects/sqlearn/src/transforms/composition/drop_null.md`: `DropNull`.
- [x] `projects/sqlearn/src/transforms/arithmetic/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/binning/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/composition/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/datetime/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/encoder/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/escape_hatch/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/imputation/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/interaction/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/operations/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/outlier/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/scaler/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/selection/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/string/README.md`: empty stub.
- [x] `projects/sqlearn/src/transforms/window/README.md`: empty stub.
- [x] `projects/sqlearn_pro/src/README.md`: index.
- [x] `projects/sqlearn_pro/src/modeling_correctness.md`: four risks, seven
  warnings, hyperfitting, `cv=K`.
- [x] `projects/sqlearn_pro/src/risk_warnings/README.md`: index.
- [x] `projects/sqlearn_pro/src/risk_warnings/target_leakage.md`: corr > 0.3.
- [x] `projects/sqlearn_pro/src/risk_warnings/small_group.md`: n < 30.
- [~] `projects/sqlearn_pro/src/risk_warnings/group_coverage_imbalance.md`:
  top group > 80%.
- [~] `projects/sqlearn_pro/src/risk_warnings/missing_concentration.md`: MNAR.
- [~]
  `projects/sqlearn_pro/src/risk_warnings/preprocessing_complexity_warning.md`:
  effective parameters > 10% of rows.
- [~] `projects/sqlearn_pro/src/risk_warnings/variance_overreduction.md`:
  > 80% variance loss.
- [~] `projects/sqlearn_pro/src/risk_warnings/cardinality_vs_sample_size.md`:
  groups > √rows.

`releases/`:

- [x] `releases/README.md`: release-file schema and status machine.
- [x] `releases/archived/2026-04-20-general-0.1.0.md`: release contract,
  reverse index, hooks.
- [x] `releases/archived/2026-04-20-general-0.2.0.md`: five subagents, commit
  gate.
- [x] `releases/archived/2026-04-21-general-0.3.0.md`: the v2 migration.
- [x] `releases/archived/.gitkeep`: empty.

`intake/`:

- [x] `intake/INDEX.md`: empty stub.
- [x] `intake/archived/INDEX.md`: empty stub.

`_old/` root:

- [x] `_old/CLAUDE.md`: 14 April war room: free/pro rule, constraints, three
  invariants, naming card, scope discipline.
- [x] `_old/MAP.md`: 13 April map.
- [x] `_old/NAMING-REVIEW.md`: settled names and 15 undecided questions.
- [x] `_old/README.md`: free/pro in three lines.
- [~] `_old/TODO.md` (1,947 lines): read the scope, validation set-up,
  brownfield and greenfield plans, class hierarchy, config system,
  brainstorm and domain-validity items; the rest by heading and keyword.
- [x] `_old/report.md`: 12 April restructure log and pro vision.

`_old/versions/`:

- [x] `_old/versions/INDEX.md`
- [x] `_old/versions/sqlearn/INDEX.md`
- [x] `_old/versions/sqlearn/0.1.0.md`: Foundation, 16 symbols.
- [~] `_old/versions/sqlearn/0.2.0.md`: about 80 symbols; portability claim.
- [~] `_old/versions/sqlearn/0.3.0.md`: about 100 symbols; universal params.
- [~] `_old/versions/sqlearn/0.4.0.md`: analysis primitives, `explore()`.
- [x] `_old/versions/sqlearn/0.5.0.md`: Pillar E locks the layer rule.
- [~] `_old/versions/sqlearn/0.6.0.md`: logging, fit-time warnings.
- [~] `_old/versions/sqlearn/0.7.0.md`: search caching.
- [~] `_old/versions/sqlearn/0.8.0.md`: DECIMAL mode, hardening.
- [~] `_old/versions/sqlearn/0.9.0.md`: connections, concurrency, `clone()`.
- [~] `_old/versions/sqlearn/1.0.0.md`: `freeze`, `audit`, `check`.
- [~] `_old/versions/sqlearn/TBC.md`: about 80 parked items, rows read by
  title, eight in full.
- [x] `_old/versions/sqlearn-pro/INDEX.md`
- [~] `_old/versions/sqlearn-pro/TBC.md`: pro bundles; federated and
  multi-dialect rows read in full.

`_old/ideas/`, `_old/intake/`, `_old/templates/`:

- [x] `_old/ideas/INDEX.md`: source audit log (scikit-learn modules audited
  11 April).
- [x] `_old/ideas/rejected/scope.md`: distributed execution and agent tooling
  rejected.
- [x] `_old/intake/INDEX.md`
- [x] `_old/intake/archived/INDEX.md`
- [x] `_old/templates/INDEX.md`
- [x] `_old/templates/tolerances.toml`: five-layer cascade.
- [~] `_old/templates/validator.py`: sections 1 to 4 read, 5 to 7 by
  function.
- [~] `_old/templates/validation-escalation.md`: tier ladder.
- [~] `_old/templates/validator-output-schema.json`: required fields.

No read hung or failed. Not present on disk though cited: `CONSTITUTION.md`
and every `standards/*.md`.
