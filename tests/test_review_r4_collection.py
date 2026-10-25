"""Round 4 review: isolated MOCK bookkeeping counterexamples; no live jobs.

Cases from the round-4 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against 6844063; the fixes made them pass.
"""

import json
from types import SimpleNamespace

import pytest

from i86 import cli, runners


@pytest.fixture
def review_area(tmp_path, monkeypatch):
    for name in ("RUNS", "WORK", "STAGE"):
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    brief = tmp_path / "MOCK-brief.md"
    brief.write_text("MOCK brief\n")
    return brief


def stage_manual(brief):
    done = runners.prepare("done", brief, "MOCK-sha", "manual")
    answer = runners.staged_response("done")
    answer.parent.mkdir(parents=True)
    answer.write_text("MOCK completed answer\n")
    return done


@pytest.mark.parametrize("backend_state", ["queued", "running", "paused-by-operator"])
def test_abandoned_subfleet_does_not_block_collection(review_area, monkeypatch, backend_state):
    done = stage_manual(review_area)
    stuck = runners.prepare("stuck", review_area, "MOCK-sha", "subfleet", job_id="MOCK-job")
    status = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"job": {"state": backend_state}, "attempts": []}),
        stderr="",
    )
    monkeypatch.setattr(runners.subprocess, "run", lambda *args, **kwargs: status)
    runners.abandon("stuck")
    cli.cmd_collect(None)
    assert runners.read_meta(stuck)["state"] == "abandoned"
    assert (done / "response.md").exists()


def test_dispatch_between_collect_snapshot_and_seal_blocks_collection(review_area, monkeypatch):
    done = stage_manual(review_area)
    original_run_dirs = cli.run_dirs

    def dispatch_after_snapshot():
        snapshot = original_run_dirs()
        # Deterministic scheduling of concurrent dispatch's first operation, after collect's
        # snapshot but before it checks metadata or copies answers. No subprocess is started.
        runners.prepare("active", review_area, "MOCK-sha", "claude")
        return snapshot

    monkeypatch.setattr(cli, "run_dirs", dispatch_after_snapshot)
    cli.cmd_collect(None)
    active_meta = runners.read_meta(runners.RUNS / "active")
    assert runners.still_going(active_meta)
    assert not active_meta.get("late")
    assert not (done / "response.md").exists()
