"""Round-7 recovery probes. All jobs, answers and paths are temporary MOCK data."""

import fcntl
import hashlib
import json
import os
import signal
import threading
import time
from types import SimpleNamespace

import pytest

from i86 import audit, runners


class RecoveryDefect(AssertionError):
    """The setup succeeded, but recovery did not preserve an invariant."""


def stream(result, path=None):
    events = []
    if path is not None:
        events.append({"type": "assistant", "message": {"content": [{
            "type": "tool_use", "name": "Read", "input": {"file_path": str(path)},
        }]}})
    events.append({"type": "result", "subtype": "success", "result": result})
    return "".join(json.dumps(event) + "\n" for event in events)


@pytest.fixture
def lost_run(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    prompt = tmp_path / "MOCK-prompt.md"
    prompt.write_text("MOCK brief")
    run = runners.prepare("lost", prompt, "MOCK-sha", "subfleet", job_id="MOCK-job")
    attempt = runners.JOBS / "MOCK-job" / "a1"
    attempt.mkdir(parents=True)
    (attempt / "exit.json").write_text(json.dumps({"rc": 0, "signal": None}))
    (attempt / "stdout").write_text(stream("MOCK own final"))
    info = {"job": {"job_id": "MOCK-job", "state": "lost"}, "attempts": [{
        "attempt_id": "MOCK-job/a1", "state": "quarantined",
    }]}

    def show(command, **kwargs):
        assert command == ["subfleet", "runs", "show", "MOCK-job", "--json"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(info), stderr="")

    monkeypatch.setattr(runners.subprocess, "run", show)
    return run, attempt


def test_recovery_does_not_accept_deleted_tool_events(lost_run, tmp_path, monkeypatch):
    run, attempt = lost_run
    protected = tmp_path / "MOCK-protected"
    protected.mkdir()
    path = protected / "MOCK-answer.json"
    path.write_text("MOCK OTHER ANSWER")
    monkeypatch.setattr(audit, "protected_roots", lambda: [protected])
    transcript = attempt / "stdout"
    transcript.write_text(stream("MOCK own final", path))
    assert not audit.audit_transcript(transcript, str(runners.WORK / "lost"))["passed"]
    runners.recover("lost")
    transcript.write_text(stream("MOCK own final"))
    if runners.seal(run) and audit.audit_transcript(run / "transcript.jsonl", str(runners.WORK / "lost"))["passed"]:
        raise RecoveryDefect("deleting a protected Read after recovery makes the collected audit pass")


def test_recovery_copies_the_validated_snapshot(lost_run, monkeypatch):
    run, attempt = lost_run
    runners.recover("lost")
    parsed, changed = threading.Event(), threading.Event()
    original = runners.parse_stream

    def pause(text):
        result = original(text)
        parsed.set()
        assert changed.wait(5)
        return result

    def rewrite():
        assert parsed.wait(5)
        (attempt / "stdout").write_text(stream("MOCK REPLACED final"))
        changed.set()

    writer = threading.Thread(target=rewrite)
    writer.start()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(runners, "parse_stream", pause)
            assert runners.seal(run)
    finally:
        writer.join(5)
    assert not writer.is_alive()
    answer = (run / "response.md").read_text()
    copied = original((run / "transcript.jsonl").read_text())[0]
    assert answer == "MOCK own final"
    if hashlib.sha256(copied.encode()).hexdigest() != runners.read_meta(run)["recovered"]["result_sha256"]:
        raise RecoveryDefect((answer, copied))


def test_dead_lock_owner_does_not_block_its_forked_child(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    prompt = tmp_path / "MOCK-prompt.md"
    prompt.write_text("MOCK brief")
    owner = os.fork()
    if owner == 0:
        with runners.bookkeeping_lock():
            child = os.fork()
            if child == 0:
                (tmp_path / "started").touch()
                runners.prepare("child", prompt, "MOCK-sha", "manual")
                (tmp_path / "finished").touch()
                time.sleep(120)  # alive, outside any use, until the parent has looked (then killed)
                os._exit(0)
            (tmp_path / "child-pid").write_text(str(child))
            os._exit(0)
    os.waitpid(owner, 0)
    child = None
    try:
        # The child's own use may take a while on a loaded host; it must end, and then leave the
        # lock free while the child lives on.
        deadline = time.monotonic() + 60
        while not (tmp_path / "finished").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        child = int((tmp_path / "child-pid").read_text())
        if not (tmp_path / "finished").exists():
            raise RecoveryDefect("owner has exited; the child's bookkeeping remains blocked")
        lock = runners.STAGE.with_name(runners.STAGE.name + ".lock")
        with lock.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RecoveryDefect("the child holds the lock outside any use; other bookkeeping is blocked")
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
