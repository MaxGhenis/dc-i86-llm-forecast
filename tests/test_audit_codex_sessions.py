"""scripts/audit_codex_sessions.py finds every Codex thread behind a run, ties each main thread to a
subfleet attempt, keeps its log and audits it. MOCK session logs, transcripts and subfleet records in
temporary directories; the tests never run subfleet or any other command. The pooling gate
(`cli._session_audit`) reads every audit a test writes and must reach the script's verdict."""

import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from i86 import cli

spec = importlib.util.spec_from_file_location(
    "audit_codex_sessions", Path(__file__).parent.parent / "scripts" / "audit_codex_sessions.py")
acs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acs)

PARENT, HELPER = "MOCK-parent-thread", "MOCK-helper-thread"
EARLIER, EARLIER_HELPER = "MOCK-earlier-thread", "MOCK-earlier-helper-thread"
JOB = "MOCK-job-sol-1"
CITE = "cite{}"  # the web tool's cite marker: "citeturn0view0" between private-use characters


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


def command(cmd: str, cwd: str, item_id: str | None = None) -> dict:
    return {"type": "CommandExecution", "id": item_id or f"MOCK-{cmd}", "command": ["/bin/zsh", "-lc", cmd],
            "cwd": f"file://{cwd}", "status": "completed", "exit_code": 0, "aggregated_output": ""}


def exec_call(code: str, call_id: str | None = None) -> dict:
    payload = {"type": "custom_tool_call", "name": "exec", "input": code}
    return {"type": "response_item", "payload": {**payload, "call_id": call_id} if call_id else payload}


def tool_output(text: str, kind: str = "custom_tool_call_output", call_id: str | None = None) -> dict:
    """A script's result (or, as a function_call_output, a running cell's that `wait` returns)."""
    payload = {"type": kind, "output": [{"type": "input_text", "text": text}]}
    return {"type": "response_item", "payload": {**payload, "call_id": call_id} if call_id else payload}


def refusal(call_id: str) -> dict:
    """A script's output as Codex reports one that V8 refused to compile."""
    return {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": call_id, "output": [
        {"type": "input_text", "text": "Script failed\nWall time 0.0 seconds\nOutput:\n"},
        {"type": "input_text", "text": "Script error:\nSyntaxError: MOCK unexpected token"}]}}


def served(url: str, ref: str = "turn0view0") -> str:
    """A page as the web tool's reply cites it."""
    return f"MOCK page ({url})\n{CITE.format(ref)} [wordlim: 200] MOCK text"


def function_call(name: str, namespace: str | None = "collaboration") -> dict:
    """A function call as a session log records it: a sub-agent tool in its namespace, or (with no
    namespace) code mode's `wait`."""
    payload = {"type": "function_call", "name": name, "arguments": "{}"}
    if namespace is not None:
        payload["namespace"] = namespace
    return {"type": "response_item", "payload": payload}


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
    unrelated job in the lanes. No test may start a process, and the gate must read each audit the
    script writes as passing exactly when the script says it passed."""
    def no_process(*args, **kwargs):
        raise AssertionError(f"the tests run no command: {args}")

    script_audit = acs.audit_run

    def audit_run(run_dir: Path, lanes: Path) -> dict:
        report = script_audit(run_dir, lanes)
        verdict = cli._session_audit(run_dir)
        assert isinstance(verdict, dict) and verdict["passed"] is report["passed"], verdict
        return report

    monkeypatch.setattr(acs.subprocess, "run", no_process)
    monkeypatch.setattr(acs, "audit_run", audit_run)
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
    """The collected main thread's log: its items, one `spawn_agent` call and a started event for each
    sub-agent in `spawned`, and any other `records`."""
    items = [search("MOCK main query")] if items is None else items
    return write_log(lanes, "rollout-MOCK-parent.jsonl", root_meta(workdir),
                     records=[*records, *[function_call("spawn_agent") for _ in spawned]],
                     items=[*items, *[started(t) for t in spawned]])


def with_record(monkeypatch, run: Path, attempts, accepted: str = f"{JOB}/a2", collected: str = f"{JOB}/a2"):
    """Give the MOCK run a subfleet job whose attempts are (attempt id, session, state), each of which
    started unless a fourth item says when (None: it never did)."""
    meta = json.loads((run / "meta.json").read_text())
    meta.update(job_id=JOB, attempt_id=collected)
    (run / "meta.json").write_text(json.dumps(meta))
    record = {"job": {"accepted_attempt_id": accepted},
              "attempts": [{"attempt_id": a[0], "native_session_id": a[1], "state": a[2], "lane_id": "codex-9",
                            "started_at": a[3] if len(a) > 3 else "2026-11-03T18:00:00Z"} for a in attempts]}
    monkeypatch.setattr(acs, "subfleet_record", lambda job: record if job == JOB else None)
    return record


def add_earlier_attempt(lanes: Path, workdir: str, helper_items=()) -> None:
    """A failed first attempt in the same work directory: its main thread and one sub-agent."""
    write_log(lanes, "rollout-MOCK-earlier.jsonl", root_meta(workdir, EARLIER, "2026-11-03T18:00:00Z"),
              records=[function_call("spawn_agent")], items=[search("MOCK earlier query"), started(EARLIER_HELPER)])
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
    names = ["send_message", "followup_task", "wait_agent", "interrupt_agent", "list_agents"]
    add_parent(lanes, workdir, records=[*[function_call(name) for name in names], function_call("wait", None)])
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["passed"]
    parent = next(t for t in report["threads"] if t["thread_id"] == PARENT)
    assert parent["functions"] == {name: 1 for name in [*names, "wait", "spawn_agent"]}


@pytest.mark.parametrize("name, namespace", [("send_message", "MOCK_connector"), ("wait", "collaboration"),
                                             ("spawn_agent", None)])
def test_a_function_is_read_only_in_its_own_namespace(area, name, namespace):
    """Review finding 8: a connector's function of the same name is not a sub-agent tool."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[function_call(name, namespace)])
    report = acs.audit_run(run, lanes)
    assert f"function {name!r} in namespace {namespace!r}, which this script does not read" in " ".join(report["flags"])
    assert not report["passed"]


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


@pytest.mark.parametrize("line, flag", [("{MOCK", "does not parse"), ("[1]", "is not a record")])
def test_a_log_line_that_is_not_a_record_is_flagged(area, line, flag):
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    with parent.open("a") as fh:
        fh.write(line + "\n")
    report = acs.audit_run(run, lanes)
    assert f"rollout-MOCK-parent.jsonl line 3 {flag}" in report["flags"] and not report["passed"]


def test_a_plain_web_script_passes(area):
    lanes, run, workdir = area
    code = ('text(await tools.web__run({search_query: [{q: "MOCK query"}], '
            'open: [{ref_id: "https://www.example.org/MOCK"}, {ref_id: "turn0search1"}]}))')
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["suspect"] == 0 and report["passed"]
    assert report["threads"][0]["script_tools"] == {"web__run": 1}


@pytest.mark.parametrize("code", [
    # The pattern of sol-3's keys: strings built around values, with a piece that is part of no name
    # the script denies.
    'const cells = ["a", "b"]; const m = {}; for (let i = 0; i < cells.length; i++) { const s = "x"; '
    'm["yes_" + cells[i] + "|" + s] = i; m[`no_${cells[i]}`] = i - 1; } text(JSON.stringify(m))',
    'const xs = [1, 2, 3]; text(xs[xs.length - 1], xs[0], ({a: 1})["a"])',
    'const {a, b: [c = 1, ...rest]} = {a: 1, b: [2]}; text(a + c + rest.length)',
    'async function f(q) { return await tools.web__run({search_query: [{q}]}); } '
    'try { text(await f("MOCK")); } catch (e) { text(String(e)); }',
    'class Store { get() { return 1; } } text(new Store().get(), ALL_TOOLS.map((t) => t.name).join(","))',
    'setTimeout(() => text("MOCK"), 0); for (const [k, v] of Object.entries({MOCK: 1})) text(k, v)',
    'const r = await tools.web__run({open: [{ref_id: `turn0view0`}, {"ref_id": "https://www.example.org/MOCK"}]}); '
    'text(r)',
])
def test_a_script_that_uses_only_the_language_and_the_web_tool_passes(area, code):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["suspect"] == 0 and report["passed"]


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
    'text("\\x74ools")',
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
    # Review finding 1: a getter on every object's prototype hands back the global object.
    'Object.defineProperty(Object.prototype, "g", {get() { return this; }});\n'
    'await g["to" + "ols"]["mcp__codex_apps__github_fetch_file"]({});',
    'Object.__defineGetter__("g", () => 1)',
    'text(Object.__lookupGetter__("g"))',
    'Object.defineProperty({}, "g", {value: 1})',
    'Object.defineProperties({}, {})',
    'text(Object.getPrototypeOf([]))',
    'text(Object.getOwnPropertyDescriptor(Object, "MOCK"))',
    'text(Object.setPrototypeOf({}, null))',
    'text(Array.prototype)',
    'text({}.__proto__)',
    'text(Reflect.ownKeys({}))',
    'text(new Proxy({}, {}))',
    'const o = {get g() { return 1; }}',
    'class A { static set g(v) {} }',
])
def test_a_script_that_can_spell_or_build_code_is_flagged(area, code):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert any("can spell or build code" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("code, problem", [
    # Review finding 1: a split "constructor" reaches the Function constructor, which builds code.
    ('[]["con" + "structor"]["con" + "structor"]("return to" + "ols")()["mcp__codex_apps__github_fetch_file"]({})',
     "indexes with 'constructor'"),
    ('const o = {}; text(await o["to" + "ols"].web__run({}))', "indexes with 'tools'"),
    ('const o = {}; text(o[`${"__pro"}to__`])', "indexes with '__proto__'"),
    ('const w = `to${"ols"}`; text(w)', "builds the string 'tools'"),
    ('const o = {get ["g"]() { return 1; }}; text(o.g)', "defines an accessor"),
    ("text(this)", "uses this"),
    ("text(MOCK_global)", "names 'MOCK_global', which it does not declare"),
    ("with ({}) { text(1) }", "uses with"),
    ('const o = {}; const k = "a"; text(o[k.repeat(1)])', "a key this script cannot read"),
    ("Error.prepareStackTrace = (e, f) => f; text(1)", "names prepareStackTrace"),
])
def test_a_script_that_reaches_past_its_tools_is_flagged_from_its_syntax(area, code, problem):
    """None of these holds a word the text checks look for; the syntax tree shows what each does."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    flags = " ".join(report["flags"])
    assert problem in flags and "can spell or build code" not in flags and not report["passed"]


@pytest.mark.parametrize("code, problem", [
    ("const t = tools; text(t)", "reaches tools other than as tools.web__run or tools.exec_command"),
    ("text(tools[0])", "reaches tools other than as tools.web__run or tools.exec_command"),
    ("text(await tools.mcp__codex_apps__github_fetch_file({}))", "reaches tools other than as tools.web__run"),
    ("text(await tools?.web__run({}))", "reaches tools other than as tools.web__run"),
    ("text([].map.constructor)", "names constructor"),
    ('text(({})["__proto__"])', "indexes with '__proto__'"),
    ("text(eval)", "names 'eval', which it does not declare"),
    ("text(globalThis)", "names 'globalThis', which it does not declare"),
    ("const o = {set s(v) {}}", "defines an accessor"),
])
def test_the_syntax_check_reads_each_rule_on_its_own(code, problem):
    """The text checks flag these too; the syntax check must not lean on them."""
    src = code.encode()
    assert any(problem in found for found in acs.cell_problems(acs._JS.parse(src), src))


def test_a_script_too_deep_to_read_is_flagged(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call("text(" + " + ".join(['"MOCK"'] * 3000) + ")")])
    report = acs.audit_run(run, lanes)
    assert any("nests too deeply for this script to read" in flag for flag in report["flags"])
    assert not report["passed"]


@pytest.mark.parametrize("replies, passes", [
    (["refused"], True), ([], False), (["result"], False), (["refused", "refused"], False),
    (["refused elsewhere"], False), (["type error"], False), (["three parts"], False)])
def test_a_script_the_grammar_cannot_parse_passes_only_as_one_v8_refused(area, replies, passes):
    lanes, run, workdir = area
    type_error, three_parts = refusal("MOCK-call"), refusal("MOCK-call")
    type_error["payload"]["output"][1]["text"] = "Script error:\nTypeError: MOCK"
    three_parts["payload"]["output"].append({"type": "input_text", "text": "MOCK more"})
    outputs = {"refused": refusal("MOCK-call"), "result": tool_output("MOCK result", call_id="MOCK-call"),
               "refused elsewhere": refusal("MOCK-other-call"), "type error": type_error, "three parts": three_parts}
    records = [exec_call("text(await tools.web__run({)", "MOCK-call"), *[outputs[r] for r in replies]]
    add_parent(lanes, workdir, spawned=(), records=records)
    report = acs.audit_run(run, lanes)
    flagged = any("does not parse as JavaScript" in flag for flag in report["flags"])
    assert flagged is not passes and report["passed"] is passes


@pytest.mark.parametrize("args, why", [
    ('{open: [{ref_id: "http://127.0.0.1:8080/MOCK"}]}', "127.0.0.1"),
    ('{open: [{ref_id: "https://lim s.example.gov/MOCK"}]}', "`lim`"),
    ('{open: [{ref_id: "https://github.com/MaxGhenis/dc-i86-llm-forecast/blob/main/README.md"}]}', "repository"),
    ('{open: [{ref_id: "file:///etc/hosts"}]}', "neither a web address"),
    ('{open: [{ref_id: "~/.ssh/MOCK"}]}', "neither a web address"),
    ('{search_query: [{q: "ftp://MOCK.example.org/MOCK"}]}', "other than http(s)"),
    # Review finding 6: each string's text with its escapes decoded, and each `+` of constants.
    (r'{open: [{ref_id: "https://github.com/MaxGhenis/dc-i86-llm-fore\cast"}]}', "repository"),
    (r'{search_query: [{q: `https://github.com/MaxGhenis/dc-i86-llm-fore\cast/${Math.PI}`}]}', "repository"),
    ('{search_query: [{q: "dc-i86-" + "llm-forecast"}]}', "repository"),
    ('{search_query: [{q: "http://" + "127.0.0.1:8080/MOCK"}]}', "127.0.0.1"),
    (r'{search_query: [{q: "file\:///etc/hosts"}]}', "other than http(s)"),
])
def test_a_scripts_urls_are_read_as_a_web_calls_input(area, args, why):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(f"text(await tools.web__run({args}))")])
    report = acs.audit_run(run, lanes)
    [suspect] = report["threads"][0]["script_suspect"]
    assert suspect["tool"] == "exec script" and why in suspect["why"]
    assert report["suspect"] == 1 and report["flags"] == [] and report["passed"]


@pytest.mark.parametrize("code, why", [
    ('text(await tools.web__run({open: [{"ref_id": "/etc/hosts"}]}))', "neither a web address"),
    ("text(await tools.web__run({open: [{'ref_id': '/etc/hosts'}]}))", "neither a web address"),
    ('const ref_id = "/MOCK"; text(await tools.web__run({open: [{ref_id}]}))', "holds in a variable"),
    ('const r = "/MOCK"; text(await tools.web__run({open: [{ref_id: r}]}))', "not one string written out"),
    ('text(await tools.web__run({open: [{"ref_id": "file" + ":///etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{ref_id: "https://www.example.org/" + "MOCK"}]}))', "not one string"),
    ('text(await tools.web__run({open: [{ref_id: `https://www.example.org/${"MOCK"}`}]}))', "not one string"),
    ('const r = "/MOCK"; text(await tools.web__run({open: [{["ref_id"]: r}]}))', "not one string written out"),
    ('const o = {}; o.ref_id = "/MOCK"; text(await tools.web__run({open: [o]}))', "a ref_id member"),
    ('const o = {}; o["ref_id"] = "/MOCK"; text(await tools.web__run({open: [o]}))', "a ref_id member"),
    # Review finding 6: a page given by a constant the regular expression does not read.
    ('text(await tools.web__run({open: [{ref_id:/**/"/etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{["ref_id"]:"/etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{[/**/"ref_id"]: "/etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{[("ref_" + "id")]: "/etc/hosts"}]}))', "neither a web address"),
    (r'text(await tools.web__run({open: [JSON.parse("{\"ref_id\": \"/etc/hosts\"}")]}))', "neither a web address"),
    ('const k = "ref_id"; text(await tools.web__run({open: [{[k]: "/MOCK"}]}))', "writes the string ref_id"),
    ('const k = `${"ref_id"}`; text(await tools.web__run({open: [{[k]: "/MOCK"}]}))', "writes the string ref_id"),
    ('const e = ""; text(await tools.web__run({open: [{[e + "ref_id"]: "/MOCK"}]}))', "writes the string ref_id"),
    ('text(await tools.web__run({open: [Object.fromEntries([["ref_id", "/MOCK"]])]}))', "writes the string ref_id"),
    ('class P { ref_id = "/MOCK" } text(await tools.web__run({open: [new P()]}))', "names ref_id in a field_definition"),
])
def test_a_page_a_script_opens_must_be_one_string_written_out(area, code, why):
    """Review findings 4 and 6: a `ref_id` under a quoted or computed key, held in a variable, built
    from pieces, given with a comment before it, parsed from JSON, or built as an object's key."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    [suspect] = report["threads"][0]["script_suspect"]
    assert suspect["tool"] == "exec script" and why in suspect["why"]
    assert report["suspect"] == 1 and report["passed"]


@pytest.mark.parametrize("pages", [
    '{ref_id: "turn0search3"}, {ref_id: "https://www.example.org/MOCK"}',
    '{"ref_id": "turn1view0"}, {\'ref_id\': `https://www.example.org/MOCK`}',
    '{["ref_id"]: "turn0search3"}, {[("ref_" + "id")]: "https://www.example.org/MOCK"}',
    '{[/* MOCK */ ("ref_id")]: "turn0search3", lineno: 1}',
])
def test_a_page_a_script_opens_by_one_string_written_out_is_a_web_call(area, pages):
    """No false flag: a page a script opens by a `ref_id` key written out, quoted or computed from
    constants, with a web address or a page the web tool returned."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(f"text(await tools.web__run({{open: [{pages}]}}))")])
    report = acs.audit_run(run, lanes)
    assert report["threads"][0]["script_suspect"] == [] and report["flags"] == [] and report["passed"]


def test_each_page_the_web_tool_served_is_audited(area):
    lanes, run, workdir = area
    records = [tool_output(served("https://www.example.org/MOCK") + served("http://192.168.0.1/MOCK", "turn0view1")),
               tool_output(served("https://www.example.org/MOCK", "turn1view0")
                           + served("https://github.com/MaxGhenis/dc-i86-llm-forecast", "turn1view1")
                           + served("http://192.168.0.1/MOCK", "turn1view2"),  # served again: one suspect
                           kind="function_call_output")]
    add_parent(lanes, workdir, spawned=(), records=records)
    report = acs.audit_run(run, lanes)
    thread = report["threads"][0]
    assert thread["served_pages"] == 3 and report["served_pages"] == 3
    assert [(s["tool"], s["call"]) for s in thread["script_suspect"]] == [
        ("web page", "http://192.168.0.1/MOCK"), ("web page", "https://github.com/MaxGhenis/dc-i86-llm-forecast")]
    assert report["suspect"] == 2 and report["passed"]


def test_a_page_cited_after_an_escaped_newline_is_audited(area):
    """Review finding 2: a script that prints the web tool's reply as JSON leaves `\\n` between a page's
    address and its cite marker; an empty "()" names no page, and a link inside a page has a marker of
    its own."""
    lanes, run, workdir = area
    text = (json.dumps(served("http://127.0.0.1:8080/MOCK"), ensure_ascii=False)
            + f" MOCK () {CITE.format('turn1view0')} MOCK link cite9†MOCK anchor")
    add_parent(lanes, workdir, spawned=(), records=[tool_output(text)])
    report = acs.audit_run(run, lanes)
    [suspect] = report["threads"][0]["script_suspect"]
    assert (suspect["tool"], suspect["call"]) == ("web page", "http://127.0.0.1:8080/MOCK")
    assert report["served_pages"] == 1 and report["flags"] == [] and report["passed"]


@pytest.mark.parametrize("text", [
    f"MOCK page {CITE.format('turn0view0')}",
    "MOCK entityMOCK",
    f"MOCK (https://www.example.org/MOCK) {CITE.format('MOCK')}",
])
def test_a_cite_marker_this_script_cannot_read_is_flagged(area, text):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[tool_output(text)])
    report = acs.audit_run(run, lanes)
    assert "a tool's reply holds 1 cite marker(s) this script does not read" in " ".join(report["flags"])
    assert not report["passed"]


def test_a_shell_command_a_script_ran_with_no_item_is_flagged(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call('text(await tools.exec_command({cmd: "echo MOCK"}))')])
    report = acs.audit_run(run, lanes)
    assert "1 tools.exec_command calls in exec scripts, 0 completed commands" in " ".join(report["flags"])
    assert not report["passed"]


def test_every_script_that_calls_the_shell_is_suspect(area):
    """Review finding 3: one script runs two commands, so the counts match although the second script's
    command has no item; each script is suspect, and the shell rules read the command it names."""
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    records = [exec_call('for (const c of ["true", "true"]) await tools.exec_command({cmd: c});'),
               exec_call('await tools.exec_command({cmd: "cat ~/.ssh/MOCK_key"});')]
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), records=records,
              items=[command("true", workdir), command("true", workdir, "MOCK-true-2")])
    report = acs.audit_run(run, lanes)
    helper = next(t for t in report["threads"] if t["thread_id"] == HELPER)
    whys = [s["why"] for s in helper["script_suspect"]]
    assert len(whys) == 2 and "only a command's completed item says what ran" in whys[0]
    assert "calls tools.exec_command with 'cat ~/.ssh/MOCK_key' (suspect: " in whys[1]
    assert report["flags"] == [] and report["suspect"] == 2 and report["passed"]


def test_a_command_a_script_names_is_read_by_the_shell_rules():
    code = f'await tools.exec_command({{cmd: "cat " + "{acs.ROOT / "README.md"}"}})'
    tree = acs._JS.parse(code.encode())
    verdict, why = acs.check_script(code, "/MOCK/work", tree)
    assert verdict == "suspect" and "(violation: " in why


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
        with_record(monkeypatch, run, [(f"{JOB}/a1", PARENT, "succeeded")], accepted=f"{JOB}/a1", collected=f"{JOB}/a1")
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


@pytest.mark.parametrize("started_at, passes", [("2026-11-03T18:00:00Z", False), (None, True)])
def test_an_attempt_that_started_must_name_its_session(area, monkeypatch, started_at, passes):
    """Review finding 6, gap A: an earlier attempt that started with no session on record could have
    left threads no log is known for; one that never started has none."""
    lanes, run, workdir = area
    with_record(monkeypatch, run, [(f"{JOB}/a1", None, "failed", started_at), (f"{JOB}/a2", PARENT, "succeeded")])
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert (f"subfleet records no session for attempt {JOB}/a1, which started" in report["flags"]) is not passes
    assert report["passed"] is passes


@pytest.mark.parametrize("collected, passes", [(None, True), (f"{JOB}/a1", True), (f"{JOB}/a2", False)])
def test_without_attempts_on_record_a_run_must_have_collected_its_jobs_first(area, collected, passes):
    """Review finding 6, gap B: with no record, nothing says what an earlier attempt left."""
    lanes, run, workdir = area
    if collected:
        meta = json.loads((run / "meta.json").read_text())
        (run / "meta.json").write_text(json.dumps({**meta, "attempt_id": collected}))
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert any("not its job's first attempt" in flag for flag in report["flags"]) is not passes
    assert report["passed"] is passes


def test_two_logs_of_one_thread_must_hold_the_same_bytes(area):
    """Review finding 6, gap D: a second log of a thread is the same log only if it matches the first."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    shutil.copyfile(parent, parent.with_name("rollout-MOCK-parent-copy.jsonl"))
    assert acs.audit_run(run, lanes)["passed"]
    write_log(lanes, "rollout-MOCK-parent-edited.jsonl", root_meta(workdir),
              items=[search("MOCK main query"), search("MOCK added query")])
    report = acs.audit_run(run, lanes)
    assert any(f"both hold thread {PARENT}, and they differ" in flag for flag in report["flags"])
    assert not report["passed"]


@pytest.mark.parametrize("case, flag", [
    ("cut", "names the work directory but does not parse"),
    ("other record", "names the work directory but is not a session's record"),
    ("no id", "a session in the work directory with no thread id"),
    ("sub-agent source as a string", "gives a source this script cannot read"),
    ("other source", "gives a source this script cannot read"),
    ("nested too deeply", "names the work directory but does not parse"),
])
def test_a_log_in_the_work_directory_this_script_cannot_read_is_flagged(area, case, flag):
    """Review findings 6 (gap E) and 9: such a log is flagged, not skipped, and does not stop the audit."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    first = {
        "cut": json.dumps({"type": "session_meta", "payload": root_meta(workdir, "MOCK-odd")})[:-10],
        "other record": json.dumps({"type": "MOCK_record", "payload": {"cwd": workdir}}),
        "no id": json.dumps({"type": "session_meta", "payload": {"cwd": workdir, "source": "exec"}}),
        "sub-agent source as a string": json.dumps(
            {"type": "session_meta", "payload": {**root_meta(workdir, "MOCK-odd"), "source": {"subagent": "MOCK"}}}),
        "other source": json.dumps(
            {"type": "session_meta", "payload": {**root_meta(workdir, "MOCK-odd"), "source": "MOCK-cli"}}),
        "nested too deeply": json.dumps({"type": "session_meta", "payload": root_meta(workdir, "MOCK-odd")})[:-2]
        + ', "MOCK": ' + "[" * 100_000 + "]" * 100_000 + "}}",
    }[case]
    (lanes / "codex-9" / "sessions" / "2026" / "11" / "03" / "rollout-MOCK-odd.jsonl").write_text(first + "\n")
    report = acs.audit_run(run, lanes)
    assert any(flag in f for f in report["flags"]) and not report["passed"]


def spell(text: str, how: str) -> str:
    """`text` as the body of a JSON string that spells it with escapes."""
    if how == "escaped slashes":
        return text.replace("/", "\\/")
    if how == "unicode slashes":
        return text.replace("/", "\\u002F")
    return "".join(f"\\u{ord(char):04x}" for char in text)


def escape_first_line(log: Path, workdir: str, how: str) -> None:
    """Rewrite a log's first line to spell the work directory with escapes."""
    first, rest = log.read_text().split("\n", 1)
    first = first.replace(json.dumps(workdir), '"' + spell(workdir, how) + '"')
    assert json.dumps(workdir) not in first and json.loads(first)["payload"]["cwd"] == workdir
    log.write_text(first + "\n" + rest)


@pytest.mark.parametrize("how", ["escaped slashes", "unicode slashes", "every character"])
def test_a_log_that_spells_the_work_directory_with_escapes_is_compared(area, how):
    """Review finding 2: discovery reads the work directory however a log's JSON spells it, so a second
    log of the main thread, with a call the first lacks, fails the run."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    copy = write_log(lanes, "rollout-MOCK-parent-escaped.jsonl", root_meta(workdir),
                     items=[search("MOCK main query"), command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    escape_first_line(copy, workdir, how)
    report = acs.audit_run(run, lanes)
    assert any(f"both hold thread {PARENT}, and they differ" in flag for flag in report["flags"])
    assert not report["passed"]


@pytest.mark.parametrize("how", ["escaped slashes", "unicode slashes", "every character"])
def test_a_sub_agent_whose_log_spells_the_work_directory_with_escapes_is_audited(area, how):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    helper = write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
                       items=[search("MOCK helper query"), command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    escape_first_line(helper, workdir, how)
    report = acs.audit_run(run, lanes)
    assert {t["thread_id"] for t in report["threads"]} == {PARENT, HELPER} and report["missing"] == []
    assert report["violations"] == 1 and not report["passed"]


@pytest.mark.parametrize("before", [None, 'MOCK "quote'], ids=["alone", "after an escaped quote"])
@pytest.mark.parametrize("case", ["cut", "other record"])
def test_a_first_line_that_escapes_the_work_directory_and_cannot_be_read_is_flagged(area, tmp_path, case, before):
    """A log whose first line spells the work directory with escapes, but does not parse as a session's
    record, is flagged, also after a string that escapes a quote; one that spells another directory so
    is not."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    folder = lanes / "codex-9" / "sessions" / "2026" / "11" / "03"
    for name, where in [("rollout-MOCK-odd.jsonl", workdir), ("rollout-MOCK-odd-elsewhere.jsonl", str(tmp_path / "MOCK"))]:
        payload = root_meta(where, "MOCK-odd") if case == "cut" else {"cwd": where}
        if before is not None:
            payload = {"note": before, **payload}
        record = {"type": "session_meta" if case == "cut" else "MOCK_record", "payload": payload}
        first = json.dumps(record).replace(json.dumps(where), '"' + spell(where, "escaped slashes") + '"')
        (folder / name).write_text((first[:-10] if case == "cut" else first) + "\n")
    report = acs.audit_run(run, lanes)
    assert [flag.split(":")[0] for flag in report["flags"]] == ["rollout-MOCK-odd.jsonl"] and not report["passed"]


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


@pytest.mark.parametrize("case, flag", [
    ("only the collected attempt", f"lists attempts ['{JOB}/a2'], not {JOB}/a1 to {JOB}/a1"),
    ("another job's attempt", f"of job {JOB} lists attempts ['MOCK-other-job/a1'], not {JOB}/a1 to {JOB}/a1"),
    ("one session for two attempts", f"names session {PARENT} for 2 attempts"),
    ("a sub-agent as an attempt's session", f"attempt {JOB}/a2's session {EARLIER_HELPER} is a sub-agent"),
    ("a session that is not a string", f"gives attempt {JOB}/a1 a session this script cannot read"),
    ("an attempt id that is not a string", f"lists attempts [None, '{JOB}/a2'], not {JOB}/a1 to {JOB}/a2"),
    ("a kept record of another job", f"of job MOCK-other-job lists attempts ['{JOB}/a1'], not {JOB}/a1 to {JOB}/a1"),
])
def test_each_attempt_must_be_its_jobs_with_a_main_thread_of_its_own(area, monkeypatch, case, flag):
    """Review finding 3: a record that leaves out an attempt, gives two attempts one session, or gives
    an attempt a sub-agent as its session cannot say which threads each attempt left. Each case fails
    the run on this flag alone."""
    lanes, run, workdir = area
    if case == "a sub-agent as an attempt's session":
        with_record(monkeypatch, run, [(f"{JOB}/a1", EARLIER, "failed"), (f"{JOB}/a2", EARLIER_HELPER, "succeeded")])
        add_earlier_attempt(lanes, workdir)
        write_transcript(run, EARLIER_HELPER, [web("MOCK earlier helper query")])
    elif case == "a kept record of another job":
        add_parent(lanes, workdir, spawned=())
        with_record(monkeypatch, run, [(f"{JOB}/a1", PARENT, "succeeded")], accepted=f"{JOB}/a1", collected=f"{JOB}/a1")
        monkeypatch.setattr(acs, "subfleet_record", lambda job: None)  # subfleet has pruned the job
        (run / "codex-sessions").mkdir()
        (run / "codex-sessions" / "attempts.json").write_text(json.dumps({
            "job_id": "MOCK-other-job", "accepted_attempt_id": f"{JOB}/a1",
            "attempts": [{"attempt_id": f"{JOB}/a1", "native_session_id": PARENT, "started_at": "MOCK"}]}))
    else:
        add_parent(lanes, workdir, spawned=())
        with_record(monkeypatch, run, *{
            "only the collected attempt": ([(f"{JOB}/a2", PARENT, "succeeded")],),
            "another job's attempt": ([("MOCK-other-job/a1", PARENT, "succeeded")], "MOCK-other-job/a1",
                                      "MOCK-other-job/a1"),
            "one session for two attempts": ([(f"{JOB}/a1", PARENT, "failed"), (f"{JOB}/a2", PARENT, "succeeded")],),
            "a session that is not a string": ([(f"{JOB}/a1", ["MOCK"], "failed"), (f"{JOB}/a2", PARENT, "succeeded")],),
            "an attempt id that is not a string": ([(None, None, "failed", None), (f"{JOB}/a2", PARENT, "succeeded")],),
        }[case])
    report = acs.audit_run(run, lanes)
    [only] = report["flags"]
    assert flag in only and report["missing"] == [] and not report["passed"]


@pytest.mark.parametrize("text", ['{"attempts": "MOCK"}', '["MOCK"]', '{"attempts": ["MOCK"]}'])
def test_a_kept_attempts_file_that_is_not_a_record_stops_the_audit(area, text):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    (run / "codex-sessions").mkdir()
    (run / "codex-sessions" / "attempts.json").write_text(text)
    with pytest.raises(SystemExit, match="is not a record of attempts"):
        acs.audit_run(run, lanes)


def test_a_grandchild_thread_belongs_to_its_attempt(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), records=[function_call("spawn_agent")],
              items=[search("MOCK helper query"), started("MOCK-grandchild")])
    write_log(lanes, "rollout-MOCK-grandchild.jsonl",
              helper_meta(workdir, "MOCK-grandchild", HELPER, "2026-11-03T18:11:00Z"),
              items=[search("MOCK grandchild query")])
    report = acs.audit_run(run, lanes)
    grandchild = next(t for t in report["threads"] if t["thread_id"] == "MOCK-grandchild")
    assert grandchild["attempt"] == f"{JOB}/a2" and grandchild["collected"] and report["passed"]


def test_a_thread_whose_parent_has_no_log_fails(area):
    """Review finding 7: the orphan's own audit passes, so only the orphan rule fails the run."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-orphan.jsonl", helper_meta(workdir, "MOCK-orphan", "MOCK-gone"),
              items=[search("MOCK orphan query")])
    report = acs.audit_run(run, lanes)
    assert report["orphans"] == ["MOCK-orphan"] and report["flags"] == [] and report["missing"] == []
    assert all(t["audit"]["passed"] for t in report["threads"]) and not report["passed"]


def test_a_threads_spawn_calls_must_match_the_sub_agents_it_started(area):
    """Review finding 6: each sub-agent comes from one `spawn_agent` call."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, records=[function_call("spawn_agent")])  # two calls, one sub-agent
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"thread {PARENT} made 2 spawn_agent calls and started 1 sub-agents"]
    assert not report["passed"]


def test_threads_whose_parents_form_a_cycle_fail(area):
    """Review finding 4: two sub-agents that each name the other as their parent, and each started the
    other, descend from no main thread."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    loop = ["MOCK-loop-a", "MOCK-loop-b"]
    for me, other in zip(loop, reversed(loop)):
        write_log(lanes, f"rollout-{me}.jsonl", helper_meta(workdir, me, other), records=[function_call("spawn_agent")],
                  items=[search(f"{me} query"), started(other)])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"thread {t} descends from no main thread: its parents form a cycle" for t in loop]
    assert report["orphans"] == [] and report["missing"] == [] and not report["passed"]


def test_a_sub_agent_must_name_the_thread_that_started_it(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"thread {PARENT} started [], but ['{HELPER}'] name it as their parent"]
    assert not report["passed"]


def test_a_sibling_work_directory_is_not_this_runs(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-sibling.jsonl", root_meta(workdir + "0", "MOCK-sibling"))
    write_log(lanes, "rollout-MOCK-mention.jsonl",
              {**root_meta(workdir + "-elsewhere", "MOCK-mention"), "note": workdir})
    report = acs.audit_run(run, lanes)
    assert [t["thread_id"] for t in report["threads"]] == [PARENT] and report["passed"]


@pytest.mark.parametrize("result, expected", [
    ({"returncode": 0, "stdout": '{"attempts": []}'}, {"attempts": []}),
    ({"returncode": 1, "stdout": '{"attempts": []}'}, None),
    ({"returncode": 0, "stdout": "MOCK not JSON"}, None),
    (OSError("MOCK: no subfleet"), None),
])
def test_subfleet_is_asked_for_the_job_and_any_failure_means_no_record(monkeypatch, result, expected):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(cmd, result["returncode"], result["stdout"], "")

    monkeypatch.setattr(acs.subprocess, "run", fake_run)
    assert acs.subfleet_record(JOB) == expected
    assert seen == [["subfleet", "runs", "show", JOB, "--json"]]


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


@given(pieces=st.lists(st.text(max_size=6), min_size=1, max_size=4))
@example(pieces=["\U0001f600", "\u2028\\"])
def test_a_constant_string_folds_to_what_the_script_builds(pieces):
    """Property: a sum of string literals, each written as JSON writes it (escapes JavaScript reads the
    same way, surrogate pairs included), and a template of them both fold to the string they build."""
    template = "`" + "".join("${" + json.dumps(p) + "}" for p in pieces) + "`"
    for expr in (" + ".join(json.dumps(p) for p in pieces), template):
        src = f"x = {expr};".encode()
        tree = acs._JS.parse(src)
        assert not tree.root_node.has_error
        assignment = tree.root_node.named_children[0].named_children[0]
        assert acs._fold(assignment.child_by_field_name("right"), src) == "".join(pieces)


@given(data=st.data())
def test_an_index_that_can_build_a_denied_name_is_flagged(data):
    """Property: split a name the script denies into pieces, write at least one of them out as a string
    and hold the rest in variables; an index with their sum, or with a template of them, is flagged."""
    word = data.draw(st.sampled_from(sorted(acs.SPELLED)))
    cuts = sorted(data.draw(st.sets(st.integers(1, len(word) - 1), max_size=3)))
    pieces = [word[i:j] for i, j in zip([0, *cuts], [*cuts, len(word)])]
    written = data.draw(st.lists(st.booleans(), min_size=len(pieces), max_size=len(pieces)).filter(any))
    parts = [json.dumps(p) if w else f"v{i}" for i, (p, w) in enumerate(zip(pieces, written))]
    held = "".join(f"const v{i} = {json.dumps(p)}; " for i, (p, w) in enumerate(zip(pieces, written)) if not w)
    for key in (" + ".join(parts), "`" + "".join("${" + part + "}" for part in parts) + "`"):
        src = f"{held}const o = {{}}; text(o[{key}]);".encode()
        problems = acs.cell_problems(acs._JS.parse(src), src)
        assert any(problem.startswith("indexes with") for problem in problems), (src, problems)


@settings(deadline=None)
@given(path=st.lists(st.from_regex(r"[A-Za-z0-9._-]{1,8}", fullmatch=True), min_size=1, max_size=5),
       note=st.text(alphabet='M "\\', max_size=6), data=st.data())
def test_discovery_reads_the_work_directory_however_json_spells_it(path, note, data):
    """Property (review finding 2): a log whose first line spells the work directory with any mix of
    escapes (`\\/`, `\\u` in either case), after a string that may escape quotes and backslashes, is
    found, and flagged when it does not parse; one that spells another directory is neither."""
    workdir = "/" + "/".join(path)

    def spelled(text: str) -> str:
        out = []
        for char in text:
            how = data.draw(st.sampled_from(["raw", "unicode", "UNICODE", *(["slash"] if char == "/" else [])]))
            out.append({"raw": char, "slash": "\\/", "unicode": f"\\u{ord(char):04x}",
                        "UNICODE": f"\\u{ord(char):04X}"}[how])
        return '"' + "".join(out) + '"'

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "rollout-MOCK.jsonl"
        for where, named in [(workdir, True), (workdir + "-MOCK", False)]:
            first = ('{"type": "session_meta", "payload": {"note": ' + json.dumps(note) + ', "id": "MOCK-thread", "cwd": '
                     + spelled(where) + ', "source": "exec"}}')
            log.write_text(first + "\n")
            threads, problems = acs.find_threads([log], workdir)
            assert (set(threads) == {"MOCK-thread"}) is named and problems == []
            log.write_text(first[:-3] + "\n")  # cut inside its last string: it does not parse
            threads, problems = acs.find_threads([log], workdir)
            assert threads == {} and len(problems) == int(named)


# What a JavaScript string may escape as the character itself: no escape with a meaning of its own
# (`\b`, `\n`, `\u`...), no digit (an octal escape, which a module refuses) and no line break.
IDENTITY = set("acdeghijklmopqswyzABCDEFGHIJKLMNOPQRSTUVWXYZ./:-_ ")
PLACES = {"open": 'text(await tools.web__run({{open: [{{ref_id: "{}"}}]}}))',
          "search": 'text(await tools.web__run({{search_query: [{{q: "{}"}}]}}))'}
TARGETS = ["https://www.example.org/MOCK", "http://127.0.0.1:8080/MOCK", "http://localhost/MOCK",
           "https://github.com/MaxGhenis/dc-i86-llm-forecast", "file:///etc/hosts", "ftp://MOCK.example.org/MOCK",
           "https://lim s.example.gov/MOCK", "/etc/hosts", "turn0search3"]


@given(target=st.sampled_from(TARGETS), place=st.sampled_from(sorted(PLACES)), data=st.data())
def test_no_escape_hides_what_a_scripts_string_opens(target, place, data):
    """Property (review finding 6): write a script's string with escapes JavaScript reads as the
    character itself, and with line continuations, and the script stays suspect whenever the plain
    string makes it so."""
    choices = data.draw(st.lists(st.sampled_from(["plain", "escaped", "continued"]), min_size=len(target),
                                 max_size=len(target)))
    escaped = "".join("\\" + char if how == "escaped" and char in IDENTITY else
                      char + "\\\n" if how == "continued" else char for char, how in zip(target, choices))

    def verdict(text: str) -> str:
        code = PLACES[place].format(text)
        tree = acs._JS.parse(code.encode())
        assert not tree.root_node.has_error
        return acs.check_script(code, "/MOCK/work", tree)[0]

    if verdict(target) == "suspect":
        assert verdict(escaped) == "suspect", escaped
