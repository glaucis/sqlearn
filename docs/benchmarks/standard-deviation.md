---
type: note
tags: [benchmarks, performance, std, numerics, larger-than-memory, sqlearn]
summary: "Times the two-pass standard deviation against DuckDB's one-pass stddev_pop on 20,000,000 rows under a 64 MB limit on one thread, and with no limit, with each result's distance from the exact value."
related: [docs/benchmarks/index.md, docs/benchmarks/onehot-second-run.md, docs/benchmarks/category-lookup.md]
---
# The standard deviation in two passes

[Issue #28](https://github.com/glaucis/sqlearn/issues/28) moved
`sq.agg.std` from DuckDB's one-pass `stddev_pop` to two passes: the mean with
the compensated `favg`, then `sqrt(favg((x - mean) ^ 2))` over the rows beside
that one mean, each pass a stage of its own. This page states what the second
pass costs on large data, and how far each form lands from the exact value. It
recommends nothing.

## What was measured

- **Data:** generated from a fixed seed (`SEED = 0`) into a temporary
  directory: one DOUBLE column of 20,000,000 rows, a tenth NULL, the rest
  spread evenly over 900 to 1,100, far from zero as the validation's values
  are. 115.1 MB as Parquet; 18,000,172 present values.
- **Forms:**
  - `stddev_pop(x)` and the two passes written as DuckDB SQL, read from the
    Parquet file;
  - through sqlearn, a one-step pipeline learning one column's standard
    deviation: once with an aggregate building `stddev_pop` of the present
    values (`sq.agg.std` as it was), once with `sq.agg.std` as it is;
  - `sq.scale.standard()` learned, which also learns the mean, the count and
    the variance for its zero-spread rule.
- **Times:** wall clock, the median of three repetitions after one discarded
  run; sqlearn learns from scratch (the step store cleared) every time.
- **Settings:** `SET memory_limit = '64MB'` with `SET threads = 1`, the
  core's larger-than-memory setting, then no limit with DuckDB's default
  threads (8). A form that runs out of memory would be recorded as failed.
- **Exact value:** every value lies in [512, 2048), so each is a whole
  multiple of 2^-43; scaled by 2^43, Python's integers sum the values and their
  squares exactly, and the root is taken at 50 digits with mpmath. Each form's
  distance from it is given in ULPs.

The machine details come from `sysctl` and are macOS-only; on other systems
the script prints "unknown" for them.

Reproduce with `uv run python -m validation.benchmarks.std_cost`. It takes
about half a minute on this machine.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| sqlearn | 0.1.dev237+g195e3574f (with the two passes, before their commit) |

## Results

The exact population standard deviation is `57.73272902140357`.

| memory limit | threads | form | s | ULPs from exact |
|---|---|---|---|---|
| 64 MB | 1 | `stddev_pop` (DuckDB SQL) | 0.317 | 700 |
| 64 MB | 1 | two passes (DuckDB SQL) | 0.803 | 1 |
| 64 MB | 1 | one pass, learned by sqlearn | 0.403 | 700 |
| 64 MB | 1 | `sq.agg.std`, learned by sqlearn | 1.152 | 1 |
| 64 MB | 1 | `sq.scale.standard`, learned | 1.634 | 1 |
| none | 8 | `stddev_pop` (DuckDB SQL) | 0.061 | 47 |
| none | 8 | two passes (DuckDB SQL) | 0.154 | 1 |
| none | 8 | one pass, learned by sqlearn | 0.076 | 41 |
| none | 8 | `sq.agg.std`, learned by sqlearn | 0.179 | 1 |
| none | 8 | `sq.scale.standard`, learned | 0.276 | 1 |

## What the numbers show

Every form runs within 64 MB on one thread; none failed.

Under 64 MB on one thread, learning the standard deviation through sqlearn
takes 1.152 s in two passes against 0.403 s in one, about 2.9 times as long;
as DuckDB SQL alone, 0.803 s against 0.317 s, about 2.5 times. With no limit
on eight threads, 0.179 s against 0.076 s through sqlearn.

On these 18,000,172 values, `stddev_pop` lands 700 ULPs from the exact value on
one thread and 41 to 47 on eight; the two passes land 1 ULP from it in every
setting. The validation's 100,000 values show 12 ULPs for `stddev_pop` and 1
for the two passes.
