"""Learned values carried from one Python process to the next.

Each case runs short scripts in new processes. A script calls ``mark(label)``
after each action: it records what the store learned (``STORE.learns``) and
the `SqlearnWarning` messages raised since the last mark, and the script
prints them as one JSON line for the test to read.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

_PRELUDE = """
import json
import os
import warnings

import duckdb

import sqlearn as sq
from sqlearn._config import connection
from sqlearn._store import STORE

out = {}
caught = []


def _hook(message, category, filename, lineno, file=None, line=None):
    caught.append((category.__name__, str(message)))


warnings.showwarning = _hook
warnings.simplefilter("always")


def mark(label):
    said = [m for c, m in caught if c == "SqlearnWarning"]
    out[label] = {"learns": dict(STORE.learns), "warnings": said}
    STORE.learns.clear()
    caught.clear()


def parquet(path, ages):
    rows = ", ".join(f"({a}, {a % 3}.5, {a % 2})" for a in ages)
    duckdb.sql(
        f"COPY (SELECT * FROM (VALUES {rows}) t(age, income, churned)) "
        f"TO '{path}' (FORMAT parquet)"
    )


def csv(path, ages):
    rows = ", ".join(f"({a}, {a % 2})" for a in ages)
    duckdb.sql(
        f"COPY (SELECT * FROM (VALUES {rows}) t(age, churned)) "
        f"TO '{path}' (FORMAT csv)"
    )


def pipe():
    return sq.Pipeline([sq.impute.median(), sq.scale.standard()])
"""

_LEARNED = {"median": 1, "standard": 1}


def _run(cwd: Path, body: str) -> dict[str, Any]:
    script = _PRELUDE + textwrap.dedent(body) + "\nprint(json.dumps(out))\n"
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_values_learned_in_one_process_are_found_in_the_next(tmp_path: Path) -> None:
    """A loaded pipeline applies, learns and trains without learning again."""
    first = _run(
        tmp_path,
        """
        parquet("customers.parquet", [20, 31, 40, 51, 60, 71])
        learned = pipe().learn("customers.parquet", target="churned")
        mark("learn")
        sq.save(learned, "customers.sqlearn.json")
        """,
    )
    assert first["learn"]["learns"] == _LEARNED
    second = _run(
        tmp_path,
        """
        from sklearn.linear_model import LogisticRegression

        loaded = sq.load("customers.sqlearn.json")
        loaded.apply("customers.parquet")
        mark("apply")
        loaded.learn("customers.parquet", target="churned")
        mark("learn")
        model = sq.Pipeline(
            [*loaded.steps, ("model", sq.Model(LogisticRegression()))]
        )
        model.train("customers.parquet", "churned")
        mark("train")
        """,
    )
    for label in ("apply", "learn", "train"):
        assert second[label] == {"learns": {}, "warnings": []}, label


def test_a_changed_file_is_learned_again_with_a_warning(tmp_path: Path) -> None:
    """A file changed since the save is learned again, said once."""
    _run(
        tmp_path,
        """
        parquet("customers.parquet", [20, 30, 40, 50])
        sq.save(pipe().learn("customers.parquet"), "customers.sqlearn.json")
        """,
    )
    second = _run(
        tmp_path,
        """
        loaded = sq.load("customers.sqlearn.json")
        parquet("customers.parquet", [21, 31, 41, 51, 61])
        loaded.learn("customers.parquet")
        mark("changed")
        loaded.learn("customers.parquet")
        mark("again")
        """,
    )
    assert second["changed"]["learns"] == _LEARNED
    [said] = second["changed"]["warnings"]
    assert said.startswith("customers.parquet changed since the values in ")
    assert "customers.sqlearn.json" in said
    assert "size or modification time" in said
    assert said.endswith("Fix: save the pipeline again to keep the new values.")
    assert second["again"] == {"learns": {}, "warnings": []}


def test_apply_and_predict_on_a_changed_file_leave_the_warning_to_learn(
    tmp_path: Path,
) -> None:
    """Apply and predict read a changed file silently; the next learn warns."""
    _run(
        tmp_path,
        """
        from sklearn.linear_model import LogisticRegression

        parquet("customers.parquet", [20, 31, 40, 51, 60, 71])
        trained = sq.Pipeline(
            [*pipe().steps, ("model", sq.Model(LogisticRegression()))]
        ).train("customers.parquet", "churned")
        sq.save(trained, "model.sqlearn.json", model="pickle")
        learned = pipe().learn("customers.parquet", target="churned")
        sq.save(learned, "steps.sqlearn.json")
        """,
    )
    second = _run(
        tmp_path,
        """
        import sklearn.linear_model

        trained = sq.load("model.sqlearn.json", trust_model=True)
        loaded = sq.load("steps.sqlearn.json")
        parquet("customers.parquet", [21, 30, 41, 50, 61, 70, 81])
        loaded.apply("customers.parquet")
        mark("apply")
        trained.predict("customers.parquet")
        mark("predict")
        loaded.learn("customers.parquet", target="churned")
        mark("learn")
        loaded.learn("customers.parquet", target="churned")
        mark("again")
        """,
    )
    for label in ("apply", "predict"):
        assert second[label] == {"learns": {}, "warnings": []}, label
    assert second["learn"]["learns"] == _LEARNED
    [said] = second["learn"]["warnings"]
    assert said.startswith("customers.parquet changed since the values in ")
    assert second["again"] == {"learns": {}, "warnings": []}


def test_a_glob_that_gains_a_file_warns(tmp_path: Path) -> None:
    """A glob matching one more file is the same source, changed."""
    (tmp_path / "data").mkdir()
    _run(
        tmp_path,
        """
        csv("data/a.csv", [20, 30, 40])
        sq.save(pipe().learn("data/*.csv"), "p.json")
        """,
    )
    second = _run(
        tmp_path,
        """
        loaded = sq.load("p.json")
        csv("data/b.csv", [50, 60])
        loaded.learn("data/*.csv")
        mark("gained")
        """,
    )
    assert second["gained"]["learns"] == _LEARNED
    [said] = second["gained"]["warnings"]
    assert said.startswith("data/*.csv changed since the values in p.json")
    assert "b.csv" in said


def test_a_relative_path_is_found_from_the_same_folder_only(tmp_path: Path) -> None:
    """The same relative path from another folder is another file: new data."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _run(
        tmp_path / "a",
        """
        parquet("customers.parquet", [20, 30, 40, 50])
        sq.save(pipe().learn("customers.parquet"), "p.json")
        """,
    )
    second = _run(
        tmp_path / "a",
        """
        loaded = sq.load("p.json")
        loaded.learn("customers.parquet")
        mark("same")
        os.chdir("../b")
        parquet("customers.parquet", [21, 31, 41])
        loaded.learn("customers.parquet")
        mark("other")
        """,
    )
    assert second["same"] == {"learns": {}, "warnings": []}
    assert second["other"] == {"learns": _LEARNED, "warnings": []}


def test_a_checkpointed_table_carries_its_values(tmp_path: Path) -> None:
    """A table checkpointed before the save is found; edited, it warns."""
    use = """
    con = duckdb.connect("data.duckdb")
    sq.set_config(connection=con)
    """
    _run(
        tmp_path,
        use
        + """
    con.execute("CREATE TABLE t AS SELECT range * 10.0 AS age FROM range(5)")
    con.execute("CHECKPOINT")
    sq.save(pipe().learn("t"), "p.json")
    mark("save")
    con.close()
    """,
    )
    second = _run(
        tmp_path,
        use
        + """
    sq.load("p.json").learn("t")
    mark("learn")
    con.close()
    """,
    )
    assert second["learn"] == {"learns": {}, "warnings": []}
    third = _run(
        tmp_path,
        use
        + """
    con.execute("UPDATE t SET age = age + 1 WHERE age = 0")
    con.execute("CHECKPOINT")
    sq.load("p.json").learn("t")
    mark("edited")
    con.close()
    """,
    )
    assert third["edited"]["learns"] == _LEARNED
    [said] = third["edited"]["warnings"]
    assert said.startswith("the table main.t in data.duckdb changed since")
    assert "storage" in said


def test_a_table_with_pending_writes_warns_at_save(tmp_path: Path) -> None:
    """A table not checkpointed is saved without its fingerprint, said."""
    use = """
    con = duckdb.connect("data.duckdb")
    sq.set_config(connection=con)
    """
    first = _run(
        tmp_path,
        use
        + """
    con.execute("CREATE TABLE t AS SELECT range * 10.0 AS age FROM range(5)")
    learned = pipe().learn("t")
    mark("learn")
    sq.save(learned, "p.json")
    mark("save")
    con.close()
    """,
    )
    [said] = first["save"]["warnings"]
    assert "Fix: run CHECKPOINT before" in said
    saved = json.loads((tmp_path / "p.json").read_text())
    assert saved["learned"]["data"] == {"kind": "unknown"}
    second = _run(
        tmp_path,
        use
        + """
    sq.load("p.json").learn("t")
    mark("learn")
    con.close()
    """,
    )
    assert second["learn"] == {"learns": _LEARNED, "warnings": []}


def test_a_frame_carries_its_values_and_never_warns(tmp_path: Path) -> None:
    """An equal frame finds its values; a changed one is new data."""
    _run(
        tmp_path,
        """
        import pandas as pd

        frame = pd.DataFrame({"age": [20.0, None, 40.0]})
        sq.save(pipe().learn(frame), "p.json")
        """,
    )
    second = _run(
        tmp_path,
        """
        import pandas as pd

        loaded = sq.load("p.json")
        loaded.learn(pd.DataFrame({"age": [20.0, None, 40.0]}))
        mark("equal")
        loaded.learn(pd.DataFrame({"age": [21.0, None, 40.0]}))
        mark("changed")
        """,
    )
    assert second["equal"] == {"learns": {}, "warnings": []}
    assert second["changed"] == {"learns": _LEARNED, "warnings": []}


def test_a_relation_does_not_carry_its_values(tmp_path: Path) -> None:
    """A relation is saved as unknown: apply works, learn learns again."""
    relation = 'connection().sql("SELECT range * 1.0 AS age FROM range(4)")'
    _run(tmp_path, f'sq.save(pipe().learn({relation}), "p.json")\n')
    saved = json.loads((tmp_path / "p.json").read_text())
    assert saved["learned"]["data"] == {"kind": "unknown"}
    second = _run(
        tmp_path,
        f"""
        loaded = sq.load("p.json")
        loaded.apply({relation})
        mark("apply")
        loaded.learn({relation})
        mark("learn")
        """,
    )
    assert second["apply"] == {"learns": {}, "warnings": []}
    assert second["learn"] == {"learns": _LEARNED, "warnings": []}
