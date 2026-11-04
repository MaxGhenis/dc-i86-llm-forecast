"""Dispatch bookkeeping: staging, sealing, late runs and which runs get pooled. MOCK runs only."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from i86 import cli, report, runners
from i86.response import parse
from i86.summarize import pool
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
JOB = "MOCK-job"
WORKDIR = "/MOCK/work/sol"
# subfleet's record of the MOCK job: a failed first attempt and the collected second one.
ATTEMPTS = {"job_id": JOB, "accepted_attempt_id": f"{JOB}/a2",
            "attempts": [{"attempt_id": f"{JOB}/a1", "native_session_id": "MOCK-earlier", "started_at": "MOCK"},
                         {"attempt_id": f"{JOB}/a2", "native_session_id": "MOCK-main", "started_at": "MOCK"}]}


def _codex_run(graph, label, session, suspect=(), attempts=ATTEMPTS, collected=f"{JOB}/a2", thread="MOCK-main",
               workdir=WORKDIR):
    """A MOCK run a Codex lane served in `workdir`: a MOCK audit of its session logs (None: no such
    audit), subfleet's record of its attempts (None: none on record; a string: the file's text), and a
    transcript of `thread`."""
    _accepted_run(graph, label, suspect=suspect)
    run = runners.RUNS / label
    meta = runners.read_meta(run)
    meta.update(lane_id="codex-9", job_id=JOB, attempt_id=collected, workdir=workdir)
    runners.write_meta(run, meta)
    (run / "transcript.jsonl").write_text(json.dumps({"type": "thread.started", "thread_id": thread}) + "\n")
    if session is not None:
        record = {"run": label, **_marked(session, attempts)}
        if attempts is None:  # the script names the job and the collected attempt only from their record
            record = {k: v for k, v in record.items() if k not in ("job_id", "collected_attempt")}
        (run / "codex-sessions").mkdir()
        (run / "codex-sessions" / "audit.json").write_text(json.dumps(record))
        if attempts is not None:
            text = attempts if isinstance(attempts, str) else json.dumps(attempts)
            (run / "codex-sessions" / "attempts.json").write_text(text)


def _thread(tid, parent, suspect=(), script_suspect=(), spawns=0):
    """One thread's entry in a MOCK session audit, as the script writes one: a web search for each call
    its own audit read (one web call, the rest suspect), a message, a start event and a `spawn_agent`
    call for each sub-agent, two pages served, and its scripts' suspect calls."""
    searches = 1 + len(suspect)
    return {"thread_id": tid, "spawned_by": parent, "agent_path": None if parent is None else "/root/MOCK",
            "started": "2026-11-03T18:10:00Z", "file": f"codex-sessions/rollout-{tid}.jsonl", "sha256": "0" * 64,
            "items": {"Extension:web.search": searches, "AgentMessage": 1,
                      **({"SubAgentActivity": spawns} if spawns else {})},
            "script_tools": {"web__run": 1}, "functions": {"spawn_agent": spawns} if spawns else {},
            "served_pages": 2, "script_suspect": list(script_suspect),
            "audit": {"events": searches + 1, "tool_calls": searches, "web_calls": 1,
                      "urls": ["https://www.example.org/MOCK"], "violations": [], "suspect": list(suspect),
                      "local_calls": [], "passed": True}}


def _marked(session: dict, attempts) -> dict:
    """A MOCK session audit whose threads each say, as the script marks them, whether they descend from
    its main thread (`collected`) and which attempt's session they descend from, unless a thread says."""
    threads = session.get("threads")
    if not (isinstance(threads, list) and all(isinstance(t, dict) and isinstance(t.get("thread_id"), str)
                                              and isinstance(t.get("spawned_by"), (str, type(None))) for t in threads)):
        return session
    parent = {t["thread_id"]: t["spawned_by"] for t in threads}
    listed = attempts.get("attempts") if isinstance(attempts, dict) else None
    attempt_of = {a["native_session_id"]: a.get("attempt_id") for a in listed if isinstance(a, dict)
                  and isinstance(a.get("native_session_id"), str) and a["native_session_id"]} if isinstance(
        listed, list) else {}

    def root(tid: str) -> str:
        for _ in parent:
            if parent.get(tid) is None:
                break
            tid = parent[tid]
        return tid

    return {**session, "threads": [{"collected": root(t["thread_id"]) == session.get("main_thread"),
                                    "attempt": attempt_of.get(root(t["thread_id"])), **t} for t in threads]}


def _totals(threads) -> dict:
    """A session audit's totals over its threads, as the script adds them up."""
    return {"web_calls": sum(t["audit"]["web_calls"] for t in threads),
            "served_pages": sum(t["served_pages"] for t in threads),
            "commands": sum(t["items"].get("CommandExecution", 0) for t in threads),
            "violations": sum(len(t["audit"]["violations"]) for t in threads),
            "suspect": sum(len(t["audit"]["suspect"]) + len(t["script_suspect"]) for t in threads)}


def _compared(threads, main) -> dict:
    """The check of the transcript a passing audit writes: each of the main thread's web searches and
    commands compared, and none that differs."""
    items = next((t["items"] for t in threads if t.get("thread_id") == main), {})
    searches = sum(n for kind, n in items.items() if kind.startswith("Extension:web."))
    return {"items": searches + items.get("CommandExecution", 0), "only_in_transcript": [], "only_in_log": [],
            "different": []}


def _session(passed=True, main=(), helper=(), earlier=(), script=(), threads=None, main_thread="MOCK-main"):
    """A MOCK session-log audit as the script writes one: an earlier attempt's main thread, the
    collected main thread and its sub-agent, with their suspect calls (`script`: the collected main
    thread's from its scripts' text), and totals that add up. A failed one has a sub-agent's violation."""
    if threads is None:
        threads = [_thread("MOCK-earlier", None, earlier), _thread("MOCK-main", None, main, script, spawns=1),
                   _thread("MOCK-helper", "MOCK-main", helper)]
        if not passed:
            threads[2]["audit"].update(passed=False, violations=[CALL])
    return {"workdir": WORKDIR, "passed": passed, "main_thread": main_thread, "job_id": JOB,
            "collected_attempt": f"{JOB}/a2", "flags": [], "missing": [], "orphans": [], "threads": threads,
            **_totals(threads), "transcript_check": _compared(threads, main_thread)}


def _edited(change) -> dict:
    """A passing MOCK session audit after `change` edits it in place."""
    session = _session()
    change(session)
    return session


def _drop_all_but_main(session):
    session["threads"] = [t for t in session["threads"] if t["thread_id"] == "MOCK-main"]
    session.update(_totals(session["threads"]))


def _add_stray_root(session):
    session["threads"].append(_thread("MOCK-stray", None))
    session.update(_totals(session["threads"]))


def _drop_earlier(session):
    session["threads"] = [t for t in session["threads"] if t["thread_id"] != "MOCK-earlier"]
    session.update(_totals(session["threads"]))


def _with_reasoning(session):
    """The sub-agent reasoned twice: two more items, each a line of the stream its audit read."""
    helper = session["threads"][2]
    helper["items"]["Reasoning"] = 2
    helper["audit"]["events"] += 2


def _with_main_command(session):
    """The main thread ran a command: one more item, event and call, and one more item for the check of
    the transcript to compare."""
    main = session["threads"][1]
    main["items"]["CommandExecution"] = 1
    main["audit"].update(events=main["audit"]["events"] + 1, tool_calls=main["audit"]["tool_calls"] + 1)
    session.update(_totals(session["threads"]), transcript_check=_compared(session["threads"], "MOCK-main"))


def _attempts(*sessions) -> dict:
    """subfleet's record of the MOCK job with one started attempt per session, a1 first."""
    return {**ATTEMPTS, "attempts": [{"attempt_id": f"{JOB}/a{i}", "native_session_id": sid, "started_at": "MOCK"}
                                     for i, sid in enumerate(sessions, 1)]}


def _check(**change) -> dict:
    """A passing MOCK session audit whose check of the transcript has these fields changed."""
    session = _session()
    session["transcript_check"].update(change)
    return session


# Threads whose ids or parents the gate cannot read as a graph (review findings 4 and 8).
DUPLICATED = [_thread("MOCK-earlier", None), _thread("MOCK-main", None, spawns=2), _thread("MOCK-helper", "MOCK-main"),
              _thread("MOCK-helper", "MOCK-main")]
LOOP = [*_session()["threads"], _thread("MOCK-loop-a", "MOCK-loop-b", spawns=1),
        _thread("MOCK-loop-b", "MOCK-loop-a", spawns=1)]
UNDER_ROOT = [_thread("MOCK-root", None, spawns=1), _thread("MOCK-main", "MOCK-root")]
UNDER_EARLIER = [_thread("MOCK-earlier", None, spawns=1), _thread("MOCK-main", "MOCK-earlier")]


# A record that says it passed but does not hold up, and the reason the gate gives (review finding 5):
# (session, attempts, collected, the reason).
INCONSISTENT = {
    "sol-flags": ({**_session(), "flags": ["MOCK flag"]}, ATTEMPTS, f"{JOB}/a2", "its 'flags' field is not"),
    "sol-missing": ({**_session(), "missing": ["MOCK-lost"]}, ATTEMPTS, f"{JOB}/a2", "its 'missing' field is not"),
    "sol-orphans": ({**_session(), "orphans": ["MOCK-o"]}, ATTEMPTS, f"{JOB}/a2", "its 'orphans' field is not"),
    "sol-no-flags": ({k: v for k, v in _session().items() if k != "flags"}, ATTEMPTS, f"{JOB}/a2",
                     "its 'flags' field is not"),
    "sol-thread-failed": (_edited(lambda s: s["threads"][2]["audit"].update(passed=False)), ATTEMPTS, f"{JOB}/a2",
                          "one thread's own audit failed"),
    "sol-thread-violation": (_edited(lambda s: s["threads"][2]["audit"].update(violations=[CALL])), ATTEMPTS,
                             f"{JOB}/a2", "one thread's own audit failed"),
    "sol-parent-gone": (_edited(lambda s: s["threads"][2].update(spawned_by="MOCK-gone")), ATTEMPTS, f"{JOB}/a2",
                        "one thread's parent is not among its threads"),
    "sol-spawns": (_edited(lambda s: s["threads"][1].update(functions={"spawn_agent": 2})), ATTEMPTS, f"{JOB}/a2",
                   "spawn_agent calls do not match"),
    "sol-all-but-main-dropped": (_edited(_drop_all_but_main), ATTEMPTS, f"{JOB}/a2", "spawn_agent calls do not match"),
    "sol-violation": ({**_session(), "violations": 1}, ATTEMPTS, f"{JOB}/a2", "its violations do not add up"),
    "sol-web-calls": ({**_session(), "web_calls": 99}, ATTEMPTS, f"{JOB}/a2", "its web_calls do not add up"),
    "sol-pages": ({**_session(), "served_pages": 1}, ATTEMPTS, f"{JOB}/a2", "its served_pages do not add up"),
    "sol-commands": ({**_session(), "commands": 2}, ATTEMPTS, f"{JOB}/a2", "its commands do not add up"),
    "sol-suspect-total": ({**_session(), "suspect": 5}, ATTEMPTS, f"{JOB}/a2", "its suspect do not add up"),
    "sol-no-main": ({**_session(), "main_thread": None}, ATTEMPTS, f"{JOB}/a2", "names no main thread among"),
    "sol-unknown-main": ({**_session(), "main_thread": "MOCK-unknown"}, ATTEMPTS, f"{JOB}/a2",
                         "names no main thread among"),
    "sol-first-attempt-main": ({**_session(), "main_thread": "MOCK-earlier"}, ATTEMPTS, f"{JOB}/a2",
                               "its main thread is not the thread the transcript records"),
    "sol-no-record": (_session(), None, f"{JOB}/a2", "it has no attempts on record and 2 main threads"),
    "sol-no-record-later-attempt": (_edited(lambda s: s["threads"].pop(0) and s.update(_totals(s["threads"]))),
                                    None, f"{JOB}/a2", "not its job's first attempt"),
    "sol-record-unparsable": (_session(), "{MOCK", f"{JOB}/a2", "its attempts.json is not a file of JSON this check"),
    "sol-record-no-list": (_session(), {**ATTEMPTS, "attempts": "MOCK"}, f"{JOB}/a2", "lists no attempts"),
    "sol-collected-other": ({**_session(), "collected_attempt": f"{JOB}/a1"}, ATTEMPTS, f"{JOB}/a2",
                            "not the attempt subfleet accepted and the audit names"),
    "sol-accepted-other": (_session(), {**ATTEMPTS, "accepted_attempt_id": f"{JOB}/a1"}, f"{JOB}/a2",
                           "not the attempt subfleet accepted and the audit names"),
    "sol-main-not-its-session": (_session(), {**ATTEMPTS, "attempts": [
        {"attempt_id": f"{JOB}/a1", "native_session_id": "MOCK-main", "started_at": "MOCK"},
        {"attempt_id": f"{JOB}/a2", "native_session_id": "MOCK-earlier", "started_at": "MOCK"}]}, f"{JOB}/a2",
        "its main thread is not the collected attempt's session"),
    "sol-attempt-lost": (_session(), {**ATTEMPTS, "attempts": [
        *ATTEMPTS["attempts"], {"attempt_id": f"{JOB}/a3", "native_session_id": "MOCK-lost", "started_at": "MOCK"}]},
        f"{JOB}/a2", "an attempt that started names no session among its threads"),
    "sol-attempt-without-session": (_session(), {**ATTEMPTS, "attempts": [
        *ATTEMPTS["attempts"], {"attempt_id": f"{JOB}/a3", "native_session_id": None, "started_at": "MOCK"}]},
        f"{JOB}/a2", "an attempt that started names no session among its threads"),
    "sol-stray-root": (_edited(_add_stray_root), ATTEMPTS, f"{JOB}/a2",
                       "a main thread among its threads is no attempt's session"),
    # Review finding 4: a graph of threads that is no tree from the main thread.
    "sol-thread-twice": (_session(threads=DUPLICATED), ATTEMPTS, f"{JOB}/a2", "two of its threads share an id"),
    "sol-loop": (_session(threads=LOOP), ATTEMPTS, f"{JOB}/a2", "its threads' parents form a cycle"),
    "sol-own-parent": (_session(threads=[*_session()["threads"], _thread("MOCK-self", "MOCK-self", spawns=1)]),
                       ATTEMPTS, f"{JOB}/a2", "its threads' parents form a cycle"),
    "sol-no-record-main-under-root": (_session(threads=UNDER_ROOT), None, f"{JOB}/a1", "its main thread is a sub-agent"),
    "sol-main-under-earlier": (_session(threads=UNDER_EARLIER), ATTEMPTS, f"{JOB}/a2",
                               "its main thread is a sub-agent"),
    # Review finding 5: a check of the transcript that is missing or found a difference.
    "sol-no-transcript-check": ({k: v for k, v in _session().items() if k != "transcript_check"}, ATTEMPTS,
                                f"{JOB}/a2", "its check of the transcript is missing or found calls that differ"),
    "sol-only-in-transcript": (_check(only_in_transcript=['"MOCK"']), ATTEMPTS, f"{JOB}/a2",
                               "its check of the transcript is missing or found calls that differ"),
    "sol-only-in-log": (_check(only_in_log=['"MOCK"']), ATTEMPTS, f"{JOB}/a2",
                        "its check of the transcript is missing or found calls that differ"),
    "sol-different": (_check(different=['"MOCK"']), ATTEMPTS, f"{JOB}/a2",
                      "its check of the transcript is missing or found calls that differ"),
    "sol-check-items-text": (_check(items="1"), ATTEMPTS, f"{JOB}/a2",
                             "its check of the transcript is missing or found calls that differ"),
    # Review finding 3: attempts that are not the job's a1, a2 and on, or that share or misplace a session.
    "sol-only-a2": (_edited(_drop_earlier), {**ATTEMPTS, "attempts": ATTEMPTS["attempts"][1:]}, f"{JOB}/a2",
                    f"does not list the attempts of job {JOB} from a1 up"),
    "sol-other-job": (_session(), {**ATTEMPTS, "job_id": "MOCK-other-job"}, f"{JOB}/a2",
                      f"does not list the attempts of job {JOB} from a1 up"),
    "sol-a1-twice": (_session(), {**ATTEMPTS, "attempts": [ATTEMPTS["attempts"][0], {
        **ATTEMPTS["attempts"][1], "attempt_id": f"{JOB}/a1"}]}, f"{JOB}/a2",
        f"does not list the attempts of job {JOB} from a1 up"),
    "sol-one-session-twice": (_edited(_drop_earlier), _attempts("MOCK-main", "MOCK-main"), f"{JOB}/a2",
                              "two attempts name the same session"),
    "sol-sub-agent-session": (_edited(_drop_earlier), _attempts("MOCK-helper", "MOCK-main"), f"{JOB}/a2",
                              "an attempt's session is a sub-agent, not a main thread"),
    # Review finding 8: ids that are not strings exclude the run instead of stopping the pooling.
    "sol-attempt-id-list": (_session(), {**ATTEMPTS, "attempts": [{**ATTEMPTS["attempts"][0], "attempt_id": []},
                                                                  ATTEMPTS["attempts"][1]]}, f"{JOB}/a2",
                            "gives an attempt an id or a session that is not a string"),
    "sol-session-list": (_session(), {**ATTEMPTS, "attempts": [{**ATTEMPTS["attempts"][0], "native_session_id": []},
                                                               ATTEMPTS["attempts"][1]]}, f"{JOB}/a2",
                         "gives an attempt an id or a session that is not a string"),
    # The sixth round: fields the gate took on trust.
    "sol-other-workdir": ({**_session(), "workdir": "/MOCK/elsewhere"}, ATTEMPTS, f"{JOB}/a2",
                          "it does not audit the run's work directory"),
    "sol-no-workdir": ({k: v for k, v in _session().items() if k != "workdir"}, ATTEMPTS, f"{JOB}/a2",
                       "it does not audit the run's work directory"),
    # The seventh round: a thread's audit that read no events, a count or mark of another type.
    "sol-no-events": (_edited(lambda s: s["threads"][2]["audit"].update(events=0)), ATTEMPTS, f"{JOB}/a2",
                      "one thread's own audit failed"),
    "sol-events-text": (_edited(lambda s: s["threads"][2]["audit"].update(events="2")), ATTEMPTS, f"{JOB}/a2",
                        "one thread's own audit failed"),
    "sol-no-events-field": (_edited(lambda s: s["threads"][2]["audit"].pop("events")), ATTEMPTS, f"{JOB}/a2",
                            "one thread's own audit failed"),
    "sol-events-bool": (_edited(lambda s: s["threads"][2]["audit"].update(events=True)), ATTEMPTS, f"{JOB}/a2",
                        "one thread's own audit failed"),
    "sol-bool-item": (_edited(lambda s: s["threads"][2]["items"].update({"Extension:web.search": True})), ATTEMPTS,
                      f"{JOB}/a2", "one thread's counts are not whole numbers of zero or more"),
    "sol-collected-number": (_edited(lambda s: s["threads"][2].update(collected=1)), ATTEMPTS, f"{JOB}/a2",
                             "one thread is marked collected though it does not descend from the main thread"),
    "sol-negative-web-calls": (_edited(lambda s: (s["threads"][0]["audit"].update(web_calls=-1),
                                                  s["threads"][1]["audit"].update(web_calls=3))), ATTEMPTS,
                               f"{JOB}/a2", "its web_calls do not add up"),
    "sol-negative-pages": (_edited(lambda s: (s["threads"][0].update(served_pages=-2),
                                              s["threads"][1].update(served_pages=6))), ATTEMPTS, f"{JOB}/a2",
                           "its served_pages do not add up"),
    "sol-negative-commands": (_edited(lambda s: (s["threads"][0]["items"].update(CommandExecution=-1),
                                                 s["threads"][1]["items"].update(CommandExecution=1))), ATTEMPTS,
                              f"{JOB}/a2", "one thread's counts are not whole numbers of zero or more"),
    "sol-negative-item": (_edited(lambda s: s["threads"][2]["items"].update({"Extension:web.search": -1})), ATTEMPTS,
                          f"{JOB}/a2", "one thread's counts are not whole numbers of zero or more"),
    "sol-no-script-tools": (_edited(lambda s: s["threads"][2].pop("script_tools")), ATTEMPTS, f"{JOB}/a2",
                            "one thread's counts are not whole numbers of zero or more"),
    "sol-function-negative": (_edited(lambda s: s["threads"][2]["functions"].update(wait_agent=-1)), ATTEMPTS,
                              f"{JOB}/a2", "one thread's counts are not whole numbers of zero or more"),
    "sol-check-items-negative": (_check(items=-1), ATTEMPTS, f"{JOB}/a2",
                                 "its check of the transcript is missing or found calls that differ"),
    "sol-other-job-named": ({**_session(), "job_id": "MOCK-other-job"}, ATTEMPTS, f"{JOB}/a2",
                            f"it names job MOCK-other-job, not the run's job {JOB}"),
    "sol-no-job-named": ({k: v for k, v in _session().items() if k != "job_id"}, ATTEMPTS, f"{JOB}/a2",
                         f"it names job None, not the run's job {JOB}"),
    "sol-helper-not-collected": (_edited(lambda s: s["threads"][2].update(collected=False)), ATTEMPTS, f"{JOB}/a2",
                                 "one thread is marked collected though it does not descend from the main thread"),
    "sol-earlier-collected": (_edited(lambda s: s["threads"][0].update(collected=True)), ATTEMPTS, f"{JOB}/a2",
                              "one thread is marked collected though it does not descend from the main thread"),
    "sol-helper-other-attempt": (_edited(lambda s: s["threads"][2].update(attempt=f"{JOB}/a1")), ATTEMPTS,
                                 f"{JOB}/a2", "one thread names an attempt other than the one whose session"),
    "sol-no-record-attempt-named": (_session(threads=[{**_thread("MOCK-main", None, spawns=1), "attempt": f"{JOB}/a1"},
                                                      _thread("MOCK-helper", "MOCK-main")]), None, f"{JOB}/a1",
                                    "one thread names an attempt other than the one whose session"),
    # The eighth round: fields of a thread that contradict each other or the script's rules.
    "sol-script-tool-unknown": (_edited(lambda s: s["threads"][2]["script_tools"].update(read_file=1)), ATTEMPTS,
                                f"{JOB}/a2", "one thread records an item, a script's tool or a function for which"),
    "sol-function-unknown": (_edited(lambda s: s["threads"][2]["functions"].update(MOCK_function=1)), ATTEMPTS,
                             f"{JOB}/a2", "one thread records an item, a script's tool or a function for which"),
    "sol-item-unknown": (_edited(lambda s: s["threads"][2]["items"].update(MOCKItem=1)), ATTEMPTS, f"{JOB}/a2",
                         "one thread records an item, a script's tool or a function for which"),
    "sol-extension-unknown": (_edited(lambda s: s["threads"][2]["items"].update({"Extension:MOCK": 1})), ATTEMPTS,
                              f"{JOB}/a2", "one thread records an item, a script's tool or a function for which"),
    "sol-exec-without-command": (_edited(lambda s: s["threads"][2]["script_tools"].update(exec_command=1)), ATTEMPTS,
                                 f"{JOB}/a2", "one thread's scripts call the shell more often than its commands"),
    "sol-search-added": (_edited(lambda s: s["threads"][2]["items"].update({"Extension:web.search": 2})), ATTEMPTS,
                         f"{JOB}/a2", "one thread's audit counts other events or calls than its items make"),
    "sol-message-added": (_edited(lambda s: s["threads"][2]["items"].update(AgentMessage=2)), ATTEMPTS, f"{JOB}/a2",
                          "one thread's audit counts other events or calls than its items make"),
    "sol-events-added": (_edited(lambda s: s["threads"][2]["audit"].update(events=3)), ATTEMPTS, f"{JOB}/a2",
                         "one thread's audit counts other events or calls than its items make"),
    "sol-tool-calls": (_edited(lambda s: s["threads"][2]["audit"].update(tool_calls=2)), ATTEMPTS, f"{JOB}/a2",
                       "one thread's audit counts other events or calls than its items make"),
    "sol-tool-calls-bool": (_edited(lambda s: s["threads"][2]["audit"].update(tool_calls=True)), ATTEMPTS, f"{JOB}/a2",
                            "one thread's audit counts other events or calls than its items make"),
    "sol-web-calls-over": (_edited(lambda s: (s["threads"][2]["audit"].update(web_calls=2),
                                              s.update(web_calls=s["web_calls"] + 1))), ATTEMPTS, f"{JOB}/a2",
                           "one thread's audit lists more calls than it read"),
    "sol-local-call-over": (_edited(lambda s: s["threads"][2]["audit"].update(local_calls=[CALL])), ATTEMPTS,
                            f"{JOB}/a2", "one thread's audit lists more calls than it read"),
    "sol-no-urls": (_edited(lambda s: s["threads"][2]["audit"].update(urls=[])), ATTEMPTS, f"{JOB}/a2",
                    "or web addresses that do not match its web calls"),
    "sol-urls-unsorted": (_edited(lambda s: s["threads"][2]["audit"].update(urls=["MOCK b", "MOCK a"])), ATTEMPTS,
                          f"{JOB}/a2", "or web addresses that do not match its web calls"),
    "sol-sub-agent-events": (_edited(lambda s: s["threads"][1]["items"].pop("SubAgentActivity")), ATTEMPTS,
                             f"{JOB}/a2", "one thread records fewer sub-agent events than the threads that name it"),
    "sol-check-items-zero": (_check(items=0), ATTEMPTS, f"{JOB}/a2",
                             "its check of the transcript compared another number of items than"),
    "sol-check-items-two": (_check(items=2), ATTEMPTS, f"{JOB}/a2",
                            "its check of the transcript compared another number of items than"),
    "sol-check-extra-field": (_check(MOCK=[]), ATTEMPTS, f"{JOB}/a2",
                              "its check of the transcript has other fields than the script writes"),
    "sol-thread-extra-field": (_edited(lambda s: s["threads"][2].update(MOCK=1)), ATTEMPTS, f"{JOB}/a2",
                               "one thread's entry or its audit has other fields than the script writes"),
    "sol-thread-no-file": (_edited(lambda s: s["threads"][2].pop("file")), ATTEMPTS, f"{JOB}/a2",
                           "one thread's entry or its audit has other fields than the script writes"),
    "sol-audit-extra-field": (_edited(lambda s: s["threads"][2]["audit"].update(MOCK=1)), ATTEMPTS, f"{JOB}/a2",
                              "one thread's entry or its audit has other fields than the script writes"),
    "sol-audit-no-urls": (_edited(lambda s: s["threads"][2]["audit"].pop("urls")), ATTEMPTS, f"{JOB}/a2",
                          "one thread's entry or its audit has other fields than the script writes"),
    "sol-file-elsewhere": (_edited(lambda s: s["threads"][2].update(file="/MOCK/rollout-MOCK.jsonl")), ATTEMPTS,
                           f"{JOB}/a2", "one thread gives an agent path, a start time, a file or a SHA-256"),
    "sol-file-up": (_edited(lambda s: s["threads"][2].update(file="codex-sessions/../rollout-MOCK.jsonl")), ATTEMPTS,
                    f"{JOB}/a2", "one thread gives an agent path, a start time, a file or a SHA-256"),
    "sol-sha-short": (_edited(lambda s: s["threads"][2].update(sha256="0" * 63)), ATTEMPTS, f"{JOB}/a2",
                      "one thread gives an agent path, a start time, a file or a SHA-256"),
    "sol-agent-path-list": (_edited(lambda s: s["threads"][2].update(agent_path=["MOCK"])), ATTEMPTS, f"{JOB}/a2",
                            "one thread gives an agent path, a start time, a file or a SHA-256"),
    "sol-started-number": (_edited(lambda s: s["threads"][2].update(started=1)), ATTEMPTS, f"{JOB}/a2",
                           "one thread gives an agent path, a start time, a file or a SHA-256"),
    "sol-suspect-extra-field": (_session(earlier=[{**CALL, "MOCK": "MOCK"}]), ATTEMPTS, f"{JOB}/a2",
                                "one thread lists a call other than as the audits list one"),
    "sol-suspect-call-number": (_session(earlier=[{**CALL, "call": 1}]), ATTEMPTS, f"{JOB}/a2",
                                "one thread lists a call other than as the audits list one"),
    "sol-script-suspect-no-why": (_session(script=[{"tool": "exec script", "call": "MOCK"}]), ATTEMPTS, f"{JOB}/a2",
                                  "one thread lists a call other than as the audits list one"),
    "sol-local-call-number": (_edited(lambda s: s["threads"][2]["audit"].update(local_calls=[{"tool": "shell",
                                                                                              "call": 1}])),
                              ATTEMPTS, f"{JOB}/a2", "one thread lists a call other than as the audits list one"),
    "sol-extra-field": ({**_session(), "MOCK": 1}, ATTEMPTS, f"{JOB}/a2", "it has other fields than the script writes"),
    "sol-suspect-over": (_edited(lambda s: (s["threads"][2]["audit"]["suspect"].append(CALL),
                                            s.update(suspect=s["suspect"] + 1))), ATTEMPTS, f"{JOB}/a2",
                         "one thread's audit lists more calls than it read"),
    "sol-urls-twice": (_edited(lambda s: s["threads"][2]["audit"].update(urls=["https://www.example.org/MOCK"] * 2)),
                       ATTEMPTS, f"{JOB}/a2", "or web addresses that do not match its web calls"),
    "sol-urls-without-web-calls": (_edited(lambda s: (s["threads"][2]["audit"].update(web_calls=0),
                                                      s.update(web_calls=s["web_calls"] - 1))), ATTEMPTS, f"{JOB}/a2",
                                   "or web addresses that do not match its web calls"),
    # Mutants that outlived the cases above: a file whose path climbs out through a folder under the kept
    # logs, a call with no tool or no call, and a script's call that is not text.
    "sol-file-up-from-a-folder": (_edited(lambda s: s["threads"][2].update(
        file="codex-sessions/rollout-MOCK/../../rollout-MOCK.jsonl")), ATTEMPTS, f"{JOB}/a2",
        "one thread gives an agent path, a start time, a file or a SHA-256"),
    "sol-suspect-no-tool": (_session(earlier=[{"call": CALL["call"], "why": CALL["why"]}]), ATTEMPTS, f"{JOB}/a2",
                            "one thread lists a call other than as the audits list one"),
    "sol-suspect-no-call": (_session(earlier=[{"tool": CALL["tool"], "why": CALL["why"]}]), ATTEMPTS, f"{JOB}/a2",
                            "one thread lists a call other than as the audits list one"),
    "sol-script-suspect-call-number": (_session(script=[{**CALL, "call": 1}]), ATTEMPTS, f"{JOB}/a2",
                                       "one thread lists a call other than as the audits list one"),
}


def test_a_codex_run_is_pooled_only_with_a_passing_audit_of_its_session_logs(area, graph, capsys):
    """A Codex run's transcript omits its sub-agents and earlier attempts, so its session logs' audit
    gates it too."""
    _accepted_run(graph, "opus")  # no Codex lane, so no session logs to audit
    _codex_run(graph, "sol-ok", _session())
    _codex_run(graph, "sol-reasoning", _edited(_with_reasoning))
    _codex_run(graph, "sol-main-command", _edited(_with_main_command))
    _codex_run(graph, "sol-never-started", _session(), attempts={**ATTEMPTS, "attempts": [
        *ATTEMPTS["attempts"], {"attempt_id": f"{JOB}/a3", "native_session_id": None, "started_at": None}]})
    _codex_run(graph, "sol-none", None)
    _codex_run(graph, "sol-failed", _session(passed=False))
    _codex_run(graph, "sol-odd", _session(helper=[CALL, CALL]))
    _codex_run(graph, "sol-main", _session(main=[CALL]), suspect=[CALL])
    _codex_run(graph, "sol-hidden", _session(main=[CALL]))  # only the session logs show the main thread's call
    _codex_run(graph, "sol-earlier", _session(earlier=[CALL]))
    _codex_run(graph, "sol-script", _session(main=[CALL], script=[OTHER]), suspect=[CALL])
    unreadable = {
        "sol-bad": {"passed": True},  # not a session audit: it lists no threads
        "sol-passed-text": {**_session(), "passed": "false"},
        "sol-passed-missing": {k: v for k, v in _session().items() if k != "passed"},
        "sol-other-run": {**_session(), "run": "sol-ok"},
        "sol-no-script-list": {**_session(), "threads": [{k: v for k, v in t.items() if k != "script_suspect"}
                                                         for t in _session()["threads"]]},
        "sol-call-not-object": _session(helper=["MOCK call"]),
        "sol-audit-not-object": {**_session(), "threads": [{**t, "audit": ["MOCK"]} for t in _session()["threads"]]},
        # Review finding 8: a thread's id or its parent's that is not a string.
        "sol-thread-id-list": {**_session(), "threads": [*_session()["threads"][:2], {**_session()["threads"][2],
                                                                                       "thread_id": []}]},
        "sol-thread-id-missing": {**_session(), "threads": [*_session()["threads"][:2], {
            k: v for k, v in _session()["threads"][2].items() if k != "thread_id"}]},
        "sol-parent-list": {**_session(), "threads": [*_session()["threads"][:2], {**_session()["threads"][2],
                                                                                    "spawned_by": []}]},
    }
    for label, session in unreadable.items():
        _codex_run(graph, label, session)
    for label, (session, attempts, collected, _) in INCONSISTENT.items():
        _codex_run(graph, label, session, attempts=attempts, collected=collected)
    _codex_run(graph, "sol-not-json-run", None)
    (runners.RUNS / "sol-not-json-run" / "codex-sessions").mkdir()
    (runners.RUNS / "sol-not-json-run" / "codex-sessions" / "audit.json").write_text("{MOCK")
    assert set(cli.accepted_runs(graph, "sha")) == {"opus", "sol-ok", "sol-reasoning", "sol-main-command",
                                                    "sol-never-started"}
    err = capsys.readouterr().err
    for label in ["sol-none", "sol-not-json-run", *unreadable]:
        assert f"excluding {label}: no readable audit of its session logs" in err
    lines = {line.split(":")[0]: line for line in err.splitlines()}
    for label, (_, _, _, reason) in INCONSISTENT.items():
        line = lines[f"excluding {label}"]
        assert line.startswith(f"excluding {label}: the audit of its session logs says it passed, but ")
        assert reason in line, label
    assert "excluding sol-failed: the audit of its session logs failed" in err
    assert "excluding sol-odd: 2 suspect call(s)" in err
    assert "excluding sol-main: 1 suspect call(s)" in err  # the main thread's call counts once
    assert "excluding sol-hidden: 1 suspect call(s)" in err
    assert "excluding sol-earlier: 1 suspect call(s)" in err  # an earlier attempt's thread counts
    assert "excluding sol-script: 2 suspect call(s)" in err  # a script's call counts beside its item's
    accept = {"sol-odd", "sol-main", "sol-hidden", "sol-earlier", "sol-script", "sol-none", "sol-failed",
              *unreadable, *INCONSISTENT}
    assert set(cli.accepted_runs(graph, "sha", accept_suspect=accept)) == {
        "opus", "sol-ok", "sol-reasoning", "sol-main-command", "sol-never-started", "sol-odd", "sol-main", "sol-hidden",
        "sol-earlier", "sol-script"}


@pytest.mark.parametrize("name", ["audit.json", "attempts.json"])
@pytest.mark.parametrize("kind", ["a folder", "a pipe", "a link to nothing", "empty", "cut", "not UTF-8",
                                  "nested too deeply", pytest.param("no permission to read it", marks=pytest.mark.skipif(
                                      os.geteuid() == 0, reason="root reads any file"))])
def test_a_record_that_is_no_regular_file_of_json_excludes_the_run(area, graph, capsys, name, kind):
    """Review 6: the gate reads a run's records without stopping `simulate`. A folder, a pipe (whose read
    would wait for a writer forever), a link to nothing, an empty or cut file, bytes that are not UTF-8,
    JSON nested past 64 levels and a file the system will not let it read each exclude the run, with
    the reason."""
    _codex_run(graph, "sol-odd", _session())
    _codex_run(graph, "sol-ok", _session())
    path = runners.RUNS / "sol-odd" / "codex-sessions" / name
    path.unlink()
    {"a folder": path.mkdir, "a pipe": lambda: os.mkfifo(path),
     "a link to nothing": lambda: path.symlink_to(path.with_name("MOCK-gone")), "empty": lambda: path.write_text(""),
     "cut": lambda: path.write_text('{"attempts":'), "not UTF-8": lambda: path.write_bytes(b'{"MOCK": "\xff"}'),
     "nested too deeply": lambda: path.write_text("[" * 65 + "]" * 65),
     "no permission to read it": lambda: (path.write_text("{}"), path.chmod(0))}[kind]()
    assert set(cli.accepted_runs(graph, "sha")) == {"sol-ok"}
    assert ("excluding sol-odd: no readable audit of its session logs" if name == "audit.json" else
            "excluding sol-odd: the audit of its session logs says it passed, but its attempts.json is not a file of "
            "JSON this check can read") in capsys.readouterr().err


@pytest.mark.parametrize("workdir", [None, "", "MOCK/work/sol", ["/MOCK/work/sol"]],
                         ids=["none", "empty", "relative", "a list"])
def test_a_run_whose_work_directory_is_not_an_absolute_path_is_excluded(area, graph, capsys, workdir):
    """The gate pools a Codex run only when its audit read the run's own work directory, an absolute
    path, as the script reads one; an audit that records the same odd value does not pass."""
    _codex_run(graph, "sol-odd-workdir", {**_session(), "workdir": workdir}, workdir=workdir)
    _codex_run(graph, "sol-ok", _session())
    assert set(cli.accepted_runs(graph, "sha")) == {"sol-ok"}
    assert ("excluding sol-odd-workdir: the audit of its session logs says it passed, but it does not audit the "
            "run's work directory") in capsys.readouterr().err


def test_a_transcript_thread_id_that_is_not_a_string_names_no_thread(area, graph, capsys):
    """A transcript whose `thread.started` event gives a number names no thread, though Python writes
    that number as the main thread's id."""
    session = _session(threads=[_thread("7", None, spawns=1), _thread("MOCK-helper", "7")], main_thread="7")
    _codex_run(graph, "sol-number", session, attempts=None, collected=f"{JOB}/a1", thread=7)
    _codex_run(graph, "sol-text", session, attempts=None, collected=f"{JOB}/a1", thread="7")
    assert set(cli.accepted_runs(graph, "sha")) == {"sol-text"}
    assert ("excluding sol-number: the audit of its session logs says it passed, but its main thread is not the "
            "thread the transcript records") in capsys.readouterr().err


def test_a_record_that_names_a_job_with_no_attempts_on_record_is_excluded(area, graph, capsys):
    """The script names the job and the collected attempt only from their record, so a record that
    names them with no attempts.json beside it is not one the script wrote."""
    session = _session(threads=[_thread("MOCK-main", None, spawns=1), _thread("MOCK-helper", "MOCK-main")])
    _codex_run(graph, "sol-plain", session, attempts=None, collected=f"{JOB}/a1")
    _codex_run(graph, "sol-named", session, attempts=None, collected=f"{JOB}/a1")
    path = runners.RUNS / "sol-named" / "codex-sessions" / "audit.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "job_id": JOB, "collected_attempt": f"{JOB}/a1"}))
    assert set(cli.accepted_runs(graph, "sha")) == {"sol-plain"}
    assert ("excluding sol-named: the audit of its session logs says it passed, but it has other fields than the "
            "script writes") in capsys.readouterr().err


@pytest.mark.parametrize("levels, accepted", [(64, True), (65, False)])
def test_a_transcript_names_its_thread_only_on_a_line_nested_at_most_64_levels(area, graph, capsys, levels, accepted):
    """As the script reads a transcript, a line nested more than 64 levels is no event, so a transcript
    whose one `thread.started` line nests deeper names no thread."""
    session = _session(threads=[_thread("MOCK-main", None, spawns=1), _thread("MOCK-helper", "MOCK-main")])
    _codex_run(graph, "sol-deep", session, attempts=None, collected=f"{JOB}/a1")
    nested = "[" * (levels - 1) + "]" * (levels - 1)
    (runners.RUNS / "sol-deep" / "transcript.jsonl").write_text(
        '{"type": "thread.started", "thread_id": "MOCK-main", "MOCK": ' + nested + "}\n")
    assert set(cli.accepted_runs(graph, "sha")) == ({"sol-deep"} if accepted else set())
    assert ("its main thread is not the thread the transcript records" in capsys.readouterr().err) is not accepted


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


def test_the_runs_note_names_what_only_the_session_logs_record(graph):
    """The note under the runs table names each thing the session-log audit adds to a Codex run's count,
    and the committed summary carries the note the report writes now."""
    result = pool(graph, {"MOCK": parse(graph, MOCK_response(graph))}, n=200, seed=86)
    note = next(line for line in report.markdown(graph, result, {}).splitlines()
                if line.startswith("'Same at every cell'"))
    for source in ("the calls of its sub-agents", "its earlier attempts", "its scripts",
                   "the pages the web tool served (`codex-sessions/audit.json`)"):
        assert source in note
    assert note in (Path(__file__).resolve().parents[1] / "outputs/summary.md").read_text().splitlines()


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
       main=st.integers(0, 3), transcript=st.integers(0, 3), passed=st.booleans(), accept=st.booleans())
def test_the_gate_admits_and_counts_as_its_rule_says(graph, threads, main, transcript, passed, accept):
    """Property (differential against the rule written out): a Codex run whose session audit holds up
    is pooled exactly when that audit passed and the run has no suspect call or the reader accepted it;
    its count is the main thread's item calls as the longer of its two audits lists them, plus that
    thread's script calls and every call of every other thread; and `simulate` reports that count."""
    main %= len(threads)
    rows = [_thread(f"MOCK-{i}", None if i == main else f"MOCK-{main}", [CALL] * items, [OTHER] * scripts,
                    spawns=len(threads) - 1 if i == main else 0) for i, (items, scripts) in enumerate(threads)]
    if not passed:
        rows[main]["audit"].update(passed=False, violations=[CALL])
    session = _session(passed, threads=rows, main_thread=f"MOCK-{main}")
    expected = (max(transcript, threads[main][0]) + threads[main][1]
                + sum(items + scripts for i, (items, scripts) in enumerate(threads) if i != main))
    pooled = passed and (expected == 0 or accept)
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        mp.setattr(runners, "RUNS", Path(tmp) / "runs")
        _codex_run(graph, "sol-1", session, suspect=[CALL] * transcript, attempts=None, collected=f"{JOB}/a1",
                   thread=f"MOCK-{main}")
        accepted = {"sol-1"} if accept else set()
        assert set(cli.accepted_runs(graph, "sha", accept_suspect=accepted)) == ({"sol-1"} if pooled else set())
        assert len(cli._codex_suspects([CALL] * transcript, {"run": "sol-1", **session})) == expected
        if pooled:
            assert _simulated_counts(graph, mp, accepted) == {"sol-1": expected}


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(parents=st.lists(st.none() | st.integers(0, 5), min_size=1, max_size=6), main=st.integers(0, 5),
       twice=st.booleans())
def test_the_gate_admits_a_thread_graph_only_as_one_tree_from_its_main_thread(graph, parents, main, twice):
    """Property (against the rule restated, review finding 4): with no attempts on record, the gate
    pools a run whose session audit passed exactly when its threads have ids of their own and each
    descends with no cycle from the one thread with no parent, the thread its transcript records."""
    up = [None if p is None else p % len(parents) for p in parents]
    main %= len(parents)
    rows = [_thread(f"MOCK-{i}", None if p is None else f"MOCK-{p}", spawns=up.count(i)) for i, p in enumerate(up)]
    if twice:
        rows.append(dict(rows[-1]))
    session = _session(threads=rows, main_thread=f"MOCK-{main}")

    def descends(i: int) -> bool:
        seen = set()
        while up[i] is not None:
            if i in seen:
                return False
            seen.add(i)
            i = up[i]
        return True

    admitted = not twice and all(map(descends, range(len(up)))) and [i for i, p in enumerate(up) if p is None] == [main]
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        mp.setattr(runners, "RUNS", Path(tmp) / "runs")
        _codex_run(graph, "sol-1", session, attempts=None, collected=f"{JOB}/a1", thread=f"MOCK-{main}")
        assert set(cli.accepted_runs(graph, "sha")) == ({"sol-1"} if admitted else set())


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
