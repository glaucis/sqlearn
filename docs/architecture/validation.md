---
type: architecture
tags: [validation, testing, scikit-learn, accuracy, ulps, checks]
summary: "Explains sqlearn's validation: every result compared with an exact canonical value and with the reference libraries, the results and what they mean, the 24 runners, their data, how to run them, how each reruns only when what it uses changed, and what is planned."
related: [docs/adr/0016-validation-method.md, docs/adr/0043-repeatable-within-rounding.md, docs/architecture/testing.md, docs/specs/selection-by-group.md, validation/__main__.py, validation/_cases.py, validation/_record.py, validation/_groups.py]
---
# Validation

The validation checks that every number sqlearn computes is right. It compares
each result with the exact mathematical answer and with the libraries that
compute the same thing, and it writes every measurement down. The method is
[ADR 0016](../adr/0016-validation-method.md); the bounds are
[ADR 0043](../adr/0043-repeatable-within-rounding.md). The tests check that
the code does what it says; the validation checks that its numbers are the
true ones.

## One case

A case is one formula, on one dataset, from one source. For example the mean
that `sq.scale.standard()` centres a column by, on the four-row `small`
dataset:

1. **The canonical value**: the exact answer, computed in Python with
   `Fraction` where the answer is rational and with `mpmath` at 50 digits
   otherwise (`DIGITS` in `validation/_cases.py`), never taken from another
   library. Here `1018.4737031349603`.
2. **sqlearn's value**: the step's SQL, run in sqlearn's DuckDB.
3. **The distance**, in ULPs (units in the last place), against a bound set
   from measurement; loosening a bound needs a written reason.
4. **The same for each reference** that computes it: scikit-learn, numpy,
   scipy, pandas.

To place a drift, a formula DuckDB computes is also measured with DuckDB's own
function alone (a DuckDB limitation then shows as DuckDB's) and on one thread
(drift from parallel summation then shows as such).

## The results

Every results file starts with what each result means (`RULES` in
`validation/_cases.py`):

| Result | Meaning |
|---|---|
| `pass` | sqlearn within its bound (0 mismatches for an encoder); a reference within `ANOMALY_FACTOR` (4) times sqlearn's bound, or refusing an input with no answer |
| `fail` | sqlearn only: outside its bound, or a mismatch with scikit-learn. The run fails and blocks the merge |
| `anomaly` | a reference more than 4 times sqlearn's bound from the canonical value: it misses what its own algorithm should reach. Reported upstream, never a reason to loosen a bound |
| `recorded` | a measurement with no bound to pass (`approx_quantile`, approximate by name): its error is kept as a known number |
| `skipped` | the reference cannot run on this input, or the input has no canonical value; the note says which. Kept so the table shows every combination |

A runner prints its counts, for example `validate_aggregates: {'anomaly': 6,
'pass': 596, 'recorded': 21, 'skipped': 73}`: every sqlearn case passed, and
six reference values drifted.

## The data

Every dataset is generated from seed 0 (`SEED`), never downloaded
([ADR 0006](../adr/0006-local-and-offline.md)): `small` (4 rows), `medium`
(1,000), `large` (100,000), and the awkward ones, `null`, `nan`, `empty`,
`single` and `reserved` (column names that are SQL words). The numbers sit
around 1,000, far from zero, so a carelessly computed mean or variance shows.
The `devdata` runners check the development datasets themselves.

## The runners

24 runners, listed in `RUNNERS` (`validation/__main__.py`), one module each:

- **Aggregates**: `validation/sqlearn/agg/validate_aggregates.py`.
- **Preprocessing** (`validation/sqlearn/preprocessing/`): impute, scale,
  one-hot, ordinal, target encoding, binning, transforms, features.
- **Metrics** (`validation/sqlearn/metrics/`): accuracy, regression,
  probability, classification, balanced, tables, curves.
- **Feature selection, decomposition (PCA), exploration**: one each.
- **Whole pipelines** (`validation/pipelines/`): slicing, a preprocessing
  pipeline against scikit-learn's step for step, and model selection against
  scikit-learn's search.
- **Development data** (`validation/devdata/`): the bundled and the generated
  datasets.

Each runner's `cases()` returns its cases, and its results go to the
`*.results.json` beside it, with the rules at the top. `environment.json`
records what they were measured with: the libraries, Python, the OS and its
release, the machine and numpy's BLAS.

## Running it

- `just validate` runs each runner whose inputs changed since it last
  passed (below), each in a process of its own.
- `just validate-all` reruns every runner whatever its records say: at a
  release, so its results come from one full run.
- `just done` and `just verify` run it with the other checks (`validate` and
  `validate-all`).
- One runner alone: `uv run --locked python -c "from validation.__main__
  import main, ROOT; main(['validation.sqlearn.decomposition.validate_pca'],
  ROOT)"` (`main` takes `validation/` as its root, never `.`).

A full run takes about 47 minutes on this machine: each case is computed
several ways, the exact side in Python's `Fraction` and `mpmath`, over every
dataset. A rerun's numbers differ from the last only in their last digits
(DuckDB sums in thread-finish order, ADR 0043): discard those changes to the
results files, and check that no `result` moved between `pass` and `fail`.

## When a runner reruns

Each runner keeps records of its passed runs (`validation/_record.py`, in git's
common directory, shared by every worktree). A record holds the SHA-256 of
every repository file the runner imported, of `uv.lock` and of
`devdata/data/`, the environment, and the key `groups`: the fingerprints of
the C++ groups the runner uses and of the module's shared part
(`validation/_groups.py`). A runner is skipped, printing `unchanged since a
passed run`, while the newest record matching all of that passed. The full
description is in [Testing](testing.md) ("Selecting by group" and "The
validation runners"); the design is the
[selecting by group spec](../specs/selection-by-group.md).

What reruns, today:

| Change | Runners rerun |
|---|---|
| a docs page, a comment, CMake text, a C++ test or fuzz input | none |
| a real change in the C++ | every runner: all of today's C++ (`core`, `raw`, `crash`) runs when the module loads. After the rewrite (ADR 0070), only the runners the changed group claims (`VALIDATION` in `sq_add_group`) |
| any file under `src/sqlearn` | every runner: `import sqlearn` loads the whole package, which is frozen during the rewrite |
| `validation/__main__.py`, `_cases.py`, `_groups.py`, `uv.lock` | every runner: every runner imports them |
| one runner's own module | that runner |

A runner whose groups' fingerprints, or whose files, changed while it ran
records no pass; a failing run reruns every time.

## What stays Python, and what is planned

The validation is development tooling: it never ships. It stays in Python
where it calls a reference library (scikit-learn, numpy, scipy and pandas are
Python). The rest is planned to move to C++ (`HANDOFF.md`, "Next up"):
first each runner's wall time in its record, to see where the 47 minutes go;
then the exact arithmetic (for example with Boost.Multiprecision), the runner
code and the case generation, the heaviest runners first. ADR 0016's step
pages, generated from the runs, are still to be built: the published page
[Validation](../validation/index.md) is a placeholder until then.
