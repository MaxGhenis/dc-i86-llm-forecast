"""Command line: i86 prompt | dispatch | collect | abandon | recover | check | audit | simulate | prereg.

    i86 prompt                      write prompts/forecaster.md and schemas/template.json
    i86 dispatch subfleet LABEL --tier standard -m opus      (or --tier hard, no -m, for GPT-6.1 Sol)
    i86 dispatch claude LABEL -m claude-opus-5-5
    i86 collect                     refresh subfleet runs; fetch answers once all have finished
    i86 abandon LABEL               mark a run that will never finish (final)
    i86 recover LABEL               take a lost subfleet run's final message from its own transcript
    i86 check                       parse every runs/*/response.md into runs/*/response.json
    i86 audit                       check each run's transcript for local file reads
    i86 simulate [--n 20000 --seed 0]
                                    pool the accepted runs into outputs/
    i86 prereg                      hash the prompt, graph, runs and outputs into prereg/SHA256SUMS
                                    and request an OpenTimestamps proof
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import audit, graph as graph_mod, prompt, report, runners
from .graph import ROOT
from .response import ResponseError, extract_json, parse, template
from .summarize import pool

PROMPT_PATH = ROOT / "prompts" / "forecaster.md"
# A forecaster's prior_context that mentions these questions, other than a bare "none", means it saw
# something beyond the brief.
DISCLOSURE = re.compile(r"foie|initiative.?86|\bi-?86\b|force.?fe", re.I)
BARE_NONE = re.compile(r"\W*(?:none|nothing|n/?a)\W*", re.I)


def discloses(prior_context) -> bool:
    text = str(prior_context or "")
    return not BARE_NONE.fullmatch(text) and bool(DISCLOSURE.search(text))
TEMPLATE_PATH = ROOT / "schemas" / "template.json"
OUTPUTS = ROOT / "outputs"


def cmd_prompt(args) -> int:
    g = graph_mod.load()
    sha = prompt.write(g, PROMPT_PATH)
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATE_PATH.write_text(json.dumps(template(g), indent=1) + "\n")
    (PROMPT_PATH.parent / "forecaster.md.sha256").write_text(f"{sha}  forecaster.md\n")
    print(f"{PROMPT_PATH.relative_to(ROOT)} sha256 {sha}")
    return 0


def _prompt_sha() -> str:
    g = graph_mod.load()
    text = prompt.build(g)
    if PROMPT_PATH.read_text() != text:
        raise SystemExit("prompts/forecaster.md is stale; run `i86 prompt` and commit it first")
    return prompt.sha256(text)


def cmd_dispatch(args) -> int:
    sha = _prompt_sha()
    if args.backend == "subfleet":
        meta = runners.dispatch_subfleet(args.label, PROMPT_PATH, sha, args.tier, args.model, args.late)
    elif args.backend == "claude":
        meta = runners.dispatch_claude(args.label, PROMPT_PATH, sha, args.model or "claude-opus-5-5", args.late)
    else:
        runners.prepare(args.label, PROMPT_PATH, sha, "manual", late=args.late)
        print(f"runs/{args.label}/prompt.md is ready; save the agent's final message as "
              f"{runners.staged_response(args.label)}")
        return 0
    print(json.dumps({k: meta.get(k) for k in ("label", "job_id", "backend", "dispatched_at")}))
    return 0


def run_dirs() -> list[Path]:
    return runners.run_dirs()


def cmd_collect(args) -> int:
    """Refresh every subfleet run; copy answers in only once every run, of any backend, has finished.

    The whole check-and-copy holds the runs' lock, so no dispatch can start a run in between; before
    copying, the runs are listed again and must match what was checked."""
    with runners.bookkeeping_lock():
        dirs = run_dirs()
        metas = {d: (runners.refresh_subfleet(d) if runners.read_meta(d).get("backend") == "subfleet"
                     else runners.read_meta(d)) for d in dirs}
        pending = [d.name for d, m in metas.items() if runners.still_going(m)]
        unknown = {m.get("state") for m in metas.values() if m.get("backend") == "subfleet"} - runners.FINISHED - {
            "queued", "waiting", "running", None}
        if unknown:
            print(f"unknown subfleet state(s) {sorted(unknown)}: treated as still going", file=sys.stderr)
        if not pending:
            now_dirs = runners.run_dirs()
            pending = [d.name for d in now_dirs if d not in metas or runners.still_going(runners.read_meta(d))]
            for d in now_dirs:
                metas.setdefault(d, runners.read_meta(d))
        if not pending:
            for d in dirs:
                runners.seal(d)
    for d, meta in metas.items():
        have = (d / "response.md").exists()
        print(f"{d.name:24s} {meta.get('state') or '-':10s} {meta.get('model_served') or '-':18s} response={'yes' if have else 'no'}")
    if pending:
        print(f"{len(pending)} run(s) still going ({', '.join(pending)}); no answers copied yet. "
              "`i86 abandon <label>` marks a run that will never finish; `i86 recover <label>` takes a lost "
              "subfleet run's answer from its transcript")
    return 0


def cmd_abandon(args) -> int:
    meta = runners.abandon(args.label)
    print(f"{args.label}: abandoned at {meta['abandoned_at']}")
    return 0


def cmd_recover(args) -> int:
    meta = runners.recover(args.label)
    print(f"{args.label}: recovered from {meta['attempt_id']} (subfleet: {meta['backend_state']})")
    return 0


def cmd_check(args) -> int:
    g = graph_mod.load()
    bad = 0
    for d in run_dirs():
        src = d / "response.md"
        if not src.exists():
            continue
        try:
            obj = extract_json(src.read_text())
            parse(g, obj)
        except ResponseError as exc:
            bad += 1
            (d / "problems.txt").write_text("\n".join(exc.problems) + "\n")
            print(f"{d.name}: {len(exc.problems)} problem(s); see runs/{d.name}/problems.txt")
            continue
        (d / "response.json").write_text(json.dumps(obj, indent=1) + "\n")
        (d / "problems.txt").unlink(missing_ok=True)
        print(f"{d.name}: ok")
    return 1 if bad else 0


def cmd_audit(args) -> int:
    worst = 0
    for d in run_dirs():
        meta = runners.read_meta(d)
        if not (d / "response.md").exists() or meta.get("backend") == "manual":
            continue
        # Only the committed copy, which prereg hashes: a collected run without one fails, since the
        # job store's copy can change after collection.
        path = d / "transcript.jsonl"
        if not path.is_file():
            result = {"events": 0, "passed": False, "violations": [], "web_calls": 0, "local_calls": [],
                      "suspect": [], "error": f"no committed transcript at runs/{d.name}/transcript.jsonl"}
        else:
            result = audit.audit_transcript(path, meta.get("workdir", ""))
        (d / "audit.json").write_text(json.dumps(result, indent=1) + "\n")
        flag = "ok" if result["passed"] else ("VIOLATION" if result["violations"] else "NO EVENTS")
        worst = max(worst, 0 if result["passed"] else 1)
        print(f"{d.name}: {flag}; {result['events']} events, {result['web_calls']} web calls, "
              f"{len(result['suspect'])} suspect, {len(result['local_calls'])} other local calls")
        for rec in result["violations"] + result["suspect"]:
            print(f"    {rec.get('why', '')}: {rec['call'][:160]}")
    return worst


def _audit_record(result) -> bool:
    """Whether an audit.json holds what `audit_transcript` writes: whether the run passed, and its
    violations and suspect calls as lists. A record without them (damaged, cut short so that it is
    not JSON, or an older audit's) keeps its run out of the pool, as no audit does."""
    return (isinstance(result, dict) and isinstance(result.get("passed"), bool)
            and isinstance(result.get("violations"), list) and isinstance(result.get("suspect"), list))


SESSIONS = "codex-sessions"
# What a passing audit of a Codex run's session logs records, as `scripts/audit_codex_sessions.py`
# writes it, and the most levels its JSON nests (it writes six or so). A test checks these against the
# script's own tables.
DEPTH = 64
SCRIPT_TOOLS = frozenset({"web__run", "exec_command"})  # what a script may call
FUNCTIONS = frozenset({"spawn_agent", "send_message", "followup_task", "wait_agent", "interrupt_agent",
                       "list_agents", "wait"})  # what a thread may call, each in its own namespace
# The items the script turns into one line each of the stream it audits (and each web search, an
# `Extension:web.` item), and those it reads and passes over.
LINE_ITEMS = frozenset({"CommandExecution", "AgentMessage", "Reasoning"})
QUIET_ITEMS = frozenset({"UserMessage", "SubAgentActivity"})
RECORD_KEYS = frozenset({"run", "workdir", "threads", "missing", "flags", "orphans", "main_thread",
                         "transcript_check", "web_calls", "served_pages", "commands", "violations", "suspect",
                         "passed"})
THREAD_KEYS = frozenset({"thread_id", "spawned_by", "agent_path", "attempt", "collected", "started", "file",
                         "sha256", "items", "script_tools", "functions", "served_pages", "audit", "script_suspect"})
AUDIT_KEYS = frozenset({"events", "tool_calls", "web_calls", "urls", "violations", "suspect", "local_calls",
                        "passed"})
CHECK_KEYS = frozenset({"items", "only_in_transcript", "only_in_log", "different"})
ABSENT, UNREADABLE = object(), object()


def _nests_deeper_than(value, levels: int) -> bool:
    """Whether a JSON value nests objects and arrays more than `levels` deep, found without recursion."""
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, (dict, list)):
            if depth == levels:
                return True
            stack.extend((child, depth + 1) for child in (node.values() if isinstance(node, dict) else node))
    return False


def _json_file(path: Path):
    """The JSON value a file holds; ABSENT if nothing is at `path`; UNREADABLE if what is there is not a
    regular file (a folder, or a pipe that would block), cannot be read or decoded, does not parse, or
    nests more than DEPTH levels."""
    if not os.path.lexists(path):
        return ABSENT
    if not os.path.isfile(path):
        return UNREADABLE
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, RecursionError):
        return UNREADABLE
    return UNREADABLE if _nests_deeper_than(value, DEPTH) else value


def _session_audit(run_dir: Path):
    """A Codex run's audit of every thread of every attempt, sub-agents included
    (`scripts/audit_codex_sessions.py`): the record; None if the run has none; "unreadable" if it is
    not such a record or is another run's; or, for a record that says it passed but does not hold up
    (`_session_problem`), why not."""
    rec = _json_file(run_dir / SESSIONS / "audit.json")
    if rec is ABSENT:
        return None
    ok = (isinstance(rec, dict) and rec.get("run") == run_dir.name and isinstance(rec.get("passed"), bool)
          and isinstance(rec.get("threads"), list)
          and all(isinstance(t, dict) and isinstance(t.get("thread_id"), str) and t["thread_id"]
                  and (t.get("spawned_by") is None or isinstance(t["spawned_by"], str))
                  and isinstance(t.get("audit"), dict)
                  and all(isinstance(calls, list) and all(isinstance(call, dict) for call in calls)
                          for calls in (t["audit"].get("suspect"), t.get("script_suspect")))
                  for t in rec["threads"]))
    if not ok:
        return "unreadable"
    return (_session_problem(run_dir, rec) or rec) if rec["passed"] else rec


def _transcript_thread(path: Path) -> str | None:
    """The thread a `codex exec --json` transcript records (its first `thread.started` event), or None
    if it records none or one whose id is not a string."""
    if not path.is_file():  # not a folder, or a pipe that would block
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    for raw in text.split("\n"):
        try:
            line = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        if isinstance(line, dict) and not _nests_deeper_than(line, DEPTH) and line.get("type") == "thread.started":
            tid = line.get("thread_id")
            return tid if isinstance(tid, str) else None
    return None


def _counts(value) -> bool:
    """Whether a value is a table of counts: whole numbers of zero or more."""
    return isinstance(value, dict) and all(type(v) is int and v >= 0 for v in value.values())


def _calls_listed(records, fields: frozenset) -> bool:
    """Whether a value lists calls as the audits write them: objects with a tool and a call and no field
    outside `fields`, each a string."""
    return isinstance(records, list) and all(
        isinstance(r, dict) and {"tool", "call"} <= set(r) <= fields and all(isinstance(v, str) for v in r.values())
        for r in records)


def _searches(items: dict) -> int:
    """A thread's web searches: its items of an `Extension:web.` kind."""
    return sum(n for kind, n in items.items() if kind.startswith("Extension:web."))


def _thread_problem(t: dict) -> str | None:
    """Why one thread's entry in a session audit that passed does not hold up, or None. It must have the
    fields the script writes, of their types: a file that names a log straight under the run's
    `codex-sessions`, as the script names each kept log, a SHA-256, and calls in the form the audits
    write them. Its own audit must count the events and calls its items make: the script turns each web
    search, command, message and reasoning item into one line of the stream it audits, and `audit` reads
    one call from each search and command. `audit` lists each call it does not
    read as a web call, or counts it as neither, and gives each web call one address or more. And the
    thread's scripts may call the shell no more often than its commands completed."""
    items, own = t["items"], t["audit"]
    if set(t) != THREAD_KEYS or set(own) != AUDIT_KEYS:
        return "one thread's entry or its audit has other fields than the script writes"
    if not (all(t[key] is None or isinstance(t[key], str) for key in ("agent_path", "started"))
            and isinstance(t["file"], str) and re.fullmatch(r"codex-sessions/rollout-[^/]*\.jsonl", t["file"])
            and isinstance(t["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", t["sha256"])):
        return "one thread gives an agent path, a start time, a file or a SHA-256 the script does not write"
    if not (_calls_listed(own["suspect"], frozenset({"tool", "call", "why"}))
            and _calls_listed(own["local_calls"], frozenset({"tool", "call", "why"}))
            and _calls_listed(t["script_suspect"], frozenset({"tool", "call", "why"}))
            and all(set(r) == {"tool", "call", "why"} for r in t["script_suspect"])):
        return "one thread lists a call other than as the audits list one"
    calls = _searches(items) + items.get("CommandExecution", 0)
    if own["events"] != calls + items.get("AgentMessage", 0) + items.get("Reasoning", 0) or not (
            type(own["tool_calls"]) is int and own["tool_calls"] == calls):
        return "one thread's audit counts other events or calls than its items make"
    urls = own["urls"]
    if not (own["web_calls"] + len(own["suspect"]) + len(own["local_calls"]) <= own["tool_calls"]
            and isinstance(urls, list) and all(isinstance(u, str) for u in urls) and urls == sorted(set(urls))
            and bool(urls) == (own["web_calls"] > 0)):
        return "one thread's audit lists more calls than it read, or web addresses that do not match its web calls"
    if t["script_tools"].get("exec_command", 0) > items.get("CommandExecution", 0):
        return "one thread's scripts call the shell more often than its commands completed"
    return None


def _session_problem(run_dir: Path, rec: dict) -> str | None:
    """Why a session audit that says it passed does not hold up, or None. The gate reads the verdict again
    rather than trust it: the run's own work directory, an absolute path; no flags, missing threads or
    orphans; each thread with an id of its own, counts of zero or more, and it passed its own audit,
    which reads one event or more and finds no violation; no item, script tool or function the script
    fails a run for; each parent among the threads, every thread descended from a main thread with no
    cycle, each thread's `spawn_agent` calls as many as the threads that name it as their parent, and
    as many sub-agent events or more; totals that add up; each thread's fields and counts as
    `_thread_problem` reads them; as its main thread, a thread `codex exec` started, the one the
    transcript records; a check of the transcript that compared each of the main thread's searches and
    commands and found the same calls in it and in the main thread's log; and each thread marked as
    collected exactly when it descends from the main thread, and with the attempt whose session it
    descends from. With attempts on record (`attempts.json`), they must be the job's attempts a1, a2 and
    on, the job meta.json's and the audit's, and meta.json's attempt must be the one subfleet accepted
    and the audit names, with the main thread as its session; each attempt that started must name its
    own session among the threads, a main thread, and each main thread must be an attempt's session.
    With none, the run has one main thread, from the job's first attempt. Last, the record must have the
    fields the script writes, and no others."""
    meta = runners.read_meta(run_dir)
    threads = rec["threads"]
    parent = {t["thread_id"]: t.get("spawned_by") for t in threads}
    ids = set(parent)
    workdir = meta.get("workdir")
    if not (isinstance(workdir, str) and workdir.startswith("/") and rec.get("workdir") == workdir):
        return "it does not audit the run's work directory, an absolute path"
    for key in ("flags", "missing", "orphans"):
        if rec.get(key) != []:
            return f"its {key!r} field is not an empty list"
    if len(ids) != len(threads):
        return "two of its threads share an id"
    if not all(t["audit"].get("passed") is True and t["audit"].get("violations") == []
               and type(t["audit"].get("events")) is int and t["audit"]["events"] > 0 for t in threads):
        return "one thread's own audit failed: it found a violation or read no events"
    if not all(_counts(t.get(key)) for t in threads for key in ("items", "script_tools", "functions")):
        return "one thread's counts are not whole numbers of zero or more"
    if not all(set(t["script_tools"]) <= SCRIPT_TOOLS and set(t["functions"]) <= FUNCTIONS
               and all(kind in LINE_ITEMS or kind in QUIET_ITEMS or kind.startswith("Extension:web.")
                       for kind in t["items"]) for t in threads):
        return "one thread records an item, a script's tool or a function for which the script fails a run"
    if any(p is not None and p not in ids for p in parent.values()):
        return "one thread's parent is not among its threads"
    root = {}
    for tid in parent:
        seen, top = set(), tid
        while parent[top] is not None:
            if top in seen:
                return "its threads' parents form a cycle"
            seen.add(top)
            top = parent[top]
        root[tid] = top
    children = collections.Counter(parent.values())
    if any(t["functions"].get("spawn_agent", 0) != children[t["thread_id"]] for t in threads):
        return "one thread's spawn_agent calls do not match the threads that name it as their parent"
    if any(t["items"].get("SubAgentActivity", 0) < children[t["thread_id"]] for t in threads):
        return "one thread records fewer sub-agent events than the threads that name it as their parent"

    def total(values) -> int | None:
        return sum(values) if all(type(v) is int and v >= 0 for v in values) else None

    totals = {"web_calls": total([t["audit"].get("web_calls") for t in threads]),
              "served_pages": total([t.get("served_pages") for t in threads]),
              "commands": total([t["items"].get("CommandExecution", 0) for t in threads]),
              "violations": 0, "suspect": sum(len(t["audit"]["suspect"]) + len(t["script_suspect"]) for t in threads)}
    for key, value in totals.items():
        if value is None or type(rec.get(key)) is not int or rec[key] != value:
            return f"its {key} do not add up over its threads"
    for t in threads:
        problem = _thread_problem(t)
        if problem:
            return problem
    main = rec.get("main_thread")
    if not isinstance(main, str) or main not in ids:
        return "it names no main thread among its threads"
    if parent[main] is not None:
        return "its main thread is a sub-agent"
    if main != _transcript_thread(run_dir / "transcript.jsonl"):
        return "its main thread is not the thread the transcript records"
    check = rec.get("transcript_check")
    if not (isinstance(check, dict) and type(check.get("items")) is int and check["items"] >= 0
            and all(check.get(key) == [] for key in ("only_in_transcript", "only_in_log", "different"))):
        return "its check of the transcript is missing or found calls that differ from the main thread's log"
    if set(check) != CHECK_KEYS:
        return "its check of the transcript has other fields than the script writes"
    main_items = next(t["items"] for t in threads if t["thread_id"] == main)
    if check["items"] != _searches(main_items) + main_items.get("CommandExecution", 0):
        return "its check of the transcript compared another number of items than the main thread's log holds"
    roots = {tid for tid, p in parent.items() if p is None}
    collected = meta.get("attempt_id")
    record = _json_file(run_dir / SESSIONS / "attempts.json")
    if record is ABSENT:
        if len(roots) != 1:
            return f"it has no attempts on record and {len(roots)} main threads"
        if collected is not None and not str(collected).endswith("/a1"):
            return f"it has no attempts on record, and the run collected {collected}, not its job's first attempt"
        attempt_of = {}
    else:
        if record is UNREADABLE:
            return "its attempts.json is not a file of JSON this check can read"
        listed = record.get("attempts") if isinstance(record, dict) else None
        if not isinstance(listed, list) or not all(isinstance(a, dict) for a in listed):
            return "its attempts.json lists no attempts"
        if not all(isinstance(a.get("attempt_id"), str)
                   and (a.get("native_session_id") is None or isinstance(a["native_session_id"], str))
                   for a in listed):
            return "its attempts.json gives an attempt an id or a session that is not a string"
        job = meta.get("job_id")
        if record.get("job_id") != job or sorted(a["attempt_id"] for a in listed) != sorted(
                f"{job}/a{i}" for i in range(1, len(listed) + 1)):
            return f"its attempts.json does not list the attempts of job {job} from a1 up"
        if rec.get("job_id") != job:
            return f"it names job {str(rec.get('job_id'))[:200]}, not the run's job {job}"
        if record.get("accepted_attempt_id") != collected or rec.get("collected_attempt") != collected:
            return f"the run collected {collected}, not the attempt subfleet accepted and the audit names"
        sessions = {a["attempt_id"]: a.get("native_session_id") for a in listed}
        if sessions.get(collected) != main:
            return "its main thread is not the collected attempt's session"
        if any((a.get("native_session_id") or a.get("started_at")) and a.get("native_session_id") not in ids
               for a in listed):
            return "an attempt that started names no session among its threads"
        named = [a["native_session_id"] for a in listed if a.get("native_session_id")]
        if len(set(named)) != len(named):
            return "two attempts name the same session"
        if not set(named) <= roots:
            return "an attempt's session is a sub-agent, not a main thread"
        if not roots <= set(named):
            return "a main thread among its threads is no attempt's session"
        attempt_of = {a["native_session_id"]: a["attempt_id"] for a in listed if a.get("native_session_id")}
    if any(t.get("collected") is not (root[t["thread_id"]] == main) for t in threads):
        return "one thread is marked collected though it does not descend from the main thread, or the reverse"
    if any(t.get("attempt") != attempt_of.get(root[t["thread_id"]]) for t in threads):
        return "one thread names an attempt other than the one whose session it descends from"
    if set(rec) != RECORD_KEYS | (set() if record is ABSENT else {"job_id", "collected_attempt"}):
        return "it has other fields than the script writes"
    return None


def _hidden_suspects(session: dict) -> list:
    """The suspect calls of every thread but the collected main thread: its sub-agents', and every
    thread of an earlier attempt. Only the session logs record them; the transcript audit never sees them."""
    return [call for t in session["threads"] if t.get("thread_id") != session.get("main_thread")
            for call in (*t["audit"]["suspect"], *t["script_suspect"])]


def _codex_suspects(transcript: list, session: dict) -> list:
    """A Codex run's suspect calls. Its transcript and its session logs both record the collected main
    thread's items, so those come from whichever audit lists more. Only the session audit reads that
    thread's scripts and the pages the web tool served it (`script_suspect`), and the other threads."""
    main = [t for t in session["threads"] if t.get("thread_id") == session.get("main_thread")]
    items = [call for t in main for call in t["audit"]["suspect"]]
    scripts = [call for t in main for call in t["script_suspect"]]
    return [*max(transcript, items, key=len), *scripts, *_hidden_suspects(session)]


def accepted_runs(g, prompt_sha: str, allow_unaudited: bool = False, accept_prior: set[str] = frozenset(),
                  accept_suspect: set[str] = frozenset()) -> dict:
    """Runs with a parsed response, the current prompt's hash, a passing audit with no suspect calls
    and no prior context about these questions; a Codex run also needs a passing audit of its session
    logs, whose other threads' suspect calls count with the rest. The operator may read a run's suspect
    calls, or its prior context, and list it in `accept_suspect` or `accept_prior` to pool it anyway."""
    runs = {}
    for d in run_dirs():
        resp = d / "response.json"
        if not resp.exists():
            continue
        meta = runners.read_meta(d)
        if meta.get("prompt_sha256") != prompt_sha:
            print(f"excluding {d.name}: made with prompt {str(meta.get('prompt_sha256'))[:12]}, not {prompt_sha[:12]}",
                  file=sys.stderr)
            continue
        audit_path = d / "audit.json"
        try:
            result = json.loads(audit_path.read_text()) if audit_path.exists() else None
        except (ValueError, RecursionError):
            result = "unreadable"  # not an audit record (below)
        if result is None and not (allow_unaudited and meta.get("backend") == "manual"):
            print(f"excluding {d.name}: no audit (run `i86 audit`; manual runs need --allow-unaudited)",
                  file=sys.stderr)
            continue
        if result is not None and not _audit_record(result):
            print(f"excluding {d.name}: audit.json is not an audit record (run `i86 audit` again)", file=sys.stderr)
            continue
        if result is not None and not (result["passed"] and not result["violations"]):
            print(f"excluding {d.name}: audit failed", file=sys.stderr)
            continue
        suspect = result["suspect"] if result is not None else []
        if runners.served_by_codex(meta):
            session = _session_audit(d)
            if session is None or session == "unreadable":
                print(f"excluding {d.name}: no readable audit of its session logs (run "
                      f"scripts/audit_codex_sessions.py {d.name})", file=sys.stderr)
                continue
            if isinstance(session, str):
                print(f"excluding {d.name}: the audit of its session logs says it passed, but {session} (run "
                      f"scripts/audit_codex_sessions.py {d.name})", file=sys.stderr)
                continue
            if not session["passed"] or session.get("violations"):
                print(f"excluding {d.name}: the audit of its session logs failed (read runs/{d.name}/{SESSIONS}/"
                      f"audit.json)", file=sys.stderr)
                continue
            suspect = _codex_suspects(suspect, session)
        if suspect and d.name not in accept_suspect:
            print(f"excluding {d.name}: {len(suspect)} suspect call(s) (read them in runs/{d.name}/audit.json and, "
                  f"for a Codex run, {SESSIONS}/audit.json; --accept-suspect {d.name} to include)", file=sys.stderr)
            continue
        fc = parse(g, json.loads(resp.read_text()))
        disclosed = str(fc.forecaster.get("prior_context") or "")
        if discloses(disclosed) and d.name not in accept_prior:
            print(f"excluding {d.name}: prior context mentions these questions (read it; --accept-prior "
                  f"{d.name} to include): {disclosed[:200]}", file=sys.stderr)
            continue
        runs[d.name] = fc
    return runs


def cmd_simulate(args) -> int:
    g = graph_mod.load()
    runs = accepted_runs(g, _prompt_sha(), args.allow_unaudited, set(args.accept_prior), set(args.accept_suspect))
    if not runs:
        raise SystemExit("no accepted runs: dispatch, collect and check first")
    result = pool(g, runs, n=args.n, seed=args.seed)
    meta = {d.name: runners.read_meta(d) for d in run_dirs() if d.name in runs}
    for rid, m in meta.items():
        m["prior_context"] = runs[rid].forecaster.get("prior_context")
        audit_path = runners.RUNS / rid / "audit.json"
        suspect = json.loads(audit_path.read_text()).get("suspect", []) if audit_path.exists() else None
        session = _session_audit(runners.RUNS / rid) if runners.served_by_codex(m) else None
        if isinstance(session, dict):
            suspect = _codex_suspects(suspect or [], session)
        if suspect is not None:
            m["suspect_calls"] = len(suspect)
    report.write(g, result, meta, OUTPUTS)
    print(f"pooled {len(runs)} run(s) into {OUTPUTS.relative_to(ROOT)}/")
    return 0


PREREG = ROOT / "prereg"


def _keeps(folder: Path, sums: Path, proof: Path) -> bool:
    """Whether a dated folder holds the same manifest and proof as `prereg/`, byte for byte."""
    return all((folder / p.name).is_file() and p.is_file() and (folder / p.name).read_bytes() == p.read_bytes()
               for p in (sums, proof))


def _files(paths) -> list[Path]:
    """The paths at which there is something for prereg to hash. Anything there but a regular file (a
    folder, a pipe that would block, a link to nothing) stops prereg."""
    present = [p for p in paths if os.path.lexists(p)]
    for p in present:
        if not os.path.isfile(p):
            raise SystemExit(f"{p.relative_to(ROOT)} is not a regular file, so prereg cannot hash it")
    return present


def _sha256(p: Path) -> str:
    """A file's SHA-256 for prereg's manifest. A file prereg cannot read stops it, by name."""
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError as error:
        raise SystemExit(f"prereg cannot read {p.relative_to(ROOT)} ({type(error).__name__})") from None


def cmd_prereg(args) -> int:
    files = [ROOT / "graph" / "graph.yaml", PROMPT_PATH, TEMPLATE_PATH, *sorted((ROOT / "context").iterdir())]
    for d in run_dirs():
        files += _files((d / "meta.json", d / "response.md", d / "response.json", d / "audit.json",
                         d / "transcript.jsonl"))
        # A Codex run's audit of its session logs (scripts/audit_codex_sessions.py) and its attempts. The
        # logs stay out of this public repository; the audit records each one's SHA-256.
        files += _files((d / SESSIONS / "audit.json", d / SESSIONS / "attempts.json"))
    files += sorted(p for p in OUTPUTS.glob("*") if p.is_file())
    lines = [f"{_sha256(p)}  {p.relative_to(ROOT)}" for p in files]
    PREREG.mkdir(exist_ok=True)
    sums, proof = PREREG / "SHA256SUMS", PREREG / "SHA256SUMS.ots"
    # The previous proof stamps the previous manifest. `ots stamp` will not overwrite it, and left in
    # place it would sit beside a manifest it does not prove, so it goes; but first a dated folder must
    # keep both, byte for byte, or the proof would survive only in git's history.
    if proof.exists() and not any(_keeps(d, sums, proof) for d in PREREG.iterdir() if d.is_dir()):
        raise SystemExit(f"{proof.relative_to(ROOT)} and its manifest are in no dated folder: copy both into "
                         f"{PREREG.relative_to(ROOT)}/<date>-<name>/ and run prereg again")
    sums.write_text("\n".join(lines) + "\n")
    proof.unlink(missing_ok=True)
    print(f"{len(lines)} files hashed into {sums.relative_to(ROOT)}")
    if args.no_stamp:
        return 0
    proc = subprocess.run(["uvx", "--from", "opentimestamps-client", "ots", "stamp", str(sums)],
                          capture_output=True, text=True)
    print(proc.stdout + proc.stderr)
    return proc.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="i86", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prompt")
    d = sub.add_parser("dispatch")
    d.add_argument("backend", choices=["subfleet", "claude", "manual"])
    d.add_argument("label")
    d.add_argument("--tier", default="standard", choices=["standard", "hard"])
    d.add_argument("-m", "--model")
    d.add_argument("--late", action="store_true", help="dispatch after answers were collected (flagged in the report)")
    sub.add_parser("collect")
    sub.add_parser("check")
    sub.add_parser("audit")
    ab = sub.add_parser("abandon", help="mark a run that will never finish, so collection can proceed")
    ab.add_argument("label")
    rc = sub.add_parser("recover", help="take a lost subfleet run's final message from its own transcript")
    rc.add_argument("label")
    s = sub.add_parser("simulate")
    s.add_argument("--n", type=int, default=20000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--allow-unaudited", action="store_true",
                   help="pool manual runs, which have no transcript to audit")
    s.add_argument("--accept-prior", action="append", default=[], metavar="LABEL",
                   help="pool this run although its prior_context mentions these questions (read it first)")
    s.add_argument("--accept-suspect", action="append", default=[], metavar="LABEL",
                   help="pool this run although its audit lists suspect calls (read them first)")
    pr = sub.add_parser("prereg")
    pr.add_argument("--no-stamp", action="store_true")
    args = ap.parse_args(argv)
    return {"prompt": cmd_prompt, "dispatch": cmd_dispatch, "collect": cmd_collect, "check": cmd_check,
            "audit": cmd_audit, "abandon": cmd_abandon, "recover": cmd_recover, "simulate": cmd_simulate, "prereg": cmd_prereg}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
