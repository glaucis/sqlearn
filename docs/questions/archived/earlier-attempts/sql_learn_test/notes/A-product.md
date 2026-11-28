---
type: note
tags: [sql-learn, scikit-learn, duckdb, agent-workflow, research, restart]
summary: "Product and research review of the sql_learn_test restart: a scikit-learn-parity DuckDB library attempt that produced process research rather than estimators."
related: [docs/questions/archived/earlier-attempts/sql_learn_test/notes/A-product.md]
mdindex: [type=edb465, tags=32c6c9, summary=cc7c3e]
---
# sql_learn_test, batch A: product and research

OLD is
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sql_learn_test`
(GitHub `glaucis/sql_learn`, 21–24 August 2026, 59 commits). Read only; nothing
was run there. DuckDB claims were rechecked on DuckDB 2.0.0 in this repository.
"Inference" marks what the files do not say outright.

## Summary

- The restart built no library. `src/sql_learn/__init__.py` exports only
  `__version__` (`OLD:src/sql_learn/__init__.py:L3-5`); `tests/` holds a
  package smoke test and a docstring gate that skips while no estimator exists
  (`OLD:tests/test_docstrings.py:L123`).
- Its product decision fits one page: scikit-learn's documented API is the
  specification, and a running scikit-learn is the test oracle
  (`OLD:architecture/sklearn-parity.md:L9-20`).
- "Public API is identical to scikit-learn; the internal data path is SQL"
  (`OLD:CLAUDE.md:L3-4`) meant: scikit-learn's signatures, parameter and
  attribute names and trailing-underscore fitted state, with no adaptation for
  SQL; numpy, pandas and sklearn banned from library code by ruff `TID251`
  (`OLD:pyproject.toml:L49-57`); `check_estimator` not a target;
  `sklearn.model_selection` rewritten in SQL or not offered
  (`OLD:architecture/sklearn-parity.md:L56-74`).
- Almost all the work was process research: 17 topics, each sent to two models
  (opus, fable) with identical briefs and neither seeing the other's output (36
  reports), merged into 17 syntheses, turned into five `rules/` files and
  audited by three reviewers. The coverage reviewer counts "219,000 words of
  research" (`OLD:reports/20260824T133416Z-reviewer-coverage-gaps.md:L689`).
- No synthesis researched scikit-learn's API, DuckDB or the earlier attempts
  as a subject. Every one is about running agents: test order, information
  barriers, review, gates, debugging, refactoring, docs and so on. Library facts
  come up only as worked examples.
- Those by-products include a strong set of measured DuckDB facts: threaded
  float aggregation is not reproducible, `NaN = NaN` is true, NULLs sort last
  under `DESC`, and a column name passed as a parameter becomes a constant
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L692-728`). All
  but one still hold on 2.0.0; `1 % 0` now raises an error.
- Validation takes the opposite line to the overview's exact references: the
  oracle is a live scikit-learn, values are never transcribed, and the
  tolerance comes from measurement. It never fixed a number
  (`OLD:architecture/sklearn-parity.md:L79-89`).
- New open points it names: whether "SQL, not numpy" covers the small dense
  solve (the p × p system, PCA's eigendecomposition)
  (`OLD:TODO.md:L1319-1322`), and that units composed in a pipeline can be
  wrong even when each one is right (`fit` right,
  `transform` right, `fit_transform` wrong)
  (`OLD:reports/20260824T000000Z-research-change-size-opus.md:L677-688`).
- It confirms the baseline's process finding yet again: zero estimators after
  four days, a data-loss incident from a repository-wide `git checkout`
  (`OLD:TODO.md:L35-57`), and research files that claimed results nobody had
  measured (`OLD:TODO.md:L177-199`).

## Aim of the restart

What it set out to do, from its own files:

- **Product, narrowed to parity.** "A scikit-learn-compatible ML ecosystem with
  SQL (DuckDB) as the engine instead of numpy/pandas. Public API is identical to
  scikit-learn; the internal data path is SQL" (`OLD:CLAUDE.md:L3-4`). The
  argument: a user who knows scikit-learn is "the whole audience; an API that is
  *nearly* the same costs that user more than a different one"
  (`OLD:architecture/sklearn-parity.md:L13-15`). When API and SQL disagree,
  "the SQL changes" (`L12`).
- **Correctness from an outside oracle, not agreement.** "Correctness here is
  measured against a reference, not established by reading the code and
  agreeing with it" (`OLD:architecture/sklearn-parity.md:L19-20`). A plan, its
  tests and its code can share one misunderstanding; only the reference "was
  not in the conversation" (`L29-35`).
- **A pipeline of agents with controls checked by machine.** The repository
  centres on a roster of agents (`.claude/agents/`, batch B) and on making
  every control mechanical. The reason given is measurement: prompts telling an
  agent not to edit tests have been shown to fail (ImpossibleBench: GPT-5
  cheats 54% of the time, Claude Opus 4.1 50%;
  `OLD:syntheses/mechanical-gates.md:L7-16`, `OLD:TODO.md:L229-238`).
- **Evidence before rules.** Every rule was to rest on primary-source research,
  with model pairs blind to each other so that disagreement surfaces
  (`OLD:syntheses/test-ordering.md:L11-17`).

Why it differed from the war room (inference: no file in this batch mentions
an earlier attempt): the war room swung scope by conversation and specified
five engines. This restart pinned the scope to "scikit-learn's surface, DuckDB
only" and tried to replace opinion with measured evidence and mechanical
gates. It repeated the war room's main failure all the same: process work grew
to fill the time, and no product came of it.

## Syntheses

All 17 follow one template: the question, where the two halves agree, where
they disagree, claims with sources, noticed, contradicts current practice,
dropped. All are about the agent workflow.

- **change-size**: how big is one unit of work? One vertical slice of one
  estimator's public surface (a method plus its SQL, provable by one
  scikit-learn comparison), capped on lines and files; the reviewer refuses
  oversized diffs (`OLD:syntheses/change-size.md:L17-30`).
- **code-craft**: which code properties predict defects? No static metric
  survives controlling for size. A live scikit-learn carries the defect load.
  Around it: one choke-point module for all SQL, bound values, one helper for
  quoting identifiers, explicit column lists, `ORDER BY` wherever order is
  observed, and fixtures with NULL, NaN, empty input and a single row
  (`OLD:syntheses/code-craft.md:L18-29`).
- **context-engineering**: how do you write rules agents follow? Each
  obligation can fail, so compliance falls as they multiply; at most about
  seven per file. Prohibitions under a strong prior need mechanical controls.
  Quote rules into the brief rather than ask agents to find them
  (`OLD:syntheses/context-engineering.md:L15-29`).
- **debugging-workflow**: how do agents debug? A ladder of reproduce,
  diagnose, fix, review, regress, record, one stage per dispatch. Reproduce
  twice with DuckDB pinned (`threads=1`, seeds, `ORDER BY`) before any fix
  (`OLD:syntheses/debugging-workflow.md:L17-29`).
- **documentation**: does it need its own workflow? No: a rule plus a gate.
  In a parity library reference docs are "not authored, it is verified":
  docstrings checked against upstream with `inspect.signature` and numpydoc
  (`OLD:syntheses/documentation.md:L16-28`).
- **hardened-testing**: what testing beyond examples? Parity is the backbone
  but cannot see a wrapper or numpy-backed implementation, so "honesty
  controls" are needed. Metamorphic relations go in a catalogue, Hypothesis
  carries them, and SQL mutants are written by hand (Tuya's operators). No
  coverage gate (`OLD:syntheses/hardened-testing.md:L19-35`).
- **high-assurance**: what do near-zero-defect projects do? They build an
  independent oracle, and here it comes free. Adopt parity as a permanent
  battery, harvest `estimator_checks`, metamorphic relations, generated input
  shapes. TLA+ only if a protocol appears with an ordering invariant across
  calls (`partial_fit`, out-of-core chunking)
  (`OLD:syntheses/high-assurance.md:L25-43`).
- **information-barriers**: does keeping one agent blind to another's work
  help? Two of its three mechanisms survive: expected values come from the
  oracle, and an author never grades its own work. Two blinded authors are
  not statistically independent. Enforce by dispatch order, not by prohibition
  (`OLD:syntheses/information-barriers.md:L18-30`).
- **loop-convergence**: can a loop run until the code is "perfect"? No. The
  honest target is a ratchet: three dissimilar loops, exits computed from exit
  codes, hard caps (`OLD:syntheses/loop-convergence.md:L14-24`).
- **mechanical-gates**: which controls can be machine-checked? The
  orchestrator runs a script after each dispatch. Use
  `git status --porcelain -uall`, not `git diff`; close the gaps in `TID251`
  with a `sys.meta_path` blocker; check signature parity against live
  scikit-learn (`OLD:syntheses/mechanical-gates.md:L16-31`). One half used
  DuckDB `EXPLAIN` as a SQL validator and rejected sqlglot
  (`L66-74`).
- **multi-agent-pipelines**: how many roles? About seven, each justified only by
  a structural asymmetry; running code (`pytest`, `ruff`, the oracle) ranks
  above any reviewer's opinion
  (`OLD:syntheses/multi-agent-pipelines.md:L20-32`).
- **planning-workflow**: what should a plan produce? A decision memo that
  ends `blocked` for the human, then a contract: exact signatures and defaults
  from the installed scikit-learn, return shape, dtype and column order, fitted
  attributes, errors, a tolerance with its reason, a divergence ledger
  (`OLD:syntheses/planning-workflow.md:L17-30`).
- **redteam-coding-rule**: an attack on the first workflow rule. The
  architecture survives; the gates did not exist or were broken, so "no
  green suite here is currently evidence"
  (`OLD:syntheses/redteam-coding-rule.md:L14-29`).
- **refactoring**: how do you change tested code? A pure refactor leaves
  `tests/` unchanged; when the SQL moves, the flagship gate is SQL identity,
  run against an adversarial corpus (NULLs, ties, empty input, one row,
  duplicates, permuted order) (`OLD:syntheses/refactoring.md:L17-30`).
- **review-workflow**: where does review go? A stage inside the build, one
  reviewer per artefact, no `Edit` tool, two fix rounds and then the human
  (`OLD:syntheses/review-workflow.md:L21-34`).
- **task-intake**: how does a wish become a task? A rule and a checklist.
  Public API, parity deviations, NULL, ordering, tolerance, `ddof` and new
  dependencies are reserved for Tomas (`OLD:syntheses/task-intake.md:L16-29`).
- **test-ordering**: which order: plan, tests, code? Adopt
  `plan → tests → code`, while admitting that exposure, not order, does the
  work; the live oracle is "the load-bearing asset"
  (`OLD:syntheses/test-ordering.md:L19-35`).

## Reports

36 research reports (17 topics × opus and fable, plus extra halves for
change-size, code-craft, context-engineering, mechanical-gates, refactoring
and task-intake, the second wave dated `20260824T000000Z`), three reviewer
reports and a template. Every research report is the source of the synthesis
of the same name; I read them by their recommendation and, where they bear on
the library, by their evidence.

- `TEMPLATE.md`: front matter `agent/task/status/needs_todo`; sections What I
  did, Noticed, Problem.
- `…debugging-workflow-{fable,opus}`: source of debugging-workflow. Opus
  measured DuckDB 1.5.5's `sum()` over 2 million doubles giving four results in
  four runs at `threads=8`.
- `…documentation-{fable,opus}`: source of documentation. Opus built and
  mutation-tested a docstring checker: 17 defects, all caught.
- `…hardened-testing-{fable,opus}`: source of hardened-testing. Opus measured
  scikit-learn's own permutation invariance as only 266 bitwise-exact results
  in 2000.
- `…high-assurance-{fable,opus}`: source of high-assurance. Verified that
  scikit-learn 1.9.0 has 107 `check_*` functions.
- `…information-barriers-{fable,opus}`: source of information-barriers.
- `…loop-convergence-{fable,opus}`: source of loop-convergence.
- `…multi-agent-pipelines-{fable,opus}`: source of multi-agent-pipelines.
- `…planning-workflow-{fable,opus}`: source of planning-workflow. Fable lists
  metamorphic relations for a scaler (mean ≈ 0, std ≈ 1,
  `fit_transform ≡ fit().transform()`)
  (`OLD:reports/20260823T225316Z-research-planning-workflow-fable.md:L90`).
- `…redteam-coding-rule-{fable,opus}`: source of redteam-coding-rule. Opus
  returned `status: issue`.
- `…review-workflow-{fable,opus}`: source of review-workflow.
- `…test-ordering-{fable,opus}`: source of test-ordering.
- `…change-size-{fable,opus}`: source of change-size. Opus names the gap in
  composition that no per-unit rule closes
  (`OLD:reports/20260824T000000Z-research-change-size-opus.md:L677-688`).
- `…code-craft-{fable,opus}`: source of code-craft. Opus has the fullest DuckDB
  list in the attempt, half re-run first-hand
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L680-728`).
- `…context-engineering-{fable,opus}`: source of context-engineering.
- `…mechanical-gates-{fable,opus}`: source of mechanical-gates. Fable: DuckDB
  `EXPLAIN` against a schema fixture rejects syntax errors, unknown columns and
  `avg(VARCHAR)`; sqlglot accepted a trailing `GROUP BY`; `NewType("Sql", str)`
  stops raw strings reaching the executor
  (`OLD:reports/20260824T000000Z-research-mechanical-gates-fable.md:L95-105`).
- `…refactoring-{fable,opus}`: source of refactoring.
- `…task-intake-{fable,opus}`: source of task-intake.
- `20260824T133416Z-reviewer-coverage-gaps`: 40 gaps (G1–G40) and 16 open forks
  (D1–D16) between the syntheses and the rules. G21: no policy for seeds,
  threads or tolerance; G24: nothing pins the oracle or the engine.
- `20260824T133416Z-reviewer-fidelity-research-vs-rules`: `status: issue`;
  checks whether the rules dropped, softened or inverted the research (I read
  the summary only).
- `20260824T133416Z-reviewer-redteam-rules`: `status: issue`; an attack on the
  five rule files (summary only). Its findings C1–C5 and H1–H7 are indexed in
  `OLD:TODO.md:L75-115`.

## Code

- `OLD:src/sql_learn/__init__.py:L1-5`: docstring, `__version__ = "0.0.0"`,
  `__all__`. `py.typed` is empty. A stale
  `__pycache__/_probe_tmp.cpython-313.pyc` shows a probe module existed and
  was deleted (inference; not opened).
- `OLD:tests/test_package.py:L10-20`: a subprocess check that importing
  `sql_learn` does not load numpy. The TODO admits it "proves very little"
  while the package imports nothing (`OLD:TODO.md:L1306-1309`).
- `OLD:tests/test_docstrings.py`: docstrings "verified against scikit-learn,
  not authored" (`L1-15`). Documented parameters must equal the signature,
  fitted attributes must end in `_`, and every public method needs a
  docstring. It includes a test that the gate can fail (`L97-120`) and
  deliberately does not compare prose with upstream, because types diverge by
  design (`L9-12`).
- `OLD:pyproject.toml`: `requires-python = ">=3.11"`, a single runtime
  dependency `duckdb==1.5.5` (`L5-12`), dev `scikit-learn==1.9.0` and numpy
  (`L14-22`), hatchling, the `TID251` bans with messages that state the fix
  (`L45-57`), `D417` named explicitly because the numpy convention silently
  drops it (`L40-43`).
- Gates in `tools/` (batch B) are described in the TODO: a content hash
  proving tests were not changed, and a `meta_path` hook that catches an
  implementation wrapping scikit-learn (`OLD:TODO.md:L69-72`).

## Bearing on the four open questions

**How fit runs.** Almost nothing; the attempt never reached `Pipeline`.
What there is:

- It names the composition gap and leaves it open: per-unit parity cannot
  catch `fit_transform` being wrong while `fit` and `transform` are right; the
  partial fix is a parity check over the whole estimator
  (`OLD:reports/20260824T000000Z-research-change-size-opus.md:L677-688`,
  `OLD:reports/20260824T133416Z-reviewer-coverage-gaps.md:L170-177`). The
  same reasoning one level up would demand the whole-pipeline comparison the
  baseline says no attempt ran (inference).
- Fitted state follows scikit-learn: Python attributes ending in `_`
  (`OLD:architecture/sklearn-parity.md:L9-11`). No design for state in SQL or
  in tables.
- Cross-validation: `sklearn.model_selection` "cannot be reused" because
  splitters materialise numpy index arrays, so splitting "is reimplemented as
  SQL or it is not offered" (`OLD:architecture/sklearn-parity.md:L71-74`);
  "deterministic predicate splits" (`OLD:TODO.md:L1340-1341`).
- The small dense solve (p × p normal equations, PCA's eigendecomposition)
  is an open question: does "SQL, not numpy" reach it? It blocks the first
  estimator (`OLD:TODO.md:L1319-1322`).
- `partial_fit` and out-of-core chunking are named as the point where an
  ordering invariant across calls appears
  (`OLD:syntheses/high-assurance.md:L37-39`).

**Multi-engine.** Out of scope: DuckDB only, pinned exactly
(`OLD:pyproject.toml:L12`). No sqlglot anywhere. Relevant findings:

- sqlglot was rejected as a SQL validator because, run with `read="duckdb"`,
  it accepted `SELECT avg(x) FROM rel GROUP BY`; DuckDB `EXPLAIN` against a
  schema fixture catches syntax, unknown-column and type errors instead
  (`OLD:reports/20260824T000000Z-research-mechanical-gates-fable.md:L99`).
  Rechecked on 2.0.0: `EXPLAIN` raises `BinderException` on an unknown column
  and `ParserException` on a trailing `GROUP BY`. The sqlglot half was not
  rechecked.
- sqlglot is kept in view only as the way to build a SQL mutator
  (`OLD:reports/20260823T225316Z-research-hardened-testing-opus.md:L276-277`).
- DuckDB departs from PostgreSQL in ways that would break a transpiling
  design: `NULLS LAST` under `DESC` as well, `1/0` = `inf`, quoted
  identifiers case-insensitive, `1 = '1.1'` and `1 = true` true
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L685-726`).

**scikit-learn API survey.** No survey; parity was simply asserted. Usable
decisions:

- Copy as is: signatures, parameter names and defaults, attribute names, the
  trailing underscore (`OLD:architecture/sklearn-parity.md:L9-15`). No logic
  or validation in `__init__`, because of `set_params` and `GridSearchCV`
  (`OLD:syntheses/code-craft.md:L102`, `L150-151`).
- Parity reaches `fit`, `transform`, `get_params`, `set_params` and
  `__sklearn_tags__`, not scikit-learn's machinery
  (`OLD:architecture/sklearn-parity.md:L56-57`). Skip `check_estimator` as a
  target (`L65-70`), though the syntheses want to harvest individual checks
  (`OLD:syntheses/high-assurance.md:L33-34`, `L57-70`). The attempt
  contradicts itself here.
- A signature gate: `inspect.signature` against live scikit-learn 1.9.0 caught a
  missing `positive` and a wrong `tol` default on a fake `LinearRegression`
  (`OLD:reports/20260824T000000Z-research-mechanical-gates-fable.md:L97`).
- Conventions that catch people out: `StandardScaler.scale_` uses ddof=0
  while `PCA.explained_variance_` uses ddof=1, so no general rule
  (`OLD:TODO.md:L1333-1337`). A constant column gives `var_ = 0.0` but
  `scale_ = 1.0` (`OLD:syntheses/hardened-testing.md:L141-144`). DuckDB's
  default `BINARY` collation sorts strings as `np.unique` does, so
  `OneHotEncoder` category order matches unless `COLLATE` is emitted
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L727-728`;
  rechecked on 2.0.0 against Python's `sorted`).
- Copying upstream docstrings brings a BSD-3 notice obligation, and the repo
  had no LICENSE (`OLD:TODO.md:L146-149`).

**Validation method.** The fullest bearing, and opposed to the overview's
exact-reference plan:

- The oracle is a live, exactly pinned scikit-learn; hand-computed values only
  where it cannot reach, labelled as such
  (`OLD:architecture/sklearn-parity.md:L91-100`). A transcribed oracle value is
  the worst option (`OLD:syntheses/test-ordering.md:L30-31`).
- Tolerance is "a decision, not a default", and no number was fixed
  (`OLD:architecture/sklearn-parity.md:L79-89`). The research contradicts the
  rule: both halves derive tolerance from the measured noise floor (about
  10×), not from dtype precision in advance
  (`OLD:syntheses/code-craft.md:L158-163`).
- Noise floor: DuckDB float aggregates vary with the thread count
  (`OLD:syntheses/debugging-workflow.md:L136-141`); choose between
  `SET threads=1` in tests and a tolerance above the floor
  (`OLD:TODO.md:L811-816`).
- A tolerance can swallow a `ddof` error at scale: the standard deviation
  differs by 15.47% at n = 4 but by 5.0e-6 at n = 100000
  (`OLD:syntheses/redteam-coding-rule.md:L122-125`). Metamorphic relations
  catch it regardless: duplicating every row leaves the population std
  unchanged but moves the sample std (`OLD:TODO.md:L796-810`).
- Divergence markers worth copying: Ibis's `notimpl` / `notyet` / `never`, and
  cuML's xfail list with a marker for "the reference is wrong" and a version
  condition (`OLD:TODO.md:L818-831`). This matches the baseline's `anomaly`
  flag.
- Iterative models: KMeans compared one-sided ("fail only if measurably
  worse than the reference's objective") and linear regression's residual
  orthogonality as an oracle needing no reference (`OLD:TODO.md:L803-810`).
  This bears on the open "iterative algorithms" point.

## New against the baseline

- DuckDB float aggregates are not reproducible across thread counts. Rechecked
  on 2.0.0: over 2 million doubles, `sum` and `stddev_pop` were bit-identical
  in two runs at `threads=1`; four runs at `threads=8` gave four different
  values each; `fsum` moved by at most one unit in the last place
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L719-723`).
- `'NaN' = 'NaN'` and `'NaN' > 3` are true; on `(1, NULL, NaN, 3)`, `max` is NaN
  and `min` is 1.0. Rechecked on 2.0.0
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L686-688`,
  `L713-714`).
- `execute("SELECT ? …", ["x"])` returns the constant `'x'`: a column name
  passed as a parameter silently becomes a literal. Rechecked on 2.0.0
  (`L700-702`).
- `ORDER BY x DESC` is not the reverse of `ASC` (NULLs last both ways);
  `2 NOT IN (1, NULL)` is NULL; `avg` 20.0 against `sum/count(*)` 13.33 with
  one NULL. All rechecked on 2.0.0 (`L715-726`;
  `OLD:syntheses/refactoring.md:L158-160`).
- DuckDB validates SQL against a schema through `EXPLAIN`, which can run as a
  test-mode gate in the one executor
  (`OLD:reports/20260824T000000Z-research-mechanical-gates-fable.md:L99`).
- `NewType("Sql", str)` under `mypy --strict` stops raw strings reaching the
  executor
  (`OLD:reports/20260824T000000Z-research-mechanical-gates-fable.md:L105`).
- The small dense solve as a numpy-or-SQL question (`OLD:TODO.md:L1319-1322`).
- Library code banned from importing numpy, pandas or sklearn by `TID251`,
  with the fix stated in the message, and the gaps it leaves:
  `importlib`, `noqa`, `scipy` pulling numpy in, and `duckdb.sql(...).df()`
  (`OLD:TODO.md:L1293-1305`).
- Docstrings checked against the signature mechanically, with a test that the
  gate can fail (`OLD:tests/test_docstrings.py:L97-160`).
- cuML runs scikit-learn's own test suite with a minimum pass rate and a
  reasoned xfail list (`OLD:TODO.md:L833-838`).
- BSD-3 obligation on adapted docstrings (`OLD:TODO.md:L146-149`).

## Contradicts the baseline

- `1 % 0`: the attempt recorded NULL on DuckDB 1.5.5
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L724`); on 2.0.0
  it raises `InvalidInputException` ("Division by zero"). `1/0` is still `inf`.
- "Every attempt used sqlglot": this one used none, and rejected it as a
  validator on a measured case.
- Validation: the overview and the April repo want exact references; this
  attempt makes a live scikit-learn the sole oracle and has the tolerance
  derived from measurement (`OLD:architecture/sklearn-parity.md:L17-20`).
- Python floor 3.11 (`OLD:pyproject.toml:L5`) against ADR 0007's 3.12; a
  `duckdb==1.5.5` exact pin against the floors in earlier attempts.

## Confirms the baseline

- ADR 0003: scikit-learn's names, `get_params` and `set_params`, no
  `learn`/`apply` (`OLD:architecture/sklearn-parity.md:L9-15`, `L56-57`).
- `stddev` is the sample statistic in DuckDB, so `StandardScaler` needs
  `stddev_pop` (`OLD:architecture/sklearn-parity.md:L37-52`).
- NaN is not NULL: one NaN makes `avg` NaN
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L713-714`).
- Never tested against a whole pipeline; the composition gap was named and left
  open (`OLD:reports/20260824T133416Z-reviewer-coverage-gaps.md:L170-177`).
- Loosened tolerances hide mismatches, now named as a failure: "a tolerance
  widened until parity holds" and scikit-learn PR #12732
  (`OLD:TODO.md:L673-683`, `L847-856`).
- Process outgrew product: no estimator, 219,000 words of research, and a
  self-inflicted loss of uncommitted work (`OLD:TODO.md:L35-57`).
- Documents asserting verification nobody ran, "the second time"
  (`OLD:TODO.md:L177-199`).
- A separate review sweep found real bugs (C1–C5 and others fixed)
  (`OLD:TODO.md:L81-101`), and deterministic checks beat agent reviewers
  (`OLD:syntheses/multi-agent-pipelines.md:L29-30`).

## Worth keeping

- The one-page parity decision, especially "When the two disagree, the SQL
  changes" and the oracle being the only check outside the conversation
  (`OLD:architecture/sklearn-parity.md:L9-35`).
- The DuckDB trap list as fixture requirements: NULL, NaN, empty input, one row,
  ties, `ORDER BY` with a full tie-break, `threads` policy
  (`OLD:reports/20260824T000000Z-research-code-craft-opus.md:L680-728`;
  `OLD:reports/20260824T000000Z-research-code-craft-fable.md:L77-97`).
- One executor module for all SQL, with an `EXPLAIN` gate in test mode and a
  ban on calling `.execute` elsewhere.
- The signature and docstring gates against the installed scikit-learn.
- Metamorphic relations as a supplement to the reference (row duplication for
  `ddof`, permutation, `fit_transform ≡ fit().transform()`).
- Divergence markers with a reason and a version condition (Ibis, cuML).
- The two scikit-learn conventions that catch people out (`ddof` per estimator,
  zero-variance `scale_ = 1`) and the category-order match under `BINARY`
  collation.

## Files covered

Syntheses (`OLD:syntheses/`, 17). Every one had its question and "Where
they agree" read in full, and was searched for library terms. Marked [x] where
the disagreement, claims and noticed sections were also read; [~] where only
the opening was read, because the topic is purely about agents.

- [~] `change-size.md`: unit of work = one method plus SQL.
- [x] `code-craft.md`: choke-point module, DuckDB quirks, where tolerance comes
      from.
- [~] `context-engineering.md`: rules for writing agent documents.
- [x] `debugging-workflow.md`: ladder; thread-count non-determinism measured.
- [x] `documentation.md`: docstrings verified against upstream; licence.
- [x] `hardened-testing.md`: parity, honesty controls, MRs, SQL mutation.
- [x] `high-assurance.md`: oracle battery, `estimator_checks`, TLA+ trigger.
- [~] `information-barriers.md`: oracle provenance, judgement independence.
- [~] `loop-convergence.md`: ratchet with three loops.
- [x] `mechanical-gates.md`: orchestrator-run gates, `EXPLAIN`, signature
      parity.
- [~] `multi-agent-pipelines.md`: about seven roles, admission test.
- [x] `planning-workflow.md`: contract contents.
- [x] `redteam-coding-rule.md`: attack on the first rule; `ddof` figures.
- [x] `refactoring.md`: empty `tests/` diff, SQL identity, DuckDB traps.
- [~] `review-workflow.md`: one reviewer per artefact, no Edit.
- [~] `task-intake.md`: decisions reserved for Tomas.
- [~] `test-ordering.md`: plan → tests → code; exposure is what matters.

Reports (`OLD:reports/`, 38). [~] means recommendation and front matter read,
plus a search for library terms.

- [x] `TEMPLATE.md`: report shape.
- [~] `20260823T225316Z-research-debugging-workflow-fable.md`: debugging.
- [~] `20260823T225316Z-research-debugging-workflow-opus.md`: debugging.
- [~] `20260823T225316Z-research-documentation-fable.md`: docs.
- [~] `20260823T225316Z-research-documentation-opus.md`: docs, prototype.
- [~] `20260823T225316Z-research-hardened-testing-fable.md`: testing arsenal.
- [~] `20260823T225316Z-research-hardened-testing-opus.md`: testing; sqlglot as
  mutator.
- [~] `20260823T225316Z-research-high-assurance-fable.md`: survey.
- [~] `20260823T225316Z-research-high-assurance-opus.md`: survey.
- [~] `20260823T225316Z-research-information-barriers-fable.md`: barriers.
- [~] `20260823T225316Z-research-information-barriers-opus.md`: barriers.
- [~] `20260823T225316Z-research-loop-convergence-fable.md`: loops.
- [~] `20260823T225316Z-research-loop-convergence-opus.md`: loops.
- [~] `20260823T225316Z-research-multi-agent-pipelines-fable.md`: roster.
- [~] `20260823T225316Z-research-multi-agent-pipelines-opus.md`: roster.
- [~] `20260823T225316Z-research-planning-workflow-fable.md`: planning; MRs.
- [~] `20260823T225316Z-research-planning-workflow-opus.md`: planning.
- [~] `20260823T225316Z-research-redteam-coding-rule-fable.md`: red team.
- [~] `20260823T225316Z-research-redteam-coding-rule-opus.md`: red team.
- [~] `20260823T225316Z-research-review-workflow-fable.md`: review.
- [~] `20260823T225316Z-research-review-workflow-opus.md`: review.
- [~] `20260823T225316Z-research-test-ordering-fable.md`: ordering.
- [~] `20260823T225316Z-research-test-ordering-opus.md`: ordering.
- [~] `20260824T000000Z-research-change-size-fable.md`: unit size.
- [~] `20260824T000000Z-research-change-size-opus.md`: unit size; composition
  gap read.
- [~] `20260824T000000Z-research-code-craft-fable.md`: craft; SQL clauses read.
- [~] `20260824T000000Z-research-code-craft-opus.md`: craft; DuckDB list read in
  full.
- [~] `20260824T000000Z-research-context-engineering-fable.md`: agent docs.
- [~] `20260824T000000Z-research-context-engineering-opus.md`: agent docs.
- [~] `20260824T000000Z-research-mechanical-gates-fable.md`: gates; gates 4–6
  read.
- [~] `20260824T000000Z-research-mechanical-gates-opus.md`: gates.
- [~] `20260824T000000Z-research-refactoring-fable.md`: refactoring.
- [~] `20260824T000000Z-research-refactoring-opus.md`: refactoring.
- [~] `20260824T000000Z-research-task-intake-fable.md`: intake.
- [~] `20260824T000000Z-research-task-intake-opus.md`: intake.
- [~] `20260824T133416Z-reviewer-coverage-gaps.md`: G1–G40, D1–D16; G11,
  G21–G24 and the closing read in full.
- [~] `20260824T133416Z-reviewer-fidelity-research-vs-rules.md`: front matter
  only.
- [~] `20260824T133416Z-reviewer-redteam-rules.md`: front matter only.

Architecture, code, tests and top level:

- [x] `architecture/README.md`: index and dead-citation scans.
- [x] `architecture/sklearn-parity.md`: the product decision.
- [x] `src/sql_learn/__init__.py`: version only.
- [x] `src/sql_learn/py.typed`: empty.
- [ ] `src/sql_learn/__pycache__/*.pyc` (2): generated, not opened.
- [x] `tests/test_package.py`: numpy-not-loaded check.
- [x] `tests/test_docstrings.py`: docstring gate.
- [ ] `tests/__pycache__/*.pyc` (3): generated, not opened.
- [x] `CLAUDE.md`: aim, attribution, rules and reports protocol.
- [~] `TODO.md`: Now, Next, Blocked, Someday, and the parity and tolerance
  rows read in full; the superseded agent-layer rows (about L240–L1230)
  searched for library terms only.
- [x] `pyproject.toml`: pins, bans, ruff selection.

No read hung or failed.
