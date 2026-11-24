"""The crash report the engine's handler writes when Python crashes after
``import sqlearn``: a file on this machine, and the crash goes on as before."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

import sqlearn as sq

# A process that imports sqlearn, then reads address 0.
CRASH = "import sqlearn, ctypes; ctypes.string_at(0)"


def run_crash(home: Path, env_extra=None) -> subprocess.CompletedProcess[str]:
    """Run CRASH in a fresh Python with `home` as its home directory."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONFAULTHANDLER", "XDG_STATE_HOME")
    }
    env["HOME"] = str(home)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-c", CRASH],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def reports_dir(home: Path) -> Path:
    """Where the handler puts its reports under `home`, on this platform."""
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "sqlearn"
    return home / ".local" / "state" / "sqlearn"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_a_crash_after_import_leaves_a_local_report(tmp_path):
    """Reading address 0 ends the process by its signal, as without sqlearn,
    and leaves one report naming the signal, the build and the stack."""
    done = run_crash(tmp_path)
    assert done.returncode in (-signal.SIGSEGV, -signal.SIGBUS), done.stderr
    reports = list(reports_dir(tmp_path).glob("sqlearn-crash-*.txt"))
    assert len(reports) == 1
    text = reports[0].read_text()
    name = signal.Signals(-done.returncode).name
    assert f"signal: {name} ({-done.returncode})" in text
    assert f"build: {sq.version()}\n" in text
    assert "sends nothing anywhere" in text
    assert text.endswith("end of report\n")
    assert str(reports[0]) in done.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_faulthandler_still_reports_after_the_crash_report(tmp_path):
    """With Python's faulthandler on before the import, it still prints its
    traceback: the handler restores it and raises the signal again."""
    done = run_crash(tmp_path, {"PYTHONFAULTHANDLER": "1"})
    assert done.returncode in (-signal.SIGSEGV, -signal.SIGBUS), done.stderr
    assert "Fatal Python error" in done.stderr
    assert list(reports_dir(tmp_path).glob("sqlearn-crash-*.txt"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_an_unwritable_report_directory_never_fails_the_import(tmp_path):
    """When the report directory cannot be made, the import goes on and the
    handler is not installed."""
    # A file where the directory's parent should be.
    blocker = reports_dir(tmp_path).parent
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory\n")
    env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
    env["HOME"] = str(tmp_path)
    done = subprocess.run(
        [sys.executable, "-c", "import sqlearn as sq; print(sq.version())"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("sqlearn ")
