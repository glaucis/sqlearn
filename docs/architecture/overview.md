---
type: architecture
tags: [sqlearn, duckdb, roadmap, scikit-learn, parts]
summary: "Project map of sqlearn: its purpose, agreed constraints, the parts from foundation to validation, and their build order."
related: [docs/adr/0003-scikit-learn-style-api.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/0004-apache-2-licence.md, docs/adr/0005-runtime-dependencies.md, docs/adr/0006-local-and-offline.md, docs/questions/applications-home.md, docs/adr/0001-uv-for-python-packaging.md, docs/adr/0007-python-3-12-floor.md]
mdindex: [type=4ca303, tags=83b516, summary=39d7b0, related=c3fc8f]
---
# Overview

The map of the whole project, written before the first line of product code.
It says what the parts are, how they relate, and in what order they are
built. Each part gets its own spec in `docs/specs/` when its turn comes.

Status, 2026-11-03: the foundation (3.1) is built; everything else is the plan.

Three kinds of statement, marked where it matters:

- **Agreed**: what Tomas has decided.
- **Proposed**: a proposal that stands until overturned.
- **Open**: still to be decided; each has a file in
  [`docs/questions/`](../questions/README.md).

## 1. Purpose

sqlearn is an alternative to the scikit-learn ecosystem, built on Python and
DuckDB. Its computation runs inside DuckDB as SQL, so it works on data larger
than memory, where the NumPy-based stack stops. Its user-facing API follows
scikit-learn ([ADR 0003](../adr/0003-scikit-learn-style-api.md)), so
scikit-learn users feel at home.

It comes with documentation to the standard set by scikit-learn and the other
large scientific-Python projects, and with a website that teaches machine
learning from the beginning in one sequential path, which nothing available
today does end to end.

Who it is for: people who prepare data that does not fit in memory and train
models on it, and people learning machine learning who want one ordered path
instead of scattered tutorials.

In time, two graphical applications join the library (agreed):

- an interactive tool for exploratory data analysis, of the kind
  ydata-profiling offers but far more advanced and interactive;
- once the library is mature, a node-based workflow editor in the manner of
  ComfyUI, where every pipeline step is a node that users add, join and merge,
  and where analysis, pipeline building and modelling happen on one canvas.

They are later parts, and the library is designed from the start so that they
need no retrofit.

### Why, against the alternatives (agreed)

- scikit-learn stands on NumPy, so the data must fit in memory.
- pandas has the same limit. Polars lifts it with lazy execution, but its
  optimisations can surprise, and turning an eager workflow into a lazy one
  step by step is not straightforward.
- The Apache systems (Spark and its kin) scale, at the price of a JVM to spin
  up and a cluster to run and operate.

sqlearn's answer: one process on one machine. DuckDB does the planning and the
larger-than-memory work underneath
([ADR 0002](../adr/0002-sql-on-duckdb-execution-engine.md)). The user writes
steps in order, as in scikit-learn, with no lazy-versus-eager split to manage
(proposed: the core's design principle, for 3.2 to prove). Because every step
is SQL, a pipeline can be combined into one query and run in one go. It runs
on a laptop or an on-premises server, offline, with no cloud and no cluster,
so a company or a government department can use it where data may not leave
the building.

## 2. Constraints (agreed)

- **Python and DuckDB.** Computation is pushed into DuckDB; Python is the glue
  ([ADR 0002](../adr/0002-sql-on-duckdb-execution-engine.md)).
- **One runtime dependency.** The installed package depends on `duckdb`,
  nothing NumPy-shaped, and as little else as possible; every runtime
  dependency is justified in writing
  ([ADR 0005](../adr/0005-runtime-dependencies.md)). Tools used to build,
  test, validate and document the project are free to use anything.
- **Licence.** Apache-2.0, free for any use; anything paid is a separate
  package ([ADR 0004](../adr/0004-apache-2-licence.md)).
- **Local and offline.** No cloud service, no cluster, no telemetry, no
  network access needed; data never leaves the machine
  ([ADR 0006](../adr/0006-local-and-offline.md)).
- **One package, `sqlearn`, for now.** More packages later, the applications
  among them, laid out so that adding one moves nothing. The applications
  bring a browser front end, and the layout admits it. Where they live is
  open: [questions/applications-home.md](../questions/applications-home.md).
- **Professional throughout:** code, tests, documentation, process.
- **One static site** for the documentation and the learning path, on GitHub
  Pages ([ADR 0009](../adr/0009-sphinx-documentation-site.md)). The repository
  is private, and GitHub Pages serves a private repository only on a paid
  plan. Open: [questions/site-hosting.md](../questions/site-hosting.md).
- **Tooling:** uv ([ADR 0001](../adr/0001-uv-for-python-packaging.md)),
  Python 3.12 as the floor ([ADR 0007](../adr/0007-python-3-12-floor.md)),
  `just` as the task runner ([ADR 0008](../adr/0008-just-task-runner.md)),
  British prose with American identifiers
  ([ADR 0010](../adr/0010-british-prose-american-identifiers.md)).

## 3. The parts

Each part is a sub-project with its own spec, plan and implementation.

### 3.1 Foundation

**What:** the repository skeleton: layout, packaging, quality gates, the docs
toolchain with a skeleton site, and the conventions everyone writes to. It
fixes only what is expensive to change later, and holds no product code.

**Done when:** a fresh clone installs with one command, `just verify` passes
on it, its docs build, and the conventions are written where every agent reads
them. CI and the site deploy join when the repository is public.

**Depends on:** nothing. It comes first. Draft spec:
[specs/foundation.md](../specs/foundation.md).

### 3.2 Library core

**What:** the contracts everything else is built on: the API (`learn` and
`apply` for steps, `train` and `predict` for models:
[ADR 0013](../adr/0013-learn-apply-train-predict.md); and what a parameter is),
the data model over DuckDB relations, the pipeline, and how an algorithm is
expressed in SQL.

Two requirements come from the later applications and are cheapest met here:

- every step declares its parameters, inputs and outputs as data, so that a
  node editor can present it without special cases;
- a pipeline is a graph, so that what the editor draws and what the code runs
  are one object. Saving it to a file and back, and exporting a trained
  pipeline as standalone code, are later ideas
  ([issue #24](https://github.com/glaucis/sqlearn/issues/24); the saving of
  a pipeline is built, in 3.3).

The user writes steps in order and sees results when asked, as in
scikit-learn; how much of a pipeline runs as one query is the library's
concern, never the user's: everything goes in one query, split only where
a step needs columns a dynamic step has not yet learned
([ADR 0012](../adr/0012-static-and-dynamic-steps.md),
[ADR 0018](../adr/0018-runs-follow-the-chains-between-steps.md)), and learned
values are kept in a store while the program runs, so nothing is learned twice
([ADR 0014](../adr/0014-learning-store.md)). See also
[questions/scikit-learn-api-survey.md](../questions/scikit-learn-api-survey.md).

Proven by one vertical slice: a few preparation steps, enough to show static
steps chaining (`Impute` then `Scale`), a dynamic step (`OneHot`), and two
independent dynamic steps sharing a run; one search over folds; the prepared
data handed to an outside model library; one metric; end to end, with the
preparation on data larger than memory. Its tests assert the number of runs as
well as the results, over every combination of steps that can be built. Models
come from other libraries for now
([ADR 0017](../adr/0017-models-from-other-libraries.md)).

**Done when:** the slice runs, its tests pass against a reference
implementation (dev-only dependencies are allowed in tests), and the contract
is documented.

**Depends on:** 3.1.

### 3.3 Library breadth

**What:** the areas, each its own spec: preprocessing, model selection (a search
over hyperparameters and folds, with sqlearn's folds or an outside optimiser
such as Optuna), metrics, datasets, saving a pipeline to a JSON file (`sq.save`,
`sq.load`; [ADR 0047](../adr/0047-a-pipeline-saves-as-json.md)), where the user
saves the trained model and `sq.load` imports nothing
([ADR 0048](../adr/0048-the-user-saves-the-model-and-imports-its-packages.md)),
and whatever the core's contract makes possible. Models come from other
libraries the user installs, for now; models in SQL are a later idea
([ADR 0017](../adr/0017-models-from-other-libraries.md)).

**Done when:** never; it grows. Each area is done when its spec says so.

**Depends on:** 3.2.

### 3.4 Documentation

**What:** the API reference generated from docstrings, the user guide, and
executed examples, on the foundation's toolchain, growing with 3.3.

**Done when:** every public object has a reference page and every area a
guide chapter, and the checks cover both.

**Depends on:** 3.1 for the toolchain; 3.2 for the first content.

### 3.5 Learning site

**What:** the curriculum: machine learning taught in sequence, in three levels
([ADR 0011](../adr/0011-curriculum-levels.md)), on sqlearn, on the same site
as the documentation. Its place in the site is reserved by 3.1 so that no URL
moves later.

**Done when:** each level has its lessons, each lesson states what it assumes
and what the reader can do at its end, and the sequence has been read through
by someone at the level it is written for.

**Depends on:** 3.1 for the site; 3.2 and 3.3 for the material.

### 3.6 Exploratory data analysis

**What:** first a library module: profiling and analysis computed inside
DuckDB (distributions, missingness, correlations, cardinality, and what its
spec adds), returning structured results a program can render. Then the
interactive application that renders them. The module is usable without the
application, from code and from notebooks.

**Done when:** for the module, when its spec says so; for the application,
when a user can open a dataset and explore it without writing code.

**Depends on:** 3.2 for the data model; the application on the module. Front end
open:
[questions/application-front-end.md](../questions/application-front-end.md).

### 3.7 Workflow editor

**What:** a node-based editor in the manner of ComfyUI. Every pipeline step,
analysis and model is a node; users add, join and merge nodes on a canvas; the
graph runs on the library and serialises to the same form the library's own
pipeline uses.

**Done when:** a graph built in the editor runs unchanged from code, and a
pipeline written in code opens unchanged in the editor.

**Depends on:** 3.2's contract (declared parameters, serialisable graph); 3.3
for the nodes; 3.6 for the analysis nodes. Last.

### 3.8 Validation

**What:** the proof that the mathematics is right. For every public numeric
function (a scaler, a model, a metric), one page holds:

- the formula in LaTeX, citing its source with the equation named;
- a reference implementation in pure Python, exact where exactness exists
  (`fractions.Fraction`, or `decimal` at a precision its spec sets), since
  Python's floats are the same doubles numpy uses;
- a table of each library's error against the reference: sqlearn's, numpy's,
  scikit-learn's, Polars', whichever computes the same thing. No library is
  trusted, numpy included.

The same reference code is imported by the tests, where it guards against a
wrong SQL expression on every `just verify`. The pages do not run at build:
`just validate` computes each function with sqlearn and each library and
writes the inputs, reference value, each library's value, error and version to
`validation/results/` as JSON. The results are committed and the pages are
rendered from them, so a change in sqlearn's error shows as a diff in review.
It lives in `validation/` at the root, never in the installed package.

Sources, in order of preference: the original paper (by DOI), a standard
textbook, a government or standards body (NIST's handbooks above all), a
university course. Never a blog; Wikipedia only as a cross-check. One
bibliography serves the whole site through `sphinxcontrib-bibtex`. Each page
names the variant it computes (population or sample standard deviation, say)
and compares each library on the variant that library computes. A symbols
table maps the source's notation to sqlearn's names. A reviewer checks the
LaTeX against the source's equation.

**Done when:** every public numeric function has its page and its reference,
and the tests compare against it. The first page is 3.2's slice. The method,
with its three-way location of drift, anomaly flags and merge gate:
[ADR 0016](../adr/0016-validation-method.md). Open points:
[questions/validation-method.md](../questions/validation-method.md).

**Depends on:** 3.2 for the first function; grows with 3.3.

### 3.9 Benchmarks

**What:** sqlearn against the other libraries: speed, memory, and sizes past
memory, where the others stop. Results are data, produced on a known machine
and committed with the machine described; the pages render them. Never run at
docs build.

**Done when:** each area in 3.3 has its comparison, and a reader can see where
sqlearn stands and at what size the others stop.

**Depends on:** 3.3. Open points:
[questions/benchmarks-scope.md](../questions/benchmarks-scope.md).

### Later: other database engines

Not one of the parts yet, and planned only if users ask for it. sqlearn
targets DuckDB only and builds its SQL from DuckDB's expression objects, without
sqlglot ([ADR 0015](../adr/0015-duckdb-expressions-no-sqlglot.md)); translating
to other engines would plug into its compositor:
[questions/multi-engine-support.md](../questions/multi-engine-support.md).

## 4. Order of work

1. Foundation (3.1).
2. Library core (3.2), with the first validation page (3.8) in its slice.
3. Library breadth (3.3), documentation (3.4) and validation (3.8),
   interleaved, area by area.
4. Learning site (3.5), once there is enough library to teach on; its place on
   the site is reserved from the start.
5. Benchmarks (3.9), once breadth has something to compare.
6. Exploratory data analysis (3.6): the module alongside 3.3, the application
   after it.
7. Workflow editor (3.7), last, when the library is more or less done.

How the work runs, and where each kind of document goes:
[workflow.md](workflow.md).

## 5. Earlier attempts

This plan was first written in earlier repositories of the organisation
(`sqlearn_tomosius`, `sqlearn_000`, `sqlearn_old`, `sqlearn-private`,
`sqlearn-private-old`, `sql_learn_wrong`). Everything this repository uses from
them has been carried over: the blueprint into this overview, the ADRs and the
questions, and the foundation spec into
[specs/foundation.md](../specs/foundation.md). Nothing here depends on them, and
they are due to be deleted. `sqlearn_000` (SQL-compiled preprocessing) is to be
read for anything worth keeping before the library core is designed.
