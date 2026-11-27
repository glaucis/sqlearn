---
type: adr
tags: [learning-store, cache-keys, fold, fingerprint, steps]
summary: "ADR 0076 sets the rules for the learning store and its three-part keys (data, fold, steps), superseding ADRs 0014, 0021, 0024 and 0056."
related: [docs/adr/archived/0014-learning-store.md, docs/adr/archived/0021-inputs-and-how-the-store-knows-them.md, docs/adr/archived/0024-store-keys-follow-what-a-step-reads.md, docs/adr/archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md, docs/adr/0029-relations-from-another-connection-are-refused.md, docs/adr/0040-fold-schemes-as-sql-over-rows.md, docs/adr/0074-how-a-pipeline-learns.md]
mdindex: [type=0fc814, tags=0fb0b4, summary=b24880, related=e4688f]
---
# 0076: The learning store and its keys

Status: accepted (2026-11-27). Decided by Tomas on 2026-11-27, in the docs
cleanup. Supersedes [ADR 0014](archived/0014-learning-store.md),
[ADR 0021](archived/0021-inputs-and-how-the-store-knows-them.md),
[ADR 0024](archived/0024-store-keys-follow-what-a-step-reads.md) and
[ADR 0056](archived/0056-settings-that-only-choose-the-output-stay-out-of-the-learn-key.md).

## Context

The rule of the learning store was spread over four records. ADR 0014 put
every learning result into a store kept while the program runs, keyed by the
data, the fold and the steps up to that step. ADR 0021 extended the data part
of the key from files and tables to every input DuckDB reads, and said how the
store recognises each. ADR 0024 replaced 0014's steps part: a key holds only
the steps whose output a step reads. ADR 0056 narrowed 0024: settings that
only choose a step's output stay out of the key of what it learns. Two records
that stay current touch the key too: ADR 0029 adds a relation's connection,
and ADR 0040 changes the shape of the fold part.

## Decision

- **Every learning result goes into a store that lasts while the program
  runs.** An entry holds a step's learned values and its `apply` SQL
  (ADR 0014).
- **An entry's key has three parts:** the data, the fold, and the steps
  (ADR 0014, with 0021 and 0024 applied below). Before learning, sqlearn looks
  in the store, and an entry is reused only when all three match (ADR 0014).
- **The data part.** `learn`, `train` and a search accept anything DuckDB
  reads: files (Parquet, CSV, JSON, globs such as `data/*.csv`), DuckDB tables
  and relations, and pandas, Polars and Arrow tables in memory. DuckDB reads
  the in-memory ones itself (ADR 0021). The store recognises each kind as
  cheaply as is safe (ADR 0021):

  | input | recognised by |
  |---|---|
  | file | path, size, modification time |
  | DuckDB table | connection, name, row count |
  | DuckDB relation | its connection and SQL text (ADR 0029) |
  | Polars, Arrow | the object itself (they are immutable) |
  | pandas, numpy | a fingerprint of the values and their row order |

- **The fingerprint** is a hash computed by DuckDB, once per call to `learn`,
  `train` or a search, never once per fold. It covers row order because folds
  are tied to rows. DuckDB's hash of a row skips the column names, so the key
  of a frame, a table or a relation also holds its column names and types, in
  order (ADR 0021).
- **The store never keeps the user's data alive**, and nothing watches the
  data in the background: the key is compared only when a call is made
  (ADR 0021). A relation of another connection is refused, as
  [ADR 0029](0029-relations-from-another-connection-are-refused.md) states.
- **The fold part** is the fold, when folds are used: a fixed, seeded
  numbering of the rows (ADR 0014), keyed by the fold scheme's settings and
  the fold's number, `(scheme key, k)`
  ([ADR 0040](0040-fold-schemes-as-sql-over-rows.md), replacing 0014's
  `(n, seed, k)`).
- **The steps part** holds the step's own settings and the settings of the
  steps whose output it reads, followed back through the graph of columns:
  only those steps, not every step above it (ADR 0024, superseding 0014's
  "steps up to and including that step"). Within it (ADR 0024):
  - a step that changes rows (a filter, sampling, deduplication) changes what
    every later step sees, so every later step depends on it;
  - a step whose inputs are not known depends on everything before it, as
    [ADR 0018](archived/0018-runs-follow-the-chains-between-steps.md), now
    [ADR 0074](0074-how-a-pipeline-learns.md), has it;
  - a column an earlier dynamic step takes away decides what a later selector
    matches, so a step whose selector could have matched it (by name, by
    kind, or every column) depends on that step and on what that step depends
    on;
  - the key also holds the columns the step's selector resolved to on the
    data reaching it, so a step reading other columns never finds another's
    entry.
- **Settings that only choose the output stay out of the learn key.** A step
  may declare settings that change only which output it gives from what it
  learned, never what it learns. They stay out of the key of what it learns,
  so the values learned for one such setting are found in the store for
  another. What it outputs still follows every setting: the output, and every
  later step that reads it, are keyed and built with all of them (ADR 0056).
  The feature selectors declare theirs: `k` for `sq.select.best`,
  `percentile` for `sq.select.percentile`, `threshold` for
  `sq.select.variance`; `score` changes what is learned and stays in the key
  (ADR 0056).
- **What this gives** (ADR 0014, 0024):
  - changing a step's setting relearns that step and the steps that read from
    it, and nothing else;
  - changing only the model reuses all the preparation;
  - changing the data matches nothing, so everything that read it is learned
    again; an edited pandas frame relearns everything that read it
    (ADR 0021);
  - after a restart the store is empty and everything is learned again, as in
    scikit-learn.
- **The pipeline the user holds points to its entries**, so `learn` on
  training data then `apply` on test data behaves as expected, and learned
  values are readable as attributes ending in `_`
  ([ADR 0003](0003-scikit-learn-style-api.md)). Learning the pipeline again on
  other data points it at other entries; nothing is overwritten (ADR 0014).
- **A grid search loops fold first:** for each fold it prepares the data once,
  hands it to every model and setting, and drops it before the next fold, so
  the data is transformed once per fold, not once per training, and only one
  fold's data is in memory at a time. Methods that pick settings one at a time
  (Optuna, `sq.search.optuna`) loop setting first; keeping each fold's
  prepared data for them is a later idea
  ([issue #25](https://github.com/glaucis/sqlearn/issues/25)) (ADR 0024,
  names from [ADR 0039](0039-the-search-names-as-groups.md)).
- **The mechanics are the C++'s.** The old Python implemented the store, the
  input recognition and the fingerprint in Python (`_store.py`, `_inputs.py`,
  now under `old_python/src/sqlearn/`), holding an immutable table through a
  weak reference and falling back to the fingerprint where one was not
  possible (ADR 0021). The C++ group's design decides the mechanics
  ([ADR 0070](0070-sqlearn-is-rewritten-in-cpp.md)).

## Consequences

- Cross-validation and a search learn each fold's preparation once, however
  many trials or models follow (ADR 0014); a search over a setting that only
  chooses the output learns each fold once, and preparing each setting's data
  for the model still happens per setting, as for any step (ADR 0056).
- In a notebook, re-running a cell learns only what changed (ADR 0021).
- The store holds keys, learned values and SQL text, never data: kilobytes
  per step. A size limit, removal of old entries and a `sq.store.clear()` wait
  until measurement asks for them
  ([issue #23](https://github.com/glaucis/sqlearn/issues/23)) (ADR 0014,
  0021).
- Folds must be a stored, seeded numbering, never recomputed with `RANDOM()`,
  or keys would not match from query to query (ADR 0014).
- A step that declares a setting wrongly (one that does change what it
  learns) would reuse values it should not: the declaration is tested for
  each step that makes one (ADR 0056).
- Tests assert, for a search, how many times each step learns and how many
  times the data is transformed (ADR 0024).
- ADRs 0014, 0021, 0024 and 0056 are archived in `archived/` and keep their
  numbers.
