"""Round 6 review: MOCK collection probes isolated to temporary directories."""

import json
import os
import signal
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


@pytest.mark.parametrize("pause", ["backend", "record"])
@pytest.mark.parametrize("backend", ["claude", "subfleet"])
def test_dispatch_metadata_cannot_erase_abandonment(collection_area, monkeypatch, backend, pause):
    # Metadata writes now hold the lock, so an abandon can only come between them: while the
    # backend runs, or just before dispatch's next update takes the lock.
    ready = threading.Event()
    resume = threading.Event()
    original_record = runners.record
    errors = []

    def hold():
        if threading.current_thread().name == "MOCK-dispatch" and not ready.is_set():
            ready.set()
            assert resume.wait(10)

    def paused_record(run, state=None, **fields):
        if pause == "record" and "dispatched_at" in fields:
            hold()
        return original_record(run, state, **fields)

    def backend_run(cmd, **kwargs):
        if cmd[0] == "claude":
            if pause == "backend":
                hold()
            payload = {"type": "result", "result": "MOCK late Claude answer"}
        elif "--out" in cmd:
            return SimpleNamespace(returncode=0, stdout="MOCK late subfleet answer\n", stderr="")
        elif "--json" in cmd and "show" in cmd:
            payload = {"job": {"state": "succeeded"}, "attempts": []}
        else:
            if pause == "backend":
                hold()
            payload = {"job_id": "MOCK-job"}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload) + "\n", stderr="")

    def dispatch():
        try:
            if backend == "claude":
                runners.dispatch_claude("late", collection_area, "MOCK-sha", "MOCK-model")
            else:
                runners.dispatch_subfleet("late", collection_area, "MOCK-sha", "MOCK-tier", "MOCK-model")
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(runners, "record", paused_record)
    monkeypatch.setattr(runners.subprocess, "run", backend_run)
    dispatcher = threading.Thread(target=dispatch, name="MOCK-dispatch")
    dispatcher.start()
    try:
        assert ready.wait(10)
        runners.abandon("late")
        assert runners.read_meta(runners.RUNS / "late")["state"] == "abandoned"
    finally:
        resume.set()
        dispatcher.join(10)
    assert not dispatcher.is_alive() and not errors, errors
    cli.cmd_collect(None)
    run = runners.RUNS / "late"
    meta = runners.read_meta(run)
    assert meta.get("state") == "abandoned" and not (run / "response.md").exists(), meta
    assert meta.get("backend_state") == "succeeded" or backend == "subfleet" and meta.get("job_id"), meta


def test_abandon_waits_for_a_metadata_write_in_progress(collection_area, monkeypatch):
    runners.prepare("busy", collection_area, "MOCK-sha", "subfleet")
    inside, release = threading.Event(), threading.Event()
    original_write = runners.write_meta

    def slow_write(run, meta):
        if threading.current_thread().name == "MOCK-writer":
            inside.set()
            assert release.wait(10)
        original_write(run, meta)

    monkeypatch.setattr(runners, "write_meta", slow_write)
    writer = threading.Thread(target=lambda: runners.record(runners.RUNS / "busy", state="running"),
                              name="MOCK-writer")
    writer.start()
    assert inside.wait(10)
    abandoner = threading.Thread(target=lambda: runners.abandon("busy"))
    abandoner.start()
    abandoner.join(0.3)
    assert abandoner.is_alive()  # it waits for the write, rather than being overwritten by it
    release.set()
    writer.join(10)
    abandoner.join(10)
    assert runners.read_meta(runners.RUNS / "busy")["state"] == "abandoned"


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
def test_fork_dispatch_cannot_enter_during_seal(collection_area, monkeypatch):
    done = runners.prepare("done", collection_area, "MOCK-sha", "manual")
    staged = runners.staged_response("done")
    staged.parent.mkdir(parents=True)
    staged.write_text("MOCK completed answer\n")
    child_result = collection_area.parent / "MOCK-child-result.json"
    original_seal = runners.seal
    children = []

    def seal_with_child(run):
        pid = os.fork()
        if pid == 0:
            try:
                runners.prepare("active", collection_area, "MOCK-sha", "claude")
                result = {"prepared": True}
            except BaseException as exc:
                result = {"prepared": False, "error": str(exc)}
            child_result.write_text(json.dumps(result))
            os._exit(0)
        children.append(pid)
        deadline = time.monotonic() + 1
        while not child_result.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        return original_seal(run)

    monkeypatch.setattr(runners, "seal", seal_with_child)
    try:
        cli.cmd_collect(None)
        deadline = time.monotonic() + 10
        while not child_result.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert child_result.exists()
        result = json.loads(child_result.read_text())
        active = runners.read_meta(runners.RUNS / "active")
        assert (done / "response.md").exists()
        assert not active and not result["prepared"], (result, active)
    finally:
        for pid in children:
            waited, _ = os.waitpid(pid, os.WNOHANG)
            if not waited:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
