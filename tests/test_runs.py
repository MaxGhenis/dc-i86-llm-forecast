"""Dispatch bookkeeping: staging, sealing, late runs and which runs get pooled. MOCK runs only."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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


def _accepted_run(graph, label, prompt_sha="sha", passed=True, prior="none", suspect=()):
    run = runners.RUNS / label
    run.mkdir(parents=True)
    runners.write_meta(run, {"label": label, "backend": "subfleet", "prompt_sha256": prompt_sha})
    obj = MOCK_response(graph)
    obj["forecaster"]["prior_context"] = prior
    (run / "response.json").write_text(json.dumps(obj))
    # A MOCK audit record with the fields audit_transcript writes (a failed audit has a violation).
    violations = [] if passed else [{"tool": "MOCK", "call": "MOCK", "why": "MOCK"}]
    (run / "audit.json").write_text(json.dumps({"passed": passed, "violations": violations,
                                                "suspect": list(suspect)}))


def test_pooling_takes_only_current_prompt_audited_runs_with_no_prior_context(area, graph, capsys):
    _accepted_run(graph, "ok")
    _accepted_run(graph, "old-prompt", prompt_sha="other")
    _accepted_run(graph, "failed-audit", passed=False)
    _accepted_run(graph, "saw-notes", prior="Memory notes: an earlier I-86 forecast put passage at 60%.")
    assert set(cli.accepted_runs(graph, "sha")) == {"ok"}
    err = capsys.readouterr().err
    assert "old-prompt" in err and "failed-audit" in err and "saw-notes" in err
    assert set(cli.accepted_runs(graph, "sha", accept_prior={"saw-notes"})) == {"ok", "saw-notes"}


def test_a_run_with_suspect_calls_is_pooled_only_once_the_operator_lists_it(area, graph, capsys):
    """Round-12 finding 3 (Opus): a suspect call may have read anything, so its run waits for a reader."""
    _accepted_run(graph, "ok")
    call = {"tool": "Bash", "call": '{"command": "MOCK command"}', "why": "MOCK reason"}
    _accepted_run(graph, "odd-call", suspect=[call, call])
    assert set(cli.accepted_runs(graph, "sha")) == {"ok"}
    err = capsys.readouterr().err
    assert "excluding odd-call: 2 suspect call(s)" in err and "--accept-suspect odd-call" in err
    assert set(cli.accepted_runs(graph, "sha", accept_suspect={"odd-call"})) == {"ok", "odd-call"}
    assert set(cli.accepted_runs(graph, "sha", accept_prior={"odd-call"})) == {"ok"}


CALL = {"tool": "exec_command", "call": '{"command": "MOCK command"}', "why": "MOCK reason"}
OTHER = {**CALL, "call": '{"command": "MOCK other command"}'}


def _codex_run(graph, label, session, suspect=()):
    """A MOCK run a Codex lane served, with a MOCK audit of its session logs (None: no such audit)."""
    _accepted_run(graph, label, suspect=suspect)
    meta = runners.read_meta(runners.RUNS / label)
    meta["lane_id"] = "codex-9"
    runners.write_meta(runners.RUNS / label, meta)
    if session is not None:
        (runners.RUNS / label / "codex-sessions").mkdir()
        (runners.RUNS / label / "codex-sessions" / "audit.json").write_text(json.dumps({"run": label, **session}))


def _session(passed=True, main=(), helper=(), earlier=(), script=()):
    """A MOCK session-log audit: an earlier attempt's main thread, the collected main thread and its
    sub-agent, with their suspect calls (`script`: the collected main thread's from its scripts' text)."""
    def thread(tid, parent, suspect, script_suspect=()):
        return {"thread_id": tid, "spawned_by": parent, "script_suspect": list(script_suspect),
                "audit": {"passed": passed, "violations": [], "suspect": list(suspect)}}
    return {"passed": passed, "violations": 0 if passed else 1, "main_thread": "MOCK-main",
            "threads": [thread("MOCK-earlier", None, earlier), thread("MOCK-main", None, main, script),
                        thread("MOCK-helper", "MOCK-main", helper)]}


def test_a_codex_run_is_pooled_only_with_a_passing_audit_of_its_session_logs(area, graph, capsys):
    """A Codex run's transcript omits its sub-agents and earlier attempts, so its session logs' audit
    gates it too."""
    _accepted_run(graph, "opus")  # no Codex lane, so no session logs to audit
    _codex_run(graph, "sol-ok", _session())
    _codex_run(graph, "sol-none", None)
    _codex_run(graph, "sol-failed", _session(passed=False))
    _codex_run(graph, "sol-violation", {**_session(), "violations": 1})
    _codex_run(graph, "sol-odd", _session(helper=[CALL, CALL]))
    _codex_run(graph, "sol-main", _session(main=[CALL]), suspect=[CALL])
    _codex_run(graph, "sol-hidden", _session(main=[CALL]))  # only the session logs show the main thread's call
    _codex_run(graph, "sol-earlier", _session(earlier=[CALL]))
    _codex_run(graph, "sol-script", _session(main=[CALL], script=[OTHER]), suspect=[CALL])
    unreadable = {
        "sol-bad": {"passed": True},  # not a session audit: it lists no threads
        "sol-other-run": {**_session(), "run": "sol-ok"},
        "sol-no-main": {**_session(), "main_thread": None},
        "sol-unknown-main": {**_session(), "main_thread": "MOCK-unknown"},
        "sol-no-script-list": {**_session(), "threads": [{k: v for k, v in t.items() if k != "script_suspect"}
                                                         for t in _session()["threads"]]},
        "sol-call-not-object": _session(helper=["MOCK call"]),
        "sol-audit-not-object": {**_session(), "threads": [{**t, "audit": ["MOCK"]} for t in _session()["threads"]]},
    }
    for label, session in unreadable.items():
        _codex_run(graph, label, session)
    _codex_run(graph, "sol-not-json-run", None)
    (runners.RUNS / "sol-not-json-run" / "codex-sessions").mkdir()
    (runners.RUNS / "sol-not-json-run" / "codex-sessions" / "audit.json").write_text("{MOCK")
    assert set(cli.accepted_runs(graph, "sha")) == {"opus", "sol-ok"}
    err = capsys.readouterr().err
    for label in ["sol-none", "sol-not-json-run", *unreadable]:
        assert f"excluding {label}: no readable audit of its session logs" in err
    assert "excluding sol-failed: the audit of its session logs failed" in err
    assert "excluding sol-violation: the audit of its session logs failed" in err
    assert "excluding sol-odd: 2 suspect call(s)" in err
    assert "excluding sol-main: 1 suspect call(s)" in err  # the main thread's call counts once
    assert "excluding sol-hidden: 1 suspect call(s)" in err
    assert "excluding sol-earlier: 1 suspect call(s)" in err  # an earlier attempt's thread counts
    assert "excluding sol-script: 2 suspect call(s)" in err  # a script's call counts beside its item's
    accept = {"sol-odd", "sol-main", "sol-hidden", "sol-earlier", "sol-script", "sol-none", "sol-failed",
              "sol-violation", *unreadable}
    assert set(cli.accepted_runs(graph, "sha", accept_suspect=accept)) == {
        "opus", "sol-ok", "sol-odd", "sol-main", "sol-hidden", "sol-earlier", "sol-script"}


def test_a_codex_runs_suspect_calls_count_each_thread_once():
    session = _session(main=[CALL], helper=[CALL, CALL], earlier=[OTHER], script=[OTHER])
    assert cli._hidden_suspects(session) == [OTHER, CALL, CALL]  # the earlier attempt's, then the sub-agent's
    assert cli._codex_suspects([CALL, OTHER], session) == [CALL, OTHER, OTHER, OTHER, CALL, CALL]
    assert cli._codex_suspects([], _session(main=[CALL, OTHER])) == [CALL, OTHER]
    assert cli._codex_suspects([CALL], _session(main=[OTHER])) == [CALL]  # one call, as each audit lists it


def test_the_runs_table_counts_every_threads_suspect_calls(area, graph, monkeypatch):
    """`simulate` reports the suspect calls the gate counted, a Codex run's other threads' included."""
    _accepted_run(graph, "opus", suspect=[CALL])
    _codex_run(graph, "sol-ok", _session())
    _codex_run(graph, "sol-odd", _session(main=[CALL], helper=[CALL, CALL], earlier=[CALL], script=[OTHER]),
               suspect=[CALL])
    _codex_run(graph, "sol-hidden", _session(main=[CALL]))
    assert _simulated_counts(graph, monkeypatch, ["opus", "sol-odd", "sol-hidden"]) == {
        "opus": 1, "sol-ok": 0, "sol-odd": 5, "sol-hidden": 1}


def _simulated_counts(graph, monkeypatch, accept) -> dict:
    """Each pooled run's suspect-call count as `simulate` hands it to the report (MOCK pooling)."""
    reported = {}
    monkeypatch.setattr(cli.graph_mod, "load", lambda: graph)
    monkeypatch.setattr(cli, "_prompt_sha", lambda: "sha")
    monkeypatch.setattr(cli, "pool", lambda g, runs, n, seed: "MOCK pooled result")
    monkeypatch.setattr(cli.report, "write", lambda g, result, meta, out: reported.update(meta))
    args = argparse.Namespace(n=1, seed=0, allow_unaudited=False, accept_prior=[], accept_suspect=list(accept))
    assert cli.cmd_simulate(args) == 0
    return {label: m["suspect_calls"] for label, m in reported.items()}


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(threads=st.lists(st.tuples(st.integers(0, 2), st.integers(0, 2)), min_size=1, max_size=4),
       main=st.integers(0, 3), transcript=st.integers(0, 3), passed=st.booleans(), violations=st.integers(0, 1),
       accept=st.booleans())
def test_the_gate_admits_and_counts_as_its_rule_says(graph, threads, main, transcript, passed, violations, accept):
    """Property (differential against the rule written out): a Codex run is pooled exactly when its
    session audit passed with no violation and it has no suspect call or the reader accepted it; its
    count is the main thread's item calls as the longer of its two audits lists them, plus that
    thread's script calls and every call of every other thread; and `simulate` reports that count."""
    main %= len(threads)
    session = {"passed": passed, "violations": violations, "main_thread": f"MOCK-{main}",
               "threads": [{"thread_id": f"MOCK-{i}", "spawned_by": None if i == main else f"MOCK-{main}",
                            "audit": {"suspect": [CALL] * items}, "script_suspect": [OTHER] * scripts}
                           for i, (items, scripts) in enumerate(threads)]}
    expected = (max(transcript, threads[main][0]) + threads[main][1]
                + sum(items + scripts for i, (items, scripts) in enumerate(threads) if i != main))
    pooled = passed and not violations and (expected == 0 or accept)
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        mp.setattr(runners, "RUNS", Path(tmp) / "runs")
        _codex_run(graph, "sol-1", session, suspect=[CALL] * transcript)
        accepted = {"sol-1"} if accept else set()
        assert set(cli.accepted_runs(graph, "sha", accept_suspect=accepted)) == ({"sol-1"} if pooled else set())
        assert len(cli._codex_suspects([CALL] * transcript, {"run": "sol-1", **session})) == expected
        if pooled:
            assert _simulated_counts(graph, mp, accepted) == {"sol-1": expected}


def test_a_run_is_served_by_codex_when_its_lane_or_model_says_so():
    assert runners.served_by_codex({"lane_id": "codex-4", "model_served": "gpt-6.1-sol"})
    assert runners.served_by_codex({"lane_id": "codex-9"})
    assert runners.served_by_codex({"model_served": "gpt-6.1-sol"})
    assert not runners.served_by_codex({"lane_id": "claude-8", "model_served": "claude-opus-5-5"})
    assert not runners.served_by_codex({"backend": "manual"})


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


def test_a_collected_transcript_is_the_one_its_hash_names(area):
    runners.prepare("claude-hash", area.prompt, "sha", "claude")
    _stage_answer("claude-hash")
    (runners.STAGE / "claude-hash" / "transcript.jsonl").write_text('{"type": "MOCK"}\n')
    assert runners.seal(runners.RUNS / "claude-hash")
    meta = runners.read_meta(runners.RUNS / "claude-hash")
    copied = (runners.RUNS / "claude-hash" / "transcript.jsonl").read_bytes()
    assert copied == b'{"type": "MOCK"}\n'
    assert meta["transcript_sha256"] == hashlib.sha256(copied).hexdigest()


def test_a_recovered_transcript_with_an_added_event_is_not_collected(area, monkeypatch):
    # The final message is unchanged; only the audit trail differs, which the whole-transcript hash
    # catches.
    run_dir, attempt = _lost_job(area, monkeypatch)
    runners.recover("sub-lost")
    with (attempt / "stdout").open("a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "MOCK"}]}}) + "\n")
    assert not runners.seal(run_dir)
    assert runners.read_meta(run_dir)["collect_error"]
