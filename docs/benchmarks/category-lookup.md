---
type: note
tags: [benchmarks, performance, encoders, ordinal, target, sqlearn]
summary: "Times the ways a step can look a category up in one DuckDB expression, at 100, 1,000 and 10,000 categories on 1,000,000 rows, and the ordinal and target encoders with lookup=\"list\" and lookup=\"hash\" from Parquet up to 100,000 categories."
related: [docs/benchmarks/index.md, docs/benchmarks/onehot-second-run.md]
---
# Looking a category up

[Issue #31](https://github.com/glaucis/sqlearn/issues/31) asks for a lookup of
a value among the learned categories that does not grow with the number of
categories. The ordinal and target encoders use
`list_position(<learned categories>, x)`, which compares the value with the
categories one by one. A step writes one DuckDB expression per output column,
and the learned categories go into it as constants; a join is outside that
contract. This page states what each form inside it costs. It recommends
nothing: the decision is Tomas's. He chose (#31) to keep `list_position` as
the default and offer the MD5 perfect hash as `lookup="hash"`, with a warning
above a threshold set from the encoders' times below.

## What was measured

- **Data:** generated from a fixed seed (`SEED = 0`): one text column of
  1,000,000 rows, a hundredth NULL, a hundredth a value not among the
  categories, the rest drawn uniformly from 100, 1,000 or 10,000 categories
  (`c00000`, `c00001`, ...), and a binary target for the target encoder.
- **Forms:** each gives a value's position among the categories from 0, NULL
  when it is not found. The step's own handling of NULL and of an unseen value
  wraps the form and is left out.
  - `list_position(<list>, x) - 1`, today's form;
  - `map_extract_value(MAP {category: position, ...}, x)`, and the same MAP
    read as `MAP {...}[x]`;
  - a `CASE` chain, one `WHEN x = category THEN position` per category;
  - `enum_code(TRY_CAST(x AS ENUM(<categories>)))`: DuckDB finds an ENUM's
    value by hashing, and an anonymous ENUM can be written inside the cast;
  - `json_extract` of the category from a JSON object of the positions;
  - an MD5 perfect hash: the categories' MD5s, computed in Python, give
    constant lists (a displacement per bucket, a position per slot) that send
    each category to a slot of its own, so a value costs one `md5_number`,
    three `list_extract`s and one comparison, whatever the count. A sorted
    list's binary search is not built into DuckDB and needs a loop, so it is
    not here. `x IN (<categories>)` gives no position, and DuckDB plans a long
    IN list as a hash join, so it is not here either.
- **Times:** wall clock of `SELECT sum(<form>)` over the table in memory, the
  median of five repetitions after one discarded run. A form whose median
  passes 5 s at one count is timed once, without the warm-up, at the next.
- **Same codes:** each form's codes are compared with `list_position`'s on the
  first 20,000 rows; "yes" is no difference, NULLs included.
- **Two costs that grow with the count:** reading one element of a constant
  INTEGER list of that many elements on 1,000,000 rows; and the ENUM cast
  failing, on 20,000 values none of which is a category, beside
  `list_position` on the same values (each timed once for the failing cast, as
  the median of five for the others).
- **The encoders as they are:** `sq.encode.ordinal("c")` and
  `sq.encode.target("c")` learned from scratch (the step store cleared before
  every repetition) from the data written as Parquet, then applied to the same
  file and written out as Parquet; the median of five repetitions after one
  discarded run.

The machine details come from `sysctl` and are macOS-only; on other systems
the script prints "unknown" for them.

Reproduce with `uv run python -m validation.benchmarks.category_lookup`. It
takes about seven minutes on this machine, most of them the JSON form.
`... category_lookup encoders 3000` times only the encoders, at the counts
given; one count per process keeps a large run from running short of memory.

## Environment

| | |
|---|---|
| CPU | Apple M3, 8 cores |
| RAM | 16 GiB |
| OS | macOS 26.6.1 (arm64) |
| Python | 3.12.13 |
| DuckDB | 2.0.0 |
| sqlearn | 0.1.dev233+g283aef7db |

## Results

The forms, 1,000,000 rows in memory:

| categories | form | s | same codes |
|---|---|---|---|
| 100 | list_position (today) | 0.013 | yes |
| 100 | map_extract_value(MAP {...}, x) | 0.020 | yes |
| 100 | MAP {...}[x] | 0.019 | yes |
| 100 | CASE chain | 0.058 | yes |
| 100 | TRY_CAST(x AS ENUM(...)) | 0.022 | yes |
| 100 | json_extract | 0.638 | yes |
| 100 | MD5 perfect hash | 0.322 | yes |
| 1,000 | list_position (today) | 0.143 | yes |
| 1,000 | map_extract_value(MAP {...}, x) | 0.166 | yes |
| 1,000 | MAP {...}[x] | 0.162 | yes |
| 1,000 | CASE chain | 0.359 | yes |
| 1,000 | TRY_CAST(x AS ENUM(...)) | 0.131 | yes |
| 1,000 | json_extract | 4.407 | yes |
| 1,000 | MD5 perfect hash | 0.394 | yes |
| 10,000 | list_position (today) | 1.280 | yes |
| 10,000 | map_extract_value(MAP {...}, x) | 1.431 | yes |
| 10,000 | MAP {...}[x] | 1.503 | yes |
| 10,000 | CASE chain | 3.017 | yes |
| 10,000 | TRY_CAST(x AS ENUM(...)) | 1.004 | yes |
| 10,000 | json_extract | 91.872 | yes |
| 10,000 | MD5 perfect hash | 0.742 | yes |

How each form grows from 100 to 10,000 categories (a hundred times as many):

| form | 100 s | 10,000 s | growth |
|---|---|---|---|
| list_position (today) | 0.013 | 1.280 | about 98x |
| map_extract_value(MAP {...}, x) | 0.020 | 1.431 | about 72x |
| MAP {...}[x] | 0.019 | 1.503 | about 79x |
| CASE chain | 0.058 | 3.017 | about 52x |
| TRY_CAST(x AS ENUM(...)) | 0.022 | 1.004 | about 46x |
| json_extract | 0.638 | 91.872 (one run) | about 144x |
| MD5 perfect hash | 0.322 | 0.742 | about 2.3x |

The two costs that grow with the count:

| categories | read a constant list, 1,000,000 rows | failing ENUM cast, 20,000 rows | list_position, the same 20,000 rows |
|---|---|---|---|
| 100 | 0.002 | 0.122 | 0.004 |
| 1,000 | 0.008 | 0.890 | 0.027 |
| 10,000 | 0.070 | 9.639 | 0.207 |

The encoders as they are, from Parquet (seconds):

| categories | encoder | learn s | apply s | list_position alone, from Parquet s |
|---|---|---|---|---|
| 100 | ordinal | 0.068 | 0.177 | 0.003 |
| 100 | target | 5.081 | 0.683 | 0.003 |
| 1,000 | ordinal | 0.092 | 0.220 | 0.020 |
| 1,000 | target | 8.093 | 0.823 | 0.020 |
| 10,000 | ordinal | 0.127 | 0.460 | 0.306 |
| 10,000 | target | 46.771 | 1.609 | 0.306 |

The last column comes from a second run of the script, which added it; the
machine ran short of memory and that run was stopped before its last row
(target at 10,000). The rest of the page is the first, complete run. Where the
two runs overlap they differ by up to a quarter (at 10,000 categories,
`list_position` 1.170 s against 1.280 s, the failing ENUM cast 10.319 s
against 9.639 s, ordinal's apply 0.617 s against 0.460 s).

The target encoder's learning after
[issue #41](https://github.com/glaucis/sqlearn/issues/41), beside the times
above: the learn stage reads the staged statistics list once, beside the one
row of its scan, where before every source row carried it through a cross
join. Measured with the encoders' part of the script alone, one category
count per process, on sqlearn 0.1.dev253+gd1ccdb53c; the machine was busier
than for the first run (ordinal's learn took 0.154, 0.164 and 0.269 s, its
apply 0.427, 0.394 and 0.895 s).

| categories | target learn s, before | target learn s, after #41 | target apply s, after #41 |
|---|---|---|---|
| 100 | 5.081 | 2.375 | 1.423 |
| 1,000 | 8.093 | 3.753 | 1.632 |
| 10,000 | 46.771 | 4.001 | 1.690 |

## The encoders with `lookup="hash"`

Measured with the encoders' part alone, one count per process, from Parquet,
1,000,000 rows, each encoder with `lookup="list"` and `lookup="hash"`; beside
them each lookup alone, summed over the same Parquet file. sqlearn
0.1.dev288+g47e29b323, DuckDB 2.0.0. The machine was shared with other work:
its load average was between 10 and 17 for the first three counts and 41 at
the end of the last, so the times are rough and the 30,000 rows the roughest.

| categories | encoder | learn s | apply s | list_position alone, from Parquet s | MD5 perfect hash alone, from Parquet s |
|---|---|---|---|---|---|
| 1,000 | ordinal | 0.305 | 0.943 | 0.092 | 0.557 |
| 1,000 | ordinal, hash | 1.027 | 2.246 | 0.092 | 0.557 |
| 1,000 | target | 2.153 | 1.076 | 0.092 | 0.557 |
| 1,000 | target, hash | 4.281 | 3.646 | 0.092 | 0.557 |
| 3,000 | ordinal | 0.208 | 0.489 | 0.083 | 0.587 |
| 3,000 | ordinal, hash | 1.613 | 3.443 | 0.083 | 0.587 |
| 3,000 | target | 3.444 | 2.118 | 0.083 | 0.587 |
| 3,000 | target, hash | 3.451 | 2.702 | 0.083 | 0.587 |
| 10,000 | ordinal | 0.425 | 1.604 | 0.445 | 0.734 |
| 10,000 | ordinal, hash | 1.657 | 3.203 | 0.445 | 0.734 |
| 10,000 | target | 6.004 | 2.958 | 0.445 | 0.734 |
| 10,000 | target, hash | 6.181 | 3.775 | 0.445 | 0.734 |
| 30,000 | ordinal | 0.794 | 14.264 | 6.268 | 1.919 |
| 30,000 | ordinal, hash | 3.494 | 5.228 | 6.268 | 1.919 |
| 30,000 | target | 13.345 | 12.620 | 6.268 | 1.919 |
| 30,000 | target, hash | 28.942 | 20.325 | 6.268 | 1.919 |

Read from Parquet, `list_position` alone costs far less than over the table
in memory (0.445 s against 1.280 s at 10,000 categories), so the crossing
point lies higher than the in-memory table suggests: the lookups alone cross
between 10,000 and 30,000 categories, and so does the ordinal encoder's
apply (1.604 s against 3.203 s at 10,000, 14.264 s against 5.228 s at
30,000). The target encoder's apply was slower with the hash at every count,
30,000 included. These times were taken under heavy load and were measured
again on a quieter machine (below), which moved the threshold.

## The encoders measured again, quieter

Measured on 2026-11-12 as above (encoders' part alone, one count per process,
from Parquet, 1,000,000 rows), sqlearn 0.1.dev350+g34c08d242, DuckDB 2.0.0,
on an Apple M3, 8 cores, 16 GB. The machine still ran other work: a first run
of 10,000 to 100,000 categories saw a load average between 8 and 34, so
15,000, 20,000 and 30,000 were measured again, with 50,000, at a load
between 4 and 8. The table holds the second run's rows, and the first run's
for 10,000 and 100,000 (load between 8 and 12).

| categories | encoder | learn s | apply s | list_position alone, from Parquet s | MD5 perfect hash alone, from Parquet s |
|---|---|---|---|---|---|
| 10,000 | ordinal | 0.285 | 0.937 | 0.374 | 0.787 |
| 10,000 | ordinal, hash | 1.615 | 2.539 | 0.374 | 0.787 |
| 10,000 | target | 2.498 | 1.099 | 0.374 | 0.787 |
| 10,000 | target, hash | 4.044 | 1.888 | 0.374 | 0.787 |
| 15,000 | ordinal | 0.154 | 0.620 | 0.339 | 0.398 |
| 15,000 | ordinal, hash | 0.818 | 1.464 | 0.339 | 0.398 |
| 15,000 | target | 3.483 | 1.524 | 0.339 | 0.398 |
| 15,000 | target, hash | 4.085 | 2.340 | 0.339 | 0.398 |
| 20,000 | ordinal | 0.229 | 2.370 | 2.094 | 0.599 |
| 20,000 | ordinal, hash | 1.077 | 1.923 | 2.094 | 0.599 |
| 20,000 | target | 4.638 | 3.497 | 2.094 | 0.599 |
| 20,000 | target, hash | 5.290 | 2.897 | 2.094 | 0.599 |
| 30,000 | ordinal | 0.284 | 3.393 | 2.796 | 0.724 |
| 30,000 | ordinal, hash | 1.416 | 2.502 | 2.796 | 0.724 |
| 30,000 | target | 6.559 | 4.922 | 2.796 | 0.724 |
| 30,000 | target, hash | 7.357 | 3.867 | 2.796 | 0.724 |
| 50,000 | ordinal | 0.412 | 5.456 | 4.994 | 1.095 |
| 50,000 | ordinal, hash | 2.129 | 3.535 | 4.994 | 1.095 |
| 50,000 | target | 10.250 | 8.245 | 4.994 | 1.095 |
| 50,000 | target, hash | 11.237 | 5.764 | 4.994 | 1.095 |
| 100,000 | ordinal | 1.110 | 15.403 | 22.239 | 1.932 |
| 100,000 | ordinal, hash | 3.991 | 6.779 | 22.239 | 1.932 |
| 100,000 | target | 21.497 | 24.722 | 22.239 | 1.932 |
| 100,000 | target, hash | 20.315 | 10.478 | 22.239 | 1.932 |

`list_position` alone steps up sixfold between 15,000 and 20,000 categories
(0.339 s to 2.094 s; 0.317 s to 1.583 s in the first run), and from there both
encoders apply faster with the hash: the ordinal encoder 1.923 s against
2.370 s, the target encoder 2.897 s against 3.497 s. At 15,000 the list is
faster for both. The two runs agree on that at 15,000 and 20,000. The first
run's 30,000 for the target encoder (6.446 s with the list, 12.563 s with the
hash) was taken at the busiest moment and is not repeated here: on the
quieter machine the hash won (3.867 s against 4.922 s). Learning with the
hash costs more at every count except the target encoder's 100,000.

`sq.encode`'s warning threshold, `WARN_ABOVE`, is 20,000 for both encoders:
the smallest count measured at which the hash applied faster. The crossing
lies between 15,000 and 20,000.

Most of the target encoder's learn above was Python: at 30,000 categories its
`derive` made every row's sums exact again for each of the six encodings
("all" and the five inner folds), about 6 million `Fraction`s. It now makes
each exact once and takes a fold's complement as the whole less the fold,
which gives the same encodings to the bit. Measured again at 30,000
categories (load average about 8): learn 3.582 s with the list and 4.839 s
with the hash, against 6.559 s and 7.357 s above.

The hash costs more in an encoder than alone for two reasons, both found
while measuring:

- **DuckDB shares no repeated subexpression inside a `CASE`.** The form in the
  tables above writes the MD5 out wherever it is used, which an encoder's NULL
  handling (and the target encoder's folds) then wraps in a `CASE`. Inside a
  `CASE`, at 1,000 categories from Parquet, that form took 1.834 s against
  0.679 s outside one. `lookup="hash"` binds the MD5 and the slot once each,
  with `list_transform([value], lambda ...)[1]`: 0.284 s inside a `CASE`,
  0.324 s outside (one run each, same codes as `list_position` on every row).
  The column "MD5 perfect hash alone" above is that bound form; "MD5 perfect
  hash" in the earlier tables is the form written out.
- **A fixed cost per query.** The hash's SQL holds about 3.5 constants per
  category (the categories, a slot table of a prime above twice their count,
  and a displacement per two categories) against one for `list_position`.
  DuckDB parses, binds and plans it on each query a learn or an apply
  prepares: on 2,000 rows at 10,000 categories, an apply took between 1.2 and
  2.4 s with the hash against 0.4 to 0.6 s with the list (a few runs, under
  load). That cost does not grow with the rows, so the more rows, the sooner
  the hash pays.

The hash compares the bytes exactly. A collated column (`VARCHAR COLLATE
NOCASE`) is matched by its collation by `list_position` and by its bytes by
the hash. DuckDB does not report the collation to a step: the relation's type
is plain `VARCHAR`, `duckdb_columns()` shows `VARCHAR` with no collation, and
only the table's `CREATE` text in `duckdb_tables()` names it, which a step
reading any relation cannot reach. So `lookup="hash"` is not refused on a
collated column; the encoders' documentation says it ignores the collation.

## What the numbers show

Every form gives today's codes on the rows compared.

At 10,000 categories on 1,000,000 rows, `list_position` takes 1.280 s; the
MD5 perfect hash 0.742 s, the ENUM cast 1.004 s, the two MAP forms 1.431 s and
1.503 s, the `CASE` chain 3.017 s and `json_extract` 91.872 s (one run).

With a hundred times as many categories, `list_position` takes about 98 times as
long, in step with the count, and the MD5 perfect hash about 2.3 times as long,
far less than the count, which makes the hash the fastest form at 10,000
categories; the other forms take between 46 and 144 times as long. None takes
the same time at every count:

- A constant list costs time in proportion to its length on every batch of
  rows, wherever it is used: reading one element of a 10,000-element list on
  1,000,000 rows takes 0.070 s, of a 100-element one 0.002 s. The MD5 perfect
  hash holds three such lists; its time goes from 0.322 s at 100 categories to
  0.742 s at 10,000. At 100 and 1,000 categories it is slower than
  `list_position` (0.322 s against 0.013 s, 0.394 s against 0.143 s).
- The ENUM cast finds a category without a scan, but a value that is not one
  makes the cast fail, and a failure costs time in proportion to the count:
  20,000 such values take 9.639 s at 10,000 categories, against 0.207 s for
  `list_position` on the same values. With a hundredth of the rows unseen it
  takes 1.004 s at 10,000 categories.
- The MAP lookups take as long as `list_position` or longer, at every count.

Read from Parquet, the same `list_position` lookup takes 0.306 s at 10,000
categories (from the second run), against 1.280 s over the table in memory (the
first run).

The ordinal encoder's apply, Parquet in and out, takes 0.177 s at 100
categories and 0.460 s at 10,000. The target encoder's learning took 5.081 s
at 100 categories and 46.771 s at 10,000; it contains no lookup. Its apply
takes 0.683 s and 1.609 s. Most of that learning was the statistics list
carried on every row; since #41 it takes 2.375 s at 100 categories and
4.001 s at 10,000. What remains is the `GROUP BY` of the statistics and the
Python `Fraction` arithmetic over them (about 5 s under the profiler at
200,000 rows in #41's report), which #41 leaves as it was.
