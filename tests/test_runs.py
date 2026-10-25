"""Dispatch bookkeeping: staging, sealing, late runs and which runs get pooled. MOCK runs only."""

import json
from types import SimpleNamespace

import pytest

from i86 import cli, runners
from mock import MOCK_response


@pytest.fixture
def area(tmp_path, monkeypatch):
    for name, sub in [("RUNS", "runs"), ("WORK", "work"), ("STAGE", "stage")]:
        monkeypatch.setattr(runners, name, tmp_path / sub)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("MOCK brief\n")
    return SimpleNamespace(root=tmp_path, prompt=prompt)


def _stage_answer(label, text="MOCK answer"):
    stage = runners.STAGE / label
    stage.mkdir(parents=True)
    (stage / "response.md").write_text(text)
    (stage / "transcript.jsonl").write_text("{}\n")
    meta = runners.read_meta(runners.RUNS / label)
    meta.update(state="succeeded", transcript=str(stage / "transcript.jsonl"))
    runners.write_meta(runners.RUNS / label, meta)


def test_answers_stay_staged_until_every_run_has_finished(area, monkeypatch):
    runners.prepare("claude-1", area.prompt, "sha", "claude")
    _stage_answer("claude-1")
    runners.prepare("sub-1", area.prompt, "sha", "subfleet", job_id="j1")
    state = {"sub-1": "running"}

    def refresh(run_dir):
        meta = runners.read_meta(run_dir)
        meta["state"] = state[run_dir.name]
        runners.write_meta(run_dir, meta)
        return meta

    monkeypatch.setattr(runners, "refresh_subfleet", refresh)
    monkeypatch.setattr(runners, "seal", lambda d, _seal=runners.seal: _seal(d) if d.name != "sub-1" else False)
    cli.cmd_collect(None)
    assert not (runners.RUNS / "claude-1" / "response.md").exists()

    state["sub-1"] = "succeeded"
    cli.cmd_collect(None)
    run = runners.RUNS / "claude-1"
    assert (run / "response.md").read_text() == "MOCK answer"
    assert (run / "transcript.jsonl").exists() and runners.read_meta(run)["transcript"] == str(run / "transcript.jsonl")


def test_an_unknown_subfleet_state_counts_as_still_going(area, monkeypatch, capsys):
    runners.prepare("claude-1", area.prompt, "sha", "claude")
    _stage_answer("claude-1")
    runners.prepare("sub-1", area.prompt, "sha", "subfleet", job_id="j1")

    def refresh(run_dir):
        meta = runners.read_meta(run_dir)
        meta["state"] = "paused-by-operator"
        return meta

    monkeypatch.setattr(runners, "refresh_subfleet", refresh)
    cli.cmd_collect(None)
    assert not (runners.RUNS / "claude-1" / "response.md").exists()
    assert "unknown subfleet state" in capsys.readouterr().err


def test_dispatch_after_collection_needs_late_and_is_flagged(area):
    runners.prepare("claude-1", area.prompt, "sha", "claude")
    _stage_answer("claude-1")
    assert runners.seal(runners.RUNS / "claude-1")
    with pytest.raises(RuntimeError, match="--late"):
        runners.prepare("claude-2", area.prompt, "sha", "claude")
    run = runners.prepare("claude-2", area.prompt, "sha", "claude", late=True)
    assert runners.read_meta(run)["late"] is True


def test_the_work_directory_is_outside_the_repository(area):
    run = runners.prepare("claude-1", area.prompt, "sha", "claude")
    work = runners.read_meta(run)["workdir"]
    assert work == str(runners.WORK / "claude-1") and not work.startswith(str(runners.RUNS))


def _accepted_run(graph, label, prompt_sha="sha", passed=True, prior="none"):
    run = runners.RUNS / label
    run.mkdir(parents=True)
    runners.write_meta(run, {"label": label, "backend": "subfleet", "prompt_sha256": prompt_sha})
    obj = MOCK_response(graph)
    obj["forecaster"]["prior_context"] = prior
    (run / "response.json").write_text(json.dumps(obj))
    (run / "audit.json").write_text(json.dumps({"passed": passed}))


def test_pooling_takes_only_current_prompt_audited_runs_with_no_prior_context(area, graph, capsys):
    _accepted_run(graph, "ok")
    _accepted_run(graph, "old-prompt", prompt_sha="other")
    _accepted_run(graph, "failed-audit", passed=False)
    _accepted_run(graph, "saw-notes", prior="Memory notes: an earlier I-86 forecast put passage at 60%.")
    assert set(cli.accepted_runs(graph, "sha")) == {"ok"}
    err = capsys.readouterr().err
    assert "old-prompt" in err and "failed-audit" in err and "saw-notes" in err
    assert set(cli.accepted_runs(graph, "sha", accept_prior={"saw-notes"})) == {"ok", "saw-notes"}


def test_runs_without_an_audit_are_excluded_unless_manual_and_allowed(area, graph):
    _accepted_run(graph, "sub")
    (runners.RUNS / "sub" / "audit.json").unlink()
    _accepted_run(graph, "man")
    (runners.RUNS / "man" / "audit.json").unlink()
    meta = runners.read_meta(runners.RUNS / "man")
    meta["backend"] = "manual"
    runners.write_meta(runners.RUNS / "man", meta)
    assert set(cli.accepted_runs(graph, "sha")) == set()
    assert set(cli.accepted_runs(graph, "sha", allow_unaudited=True)) == {"man"}
