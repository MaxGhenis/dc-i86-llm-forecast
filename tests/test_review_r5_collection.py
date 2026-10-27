"""Round 5 review: MOCK bookkeeping cases isolated to temporary directories.

Cases from the round-5 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against bcb83c6; the fixes made them pass.
"""

import json
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from i86 import cli, runners


@pytest.fixture
def collection_area(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    brief = tmp_path / "MOCK-brief.md"
    brief.write_text("MOCK brief\n")
    return brief


def stage_manual(brief, label="done"):
    run = runners.prepare(label, brief, "MOCK-sha", "manual")
    answer = runners.staged_response(label)
    answer.parent.mkdir(parents=True)
    answer.write_text("MOCK completed answer\n")
    return run


@pytest.mark.parametrize("stage_first", [True, False])
def test_manual_abandonment_is_final(collection_area, stage_first):
    if stage_first:
        run = stage_manual(collection_area)
    else:
        run = runners.prepare("done", collection_area, "MOCK-sha", "manual")
    runners.abandon("done")
    if not stage_first:
        answer = runners.staged_response("done")
        answer.parent.mkdir(parents=True)
        answer.write_text("MOCK late answer\n")
    cli.cmd_collect(None)
    meta = runners.read_meta(run)
    assert meta["state"] == "abandoned"
    assert meta["backend_state"] == "staged"  # what arrived is kept, as the README says
    assert not (run / "response.md").exists()


def test_claude_completion_does_not_revive_abandonment(collection_area, monkeypatch):
    def finish_after_abandon(*args, **kwargs):
        runners.abandon("late")
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "type": "result", "result": "MOCK answer after abandonment"}) + "\n")

    monkeypatch.setattr(runners.subprocess, "run", finish_after_abandon)
    runners.dispatch_claude("late", collection_area, "MOCK-sha", "MOCK-model")
    cli.cmd_collect(None)
    run = runners.RUNS / "late"
    assert runners.read_meta(run)["state"] == "abandoned"
    assert not (run / "response.md").exists()


def test_threaded_dispatch_cannot_enter_during_seal(collection_area, monkeypatch):
    done = stage_manual(collection_area)
    at_seal = threading.Event()
    resume_seal = threading.Event()
    prepare_finished = threading.Event()
    failures = []
    original_seal = runners.seal

    def wait_before_seal(run):
        at_seal.set()
        assert resume_seal.wait(5)
        return original_seal(run)

    def prepare_active():
        try:
            runners.prepare("active", collection_area, "MOCK-sha", "claude")
        except RuntimeError as exc:
            failures.append(str(exc))
        finally:
            prepare_finished.set()

    monkeypatch.setattr(runners, "seal", wait_before_seal)
    collector = threading.Thread(target=cli.cmd_collect, args=(None,))
    collector.start()
    try:
        assert at_seal.wait(5)
        dispatcher = threading.Thread(target=prepare_active)
        dispatcher.start()
        prepare_finished.wait(.1)
    finally:
        resume_seal.set()
        collector.join(5)
    dispatcher.join(5)
    assert not collector.is_alive() and not dispatcher.is_alive()
    meta = runners.read_meta(runners.RUNS / "active")
    # The dispatcher waits for collect's lock, then refuses: answers are already in runs/. (As the
    # review wrote it, the check read a missing run's empty meta as still going.)
    assert (done / "response.md").exists()
    assert not meta and failures and "already in runs/" in failures[0], (meta, failures)


def test_exec_process_prepare_obeys_lock(collection_area):
    """A fresh process, as used by the CLI, does wait for the parent's file lock."""
    area = collection_area.parent
    code = """
import sys
from pathlib import Path
from i86 import runners
area = Path(sys.argv[1])
for name in ('RUNS', 'WORK', 'STAGE'):
    setattr(runners, name, area / name.lower())
(area / 'MOCK-child-ready').write_text('MOCK child ready')
runners.prepare('child', area / 'MOCK-brief.md', 'MOCK-sha', 'manual')
"""
    with runners.bookkeeping_lock():
        child = subprocess.Popen([sys.executable, "-c", code, str(area)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 20
        while not (area / "MOCK-child-ready").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (area / "MOCK-child-ready").exists()
        assert child.poll() is None
        assert not (runners.RUNS / "child" / "meta.json").exists()
    stdout, stderr = child.communicate(timeout=60)
    assert child.returncode == 0, (stdout, stderr)
    assert (runners.RUNS / "child" / "meta.json").exists()
