"""Audit every Codex thread behind a run from the lanes' session logs: its main thread, the sub-agents
that thread spawned, and every thread of an attempt subfleet made before the one it collected.

On Codex CLI 0.159, `codex exec --json`, which `runs/<label>/transcript.jsonl` records, carries only
the main thread. The sub-agents that thread spawns (`spawn_agent`) run their own web searches and
shell commands, and only the lane's session logs (`$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`)
record them. So `i86 audit`, which reads the transcript, never sees their calls. And when an attempt
fails (the model at capacity, say), subfleet runs the brief again in the same work directory; the
transcript is the collected attempt's alone. For each Codex run this script:

1. finds every thread that worked in the run's work directory: each main thread (a session `codex
   exec` started there) and every thread spawned from one, at any depth, in the lanes' logs and the
   copies already kept (so a rerun after a lane prunes its logs gives the same audit), and checks that
   each thread a log says it started has a log;
2. reads the run's attempts from subfleet (`subfleet runs show JOB --json`) and keeps them in
   `runs/<label>/codex-sessions/attempts.json`, never replacing a different record. Each main thread
   must be the session of one of the job's attempts, each attempt's session must have a log, and the
   collected attempt's main thread must be the thread the committed transcript records. Without
   attempts on record, a run may have one main thread only;
3. copies the logs into `runs/<label>/codex-sessions/`, never replacing a different file. `.gitignore`
   keeps them out of this public repository; `audit.json` records each one's SHA-256;
4. turns each log's completed items into the `codex exec --json` items `i86 audit` reads (web searches,
   shell commands, messages) and audits them with `audit.audit_transcript`, as `i86 audit` audits a
   transcript. The collected main thread's items must match its transcript's, item by item;
5. reads what the items miss. An item records only part of what a `tools.web__run` call opens, nothing
   of what a click opens, and nothing for a call whose cell never finished. So it checks every `exec`
   script's text as a web call's input (each URL in it, each page it opens by `ref_id`, any scheme but
   http(s)), and audits each page the web tool's replies say it served as the item of a call that
   opened it;
6. flags any tool or record it does not read: a script that calls a tool other than `tools.web__run`
   and `tools.exec_command` (code mode's `tools` object also holds the lane account's connector tools,
   such as GitHub's and ChatGPT Space's), reaches `tools` other than as `tools.<name>`, or can spell or
   build code as it runs; a function other than the sub-agent ones and code mode's `wait`; a record,
   event or item of a kind it does not convert; a shell command a script calls with no completed item
   to audit; or a command run outside the work directory;
7. writes `runs/<label>/codex-sessions/audit.json`.

    .venv/bin/python scripts/audit_codex_sessions.py [LABEL ...] [--lanes DIR]

It exits 1 if any thread fails the audit or any check above flags something.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from i86 import audit, runners  # noqa: E402

RUNS = ROOT / "runs"
LANES = Path.home() / ".subfleet" / "lanes"
FOLDER = "codex-sessions"
# What an `exec` script may call: the web, and the shell. Codex 0.159's spec for `exec`: "All nested
# tools are available on the global `tools` object". That object also held the lane account's
# connector tools (GitHub, ChatGPT Space and more), as the scripts that listed `ALL_TOOLS` show.
SCRIPT_TOOLS = {"web__run", "exec_command"}
# The collaboration tools Codex's multi-agent role prompt names, and code mode's `wait`. Codex 0.159's
# spec for `wait`: "`cell_id` identifies the running `exec` cell to resume"; it waits for, or with
# `terminate` stops, a cell an `exec` call started, so the cell's calls are that script's and its items.
FUNCTIONS = {"spawn_agent", "send_message", "followup_task", "wait_agent", "interrupt_agent", "list_agents", "wait"}
SKIPPED_ITEMS = {"UserMessage", "SubAgentActivity"}  # the brief or a thread's message; sub-agent events
# Every `tools` in a script must start a `tools.<name>`; any other (an index, a space or comment before
# the dot, `?.`, an alias, a spread) can call a tool by a name the script builds as it runs.
TOOLS_WORD = re.compile(r"\btools\b")
TOOLS_NAMED = re.compile(r"\btools\.(\w+)\b")
# Text that can spell a name (a `\u` escape), build code as the script runs, reach the global object or
# a module, or call a runtime the isolate lacks ("no Node, no file system, no network access").
SCRIPT_ESCAPES = re.compile(r"\\u|\beval\b|\bFunction\b|\bconstructor\b|\bglobalThis\b|\bimport\b|\brequire\b"
                            r"|\bfs\.|\bDeno\.|\bprocess\.|\bBun\.")
REF_ID = re.compile(r"""\bref_id\s*:\s*(["'`])(.*?)\1""")  # the page a web__run call opens, clicks in or searches
TURN_REF = re.compile(r"turn\d+[a-z]+\d+")  # a page the web tool returned earlier, by its reference
OTHER_SCHEME = re.compile(r"(?i)(?<![a-z0-9+.\-])(?!https?://)[a-z][a-z0-9+.\-]*://|\bfile:")
# A page the web tool's reply says it served: "<title> (<url>) \ue200cite\ue202turn3view0\ue201".
SERVED = re.compile(r"\(([^()\s]+)\)\s*\ue200cite\ue202turn\d+[a-z]+\d+\ue201")
# What a 0.159 session log holds, besides the calls this script reads. Anything else is flagged.
RECORDS = {"session_meta", "event_msg", "response_item", "turn_context", "world_state", "token_usage_record",
           "inter_agent_communication_metadata"}
EVENTS = {"item_completed", "task_started", "task_complete", "turn_aborted", "token_count", "thread_settings_applied"}
RESPONSE_ITEMS = {"message", "reasoning", "agent_message", "custom_tool_call", "custom_tool_call_output",
                  "function_call", "function_call_output"}
# The fields of subfleet's record of an attempt that `attempts.json` keeps.
ATTEMPT_FIELDS = ("attempt_id", "lane_id", "native_session_id", "state", "outcome_class", "outcome_detail",
                  "started_at", "finished_at", "model_served")


def header(path: Path) -> dict:
    """A session log's first record, its `session_meta` payload ({} if it has none). A sub-agent's log
    repeats its parent's `session_meta` second, with the history it was forked from."""
    with path.open() as fh:
        first = json.loads(fh.readline() or "{}")
    return first.get("payload", {}) if first.get("type") == "session_meta" else {}


def spawned_by(meta: dict) -> str | None:
    """The thread that spawned this one, or None for a thread `codex exec` started."""
    src = meta.get("source")
    if isinstance(src, dict):
        return (src.get("subagent") or {}).get("thread_spawn", {}).get("parent_thread_id")
    return None


def find_threads(paths: list[Path], workdir: str) -> dict[str, dict]:
    """Every session log among `paths` whose thread worked in `workdir`, by thread id; a thread's
    first log wins. A log whose first line lacks the work directory as JSON writes it cannot name it
    as its `cwd`, so only the others are parsed (the lanes hold tens of thousands of logs)."""
    needle = json.dumps(workdir, ensure_ascii=False).encode()
    found = {}
    for path in paths:
        try:
            with path.open("rb") as fh:
                if needle not in fh.readline():
                    continue
            meta = header(path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if meta.get("cwd") != workdir or not meta.get("id") or meta["id"] in found:
            continue
        found[meta["id"]] = {"path": path, "spawned_by": spawned_by(meta), "source": meta.get("source"),
                             "started": meta.get("timestamp"), "agent_path": (
                                 ((meta.get("source") or {}).get("subagent") or {}).get("thread_spawn", {})
                                 .get("agent_path") if isinstance(meta.get("source"), dict) else None)}
    return found


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keep(src: Path, dest_dir: Path) -> Path:
    """Copy a log into the run's folder, append-only: an existing copy must match byte for byte."""
    dest = dest_dir / src.name
    if dest.exists():
        if sha256(dest) != sha256(src):
            raise SystemExit(f"{dest} differs from {src}; the kept copy is final")
        return dest
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest


def subfleet_record(job_id: str) -> dict | None:
    """subfleet's record of a job (`subfleet runs show JOB --json`), or None if it has none to give."""
    try:
        proc = subprocess.run(["subfleet", "runs", "show", job_id, "--json"], capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def attempts(run_dir: Path, meta: dict) -> dict | None:
    """The run's subfleet attempts: the copy kept in `attempts.json`, or subfleet's record, kept there.
    A kept copy is final: a different record from subfleet stops the audit. None for a run with no
    job, or none on record."""
    kept = run_dir / FOLDER / "attempts.json"
    job = meta.get("job_id")
    info = subfleet_record(job) if job else None
    fresh = None
    if isinstance(info, dict) and isinstance(info.get("attempts"), list):
        fresh = {"job_id": job, "accepted_attempt_id": (info.get("job") or {}).get("accepted_attempt_id"),
                 "attempts": [{k: a.get(k) for k in ATTEMPT_FIELDS} for a in info["attempts"] if isinstance(a, dict)]}
    if kept.exists():
        old = json.loads(kept.read_text())
        if fresh is not None and fresh != old:
            raise SystemExit(f"{kept} differs from subfleet's record of {job}; the kept copy is final")
        return old
    if fresh is None:
        return None
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps(fresh, indent=1) + "\n")
    return fresh


def local_path(cwd) -> str | None:
    """A CommandExecution's cwd (a file:// URL or a path) as a path."""
    if not isinstance(cwd, str) or not cwd:
        return None
    return unquote(urlparse(cwd).path) if cwd.startswith("file:") else cwd


def web_action(action):
    """A web item's action as `codex exec --json` writes it. The log names the kind in camelCase
    (`openPage`, `findInPage`) and keeps null fields; the transcript's record of the same item, by id,
    names it in snake_case (`open_page`, `find_in_page`) and drops them, and differs in nothing else."""
    if not isinstance(action, dict):
        return action
    out = {k: v for k, v in action.items() if v is not None}
    if isinstance(out.get("type"), str):
        # Each capital after the first character starts a word, as in the names both forms come from.
        out["type"] = re.sub(r"(?<!^)(?=[A-Z])", "_", out["type"]).lower()
    return out


def check_script(code: str, workdir: str) -> tuple[str, str]:
    """The audit's verdict on an `exec` script's text read as a web call's input: every URL in it,
    as `audit` reads a web call's (`_web_hosts`), must name another machine, and none may open this
    repository; each page it opens by `ref_id` must be a web address or a page the web tool returned;
    and it may name no URL but http(s). What a script opens on the web is in its `web__run` arguments,
    which the item for the call records only in part. `audit` gives a web call "web" or "suspect"."""
    verdict, why = audit.check_call("web_search", {"script": code}, Path(workdir), audit.protected_roots())
    if verdict != "web":
        return verdict, why
    for ref in REF_ID.finditer(code):
        if not (re.match(r"(?i)https?://", ref.group(2)) or TURN_REF.fullmatch(ref.group(2))):
            return "suspect", f"opens {ref.group(2)[:80]!r}, neither a web address nor a page the web tool returned"
    if OTHER_SCHEME.search(code):
        return "suspect", "names a URL other than http(s)"
    return "web", ""


def check_page(url: str, workdir: str) -> tuple[str, str]:
    """The audit's verdict on a page the web tool's reply says it served, read as the item of a call
    that opened it: a click's page, and a script's, have no item of their own."""
    return audit.check_call("web_search", {"query": "", "url": url, "action": {"type": "open_page", "url": url}},
                            Path(workdir), audit.protected_roots())


def output_text(output) -> str:
    """A tool output's text: a string, or the text of each part of a list."""
    if isinstance(output, list):
        return "\n".join(str(part.get("text", "")) for part in output if isinstance(part, dict))
    return output if isinstance(output, str) else ""


def convert(path: Path, workdir: str) -> tuple[list[dict], dict]:
    """The log's completed items as `codex exec --json` lines, and what the conversion found."""
    lines: list[dict] = []
    found = {"items": collections.Counter(), "script_tools": collections.Counter(),
             "functions": collections.Counter(), "started_threads": [], "flags": [], "script_suspect": []}
    served: set[str] = set()
    with path.open() as fh:
        for n, raw in enumerate(fh, 1):
            rec = json.loads(raw)
            kind_of_record = rec.get("type")
            payload = rec.get("payload") or {}
            sub = payload.get("type") if isinstance(payload, dict) else None
            if kind_of_record not in RECORDS:
                found["flags"].append(f"line {n}: a {kind_of_record!r} record, which this script does not read")
            elif kind_of_record == "event_msg" and sub not in EVENTS:
                found["flags"].append(f"line {n}: a {sub!r} event, which this script does not read")
            elif kind_of_record == "response_item" and sub not in RESPONSE_ITEMS:
                found["flags"].append(f"line {n}: a {sub!r} response item, which this script does not read")
            if kind_of_record == "response_item" and sub == "custom_tool_call":
                name = payload.get("name")
                if name != "exec":
                    found["flags"].append(f"line {n}: custom tool {name!r}, which this script does not read")
                    continue
                code = str(payload.get("input", ""))
                named = list(TOOLS_NAMED.finditer(code))
                for match in named:
                    found["script_tools"][match.group(1)] += 1
                    if match.group(1) not in SCRIPT_TOOLS:
                        found["flags"].append(f"line {n}: an exec script calls tools.{match.group(1)}")
                starts = {match.start() for match in named}
                if any(match.start() not in starts for match in TOOLS_WORD.finditer(code)):
                    found["flags"].append(f"line {n}: an exec script reaches tools other than by name: {code[:200]!r}")
                if SCRIPT_ESCAPES.search(code):
                    found["flags"].append(f"line {n}: an exec script can spell or build code as it runs, or reach "
                                          f"past its tools: {code[:200]!r}")
                verdict, why = check_script(code, workdir)
                if verdict != "web":
                    found["script_suspect"].append({"tool": "exec script", "call": code[:4000], "why": why})
            elif kind_of_record == "response_item" and sub in ("custom_tool_call_output", "function_call_output"):
                # A script's result, or a running cell's that `wait` returns: the pages the web tool served.
                for url in SERVED.findall(output_text(payload.get("output"))):
                    if url in served:
                        continue
                    served.add(url)
                    verdict, why = check_page(url, workdir)
                    if verdict != "web":
                        found["script_suspect"].append({"tool": "web page", "call": url[:4000], "why": why})
            elif kind_of_record == "response_item" and sub == "function_call":
                name = payload.get("name")
                found["functions"][name] += 1
                if name not in FUNCTIONS:
                    found["flags"].append(f"line {n}: function {name!r}, which this script does not read")
            if kind_of_record != "event_msg" or sub != "item_completed":
                continue
            item = payload.get("item") or {}
            kind = item.get("type")
            found["items"][f"{kind}:{item.get('kind')}" if kind == "Extension" else kind] += 1
            if kind == "Extension" and str(item.get("kind", "")).startswith("web."):
                lines.append({"type": "item.completed", "item": {
                    "id": item.get("id"), "type": "web_search", "query": item.get("query", ""),
                    "action": web_action(item.get("action")), "results": item.get("results")}})
            elif kind == "CommandExecution":
                command = item.get("command")
                cwd = local_path(item.get("cwd"))
                if cwd is not None and cwd.rstrip("/") != workdir.rstrip("/"):
                    found["flags"].append(f"line {n}: a command ran in {cwd}, outside the work directory")
                lines.append({"type": "item.completed", "item": {
                    "id": item.get("id"), "type": "command_execution",
                    "command": shlex.join(command) if isinstance(command, list) else command,
                    "aggregated_output": item.get("aggregated_output", ""),
                    "exit_code": item.get("exit_code"), "status": item.get("status")}})
            elif kind == "AgentMessage":
                text = " ".join(p.get("text", "") for p in item.get("content") or [] if isinstance(p, dict))
                lines.append({"type": "item.completed", "item": {"id": item.get("id"), "type": "agent_message",
                                                                  "text": text}})
            elif kind == "Reasoning":
                lines.append({"type": "item.completed", "item": {"id": item.get("id"), "type": "reasoning",
                                                                  "text": ""}})
            elif kind == "SubAgentActivity":
                if item.get("kind") == "started" and item.get("agent_thread_id"):
                    found["started_threads"].append(item["agent_thread_id"])
            elif kind not in SKIPPED_ITEMS:
                found["flags"].append(f"line {n}: a completed {kind!r} item, which this script does not read")
    # A shell command a script started may have no completed item (its cell stopped first); only the
    # item says what ran, so a script's call without one is flagged.
    if found["script_tools"]["exec_command"] > found["items"]["CommandExecution"]:
        found["flags"].append(f"{found['script_tools']['exec_command']} tools.exec_command calls in exec scripts, "
                              f"{found['items']['CommandExecution']} completed commands")
    found["served_pages"] = len(served)
    return lines, found


def _calls(lines: list[dict]) -> dict[str, list]:
    """Each completed item's calls, as `audit` reads them, by item id. A shell command is compared as
    the words it splits into: the transcript quotes the command the log keeps as a list."""
    out: dict[str, list] = {}
    for line in lines:
        item = line.get("item")
        if line.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if item.get("type") in audit.CODEX_NOT_CALLS:
            continue
        calls = []
        for tool, inp in audit._tool_calls(line):
            if tool == "shell" and isinstance(inp, dict) and isinstance(inp.get("command"), str):
                try:
                    inp = {**inp, "command": shlex.split(inp["command"])}
                except ValueError:
                    pass
            calls.append([tool, json.dumps(inp, sort_keys=True, default=str)])
        out[json.dumps(item.get("id"))] = calls
    return out


def transcript_lines(path: Path) -> list[dict]:
    """A transcript's events (the lines that parse as JSON objects)."""
    lines = []
    for raw in path.read_text(errors="replace").split("\n"):
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines


def check_transcript(transcript: Path, log_lines: list[dict]) -> dict:
    """Whether the committed transcript records the same calls as the main thread's log, item by item."""
    mine, theirs = _calls(log_lines), _calls(transcript_lines(transcript))
    return {"items": len(theirs),
            "only_in_transcript": sorted(k for k in theirs if k not in mine),
            "only_in_log": sorted(k for k in mine if k not in theirs),
            "different": sorted(k for k in theirs if k in mine and theirs[k] != mine[k])}


def audit_thread(path: Path, workdir: str) -> tuple[dict, dict, list[dict]]:
    lines, found = convert(path, workdir)
    with tempfile.TemporaryDirectory() as tmp:
        stream = Path(tmp) / "stream.jsonl"
        stream.write_text("".join(json.dumps(line) + "\n" for line in lines))
        result = audit.audit_transcript(stream, workdir)
    return result, found, lines


def transcript_thread(path: Path) -> str | None:
    """The thread a `codex exec --json` transcript records (its `thread.started` event)."""
    if not path.is_file():
        return None
    return next((str(line.get("thread_id")) for line in transcript_lines(path)
                 if line.get("type") == "thread.started"), None)


def audit_run(run_dir: Path, lanes: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    workdir = meta.get("workdir", "")
    logs = [*sorted(lanes.glob("*/sessions/*/*/*/rollout-*.jsonl")), *sorted((run_dir / FOLDER).glob("rollout-*.jsonl"))]
    threads = find_threads(logs, workdir) if workdir else {}
    roots = sorted((t for t, v in threads.items() if v["spawned_by"] is None), key=lambda t: threads[t]["started"] or "")
    report = {"run": run_dir.name, "workdir": workdir, "threads": [], "missing": [], "flags": [],
              "orphans": sorted(t for t, v in threads.items() if v["spawned_by"] and v["spawned_by"] not in threads)}
    # Which attempt each main thread was, and which one the transcript records.
    record = attempts(run_dir, meta)
    collected = meta.get("attempt_id")
    attempt_of: dict[str, str] = {}
    main = None
    if record is not None:
        report["job_id"] = record.get("job_id")
        report["collected_attempt"] = collected
        if record.get("accepted_attempt_id") != collected:
            report["flags"].append(f"subfleet accepted {record.get('accepted_attempt_id')}, but the run collected {collected}")
        attempt_of = {a["native_session_id"]: a["attempt_id"] for a in record["attempts"] if a.get("native_session_id")}
        for root in roots:
            if root not in attempt_of:
                report["flags"].append(f"main thread {root} in the work directory is no attempt's session")
        report["missing"] += [sid for sid in attempt_of if sid not in threads]
        main = next((sid for sid, aid in attempt_of.items() if aid == collected), None)
        if main is None:
            report["flags"].append(f"subfleet records no session for the collected attempt {collected}")
    elif len(roots) != 1:
        report["flags"].append(f"{len(roots)} threads started by codex exec in the work directory and no attempts "
                               "on record; expected 1")
    else:
        main = roots[0]
    transcript = run_dir / "transcript.jsonl"
    recorded = transcript_thread(transcript)
    if main is not None and recorded != main:
        report["flags"].append(f"the transcript records thread {recorded}, not the collected main thread {main}")
    report["main_thread"] = main if main is not None and recorded == main else None

    def root_of(tid: str) -> str:
        seen = set()
        while threads.get(tid, {}).get("spawned_by") and tid not in seen:
            seen.add(tid)
            tid = threads[tid]["spawned_by"]
        return tid

    started: set[str] = set()
    for tid, info in sorted(threads.items(), key=lambda kv: kv[1]["started"] or ""):
        kept = keep(info["path"], run_dir / FOLDER)
        result, found, lines = audit_thread(kept, workdir)
        started.update(found["started_threads"])
        report["flags"] += [f"{kept.name} {flag}" for flag in found["flags"]]
        if tid == report["main_thread"]:
            check = check_transcript(transcript, lines)
            report["transcript_check"] = check
            if check["only_in_transcript"] or check["only_in_log"] or check["different"]:
                report["flags"].append(f"{kept.name} the log and the committed transcript record different calls")
        root = root_of(tid)
        # `audit` is the audit of the items, as a transcript's; `script_suspect` lists what only the
        # session logs show: the scripts' text and the pages the web tool served, read as web calls.
        report["threads"].append({
            "thread_id": tid, "spawned_by": info["spawned_by"], "agent_path": info["agent_path"],
            "attempt": attempt_of.get(root), "collected": root == report["main_thread"],
            "started": info["started"], "file": f"{FOLDER}/{kept.name}", "sha256": sha256(kept),
            "items": dict(found["items"]), "script_tools": dict(found["script_tools"]),
            "functions": dict(found["functions"]), "served_pages": found["served_pages"], "audit": result,
            "script_suspect": found["script_suspect"]})
    report["missing"] = sorted(set(report["missing"]) | (started - set(threads)))
    report["web_calls"] = sum(t["audit"]["web_calls"] for t in report["threads"])
    report["served_pages"] = sum(t["served_pages"] for t in report["threads"])
    report["commands"] = sum(t["items"].get("CommandExecution", 0) for t in report["threads"])
    report["violations"] = sum(len(t["audit"]["violations"]) for t in report["threads"])
    report["suspect"] = sum(len(t["audit"]["suspect"]) + len(t["script_suspect"]) for t in report["threads"])
    report["passed"] = (bool(report["threads"]) and report["main_thread"] is not None and not report["missing"]
                        and not report["orphans"] and not report["flags"]
                        and all(t["audit"]["passed"] for t in report["threads"]))
    (run_dir / FOLDER).mkdir(parents=True, exist_ok=True)
    (run_dir / FOLDER / "audit.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def codex_runs() -> list[Path]:
    """Collected runs a Codex lane served."""
    out = []
    for d in sorted(RUNS.iterdir()):
        meta_path = d / "meta.json"
        if not meta_path.is_file() or not (d / "response.md").exists():
            continue
        if runners.served_by_codex(json.loads(meta_path.read_text())):
            out.append(d)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("labels", nargs="*", help="runs to audit (default: every collected Codex run)")
    ap.add_argument("--lanes", type=Path, default=LANES, help="the Subfleet lanes folder")
    args = ap.parse_args(argv)
    dirs = [RUNS / label for label in args.labels] if args.labels else codex_runs()
    worst = 0
    for d in dirs:
        r = audit_run(d, args.lanes)
        helpers = sum(1 for t in r["threads"] if t["spawned_by"])
        earlier = sum(1 for t in r["threads"] if not t["collected"])
        print(f"{r['run']}: {'ok' if r['passed'] else 'FAILED'}; {len(r['threads'])} threads ({helpers} sub-agents, "
              f"{earlier} from earlier attempts), {r['web_calls']} web calls, {r['served_pages']} pages served, "
              f"{r['commands']} commands, {r['violations']} violations, {r['suspect']} suspect, "
              f"{len(r['missing'])} missing, {len(r['flags'])} flags")
        for t in r["threads"]:
            for rec in t["audit"]["violations"] + t["audit"]["suspect"] + t["script_suspect"]:
                print(f"    {t['thread_id'][:13]} {rec.get('why', '')}: {rec['call'][:160]}")
        for flag in r["flags"]:
            print(f"    {flag}")
        worst = max(worst, 0 if r["passed"] else 1)
    return worst


if __name__ == "__main__":
    sys.exit(main())
