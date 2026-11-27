---
type: adr
tags: [validation, tests, benchmarks, results, layout, publishing]
summary: "Records that every validation, test and benchmark result is stored as committed JSON with fixed names, in folders that mirror the package, so pages can publish all of it later."
related: [docs/adr/0016-validation-method.md, docs/architecture/layout.md, docs/architecture/testing.md, docs/specs/archived/library-core.md]
---
# 0025: Results stored as data, in folders that mirror the package

Status: accepted (2026-11-04). Adds to [ADR 0016](0016-validation-method.md),
which asks for validation pages generated from the runs.

## Context

sqlearn is to convince its users that it is serious: tested, validated against
the mathematics and against every comparable library, and fast. All of it is to
be published: each step's validation, and a page of every test and how it
passed. The pages are built later (overview 3.8, 3.9); the results must be
there, complete and easy to find, from the first step on.

## Decision

**Results are data.** Every run writes its results as JSON with fixed names,
and they are committed:

- each validation case: the step, the formula, the dataset and its size, the
  type, the reference, the absolute, relative and ULP error, the bound and the
  result (pass, fail or anomaly);
- every test: its name, area, tier (fast or slow) and outcome;
- the environment: the versions of sqlearn, DuckDB, the reference libraries,
  Python and the operating system.

The files hold no dates, times or durations, so they change only when a result
changes; the date and the commit come from git. `just validate` writes the
validation results and `just verify` runs it; a result outside its bound fails
the merge.

**Folders mirror the package.** Everything about one module sits at the same
path in each tree:

```text
src/sqlearn/preprocessing/scale.py                     the step
tests/src/sqlearn/preprocessing/test_scale.py          its tests
validation/sqlearn/preprocessing/validate_scale.py     its validation runner
validation/sqlearn/preprocessing/scale.results.json    its validation results
benchmarks/sqlearn/preprocessing/bench_scale.py        its benchmark (3.9)
benchmarks/sqlearn/preprocessing/scale.results.json    its benchmark results
```

Tests keep mirroring the whole repository (`tests/src/sqlearn/`, as
`tests/githooks/` mirrors `.githooks/`); validation and benchmarks are only
about the package and mirror it directly. Results about more than one module
sit at the top: `validation/environment.json`, `validation/tests.json`,
`validation/pipelines/<name>.results.json`.

A check in `just check` fails when a module in `src/sqlearn/` has no test file,
or a step has no validation runner, and names the missing file.

## Consequences

- A page generator collects `validation/**/*.results.json` and
  `benchmarks/**/*.results.json`; it is built with the validation and
  benchmark parts (overview 3.8, 3.9). DuckDB can query the JSON directly.
- A changed number shows as a readable diff in git, with its history.
