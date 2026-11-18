---
type: plan
tags: [datasets, generators, threads, parallelism, duckdb, attach]
summary: "Builds #46: the sq.datasets generators read row numbers from work tickets in an attached in-memory database, meta_sqlearn, so they use every thread, with parallel=False giving today's SQL."
related: [docs/specs/datasets-many-threads.md, docs/adr/0045-datasets-are-relations-built-in-sql.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# Generators on many threads: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** `blobs`, `regression`, `classification` and `customers` use every
thread DuckDB is allowed, with the same rows in the same order, and
`parallel=False` gives today's SQL.

**Architecture:** A new private module `src/sqlearn/datasets/_tickets.py` owns
`meta_sqlearn` and writes the SQL that turns work tickets into row numbers.
`random_columns` takes that SQL as an optional row source; without it, it stays
as it is. Each generator gains `parallel=True` and passes the source on.

**Tech Stack:** Python 3.12+, DuckDB 2.0, pytest, numpy (tests), uv, just.

**Spec:** `docs/specs/datasets-many-threads.md`. Read it first: §2 holds the
measurements behind each rule here.

## Global Constraints

- Computation is SQL run by DuckDB; Python is the glue (ADR 0002). `duckdb` is
  the only runtime dependency (ADR 0005).
- Same rows bit for bit on one machine; row-number order while
  `preserve_insertion_order` is on; no data row computed on creating a relation,
  up to `rows=2**63 - 1`.
- Never write to the user's database, join their transaction, or change their
  DuckDB settings (`threads`, `temp_directory`, `preserve_insertion_order`).
- Every write to `meta_sqlearn` goes through a `cursor()`, closed afterwards.
- A ticket table is never changed, replaced or dropped.
- Warnings and refusals use the house form with `Why:` and `Fix:` (ADR 0046).
- British English in prose, American spelling in identifiers (ADR 0010).
- Commits: no AI attribution, no trailer; commitlint takes no scope but `hooks`,
  `site`, `deps`, and a header of at most 72 characters.
- **The laptop is short of memory:** keep probes and tests small; no test here
  needs more than about 4M rows.
- Before each commit: `just fmt`, `just check`, `just test`, naming every
  failure. Leave out of commits any frontmatter edits the docs tagger made to
  files you did not touch (`docs/guide/index.md`, `docs/reference/index.md` are
  such files now).

## Review Focus

Each has its test in the task named.

1. Generators on two connections in turn: each gets its own `meta_sqlearn`, and
   a relation stays on its connection (Task 4).
2. A user table named `tickets_8` in their own database, and their current
   database or schema: tickets are always read by full name (Task 3).
3. A cursor configured as sqlearn's connection (Task 3).
4. A relation made before the thread count rose still gives its rows (Task 4).
5. A generated relation passing through `sq.Pipeline`, which registers it as a
   view on the connection (Task 2).

## Before Task 1

- [ ] Create the branch `datasets-many-threads` from `main` (in a worktree if
  executing with subagents), and mark #46 in progress with the github-pm skill.
- [ ] Commit the spec and this plan:

```bash
git add docs/specs/datasets-many-threads.md docs/plans/2026-11-18-datasets-many-threads.md
git commit -m "docs: spec and plan for generators on many threads (#46)"
```

---

### Task 1: Row numbers from tickets

**Files:**
- Create: `src/sqlearn/datasets/_tickets.py`
- Modify: `src/sqlearn/datasets/_random.py:198-252`
- Test: `tests/src/sqlearn/datasets/test__tickets.py`,
  `tests/src/sqlearn/datasets/test__random.py`

**Interfaces:**
- Produces, in `_tickets.py`: constants `DATABASE = "meta_sqlearn"`,
  `ROW_GROUP = 122_880`, `MIN_GROUPS = 8`, `FAN_OUT = 4_096`;
  `ticket_rows(rows: int, table: str, tickets: int) -> str`, a query with one
  `BIGINT` column `range`; and the private
  <!-- markdownlint-disable-next-line MD013 -->
  `_row_numbers(rows: int, scan: str, size: int, each_list: Callable[[str], str] = str) -> str`,
  where `scan` is a query giving `a` and `w` (`HUGEINT`: a block's start and
  width) and `each_list` wraps every `range(...)` list before it is unnested.
- Produces, in `_random.py`:
  `random_columns(seed, rows, uniforms, normals, row_source: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("threads", [1, 2, 8])
@pytest.mark.parametrize(
    ("tickets", "rows"),
    [
        (983_040, n)
        for n in (1, 7, 122_879, 122_880, 122_881, 983_039, 983_040, 983_041, 3_000_001)
    ]
    + [(1, n) for n in (1, 4_096, 4_097, 16_777_216 // 8)]
    + [(8, n) for n in (8, 32_768, 32_769, 3_000_001)],
)
def test_work_tickets_number_every_row_once_in_order(threads, tickets, rows):
    con = duckdb.connect()
    con.execute(f"SET threads = {threads}")
    con.execute(f"CREATE TABLE t AS SELECT range AS ticket FROM range({tickets})")
    got = con.sql(ticket_rows(rows, "t", tickets)).fetchnumpy()["range"]
    assert got.tolist() == list(range(rows))


def test_the_largest_row_count_starts_at_zero():
    # table t as above, 983_040 tickets
    sql = ticket_rows(2**63 - 1, "t", 983_040)
    assert con.sql(f"{sql} LIMIT 3").fetchall() == [(0,), (1,), (2,)]


def test_the_largest_row_count_ends_on_its_last_row():
    rows, tickets = 2**63 - 1, 983_040
    size = -(-rows // tickets)
    scan = f"SELECT {tickets - 1}::HUGEINT * {size} AS a, {size}::HUGEINT AS w"
    sql = _row_numbers(rows, scan, size, lambda s: f"list_reverse({s})")
    assert duckdb.connect().sql(f"{sql} LIMIT 2").fetchall() == [
        (rows - 1,),
        (rows - 2,),
    ]
```

In `test__random.py`:

```python
def test_a_row_source_gives_the_rows_of_range():
    con = connection()
    plain = random_columns(5, 1_000, {"u": 0}, {"n": 1})
    other = random_columns(
        5, 1_000, {"u": 0}, {"n": 1}, row_source="SELECT range FROM range(1000)"
    )
    assert con.sql(plain).fetchall() == con.sql(other).fetchall()


def test_without_a_row_source_the_sql_reads_range():
    assert "FROM range(10)" in random_columns(0, 10, {"u": 0}, {})
```

- [ ] **Step 2: Run them and see them fail**

Run:
`uv run pytest tests/src/sqlearn/datasets/test__tickets.py tests/src/sqlearn/datasets/test__random.py`
Expected: FAIL: `_tickets` cannot be imported; `row_source` is unexpected.

- [ ] **Step 3: Implement `ticket_rows`, `_row_numbers` and the `row_source`
  argument**

`ticket_rows`: `used = min(tickets, rows)`, `size = ceil(rows / used)`; `scan`
reads `ticket::HUGEINT * size AS a, size::HUGEINT AS w` from `table` `WHERE
ticket < used`. `_row_numbers` follows the sketch in spec §5: while `size >
FAN_OUT`, take `child = ceil(size / FAN_OUT)` and wrap `scan` in one `unnest` of
`each_list("range(a::BIGINT, least(a + w, rows)::BIGINT, child)")`; then one
last `unnest` of `each_list("range(a::BIGINT, least(a + w, rows)::BIGINT)")` as
`range`. Integer arithmetic only, never floats. In `random_columns`, read
`FROM ({row_source})` when given, and leave the default text unchanged. Add
numpy-style docstrings with doctests.

- [ ] **Step 4: Run them and see them pass**

Run: the command of Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sqlearn/datasets/_tickets.py src/sqlearn/datasets/_random.py tests/src/sqlearn/datasets/test__tickets.py tests/src/sqlearn/datasets/test__random.py
git commit -m "feat: number rows from work tickets (#46)"
```

---

### Task 2: The `parallel` setting

**Files:**
- Modify: `src/sqlearn/datasets/_tickets.py`,
  `src/sqlearn/datasets/generated.py` (the module docstring, `blobs:297`,
  `regression:382`, `classification:640`, `customers:810`)
- Test: `tests/src/sqlearn/datasets/test_generated.py`

**Interfaces:**
- Consumes: `ticket_rows`, `random_columns(..., row_source=)`.
- Produces: `row_source(rows: int, parallel: bool) -> str | None` in
  `_tickets.py`: `None` means plain `range`. Each generator gains
  `parallel: bool = True`, last, and calls
  `random_columns(..., row_source=row_source(rows, parallel))`.

- [ ] **Step 1: Write the failing tests**, one at a time, each run red, then
      given its code (Step 3). `GENERATORS` and `_refused` already exist in the
      file.

```python
@pytest.mark.parametrize("threads", [1, 2, 8])
@pytest.mark.parametrize("make", GENERATORS)
def test_every_generator_gives_the_same_rows_parallel_or_not(make, threads):
    connection().execute(f"SET threads = {threads}")
    assert make(rows=5_000, seed=3).fetchall() == (
        make(rows=5_000, seed=3, parallel=False).fetchall()
    )


@pytest.mark.parametrize(("parallel", "shared"), [(True, True), (False, False)])
def test_work_tickets_share_the_work_between_threads(parallel, shared):
    con = connection()
    con.execute("SET threads = 4")
    seen: set[int] = set()

    def note(x: float) -> float:
        seen.add(threading.get_ident())
        return x

    con.create_function("note", note, ["DOUBLE"], "DOUBLE", side_effects=True)
    rel = sq.datasets.blobs(rows=1_000_000, n_features=1, parallel=parallel)
    rel.aggregate("sum(note(x0))").fetchall()
    assert (len(seen) > 1) is shared


def test_parallel_false_needs_no_meta_sqlearn():
    rel = sq.datasets.blobs(rows=10, parallel=False)
    assert "meta_sqlearn" not in rel.sql_query()
    names = connection().sql("SELECT database_name FROM duckdb_databases()")
    assert ("meta_sqlearn",) not in names.fetchall()


def test_a_view_over_parallel_false_survives_reopening(tmp_path):
    path = tmp_path / "work.duckdb"
    con = duckdb.connect(path)
    sq.set_config(connection=con)
    sq.datasets.blobs(rows=10, parallel=False).create_view("kept")
    con.close()
    assert duckdb.connect(path).sql("SELECT count(*) FROM kept").fetchall() == [(10,)]


@pytest.mark.parametrize("make", GENERATORS)
def test_parallel_must_be_a_bool(make):
    assert "parallel" in _refused(make, parallel="yes")


def test_limit_and_ordered_keep_their_meaning():
    rel = sq.datasets.blobs(rows=10_000, seed=1)
    plain = sq.datasets.blobs(rows=10_000, seed=1, parallel=False)
    assert rel.limit(5).fetchall() == plain.limit(5).fetchall()
    assert sq.datasets.blobs(rows=10_000, seed=1, ordered=True).fetchall() == (
        sq.datasets.blobs(rows=10_000, seed=1, ordered=True, parallel=False).fetchall()
    )


def test_without_insertion_order_the_rows_are_the_same_set():
    con = connection()
    con.execute("SET preserve_insertion_order = false")
    got = sq.datasets.blobs(rows=10_000, seed=1).fetchall()
    assert sorted(got) == sorted(
        sq.datasets.blobs(rows=10_000, seed=1, parallel=False).fetchall()
    )


def test_a_pipeline_learned_from_tickets_saves_loads_and_applies(tmp_path):
    rel = sq.datasets.blobs(rows=1_000, seed=2)
    pipe = sq.Pipeline([sq.scale.standard()]).learn(rel)
    sq.save(pipe, tmp_path / "pipe.json")
    again = sq.load(tmp_path / "pipe.json")
    assert again.apply(rel).fetchall() == pipe.apply(rel).fetchall()


@pytest.mark.parametrize(("parallel", "folder"), [(True, True), (False, False)])
def test_an_ordered_export_under_a_memory_limit(tmp_path, parallel, folder):
    """Tickets may overflow to the temporary folder; ``range`` needs none."""
    con = duckdb.connect()
    sq.set_config(connection=con)
    rel = sq.datasets.blobs(rows=4_000_000, n_features=1, parallel=parallel)
    place = tmp_path / "spill" if folder else ""
    con.execute(f"SET threads = 4; SET temp_directory = '{place}'")
    con.execute("SET memory_limit = '60MB'")
    out = tmp_path / "out.parquet"
    con.execute(f"COPY ({rel.sql_query()}) TO '{out}' (FORMAT parquet)")
    assert con.sql(f"SELECT count(*) FROM '{out}'").fetchall() == [(4_000_000,)]
```

The existing `test_a_trillion_rows_are_created_at_once` now covers laziness for
tickets. Add beside it:

```python
def test_the_largest_row_count_is_created_at_once():
    rel = sq.datasets.blobs(rows=2**63 - 1, n_features=1)
    assert rel.limit(3).count("*").fetchall() == [(3,)]
```

Also `test_a_model_streams_from_a_generated_relation`: a `feed="stream"` model
trained on `sq.datasets.blobs(rows=2_000)`, written as the streaming tests of
`tests/src/sqlearn/test__feed.py`, asserting the model has been fitted.

- [ ] **Step 2: Run each and see it fail for the right reason**

Run: `uv run pytest tests/src/sqlearn/datasets/test_generated.py -k "<name>"`
Expected: FAIL: `parallel` is an unexpected argument, or one thread seen.

- [ ] **Step 3: Implement**

`row_source(rows, parallel)`: `None` when not `parallel`. Otherwise, on
`connection()`, `ATTACH IF NOT EXISTS ':memory:' AS meta_sqlearn` and `CREATE
TABLE IF NOT EXISTS meta_sqlearn.tickets_8` of `8 * ROW_GROUP` tickets, then
`ticket_rows(rows, "meta_sqlearn.tickets_8", 8 * ROW_GROUP)`. Task 3 and Task 4
make this safe and sized. In `generated.py`, add `_check_parallel(function,
parallel)` in the form of `_check_ordered`, the `parallel` parameter and its
docstring to all four generators (what it does, the two reasons for `False` from
spec §5), and correct the module docstring's "over ``range(rows)``: creating it
reads and writes nothing".

- [ ] **Step 4: Run the datasets tests and the whole suite**

Run: `uv run pytest tests/src/sqlearn/datasets` then `just test`
Expected: PASS. In `test__random.py` and `test_generated.py`, correct any
docstring saying `range()` makes the thread test unable to fail.

- [ ] **Step 5: Commit**

```bash
git add src/sqlearn/datasets tests/src/sqlearn/datasets
git commit -m "feat: generators run on every thread by default (#46)"
```

---

### Task 3: Leave the user's database alone

**Files:**
- Modify: `src/sqlearn/datasets/_tickets.py`
- Test: `tests/src/sqlearn/datasets/test__tickets.py`

**Interfaces:**
- Consumes: `row_source`. Its signature does not change.

- [ ] **Step 1: Write the failing tests**, one at a time.

```python
def _on_file(path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS mine (a INT)")
    sq.set_config(connection=con)
    return con


def test_a_database_file_is_left_as_it_was(tmp_path):
    path = tmp_path / "work.duckdb"
    con = _on_file(path)
    con.execute("CHECKPOINT")
    size = path.stat().st_size
    sq.datasets.blobs(rows=100).fetchall()
    con.execute("CHECKPOINT")
    assert path.stat().st_size == size
    con.close()
    tables = duckdb.connect(path).sql("SELECT table_name FROM duckdb_tables()")
    assert tables.fetchall() == [("mine",)]


def test_generators_work_on_a_read_only_database(tmp_path):
    path = tmp_path / "work.duckdb"
    _on_file(path).close()
    sq.set_config(connection=duckdb.connect(path, read_only=True))
    assert sq.datasets.blobs(rows=100).fetchall() == (
        sq.datasets.blobs(rows=100, parallel=False).fetchall()
    )


@pytest.mark.parametrize("wrote_first", [False, True])
@pytest.mark.parametrize(("end", "kept"), [("COMMIT", True), ("ROLLBACK", False)])
def test_an_open_transaction_is_left_alone(tmp_path, wrote_first, end, kept):
    con = _on_file(tmp_path / "work.duckdb")
    con.execute("BEGIN")
    if wrote_first:
        con.execute("INSERT INTO mine VALUES (1)")
    assert sq.datasets.blobs(rows=100).count("*").fetchall() == [(100,)]
    con.execute("INSERT INTO mine VALUES (2)")
    con.execute(end)
    count = con.sql("SELECT count(*) FROM mine").fetchall()[0][0]
    assert count == ((1 + wrote_first) if kept else 0)
    assert sq.datasets.blobs(rows=100).count("*").fetchall() == [(100,)]


def test_a_users_own_tickets_table_is_not_read(tmp_path):
    con = _on_file(tmp_path / "work.duckdb")
    con.execute("CREATE TABLE tickets_8 AS SELECT 'no' AS ticket")
    con.execute("CREATE SCHEMA other; USE work.other")
    assert sq.datasets.blobs(rows=100).fetchall() == (
        sq.datasets.blobs(rows=100, parallel=False).fetchall()
    )


def test_a_cursor_may_be_sqlearns_connection():
    sq.set_config(connection=duckdb.connect().cursor())
    assert sq.datasets.blobs(rows=100).count("*").fetchall() == [(100,)]
```

- [ ] **Step 2: Run each and see it fail**

Run: `uv run pytest tests/src/sqlearn/datasets/test__tickets.py -k "<name>"`
Expected: the read-only test fails with `Cannot launch in-memory database in
read-only mode`; the transaction tests with `a single transaction can only write
to a single attached database`, or a table lost on `ROLLBACK`.

- [ ] **Step 3: Implement**

In `row_source`, do the `ATTACH ... (READ_WRITE)` and `CREATE TABLE` on
`con.cursor()`, closing it in a `finally`. Write every name fully qualified.

- [ ] **Step 4: Run the tests of this file and of `test_generated.py`**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sqlearn/datasets/_tickets.py tests/src/sqlearn/datasets/test__tickets.py
git commit -m "fix: tickets never touch the user's database (#46)"
```

---

### Task 4: One ticket table per size

**Files:**
- Modify: `src/sqlearn/datasets/_tickets.py`
- Test: `tests/src/sqlearn/datasets/test__tickets.py`

**Interfaces:**
- Produces: tables `meta_sqlearn.tickets_<groups>`, one `BIGINT` column
  `ticket`, `0` to `groups * ROW_GROUP - 1`;
  `_visible_tables(con) -> dict[int, str]` (groups to full name, as `con` itself
  sees them).

- [ ] **Step 1: Write the failing tests**, one at a time.

```python
def _ticket_tables(con) -> list[str]:
    return sorted(
        r[0]
        for r in con.sql(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE database_name = 'meta_sqlearn'"
        ).fetchall()
    )


def test_more_threads_add_a_larger_ticket_table():
    con = connection()
    con.execute("SET threads = 2")
    sq.datasets.blobs(rows=10).fetchall()
    assert _ticket_tables(con) == ["tickets_8"]
    con.execute("SET threads = 9")
    sq.datasets.blobs(rows=10).fetchall()
    assert _ticket_tables(con) == ["tickets_8", "tickets_9"]
    count = con.sql("SELECT count(*) FROM meta_sqlearn.tickets_9").fetchall()
    assert count == [(9 * ROW_GROUP,)]


def test_a_relation_keeps_its_rows_when_threads_rise():
    con = connection()
    con.execute("SET threads = 2")
    rel = sq.datasets.blobs(rows=1_000, seed=4)
    before = rel.fetchall()
    con.execute("SET threads = 9")
    sq.datasets.blobs(rows=10).fetchall()
    assert rel.fetchall() == before


def test_a_transaction_that_cannot_see_a_new_table_still_gets_every_row(tmp_path):
    con = duckdb.connect(tmp_path / "work.duckdb")
    sq.set_config(connection=con)
    con.execute("SET threads = 2")
    sq.datasets.blobs(rows=10).fetchall()
    con.execute("BEGIN")
    con.sql("SELECT count(*) FROM meta_sqlearn.tickets_8").fetchall()
    con.execute("SET threads = 9")
    rel = sq.datasets.blobs(rows=1_000_000, n_features=1, seed=5)
    plain = sq.datasets.blobs(rows=1_000_000, n_features=1, seed=5, parallel=False)
    assert rel.fetchall() == plain.fetchall()
    con.execute("ROLLBACK")


def test_two_python_threads_may_generate_at_once():
    con = duckdb.connect()
    sq.set_config(connection=con)
    start, results, errors = threading.Barrier(8), [], []

    def work():
        try:
            start.wait()
            results.append(sq.datasets.blobs(rows=1_000, seed=1).fetchall())
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and all(r == results[0] for r in results)


def test_each_connection_has_its_own_meta_sqlearn():
    first, second = duckdb.connect(), duckdb.connect()
    sq.set_config(connection=first)
    rel = sq.datasets.blobs(rows=10, seed=1)
    sq.set_config(connection=second)
    other = sq.datasets.blobs(rows=10, seed=1)
    assert rel.fetchall() == other.fetchall()
```

- [ ] **Step 2: Run each and see it fail**

Expected: `tickets_9` is missing; the two-Python-threads test may fail with a
catalog write conflict. A test already green is noted in the task report.

- [ ] **Step 3: Implement**

Under one module-level `threading.Lock`: read `current_setting('threads')`,
`wanted = max(MIN_GROUPS, threads)`, and through the cursor create
`tickets_<wanted>` unless a table at least that large exists. Outside the lock,
`_visible_tables(con)`, on the user's connection, and use the largest. Pass that
table's ticket count to `ticket_rows`. Never `CREATE OR REPLACE`, never `DROP`.

- [ ] **Step 4: Run the datasets tests**

Run: `uv run pytest tests/src/sqlearn/datasets`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sqlearn/datasets/_tickets.py tests/src/sqlearn/datasets/test__tickets.py
git commit -m "feat: size work tickets to the thread count (#46)"
```

---

### Task 5: When `meta_sqlearn` cannot be used

**Files:**
- Modify: `src/sqlearn/datasets/_tickets.py`
- Test: `tests/src/sqlearn/datasets/test__tickets.py`

**Interfaces:**
- Consumes: `_visible_tables`. `row_source` now returns `None` and warns when
  tickets cannot be used.

- [ ] **Step 1: Write the failing tests**, one at a time.

```python
def _falls_back() -> None:
    with pytest.warns(SqlearnWarning) as caught:
        rel = sq.datasets.blobs(rows=100, seed=1)
    text = str(caught[0].message)
    assert all(w in text for w in ("meta_sqlearn", "Why:", "Fix:", "parallel=False"))
    assert "meta_sqlearn" not in rel.sql_query()
    assert (
        rel.fetchall() == sq.datasets.blobs(rows=100, seed=1, parallel=False).fetchall()
    )


@pytest.mark.parametrize(
    "table",
    [
        "SELECT 1 AS mine",
        "SELECT range AS ticket FROM range(5)",  # tickets_8 of the wrong size
        "SELECT 983039 - range AS ticket FROM range(983040)",  # reversed
        "SELECT range::INT AS ticket FROM range(983040)",  # of the wrong type
    ],
)
def test_a_foreign_database_in_memory_is_left_alone(table):
    con = connection()
    con.execute("ATTACH ':memory:' AS meta_sqlearn")
    con.execute(f"CREATE TABLE meta_sqlearn.tickets_8 AS {table}")
    _falls_back()
    assert _ticket_tables(con) == ["tickets_8"]


def test_a_foreign_database_file_is_left_alone(tmp_path):
    con = connection()
    con.execute(f"ATTACH '{tmp_path / 'other.duckdb'}' AS meta_sqlearn")
    _falls_back()
    assert _ticket_tables(con) == []


def test_a_failure_to_make_tickets_falls_back():
    con = duckdb.connect()
    sq.set_config(connection=con)
    con.execute("SET temp_directory = ''; SET memory_limit = '1MB'")
    with pytest.warns(SqlearnWarning, match="meta_sqlearn"):
        rel = sq.datasets.blobs(rows=100, seed=1)
    con.execute("SET memory_limit = '200MB'")
    assert "meta_sqlearn" not in rel.sql_query()


def test_after_a_detach_the_next_generator_attaches_again():
    con = connection()
    old = sq.datasets.blobs(rows=10)
    con.execute("DETACH meta_sqlearn")
    with pytest.raises(duckdb.Error):
        old.fetchall()
    assert sq.datasets.blobs(rows=10).count("*").fetchall() == [(10,)]
```

Tests run with warnings as errors, so every other test also proves that the
normal path does not warn.

- [ ] **Step 2: Run each and see it fail**

Expected: no warning is raised, or a foreign table is read.

- [ ] **Step 3: Implement**

Through the cursor: when a database named `meta_sqlearn` exists, it is ours only
if `path` is NULL in `duckdb_databases()` and every table in it is
`tickets_<groups>` with the one `BIGINT` column `ticket`, `groups * ROW_GROUP`
rows, and no row where `ticket <> rowid` (one query per table, about 3 ms for 8
groups, measured). Any `duckdb.Error` while checking, attaching or creating, a
foreign database, or no visible ticket table makes `row_source` warn and return
`None`. Warn with `SqlearnWarning` and `skip_file_prefixes` as `generated.py`
does, naming the reason, DuckDB's message when there is one, and a `Fix:` that
offers detaching or renaming the other database, and `parallel=False` to silence
the warning.

- [ ] **Step 4: Run the datasets tests, then `just test`**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sqlearn/datasets/_tickets.py tests/src/sqlearn/datasets/test__tickets.py
git commit -m "feat: fall back to one thread when tickets cannot be used (#46)"
```

---

### Task 6: Decisions and documents

**Files:**
- Create: `docs/adr/0052-meta-sqlearn.md`
- Modify: `docs/adr/index.md` (under "Execution in DuckDB"),
  `docs/adr/0045-datasets-are-relations-built-in-sql.md`,
  `docs/specs/library-datasets.md`, `docs/guide/datasets.md`, `GLOSSARY.md`

- [ ] **Step 1: Write ADR 0052**, "sqlearn's own tables live in `meta_sqlearn`":
      context from spec §2, the decision and every rule of spec §5 (in memory,
      writes through a cursor, immutable ticket tables, ownership, fallback,
      `parallel=False`), the alternatives of spec §4, and consequences: the two
      costs of spec §2. Any later table placed there follows these rules.

- [ ] **Step 2: Amend ADR 0045.** Replace its statement that generators run on
      one thread, and "creating it reads and writes nothing" with "computes no
      data row": the first generator call on a connection makes the small ticket
      table. Add `Amended 2026-11-18 by ADR 0052` to its status line.

- [ ] **Step 3: Update `library-datasets.md` and `datasets.md`.** The spec: same
      two points, plus `parallel` in §5. The guide: a section "Threads" with an
      example of `parallel=False`, what a user sees (`meta_sqlearn` in
      `SHOW DATABASES`, about 8 MiB of memory), and when to pass it: an ordered
      export needs temporary disk, in `.tmp` or `<file>.tmp`, and a writable
      folder; views or SQL that outlive the connection need `parallel=False`.

- [ ] **Step 4: Add to `GLOSSARY.md`** the terms **Work ticket** and
  **meta_sqlearn**, each in the sense of spec §5.

- [ ] **Step 5: Verify**

Run: `just fmt`, then `just check`, then
`rm -rf docs/reference/generated docs/_build && just build-docs`.
Expected: all pass; the guide's code cells and the doctests run.

- [ ] **Step 6: Commit**

```bash
git add docs/adr docs/specs/library-datasets.md docs/guide/datasets.md GLOSSARY.md
git commit -m "docs: meta_sqlearn and generators on many threads (#46)"
```

---

### Task 7: Measure, verify, close

**Files:**
- Create: `docs/benchmarks/generators-on-many-threads.md`
- Modify: `docs/benchmarks/index.md`, `HANDOFF.md`, `CLAUDE.md` only if it
  states generators are single-threaded

- [ ] **Step 1: Run `just verify`.** Expected: passes. Discard diffs in
  `validation/**/*.results.json` that are thread-order rounding only (ADR 0043);
  commit `validation/tests.json` since tests were added. Name every failure.

- [ ] **Step 2: Ask Tomas before measuring.** The run uses all 8 threads and
      should have the machine quiet. Do not start it without his yes.

- [ ] **Step 3: Measure.** `sq.datasets.blobs`, 20M rows and 20 features, all
      columns summed, `parallel=False` and the default, at 1, 2, 4 and 8
      threads; each probe a fresh subprocess, `memory_limit` 2 GB, a time limit,
      three runs, the median reported, `uptime` before and after, one at a time.
      Also the cost at 100 rows, and an ordered Parquet export's time and peak
      temporary disk.

- [ ] **Step 4: Write the page** in the form of `median-reach.md`: what was
  measured, the machine (4 performance and 4 efficiency cores), the load, the
  results. Add it to the index's toctree.

- [ ] **Step 5: Update `HANDOFF.md`:** #46 to "Just finished" with its commit;
      remove it from "Next up"; correct the traps saying generators or their
      source run on one thread (keep the fact about `range()`); add the traps
      worth keeping: a transaction writes one database, so `meta_sqlearn` is
      written through a cursor; a transaction may not see a ticket table made
      after it read the database.

- [ ] **Step 6: Run `just fmt`, `just check`, `just test`, `just verify`, and
  commit**

```bash
git add docs/benchmarks HANDOFF.md validation/tests.json
git commit -m "docs: generators on many threads are measured (#46)"
```

- [ ] **Step 7: Finish the branch** with
      superpowers:finishing-a-development-branch, and on merge close #46 with
      the results, keeping the board in step (github-pm).
