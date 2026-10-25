"""Check that each forecaster worked independently.

The forecasters run on machines that also hold earlier forecasts of these questions, other runs'
answers and the operator's notes. The prompt forbids reading local files; this audit reads each run's
native transcript (Claude stream-json or Codex JSONL) and checks every tool call.

- Web calls (WebSearch, WebFetch, Codex web_search, and shell commands that only fetch URLs) are
  counted, and their URLs and queries logged for review.
- A call is a violation, which excludes the run, if it names a forbidden path or term (forecast,
  ballot or operator files, other runs' work directories, agent homes), searches the home directory or
  the filesystem broadly, or uses any MCP tool.
- Other local calls (an agent reading its own lane's skill files, say) are listed for review.

The audit fails closed: a transcript with no parseable events is a failed audit, and `simulate`
excludes runs without a passing audit unless told otherwise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Places no forecaster has reason to look: the repository and other runs' work directories, agent
# homes and job stores, and the operator's notes and ledgers.
FORBIDDEN_ROOTS = re.compile(
    r"dc-i86-llm-forecast|dc-ballot|\.subfleet|\.claude|\.codex|chief-of-staff|/reviews/|"
    r"MEMORY\.md|/memory/|\.brier|predictions/",
    re.I,
)
# Terms that are a violation only alongside a local path outside the work directory (a draft named
# forecast.json in the work directory is fine).
FORBIDDEN_TERMS = re.compile(r"i86|initiative.?86|foie|forecast|response\.(?:md|json)|runs/", re.I)
LOCAL = re.compile(r"(?:^|[\s'\"=(:])(?:/Users/|/private/|/tmp/|/var/|/home/|/etc/|~|\$HOME|\.\./|\.\.$)")
# Searches that sweep the home directory or the whole filesystem.
BROAD = re.compile(
    r"\b(?:find|grep\s+-[a-zA-Z]*r|rg|fd|ag|locate|mdfind|ls|tree|du)\b[^|;&]*"
    r"(?:\s(?:~|\$HOME|/|/Users(?:/[^/\s]+)?/?|\.\.)(?:\s|$|['\"]))"
)
URL = re.compile(r"https?://[^\s'\"<>)]+")
WEB_TOOLS = {"WebSearch", "WebFetch"}


def _tool_calls(line: dict):
    """Yield (tool, text) for every tool call in one transcript event (Claude or Codex)."""
    msg = line.get("message") or {}
    content = msg.get("content") if isinstance(msg, dict) else None
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and part.get("type") == "tool_use":
            yield part.get("name", "?"), json.dumps(part.get("input", {}))
    item = line.get("item") or {}
    if line.get("type") not in {None, "item.completed"} and item:
        return  # Codex repeats an item as started and completed; count it once.
    kind = item.get("type")
    if kind == "command_execution":
        yield "shell", item.get("command", "")
    elif kind in {"file_read", "file_change"}:
        yield kind, json.dumps(item)
    elif kind == "mcp_tool_call":
        yield f"mcp:{item.get('server', '?')}/{item.get('tool', '?')}", json.dumps(item.get("arguments", {}))
    elif kind == "web_search":
        yield "web_search", item.get("query", "")


def _is_fetch_only(command: str) -> bool:
    """A shell command that only fetches URLs (curl or wget) and touches no local path."""
    body = re.sub(r"^\S*(?:zsh|bash|sh)\s+-l?c\s+", "", command.strip()).strip("'\"")
    return bool(re.match(r"(?:curl|wget)\b", body)) and URL.search(body) is not None and not LOCAL.search(
        URL.sub("", body)
    )


def audit_transcript(path: Path, workdir: str) -> dict:
    events = calls = web = 0
    local, violations, urls = [], [], []
    for raw in path.read_text(errors="replace").splitlines():
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(line, dict):
            continue
        events += 1
        for tool, text in _tool_calls(line):
            calls += 1
            cleaned = text.replace(workdir, "<workdir>") if workdir else text
            record = {"tool": tool, "call": cleaned[:300]}
            if tool in WEB_TOOLS or tool == "web_search" or (tool == "shell" and _is_fetch_only(cleaned)):
                web += 1
                urls += URL.findall(cleaned) or ([f"search: {cleaned[:200]}"] if tool in {"WebSearch", "web_search"} else [])
                continue
            if tool.startswith("mcp:"):
                violations.append({**record, "why": "MCP tool"})
                continue
            if FORBIDDEN_ROOTS.search(cleaned) or (LOCAL.search(cleaned) and FORBIDDEN_TERMS.search(cleaned)):
                violations.append({**record, "why": "forbidden path or term"})
            elif tool == "shell" and BROAD.search(cleaned):
                violations.append({**record, "why": "broad filesystem search"})
            elif tool in {"Read", "Glob", "Grep", "LS", "shell", "file_read", "file_change"} or LOCAL.search(cleaned):
                local.append(record)
    return {
        "events": events,
        "tool_calls": calls,
        "web_calls": web,
        "urls": sorted(set(urls)),
        "local_calls": local,
        "violations": violations,
        "passed": events > 0 and not violations,
    }
