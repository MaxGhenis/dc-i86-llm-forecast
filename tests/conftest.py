import os
import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from hypothesis import settings  # noqa: E402

from i86 import audit, runners  # noqa: E402
from i86 import graph as graph_mod  # noqa: E402

# These properties check what the code reads, not how fast: on a loaded host an example can take far
# longer than Hypothesis's 200 ms deadline, which would fail the test for no fault of the code.
settings.register_profile("no-deadline", parent=settings.default, deadline=None)
settings.load_profile("no-deadline")


class WaitedOnAPipe(BaseException):
    """The code under test opened a pipe that no one else opens. A BaseException, so that code that
    catches Exception or OSError cannot take it for an error of its own."""


@pytest.fixture(autouse=True)
def a_pipe_cannot_hang_a_test(monkeypatch):
    """A test that makes a pipe (`os.mkfifo`) fails within 30 seconds, instead of waiting forever, if
    the code under test opens it: no one opens the pipe's other end, so the open never returns. Making
    the pipe sets an alarm, whose handler stops the wait."""
    make, before = os.mkfifo, []

    def stop(signum, frame):
        raise WaitedOnAPipe("the code under test opened a pipe that no one else opens")

    def mkfifo(path, *args, **kwargs):
        make(path, *args, **kwargs)
        if not before:
            before.append(signal.signal(signal.SIGALRM, stop))
        signal.alarm(30)

    monkeypatch.setattr(os, "mkfifo", mkfifo)
    yield
    if before:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, before[0])


@pytest.fixture(scope="session")
def graph():
    return graph_mod.load()


@pytest.fixture
def review_area(tmp_path, monkeypatch):
    """A MOCK work area: this run's directory (opus-1, with scratch/deep), another run's, and two
    protected places, each holding a MOCK answer and a MOCK script."""
    monkeypatch.setattr(runners, "WORK", tmp_path / "work")
    roots = [tmp_path / "repository", tmp_path / "staging"]
    monkeypatch.setattr(audit, "protected_roots", lambda: roots)
    work = runners.WORK / "opus-1"
    (work / "scratch" / "deep").mkdir(parents=True)
    for root in [runners.WORK / "opus-2", *roots]:
        root.mkdir(parents=True)
        (root / "draft.json").write_text("MOCK OTHER ANSWER\n")
        script = root / "tool.sh"
        script.write_text("#!/bin/sh\necho MOCK PROTECTED SCRIPT\n")
        script.chmod(0o700)
    return work
