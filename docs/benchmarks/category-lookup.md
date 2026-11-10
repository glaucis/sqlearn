---
type: note
tags: [benchmarks, performance, encoders, ordinal, target, sqlearn]
summary: "Times the ways a step can look a category up in one DuckDB expression, at 100, 1,000 and 10,000 categories on 1,000,000 rows, and the ordinal and target encoders as they are."
related: [index, onehot-second-run]
---
# Looking a category up

[Issue #31](https://github.com/glaucis/sqlearn/issues/31) asks for a lookup of
a value among the learned categories that does not grow with the number of
categories. The ordinal and target encoders use
`list_position(<learned categories>, x)`, which compares the value with the
categories one by one. A step writes one DuckDB expression per output column,
and the learned categories go into it as constants; a join is outside that
contract. This page states what each form inside it costs. It recommends
nothing: the decision is Tomas's.

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
