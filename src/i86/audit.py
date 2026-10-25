"""Check that each forecaster worked independently.

The forecasters run on machines that also hold earlier forecasts of these questions, other runs'
answers and the operator's notes. The prompt forbids reading local files; this audit reads each run's
native transcript (Claude stream-json or Codex JSONL) and checks every tool call. It guards against
accidental and casual reads, not a forecaster set on hiding them.

Each shell command is parsed with tree-sitter's bash grammar, so quoting, here-documents, subshells,
command substitutions, pipelines, loops and redirections are read as the shell reads them (`cat
<file` reads `file`; a quoted `';'` is an argument, and the lines of a here-document fed to `cat` are
data). Local paths are then resolved against a tracked working directory:

- `~`, `$HOME`, `$PWD` and simple variable assignments expand, and substitutions such as
  `$(cd .. && pwd)` are worked out;
- `cd`, `pushd` and `popd` (options included) move the base for what follows in the same shell, not
  after a subshell, a command substitution, a pipeline stage or a nested `sh -c`;
- after a `cd` to a directory missing at audit time (often a scratch directory since deleted),
  relative paths are also resolved from where the shell would be had that `cd` failed, except inside
  an `&&` chain, which stops at a failed `cd`; directories made earlier in the command count as
  present;
- nested `sh -c`, `eval`, wrappers such as `xargs` and `env`, and shell code fed to a shell through a
  here-document or a pipe are parsed in turn;
- path-like strings inside interpreter code count, whether the code is an argument (`python -c`) or
  arrives on standard input (a here-document fed to `python3 -`);
- running a file by path counts as reading it, and `file://` URLs count as paths;
- globs are expanded against the real filesystem at audit time.

Each search tool's options are read with that tool's own arities, so a search pattern is not taken
for a path and a file operand is not taken for a pattern. Then:

- **Violations** exclude the run:
  - any resolved path, or the call's text outside URLs, inside a protected place (the repository,
    the staging area, any other run's work directory, agent homes and job stores, the author's notes
    and ledgers, session scratch directories);
  - a search rooted at the home directory or above (find, grep -r, rg, ls -R, tree, du, Grep, Glob
    and so on), and any use of locate or mdfind;
  - a content search (grep -r, rg, Grep, or a name search whose results feed another command through
    xargs, -exec, fd -x, a command substitution or a read loop) rooted above a protected place;
  - any MCP tool.
- **Suspect** calls are reported for the operator to read, without excluding the run: a name-only
  search rooted above a protected place, a listing of the home directory or above, a local path
  outside the work directory next to a term from these questions (foie, forecast, i86, ...), a
  relative path after a `cd` the audit cannot follow (an unexpandable target, a `cd` at the end of a
  pipeline), a relative path that would reach a protected place had a `cd` to a missing directory
  failed, a command the parser cannot fully read, a web call
  that opens this project's own repository (public, but without answers until every run has
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
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote

import tree_sitter_bash
from tree_sitter import Language, Parser

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
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
# Path-like strings inside code (python -c '...', node -e '...'), quoted or after an opening bracket.
EMBEDDED_PATH = re.compile(r"""(?:^|(?<=['"\s(=,:\[]))((?:~/|\.\./|\./|/)[^\s'"(),;\]]*)""")
FILE_URL = re.compile(r"""file://(?:localhost)?(/[^\s'"(),;\]]*)""", re.I)
# A quoted string without spaces inside code, and a file name with an extension.
QUOTED = re.compile(r"""(['"])([^'"\s]+)\1""")
FILE_NAME = re.compile(r"[\w.-]+\.[A-Za-z0-9]{1,6}")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
WRAPPERS = {"env", "nice", "nohup", "time", "sudo", "command", "builtin", "exec", "timeout", "stdbuf",
            "xargs", "caffeinate", "parallel", "watch", "unbuffer"}
GREP = {"grep", "egrep", "fgrep", "zgrep"}
# How each search tool reads its options. `short` and `long`: options that take a value (any other
# option takes none); `pattern`: options whose value is the pattern; `pattern_file` and `reads`:
# options whose value is a file the tool reads; `roots`: options whose value is a search root;
# `no_pattern`: options after which there is no pattern operand; `names`: options that make it a
# file-name search; `exec`: options after which the rest of the line is a command run on each result.
_GREP_SYNTAX = {
    "short": "efmABCdD",
    "long": {"regexp", "file", "max-count", "after-context", "before-context", "context", "directories",
             "devices", "include", "exclude", "exclude-dir", "exclude-from", "include-dir", "label",
             "binary-files", "group-separator"},
    "pattern": {"e", "regexp"}, "pattern_file": {"f", "file"}, "reads": {"exclude-from"},
}
_FD_SYNTAX = {
    "short": "dEetSocj",
    "long": {"max-depth", "min-depth", "exact-depth", "exclude", "type", "extension", "size", "changed-within",
             "changed-before", "change-newer-than", "change-older-than", "newer", "older", "owner",
             "base-directory", "search-path", "color", "threads", "max-results", "path-separator",
             "ignore-file", "format", "batch-size", "max-buffer-time"},
    "reads": {"ignore-file"}, "roots": {"base-directory", "search-path"},
    "exec": {"x", "X", "exec", "exec-batch"},
}
SEARCH_SYNTAX = {
    **dict.fromkeys(GREP, _GREP_SYNTAX),
    "rg": {
        "short": "ABCdEefgjMmrtT",
        "long": {"after-context", "before-context", "context", "context-separator", "color", "colors",
                 "dfa-size-limit", "encoding", "engine", "field-context-separator", "field-match-separator",
                 "file", "glob", "iglob", "hyperlink-format", "ignore-file", "max-columns", "max-count",
                 "max-depth", "maxdepth", "max-filesize", "path-separator", "pre", "pre-glob",
                 "regex-size-limit", "regexp", "replace", "sort", "sortr", "threads", "type", "type-not",
                 "type-add", "type-clear", "generate"},
        "pattern": {"e", "regexp"}, "pattern_file": {"f", "file"}, "reads": {"ignore-file"},
        "no_pattern": {"files", "type-list"}, "names": {"files"},
    },
    "ag": {
        "short": "ABCGgmpW",
        "long": {"after", "before", "context", "file-search-regex", "max-count", "depth", "path-to-ignore",
                 "ignore", "ignore-dir", "width", "pager", "workers"},
        "reads": {"p", "path-to-ignore"}, "no_pattern": {"g", "list-file-types"}, "names": {"g"},
    },
    "ack": {
        "short": "ABCmg",
        "long": {"after-context", "before-context", "context", "max-count", "type", "type-set", "type-add",
                 "type-del", "ignore-dir", "noignore-dir", "ignore-file", "match", "output", "pager"},
        "pattern": {"match"}, "no_pattern": {"f", "g"}, "names": {"f", "g"},
    },
    "fd": _FD_SYNTAX,
    "fdfind": _FD_SYNTAX,
}
# find tests whose value is a name, pattern or number, not a path.
FIND_VALUE_TESTS = {
    "-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-wholename", "-iwholename", "-lname",
    "-ilname", "-type", "-xtype", "-maxdepth", "-mindepth", "-size", "-mtime", "-mmin", "-atime", "-amin",
    "-ctime", "-cmin", "-perm", "-user", "-group", "-uid", "-gid", "-printf", "-links", "-inum",
    "-regextype", "-fstype", "-used",
}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "php", "Rscript", "osascript", "awk", "jq"}
SYSTEM_BIN = ("/bin/", "/usr/bin/", "/usr/local/bin/", "/opt/homebrew/bin/", "/sbin/", "/usr/sbin/")
DISK_SEARCH = {"locate", "mdfind", "plocate", "glocate"}
# Commands with no output, which leave a command substitution's value as it was.
SILENT = {"cd", "chdir", "pushd", "popd", "export", "declare", "typeset", "local", "readonly", "unset", "set",
          "true", "false", ":", "mkdir", "touch", "cp", "mv", "rm", "ln", "chmod", "test", "[", "[["}
# Ways a name search's results reach another command, which can then read them.
FEED = re.compile(r"\bxargs\b|\$\(|`|\s-(?:exec|execdir|ok|okdir)\b|\bwhile\s+read\b|\bparallel\b")
WEB_TOOLS = {"WebSearch", "WebFetch"}
# This project's own public repository. It holds no answers until every run has finished.
OWN_REPO = re.compile(r"dc-i86-llm-forecast", re.I)

_BASH = Parser(Language(tree_sitter_bash.language()))
# Markers inside word values: a variable to expand (\x01name\x02), and a value the audit cannot
# work out (the output of most command substitutions, say).
_VAR = re.compile("\x01([^\x02]*)\x02")
UNKNOWN = "\x00"
STATEMENTS = {
    "command", "redirected_statement", "pipeline", "list", "subshell", "compound_statement", "if_statement",
    "elif_clause", "else_clause", "while_statement", "for_statement", "c_style_for_statement",
    "case_statement", "case_item", "function_definition", "negated_command", "declaration_command",
    "variable_assignment", "variable_assignments", "test_command", "unset_command", "do_group", "ERROR",
}
REDIRECTS = {"file_redirect", "heredoc_redirect", "herestring_redirect"}


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
    """A shell word as a path, or None if it does not look like one. With `bare`, a plain name
    counts as a path too (after a `cd`, `cat notes` names a file in the new directory)."""
    token = token.strip("'\"")
    if token.lower().startswith("file:"):
        rest = token[5:]
        if rest.startswith("//"):
            host, _, rest = rest[2:].partition("/")
            if host.lower() not in {"", "localhost"}:
                return None
            rest = "/" + rest
        token = unquote(rest)
    if not token or UNKNOWN in token or token.startswith("-") or URL.match(token) or "=" in token.split("/")[0]:
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


def _text(node) -> str:
    return node.text.decode(errors="replace")


def _unquote_double(raw: bytes) -> str:
    """Text inside double quotes: a backslash escapes only $ ` " \\ and a newline (which it removes)."""
    return re.sub(r'\\([$`"\\])|\\\n', lambda m: m.group(1) or "", raw.decode(errors="replace"))


def _search_args(verb: str, args: list[str]) -> dict:
    """Read a search tool's arguments with its own option arities (SEARCH_SYNTAX)."""
    syn = SEARCH_SYNTAX[verb]
    out = {"operands": [], "values": set(), "files": [], "roots": [], "options": [], "pattern_option": False,
           "no_pattern": False, "names": False, "exec": False}
    j = 0
    while j < len(args):
        a = args[j]
        if a == "--":
            out["operands"] += range(j + 1, len(args))
            break
        if not a.startswith("-") or a == "-":
            out["operands"].append(j)
            j += 1
            continue
        opts: list[tuple[str, str | None]] = []
        if a.startswith("--"):
            name, eq, value = a[2:].partition("=")
            if name in syn.get("exec", ()):
                opts.append((name, None))
            elif eq:
                opts.append((name, value))
            elif name in syn["long"] and j + 1 < len(args):
                opts.append((name, args[j + 1]))
                out["values"].add(j + 1)
                j += 1
            else:
                opts.append((name, None))
        else:
            for k, c in enumerate(a[1:], start=1):
                if c in syn.get("exec", ()):
                    opts.append((c, None))
                    break
                if c in syn["short"]:
                    if a[k + 1:]:
                        opts.append((c, a[k + 1:]))
                    elif j + 1 < len(args):
                        opts.append((c, args[j + 1]))
                        out["values"].add(j + 1)
                        j += 1
                    break
                opts.append((c, None))
        for name, value in opts:
            out["options"].append((name, value))
            if name in syn.get("exec", ()):
                out["exec"] = True
            if name in syn.get("pattern", ()) or name in syn.get("pattern_file", ()):
                out["pattern_option"] = True
            if value and (name in syn.get("pattern_file", ()) or name in syn.get("reads", ())):
                out["files"].append(value)
            if value and name in syn.get("roots", ()):
                out["roots"].append(value)
            out["no_pattern"] |= name in syn.get("no_pattern", ())
            out["names"] |= name in syn.get("names", ())
        if out["exec"]:
            # The rest of the line is the command fd runs on each result.
            out["values"].update(range(j + 1, len(args)))
            break
        j += 1
    return out


class _Shell:
    """What one shell command reaches: paths, searches and notes, with the working directory tracked."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.cwd = workdir
        self.oldpwd = workdir
        self.stack: list[Path] = []
        self.known = True  # False after a cd the audit could not follow
        # Where else the shell could be. `cwd` assumes each cd succeeded; a cd to a directory missing
        # at audit time (a scratch directory since deleted, or one that never existed) may have
        # failed and left the shell where it was, so relative paths after it are resolved from
        # these too, into `alt_paths`.
        self.alts: list[Path] = []
        self.made: set[Path] = set()  # directories made by mkdir in this command
        self.alt_paths: list[Path] = []
        self.vars: dict[str, str] = {}
        self.paths: list[Path] = []
        # Paths found inside interpreter code, some of them fragments of URLs or patterns rather
        # than paths; they count for violations, but as paths outside the work directory only if
        # they exist.
        self.code_paths: list[Path] = []
        self.searches: list[tuple[str, str, Path]] = []
        self.notes: list[str] = []
        self.fed = False
        # What the last command printed, when the audit can tell (pwd, echo, cat of a here-document);
        # None when it cannot. Command substitutions and pipelines read it.
        self.output: str | None = None

    # Scope and values

    @contextmanager
    def child(self):
        """A subshell: directory changes and variables inside it do not outlast it."""
        saved = (self.cwd, self.oldpwd, list(self.stack), self.known, list(self.alts), dict(self.vars))
        try:
            yield
        finally:
            self.cwd, self.oldpwd, self.stack, self.known, self.alts, self.vars = saved

    def expand(self, word: str) -> str:
        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name == "HOME":
                return str(HOME)
            if name == "PWD":
                return str(self.cwd)
            if name == "OLDPWD":
                return str(self.oldpwd)
            return self.vars.get(name, "$" + name)

        return _VAR.sub(sub, word)

    def value(self, node) -> str:
        """A word's value after quote removal, with variables marked for `expand`. Command
        substitutions inside it are run (in a subshell) along the way."""
        t = node.type
        if t == "word":
            return re.sub(r"\\(.)", r"\1", _text(node), flags=re.S)
        if t == "raw_string":
            return _text(node)[1:-1]
        if t == "ansi_c_string":
            try:
                return _text(node)[2:-1].encode().decode("unicode_escape")
            except UnicodeDecodeError:
                return _text(node)[2:-1]
        if t in {"string", "translated_string"}:
            # Build from the source span: the grammar leaves some characters (newlines among them)
            # outside every child node.
            src, base = node.text, node.start_byte
            pos, end = (2 if t == "translated_string" else 1), len(src) - 1
            parts = []
            for c in node.named_children:
                cs, ce = c.start_byte - base, c.end_byte - base
                if cs > pos:
                    parts.append(_unquote_double(src[pos:cs]))
                parts.append(_unquote_double(c.text) if c.type == "string_content" else self.value(c))
                pos = max(pos, ce)
            if end > pos:
                parts.append(_unquote_double(src[pos:end]))
            return "".join(parts)
        if t == "simple_expansion":
            name = node.named_children[0] if node.named_children else None
            if name is not None and name.type == "variable_name":
                return "\x01" + _text(name) + "\x02"
            return UNKNOWN
        if t == "expansion":
            text = _text(node)
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
            if m:
                return "\x01" + m.group(1) + "\x02"
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*):?[-=]([^}$`]*)\}", text)
            if m:
                return "\x01" + m.group(1) + "\x02" if m.group(1) in self.vars else m.group(2)
            for c in node.named_children:
                self.value(c)  # runs any command substitution inside
            return UNKNOWN
        if t == "command_substitution":
            return self.substitute(node)
        if t == "process_substitution":
            with self.child():
                for c in node.named_children:
                    self.visit(c)
            return UNKNOWN
        if t == "arithmetic_expansion":
            return UNKNOWN
        if node.child_count == 0:
            return _text(node)
        if t == "concatenation":
            return "".join(self.value(c) for c in node.children)
        return "".join(self.value(c) for c in node.named_children) or _text(node)

    def substitute(self, node) -> str:
        """Run a command substitution in a subshell; its value if the audit can tell it."""
        self.output = ""
        with self.child():
            for c in node.named_children:
                self.visit(c)
        out, self.output = self.output, None
        return UNKNOWN if out is None else out.rstrip("\n")

    def resolve(self, word: str, bare: bool) -> Path | None:
        return _resolve(self.expand(word), self.cwd, bare=bare)

    def add(self, word: str, bare: bool) -> Path | None:
        p = self.resolve(word, bare)
        if p is not None:
            self.paths.extend(_expand(p))
            text = self.expand(word).strip("'\"")
            relative = not os.path.isabs(text) and not text.startswith(("~", "file:"))
            if relative and not self.known:
                self.notes.append("a relative path after a cd the audit could not follow")
            if relative:
                for alt in self.alts:
                    q = _resolve(self.expand(word), alt, bare=bare)
                    if q is not None:
                        self.alt_paths.extend(_expand(q))
        return p

    def scan_code(self, code: str) -> None:
        """Path-like strings and file URLs inside interpreter code. A quoted relative path counts
        too (`Path('notes/x')`), and after a cd, so does a quoted file name (`open('draft.json')`)."""
        found: list[tuple[str, bool]] = [(m.group(1), False) for m in EMBEDDED_PATH.finditer(code)
                                         if not m.group(1).startswith("//")]  # a URL's remainder
        found += [(m.group(1), False) for m in FILE_URL.finditer(code)]
        moved = self.cwd != self.workdir
        for m in QUOTED.finditer(code):
            word = m.group(2)
            if "/" in word:
                found.append((word, False))
            elif moved and FILE_NAME.fullmatch(word):
                found.append((word, True))
        before = len(self.paths)
        for word, bare in found:
            self.add(word, bare=bare)
        self.code_paths += self.paths[before:]

    # Statements

    def run(self, text: str) -> None:
        self.fed = self.fed or bool(FEED.search(text))
        tree = _BASH.parse(text.encode())
        if tree.root_node.has_error:
            self.notes.append("part of a command the audit could not parse")
        self.visit(tree.root_node)

    def visit(self, node) -> None:
        t = node.type
        if t == "command":
            self.simple(node)
        elif t == "redirected_statement":
            self.redirected(node)
        elif t == "pipeline":
            self.pipeline([c for c in node.named_children if c.type in STATEMENTS])
        elif t == "list":
            self.and_or(node)
        elif t == "subshell":
            with self.child():
                for c in node.named_children:
                    self.visit(c)
        elif t == "function_definition":
            body = node.child_by_field_name("body")
            if body is not None:
                with self.child():
                    self.visit(body)
        elif t == "variable_assignment":
            self.assign(node)
        elif t == "variable_assignments":
            for c in node.named_children:
                self.assign(c)
        elif t == "declaration_command":
            for c in node.named_children:
                if c.type == "variable_assignment":
                    self.assign(c)
        elif t == "for_statement":
            self.for_loop(node)
        elif t == "test_command":
            for c in node.named_children:
                self.test_words(c)
        elif t == "ERROR":
            words = []
            for c in node.named_children:
                if c.type in STATEMENTS:
                    self.visit(c)
                elif c.type not in {"comment"}:
                    words.append(self.expand(self.value(c)))
            if words:
                self.command(words)
        elif t in {"comment", "heredoc_body", "heredoc_start", "heredoc_end"}:
            return
        elif t in REDIRECTS:
            self.redirect([node], None)
        else:
            for c in node.named_children:
                if c.type in STATEMENTS or c.type in REDIRECTS:
                    self.visit(c)
                elif c.type in {"command_substitution", "process_substitution", "string", "concatenation",
                                "expansion"}:
                    self.value(c)

    def and_or(self, node) -> None:
        """`a && b` runs b only if a succeeded, so b runs where a cd in a took the shell, not where
        a failed cd would have left it. After the list, the shell may be in any of those places."""
        op = None
        for c in node.children:
            if not c.is_named:
                op = _text(c)
                continue
            if c.type not in STATEMENTS:
                continue
            if op == "&&" and self.alts:
                saved, self.alts = self.alts, []
                self.visit(c)
                self.alts = list(dict.fromkeys([*saved, *self.alts]))
            else:
                self.visit(c)

    def test_words(self, node) -> None:
        """Operands of a [ ... ] or [[ ... ]] test, which can look at files."""
        if node.type in {"word", "string", "raw_string", "concatenation", "simple_expansion", "expansion",
                         "command_substitution"}:
            self.add(self.expand(self.value(node)), bare=False)
        else:
            for c in node.named_children:
                self.test_words(c)

    def for_loop(self, node) -> None:
        var = node.child_by_field_name("variable")
        items = [self.expand(self.value(v)) for v in node.children_by_field_name("value")]
        for item in items:
            self.add(item, bare=False)
        body = node.child_by_field_name("body")
        if body is None:
            return
        values: list[str] = []
        for item in items:
            p = self.resolve(item, bare=True) if any(c in item for c in "*?[") else None
            values += [str(x) for x in _expand(p)] if p is not None else [item]
        for item in values[:20] or [None]:
            if var is not None and item is not None:
                self.vars[_text(var)] = item
            self.visit(body)

    def assign(self, node) -> None:
        name = node.child_by_field_name("name")
        val = node.child_by_field_name("value")
        if name is None:
            return
        value = self.expand(self.value(val)) if val is not None else ""
        self.vars[_text(name)] = value
        self.add(value, bare=False)

    def pipeline(self, stages: list, data: str | None = None, tail: list | None = None) -> None:
        """Each stage runs in a subshell, fed what the stage before it printed (when known). `tail`:
        redirections written after the pipeline, which belong to its last stage."""
        for i, stage in enumerate(stages):
            self.output = None
            with self.child():
                if tail and i == len(stages) - 1:
                    self.with_redirects(stage, tail, data)
                else:
                    self.statement(stage, data)
            data = self.output
        if stages and self._is_cd(stages[-1]):
            # zsh keeps a cd in the last stage; bash does not. The audit cannot tell which ran.
            self.known = False
            self.notes.append("a cd at the end of a pipeline")

    @staticmethod
    def _is_cd(node) -> bool:
        if node.type == "redirected_statement":
            node = node.child_by_field_name("body") or node
        name = node.child_by_field_name("name") if node.type == "command" else None
        return name is not None and os.path.basename(_text(name)) in {"cd", "pushd", "popd", "chdir"}

    def statement(self, node, stdin: str | None) -> None:
        if node.type == "command":
            self.simple(node, stdin=stdin)
        elif node.type == "redirected_statement":
            self.redirected(node, stdin)
        else:
            self.visit(node)

    def redirected(self, node, stdin: str | None = None, outer: list | None = None) -> None:
        body = node.child_by_field_name("body")
        redirects = [c for c in node.named_children if c.type in REDIRECTS] + list(outer or [])
        self.with_redirects(body, redirects, stdin)

    def with_redirects(self, body, redirects: list, stdin: str | None) -> None:
        """A statement and the redirections written after it. In `cd .. && python3 - <<EOF` the
        grammar attaches the here-document to the whole list; in the shell it, like any redirection
        after a list or pipeline, belongs to the last command."""
        if body is None:
            _, after = self.redirect(redirects, stdin)
            for stmt in after:
                self.visit(stmt)
        elif body.type == "command":
            self.simple(body, redirects, stdin)
        elif body.type == "redirected_statement":
            self.redirected(body, stdin, redirects)
        elif body.type == "list":
            stmts = [c for c in body.named_children if c.type in STATEMENTS]
            for stmt in stmts[:-1]:
                self.visit(stmt)
            if stmts:
                self.with_redirects(stmts[-1], redirects, stdin)
        elif body.type == "pipeline":
            self.pipeline([c for c in body.named_children if c.type in STATEMENTS], tail=redirects)
        else:
            _, after = self.redirect(redirects, stdin)
            for stmt in [body, *after]:
                self.visit(stmt)

    def redirect(self, redirects: list, stdin: str | None) -> tuple[str | None, list]:
        """Note the files that redirections name; return what reaches standard input (a
        here-document or here-string, when there is one) and any statements a here-document
        carries after it (the rest of a pipeline, say)."""
        after: list = []
        for r in redirects:
            if r.type == "file_redirect":
                op = "".join(_text(c) for c in r.children if not c.is_named)
                dest = r.child_by_field_name("destination")
                if dest is None:
                    named = [c for c in r.named_children if c.type != "file_descriptor"]
                    dest = named[-1] if named else None
                if dest is None:
                    continue
                target = self.expand(self.value(dest))
                if op.endswith("&") and (target.isdigit() or target == "-"):
                    continue  # duplicates a file descriptor
                self.add(target, bare=True)
            elif r.type == "heredoc_redirect":
                start = next((c for c in r.named_children if c.type == "heredoc_start"), None)
                body = next((c for c in r.named_children if c.type == "heredoc_body"), None)
                quoted = start is not None and any(q in _text(start) for q in "'\"\\")
                if body is not None and not quoted:
                    for c in body.named_children:
                        if c.type in {"command_substitution", "expansion", "simple_expansion"}:
                            self.value(c)
                stdin = _text(body) if body is not None else ""
                for c in r.named_children:
                    if c.type == "file_redirect":
                        self.redirect([c], None)
                    elif c.type in STATEMENTS:
                        after.append(c)
            elif r.type == "herestring_redirect":
                parts = [c for c in r.named_children]
                stdin = " ".join(self.expand(self.value(c)) for c in parts)
        return stdin, after

    def simple(self, node, redirects: list | None = None, stdin: str | None = None) -> None:
        assigns, words, redirs = [], [], list(redirects or [])
        for c in node.named_children:
            if c.type == "variable_assignment":
                assigns.append(c)
            elif c.type in REDIRECTS:
                redirs.append(c)
            elif c.type == "command_name":
                inner = c.named_children[0] if c.named_children else c
                words.append(self.value(inner) if inner is not c else _text(c))
            elif c.type != "comment":
                words.append(self.value(c))
        # Words expand before the command's own assignments take effect, as in the shell.
        words = [self.expand(w) for w in words]
        stdin, after = self.redirect(redirs, stdin)
        if not words:
            for a in assigns:
                self.assign(a)
        else:
            saved = {}
            for a in assigns:
                name = a.child_by_field_name("name")
                if name is not None:
                    saved[_text(name)] = self.vars.get(_text(name))
                self.assign(a)
            self.command(words, stdin)
            for name, old in saved.items():
                if old is None:
                    self.vars.pop(name, None)
                else:
                    self.vars[name] = old
        for stmt in after:
            if stmt.type == "pipeline":
                # `cat <<EOF | python3`: the rest of the pipeline reads what this command printed.
                data = self.output
                self.pipeline([c for c in stmt.named_children if c.type in STATEMENTS], data)
            else:
                self.visit(stmt)

    # Commands

    def chdir(self, target: str | None) -> None:
        if target is None:
            new = HOME
        else:
            if "$" in target or UNKNOWN in target:
                self.known = False
                self.notes.append(f"cd to {target.replace(UNKNOWN, '<unknown>')}, which the audit cannot expand")
                return
            new = _resolve(target, self.cwd, bare=True) or self.cwd
            alts = []
            for here in [self.cwd, *self.alts]:
                there = new if here == self.cwd else _resolve(target, here, bare=True) or here
                alts.append(there)
                if not (there.is_dir() or there in self.made):
                    alts.append(here)  # the cd may have failed and left the shell here
            self.alts = [a for a in dict.fromkeys(alts) if a != new][:8]
        if target is None:
            self.alts = []
        self.oldpwd, self.cwd = self.cwd, new
        self.paths.append(new)

    def command(self, words: list[str], stdin: str | None = None) -> None:
        if not words:
            return
        verb_word, args = words[0], words[1:]
        if "/" in verb_word and not verb_word.startswith(SYSTEM_BIN):
            self.add(verb_word, bare=True)  # running a file by path reads it
        verb = os.path.basename(verb_word)
        if verb not in SILENT:
            self.output = None
        if verb in {"export", "declare", "typeset", "local", "readonly"}:
            for a in args:
                if ASSIGN.match(a):
                    name, value = ASSIGN.match(a).groups()
                    self.vars[name] = value
                    self.add(value, bare=False)
            return
        if verb in SHELLS:
            for j, a in enumerate(args):
                if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) and j + 1 < len(args):
                    with self.child():
                        self.run(args[j + 1])
                    return
            scripts = [a for a in args if not a.startswith("-")]
            for a in scripts:
                self.add(a, bare=True)  # a script file
            if not scripts and stdin:
                with self.child():
                    self.run(stdin)  # shell code on standard input
            return
        if verb == "eval":
            self.run(" ".join(args))
            return
        if verb in {"source", "."}:
            if args:
                self.add(args[0], bare=True)
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
            if verb == "xargs" and stdin:
                try:
                    items = shlex.split(stdin)
                except ValueError:
                    items = stdin.split()
                for item in items:
                    self.add(item, bare=True)  # xargs passes these to the command as arguments
            if rest:
                self.command(rest, None if verb == "xargs" else stdin)
            return
        if verb == "mkdir":
            for a in args:
                if not a.startswith("-"):
                    p = self.resolve(a, bare=True)
                    if p is not None:
                        self.made.update([p, *p.parents])
        if verb in {"cd", "pushd", "chdir"}:
            operands = [a for a in args if not (a.startswith("-") and a != "-")]
            if verb == "pushd":
                self.stack.append(self.cwd)
            if operands and operands[0] == "-":
                self.oldpwd, self.cwd = self.cwd, self.oldpwd
                self.alts = []
                self.paths.append(self.cwd)
            else:
                self.chdir(operands[0] if operands else None)
            return
        if verb == "popd":
            if self.stack:
                self.oldpwd, self.cwd = self.cwd, self.stack.pop()
                self.alts = []
            return
        if verb == "pwd":
            self.output = str(self.cwd) if self.known else None
            return
        operands = [a for a in args if not a.startswith("-")]
        if verb in {"realpath", "grealpath"} or (verb in {"readlink", "greadlink"} and any(
                re.fullmatch(r"-[a-zA-Z]*[fem][a-zA-Z]*", a) for a in args)):
            p = self.add(operands[0], bare=True) if operands else None
            self.output = str(p) if p is not None and self.known else None
            return
        if verb in {"dirname", "basename"} and operands:
            self.output = (os.path.dirname if verb == "dirname" else os.path.basename)(operands[0])
            return
        if verb == "echo":
            self.output = " ".join(a for a in args if a not in {"-n", "-e", "-E"})
        elif verb == "printf" and args and args[0] in {"%s", "%s\n", "%s\\n"}:
            self.output = " ".join(args[1:])
        elif verb in {"cat", "tee"} and not operands:
            self.output = stdin

        bare = self.cwd != self.workdir
        skip: set[int] = set()
        roots: list[Path] = []
        if verb in SEARCH_SYNTAX:
            parsed = _search_args(verb, args)
            skip |= parsed["values"]
            for f in parsed["files"]:
                self.add(f, bare=True)
            positional = parsed["operands"]
            if positional and not (parsed["pattern_option"] or parsed["no_pattern"]):
                skip.add(positional[0])
                positional = positional[1:]
            options = parsed["options"]
            recursive = verb not in GREP or any(
                name in {"r", "R", "recursive", "dereference-recursive"}
                or (name in {"d", "directories"} and value == "recurse") for name, value in options)
            if recursive:
                roots = [p for k in positional for p in [self.resolve(args[k], bare=True)] if p is not None]
                roots += [p for r in parsed["roots"] for p in [self.resolve(r, bare=True)] if p is not None]
                roots = roots or [self.cwd]
                names = (verb in {"fd", "fdfind"} or parsed["names"]) and not (self.fed or parsed["exec"])
                self.searches += [(verb, "names" if names else "content", r) for r in roots]
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
            roots = [p for a in operands for p in [self.resolve(a, bare=True)] if p is not None] or [self.cwd]
            self.searches += [(verb, "content" if self.fed else "names", r) for r in roots]
        elif verb == "ls":
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
                self.scan_code(a)
        if code and stdin:
            self.scan_code(stdin)  # code (or data the code reads) on standard input


def _shell(command: str, workdir: Path) -> _Shell:
    shell = _Shell(workdir)
    shell.run(command)
    return shell


def shell_paths(command: str, workdir: Path) -> tuple[list[Path], list[tuple[str, str, Path]], list[str]]:
    """Resolved local paths in a shell command; the searches in it as (verb, kind, root), kind being
    'names', 'content' or 'disk'; and notes for the operator."""
    shell = _shell(command, workdir)
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
    paths, searches, notes, weak, alt = [], [], [], [], []
    if tool in {"shell", "Bash"}:
        shell = _shell(inp.get("command", ""), workdir)
        paths, searches, notes, weak = shell.paths, shell.searches, shell.notes, shell.code_paths
        alt = shell.alt_paths  # relative paths resolved as if a cd to a missing directory had failed
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
    # Had a cd to a directory missing at audit time failed, a relative path would reach these.
    # Whether it failed is not in the transcript, so a hit is for the operator to read.
    for p in alt:
        if any(_under(p, r) or _pattern_hits(p, r) for r in roots) or _reaches_sibling(p, workdir):
            notes = [*notes, f"reaches {p} if a cd to a directory missing at audit time failed"]
            break
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
    if tool in {"shell", "Bash"} and any(OWN_REPO.search(u) for u in URL.findall(text)):
        notes = [*notes, "opens this project's repository on the web"]
    if notes:
        return "suspect", "; ".join(dict.fromkeys(notes))
    weak_ids = {id(p) for p in weak}
    outside = [p for p in paths if not _under(p, workdir)
               and (id(p) not in weak_ids or (p.exists() and p != Path("/")))]
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
