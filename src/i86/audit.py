"""Check that each forecaster worked independently.

The forecasters run on machines that also hold earlier forecasts of these questions, other runs'
answers and the operator's notes. The prompt forbids reading local files; this audit reads each run's
native transcript (Claude stream-json or Codex JSONL) and checks every tool call. It guards against
accidental and casual reads, not a forecaster set on hiding them.

Each call's local paths are resolved the way the shell would see them: `~` and `$HOME` expand, relative
paths resolve against the work directory, a `cd` inside a compound command moves the base for what
follows, and globs are expanded against the real filesystem at audit time. Then:

- **Violations** exclude the run:
  - any resolved path, or the call's text outside URLs, inside a protected place (the repository,
    the staging area, any other run's work directory, agent homes and job stores, the author's notes
    and ledgers, session scratch directories);
  - a search rooted at the home directory or above (find, grep -r, rg, ls -R, tree, du, Grep, Glob
    and so on), and any use of locate or mdfind;
  - a content search (grep -r, rg, Grep, or a name search whose results feed another command through
    xargs, -exec, a command substitution or a read loop) rooted above a protected place;
  - any MCP tool.
- **Suspect** calls are reported for the operator to read, without excluding the run: a name-only
  search rooted above a protected place, a listing of the home directory or above, a local path
  outside the work directory next to a term from these questions (foie, forecast, i86, ...), and
  sub-agent calls whose contents the transcript does not show.
- Other local calls are listed. Web calls (WebSearch, WebFetch, Codex web_search, curl and wget) are
  counted and their URLs logged.

A transcript with no parseable events fails the audit.
"""

from __future__ import annotations

import fnmatch
import glob as globlib
import json
import os
import re
import shlex
from pathlib import Path

HOME = Path.home()
URL = re.compile(r"https?://[^\s'\"<>)`]+")
# Text, outside URLs, that names a protected place.
PROTECTED_TEXT = re.compile(
    r"dc-i86-llm-forecast|dc-ballot|\.subfleet|\.claude\b|\.claude/|\.codex|chief-of-staff|/reviews/|"
    r"MEMORY\.md|/memory/|\.brier|/predictions/|/private/tmp/claude-|/tmp/claude-",
    re.I,
)
TERMS = re.compile(r"foie|forecast|i-?86|initiative.?86|ban_status|yes_share|response\.(?:md|json)", re.I)
SHELL_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n|\$\(|`|\))\s*")
NAME_SEARCH = {"find", "fd", "fdfind", "tree", "du"}
CONTENT_SEARCH = {"rg", "ag", "ack"}
DISK_SEARCH = {"locate", "mdfind", "plocate", "glocate"}
# Ways a name search's results reach another command, which can then read them.
FEED = re.compile(r"\bxargs\b|\$\(|`|\s-(?:exec|execdir|ok|okdir)\b|\bwhile\s+read\b|\bparallel\b")
WEB_TOOLS = {"WebSearch", "WebFetch"}


def protected_roots() -> list[Path]:
    """Places no forecaster has reason to read. Other runs' work directories are checked separately,
    since they need not exist yet when the audit runs."""
    from .graph import ROOT
    from .runners import STAGE

    return [ROOT, STAGE, HOME / ".subfleet", HOME / ".claude", HOME / ".codex", HOME / "chief-of-staff",
            HOME / "reviews", HOME / ".brier", Path("/private/tmp/claude-501"), Path("/tmp/claude-501")]


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _at_or_above_home(path: Path) -> bool:
    return _under(HOME, path)


def _pattern_hits(pattern: Path, root: Path) -> bool:
    """A glob pattern that could match something inside root."""
    if not any(c in str(pattern) for c in "*?["):
        return False
    pp, rp = pattern.parts, root.parts
    if len(pp) < len(rp):
        return all(fnmatch.fnmatchcase(r, p) for r, p in zip(rp, pp)) and "**" in pp[-1:]
    return all(fnmatch.fnmatchcase(r, p) for r, p in zip(rp, pp[: len(rp)]))


def _reaches_sibling(path: Path, workdir: Path) -> bool:
    """A path, or a glob, inside the shared work area but outside this run's own directory."""
    from .runners import WORK

    wp, pp = WORK.parts, path.parts
    if len(pp) <= len(wp) or not all(fnmatch.fnmatchcase(w, x) for w, x in zip(wp, pp[: len(wp)])):
        return False
    return pp[len(wp)] != workdir.name or not _under(workdir, WORK)


def _covers_protected(root: Path, roots: list[Path]) -> bool:
    """A search rooted here can reach a protected place or another run's work directory."""
    from .runners import WORK

    return any(_under(r, root) for r in roots) or _under(WORK, root)


def _mask_workdir(text: str, workdir: Path) -> str:
    """Replace the run's own work directory, but not a sibling that starts with the same name."""
    return re.sub(re.escape(str(workdir)) + r"(?=[/'\"\\\s]|$)", "<workdir>", text)


def _resolve(token: str, cwd: Path, bare: bool = False) -> Path | None:
    """A shell token as a path, or None if it does not look like one. With `bare`, a plain name
    counts as a path too (after a `cd`, `cat notes` names a file in the new directory)."""
    token = token.strip("'\"")
    if not token or token.startswith("-") or URL.match(token) or "=" in token.split("/")[0]:
        return None
    token = token.replace("$HOME", str(HOME)).replace("${HOME}", str(HOME))
    if token == "~" or token.startswith("~/"):
        token = str(HOME) + token[1:]
    if not (bare or token.startswith("/") or token.startswith(".") or "/" in token or "*" in token):
        return None
    return Path(os.path.normpath(cwd / token))


def _expand(path: Path) -> list[Path]:
    text = str(path)
    if any(c in text for c in "*?["):
        return [Path(p) for p in globlib.glob(text)] or [path]
    return [path]


def shell_paths(command: str, workdir: Path) -> tuple[list[Path], list[tuple[str, str, Path]], list[str]]:
    """Resolved local paths in a shell command; the searches in it as (verb, kind, root), kind being
    'names', 'content' or 'disk'; and notes for the operator."""
    body = re.sub(r"^\S*(?:zsh|bash|sh)\s+-l?c\s+", "", command.strip())
    if len(body) > 1 and body[0] == body[-1] and body[0] in "'\"":
        body = body[1:-1]
    fed = bool(FEED.search(body))
    cwd, paths, searches, notes = workdir, [], [], []
    for segment in SHELL_SPLIT.split(body):
        try:
            tokens = shlex.split(segment, comments=False, posix=True)
        except ValueError:
            tokens = segment.split()
        if not tokens:
            continue
        verb = os.path.basename(tokens[0])
        args = tokens[1:]
        if verb == "cd":
            cwd = (_resolve(args[0], cwd, bare=True) if args else HOME) or cwd
            paths.append(cwd)
            continue
        resolved = [p for a in args for p in [_resolve(a, cwd, bare=cwd != workdir)] if p is not None]
        for p in resolved:
            paths += _expand(p)
        roots = resolved or [cwd]
        if verb in DISK_SEARCH:
            searches.append((verb, "disk", Path("/")))
        recursive_grep = verb in {"grep", "egrep", "fgrep"} and any(
            re.match(r"-[a-zA-Z]*[rR]", a) or a in {"--recursive", "--dereference-recursive"} for a in args)
        recursive_ls = verb == "ls" and any(re.match(r"-[a-zA-Z]*R", a) for a in args)
        if verb in CONTENT_SEARCH or recursive_grep:
            searches += [(verb, "content", r) for r in roots]
        elif verb in NAME_SEARCH or recursive_ls:
            searches += [(verb, "content" if fed else "names", r) for r in roots]
        if verb == "ls" and not recursive_ls and any(_at_or_above_home(r) for r in roots):
            notes.append("lists the home directory or above")
    return paths, searches, notes


def _tool_calls(line: dict):
    """Yield (tool, input) for every tool call in one transcript event (Claude or Codex)."""
    msg = line.get("message") or {}
    content = msg.get("content") if isinstance(msg, dict) else None
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and part.get("type") == "tool_use":
            yield part.get("name", "?"), part.get("input") or {}
    item = line.get("item") or {}
    if not item or line.get("type") not in {None, "item.completed"}:
        return  # Codex repeats an item as started and completed; count it once.
    kind = item.get("type")
    if kind == "command_execution":
        yield "shell", {"command": item.get("command", "")}
    elif kind in {"file_read", "file_change"}:
        yield kind, item
    elif kind == "mcp_tool_call":
        yield f"mcp:{item.get('server', '?')}/{item.get('tool', '?')}", item.get("arguments") or {}
    elif kind == "web_search":
        yield "web_search", {"query": item.get("query", "")}
    elif kind == "collab_tool_call":
        yield "collab", item


def check_call(tool: str, inp: dict, workdir: Path, roots: list[Path]) -> tuple[str, str]:
    """('web' | 'violation' | 'suspect' | 'local' | 'other', reason) for one tool call."""
    text = json.dumps(inp) if not isinstance(inp, str) else inp
    outside_urls = URL.sub("", text)
    if tool.startswith("mcp:") or tool.startswith("mcp__"):
        return "violation", "MCP tool"
    if tool == "collab":
        return "suspect", "sub-agent call; its work is not in this transcript"
    if tool in WEB_TOOLS or tool == "web_search":
        return "web", ""
    paths, searches, notes = [], [], []
    if tool in {"shell", "Bash"}:
        paths, searches, notes = shell_paths(inp.get("command", ""), workdir)
    elif tool in {"Read", "Edit", "Write", "NotebookEdit", "LS"}:
        p = _resolve(str(inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""), workdir)
        paths = [p] if p else []
    elif tool in {"Grep", "Glob"}:
        base = _resolve(str(inp.get("path") or "."), workdir, bare=True) or workdir
        paths = [base]
        searches = [(tool, "content" if tool == "Grep" else "names", base)]
        pattern = str(inp.get("pattern") or "") if tool == "Glob" else ""
        if pattern:
            paths += _expand(Path(os.path.normpath(base / pattern)))
    elif tool in {"file_read", "file_change"}:
        for key in ("path", "file_path"):
            if inp.get(key):
                p = _resolve(str(inp[key]), workdir)
                paths += [p] if p else []
    for p in paths:
        for root in roots:
            if _under(p, root) or _pattern_hits(p, root):
                return "violation", f"reaches {p} (protected: {root})"
        if _reaches_sibling(p, workdir):
            return "violation", f"reaches {p}, another run's work directory"
    if PROTECTED_TEXT.search(_mask_workdir(outside_urls, workdir)):
        return "violation", "names a protected place"
    problems = []
    for verb, kind, r in searches:
        if kind == "disk":
            problems.append(f"{verb} searches the whole disk")
        elif _at_or_above_home(r):
            problems.append(f"{verb} rooted at {r}")
        elif _covers_protected(r, roots):
            (problems if kind == "content" else notes).append(f"{verb} rooted at {r}, above a protected place")
    if problems:
        return "violation", "; ".join(problems)
    if notes:
        return "suspect", "; ".join(notes)
    outside = [p for p in paths if not _under(p, workdir)]
    if outside and TERMS.search(_mask_workdir(outside_urls, workdir)):
        return "suspect", "a path outside the work directory next to a term from these questions"
    if tool in {"shell", "Bash"} and URL.search(text) and re.search(r"\b(?:curl|wget)\b", text):
        return "web", ""
    if paths or tool in {"shell", "Bash", "Read", "Grep", "Glob", "LS", "file_read", "file_change"}:
        return "local", ""
    return "other", ""


def audit_transcript(path: Path, workdir: str) -> dict:
    work = Path(workdir) if workdir else Path("/nonexistent-workdir")
    roots = protected_roots()
    events = calls = web = 0
    lists: dict[str, list] = {"violations": [], "suspect": [], "local_calls": []}
    urls: list[str] = []
    for raw in path.read_text(errors="replace").splitlines():
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(line, dict):
            continue
        events += 1
        for tool, inp in _tool_calls(line):
            calls += 1
            verdict, why = check_call(tool, inp, work, roots)
            text = json.dumps(inp)
            if verdict == "web":
                web += 1
                found = URL.findall(text)
                urls += found or [f"search: {inp.get('query', '')}"[:200]]
                continue
            record = {"tool": tool, "call": text[:4000], **({"why": why} if why else {})}
            key = {"violation": "violations", "suspect": "suspect", "local": "local_calls"}.get(verdict)
            if key:
                lists[key].append(record)
    return {
        "events": events,
        "tool_calls": calls,
        "web_calls": web,
        "urls": sorted(set(urls)),
        **lists,
        "passed": events > 0 and not lists["violations"],
    }
