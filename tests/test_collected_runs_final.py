"""A collected run is final: later collects leave its metadata alone, and the audit reads its
committed transcript. MOCK subfleet runs in temporary directories.

Before this fix, the second `collect` (the one that took in the late runs) refreshed every subfleet
run, collected or not, and pointed six collected runs' `transcript` back at subfleet's job store.
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from i86 import cli, runners

EXAMPLES = 40


def fake_subfleet(jobs: Path):
    """subfleet as collect calls it: every job has succeeded on attempt a1."""
    def run(cmd, **kwargs):
        if cmd[:3] != ["subfleet", "runs", "show"]:
            raise AssertionError(f"unexpected command {cmd}")
        job = cmd[3]
        if "--out" in cmd:
            return SimpleNamespace(returncode=0, stdout=f"MOCK answer from {job}\n", stderr="")
        payload = {"job": {"state": "succeeded", "finished_at": "2026-10-26T07:00:00Z"},
                   "attempts": [{"state": "succeeded", "attempt_id": f"{job}/a1",
                                 "model_served": "MOCK-model", "lane_id": "MOCK-lane"}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload) + "\n", stderr="")
    return run


def add_run(root: Path, label: str, late: bool = False) -> Path:
    job = f"MOCK-job-{label}"
    stdout = runners.JOBS / job / "a1" / "stdout"
    stdout.parent.mkdir(parents=True)
    stdout.write_text(f'{{"MOCK transcript": "{label}"}}\n')
    brief = root / "MOCK-brief.md"
    brief.write_text("MOCK brief\n")
    return runners.prepare(label, brief, "MOCK-sha", "subfleet", late=late, job_id=job)


def isolate(mp: pytest.MonkeyPatch, root: Path) -> None:
    for name in ("RUNS", "WORK", "STAGE", "JOBS"):
        mp.setattr(runners, name, root / name.lower())
    mp.setattr(runners.subprocess, "run", fake_subfleet(root / "jobs"))


def fake_audit(seen: list):
    def audit_transcript(path, workdir):
        seen.append(Path(path))
        return {"events": 1, "passed": True, "violations": [], "web_calls": 0, "local_calls": [],
                "suspect": []}
    return audit_transcript


def test_second_collect_leaves_a_collected_run_alone(tmp_path, monkeypatch):
    isolate(monkeypatch, tmp_path)
    first = add_run(tmp_path, "first")
    assert cli.cmd_collect(None) == 0
    meta_bytes = (first / "meta.json").read_bytes()
    assert json.loads(meta_bytes)["transcript"] == str(first / "transcript.jsonl")

    add_run(tmp_path, "late", late=True)
    assert cli.cmd_collect(None) == 0
    assert (first / "meta.json").read_bytes() == meta_bytes
    assert (tmp_path / "runs" / "late" / "response.md").exists()


def test_audit_reads_the_committed_transcript(tmp_path, monkeypatch):
    isolate(monkeypatch, tmp_path)
    run = add_run(tmp_path, "first")
    assert cli.cmd_collect(None) == 0
    # A metadata path into the job store, as the old second collect left it, and a job store that
    # has since changed: the audit must still read the copy in runs/.
    meta = runners.read_meta(run)
    store = runners.JOBS / meta["job_id"] / "a1" / "stdout"
    meta["transcript"] = str(store)
    runners.write_meta(run, meta)
    store.write_text('{"MOCK transcript": "rewritten later"}\n')
    seen = []
    monkeypatch.setattr(cli.audit, "audit_transcript", fake_audit(seen))
    assert cli.cmd_audit(None) == 0
    assert seen == [run / "transcript.jsonl"]


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(later=st.lists(st.sampled_from(["late run", "collect", "rewrite store", "delete store"]),
                      min_size=1, max_size=6))
def test_nothing_after_collection_changes_a_collected_run(later):
    """Invariant: once a run is collected, its meta.json and transcript.jsonl keep their bytes,
    and the audit reads that transcript, whatever later dispatches, collects and job-store changes
    come after."""
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        root = Path(tmp)
        isolate(mp, root)
        run = add_run(root, "first")
        assert cli.cmd_collect(None) == 0
        frozen = {name: (run / name).read_bytes() for name in ("meta.json", "transcript.jsonl")}
        store = runners.JOBS / runners.read_meta(run)["job_id"] / "a1" / "stdout"
        n_late = 0
        for step in later:
            if step == "late run":
                n_late += 1
                add_run(root, f"late-{n_late}", late=True)
            elif step == "collect":
                assert cli.cmd_collect(None) == 0
            elif step == "rewrite store" and store.exists():
                store.write_text('{"MOCK transcript": "rewritten"}\n')
            elif step == "delete store":
                store.unlink(missing_ok=True)
        assert cli.cmd_collect(None) == 0
        assert {name: (run / name).read_bytes() for name in frozen} == frozen
        seen = []
        mp.setattr(cli.audit, "audit_transcript", fake_audit(seen))
        assert cli.cmd_audit(None) == 0
        assert run / "transcript.jsonl" in seen
