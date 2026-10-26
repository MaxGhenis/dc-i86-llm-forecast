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


def test_an_unfinished_claude_run_blocks_collection(area):
    runners.prepare("claude-done", area.prompt, "sha", "claude")
    _stage_answer("claude-done")
    runners.prepare("claude-running", area.prompt, "sha", "claude")
    cli.cmd_collect(None)
    assert not (runners.RUNS / "claude-done" / "response.md").exists()
    runners.abandon("claude-running")
    cli.cmd_collect(None)
    assert (runners.RUNS / "claude-done" / "response.md").exists()
    assert not (runners.RUNS / "claude-running" / "response.md").exists()


def test_manual_answers_are_staged_and_sealed_with_the_rest(area):
    runners.prepare("manual-1", area.prompt, "sha", "manual")
    runners.prepare("claude-1", area.prompt, "sha", "claude")
    _stage_answer("claude-1")
    cli.cmd_collect(None)
    assert not (runners.RUNS / "claude-1" / "response.md").exists()  # the manual run is still going
    stage = runners.staged_response("manual-1")
    stage.parent.mkdir(parents=True)
    stage.write_text("MOCK manual answer")
    cli.cmd_collect(None)
    assert (runners.RUNS / "manual-1" / "response.md").read_text() == "MOCK manual answer"
    assert runners.read_meta(runners.RUNS / "manual-1")["state"] == "succeeded"
    assert (runners.RUNS / "claude-1" / "response.md").exists()


def test_a_collected_run_cannot_be_abandoned(area):
    runners.prepare("claude-1", area.prompt, "sha", "claude")
    _stage_answer("claude-1")
    cli.cmd_collect(None)
    with pytest.raises(RuntimeError, match="already collected"):
        runners.abandon("claude-1")


# Recovering a subfleet run reported lost although its agent finished (MOCK job store)

def _lost_job(area, monkeypatch, label="sub-lost", events=None, exit_=None, state="lost"):
    jobs = area.root / "jobs"
    monkeypatch.setattr(runners, "JOBS", jobs)
    run_dir = runners.prepare(label, area.prompt, "sha", "subfleet")
    runners.record(run_dir, job_id=f"MOCK-{label}")
    attempt = jobs / f"MOCK-{label}" / "a1"
    attempt.mkdir(parents=True)
    if events is None:
        events = [{"type": "system", "subtype": "init", "model": "MOCK-model"},
                  {"type": "assistant", "message": {"model": "MOCK-model", "content": []}},
                  {"type": "result", "subtype": "success", "is_error": False, "result": "MOCK final answer"}]
    (attempt / "stdout").write_text("".join(json.dumps(e) + "\n" for e in events))
    (attempt / "exit.json").write_text(json.dumps(exit_ or {"rc": 0, "signal": None}))
    (attempt / "prompt.sent.md").write_text("MOCK sent prompt\n")
    info = {"job": {"state": state, "finished_at": "2026-10-26T00:00:00Z"},
            "attempts": [{"attempt_id": f"MOCK-{label}/a1", "state": "quarantined", "lane_id": "MOCK-lane",
                          "quarantine_reason": "MOCK writers remain after exit receipt"}]}

    def run(cmd, **kw):
        assert cmd[:3] == ["subfleet", "runs", "show"] and "--json" in cmd, cmd
        return SimpleNamespace(returncode=0, stdout=json.dumps(info), stderr="")

    monkeypatch.setattr(runners.subprocess, "run", run)
    return run_dir, attempt


def test_a_lost_run_with_a_finished_transcript_is_recovered_and_flagged(area, monkeypatch):
    run_dir, attempt = _lost_job(area, monkeypatch)
    meta = runners.recover("sub-lost")
    assert meta["state"] == "succeeded" and meta["backend_state"] == "lost" and meta["model_served"] == "MOCK-model"
    assert meta["recovered"]["supervisor_reason"] == "MOCK writers remain after exit receipt"
    # A later refresh from subfleet keeps the run recovered; its 'lost' goes to backend_state.
    runners.record(run_dir, state="lost")
    assert runners.read_meta(run_dir)["state"] == "succeeded"
    assert runners.seal(run_dir)
    assert (run_dir / "response.md").read_text() == "MOCK final answer"
    assert (run_dir / "prompt.sent.md").read_text() == "MOCK sent prompt\n"
    assert (run_dir / "transcript.jsonl").read_text() == (attempt / "stdout").read_text()
    with pytest.raises(RuntimeError):
        runners.recover("sub-lost")


@pytest.mark.parametrize("change", ["failed exit", "signal", "error result", "two results", "no result", "empty",
                                    "not lost"])
def test_only_a_clean_finish_is_recovered(area, monkeypatch, change):
    ok = {"type": "result", "subtype": "success", "is_error": False, "result": "MOCK final answer"}
    events, exit_, state = None, None, "lost"
    if change == "failed exit":
        exit_ = {"rc": 1, "signal": None}
    elif change == "signal":
        exit_ = {"rc": 0, "signal": 9}
    elif change == "error result":
        events = [{**ok, "subtype": "error_max_turns", "is_error": True}]
    elif change == "two results":
        events = [ok, ok]
    elif change == "no result":
        events = [{"type": "assistant", "message": {"content": []}}]
    elif change == "empty":
        events = [{**ok, "result": "  "}]
    else:
        state = "failed"
    run_dir, _ = _lost_job(area, monkeypatch, events=events, exit_=exit_, state=state)
    with pytest.raises(RuntimeError):
        runners.recover("sub-lost")
    assert runners.read_meta(run_dir).get("state") is None and "recovered" not in runners.read_meta(run_dir)


def test_an_abandoned_run_is_not_recovered(area, monkeypatch):
    _lost_job(area, monkeypatch)
    runners.abandon("sub-lost")
    with pytest.raises(RuntimeError):
        runners.recover("sub-lost")


def test_a_transcript_changed_after_recovery_is_not_collected(area, monkeypatch):
    run_dir, attempt = _lost_job(area, monkeypatch)
    runners.recover("sub-lost")
    (attempt / "stdout").write_text(json.dumps({"type": "result", "subtype": "success", "result": "MOCK other"}) + "\n")
    assert not runners.seal(run_dir)
    assert not (run_dir / "response.md").exists() and runners.read_meta(run_dir)["collect_error"]
