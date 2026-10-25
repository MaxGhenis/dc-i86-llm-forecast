import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from i86 import audit, runners  # noqa: E402
from i86 import graph as graph_mod  # noqa: E402


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
