"""scripts/audit_codex_sessions.py finds every Codex thread behind a run, ties each main thread to a
subfleet attempt, keeps its log and audits it. MOCK session logs, transcripts and subfleet records in
temporary directories; the tests never run subfleet or any other command."""

import importlib.util
import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

spec = importlib.util.spec_from_file_location(
    "audit_codex_sessions", Path(__file__).parent.parent / "scripts" / "audit_codex_sessions.py")
acs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acs)

PARENT, HELPER = "MOCK-parent-thread", "MOCK-helper-thread"
EARLIER, EARLIER_HELPER = "MOCK-earlier-thread", "MOCK-earlier-helper-thread"
JOB = "MOCK-job-sol-1"


def write_log(lanes: Path, name: str, meta: dict, items=(), records=()) -> Path:
    path = lanes / "codex-9" / "sessions" / "2026" / "11" / "03" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "session_meta", "payload": meta}, *records]
    lines += [{"type": "event_msg", "payload": {"type": "item_completed", "item": it}} for it in items]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def started(thread: str) -> dict:
    return {"type": "SubAgentActivity", "kind": "started", "agent_thread_id": thread}


def search(query: str, action: dict | None = None) -> dict:
    """A web search as a session log records it."""
    return {"type": "Extension", "kind": "web.search", "id": f"MOCK-{query}", "query": query,
            "action": action or {"type": "search", "queries": [query]}, "results": []}


def web(query: str, action: dict | None = None) -> dict:
    """The same web search as `codex exec --json` writes it in a transcript."""
    return {"id": f"MOCK-{query}", "type": "web_search", "query": query,
            "action": action or {"type": "search", "queries": [query]}, "results": []}


def command(cmd: str, cwd: str) -> dict:
    return {"type": "CommandExecution", "id": f"MOCK-{cmd}", "command": ["/bin/zsh", "-lc", cmd],
            "cwd": f"file://{cwd}", "status": "completed", "exit_code": 0, "aggregated_output": ""}


def exec_call(code: str) -> dict:
    return {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": code}}


def tool_output(text: str, kind: str = "custom_tool_call_output") -> dict:
    """A script's result (or, as a function_call_output, a running cell's that `wait` returns)."""
    return {"type": "response_item", "payload": {"type": kind, "output": [{"type": "input_text", "text": text}]}}


def served(url: str, ref: str = "turn0view0") -> str:
    """A page as the web tool's reply cites it."""
    return f"MOCK page ({url})\ncite{ref} [wordlim: 200] MOCK text"


def function_call(name: str) -> dict:
    return {"type": "response_item", "payload": {"type": "function_call", "name": name, "arguments": "{}"}}


def root_meta(workdir: str, thread: str = PARENT, timestamp: str = "2026-11-03T18:10:00Z") -> dict:
    return {"id": thread, "cwd": workdir, "source": "exec", "timestamp": timestamp}


def helper_meta(workdir: str, thread: str = HELPER, parent: str = PARENT,
                timestamp: str = "2026-11-03T18:10:30Z") -> dict:
    return {"id": thread, "cwd": workdir, "timestamp": timestamp,
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1,
                                                     "agent_path": "/root/MOCK_research"}}}}


def write_transcript(run: Path, thread: str, items=()) -> None:
    """A MOCK `codex exec --json` transcript of one thread and its items."""
    lines = [{"type": "thread.started", "thread_id": thread}, {"type": "turn.started"}]
    for it in items:
        lines += [{"type": "item.started", "item": it}, {"type": "item.completed", "item": it}]
    lines.append({"type": "turn.completed"})
    (run / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


@pytest.fixture
def area(tmp_path, monkeypatch):
    """A MOCK collected Codex run with no attempts on record, its transcript, and a log from an
    unrelated job in the lanes. No test may start a process."""
    def no_process(*args, **kwargs):
        raise AssertionError(f"the tests run no command: {args}")

    monkeypatch.setattr(acs.subprocess, "run", no_process)
    workdir = str(tmp_path / "work" / "sol-1")
    Path(workdir).mkdir(parents=True)
    run = tmp_path / "runs" / "sol-1"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"label": "sol-1", "workdir": workdir, "lane_id": "codex-9"}))
    (run / "response.md").write_text("MOCK answer\n")
    write_transcript(run, PARENT, [web("MOCK main query")])
    monkeypatch.setattr(acs, "RUNS", tmp_path / "runs")
    lanes = tmp_path / "lanes"
    write_log(lanes, "rollout-MOCK-other.jsonl", root_meta(str(tmp_path / "elsewhere"), "MOCK-other",
                                                           "2026-11-03T18:00:00Z"),
              items=[command("cat /etc/hosts", str(tmp_path / "elsewhere"))])
    return lanes, run, workdir


def add_parent(lanes: Path, workdir: str, spawned=(HELPER,), records=(), items=None) -> Path:
    items = [search("MOCK main query")] if items is None else items
    return write_log(lanes, "rollout-MOCK-parent.jsonl", root_meta(workdir), records=records,
                     items=[*items, *[started(t) for t in spawned]])


def with_record(monkeypatch, run: Path, attempts, accepted: str = f"{JOB}/a2", collected: str = f"{JOB}/a2"):
    """Give the MOCK run a subfleet job whose attempts are (attempt id, session, state)."""
    meta = json.loads((run / "meta.json").read_text())
    meta.update(job_id=JOB, attempt_id=collected)
    (run / "meta.json").write_text(json.dumps(meta))
    record = {"job": {"accepted_attempt_id": accepted},
              "attempts": [{"attempt_id": aid, "native_session_id": sid, "state": state, "lane_id": "codex-9"}
                           for aid, sid, state in attempts]}
    monkeypatch.setattr(acs, "subfleet_record", lambda job: record if job == JOB else None)
    return record


def add_earlier_attempt(lanes: Path, workdir: str, helper_items=()) -> None:
    """A failed first attempt in the same work directory: its main thread and one sub-agent."""
    write_log(lanes, "rollout-MOCK-earlier.jsonl", root_meta(workdir, EARLIER, "2026-11-03T18:00:00Z"),
              items=[search("MOCK earlier query"), started(EARLIER_HELPER)])
    write_log(lanes, "rollout-MOCK-earlier-helper.jsonl",
              helper_meta(workdir, EARLIER_HELPER, EARLIER, "2026-11-03T18:00:30Z"),
              items=[search("MOCK earlier helper query"), *helper_items])


TWO_ATTEMPTS = [(f"{JOB}/a1", EARLIER, "failed"), (f"{JOB}/a2", PARENT, "succeeded")]


def test_the_main_thread_and_its_sub_agents_are_kept_and_audited(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
              items=[search("MOCK helper query"), command("echo MOCK", workdir)])
    report = acs.audit_run(run, lanes)
    assert {t["thread_id"] for t in report["threads"]} == {PARENT, HELPER}
    assert report["missing"] == [] and report["flags"] == [] and report["passed"]
    assert report["web_calls"] == 2 and report["commands"] == 1
    assert report["main_thread"] == PARENT and report["transcript_check"]["items"] == 1
    assert (run / "codex-sessions" / "rollout-MOCK-helper.jsonl").is_file()
    assert not (run / "codex-sessions" / "rollout-MOCK-other.jsonl").exists()
    assert json.loads((run / "codex-sessions" / "audit.json").read_text())["passed"]


def test_a_spawned_thread_with_no_log_fails(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(HELPER, "MOCK-lost-thread"))
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["missing"] == ["MOCK-lost-thread"] and not report["passed"]


def test_a_sub_agent_reading_the_repository_fails_the_audit(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
              items=[command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    report = acs.audit_run(run, lanes)
    helper = next(t for t in report["threads"] if t["thread_id"] == HELPER)
    assert helper["audit"]["violations"] and not report["passed"]


def test_tools_records_and_places_the_script_does_not_read_are_flagged(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    records = [exec_call("text(await tools.read_file({path: 'MOCK'}))"),
               function_call("MOCK_shell"),
               {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "MOCK_tool", "input": ""}},
               {"type": "MOCK_record", "payload": {}},
               {"type": "event_msg", "payload": {"type": "MOCK_event"}},
               {"type": "response_item", "payload": {"type": "MOCK_response_item"}}]
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), records=records,
              items=[command("echo MOCK", "/MOCK/elsewhere"), {"type": "MOCKItem", "id": "MOCK"},
                     {"type": "Extension", "kind": "MOCK.kind", "id": "MOCK-extension"}])
    report = acs.audit_run(run, lanes)
    flags = " ".join(report["flags"])
    for expected in ("tools.read_file", "'MOCK_shell'", "'MOCK_tool'", "'MOCK_record'", "'MOCK_event'",
                     "'MOCK_response_item'", "outside the work directory", "'MOCKItem'", "'Extension'"):
        assert expected in flags
    assert not report["passed"]


def test_code_modes_wait_and_the_sub_agent_tools_are_read(area):
    lanes, run, workdir = area
    names = ["spawn_agent", "send_message", "followup_task", "wait_agent", "interrupt_agent", "list_agents", "wait"]
    add_parent(lanes, workdir, spawned=(), records=[function_call(name) for name in names])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["passed"]
    assert report["threads"][0]["functions"] == {name: 1 for name in names}


def test_a_rerun_after_the_lane_prunes_its_logs_audits_the_kept_copies(area):
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir)
    helper = write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    assert acs.audit_run(run, lanes)["passed"]
    first = (run / "codex-sessions" / "audit.json").read_bytes()
    parent.unlink()
    helper.unlink()
    assert acs.audit_run(run, lanes)["passed"]
    assert (run / "codex-sessions" / "audit.json").read_bytes() == first


def test_a_kept_log_is_final(area):
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    assert acs.audit_run(run, lanes)["passed"]
    with parent.open("a") as fh:
        fh.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}) + "\n")
    with pytest.raises(SystemExit, match="the kept copy is final"):
        acs.audit_run(run, lanes)


def test_a_plain_web_script_passes(area):
    lanes, run, workdir = area
    code = ('text(await tools.web__run({search_query: [{q: "MOCK query"}], '
            'open: [{ref_id: "https://www.example.org/MOCK"}, {ref_id: "turn0search1"}]}))')
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["suspect"] == 0 and report["passed"]
    assert report["threads"][0]["script_tools"] == {"web__run": 1}


@pytest.mark.parametrize("code", [
    'text(await tools["web__run"]({search_query: [{q: "MOCK"}]}))',
    'text(await tools .mcp__codex_apps__github_fetch_file({path: "MOCK"}))',
    'text(await tools\n.web__run({}))',
    'text(await tools?.web__run({}))',
    'text(await tools/* MOCK */.web__run({}))',
    'const t = tools; text(await t.web__run({}))',
    'const {web__run} = tools; text(await web__run({}))',
    'text(Object.keys({...tools}))',
    'text(Object.values(tools).length)',
])
def test_a_script_that_reaches_tools_other_than_by_name_is_flagged(area, code):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert any("reaches tools other than by name" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("code", [
    "text(await \\u0074ools.mcp__codex_apps__github_fetch_file({path: 'MOCK'}))",
    'text((0, eval)("MOCK"))',
    'text(new Function("return MOCK")())',
    'text([].map.constructor("return MOCK")())',
    'text(Object.keys(globalThis))',
    'text(await import("MOCK"))',
    'const m = require("MOCK")',
    'text(Deno.readTextFileSync("MOCK"))',
    'text(process.env.MOCK)',
    'text(Bun.file("MOCK"))',
    'text(fs.readFileSync("MOCK"))',
])
def test_a_script_that_can_spell_or_build_code_is_flagged(area, code):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert any("can spell or build code" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("args, why", [
    ('{open: [{ref_id: "http://127.0.0.1:8080/MOCK"}]}', "127.0.0.1"),
    ('{open: [{ref_id: "https://lim s.example.gov/MOCK"}]}', "`lim`"),
    ('{open: [{ref_id: "https://github.com/MaxGhenis/dc-i86-llm-forecast/blob/main/README.md"}]}', "repository"),
    ('{open: [{ref_id: "file:///etc/hosts"}]}', "neither a web address"),
    ('{open: [{ref_id: "~/.ssh/MOCK"}]}', "neither a web address"),
    ('{search_query: [{q: "ftp://MOCK.example.org/MOCK"}]}', "other than http(s)"),
])
def test_a_scripts_urls_are_read_as_a_web_calls_input(area, args, why):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(f"text(await tools.web__run({args}))")])
    report = acs.audit_run(run, lanes)
    [suspect] = report["threads"][0]["script_suspect"]
    assert suspect["tool"] == "exec script" and why in suspect["why"]
    assert report["suspect"] == 1 and report["flags"] == [] and report["passed"]


def test_each_page_the_web_tool_served_is_audited(area):
    lanes, run, workdir = area
    records = [tool_output(served("https://www.example.org/MOCK") + served("http://192.168.0.1/MOCK", "turn0view1")),
               tool_output(served("https://www.example.org/MOCK", "turn1view0")
                           + served("https://github.com/MaxGhenis/dc-i86-llm-forecast", "turn1view1"),
                           kind="function_call_output")]
    add_parent(lanes, workdir, spawned=(), records=records)
    report = acs.audit_run(run, lanes)
    thread = report["threads"][0]
    assert thread["served_pages"] == 3 and report["served_pages"] == 3
    assert [(s["tool"], s["call"]) for s in thread["script_suspect"]] == [
        ("web page", "http://192.168.0.1/MOCK"), ("web page", "https://github.com/MaxGhenis/dc-i86-llm-forecast")]
    assert report["suspect"] == 2 and report["passed"]


def test_a_shell_command_a_script_ran_with_no_item_is_flagged(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call('text(await tools.exec_command({cmd: "echo MOCK"}))')])
    report = acs.audit_run(run, lanes)
    assert "1 tools.exec_command calls in exec scripts, 0 completed commands" in " ".join(report["flags"])
    assert not report["passed"]


def test_web_actions_compare_as_the_transcript_writes_them(area):
    lanes, run, workdir = area
    pairs = [({"type": "openPage", "url": "https://www.example.org/MOCK"},
              {"type": "open_page", "url": "https://www.example.org/MOCK"}),
             ({"type": "findInPage", "url": None, "pattern": "MOCK"}, {"type": "find_in_page", "pattern": "MOCK"}),
             ({"type": "search", "query": None, "queries": ["MOCK a", "MOCK b"]},
              {"type": "search", "queries": ["MOCK a", "MOCK b"]})]
    add_parent(lanes, workdir, spawned=(), items=[search(f"MOCK {i}", log) for i, (log, _) in enumerate(pairs)])
    write_transcript(run, PARENT, [web(f"MOCK {i}", theirs) for i, (_, theirs) in enumerate(pairs)])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 3, "only_in_transcript": [], "only_in_log": [], "different": []}
    assert report["passed"]


def test_a_command_compares_by_its_words(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[command("echo 'MOCK words'", workdir)])
    write_transcript(run, PARENT, [{"id": "MOCK-echo 'MOCK words'", "type": "command_execution",
                                    "command": "/bin/zsh -lc \"echo 'MOCK words'\"", "aggregated_output": "",
                                    "exit_code": 0, "status": "completed"}])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == [] and report["passed"]


@pytest.mark.parametrize("theirs, key", [
    ([web("MOCK main query", {"type": "search", "queries": ["MOCK other query"]})], "different"),
    ([web("MOCK main query"), web("MOCK transcript only")], "only_in_transcript"),
    ([], "only_in_log"),
])
def test_the_log_and_the_transcript_must_record_the_same_calls(area, theirs, key):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_transcript(run, PARENT, theirs)
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"][key]
    assert any("record different calls" in flag for flag in report["flags"]) and not report["passed"]


def test_every_attempts_threads_are_audited_and_the_collected_one_matches_the_transcript(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["missing"] == [] and report["passed"]
    assert report["main_thread"] == PARENT and report["web_calls"] == 3
    threads = {t["thread_id"]: (t["attempt"], t["collected"]) for t in report["threads"]}
    assert threads == {EARLIER: (f"{JOB}/a1", False), EARLIER_HELPER: (f"{JOB}/a1", False),
                       PARENT: (f"{JOB}/a2", True)}
    kept = json.loads((run / "codex-sessions" / "attempts.json").read_text())
    assert kept["accepted_attempt_id"] == f"{JOB}/a2"
    assert [a["native_session_id"] for a in kept["attempts"]] == [EARLIER, PARENT]


def test_a_violation_in_an_earlier_attempt_fails_the_run(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir, helper_items=[command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert report["violations"] == 1 and not report["passed"]


def test_a_suspect_call_in_an_earlier_attempt_is_counted(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    write_log(lanes, "rollout-MOCK-earlier.jsonl", root_meta(workdir, EARLIER, "2026-11-03T18:00:00Z"),
              records=[exec_call('text(await tools.web__run({open: [{ref_id: "http://localhost/MOCK"}]}))')],
              items=[search("MOCK earlier query")])
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    earlier = next(t for t in report["threads"] if t["thread_id"] == EARLIER)
    assert len(earlier["script_suspect"]) == 1 and report["suspect"] == 1 and report["passed"]


@pytest.mark.parametrize("case", ["stray main thread", "attempt without a log", "no record, two main threads",
                                  "another attempt accepted", "no session for the collected attempt"])
def test_main_threads_must_match_the_attempts(area, monkeypatch, case):
    lanes, run, workdir = area
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    expected = {
        "stray main thread": "is no attempt's session",
        "attempt without a log": None,
        "no record, two main threads": "2 threads started by codex exec",
        "another attempt accepted": f"subfleet accepted {JOB}/a1",
        "no session for the collected attempt": "records no session for the collected attempt",
    }[case]
    if case == "stray main thread":
        with_record(monkeypatch, run, [(f"{JOB}/a2", PARENT, "succeeded")])
    elif case == "attempt without a log":
        with_record(monkeypatch, run, [*TWO_ATTEMPTS, (f"{JOB}/a3", "MOCK-lost-session", "failed")])
    elif case == "another attempt accepted":
        with_record(monkeypatch, run, TWO_ATTEMPTS, accepted=f"{JOB}/a1")
    elif case == "no session for the collected attempt":
        with_record(monkeypatch, run, [(f"{JOB}/a1", EARLIER, "failed"), (f"{JOB}/a2", None, "succeeded")])
    report = acs.audit_run(run, lanes)
    if expected is None:
        assert report["missing"] == ["MOCK-lost-session"]
    else:
        assert any(expected in flag for flag in report["flags"])
    assert not report["passed"]


def test_a_transcript_of_another_thread_fails(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    write_transcript(run, EARLIER, [web("MOCK earlier query")])
    report = acs.audit_run(run, lanes)
    assert report["main_thread"] is None and "transcript_check" not in report
    assert any(f"records thread {EARLIER}" in flag for flag in report["flags"]) and not report["passed"]


def test_the_kept_attempts_are_final(area, monkeypatch):
    lanes, run, workdir = area
    record = with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    assert acs.audit_run(run, lanes)["passed"]
    first = (run / "codex-sessions" / "audit.json").read_bytes()
    monkeypatch.setattr(acs, "subfleet_record", lambda job: None)  # subfleet has pruned the job
    assert acs.audit_run(run, lanes)["passed"]
    assert (run / "codex-sessions" / "audit.json").read_bytes() == first
    changed = {**record, "attempts": record["attempts"][1:]}
    monkeypatch.setattr(acs, "subfleet_record", lambda job: changed)
    with pytest.raises(SystemExit, match="the kept copy is final"):
        acs.audit_run(run, lanes)


def test_a_grandchild_thread_belongs_to_its_attempt(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, [(f"{JOB}/a2", PARENT, "succeeded")])
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
              items=[search("MOCK helper query"), started("MOCK-grandchild")])
    write_log(lanes, "rollout-MOCK-grandchild.jsonl",
              helper_meta(workdir, "MOCK-grandchild", HELPER, "2026-11-03T18:11:00Z"),
              items=[search("MOCK grandchild query")])
    report = acs.audit_run(run, lanes)
    grandchild = next(t for t in report["threads"] if t["thread_id"] == "MOCK-grandchild")
    assert grandchild["attempt"] == f"{JOB}/a2" and grandchild["collected"] and report["passed"]


def test_a_thread_whose_parent_has_no_log_fails(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-orphan.jsonl", helper_meta(workdir, "MOCK-orphan", "MOCK-gone"))
    report = acs.audit_run(run, lanes)
    assert report["orphans"] == ["MOCK-orphan"] and not report["passed"]


def test_a_sibling_work_directory_is_not_this_runs(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-sibling.jsonl", root_meta(workdir + "0", "MOCK-sibling"))
    write_log(lanes, "rollout-MOCK-mention.jsonl",
              {**root_meta(workdir + "-elsewhere", "MOCK-mention"), "note": workdir})
    report = acs.audit_run(run, lanes)
    assert [t["thread_id"] for t in report["threads"]] == [PARENT] and report["passed"]


def test_session_logs_stay_out_of_git():
    """`.gitignore` keeps each log out of this public repository and keeps its audit and attempts in."""
    def ignored(rel: str) -> bool:
        proc = subprocess.run(["git", "check-ignore", "-q", rel], cwd=acs.ROOT, capture_output=True)
        if proc.returncode not in (0, 1):
            pytest.skip("not a git checkout")
        return proc.returncode == 0

    assert ignored("runs/MOCK/codex-sessions/rollout-MOCK.jsonl")
    assert not ignored("runs/MOCK/codex-sessions/audit.json")
    assert not ignored("runs/MOCK/codex-sessions/attempts.json")
    tracked = subprocess.run(["git", "ls-files", "runs"], cwd=acs.ROOT, capture_output=True, text=True).stdout
    assert {Path(p).name for p in tracked.split() if "/codex-sessions/" in p} <= {"audit.json", "attempts.json"}


NAMES = st.lists(st.from_regex(r"[a-z][a-z0-9]{0,6}", fullmatch=True), min_size=1, max_size=4)


@given(words=NAMES, fields=st.dictionaries(st.from_regex(r"[a-z]{1,8}", fullmatch=True).filter(lambda k: k != "type"),
                                           st.none() | st.text(max_size=5) | st.lists(st.text(max_size=3), max_size=2),
                                           max_size=4))
def test_a_web_action_takes_the_transcripts_form(words, fields):
    """Property: the kind's camelCase words join with underscores, null fields drop, the rest stay,
    and the form is a fixed point."""
    camel = words[0] + "".join(w[0].upper() + w[1:] for w in words[1:])
    out = acs.web_action({"type": camel, **fields})
    assert out["type"] == "_".join(words)
    assert {k: v for k, v in out.items() if k != "type"} == {k: v for k, v in fields.items() if v is not None}
    assert acs.web_action(out) == out


@given(argv=st.lists(st.text(st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"), max_size=8),
                     min_size=1, max_size=4))
def test_a_command_compares_the_same_however_it_is_quoted(argv):
    """Property: a command the log keeps as words compares equal to any quoting of the same words."""
    def line(cmd):
        return [{"type": "item.completed", "item": {"id": "MOCK", "type": "command_execution", "command": cmd}}]

    double = " ".join('"' + re.sub(r'(["\\])', r"\\\1", word) + '"' for word in argv)
    assert acs._calls(line(shlex.join(argv))) == acs._calls(line(double))
