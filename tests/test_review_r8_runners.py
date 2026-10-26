"""Round-8 review probes; all runner paths and transcripts use temporary MOCK data."""

import fcntl
import json
import os
import signal
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from i86 import audit, cli, runners


class ReviewDefect(AssertionError):
    """A completed probe violated the intended invariant."""


def isolate(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    brief = tmp_path / "MOCK-brief.md"
    brief.write_text("MOCK brief\n")
    return brief


def test_collected_run_without_transcript_does_not_audit_job_store(tmp_path, monkeypatch):
    brief = isolate(tmp_path, monkeypatch)
    run = runners.prepare("first", brief, "MOCK-sha", "subfleet", job_id="MOCK-job")
    store = runners.JOBS / "MOCK-job" / "a1" / "stdout"
    store.parent.mkdir(parents=True)

    def show(cmd, **kwargs):
        assert cmd[:4] == ["subfleet", "runs", "show", "MOCK-job"]
        if cmd[-1] == "--out":
            return SimpleNamespace(returncode=0, stdout="MOCK answer\n", stderr="")
        assert cmd[-1] == "--json"
        info = {"job": {"state": "succeeded"}, "attempts": [
            {"attempt_id": "MOCK-job/a1", "state": "succeeded"}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(info), stderr="")

    monkeypatch.setattr(runners.subprocess, "run", show)
    assert cli.cmd_collect(None) == 0
    assert (run / "response.md").exists()
    assert not (run / "transcript.jsonl").exists()
    store.write_text('{"type":"result","subtype":"success","result":"MOCK later"}\n')
    seen = []
    actual_audit = audit.audit_transcript

    def track(path, workdir):
        seen.append(Path(path))
        return actual_audit(path, workdir)

    monkeypatch.setattr(audit, "audit_transcript", track)
    status = cli.cmd_audit(None)
    if seen:
        raise ReviewDefect((seen, status, json.loads((run / "audit.json").read_text())))
    assert status == 1


def test_fork_while_thread_waits_for_lock_does_not_retain_descriptor(tmp_path, monkeypatch):
    """Forking before a waiting flock is registered must not keep its future lock alive."""
    brief = isolate(tmp_path, monkeypatch)
    lock_path = runners.STAGE.with_name(runners.STAGE.name + ".lock")
    original_flock = fcntl.flock
    owner = child = None
    with lock_path.open("a") as blocker:
        original_flock(blocker, fcntl.LOCK_EX)
        owner = os.fork()
        if owner == 0:
            before_flock, acquired = threading.Event(), threading.Event()

            def tracked_flock(handle, operation):
                if threading.current_thread().name == "MOCK-lock-waiter" and operation == fcntl.LOCK_EX:
                    before_flock.set()
                return original_flock(handle, operation)

            runners.fcntl.flock = tracked_flock

            def wait_for_lock():
                with runners.bookkeeping_lock():
                    acquired.set()
                    # The owner exits from the main thread while this context still holds the lock.
                    threading.Event().wait(8)

            waiter = threading.Thread(target=wait_for_lock, name="MOCK-lock-waiter")
            waiter.start()
            if not before_flock.wait(5):
                os._exit(3)
            child = os.fork()
            if child == 0:
                (tmp_path / "child-started").touch()
                deadline = time.monotonic() + 8
                while not (tmp_path / "owner-exited").exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                runners.prepare("child", brief, "MOCK-sha", "manual")
                (tmp_path / "child-finished").touch()
                os._exit(0)
            (tmp_path / "child-pid").write_text(str(child))
            os._exit(0 if acquired.wait(8) else 4)

        try:
            deadline = time.monotonic() + 5
            while not (tmp_path / "child-pid").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            assert (tmp_path / "child-pid").exists()
            child = int((tmp_path / "child-pid").read_text())
            original_flock(blocker, fcntl.LOCK_UN)
            _, status = os.waitpid(owner, 0)
            owner = None
            assert os.waitstatus_to_exitcode(status) == 0
            (tmp_path / "owner-exited").touch()
            deadline = time.monotonic() + 1
            while not (tmp_path / "child-finished").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            with lock_path.open("a") as independent:
                try:
                    original_flock(independent, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ReviewDefect("dead owner left an unregistered inherited descriptor: child prepare and independent flock are blocked")
                else:
                    original_flock(independent, fcntl.LOCK_UN)
            assert (tmp_path / "child-finished").exists()
        finally:
            original_flock(blocker, fcntl.LOCK_UN)
            if child is not None:
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if owner is not None:
                try:
                    os.kill(owner, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(owner, 0)


@pytest.mark.parametrize("backend", ["manual", "claude", "subfleet"])
def test_sequential_operations_preserve_all_collected_files(tmp_path, monkeypatch, backend):
    brief = isolate(tmp_path, monkeypatch)
    event = json.dumps({"type": "result", "subtype": "success", "result": "MOCK final"}) + "\n"

    def fake_backend(cmd, **kwargs):
        if cmd[0] == "claude":
            return SimpleNamespace(returncode=0, stdout=event, stderr="")
        assert cmd[:2] == ["subfleet", "runs"] or cmd[:2] == ["subfleet", "run"]
        if cmd[1] == "run":
            return SimpleNamespace(returncode=0, stdout='{"job_id":"MOCK-job"}', stderr="")
        if cmd[-1] == "--out":
            return SimpleNamespace(returncode=0, stdout="MOCK final", stderr="")
        info = {"job": {"state": "succeeded"}, "attempts": [
            {"attempt_id": "MOCK-job/a1", "state": "succeeded"}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(info), stderr="")

    monkeypatch.setattr(runners.subprocess, "run", fake_backend)
    store = runners.JOBS / "MOCK-job" / "a1" / "stdout"
    store.parent.mkdir(parents=True)
    store.write_text(event)
    if backend == "claude":
        runners.dispatch_claude("first", brief, "MOCK-sha", "MOCK-model")
    elif backend == "subfleet":
        runners.dispatch_subfleet("first", brief, "MOCK-sha", "MOCK-tier", "MOCK-model")
    else:
        runners.prepare("first", brief, "MOCK-sha", "manual")
        staged = runners.staged_response("first")
        staged.parent.mkdir(parents=True)
        staged.write_text("MOCK final")
    assert cli.cmd_collect(None) == 0
    first = runners.RUNS / "first"
    (first / "response.json").write_text('{"MOCK":"parsed answer"}\n')
    names = ["meta.json", "response.md", "response.json"]
    if backend != "manual":
        names.append("transcript.jsonl")
    frozen = {name: (first / name).read_bytes() for name in names}
    for late in (False, True):
        with pytest.raises(FileExistsError):
            runners.prepare("first", brief, "MOCK-sha", backend, late=late)
    with pytest.raises(RuntimeError):
        runners.prepare("early", brief, "MOCK-sha", "manual")
    for action in (runners.abandon, runners.recover):
        with pytest.raises(RuntimeError):
            action("first")
    runners.prepare("late-abandoned", brief, "MOCK-sha", "manual", late=True)
    runners.abandon("late-abandoned")
    staged = runners.staged_response("late-abandoned")
    staged.parent.mkdir(parents=True)
    staged.write_text("MOCK ignored late answer")
    runners.prepare("late-finished", brief, "MOCK-sha", "manual", late=True)
    staged = runners.staged_response("late-finished")
    staged.parent.mkdir(parents=True)
    staged.write_text("MOCK late finished answer")
    store.write_text('{"MOCK":"job store changed after collection"}\n')
    assert cli.cmd_collect(None) == 0
    assert cli.cmd_collect(None) == 0
    assert {name: (first / name).read_bytes() for name in names} == frozen
    assert not (runners.RUNS / "late-abandoned" / "response.md").exists()
    assert (runners.RUNS / "late-finished" / "response.md").exists()
