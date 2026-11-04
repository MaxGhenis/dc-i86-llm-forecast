"""Audit every Codex thread behind a run from the lanes' session logs: its main thread, the sub-agents
that thread spawned, and every thread of an attempt subfleet made before the one it collected.

On Codex CLI 0.159, `codex exec --json`, which `runs/<label>/transcript.jsonl` records, carries only
the main thread. The sub-agents that thread spawns (`spawn_agent`) run their own web searches and
shell commands, and only the lane's session logs (`$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`)
record them. So `i86 audit`, which reads the transcript, never sees their calls. And when an attempt
fails (the model at capacity, say), subfleet runs the brief again in the same work directory; the
transcript is the collected attempt's alone. For each Codex run this script:

1. finds every thread that started in the run's work directory: each main thread (a session
   `codex exec` started there) and every thread spawned from one, at any depth, in the lanes' logs and
   the copies already kept (so a rerun after a lane prunes its logs gives the same audit). Each thread
   a log says it started must have a log, each thread's `spawn_agent` calls must match the sub-agents
   it started and the threads that name it as their parent, each thread must descend from a main thread
   with no cycle, and two logs of one thread must hold the same bytes. A thread started there when its
   log's first line is a session's record whose `cwd` is the work directory, however its JSON spells
   it, once both paths are normalized. This script compares paths as text, so it misses a thread whose
   log records another path to the folder, such as a symlink to it. A log this script cannot open is
   flagged; so is one that names the work directory anywhere (as UTF-8, UTF-16 or UTF-32 text, with
   JSON's escapes such as `\\/` and `\\u002f` decoded) though its first line says nothing of where its
   thread started, a session in a path that names the work directory but is another, and a session
   there that gives no thread id or a source or start time this script cannot read;
2. reads the run's attempts from subfleet (`subfleet runs show JOB --json`) and keeps them in
   `runs/<label>/codex-sessions/attempts.json`, never replacing a different record. The record must
   list the job's attempts a1, a2 and on. Each main thread must be the session of one of them, each
   attempt that started must name a session of its own with a log, a main thread, and the collected
   attempt's main thread must be the thread the committed transcript records. Without attempts on
   record, a run may have one main thread only, and must have collected its job's first attempt;
3. copies the logs into `runs/<label>/codex-sessions/`, never replacing a different file. `.gitignore`
   keeps them out of this public repository; `audit.json` records each one's SHA-256;
4. turns each log's completed items into the `codex exec --json` items `i86 audit` reads (web searches,
   shell commands, messages) and audits them with `audit.audit_transcript`, as `i86 audit` audits a
   transcript. The collected main thread's items must match its transcript's, item by item;
5. reads what the items miss. An item records only part of what a `tools.web__run` call opens, nothing
   of what a click opens, and nothing for a call whose cell never finished. So it checks every `exec`
   script's text, and each string the script writes out or builds from constants with its escapes
   decoded, as a web call's input (each URL; each page it opens by `ref_id`, which must be one string
   written out, the only place the script writes `ref_id`; any scheme but http(s)), and audits each
   page the web tool's replies say it served as the item of a call that opened it. A script that
   calls the shell is suspect: only a command's item says what ran, and the shell rules read each
   string the script passes it;
6. flags any tool or record it does not read: a script that calls a tool other than `tools.web__run` and
   `tools.exec_command` (code mode's `tools` object also holds the lane account's connector tools, such
   as GitHub's and ChatGPT Space's) or reaches `tools` other than as `tools.<name>`; a script whose text
   holds a word that can spell or build code as it runs, or reach the global object, a prototype or a
   runtime the isolate lacks; one that, parsed as JavaScript, names a global code mode does not provide,
   uses `this`, defines an accessor, builds such a word from strings, or indexes an object with a key it
   cannot read; a script that does not parse (unless its one output reads as Codex reports a script V8
   refused to compile) or nests deeper than this script reads; a function other than the sub-agent ones
   and code mode's `wait`; a log line that does not parse, nests more than `DEPTH` levels or gives a key
   twice; a record, event or item of a kind it does not convert, or with a field its checks cannot read
   (a list where Codex writes a string, say); a cite marker in a tool's reply it cannot read; a shell
   command a script calls with no completed item to audit; or a command run outside the work directory;
7. writes `runs/<label>/codex-sessions/audit.json`.

The checks in 5 and 6 read each script without running it, so a script written to hide a call can
still get past them: one that builds a name as it runs and indexes an object with it, say. What a
script returns to the model reaches it as the script's output, which the log records.

    .venv/bin/python scripts/audit_codex_sessions.py [LABEL ...] [--lanes DIR]

It exits 1 if any thread fails the audit or any check above flags something.
"""

from __future__ import annotations

import argparse
import collections
import decimal
import hashlib
import json
import math
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import tree_sitter_javascript
from tree_sitter import Language, Parser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from i86 import audit, runners  # noqa: E402

RUNS = ROOT / "runs"
LANES = Path.home() / ".subfleet" / "lanes"
FOLDER = "codex-sessions"
# How many levels of objects and arrays a log line may nest. The Sol runs' logs nest at most 9; a line
# that nests nearly as deep as Python's parser reads (about 10,000 here) can parse and then stop a
# later step that writes its items out as JSON.
DEPTH = 64
# What an `exec` script may call: the web, and the shell. Codex 0.159's spec for `exec`: "All nested
# tools are available on the global `tools` object". That object also held the lane account's
# connector tools (GitHub, ChatGPT Space and more), as the scripts that listed `ALL_TOOLS` show.
SCRIPT_TOOLS = {"web__run", "exec_command"}
# The collaboration tools Codex's multi-agent role prompt names, in the namespace the logs give them,
# and code mode's `wait`, which has none. Codex 0.159's spec for `wait`: "`cell_id` identifies the
# running `exec` cell to resume"; it waits for, or with `terminate` stops, a cell an `exec` call
# started, so the cell's calls are that script's and its items.
FUNCTIONS = {*(("collaboration", name) for name in ("spawn_agent", "send_message", "followup_task", "wait_agent",
                                                     "interrupt_agent", "list_agents")), (None, "wait")}
SKIPPED_ITEMS = {"UserMessage", "SubAgentActivity"}  # the brief or a thread's message; sub-agent events
# Every `tools` in a script must start a `tools.<name>`; any other (an index, a space or comment before
# the dot, `?.`, an alias, a spread) can call a tool by a name the script builds as it runs.
TOOLS_WORD = re.compile(r"\btools\b")
TOOLS_NAMED = re.compile(r"\btools\.(\w+)\b")
# Text that can spell a name (a `\u` or `\x` escape), build code as the script runs, reach the global
# object, a module, an object's prototype or a way to define an accessor on one, or call a runtime the
# isolate lacks ("no Node, no file system, no network access").
SCRIPT_ESCAPES = re.compile(r"\\u|\\x[0-9A-Fa-f]{2}|\beval\b|\bFunction\b|\bconstructor\b|\bglobalThis\b"
                            r"|\bimport\b|\brequire\b|\bfs\.|\bDeno\.|\bprocess\.|\bBun\.|\bprototype\b|__proto__"
                            r"|__(?:define|lookup)[GS]etter__|\bdefinePropert(?:y|ies)\b"
                            r"|\bgetOwnPropertyDescriptors?\b|\b[gs]etPrototypeOf\b|\bReflect\b|\bProxy\b"
                            r"|(?:^|[{,;}])\s*(?:static\s+)?[gs]et\s+[\w$]+\s*\(", re.M)
# The page a web__run call opens, clicks in or searches, under a key quoted or not.
REF_ID = re.compile(r"""(["'`]?)\bref_id\1\s*:\s*(["'`])(.*?)\2""")
TURN_REF = re.compile(r"turn\d+[a-z]+\d+")  # a page the web tool returned earlier, by its reference
OTHER_SCHEME = re.compile(r"(?i)(?<![a-z0-9+.\-])(?!https?://)[a-z][a-z0-9+.\-]*://|\bfile:")
# A page the web tool's reply says it served: "<title> (<url>) citeturn3view0". A reply
# a script printed as JSON holds an escaped `\n` before the marker; an empty "()" names no page.
SERVED = re.compile(r"\(([^()\s-]*)\)(?:\s|\\[nrt])*citeturn\d+[a-z]+\d+")
# A link inside a page's text, which the web tool follows by its number: "cite9†<text>".
LINK = re.compile("cite\\d+†[^-]*")
# How Codex reports a script V8 refused to compile: it failed with a SyntaxError and printed nothing.
REFUSED = re.compile(r"Script failed\nWall time [0-9.]+ seconds\nOutput:\n")
FIRST_ATTEMPT = re.compile(r"/a1\Z")  # subfleet's attempt ids run <job>/a1, <job>/a2, ...
# What a 0.159 session log holds, besides the calls this script reads. Anything else is flagged.
RECORDS = {"session_meta", "event_msg", "response_item", "turn_context", "world_state", "token_usage_record",
           "inter_agent_communication_metadata"}
EVENTS = {"item_completed", "task_started", "task_complete", "turn_aborted", "token_count", "thread_settings_applied"}
RESPONSE_ITEMS = {"message", "reasoning", "agent_message", "custom_tool_call", "custom_tool_call_output",
                  "function_call", "function_call_output"}
# The fields of subfleet's record of an attempt that `attempts.json` keeps.
ATTEMPT_FIELDS = ("attempt_id", "lane_id", "native_session_id", "state", "outcome_class", "outcome_detail",
                  "started_at", "finished_at", "model_served")

_JS = Parser(Language(tree_sitter_javascript.language()))
# What a script may name without declaring it. Codex 0.159's spec for `exec`: it "Evaluates the provided
# JavaScript code in a fresh V8 isolate as an async module", so a script names only what it declares,
# code mode's own globals (its "Global helpers", `tools` and `ALL_TOOLS`, "metadata for the enabled
# nested tools as `{ name, description }` entries"), and the ECMAScript built-ins below, none of which
# hands a script the global object or a way to compile code. (Code mode's `setTimeout` takes only a
# function: its host answers anything else with "setTimeout expects a function callback".)
GLOBALS = frozenset("""tools ALL_TOOLS exit text image audio generatedImage store load notify setTimeout
    clearTimeout yield_control undefined NaN Infinity Object Array String Number Boolean BigInt Symbol Math
    JSON Date RegExp Map Set WeakMap WeakSet Promise Intl Error TypeError RangeError SyntaxError
    ReferenceError URIError AggregateError parseInt parseFloat isNaN isFinite encodeURIComponent
    decodeURIComponent encodeURI decodeURI ArrayBuffer DataView Int8Array Uint8Array Uint8ClampedArray
    Int16Array Uint16Array Int32Array Uint32Array Float32Array Float64Array BigInt64Array
    BigUint64Array""".split())
# Members that hand a script a constructor (and through it `Function`), an object's prototype, or a
# way to define an accessor on one, and V8's hook for formatting a stack trace, which this script does
# not read. A script may not name them, index with them or build them.
DENIED = frozenset("""constructor prototype __proto__ __defineGetter__ __defineSetter__ __lookupGetter__
    __lookupSetter__ defineProperty defineProperties getOwnPropertyDescriptor getOwnPropertyDescriptors
    getPrototypeOf setPrototypeOf prepareStackTrace""".split())
# What a script may not build from pieces: those members, `tools`, and the globals that compile code or
# reach the global object, each of which the text checks flag written out.
SPELLED = DENIED | {"tools", "eval", "Function", "globalThis", "Reflect", "Proxy"}
# What an index (`x[key]`) may hold besides a constant: names, numbers and the operators between them.
# What a constant string can be written as: a string, a template, a `+` of them, or one in parentheses.
CONSTANT_KINDS = ("string", "template_string", "binary_expression", "parenthesized_expression")
KEY_PARTS = {"identifier", "number", "member_expression", "property_identifier", "parenthesized_expression",
             "unary_expression", "binary_expression", "update_expression"}
# A JavaScript string's escapes: `\u{...}`, `\uXXXX`, `\xXX`, a line continuation, or one character.
ESCAPE = re.compile(r"\\(?:u\{([0-9A-Fa-f]{1,6})\}|u([0-9A-Fa-f]{4})|x([0-9A-Fa-f]{2})|(\r\n|[\s\S]))")
SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
# A JSON string's escapes, and the encodings a log could be written in, each with the bytes of its
# smallest unit.
JSON_ESCAPE = re.compile(r'\\(?:u([0-9A-Fa-f]{4})|(["\\/bfnrt]))')
ENCODINGS = (("utf-8", 1), ("utf-16-le", 2), ("utf-16-be", 2), ("utf-32-le", 4), ("utf-32-be", 4))
# A number as a module may write it (strict mode: no legacy octal like `017`, and `_` only between
# digits): a whole number in base 16, 8, 2 or 10, which `n` makes a BigInt, or a decimal.
WHOLE = re.compile(r"0[xX](?P<x>[0-9a-fA-F](?:_?[0-9a-fA-F])*)|0[oO](?P<o>[0-7](?:_?[0-7])*)"
                   r"|0[bB](?P<b>[01](?:_?[01])*)|(?P<d>0|[1-9](?:_?[0-9])*)")
DECIMAL = re.compile(r"(?:(?:0|[1-9](?:_?[0-9])*)(?:\.(?:[0-9](?:_?[0-9])*)?)?|\.[0-9](?:_?[0-9])*)"
                     r"(?:[eE][+-]?[0-9](?:_?[0-9])*)?")


def thread_spawn(meta: dict) -> dict | None:
    """The `thread_spawn` record a sub-agent's `session_meta` gives as its source, or None."""
    src = meta.get("source")
    sub = src.get("subagent") if isinstance(src, dict) else None
    spawn = sub.get("thread_spawn") if isinstance(sub, dict) else None
    return spawn if isinstance(spawn, dict) else None


def spawned_by(meta: dict) -> str | None:
    """The thread that spawned this one, or None for a thread `codex exec` started."""
    parent = (thread_spawn(meta) or {}).get("parent_thread_id")
    return parent if isinstance(parent, str) else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized(path: str) -> str:
    """A path as `os.path.normpath` writes it (no repeated `/`, no `.` part, no `..` part after a name
    and no `/` at the end), with `//` at the start read as `/`."""
    return posixpath.normpath(re.sub(r"\A/+", "/", path))


def _names_directory(text: str, workdir: str) -> bool:
    """Whether text holds the work directory as a path, in any case (a disk that ignores case reads
    `/MOCK/SOL-1` as `/MOCK/sol-1`): with no letter, digit, `_`, `.` or `-` just before or after it, no
    `~` before it and no backslash after it (which can start an escape that spells one), so
    `/MOCK/sol-10` does not name `/MOCK/sol-1`, while a path inside the directory does."""
    pattern = r"(?<![\w.~-])" + re.escape(workdir.rstrip("/")) + r"(?![\w.\\-])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _json_unescaped(text: str) -> str:
    """Text with JSON's string escapes decoded, read left to right, so `\\\\u002f` is a backslash and
    `u002f`."""
    simple = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    return _utf16(JSON_ESCAPE.sub(lambda m: chr(int(m[1], 16)) if m[1] else simple[m[2]], text))


def _mentions(data: bytes, workdir: str) -> bool:
    """Whether a log names the work directory anywhere (`_names_directory`) once JSON's escapes are
    decoded, read as UTF-8, or as UTF-16 or UTF-32 of either byte order from any of its first bytes. A
    byte that does not decode reads as U+FFFD, which is no letter."""
    texts = (data[skip:].decode(codec, "replace") for codec, width in ENCODINGS for skip in range(width))
    return any(_names_directory(_json_unescaped(text), workdir) for text in texts)


def _record(raw: bytes | str):
    """A line of a session log as JSON. A line that gives a key twice in one object reads here as the
    last value and could read elsewhere as the first, and one that nests more than `DEPTH` levels
    could stop a later step, so neither parses (ValueError)."""
    def unique(pairs):
        keys = [key for key, _ in pairs]
        if len(set(keys)) < len(keys):
            raise ValueError("a key appears twice in one object")
        return dict(pairs)
    record = json.loads(raw, object_pairs_hook=unique)
    if _nests_deeper_than(record, DEPTH):
        raise ValueError(f"nests more than {DEPTH} levels")
    return record


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


def find_threads(paths: list[Path], workdir: str) -> tuple[dict[str, dict], list[str]]:
    """Every session log among `paths` whose thread started in `workdir`, by thread id, and what the
    search could not read. A thread started there when its log's first line parses (`_record`) as a
    `session_meta` record whose `cwd` is the work directory, the same path once `_normalized`. A log
    this script cannot open is reported. So is one whose first line says nothing of where its thread
    started (it does not parse, is another record or gives no `cwd` this script can read) when the
    log names the work directory anywhere (`_mentions`), and a session in a path that names the work
    directory but is another. A session there with no thread id or a source or start time this
    script cannot read, and a thread whose logs differ, are reported too; a second log of a thread that
    matches the first byte for byte is the same log."""
    found: dict[str, dict] = {}
    problems: list[str] = []
    for path in paths:
        problem = None if os.path.isfile(path) else "not a regular file"  # a folder, or a pipe that would block
        if problem is None:
            try:
                with path.open("rb") as fh:
                    first = fh.readline()
            except OSError as error:
                problem = type(error).__name__
        if problem is not None:
            problems.append(f"{path.name}: this script cannot open it ({problem})")
            continue
        try:
            record = _record(first)
        except (ValueError, RecursionError):
            record = None
        meta = record.get("payload") if isinstance(record, dict) and record.get("type") == "session_meta" else None
        cwd = meta.get("cwd") if isinstance(meta, dict) else None
        if not isinstance(cwd, str):
            problem = ("does not parse" if record is None
                       else "is not a session's record" if not isinstance(meta, dict)
                       else "gives no work directory this script can read")
            try:
                named = _mentions(path.read_bytes(), workdir)
            except OSError as error:
                problems.append(f"{path.name}: this script cannot open it ({type(error).__name__})")
                continue
            if named:
                problems.append(f"{path.name}: it names the work directory, but its first line {problem}")
            continue
        if _normalized(cwd) != _normalized(workdir):
            if _names_directory(cwd, workdir):
                problems.append(f"{path.name}: a session in {cwd[:200]}, a path that names the work directory "
                                "but is another")
            continue
        tid = meta.get("id")
        if not isinstance(tid, str) or not tid:
            problems.append(f"{path.name}: a session in the work directory with no thread id")
            continue
        if tid in found:
            if sha256(path) != sha256(found[tid]["path"]):
                problems.append(f"{path.name} and {found[tid]['path'].name} both hold thread {tid}, and they differ")
            continue
        parent = spawned_by(meta)
        if parent is None and meta.get("source") != "exec":
            problems.append(f"{path.name}: thread {tid} gives a source this script cannot read: "
                            f"{json.dumps(meta.get('source'))[:200]}")
        started = meta.get("timestamp")
        if started is not None and not isinstance(started, str):
            problems.append(f"{path.name}: thread {tid} gives a start time this script cannot read")
            started = None
        found[tid] = {"path": path, "spawned_by": parent, "source": meta.get("source"),
                      "started": started, "agent_path": (thread_spawn(meta) or {}).get("agent_path")}
    return found, problems


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
        if not (isinstance(old, dict) and isinstance(old.get("attempts"), list)
                and all(isinstance(a, dict) for a in old["attempts"])):
            raise SystemExit(f"{kept} is not a record of attempts; the kept copy is final")
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


def _walk(node):
    """A syntax tree's nodes, each before its children."""
    stack = [node]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _unescape(raw: str) -> str:
    """A JavaScript string's text as the script sees it: each escape replaced by what it stands for, and
    each pair of `\\u` escapes that spells one UTF-16 character as that character."""
    def one(match):
        code = match.group(1) or match.group(2) or match.group(3)
        if code:
            return chr(int(code, 16)) if int(code, 16) <= 0x10FFFF else ""
        char = match.group(4)
        return "" if char in ("\n", "\r", "\r\n", "\u2028", "\u2029") else SIMPLE_ESCAPES.get(char, char)
    return _utf16(ESCAPE.sub(one, raw))


def _utf16(text: str) -> str:
    """A string as JavaScript holds it, in UTF-16 code units: a high surrogate and the low one after it,
    from two escapes or from two strings a `+` joins, are the one character they spell."""
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _template_parts(node, src: bytes) -> list:
    """A template's parts in order: the text between its substitutions as JavaScript reads it (each
    CR LF or CR in the source as LF, and its escapes decoded), and the node of each substitution."""
    parts, raw = [], ""
    for part in node.named_children:
        if part.type == "template_substitution":
            parts += [_unescape(raw.replace("\r\n", "\n").replace("\r", "\n")), part]
            raw = ""
        else:
            raw += _text(part, src)
    return [*parts, _unescape(raw.replace("\r\n", "\n").replace("\r", "\n"))]


def _parts(node) -> list:
    """A node's named children but its comments, which the grammar places among them."""
    return [part for part in node.named_children if part.type != "comment"]


def _plus(node) -> bool:
    return node.type == "binary_expression" and getattr(node.child_by_field_name("operator"), "type", None) == "+"


def _number(literal: str) -> str | None:
    """The string JavaScript makes of a number written out (`${0x7f}` builds "127", `${1e21}` "1e+21"
    and `${127n}` "127"), or None for one a module refuses to compile (`017`, `1__0`, `1.5n`). Python
    turns at most 4,300 decimal digits into an int or back, and JavaScript any number, so a decimal
    stays text and a BigInt in another base takes its digits from `decimal`."""
    whole = WHOLE.fullmatch(literal.removesuffix("n"))
    if whole is None:
        return _number_string(float(literal.replace("_", ""))) if DECIMAL.fullmatch(literal) else None
    base, digits = next((base, digits) for base, digits in zip((16, 8, 2, 10), whole.group("x", "o", "b", "d"))
                        if digits is not None)
    digits = digits.replace("_", "")
    if base == 10:
        return digits if literal.endswith("n") else _number_string(float(digits))
    value = int(digits, base)
    if literal.endswith("n"):
        return str(decimal.Decimal(value))
    try:
        return _number_string(float(value))
    except OverflowError:  # past the largest double, which JavaScript rounds to Infinity
        return "Infinity"


def _number_string(x: float) -> str:
    """ECMAScript's Number::toString for a number x ≥ 0: the fewest significant digits that give back
    x (as Python's `repr` finds them), written out from 1e-6 up to 1e21 and with an exponent beyond."""
    if x == math.inf:
        return "Infinity"
    if x == 0:
        return "0"
    mantissa, _, exponent = repr(x).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = (whole + fraction).lstrip("0")
    point = len(whole) + int(exponent or 0) - (len(whole + fraction) - len(digits))  # x = 0.digits × 10**point
    digits = digits.rstrip("0")
    if len(digits) <= point <= 21:
        return digits + "0" * (point - len(digits))
    if 0 < point <= 21:
        return digits[:point] + "." + digits[point:]
    if -6 < point <= 0:
        return "0." + "0" * -point + digits
    mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
    return mantissa + ("e+" if point > 0 else "e-") + str(abs(point - 1))


def _fold(node, src: bytes) -> str | None:
    """The string a constant expression builds: a string; a number, `true`, `false` or `null`, as
    JavaScript writes it in a string (a number by `_number`); a template whose substitutions fold; or a
    `+` of them with a string on at least one side. None for anything else, such as a variable
    (`undefined` among them, which a script may declare), a unary operator (`-1`) or a `+` of two
    numbers, which adds them: a script computes those as it runs."""
    folded = _folded(node, src)
    return None if folded is None else _utf16(folded[0])


def _folded(node, src: bytes) -> tuple[str, bool] | None:
    """What `_fold` reads a node as, and whether JavaScript holds it as a string rather than a number,
    a boolean or null, which a `+` joins as text only to a string."""
    kind = node.type
    if kind == "string":
        return _unescape("".join(_text(part, src) for part in node.named_children)), True
    if kind == "number":
        value = _number(_text(node, src))
        return None if value is None else (value, False)
    if kind in ("true", "false", "null"):
        return kind, False
    if kind == "template_string":
        parts = []
        for part in _template_parts(node, src):
            if isinstance(part, str):
                parts.append(part)
                continue
            inner = _parts(part)
            value = _folded(inner[0], src) if len(inner) == 1 else None
            if value is None:
                return None
            parts.append(value[0])
        return "".join(parts), True
    if kind == "parenthesized_expression" and len(_parts(node)) == 1:
        return _folded(_parts(node)[0], src)
    if _plus(node):
        left = _folded(node.child_by_field_name("left"), src)
        right = _folded(node.child_by_field_name("right"), src) if left is not None else None
        if right is None or not (left[1] or right[1]):
            return None
        return left[0] + right[0], True
    return None


def _written(node, src: bytes) -> list[str]:
    """The strings written out in a `+` chain or a template: each one stands in what the chain builds."""
    kind = node.type
    if kind == "string":
        return [_fold(node, src)]
    if kind == "template_string":
        parts = []
        for part in _template_parts(node, src):
            if isinstance(part, str):
                parts.append(part)
            elif _parts(part):
                parts += _written(_parts(part)[0], src)
        return parts
    if kind == "parenthesized_expression" and _parts(node):
        return _written(_parts(node)[0], src)
    if _plus(node):
        return _written(node.child_by_field_name("left"), src) + _written(node.child_by_field_name("right"), src)
    return []


def _spells(value: str) -> bool:
    """Whether a string a script builds names one of `SPELLED`."""
    return bool(SPELLED & set(re.findall(r"[\w$]+", value)))


def _arithmetic(node) -> bool:
    """Whether an index holds only names, numbers and the operators between them."""
    return node.type in KEY_PARTS and all(_arithmetic(part) for part in _parts(node))


def _readable_key(node, src: bytes) -> bool:
    """Whether an index that does not fold to a constant can name none of `SPELLED`: arithmetic on
    names, or a string it builds around a piece written out that is part of no such name."""
    return _arithmetic(node) or any(not any(part in word for word in SPELLED) for part in _written(node, src))


def _bound(node, src: bytes) -> set[str]:
    """The names a declaration's target binds: a name, or each name in a destructuring pattern."""
    if node is None:
        return set()
    kind = node.type
    if kind in ("identifier", "shorthand_property_identifier_pattern"):
        return {_text(node, src)}
    if kind in ("assignment_pattern", "object_assignment_pattern"):
        return _bound(node.child_by_field_name("left"), src)
    if kind == "pair_pattern":
        return _bound(node.child_by_field_name("value"), src)
    if kind in ("object_pattern", "array_pattern", "rest_pattern", "formal_parameters"):
        return set().union(*(_bound(part, src) for part in node.named_children))
    return set()


def _declared(node, src: bytes) -> set[str]:
    """The names one node declares: a variable, a function or class, parameters, a caught error, or
    the variable of a `for (const x of ...)`."""
    kind = node.type
    if kind == "variable_declarator":
        return _bound(node.child_by_field_name("name"), src)
    if kind in ("function_declaration", "generator_function_declaration", "class_declaration",
                "function_expression", "generator_function", "class"):
        name = node.child_by_field_name("name")
        return {_text(name, src)} if name is not None else set()
    if kind == "formal_parameters":
        return _bound(node, src)
    if kind in ("arrow_function", "catch_clause"):
        return _bound(node.child_by_field_name("parameter"), src)
    if kind == "for_in_statement" and node.child_by_field_name("kind") is not None:
        return _bound(node.child_by_field_name("left"), src)
    return set()


def _is_tool(node, src: bytes, names=SCRIPT_TOOLS) -> bool:
    """Whether a node is `tools.<name>` for one of `names`, written out with a plain dot."""
    return (node is not None and node.type == "member_expression"
            and node.child_by_field_name("optional_chain") is None
            and _text(node.child_by_field_name("object"), src) == "tools"
            and node.child_by_field_name("object").type == "identifier"
            and _text(node.child_by_field_name("property"), src) in names)


def cell_problems(tree, src: bytes) -> list[str]:
    """What a script that parses does beyond the web tool and the shell, read from its syntax tree: a
    name it neither declares nor may use, `tools` other than as `tools.web__run` or
    `tools.exec_command`, `this`, an accessor, `with`, a member `DENIED` names, an index that is
    neither a constant nor arithmetic on names, or a string it builds that `_spells` a word."""
    nodes = list(_walk(tree.root_node))
    declared = set().union(*(_declared(node, src) for node in nodes))
    problems = []
    for node in nodes:
        kind = node.type
        if kind in ("identifier", "shorthand_property_identifier"):
            name = _text(node, src)
            if name not in declared and name not in GLOBALS:
                problems.append(f"names {name!r}, which it does not declare and code mode does not provide")
            if name == "tools" and not (node.parent is not None and node.parent.child_by_field_name("object") == node
                                        and _is_tool(node.parent, src)):
                problems.append("reaches tools other than as tools.web__run or tools.exec_command")
        elif kind == "this":
            problems.append("uses this")
        elif kind == "method_definition" and any(part.type in ("get", "set") for part in node.children):
            problems.append("defines an accessor")
        elif kind == "with_statement":
            problems.append("uses with")
        elif kind == "property_identifier" and _text(node, src) in DENIED:
            problems.append(f"names {_text(node, src)}")
        elif kind in ("subscript_expression", "computed_property_name"):
            key = node.child_by_field_name("index") if kind == "subscript_expression" else (
                (_parts(node) or [None])[0])
            value = _fold(key, src) if key is not None else None
            if value is not None and _spells(value):
                problems.append(f"indexes with {value[:80]!r}")
            elif value is None and not (key is not None and _readable_key(key, src)):
                shown = _text(key, src)[:80] if key is not None else ""
                problems.append(f"indexes with {shown!r}, a key this script cannot read")
        elif kind in ("binary_expression", "template_string"):
            value = _fold(node, src)
            if value is not None and _spells(value):
                problems.append(f"builds the string {value[:80]!r}")
    return list(dict.fromkeys(problems))


def _shell_strings(tree, src: bytes) -> list[str]:
    """Each constant string a script passes to `tools.exec_command`."""
    out = []
    for node in _walk(tree.root_node):
        if node.type != "call_expression" or not _is_tool(node.child_by_field_name("function"), src, {"exec_command"}):
            continue
        stack = [node.child_by_field_name("arguments")]
        while stack:
            part = stack.pop()
            if part is None:
                continue
            value = _fold(part, src) if part.type in ("string", "template_string", "binary_expression") else None
            if value is not None:
                out.append(value)
            else:
                stack.extend(part.named_children)
    return out


def _web_page(text: str) -> bool:
    """Whether a page a script opens is a web address or a page the web tool returned."""
    return bool(re.match(r"(?i)https?://", text) or TURN_REF.fullmatch(text))


def _constants(tree, src: bytes) -> list[str]:
    """Each string a script writes out or builds from constants (`_fold`), and each piece of a
    template written out between its substitutions, with its escapes decoded."""
    out = []
    for node in _walk(tree.root_node):
        if node.type in CONSTANT_KINDS:
            value = _fold(node, src)
            if value is not None:
                out.append(value)
        if node.type == "template_string":
            out += [part for part in _template_parts(node, src) if isinstance(part, str)]
    return [text for text in dict.fromkeys(out) if text]


def _inside_constant(node, src: bytes) -> bool:
    """Whether a constant sits inside a larger constant that folds (parentheses, a `+`, a template)."""
    parent = node.parent
    if parent is not None and parent.type == "template_substitution":
        parent = parent.parent
    return parent is not None and parent.type in CONSTANT_KINDS and _fold(parent, src) is not None


def _keyed(node) -> bool:
    """Whether a node is an object's key: a pair's, or a computed key's content. (An index that folds
    to `ref_id` reads or sets a member, which `_ref_id_problem` flags before it reaches the index.)"""
    parent = node.parent
    return parent is not None and (parent.type == "computed_property_name" or (
        parent.type == "pair" and parent.child_by_field_name("key") == node))


def _ref_id_problem(tree, src: bytes) -> str | None:
    """Why a page a script opens by `ref_id` may be other than a page on the web, or None. A script
    must give each `ref_id` as an object's key with one string written out as its value (not a
    variable, a member, a sum or a template with a substitution), whose text, its escapes decoded,
    is a web address or a page the web tool returned. It may write `ref_id` nowhere else: not as a
    member it reads or sets, a class's field, or a string from which it could build such an object
    as it runs."""
    for node in _walk(tree.root_node):
        kind = node.type
        if kind == "pair":
            key, value = node.child_by_field_name("key"), node.child_by_field_name("value")
            computed = _parts(key) if key.type == "computed_property_name" else []
            name = (_text(key, src) if key.type == "property_identifier" else
                    _fold(key, src) if key.type == "string" else
                    _fold(computed[0], src) if len(computed) == 1 else None)
            if name != "ref_id":
                continue
            if value is None:
                return "opens a ref_id with no value"
            if not (value.type == "string" or (value.type == "template_string" and not any(
                    part.type == "template_substitution" for part in value.named_children))):
                return f"opens ref_id {_text(value, src)[:80]!r}, not one string written out"
            opened = _fold(value, src)
            if not _web_page(opened):
                return f"opens {opened[:80]!r}, neither a web address nor a page the web tool returned"
        elif kind == "shorthand_property_identifier" and _text(node, src) == "ref_id":
            return "opens a ref_id it holds in a variable"
        elif kind == "member_expression" and _text(node.child_by_field_name("property"), src) == "ref_id":
            return "reads or sets a ref_id member"
        elif kind == "subscript_expression" and _fold(node.child_by_field_name("index"), src) == "ref_id":
            return "reads or sets a ref_id member"
        elif (kind == "property_identifier" and _text(node, src) == "ref_id"
              and node.parent.type not in ("pair", "member_expression")):
            return f"names ref_id in a {node.parent.type}, not as an object's key"
        elif (kind in CONSTANT_KINDS and not _inside_constant(node, src) and not _keyed(node)
              and _fold(node, src) == "ref_id"):
            return "writes the string ref_id other than as an object's key"
    return None


def check_script(code: str, workdir: str, tree=None) -> tuple[str, str]:
    """The audit's verdict on an `exec` script's text read as a web call's input (`tree`: its syntax
    tree, if it parses). Every URL in its text, and in each string it writes out or builds from
    constants with escapes decoded (`_constants`), must name another machine, as `audit` reads a web
    call's URLs (`_web_hosts`), and none may open this repository; each page it opens by `ref_id`
    must pass `_ref_id_problem`, and so must each `ref_id: "..."` in its text or its strings (JSON it
    could parse); and it may name no URL but http(s). What a script opens on the web is in its
    `web__run` arguments, which the item for the call records only in part. A script that calls the
    shell is suspect: only a command's completed item says what ran, and a cell that stops first
    leaves none; the shell rules also read each string the script passes to `tools.exec_command`.
    `audit` gives a web call "web" or "suspect"."""
    roots = audit.protected_roots()
    if "exec_command" in {match.group(1) for match in TOOLS_NAMED.finditer(code)}:
        for command in _shell_strings(tree, code.encode()) if tree is not None else []:
            verdict, why = audit.check_call("shell", {"command": command}, Path(workdir), roots)
            if verdict in ("violation", "suspect"):
                return "suspect", f"calls tools.exec_command with {command[:80]!r} ({verdict}: {why})"
        return "suspect", "calls tools.exec_command; only a command's completed item says what ran"
    strings = _constants(tree, code.encode()) if tree is not None else []
    verdict, why = audit.check_call("web_search", {"script": code, "strings": strings}, Path(workdir), roots)
    if verdict != "web":
        return verdict, why
    for text in (code, *strings):
        for ref in REF_ID.finditer(text):
            if not _web_page(ref.group(3)):
                return "suspect", f"opens {ref.group(3)[:80]!r}, neither a web address nor a page the web tool returned"
    problem = _ref_id_problem(tree, code.encode()) if tree is not None else None
    if problem:
        return "suspect", problem
    if any(OTHER_SCHEME.search(text) for text in (code, *strings)):
        return "suspect", "names a URL other than http(s)"
    return "web", ""


def check_page(url: str, workdir: str) -> tuple[str, str]:
    """The audit's verdict on a page the web tool's reply says it served, read as the item of a call
    that opened it: a click's page, and a script's, have no item of their own."""
    return audit.check_call("web_search", {"query": "", "url": url, "action": {"type": "open_page", "url": url}},
                            Path(workdir), audit.protected_roots())


def output_text(output) -> str:
    """A tool output's text: a string, or the text of each part of a list. An output of another shape
    raises TypeError, so that its line gets a flag rather than leaving the pages it serves unread."""
    if isinstance(output, str):
        return output
    if not isinstance(output, list) or not all(isinstance(part, dict) and isinstance(part.get("text", ""), str)
                                               for part in output):
        raise TypeError("a tool output this script cannot read")
    return "\n".join(part.get("text", "") for part in output)


def refused(output) -> bool:
    """Whether a script's output reads as Codex reports a script V8 refused to compile: it failed with
    a SyntaxError and printed nothing. A script that ran and then threw a SyntaxError of its own
    (`JSON.parse`'s, say) without printing reads the same, so a script the grammar cannot parse passes
    on this only because V8 refuses what the grammar does."""
    if not isinstance(output, list) or len(output) != 2 or not all(isinstance(part, dict) for part in output):
        return False
    head, error = (str(part.get("text", "")) for part in output)
    return bool(REFUSED.fullmatch(head)) and error.startswith("Script error:\nSyntaxError: ")


def convert(path: Path, workdir: str) -> tuple[list[dict], dict]:
    """The log's completed items as `codex exec --json` lines, and what the conversion found."""
    lines: list[dict] = []
    found = {"items": collections.Counter(), "script_tools": collections.Counter(),
             "functions": collections.Counter(), "started_threads": [], "flags": [], "script_suspect": []}
    served: set[str] = set()
    unparsed: dict[str, int] = {}  # each script the grammar cannot parse, by call id: its line
    replies: dict[str, list[bool]] = collections.defaultdict(list)  # by call id: whether each output reads as refused
    with path.open("rb") as fh:  # bytes, so a line that is not UTF-8 does not parse rather than stopping the audit
        for n, raw in enumerate(fh, 1):
            try:
                rec = _record(raw)
            except (ValueError, RecursionError):
                found["flags"].append(f"line {n} does not parse")
                continue
            try:
                if not isinstance(rec, dict):
                    found["flags"].append(f"line {n} is not a record")
                    continue
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
                    code = payload.get("input", "")  # Codex writes a string; another type fails below
                    named = list(TOOLS_NAMED.finditer(code))
                    for match in named:
                        found["script_tools"][match.group(1)] += 1
                        if match.group(1) not in SCRIPT_TOOLS:
                            found["flags"].append(f"line {n}: an exec script calls tools.{match.group(1)}")
                    starts = {match.start() for match in named}
                    if any(match.start() not in starts for match in TOOLS_WORD.finditer(code)):
                        found["flags"].append(f"line {n}: an exec script reaches tools other than by name: "
                                              f"{code[:200]!r}")
                    if SCRIPT_ESCAPES.search(code):
                        found["flags"].append(f"line {n}: an exec script can spell or build code as it runs, or reach "
                                              f"past its tools: {code[:200]!r}")
                    src = code.encode()
                    tree = _JS.parse(src)
                    if tree.root_node.has_error:
                        unparsed[str(payload.get("call_id") or f"line {n}")] = n
                        tree = None
                    problems = []
                    try:
                        if tree is not None:
                            problems = cell_problems(tree, src)
                        verdict, why = check_script(code, workdir, tree)
                    except RecursionError:  # nested deeper than Python's stack: the text checks still read it
                        problems.append("nests too deeply for this script to read")
                        verdict, why = check_script(code, workdir, None)
                    found["flags"] += [f"line {n}: an exec script {problem}: {code[:200]!r}" for problem in problems]
                    if verdict != "web":
                        found["script_suspect"].append({"tool": "exec script", "call": code[:4000], "why": why})
                elif kind_of_record == "response_item" and sub in ("custom_tool_call_output", "function_call_output"):
                    # A script's result, or a running cell's that `wait` returns: the pages the web tool served.
                    output = payload.get("output")
                    if sub == "custom_tool_call_output":
                        replies[str(payload.get("call_id"))].append(refused(output))
                    text = output_text(output)
                    pages = SERVED.findall(text)
                    stray = text.count("") - len(pages) - len(LINK.findall(text))
                    if stray:
                        found["flags"].append(f"line {n}: a tool's reply holds {stray} cite marker(s) this script "
                                              "does not read")
                    for url in pages:
                        if not url or url in served:
                            continue
                        served.add(url)
                        verdict, why = check_page(url, workdir)
                        if verdict != "web":
                            found["script_suspect"].append({"tool": "web page", "call": url[:4000], "why": why})
                elif kind_of_record == "response_item" and sub == "function_call":
                    name, space = payload.get("name"), payload.get("namespace")
                    found["functions"][name] += 1
                    if (space, name) not in FUNCTIONS:
                        found["flags"].append(f"line {n}: function {name!r} in namespace {space!r}, which this script "
                                              "does not read")
                if kind_of_record != "event_msg" or sub != "item_completed":
                    continue
                item = payload.get("item") or {}
                if not isinstance(item, dict):
                    found["flags"].append(f"line {n}: a completed item this script cannot read")
                    continue
                kind = item.get("type")
                found["items"][f"{kind}:{item.get('kind')}" if kind == "Extension" else kind] += 1
                if kind == "Extension" and str(item.get("kind", "")).startswith("web."):
                    lines.append({"type": "item.completed", "item": {
                        "id": item.get("id"), "type": "web_search", "query": item.get("query", ""),
                        "action": web_action(item.get("action")), "results": item.get("results")}})
                elif kind == "CommandExecution":
                    command = item.get("command")
                    cwd = local_path(item.get("cwd"))
                    if cwd is None:  # a cwd missing, empty or of another type: where the command ran is unknown
                        raise TypeError("a command without a working directory this script can read")
                    if cwd.rstrip("/") != workdir.rstrip("/"):
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
                        if not isinstance(item["agent_thread_id"], str):
                            raise TypeError("a started sub-agent's thread id is not a string")
                        found["started_threads"].append(item["agent_thread_id"])
                elif kind not in SKIPPED_ITEMS:
                    found["flags"].append(f"line {n}: a completed {kind!r} item, which this script does not read")
            except (TypeError, AttributeError, ValueError, RecursionError) as error:
                # A field the checks above cannot read (a list where Codex writes a string, say, or a string
                # that does not encode as UTF-8): the line fails the run instead of stopping the audit.
                found["flags"].append(f"line {n}: a record with a field this script cannot read "
                                      f"({type(error).__name__})")
    found["flags"] += [f"line {line}: an exec script that does not parse as JavaScript, and whose one output does not "
                       "read as V8 refusing it" for call, line in unparsed.items() if replies.get(call) != [True]]
    # A shell command a script started may have no completed item (its cell stopped first); only the
    # item says what ran, so a script's call without one is flagged.
    if found["script_tools"]["exec_command"] > found["items"]["CommandExecution"]:
        found["flags"].append(f"{found['script_tools']['exec_command']} tools.exec_command calls in exec scripts, "
                              f"{found['items']['CommandExecution']} completed commands")
    found["served_pages"] = len(served)
    return lines, found


def _calls(lines: list[dict]) -> dict[str, list]:
    """Each completed item's calls, as `audit` reads them, listed under its item id in the order the
    items complete, so that an item that repeats another's id still counts. A shell command is compared
    as the words it splits into: the transcript quotes the command the log keeps as a list."""
    out: dict[str, list] = {}
    for line in lines:
        item = line.get("item")
        if line.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if isinstance(item.get("type"), str) and item["type"] in audit.CODEX_NOT_CALLS:
            continue
        calls = []
        for tool, inp in audit._tool_calls(line):
            if tool == "shell" and isinstance(inp, dict) and isinstance(inp.get("command"), str):
                try:
                    inp = {**inp, "command": shlex.split(inp["command"])}
                except ValueError:
                    pass
            calls.append([tool, json.dumps(inp, sort_keys=True, default=str)])
        out.setdefault(json.dumps(item.get("id")), []).append(calls)
    return out


def transcript_lines(path: Path, unread: list[int] | None = None) -> list[dict]:
    """A transcript's events: the lines that parse as JSON objects. Lines end at a newline alone, and a
    line of JSON's whitespace alone is no line, as `audit` reads a transcript; `unread` collects the
    number of each other line, which does not parse or is not an object."""
    lines = []
    for number, raw in enumerate(path.read_text(errors="replace").split("\n"), 1):
        if not raw.strip(" \t\r\n"):
            continue
        try:
            line = json.loads(raw)
        except (ValueError, RecursionError):
            line = None
        if isinstance(line, dict):
            lines.append(line)
        elif unread is not None:
            unread.append(number)
    return lines


def check_transcript(transcript: Path, log_lines: list[dict]) -> dict:
    """Whether the committed transcript records the same calls as the main thread's log, item by item.
    A transcript line this script cannot read could hold a call, so it counts as one only the
    transcript holds."""
    unread: list[int] = []
    mine, theirs = _calls(log_lines), _calls(transcript_lines(transcript, unread))
    return {"items": sum(map(len, theirs.values())),
            "only_in_transcript": [*sorted(k for k in theirs if k not in mine), *(f"line {n}" for n in unread)],
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
    """The thread a `codex exec --json` transcript records (its first `thread.started` event), or None
    if it records none or one whose id is not a string."""
    if not path.is_file():
        return None
    tid = next((line.get("thread_id") for line in transcript_lines(path) if line.get("type") == "thread.started"), None)
    return tid if isinstance(tid, str) else None


def audit_run(run_dir: Path, lanes: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    workdir = meta.get("workdir")
    logs = [*sorted(lanes.glob("*/sessions/*/*/*/rollout-*.jsonl")), *sorted((run_dir / FOLDER).glob("rollout-*.jsonl"))]
    if isinstance(workdir, str) and workdir.startswith("/"):
        threads, problems = find_threads(logs, workdir)
    else:
        threads = {}
        problems = [f"the run gives {json.dumps(workdir)[:200]} as its work directory, not an absolute path"]
    roots = sorted((t for t, v in threads.items() if v["spawned_by"] is None), key=lambda t: threads[t]["started"] or "")
    report = {"run": run_dir.name, "workdir": workdir, "threads": [], "missing": [], "flags": list(problems),
              "orphans": sorted(t for t, v in threads.items() if v["spawned_by"] and v["spawned_by"] not in threads)}
    # Which attempt each main thread was, and which one the transcript records.
    record = attempts(run_dir, meta)
    collected = meta.get("attempt_id")
    attempt_of: dict[str, str] = {}
    main = None
    if record is not None:
        job = meta.get("job_id")
        report["job_id"] = record.get("job_id")
        report["collected_attempt"] = collected
        if record.get("accepted_attempt_id") != collected:
            report["flags"].append(f"subfleet accepted {record.get('accepted_attempt_id')}, but the run collected {collected}")
        # subfleet numbers a job's attempts from a1 up, so a record that skips one leaves out an attempt
        # whose threads nothing names.
        listed = [a.get("attempt_id") for a in record["attempts"]]
        if record.get("job_id") != job or sorted(map(str, listed)) != sorted(f"{job}/a{i}"
                                                                            for i in range(1, len(listed) + 1)):
            report["flags"].append(f"subfleet's record of job {record.get('job_id')} lists attempts {listed}, not "
                                   f"{job}/a1 to {job}/a{len(listed)}")
        for attempt in record["attempts"]:
            sid = attempt.get("native_session_id")
            if sid is not None and not isinstance(sid, str):
                report["flags"].append(f"subfleet's record gives attempt {attempt.get('attempt_id')} a session this "
                                       f"script cannot read: {json.dumps(sid)[:200]}")
            elif not sid and attempt.get("started_at"):
                report["flags"].append(f"subfleet records no session for attempt {attempt.get('attempt_id')}, "
                                       "which started")
        named = [(a["native_session_id"], a.get("attempt_id")) for a in record["attempts"]
                 if isinstance(a.get("native_session_id"), str) and a["native_session_id"]]
        for sid, count in sorted(collections.Counter(sid for sid, _ in named).items()):
            if count > 1:
                report["flags"].append(f"subfleet's record names session {sid} for {count} attempts")
        attempt_of = dict(named)
        for root in roots:
            if root not in attempt_of:
                report["flags"].append(f"main thread {root} in the work directory is no attempt's session")
        for sid, aid in attempt_of.items():
            if sid in threads and threads[sid]["spawned_by"] is not None:
                report["flags"].append(f"attempt {aid}'s session {sid} is a sub-agent, not a thread codex exec started")
        report["missing"] += [sid for sid in attempt_of if sid not in threads]
        main = next((sid for sid, aid in attempt_of.items() if aid == collected), None)
        if main is None:
            report["flags"].append(f"subfleet records no session for the collected attempt {collected}")
    elif len(roots) != 1:
        report["flags"].append(f"{len(roots)} threads started by codex exec in the work directory and no attempts "
                               "on record; expected 1")
    elif collected is not None and not FIRST_ATTEMPT.search(str(collected)):
        # An earlier attempt may have left threads whose logs are gone; without the record, nothing says.
        report["flags"].append(f"no attempts on record, and the run collected {collected}, not its job's first "
                               "attempt (<job>/a1)")
    else:
        main = roots[0]
    transcript = run_dir / "transcript.jsonl"
    recorded = transcript_thread(transcript)
    if main is not None and recorded != main:
        shown = f"thread {recorded[:200]}" if recorded is not None else "no thread whose id this script can read"
        report["flags"].append(f"the transcript records {shown}, not the collected main thread {main}")
    report["main_thread"] = main if main is not None and recorded == main else None

    def root_of(tid: str) -> str:
        seen = set()
        while threads.get(tid, {}).get("spawned_by") and tid not in seen:
            seen.add(tid)
            tid = threads[tid]["spawned_by"]
        return tid

    started: set[str] = set()
    spawns: dict[str, tuple[int, list[str]]] = {}
    for tid, info in sorted(threads.items(), key=lambda kv: kv[1]["started"] or ""):
        kept = keep(info["path"], run_dir / FOLDER)
        result, found, lines = audit_thread(kept, workdir)
        started.update(found["started_threads"])
        spawns[tid] = (found["functions"]["spawn_agent"], found["started_threads"])
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
    # Each sub-agent a thread started came from one of its spawn_agent calls, and the threads that name
    # it as their parent are the ones it started (a started thread with no log is missing, above).
    for tid, (calls, begun) in sorted(spawns.items()):
        children = sorted(t for t, v in threads.items() if v["spawned_by"] == tid)
        if calls != len(begun):
            report["flags"].append(f"thread {tid} made {calls} spawn_agent calls and started {len(begun)} sub-agents")
        if sorted(t for t in begun if t in threads) != children:
            report["flags"].append(f"thread {tid} started {sorted(begun)}, but {children} name it as their parent")
    # Each thread descends from a main thread: parents that loop back reach none.
    for tid in sorted(threads):
        top = root_of(tid)
        if top in threads and threads[top]["spawned_by"] is not None:
            report["flags"].append(f"thread {tid} descends from no main thread: its parents form a cycle")
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
