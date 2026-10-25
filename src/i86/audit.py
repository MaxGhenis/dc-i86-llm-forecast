"""Check that each forecaster worked independently.

The forecasters run on machines that also hold earlier forecasts of these questions, other runs'
answers and the operator's notes. The prompt forbids reading local files; this audit reads each run's
native transcript (Claude stream-json or Codex JSONL) and checks every tool call. It guards against
accidental and casual reads, not a forecaster set on hiding them.

Each shell command is tokenized as the shell would: quoting, `&&`, `||`, `;`, pipes, subshells,
command substitutions and redirections (`cat <file` reads `file`). Local paths are then resolved
against a tracked working directory: `~`, `$HOME` and simple variable assignments expand, relative
paths resolve against the work directory, `cd`, `pushd` and `popd` (options included) move the base
for what follows, nested `sh -c`, `eval` and wrappers such as `xargs` and `env` are parsed in turn,
quoted paths inside `python -c` style code count, and globs are expanded against the real
filesystem at audit time. A search command's pattern is not taken for a path. Then:

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
  outside the work directory next to a term from these questions (foie, forecast, i86, ...), a web
  call that opens this project's own repository (public, but without answers until every run has
  finished), and sub-agent calls whose contents the transcript does not show.
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
    r"dc-i86-llm-forecast|dc-ballot|\.subfleet|\.claude\b|\.codex\b|chief-of-staff|\.brier|"
    r"(?:~|\$\{?HOME\}?|" + re.escape(str(HOME)) + r")/reviews\b|"
    r"MEMORY\.md|/memory/|/predictions/|/private/tmp/claude-|/tmp/claude-",
    re.I,
)
TERMS = re.compile(r"foie|forecast|i-?86|initiative.?86|ban_status|yes_share|response\.(?:md|json)", re.I)
OPERATOR = re.compile(r"^[;&|()<>]+$")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
# Path-like strings inside code (python -c '...', node -e '...'), quoted or after an opening bracket.
EMBEDDED_PATH = re.compile(r"""(?:^|(?<=['"\s(=,:\[]))((?:~/|\.\./|\./|/)[^\s'"(),;\]]*)""")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
WRAPPERS = {"env", "nice", "nohup", "time", "sudo", "command", "builtin", "exec", "timeout", "stdbuf",
            "xargs", "caffeinate", "parallel", "watch", "unbuffer"}
NAME_SEARCH = {"find", "fd", "fdfind", "tree", "du"}
CONTENT_SEARCH = {"rg", "ag", "ack"}
GREP = {"grep", "egrep", "fgrep", "zgrep"}
# Commands whose first operand is a pattern rather than a file.
PATTERN_FIRST = GREP | CONTENT_SEARCH | {"fd", "fdfind"}
# Options of grep, rg, ag, ack and fd that take a separate value.
VALUE_OPTIONS = {
    "-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "-g", "-t", "-T", "-j", "-M", "-r", "-E", "-x", "-X",
    "-S", "-c", "--regexp", "--file", "--max-count", "--after-context", "--before-context", "--context",
    "--directories", "--devices", "--include", "--exclude", "--exclude-dir", "--exclude-from", "--label",
    "--binary-files", "--glob", "--iglob", "--type", "--type-not", "--type-add", "--type-clear",
    "--threads", "--max-columns", "--replace", "--encoding", "--max-depth", "--maxdepth",
    "--max-filesize", "--sort", "--sortr", "--colors", "--context-separator", "--path-separator",
    "--pre", "--pre-glob", "--engine", "--ignore-file", "--extension", "--exec", "--exec-batch",
    "--size", "--changed-within", "--changed-before", "--owner", "--base-directory", "--search-path",
}
PATTERN_OPTIONS = {"-e", "-f", "--regexp", "--file"}
# find tests whose value is a name, pattern or number, not a path.
FIND_VALUE_TESTS = {
    "-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-wholename", "-iwholename", "-lname",
    "-ilname", "-type", "-xtype", "-maxdepth", "-mindepth", "-size", "-mtime", "-mmin", "-atime", "-amin",
    "-ctime", "-cmin", "-perm", "-user", "-group", "-uid", "-gid", "-printf", "-links", "-inum",
    "-regextype", "-fstype", "-used",
}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "php", "Rscript", "osascript", "awk", "jq"}
DISK_SEARCH = {"locate", "mdfind", "plocate", "glocate"}
# Ways a name search's results reach another command, which can then read them.
FEED = re.compile(r"\bxargs\b|\$\(|`|\s-(?:exec|execdir|ok|okdir)\b|\bwhile\s+read\b|\bparallel\b")
WEB_TOOLS = {"WebSearch", "WebFetch"}
# This project's own public repository. It holds no answers until every run has finished.
OWN_REPO = re.compile(r"dc-i86-llm-forecast", re.I)


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


def _tokens(text: str) -> list[str]:
    """Shell words and operators. Newlines and backticks become command separators."""
    text = text.replace("`", " ; ").replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: fall back to plain splitting
        return re.findall(r"[;&|()<>]+|[^\s;&|()<>]+", text)


def _commands(tokens: list[str]) -> list[tuple[list[str], list[str]]]:
    """Split tokens into simple commands, each as (words, files named by redirections)."""
    out, words, redirects = [], [], []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "$" and i + 1 < len(tokens) and tokens[i + 1].startswith("("):
            i += 1
            continue
        if OPERATOR.match(tok):
            if "(" in tok or ")" in tok or not re.search(r"[<>]", tok):
                if words or redirects:
                    out.append((words, redirects))
                words, redirects = [], []
                i += 1
                continue
            # A redirection. A file descriptor number before it is not an argument.
            if words and words[-1].isdigit():
                words.pop()
            target = tokens[i + 1] if i + 1 < len(tokens) else None
            if target is not None and not OPERATOR.match(target):
                here = tok.startswith("<<")  # a here-document delimiter or here-string, not a file
                dup = tok.endswith("&") and (target.isdigit() or target == "-")
                if not (here or dup):
                    redirects.append(target)
                i += 2
                continue
            i += 1
            continue
        words.append(tok)
        i += 1
    if words or redirects:
        out.append((words, redirects))
    return out


class _Shell:
    """What one shell command reaches: paths, searches and notes, with the working directory tracked."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.cwd = workdir
        self.oldpwd = workdir
        self.stack: list[Path] = []
        self.known = True  # False after a cd the audit could not follow
        self.vars: dict[str, str] = {}
        self.paths: list[Path] = []
        self.searches: list[tuple[str, str, Path]] = []
        self.notes: list[str] = []
        self.fed = False

    def expand(self, word: str) -> str:
        def sub(m: re.Match) -> str:
            name = m.group(1) or m.group(2)
            if name == "HOME":
                return str(HOME)
            if name == "PWD":
                return str(self.cwd)
            if name == "OLDPWD":
                return str(self.oldpwd)
            return self.vars.get(name, m.group(0))

        return VAR.sub(sub, word)

    def resolve(self, word: str, bare: bool) -> Path | None:
        return _resolve(self.expand(word), self.cwd, bare=bare)

    def add(self, word: str, bare: bool) -> Path | None:
        p = self.resolve(word, bare)
        if p is not None:
            self.paths.extend(_expand(p))
            if not self.known and not os.path.isabs(self.expand(word).strip("'\"")) and not word.startswith("~"):
                self.notes.append("a relative path after a cd the audit could not follow")
        return p

    def run(self, text: str) -> None:
        self.fed = self.fed or bool(FEED.search(text))
        for words, redirects in _commands(_tokens(text)):
            self.command(words, redirects)

    def chdir(self, target: str | None) -> None:
        if target is None:
            new = HOME
        else:
            expanded = self.expand(target)
            if "$" in expanded:
                self.known = False
                self.notes.append(f"cd to {target}, which the audit cannot expand")
                return
            new = _resolve(expanded, self.cwd, bare=True) or self.cwd
        self.oldpwd, self.cwd = self.cwd, new
        self.paths.append(new)

    def command(self, words: list[str], redirects: list[str]) -> None:
        for r in redirects:
            self.add(r, bare=True)
        while words and ASSIGN.match(words[0]):
            name, value = ASSIGN.match(words[0]).groups()
            self.vars[name] = self.expand(value)
            self.add(value, bare=False)
            words = words[1:]
        if not words:
            return
        verb = os.path.basename(self.expand(words[0]))
        args = words[1:]
        if verb == "export":
            for a in args:
                if ASSIGN.match(a):
                    name, value = ASSIGN.match(a).groups()
                    self.vars[name] = self.expand(value)
                    self.add(value, bare=False)
            return
        if verb in SHELLS:
            for j, a in enumerate(args):
                if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) and j + 1 < len(args):
                    self.run(args[j + 1])
                    return
            for a in args:
                if not a.startswith("-"):
                    self.add(a, bare=True)  # a script file
            return
        if verb == "eval":
            self.run(" ".join(args))
            return
        if verb in WRAPPERS:
            rest = list(args)
            while rest and (rest[0].startswith("-") or ASSIGN.match(rest[0]) or re.fullmatch(r"[\d.]+[smhd]?", rest[0])
                            or rest[0] == "{}"):
                if verb == "xargs" and rest[0] in {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a"} and len(rest) > 1:
                    if rest[0] == "-a":
                        self.add(rest[1], bare=True)
                    rest = rest[2:]
                    continue
                rest = rest[1:]
            if rest:
                self.command(rest, [])
            return
        if verb in {"cd", "pushd", "chdir"}:
            operands = [a for a in args if not (a.startswith("-") and a != "-")]
            if verb == "pushd":
                self.stack.append(self.cwd)
            if operands and operands[0] == "-":
                self.oldpwd, self.cwd = self.cwd, self.oldpwd
                self.paths.append(self.cwd)
            else:
                self.chdir(operands[0] if operands else None)
            return
        if verb == "popd":
            if self.stack:
                self.oldpwd, self.cwd = self.cwd, self.stack.pop()
            return

        bare = self.cwd != self.workdir
        skip: set[int] = set()
        roots: list[Path] = []
        if verb in PATTERN_FIRST:
            positional = []
            has_pattern_option = False
            j = 0
            while j < len(args):
                a = args[j]
                if a == "--":
                    positional += list(range(j + 1, len(args)))
                    break
                if a.startswith("-") and a != "-":
                    name = a.split("=", 1)[0]
                    if name in PATTERN_OPTIONS or re.fullmatch(r"-[a-zA-Z]*[ef].*", a) and not a.startswith("--"):
                        has_pattern_option = True
                    if a in VALUE_OPTIONS and j + 1 < len(args):
                        if a in {"-f", "--file", "--ignore-file", "--exclude-from", "--base-directory",
                                 "--search-path"}:
                            self.add(args[j + 1], bare=True)
                        skip.add(j + 1)
                        j += 2
                        continue
                    if "=" in a:
                        self.add(a.split("=", 1)[1], bare=False)
                    j += 1
                    continue
                positional.append(j)
                j += 1
            if positional and not has_pattern_option:
                skip.add(positional[0])
                positional = positional[1:]
            operands = [args[k] for k in positional]
            recursive_grep = verb in GREP and any(
                re.match(r"-[a-zA-Z]*[rR]", a) or a in {"--recursive", "--dereference-recursive"} for a in args)
            if verb in CONTENT_SEARCH or recursive_grep or verb in {"fd", "fdfind"}:
                roots = [p for a in operands for p in [self.resolve(a, bare=True)] if p is not None] or [self.cwd]
                kind = "names" if verb in {"fd", "fdfind"} and not self.fed else "content"
                self.searches += [(verb, kind, r) for r in roots]
        elif verb == "find":
            j = 0
            while j < len(args) and args[j] in {"-H", "-L", "-P"}:
                j += 1
            start = j
            while j < len(args) and not (args[j].startswith("-") or args[j] in {"(", "!", ","}):
                j += 1
            roots = [p for a in args[start:j] for p in [self.resolve(a, bare=True)] if p is not None] or [self.cwd]
            for k in range(j, len(args)):
                if args[k] in FIND_VALUE_TESTS and k + 1 < len(args):
                    skip.add(k + 1)
            self.searches += [(verb, "content" if self.fed else "names", r) for r in roots]
        elif verb in {"tree", "du"} or (verb == "ls" and any(re.match(r"-[a-zA-Z]*R", a) for a in args)):
            operands = [a for a in args if not a.startswith("-")]
            roots = [p for a in operands for p in [self.resolve(a, bare=True)] if p is not None] or [self.cwd]
            self.searches += [(verb, "content" if self.fed else "names", r) for r in roots]
        elif verb == "ls":
            operands = [a for a in args if not a.startswith("-")]
            listed = [p for a in operands for p in [self.resolve(a, bare=True)] if p is not None] or [self.cwd]
            if any(_at_or_above_home(r) for r in listed):
                self.notes.append("lists the home directory or above")
        if verb in DISK_SEARCH:
            self.searches.append((verb, "disk", Path("/")))

        code = verb in INTERPRETERS or re.match(r"python\d", verb)
        for j, a in enumerate(args):
            if j in skip:
                continue
            if a.startswith("-") and a != "-":
                if "=" in a:
                    self.add(a.split("=", 1)[1], bare=False)
                continue
            self.add(a, bare=bare)
            if code or any(c in a for c in "'\"()"):
                for m in EMBEDDED_PATH.finditer(self.expand(a)):
                    self.add(m.group(1), bare=False)


def shell_paths(command: str, workdir: Path) -> tuple[list[Path], list[tuple[str, str, Path]], list[str]]:
    """Resolved local paths in a shell command; the searches in it as (verb, kind, root), kind being
    'names', 'content' or 'disk'; and notes for the operator."""
    shell = _Shell(workdir)
    shell.run(command)
    return shell.paths, shell.searches, shell.notes


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
        if OWN_REPO.search(text):
            return "suspect", "opens this project's repository on the web"
        return "web", ""
    paths, searches, notes = [], [], []
    if tool in {"shell", "Bash"}:
        paths, searches, notes = shell_paths(inp.get("command", ""), workdir)
    elif tool in {"Read", "Edit", "Write", "NotebookEdit", "LS"}:
        p = _resolve(str(inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""), workdir,
                     bare=True)
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
                p = _resolve(str(inp[key]), workdir, bare=True)
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
