---
type: spec
tags: [aggregates, nested, compositor, median, std, learn, larger-than-memory]
summary: "Spec for learning an aggregate inside another (#49): every aggregate gets a level, one more than the deepest inside its argument, and each level is today's staged machinery over the learn stage's input cross-joined with the levels below, all in one WITH query; the refusals of ADR 0036 and 0044 go, but for what sq.agg did not build."
related: [docs/adr/archived/0051-aggregates-learn-in-levels.md, docs/adr/archived/0036-staged-aggregates-anywhere-in-a-learned-value.md, docs/adr/archived/0044-the-standard-deviation-in-two-staged-passes.md, docs/adr/archived/0032-the-median-is-exact-by-sorting.md, docs/adr/archived/0012-static-and-dynamic-steps.md]
---
# Learning nested aggregates

Issue #49. Status: approach chosen by Tomas on 2026-11-17 (A, levels), after
a research pass on how DuckDB 2.0 keeps and spills data (§6).

## 1. Intent

A step's `learn` may return an aggregate whose argument holds another
aggregate: the inner one is computed first and its one value fed to the outer
one, row by row. Tomas ruled this on 2026-11-10 (issue #49): sqlearn learns
these instead of refusing them. Who uses it: anyone writing a step, and later
built-in steps (a robust scaler by the median absolute deviation).

The two examples on the issue, both returned from a step's `learn`:

```python
sq.agg.std(x - sq.agg.mean(x))
sq.agg.median(sq.fn.abs(x - sq.agg.median(x)))  # median absolute deviation
```

On `x = 1, 2, 3, 4, 100`: the inner median is 3, the distances 2, 1, 0, 1, 97,
their median 1.

## 2. What happens today

Measured on 2026-11-17 (`sq.Pipeline([("s", step)]).learn(rel)` on 10 values):

| A step learns | Today |
|---|---|
| `mean(abs(x - median(x)))` | learned: the median's stage runs first, the plain select reads it |
| `std(x - mean(x))` | refused (ADR 0044's amendment): plain inside staged |
| `median(abs(x - median(x)))` | refused as "an aggregate of an aggregate, which has no meaning" |
| `std(x - std(x))` | refused (ADR 0044): std inside std |
| `quantile(x - std(x))` | refused (ADR 0044): quantile of an expression holding a std |
| `sum(x - mean(x))` | DuckDB's raw binder error, no step named |

Today's order within one learn stage is fixed (`_learn_ctes` in
`src/sqlearn/_compose.py`): the quantile sort, the mode count and the target
statistics read the stage's input; the std/var passes read the input
cross-joined with those; the plain one-row select reads the input
cross-joined with all of them. Each row of the table above that is refused
is a shape that order cannot hold.

## 3. Goals, non-goals, anti-goals

Goals:

- Every row of §2's table is learned, with the values numpy gives on data
  without missing values.
- Any depth: an aggregate may sit inside an aggregate inside an aggregate.
- A plain DuckDB aggregate inside another (`sum(x - mean(x))`) is learned
  too, from the same mechanism (the issue asks to say either way: in).
- Every aggregate of one level of one learn stage, over every column the
  step learns, shares that level's passes: one plain pass, one sort for all
  its quantiles, one count for all its modes, one pair of passes for all its
  standard deviations and variances.
- One `WITH` query per run, as now (ADR 0012, 0018): no extra run, nothing
  fetched to Python between levels.

Non-goals:

- No algebraic rewriting: `std(x - mean(x))` is computed as written, not
  replaced by `std(x)`, and `sum(x - mean(x))` is not replaced by 0.
- No sharing of passes between steps: each step's learn stage reads its own
  input (the step before it), so two steps cannot share a level.
- No change to what any built-in step learns, nor to a learned value that is
  not nested (byte for byte the same SQL where no nesting exists is not
  required, the same values within ADR 0043's rounding are).

Anti-goals (a failure even if it works):

- A nested aggregate that gives up the reach beyond memory: the inner and
  outer medians stay sqlearn's sort (ADR 0032), never DuckDB's `median`,
  `quantile` or `mad`, whose state must fit in memory (§6).
- A nesting that silently computes something else (the inner value read from
  the wrong rows, or a NULL inner value treated as 0).

## 4. Design (approach A: levels)

- **A level per aggregate.** Each aggregate in a learned value, staged
  (quantile, median, mode, std, var, target statistics) or plain (any DuckDB
  aggregate: `favg`, `sum`, `min`, `count`, ...), has a level: 1 when its
  argument holds no aggregate, else 1 more than the highest level inside its
  argument. A learned value's outermost expression reads the levels it holds.
- **A level is today's machinery.** Level `k` of a learn stage computes all
  its aggregates over the stage's input cross-joined with the one-row results
  of levels `1 .. k-1`, in the order today's stage uses: quantile sort, mode
  count, target statistics, then the std/var passes, then the plain
  aggregates. An inner aggregate is replaced in its outer one's argument by
  the plain column of its level's row, as `mean(abs(x - median(x)))` reads
  the median's row today.
- **One query.** Every level is a CTE of the run's `WITH` query; the learn
  stage's final row is the last. The stage's input is referenced by every
  level, so DuckDB 2.0 materializes it (§6): the input is read once.
- **Plain aggregates are found in the SQL text** as today
  (`_aggregate_names`, `_in_aggregates`): DuckDB's list of aggregate
  functions, plus `filter`. A plain aggregate's level is found as a staged
  marker's is.
- **Refusals that remain**, in the house form (`StepError` naming the step,
  a reason, a `Fix:`): a marker `sq.agg` did not build (as today); and an
  aggregate inside a target statistic's arguments (the target encoder's own
  marker: it is cross-fitted per fold, and no built-in step nests it). The
  refusals of §2 go. No new refusal is added: a window function in a learned
  value behaves as today (a build call, 2026-11-17).
- **Missing values** (a build call, 2026-11-17, by ADR 0046: sqlearn does not
  change what the user asked): an inner value that is NULL (a column with no
  present value) is fed to the outer aggregate as NULL, and each aggregate
  does with it what its SQL does. Every `sq.agg` aggregate then gives NULL
  (it leaves NULL and NaN out, so it sees no value); a plain DuckDB
  aggregate keeps DuckDB's own result (`count(x - mean(x))` is 0,
  `sum(x - NaN)` is NaN). sqlearn wraps nothing. Tests assert this for
  `sq.agg` and for `count` and `sum`.
- **DuckDB's own holistic aggregates** (`median`, `quantile_cont`, `mad`)
  written by a user in a learned value are learned as written, nested or
  not, as they are today; so is `sq.agg.median(approx=True)`
  (`approx_quantile`, constant memory). The anti-goal binds what sqlearn
  builds, not what a user writes (a build call, 2026-11-17).

## 5. Cost

Each level beyond the first adds that level's passes over the stage's
materialized input: one pass for its plain aggregates, a sort when it holds a
quantile, a count when it holds a mode, two passes when it holds a std or
var. A learned value with no nesting keeps today's cost. Measured on
2026-11-17 with DuckDB's own median as a stand-in (10,000,000 rows, 4 columns,
Parquet, a loaded machine): 4 medians 0.59 s, 4 median absolute deviations
1.21 s. The build measures sqlearn's own levels and records them in the ADR.

## 6. How DuckDB 2.0 keeps the data (research, 2026-11-17)

From DuckDB 2.0's documentation and source (pinned in `uv.lock`):

- A CTE referenced more than once is materialized by default since 1.4; a
  materialized CTE is buffer-managed and spills to the temporary directory
  when memory runs short. So the levels read the source once; DuckDB decides
  RAM or disk.
- Two separate scans of a local file (scalar subqueries) are not shared:
  DuckDB's common-subplan optimizer merges only subplans ending in an
  aggregate, a distinct or a window, and local files are not cached
  (`cache_local_files` is false in 2.0). Hence CTE levels, not subqueries.
- DuckDB's `median`, `quantile` and `mad` keep every value in a list outside
  the buffer manager, which cannot spill. sqlearn's median sorts, and the
  sort spills (ADR 0032, 0036). Hence the anti-goal of §3.
- No optimizer rule merges an inner and an outer aggregate into one pass.

## 7. Done when

- Each row of §2's table is learned and tested against numpy, through a
  step's `learn` (vertical slices, GLOSSARY terms).
- The median absolute deviation is validated against
  `scipy.stats.median_abs_deviation` (scipy comes with scikit-learn) in
  `validation/`, within the median's bound.
- A three-level nesting and two columns sharing a level are tested, the
  latter by the number of passes in the SQL, not by timing.
- **Reach** (a build call, 2026-11-17): the median absolute deviation is
  learned under a memory limit as the plain median's reach is measured
  (`docs/benchmarks/median-reach.md`), and its reach is recorded there and
  in ADR 0051. `_quantile_ctes` warns that two sorts in one statement hold
  memory together, so the nested reach may be lower than one median's. There
  is no fixed budget; a reach below half the plain median's at the same
  limit stops the build and comes back to Tomas, as would a level costing
  more than about twice the cost of the level below it.
- The refusals of §4 are tested in the house form; `sum(x - mean(x))` no
  longer gives DuckDB's raw error.
- ADR 0051 (amending 0036 and 0044) records the levels and the measured cost
  of a level; the amendments in 0036 and 0044 point to it.
- The writing-a-step guide shows a nested aggregate.

## 8. Approaches considered

| | How | Covers | Why not |
|---|---|---|---|
| **A: levels** (chosen) | §4 | every shape, any depth | — |
| B: one extra step in front | a fixed inner pass and a second quantile sort before today's order | the two examples and `sum(x - mean(x))` | `std(x - std(x))` and deeper stay refused; each new shape is another special case |
| C: window | `abs(x - median(x) OVER ())` | every shape | DuckDB's median must hold the column in memory, losing the reach beyond memory |

Scalar subqueries in place of CTE levels were also measured: the same time on
a cached file, but one read of the file per inner aggregate (5 for 4 columns
against 2), as DuckDB does not share them.

## 9. Left to the builder

- How `_Staged` and `_learn_ctes` become a planner by level (one `_Staged`
  per level is expected), and the CTE names of each level.
- How a plain inner aggregate is lifted out of the SQL text and replaced by
  its level's column.
- Whether a learned value that is one whole marker keeps its read beside the
  scan (issue #41's optimisation) at every level.
