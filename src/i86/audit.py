"""Check that each forecaster worked independently.

The forecasters run on machines that also hold earlier forecasts of these questions, other runs'
answers and the operator's notes. The prompt forbids reading local files; this audit reads each run's
native transcript (Claude stream-json or Codex JSONL) and checks every tool call. It guards against
accidental and casual reads, not a forecaster set on hiding them.

Each shell command is parsed with tree-sitter's bash grammar, so quoting, here-documents, subshells,
command substitutions, pipelines, loops, functions and redirections are read as the shell reads them
(`cat <file` reads `file`; a quoted `';'` is an argument, and the lines of a here-document fed to
`cat` are data). The grammar misreads `!` before a compound command (`! { ...; }`, `! if ...`); the
audit reads those itself, and any other command it cannot fully read is suspect.

The working directory is tracked as the set of places the shell could be, each with the last
command's exit status (`_World`):

- `cd`, `pushd` and `popd` move every place. A `cd` to a directory missing at audit time (often a
  scratch directory since deleted), or one the same command makes only later or removed earlier,
  may have worked or failed: the shell is then in either place, and the failed one is an
  alternative. `CDPATH` is followed, and a `cd -` before any `cd` in the command goes where the
  audit cannot follow.
- `&&`, `||`, `if`, `while`, `until`, `case` and loops run their parts only where the status allows.
  The audit knows the status of `true`, `false`, `:`, `cd`, `!`, tests of known strings and numbers
  (`[ a = b ]`, `[[ ... ]]`, `test`), file tests of things present at audit time, literal `case`
  values, and commands that all but always succeed (`echo`, `mkdir -p`, assignments); after anything
  else, both ways may have run. Where the way was unknown, places reached only by the way not meant
  (the skipped side of `x && cd ..`) are alternatives too.
- Subshells, command substitutions, pipeline stages, background jobs, `sh -c` and wrapped commands
  with their own directory (`env -C`, `sudo -D`) leave the places after them unchanged, with two
  exceptions in zsh: it runs a pipeline's last stage in the current shell (`x | cd d`,
  `x | while read d; do cd "$d"; done`), as bash does after `shopt -s lastpipe`, and of an and-or
  list ending in `&` it runs only the last pipeline in the background (`cd a && make &` leaves zsh
  in a). The audit follows the shell a command names (`zsh -c`, `bash -c`); where none is named,
  or it is `sh`, it keeps the places either way would leave.
- Functions run in the calling shell with their arguments as positional parameters; aliases are
  followed. Variables, `export`, `read` from a known input (`while read` loops line by line), and
  positional parameters for `sh -c CODE NAME ARGS`, `sh -s ARGS` and shell code on standard input
  are expanded. A variable that branches may each have set differently has each of their values,
  and a function or alias they may each have defined differently, or not at all, runs as each.
- Past 64 places the audit stops following the directory.

Local paths are then resolved from every place:

- `~`, `$HOME`, `$PWD` and the variables above expand, and substitutions such as
  `$(cd .. && pwd)` are worked out; a path with a part the audit cannot work out is matched as a
  pattern;
- nested `sh -c`, `eval`, wrappers (`xargs`, `env`, `timeout` and the like, with their options'
  values) and shell code fed to a shell through a here-document or a pipe are parsed in turn;
- a command's own directory option (`git -C`, `make -C`, `tar -C`, `uv --directory`, ...) is a further
  base for its relative paths;
- interpreter code (`python -c`, `node -e`, awk and jq programs, sed scripts, code on standard input)
  is scanned for path-like strings and file URLs, never taken as a path itself, and a literal
  directory change in it (`os.chdir('x')`) moves the base for the paths after it;
- running a file by path counts as reading it, and `file://` URLs count as paths;
- globs are expanded against the real filesystem at audit time.

Each search tool's options are read with that tool's own arities, so a search pattern is not taken
for a path and a file operand is not taken for a pattern. Then:

- **Violations** exclude the run:
  - any path resolved from a main place, or the call's text outside URLs, inside a protected place
    (the repository, the staging area, any other run's work directory, agent homes and job stores,
    the author's notes and ledgers, session scratch directories);
  - a search rooted at the home directory or above (find, grep -r, rg, ls -R, tree, du, Grep, Glob
    and so on), and any use of locate or mdfind;
  - a content search (grep -r, rg, Grep, or a name search whose results reach another command: a
    later pipeline stage that is xargs, parallel, a shell or a read loop, a command or process
    substitution, find -exec, fd -x) rooted above a protected place;
  - any MCP tool.
- **Suspect** calls are reported for the operator to read, without excluding the run: a name-only
  search rooted above a protected place, a listing of the home directory or above, a local path
  outside the work directory next to a term from these questions (foie, forecast, i86, ...), a
  relative path after a `cd` the audit cannot follow (an unexpandable target, a `cd` at the end of a
  pipeline, more places than it tracks), a path or search from an alternative place that would reach
  a protected place, a path with an unknown part that could, a command the parser cannot fully read,
  a web call that opens this project's own repository (public, but without answers until every run
  has finished), and sub-agent calls whose contents the transcript does not show.
- Other local calls are listed. Web calls (WebSearch, WebFetch, Codex web_search, curl and wget) are
  counted and their URLs logged.

Whether a directory exists is judged at audit time, apart from what the same command makes or
removes; output the audit cannot work out (most commands' output, a file's contents) is unknown.

A transcript with no parseable events fails the audit.
"""

from __future__ import annotations

import fnmatch
import glob as globlib
import itertools
import json
import os
import re
import shlex
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import NamedTuple
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
# How each shell runs code where shells differ (see `_Shell.dialect`); sh, ksh and the rest may run it
# either way.
DIALECTS = {"zsh": "zsh", "bash": "posix", "dash": "posix"}
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
                 "file", "glob", "iglob", "hostname-bin", "hyperlink-format", "ignore-file", "max-columns",
                 "max-count", "max-depth", "maxdepth", "max-filesize", "path-separator", "pre", "pre-glob",
                 "regex-size-limit", "regexp", "replace", "sort", "sortr", "threads", "type", "type-not",
                 "type-add", "type-clear", "generate"},
        "pattern": {"e", "regexp"}, "pattern_file": {"f", "file"}, "reads": {"ignore-file", "pre", "hostname-bin"},
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
SYSTEM_BIN = ("/bin/", "/usr/bin/", "/usr/local/bin/", "/opt/homebrew/bin/", "/sbin/", "/usr/sbin/")
DISK_SEARCH = {"locate", "mdfind", "plocate", "glocate"}
# Commands with no output, which leave a command substitution's value as it was.
SILENT = {"cd", "chdir", "pushd", "popd", "export", "declare", "typeset", "local", "readonly", "unset", "set",
          "true", "false", ":", "mkdir", "touch", "cp", "mv", "rm", "ln", "chmod", "test", "[", "[["}
# Commands that all but always succeed (and `mkdir -p`), so `echo x && cd y` certainly runs the cd.
SUCCEEDS = {"true", ":", "echo", "printf", "pwd", "export", "declare", "typeset", "local", "readonly", "set",
            "unset", "shopt"}
# Commands the audit follows that change the shell they run in. As a pipeline's last stage they
# matter in zsh, which runs that stage in the current shell (see `_Shell.pipeline`); so do function
# and alias calls and compound commands.
STATEFUL = {"cd", "chdir", "pushd", "popd", "read", "export", "declare", "typeset", "local", "readonly", "alias",
            "eval", "source", ".", "exit", "shopt", "command", "builtin", "exec"}
# Commands that read names from standard input and act on them: a name search piped into one is
# reading what it finds.
NAME_READERS = {"xargs", "parallel", *SHELLS}
# Each wrapper's options that take a value (WRAPPER_VALUES); those whose value is a directory the
# wrapped command runs in (WRAPPER_CHDIR) or a file the wrapper reads (WRAPPER_FILES).
_XARGS_VALUES = {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J", "-R", "-S", "--max-args", "--max-procs",
                 "--max-lines", "--max-chars", "--delimiter", "--arg-file", "--process-slot-var"}
WRAPPER_VALUES = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "-D", "--user", "--group", "--host", "--prompt",
             "--close-from", "--role", "--type", "--command-timeout", "--other-user", "--chdir"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "exec": {"-a"},
    "time": {"-o", "--output", "-f", "--format"},
    "caffeinate": {"-t", "-w"},
    "watch": {"-n", "--interval"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "xargs": _XARGS_VALUES,
    "parallel": {"-j", "--jobs", "-a", "--arg-file", "-I", "-n", "-N"},
}
WRAPPER_CHDIR = {"env": {"-C", "--chdir"}, "sudo": {"-D", "--chdir"}}
WRAPPER_FILES = {"xargs": {"-a", "--arg-file"}, "parallel": {"-a", "--arg-file"}, "time": {"-o", "--output"}}
# Options naming a directory a command works in; its relative operands are resolved from there too.
# For tar (DIR_BARE) a plain name after -C is a file in that directory.
DIR_OPTIONS = {
    "git": {"-C"}, "make": {"-C", "--directory"}, "gmake": {"-C", "--directory"},
    **dict.fromkeys(["tar", "gtar", "bsdtar"], {"-C", "--directory", "--cd"}),
    "uv": {"--directory", "--project"}, "npm": {"--prefix"}, "pnpm": {"-C", "--dir"}, "yarn": {"--cwd"},
    "bun": {"--cwd"}, "cargo": {"-C"}, "unzip": {"-d"}, "cmake": {"-S", "-B"},
}
DIR_BARE = {"tar", "gtar", "bsdtar"}
# How each interpreter takes its code. `code`: options whose value is code; `first`: with no code
# option (or -f), the first operand is code; `values`: options taking that many values that are
# neither code nor paths; `files`: options whose last value is a file the interpreter reads;
# `empty_value`: options that take an empty-string value (BSD `sed -i ''`). Code is scanned for
# paths (`scan_code`), never taken as a path itself.
_PYTHON = {"code": {"-c"}, "values": {"-m": 1, "-W": 1, "-X": 1}}
_AWK = {"code": {"-e", "--source"}, "values": {"-F": 1, "-v": 1}, "files": {"-f": 1, "--file": 1}, "first": True}
CODE_SYNTAX = {
    "python": _PYTHON, "python3": _PYTHON,
    **dict.fromkeys(["node", "nodejs"], {"code": {"-e", "--eval", "-p", "--print"},
                                         "files": {"-r": 1, "--require": 1, "--import": 1}}),
    "perl": {"code": {"-e", "-E"}, "values": {"-I": 1, "-M": 1, "-m": 1}},
    "ruby": {"code": {"-e"}, "values": {"-I": 1, "-r": 1}},
    "php": {"code": {"-r"}, "values": {"-d": 1}},
    "Rscript": {"code": {"-e"}},
    "osascript": {"code": {"-e"}, "values": {"-l": 1}},
    **dict.fromkeys(["awk", "gawk", "mawk", "nawk"], _AWK),
    "jq": {"values": {"--arg": 2, "--argjson": 2, "--indent": 1},
           "files": {"-f": 1, "--from-file": 1, "--slurpfile": 2, "--rawfile": 2, "-L": 1}, "first": True},
    **dict.fromkeys(["sed", "gsed"], {"code": {"-e", "--expression"}, "values": {"-l": 1},
                                      "files": {"-f": 1, "--file": 1}, "first": True, "empty_value": {"-i"}}),
}
# A literal directory change inside interpreter code: os.chdir('x'), process.chdir('x'),
# Dir.chdir('x'), chdir('x') in Perl or PHP, setwd('x') in R.
CODE_CHDIR = re.compile(r"""(?:\b(?:os\.|process\.|Dir\.)?chdir|\bsetwd)\s*\(?\s*(['"])([^'"]+)\1""")
WEB_TOOLS = {"WebSearch", "WebFetch"}
# This project's own public repository. It holds no answers until every run has finished.
OWN_REPO = re.compile(r"dc-i86-llm-forecast", re.I)

_BASH = Parser(Language(tree_sitter_bash.language()))
# Markers inside word values: a variable to expand (\x01name\x02), and a value the audit cannot
# work out (the output of most command substitutions, say).
_VAR = re.compile("\x01([^\x02]*)\x02")
UNKNOWN = "\x00"
# Separates the words "$@" expands to.
SPLIT = "\x03"
# A value with several possibilities (a variable set differently in branches that may each have
# run): \x06a\x05b\x07 is a or b.
CHOICE = re.compile("\x06([^\x06\x07]*)\x07")
POSITIONAL = [*map(str, range(1, 10)), "#", "@", "*"]
# A command's exit status as far as the audit can tell, in each place the shell could be.
OK, FAILED, MAYBE, EXITED = "ok", "failed", "maybe", "exited"
MAX_WORLDS = 64
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


def _choices(text: str) -> list[str]:
    """Each value a text with \\x06a\\x05b\\x07 groups can take (at most 64)."""
    groups = [m.group(1).split("\x05") for m in CHOICE.finditer(text)]
    if not groups:
        return [text]
    pieces = CHOICE.split(text)[::2]
    out = []
    for combo in itertools.islice(itertools.product(*groups), 64):
        out.append("".join(p + c for p, c in zip(pieces, combo)) + pieces[-1])
    return out


# Words the grammar takes as command names only when it has misread a compound command.
RESERVED = {"{", "}", "if", "then", "elif", "else", "fi", "for", "select", "while", "until", "do", "done",
            "case", "esac"}


def _assignment_status(node) -> str:
    """An assignment succeeds unless a command substitution in it fails."""
    def substitutes(n) -> bool:
        return n.type in {"command_substitution", "process_substitution"} or any(map(substitutes, n.children))
    return MAYBE if substitutes(node) else OK


def _read_names(args: list[str]) -> list[str]:
    """The variables `read` sets, from its arguments (REPLY with none)."""
    names, j = [], 0
    while j < len(args):
        if args[j] in {"-d", "-n", "-N", "-p", "-t", "-u", "-a", "-k"}:
            j += 2
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args[j]):
            names.append(args[j])
        j += 1
    return names or ["REPLY"]


def _reserved(name) -> bool:
    """A command name the grammar produced by misreading a compound command (`{ {` included)."""
    words = _text(name).split() if name is not None else []
    return bool(words) and words[0] in RESERVED


def _reserved_commands(node) -> bool:
    if node.type == "command" and _reserved(node.child_by_field_name("name")):
        return True
    return any(_reserved_commands(c) for c in node.children)


def _misread_bangs(node) -> list[int]:
    """Offsets of each `!` before a compound command (`! { ...; }`, `! if ...`): the grammar takes
    only a simple command, a subshell or a test after `!`, and reads the rest wrongly."""
    out = []
    if node.type == "negated_command":
        bang = node.children[0] if node.children else None
        first = node.named_children[0] if node.named_children else None
        name = first.child_by_field_name("name") if first is not None and first.type == "command" else None
        if bang is not None and _text(bang) == "!" and (
                _reserved(name) or node.has_error or first is None
                or first.type == "ERROR"):
            out.append(bang.start_byte)
    for c in node.children:
        out += _misread_bangs(c)
    return out


def _parseable(data: bytes) -> tuple[bytes, set[int]]:
    """The command with each misread `!` blanked (offsets unchanged), and where the statements
    they negated start."""
    negate: set[int] = set()
    for _ in range(16):
        bangs = _misread_bangs(_BASH.parse(data).root_node)
        if not bangs:
            break
        b = bytearray(data)
        for pos in bangs:
            b[pos] = 0x20
            nxt = pos + 1
            while nxt < len(b) and b[nxt] in b" \t":
                nxt += 1
            negate.add(nxt)
        data = bytes(b)
    return data, negate


def _expand(path: Path) -> list[Path]:
    text = str(path)
    if any(c in text for c in "*?["):
        return [Path(p) for p in globlib.glob(text)] or [path]
    return [path]


def _body(node):
    """A redirected statement's body (the statement itself otherwise)."""
    if node.type == "redirected_statement":
        return node.child_by_field_name("body") or node
    return node


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


class _World(NamedTuple):
    """One place the shell could be: its directory, `$OLDPWD` (None before any cd in the command:
    the shell's own, which the audit cannot know), its pushd stack, the last command's status, and
    whether it is primary. A world is not primary when only a `cd` the audit doubts (one
    to a directory missing at audit time, say) failing would have left the shell there."""

    cwd: Path
    oldpwd: Path | None
    stack: tuple = ()
    status: str = MAYBE
    primary: bool = True


class _Shell:
    """What one shell command reaches: paths, searches and notes, with the working directory tracked
    as the set of places the shell could be (see `_World`).

    Paths reached from a primary world are `paths` (and searches `searches`); from any other world,
    `alt_paths` and `alt_searches`, which the audit reports as suspect."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.worlds: list[_World] = [_World(workdir, None)]
        self.known = True  # False after a cd the audit could not follow
        # Directories made (mkdir) and removed (rm, rmdir) earlier in this command. Any other
        # directory counts as present if it is present at audit time.
        self.made: set[Path] = set()
        self.removed: set[Path] = set()
        # Directories this command makes somewhere: until it makes one, the audit cannot take its
        # presence at audit time as presence then (`cd new; mkdir new`).
        self.later: set[Path] = set()
        self.made_ever: set[Path] = set()
        self.doubt = False  # take every directory as missing (the first pass in `_shell`)
        self.negate: set[int] = set()  # where statements negated by a removed `!` start
        # Which shell runs the code where shells differ: "zsh", "posix" (bash, dash) or None when the
        # audit cannot tell, which keeps what either would do. `lastpipe`: bash's `shopt -s lastpipe`.
        self.dialect: str | None = None
        self.lastpipe = False
        self.vars: dict[str, str] = {}
        # Each function's body and each alias's text, as a tuple of alternatives: one, or several
        # where branches that may each have run left it defined differently (None: not defined).
        self.functions: dict[str, tuple] = {}
        self.aliases: dict[str, tuple] = {}
        self.calls = 0  # depth of function calls being followed
        self.inlined = 0  # function calls followed in all
        self.feeding = 0  # > 0 while a search's results reach another command
        self.paths: list[Path] = []
        self.alt_paths: list[Path] = []
        self.unknown_paths: list[Path] = []  # patterns for paths with parts the audit cannot work out
        # Paths found inside interpreter code, some of them fragments of URLs or patterns rather
        # than paths; they count for violations, but as paths outside the work directory only if
        # they exist.
        self.code_paths: list[Path] = []
        self.searches: list[tuple[str, str, Path]] = []
        self.alt_searches: list[tuple[str, str, Path]] = []
        self.notes: list[str] = []
        # What the last command printed, when the audit can tell (pwd, echo, cat of a here-document);
        # None when it cannot. Command substitutions and pipelines read it.
        self.output: str | None = None

    # Worlds

    @property
    def cwd(self) -> Path:
        return self.worlds[0].cwd

    @property
    def oldpwd(self) -> Path | None:
        return self.worlds[0].oldpwd

    def set_worlds(self, worlds: list[_World]) -> None:
        """Merge worlds in the same place, drop exited ones while any other remains, primary first.
        Past MAX_WORLDS the audit stops following the directory (relative paths become suspect)."""
        live = [w for w in worlds if w.status != EXITED] or [w._replace(status=MAYBE) for w in worlds]
        merged: dict = {}
        for w in live:
            key = (w.cwd, w.oldpwd, w.stack)
            m = merged.get(key)
            merged[key] = w if m is None else m._replace(
                status=m.status if m.status == w.status else MAYBE, primary=m.primary or w.primary)
        out = sorted(merged.values(), key=lambda w: not w.primary)
        if len(out) > MAX_WORLDS:
            if self.known:
                self.notes.append("more possible working directories than the audit tracks")
            self.known = False
            out = out[:MAX_WORLDS]
        self.worlds = out or [_World(self.workdir, None)]

    def set_status(self, status: str) -> None:
        self.worlds = [w._replace(status=status) for w in self.worlds]

    def either(self, *runs) -> None:
        """Run each of `runs` from the same start and keep what any of them leaves (see `join`):
        where zsh and other shells differ and the audit cannot tell which runs the code, and where
        a function or alias may or may not be defined."""
        start_worlds, start_known, start = list(self.worlds), self.known, self.state()
        worlds: list[_World] = []
        states, known = [], True
        for run in runs:
            self.worlds, self.known = list(start_worlds), start_known
            self.restore(start)
            run()
            worlds += self.worlds
            states.append(self.state())
            known = known and self.known
        self.known = known
        self.join(states)
        self.set_worlds(worlds)

    def fork(self, run, when: str, otherwise=None) -> None:
        """Run `run()` in the worlds whose last status is `when` or unknown, and `otherwise()` (if
        given) in those whose status is something else. Where the status was unknown the shell may
        have gone either way; unless some primary world certainly went the other way, the other
        way's worlds whose directory differs from every primary world that ran stop being primary
        (in `x && cd ..; cat y`, the forecaster meant the cd to run)."""
        live = [w for w in self.worlds if w.status != EXITED]
        gone = [w for w in self.worlds if w.status == EXITED]
        doing = [w for w in live if w.status in (when, MAYBE)]
        other = [w for w in live if w.status != when]
        taken: list[_World] = []
        rest: list[_World] = []
        start, states = self.state(), []
        if doing:
            self.set_worlds(doing)
            run()
            taken = self.worlds
            states.append(self.state())
        if other:
            self.restore(start)
            self.set_worlds(other)
            if otherwise is not None:
                otherwise()
            rest = self.worlds
            states.append(self.state())
        self.join(states)
        definite = [w for w in other if w.status != MAYBE]
        uncertain = len(definite) < len(other) and not any(w.primary for w in definite)
        cwds = {w.cwd for w in taken if w.primary and w.status != EXITED}
        if uncertain and cwds:
            rest = [w if w.cwd in cwds else w._replace(primary=False) for w in rest]
        self.set_worlds(taken + rest + gone)

    def state(self) -> tuple:
        return dict(self.vars), set(self.made), set(self.removed), dict(self.functions), dict(self.aliases)

    def restore(self, state: tuple) -> None:
        self.vars, self.made, self.removed = dict(state[0]), set(state[1]), set(state[2])
        self.functions, self.aliases = dict(state[3]), dict(state[4])

    def join(self, states: list[tuple]) -> None:
        """After branches that may each have run, from the same start: a variable they leave
        different has each of their values, a function or alias each of their definitions (or
        none, where one left it undefined), a directory counts as made only if each made it, and
        as removed if any removed it."""
        if not states:
            return
        merged = {}
        for name in set().union(*(st[0] for st in states)):
            values = list(dict.fromkeys(c for st in states for c in _choices(st[0].get(name, ""))))
            merged[name] = values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"
        self.vars = merged
        self.made = set.intersection(*(st[1] for st in states))
        self.removed = set.union(*(st[2] for st in states))
        for k, key in ((3, lambda b: None if b is None else _text(b)), (4, lambda a: a)):
            table = {}
            for name in set().union(*(st[k] for st in states)):
                alts = {key(a): a for st in states for a in st[k].get(name, (None,))}
                table[name] = tuple(alts.values())
            if k == 3:
                self.functions = table
            else:
                self.aliases = table

    def exists(self, p: Path, directory: bool = True) -> bool:
        if p in self.made:
            return True
        if self.doubt or p in self.later or any(_under(p, r) for r in self.removed):
            return False
        return p.is_dir() if directory else p.exists()

    @contextmanager
    def child(self):
        """A subshell: directory changes, variables, functions and aliases inside it do not outlast it."""
        saved = (list(self.worlds), self.known, dict(self.vars), dict(self.functions), dict(self.aliases),
                 self.dialect, self.lastpipe)
        try:
            yield
        finally:
            (self.worlds, self.known, self.vars, self.functions, self.aliases, self.dialect,
             self.lastpipe) = saved
            self.set_status(MAYBE)

    # Values

    def expand(self, word: str) -> str:
        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name == "HOME":
                return str(HOME)
            if name == "PWD":
                return str(self.cwd)
            if name == "OLDPWD":
                return "$OLDPWD" if self.oldpwd is None else str(self.oldpwd)
            return self.vars.get(name, "$" + name)

        return _VAR.sub(sub, word)

    def bind(self, args: list[str], zero: str | None = None) -> None:
        """Set the positional parameters ($0 to $9, $#, $@ and $*)."""
        if zero is not None:
            self.vars["0"] = zero
        for i in range(1, 10):
            self.vars[str(i)] = args[i - 1] if i <= len(args) else ""
        self.vars["#"] = str(len(args))
        self.vars["@"] = SPLIT.join(args)
        self.vars["*"] = " ".join(args)

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
            if name is not None and name.type in {"variable_name", "special_variable_name"}:
                return "\x01" + _text(name) + "\x02"
            return UNKNOWN
        if t == "expansion":
            text = _text(node)
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#])\}", text)
            if m:
                return "\x01" + m.group(1) + "\x02"
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*|[0-9]+):?[-=]([^}$`]*)\}", text)
            if m:
                return "\x01" + m.group(1) + "\x02" if self.vars.get(m.group(1)) else m.group(2)
            for c in node.named_children:
                self.value(c)  # runs any command substitution inside
            return UNKNOWN
        if t == "command_substitution":
            return self.substitute(node)
        if t == "process_substitution":
            self.feeding += 1  # what it prints reaches the command that reads it
            try:
                with self.child():
                    for c in node.named_children:
                        self.visit(c)
            finally:
                self.feeding -= 1
            return UNKNOWN
        if t == "arithmetic_expansion":
            return UNKNOWN
        if node.child_count == 0:
            return _text(node)
        if t == "concatenation":
            return "".join(self.value(c) for c in node.children)
        return "".join(self.value(c) for c in node.named_children) or _text(node)

    def substitute(self, node) -> str:
        """Run a command substitution in a subshell; its value if the audit can tell it. What a
        search inside it finds becomes words of the command around it, so it counts as fed."""
        self.output = ""
        self.feeding += 1
        try:
            with self.child():
                for c in node.named_children:
                    self.visit(c)
        finally:
            self.feeding -= 1
        out, self.output = self.output, None
        return UNKNOWN if out is None else out.rstrip("\n")

    # Paths

    def resolve(self, word: str, bare: bool) -> Path | None:
        return _resolve(self.expand(word), self.cwd, bare=bare)

    def resolve_all(self, word: str, bare: bool) -> list[tuple[Path, bool]]:
        """The word as a path from each world: (path, primary)."""
        out: dict[Path, bool] = {}
        for text in _choices(self.expand(word)):
            for w in self.worlds:
                p = _resolve(text, w.cwd, bare=bare)
                if p is not None:
                    out[p] = out.get(p, False) or w.primary
        return list(out.items())

    def reach(self, path: Path, primary: bool) -> None:
        (self.paths if primary else self.alt_paths).append(path)

    def add(self, word: str, bare: bool, chdirs: tuple = (), chdir_bare: bool = False) -> Path | None:
        """Record the word as a path from every world, and from the directories `chdirs` lead to
        from each (a command's own `-C dir`, a literal `os.chdir` in code); with `chdir_bare`, a
        plain name counts as a path from those. Returns the path from the first world."""
        text = self.expand(word)
        if CHOICE.search(text):
            found = [self.add(c, bare, chdirs, chdir_bare) for c in _choices(text)]
            return next((f for f in found if f is not None), None)
        if UNKNOWN in text:
            # A path with a part the audit cannot work out (`../$(ls ..)/x`) could be any path of
            # that shape: as a pattern, it is reported if it could reach a protected place.
            if "/" in text.replace(UNKNOWN, "") and not text.lstrip("'\"").startswith(UNKNOWN):
                pattern = re.sub(UNKNOWN + "+", "*", text)
                for w in self.worlds:
                    p = _resolve(pattern, w.cwd, bare=True)
                    if p is not None:
                        self.unknown_paths.append(p)
            return None
        plain = text.strip("'\"")
        relative = not os.path.isabs(plain) and not plain.startswith(("~", "file:"))
        first = None
        for w in self.worlds if relative else self.worlds[:1]:
            bases = [w.cwd]
            for d in chdirs:
                nb = _resolve(self.expand(d), bases[-1], bare=True)
                if nb is not None:
                    bases.append(nb)
            for k, base in enumerate(bases):
                p = _resolve(text, base, bare=bare or (chdir_bare and k > 0))
                if p is None:
                    continue
                first = first or p
                for q in _expand(p):
                    self.reach(q, w.primary or not relative)
        if first is not None and relative and not self.known:
            self.notes.append("a relative path after a cd the audit could not follow")
        return first

    def scan_code(self, code: str) -> None:
        """Path-like strings and file URLs inside interpreter code. A quoted relative path counts
        too (`Path('notes/x')`), and after a cd, so does a quoted file name (`open('draft.json')`).
        A literal directory change in the code (`os.chdir('x')`) moves the base for its relative
        paths, as far as the audit can tell in order."""
        found: list[tuple[str, bool]] = [(m.group(1), False) for m in EMBEDDED_PATH.finditer(code)
                                         if not m.group(1).startswith("//")]  # a URL's remainder
        found += [(m.group(1), False) for m in FILE_URL.finditer(code)]
        chdirs = tuple(m.group(2) for m in CODE_CHDIR.finditer(code))
        moved = self.cwd != self.workdir or bool(chdirs)
        for m in QUOTED.finditer(code):
            word = m.group(2)
            if "/" in word:
                found.append((word, False))
            elif moved and FILE_NAME.fullmatch(word):
                found.append((word, True))
        before = len(self.paths)
        for i, d in enumerate(chdirs):
            self.add(d, bare=True, chdirs=chdirs[:i])
        for word, bare in found:
            self.add(word, bare=bare, chdirs=chdirs)
        self.code_paths += self.paths[before:]

    def search(self, verb: str, kind: str, words: list[str]) -> None:
        """Record a search rooted at each word (or, with none, at the working directory), from
        every world."""
        roots = [r for word in words for r in self.resolve_all(word, bare=True)]
        roots = roots or [(w.cwd, w.primary) for w in self.worlds]
        if kind == "names" and self.feeding:
            kind = "content"
        for r, primary in roots:
            (self.searches if primary else self.alt_searches).append((verb, kind, r))

    # Statements

    def run(self, text: str) -> None:
        data, negate = _parseable(text.encode())
        tree = _BASH.parse(data)
        if tree.root_node.has_error or _reserved_commands(tree.root_node):
            self.notes.append("part of a command the audit could not parse")
        saved, self.negate = self.negate, negate
        try:
            self.visit(tree.root_node)
        finally:
            self.negate = saved

    def visit(self, node) -> None:
        if node.start_byte in self.negate and node.type not in {"program", "list"} and not (
                node.type == "redirected_statement" and _body(node).type == "list"):
            # A `!` the grammar could not take, before a compound command (see `_parseable`). In
            # `! { a; } && b >x` it negates `{ a; }`, which starts where the list does.
            self.negate = self.negate - {node.start_byte}
            self.visit(node)
            swap = {OK: FAILED, FAILED: OK}
            self.worlds = [w._replace(status=swap.get(w.status, w.status)) for w in self.worlds]
            return
        after = node.next_sibling
        if node.type in STATEMENTS and after is not None and after.type == "&":
            self.background(node)
            return
        self._visit(node)

    def background(self, node) -> None:
        """A statement before `&` runs in a subshell, and the shell goes on with status 0. zsh is the
        exception for an and-or list: it runs the list's last pipeline in the background and the
        pipelines before it in the current shell, so `cd a && make &` leaves zsh in a."""
        def whole():
            with self.child():
                self._visit(node)
            self.set_status(OK)

        body = _body(node)
        if body.type != "list" or self.dialect == "posix":
            whole()
            return
        redirects = [c for c in node.named_children if c.type in REDIRECTS] if body is not node else None

        def split():
            self.and_or(body, redirects, None, background=True)

        if self.dialect == "zsh":
            split()
        else:
            self.either(whole, split)

    def _visit(self, node) -> None:
        t = node.type
        if t == "command":
            self.simple(node)
        elif t == "redirected_statement":
            self.redirected(node)
        elif t == "pipeline":
            self.pipeline(self._stages(node))
        elif t == "list":
            self.and_or(node)
        elif t == "subshell":
            with self.child():
                for c in node.named_children:
                    self.visit(c)
        elif t == "negated_command":
            for c in node.named_children:
                self.visit(c)
            swap = {OK: FAILED, FAILED: OK}
            self.worlds = [w._replace(status=swap.get(w.status, w.status)) for w in self.worlds]
        elif t == "if_statement":
            self.branches(self.if_clauses(node))
        elif t == "while_statement":
            self.while_loop(node)
        elif t == "case_statement":
            self.case(node)
        elif t == "c_style_for_statement":
            body = node.child_by_field_name("body")
            self.set_status(MAYBE)
            if body is not None:
                self.fork(lambda: self.visit(body), OK)
        elif t == "function_definition":
            name = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if body is not None:
                if name is not None:
                    self.functions[_text(name)] = (body,)
                with self.child():  # paths in a function that is never called still count
                    self.visit(body)
            self.set_status(OK)
        elif t == "variable_assignment":
            self.assign(node)
            self.set_status(_assignment_status(node))
        elif t == "variable_assignments":
            for c in node.named_children:
                self.assign(c)
            self.set_status(_assignment_status(node))
        elif t == "declaration_command":
            for c in node.named_children:
                if c.type == "variable_assignment":
                    self.assign(c)
            self.set_status(_assignment_status(node))
        elif t == "for_statement":
            self.for_loop(node)
        elif t == "test_command":
            for c in node.named_children:
                self.test_words(c)
            pattern = _text(node).startswith("[[")
            tokens = self.test_tokens(node)[1:-1]  # without the brackets
            if not {"&&", "||", "-a", "-o", "(", ")"} & set(tokens):
                # As `test` reads its arguments: the grammar takes `[ ! a = b ]` as `(! a) = b`.
                self.set_status(self.test_args(tokens, pattern))
            else:
                exprs = node.named_children
                self.set_status(self.test_eval(exprs[0], pattern) if len(exprs) == 1 else MAYBE)
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
            self.set_status(MAYBE)  # `(( x ))` and the like leave a status the audit cannot tell
            for c in node.named_children:
                if c.type in STATEMENTS or c.type in REDIRECTS:
                    self.visit(c)
                elif c.type in {"command_substitution", "process_substitution", "string", "concatenation",
                                "expansion"}:
                    self.value(c)

    def test_status(self, word: str) -> str:
        """`[ -d x ]` and the like: true if x exists at audit time (it most likely did when the
        command ran); otherwise unknown, since it may have existed then."""
        p = self.resolve(word, bare=True)
        return OK if p is not None and self.exists(p, directory=False) else MAYBE

    def test_args(self, ops: list[str], pattern: bool = False) -> str:
        """The status of `test` (or `[`) with these arguments, when the audit can tell: string and
        integer comparisons of known values, -z and -n, and file tests (see `test_status`).
        `pattern`: in `[[ ]]`, the right side of == and = is a glob pattern."""
        if any(UNKNOWN in o or "$" in o for o in ops):
            return MAYBE
        if any(CHOICE.search(o) for o in ops):
            seen = {self.test_args(list(c), pattern) for c in itertools.islice(
                itertools.product(*map(_choices, ops)), 64)}
            return seen.pop() if len(seen) == 1 else MAYBE
        if ops[:1] == ["!"]:
            return {OK: FAILED, FAILED: OK}.get(self.test_args(ops[1:], pattern), MAYBE)
        if not ops:
            return FAILED
        if len(ops) == 1:
            return OK if ops[0] else FAILED
        if len(ops) == 2:
            op, x = ops
            if op in {"-z", "-n"}:
                return OK if (x == "") == (op == "-z") else FAILED
            return self.test_status(x) if op in {"-d", "-e", "-f"} else MAYBE
        if len(ops) == 3:
            x, op, y = ops
            if op in {"=", "=="}:
                return OK if (fnmatch.fnmatchcase(x, y) if pattern else x == y) else FAILED
            if op == "!=":
                return FAILED if (fnmatch.fnmatchcase(x, y) if pattern else x == y) else OK
            compare = {"-eq": int.__eq__, "-ne": int.__ne__, "-lt": int.__lt__, "-le": int.__le__,
                       "-gt": int.__gt__, "-ge": int.__ge__}.get(op)
            if compare is not None:
                try:
                    return OK if compare(int(x), int(y)) else FAILED
                except ValueError:
                    return MAYBE
        return MAYBE

    def test_tokens(self, node) -> list[str]:
        """A test expression's operators and operand values, in order."""
        out: list[str] = []
        for c in node.children:
            if c.type in {"unary_expression", "binary_expression", "parenthesized_expression"}:
                out += self.test_tokens(c)
            elif not c.is_named or c.type == "test_operator":
                out.append(_text(c))
            else:
                out.append(self.expand(self.value(c)))
        return out

    def test_eval(self, node, pattern: bool) -> str:
        """The status of a [ ... ] or [[ ... ]] expression, when the audit can tell."""
        t = node.type
        if t == "parenthesized_expression":
            inner = node.named_children
            return self.test_eval(inner[0], pattern) if len(inner) == 1 else MAYBE
        if t == "unary_expression":
            op = node.child_by_field_name("operator")
            rest = [c for c in node.named_children if (c.start_byte, c.end_byte) != (op.start_byte, op.end_byte)]
            if op is None or len(rest) != 1:
                return MAYBE
            if _text(op) == "!":
                return {OK: FAILED, FAILED: OK}.get(self.test_eval(rest[0], pattern), MAYBE)
            return self.test_args([_text(op), self.expand(self.value(rest[0]))], pattern)
        if t == "binary_expression":
            op, left, right = (node.child_by_field_name(f) for f in ("operator", "left", "right"))
            if op is None or left is None or right is None:
                return MAYBE
            o = _text(op)
            if o in {"&&", "-a", "||", "-o"}:
                a, b = self.test_eval(left, pattern), self.test_eval(right, pattern)
                win, lose = (FAILED, OK) if o in {"&&", "-a"} else (OK, FAILED)
                return win if win in (a, b) else lose if a == b == lose else MAYBE
            return self.test_args([self.expand(self.value(left)), o, self.expand(self.value(right))], pattern)
        return self.test_args([self.expand(self.value(node))], pattern)

    def and_or(self, node, redirects: list | None = None, stdin: str | None = None, background: bool = False) -> None:
        """`a && b` runs b only where a succeeded, and `a || b` only where it failed (see `fork`).
        Redirections written after the list belong to its last command. `background`: the list ends
        with `&` in zsh, which runs only its last pipeline in the background (see `background`)."""
        items: list[tuple[str | None, object]] = []
        op = None
        for c in node.children:
            if not c.is_named:
                op = _text(c)
            elif c.type in STATEMENTS:
                items.append((op, c))
                op = None
        for k, (op, c) in enumerate(items):
            last = k == len(items) - 1

            def step(c=c, last=last):
                with self.child() if last and background else nullcontext():
                    if last and redirects:
                        self.with_redirects(c, redirects, stdin)
                    else:
                        self.visit(c)
                if last and background:
                    self.set_status(OK)

            if op == "&&":
                self.fork(step, OK)
            elif op == "||":
                self.fork(step, FAILED)
            else:
                step()

    @staticmethod
    def if_clauses(node) -> list:
        """[(condition statements, body statements)], with None as the condition of an else."""
        clauses: list = []

        def split(n):
            cond, body, part = [], [], "cond"
            for c in n.children:
                if not c.is_named:
                    if _text(c) == "then":
                        part = "body"
                    continue
                if c.type in {"elif_clause", "else_clause"}:
                    continue
                if c.type in STATEMENTS:
                    (cond if part == "cond" else body).append(c)
            return cond, body

        clauses.append(split(node))
        for c in node.named_children:
            if c.type == "elif_clause":
                clauses.append(split(c))
            elif c.type == "else_clause":
                clauses.append((None, [s for s in c.named_children if s.type in STATEMENTS]))
        return clauses

    def branches(self, clauses: list) -> None:
        if not clauses:
            return
        cond, body = clauses[0]
        if cond is None:
            for s in body:
                self.visit(s)
            return
        self.set_status(MAYBE)
        for s in cond:
            self.visit(s)
        rest = clauses[1:]
        # With no branch taken, an if statement's status is 0.
        self.fork(lambda: [self.visit(s) for s in body], OK,
                  (lambda: self.branches(rest)) if rest else (lambda: self.set_status(OK)))

    def while_loop(self, node, stdin: str | None = None) -> None:
        until = any(not c.is_named and _text(c) == "until" for c in node.children)
        body = node.child_by_field_name("body")
        conds = [c for i, c in enumerate(node.children)
                 if node.field_name_for_child(i) == "condition" and c.type in STATEMENTS]
        if (not until and body is not None and stdin is not None and len(conds) == 1 and conds[0].type == "command"
                and self._command_name(conds[0]) == "read"):
            # `while read x; do ...; done` on input the audit knows: one pass per line, in order.
            names = _read_names([self.expand(self.value(c)) for c in conds[0].children_by_field_name("argument")])
            for line in stdin.splitlines()[:20]:
                self.bind_read(names, line)
                self.visit(body)
            self.bind_read(names, "")
            self.set_status(OK)
            return
        self.set_status(MAYBE)
        for c in conds:
            self.visit(c)
        if body is not None:
            # The body runs zero or more times; one pass stands for all of them.
            self.fork(lambda: self.visit(body), FAILED if until else OK)
        self.set_status(MAYBE)

    def bind_read(self, names: list[str], line: str | None) -> None:
        """What `read NAME...` sets from one line (None: a line the audit does not know)."""
        fields = line.split(None, len(names) - 1) if line is not None else []
        for k, name in enumerate(names):
            self.vars[name] = UNKNOWN if line is None else fields[k] if k < len(fields) else ""

    def case(self, node) -> None:
        """With a known value and patterns, run the first item that matches; otherwise run each."""
        value = node.child_by_field_name("value")
        word = self.expand(self.value(value)) if value is not None else UNKNOWN
        items = [c for c in node.named_children if c.type == "case_item"]
        patterns = [[self.expand(self.value(p)) for p in item.children_by_field_name("value")] for item in items]
        if not any(c in x for x in [word, *sum(patterns, [])] for c in "$\x06" + UNKNOWN + SPLIT):
            match = next((item for item, pats in zip(items, patterns)
                          if any(fnmatch.fnmatchcase(word, p) for p in pats)), None)
            self.set_status(OK)
            for s in match.named_children if match is not None else []:
                if s.type in STATEMENTS:
                    self.visit(s)
            return
        before, start = self.worlds, self.state()
        results: list[list[_World]] = []
        states = [start]  # no pattern matches
        for item in items:
            self.restore(start)
            self.set_worlds(before)
            for s in item.named_children:
                if s.type in STATEMENTS:
                    self.visit(s)
            results.append(self.worlds)
            states.append(self.state())
        results.append(before)  # no pattern matches
        self.join(states)
        # Which item matches is unknown: the first counts as taken, the others as alternatives.
        cwds = {w.cwd for w in results[0] if w.primary}
        rest = [w if w.cwd in cwds else w._replace(primary=False) for r in results[1:] for w in r]
        self.set_worlds(results[0] + rest)
        self.set_status(MAYBE)

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
        items = [x for item in items for x in item.split(SPLIT)]
        for item in items:
            self.add(item, bare=False)
        body = node.child_by_field_name("body")
        if body is None:
            return
        values: list[str] = []
        for item in items:
            p = self.resolve(item, bare=True) if any(c in item for c in "*?[") else None
            values += [str(x) for x in _expand(p)] if p is not None else [item]
        literal = bool(items) and not any(any(c in x for c in "*?[$\x06" + UNKNOWN) for x in items)

        def passes():
            for item in values[:20] or [None]:
                if var is not None and item is not None:
                    self.vars[_text(var)] = item
                self.visit(body)

        if literal:
            passes()  # a literal list: the body runs once per item, in order
        else:
            self.set_status(MAYBE)
            self.fork(passes, OK)  # the list may be empty
        self.set_status(MAYBE)

    def assign(self, node) -> None:
        name = node.child_by_field_name("name")
        val = node.child_by_field_name("value")
        if name is None:
            return
        value = self.expand(self.value(val)).replace(SPLIT, " ") if val is not None else ""
        self.vars[_text(name)] = value
        self.add(value, bare=False)

    def pipeline(self, stages: list, data: str | None = None, tail: list | None = None) -> None:
        """Each stage runs in a subshell, fed what the stage before it printed (when known), except
        that zsh runs the last stage in the current shell, as bash does after `shopt -s lastpipe`:
        `x | cd d`, `x | read y` and `x | while read d; do cd "$d"; done` change zsh's shell. Where
        the audit cannot tell which shell runs the code and the last stage could change the shell
        (see `_keeps_shell`), it keeps both outcomes. `tail`: redirections written after the
        pipeline, which belong to its last stage. A search whose results reach a later stage that
        reads names (xargs, a shell, a `while read` loop) is fed."""
        if not stages:
            self.set_status(MAYBE)
            return
        here = {"zsh": [True], "posix": [False, True] if self.lastpipe else [False]}.get(self.dialect, [False, True])
        ways = [False] if self._keeps_shell(stages[-1]) else here
        if len(ways) == 1:
            self._pipeline(stages, data, tail, ways[0])
        else:
            self.either(*(lambda h=h: self._pipeline(stages, data, tail, h) for h in ways))

    def _pipeline(self, stages: list, data: str | None, tail: list | None, here: bool) -> None:
        """`pipeline` with the last stage run in the current shell if `here`."""
        readers = [self._reads_names(s) for s in stages]
        for i, stage in enumerate(stages):
            last = i == len(stages) - 1
            self.output = None
            fed = any(readers[i + 1:])
            self.feeding += fed
            try:
                with nullcontext() if last and here else self.child():
                    if tail and last:
                        self.with_redirects(stage, tail, data)
                    else:
                        self.statement(stage, data)
            finally:
                self.feeding -= fed
            data = self.output
        self.set_status(MAYBE)

    def _keeps_shell(self, node) -> bool:
        """Whether a pipeline stage leaves the shell as it was wherever it runs: a simple command,
        named literally, that is not a function, an alias or one of STATEFUL."""
        node = _body(node)
        name = node.child_by_field_name("name") if node.type == "command" else None
        if name is None:
            return False
        word = os.path.basename(re.sub(r"[\"'\\]", "", _text(name)))
        return (re.fullmatch(r"[\w.+-]+", word) is not None and word not in STATEFUL
                and word not in self.functions and word not in self.aliases)

    @classmethod
    def _stages(cls, node) -> list:
        """A pipeline's stages. After a here-document the grammar nests the rest of the pipeline
        (`cat <<EOF | tee x | sh`) as one more pipeline."""
        out = []
        for c in node.named_children:
            if c.type == "pipeline":
                out += cls._stages(c)
            elif c.type in STATEMENTS:
                out.append(c)
        return out

    @staticmethod
    def _command_name(node) -> str | None:
        if node.type == "redirected_statement":
            node = node.child_by_field_name("body") or node
        name = node.child_by_field_name("name") if node.type == "command" else None
        return os.path.basename(_text(name)) if name is not None else None

    @classmethod
    def _reads_names(cls, node) -> bool:
        inner = node.child_by_field_name("body") if node.type == "redirected_statement" else node
        if inner is not None and inner.type == "while_statement":
            return True
        return cls._command_name(node) in NAME_READERS

    def statement(self, node, stdin: str | None) -> None:
        if node.type == "command":
            self.simple(node, stdin=stdin)
        elif node.type == "redirected_statement":
            self.redirected(node, stdin)
        elif node.type == "while_statement":
            self.while_loop(node, stdin)
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
            self.and_or(body, redirects, stdin)
        elif body.type == "pipeline":
            self.pipeline(self._stages(body), tail=redirects)
        elif body.type == "while_statement":
            data, after = self.redirect(redirects, stdin)
            self.while_loop(body, data)
            for stmt in after:
                self.visit(stmt)
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
        # Words expand before the command's own assignments take effect, as in the shell; "$@"
        # becomes one word per parameter.
        words = [x for w in words for x in self.expand(w).split(SPLIT)]
        stdin, after = self.redirect(redirs, stdin)
        if not words:
            for a in assigns:
                self.assign(a)
            self.set_status(_assignment_status(node))
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
                self.pipeline(self._stages(stmt), data)
            else:
                self.visit(stmt)

    # Commands

    def cd_candidates(self, target: str, cwd: Path) -> list[Path]:
        """Where `cd target` may go from cwd, in the order the shell tries them: each CDPATH entry
        first (for a relative target not starting with . or ..), then cwd itself."""
        out = []
        cdpath = self.vars.get("CDPATH")
        if cdpath and not target.startswith(("/", "~", "./", "../")) and target not in {".", ".."}:
            for entry in cdpath.split(":"):
                base = cwd if entry in {"", "."} else _resolve(entry, cwd, bare=True)
                p = _resolve(target, base, bare=True) if base is not None else None
                if p is not None:
                    out.append(p)
        p = _resolve(target, cwd, bare=True)
        return [*dict.fromkeys(out + ([p] if p is not None else [cwd]))]

    def chdir(self, target: str | None) -> None:
        """cd in every world. A target missing at audit time forks the world: the cd may have
        worked (it was there then) or failed, leaving the shell where it was (not primary)."""
        if target is not None and ("$" in target or UNKNOWN in target):
            self.known = False
            self.notes.append(f"cd to {target.replace(UNKNOWN, '<unknown>')}, which the audit cannot expand")
            self.set_status(MAYBE)
            return
        out = []
        for w in self.worlds:
            # A target with several possible values goes to each of them.
            for t in [None] if target is None else _choices(target):
                cands = [HOME] if t is None else self.cd_candidates(t, w.cwd)
                for c in cands:
                    self.reach(c, w.primary)
                there = [c for c in cands if self.exists(c)]
                if there:
                    out.append(_World(there[0], w.cwd, w.stack, OK, w.primary))
                else:
                    out.append(_World(cands[-1], w.cwd, w.stack, OK, w.primary))
                    out.append(w._replace(status=FAILED, primary=False))
        self.set_worlds(out)

    def shadowed(self, kind: str, name: str, alt, words: list[str], stdin: str | None) -> None:
        """Run a command with one alternative definition (None: none) of a function or alias
        (`kind`: "functions" or "aliases")."""
        saved, shadow = getattr(self, kind).pop(name), (alt,)
        if alt is not None:
            getattr(self, kind)[name] = shadow
        try:
            self.command(words, stdin)
        finally:
            table = getattr(self, kind)
            if table.get(name, shadow) is shadow:  # unless the command defined it anew
                table[name] = saved

    def command(self, words: list[str], stdin: str | None = None) -> None:
        if not words:
            return
        self.set_status(MAYBE)
        verb_word, args = words[0], words[1:]
        if "/" in verb_word and not verb_word.startswith(SYSTEM_BIN):
            self.add(verb_word, bare=True)  # running a file by path reads it
        verb = os.path.basename(verb_word)
        if verb not in SILENT:
            self.output = None
        for kind in ("aliases", "functions"):
            alts = getattr(self, kind).get(verb, ())
            if len(alts) > 1:
                # Defined in only some of the branches that may have run, or differently there.
                self.either(*(lambda a=a: self.shadowed(kind, verb, a, words, stdin) for a in alts))
                return
        if verb in self.aliases and self.calls < 4 and self.inlined < 256:
            # zsh expands aliases in scripts (bash only when told to); follow them either way.
            self.calls += 1
            self.inlined += 1
            try:
                self.run(" ".join([self.aliases[verb][0], *map(shlex.quote, args)]))
            finally:
                self.calls -= 1
            return
        if verb in self.functions and self.calls < 4 and self.inlined < 256:
            # A function runs in the calling shell, with its own positional parameters.
            for a in args:
                self.add(a, bare=False)
            saved = {k: self.vars.get(k) for k in POSITIONAL}
            self.bind(args)
            self.calls += 1
            self.inlined += 1
            try:
                self.visit(self.functions[verb][0])
            finally:
                self.calls -= 1
                for k, old in saved.items():
                    if old is None:
                        self.vars.pop(k, None)
                    else:
                        self.vars[k] = old
            self.set_status(MAYBE)
            return
        if verb in SUCCEEDS or (verb == "mkdir" and any(re.fullmatch(r"-[a-zA-Z]*p[a-zA-Z]*", a) for a in args)):
            self.set_status(OK)
        if verb in {"true", ":"}:
            return
        if verb == "shopt":
            if "lastpipe" in args and {"-s", "-u"} & set(args):
                self.lastpipe = "-s" in args
            return
        if verb == "false":
            self.set_status(FAILED)
            return
        if verb == "exit":
            self.set_status(EXITED)
            return
        if verb in {"test", "["}:
            for a in args:
                if a not in {"]", "!"} and not re.fullmatch(r"-[a-zA-Z]+", a):
                    self.add(a, bare=self.cwd != self.workdir)
            self.set_status(self.test_args(args[:-1] if verb == "[" and args[-1:] == ["]"] else args))
            return
        if verb == "read":
            lines = stdin.splitlines() if stdin is not None else None
            self.bind_read(_read_names(args), None if lines is None else lines[0] if lines else "")
            self.set_status(MAYBE if lines is None else OK if lines else FAILED)
            return
        if verb == "alias":
            for a in args:
                m = re.match(r"^([^=\s]+)=(.*)$", a, re.S)
                if m:
                    self.aliases[m.group(1)] = (m.group(2),)
            self.set_status(OK)
            return
        if verb in {"export", "declare", "typeset", "local", "readonly"}:
            for a in args:
                if ASSIGN.match(a):
                    name, value = ASSIGN.match(a).groups()
                    self.vars[name] = value
                    self.add(value, bare=False)
            return
        if verb in SHELLS:
            self.shell_command(verb, args, stdin)
            return
        if verb == "eval":
            self.run(" ".join(args))
            return
        if verb in {"source", "."}:
            if args:
                self.add(args[0], bare=True)
            return
        if verb in WRAPPERS:
            self.wrapper(verb, args, stdin)
            return
        if verb == "mkdir":
            for a in args:
                if not a.startswith("-"):
                    for p, _ in self.resolve_all(a, bare=True):
                        self.made.update([p, *p.parents])
                        self.made_ever.add(p)
                        self.removed -= {p, *p.parents}
        if verb in {"rm", "rmdir"}:
            for a in args:
                if not a.startswith("-"):
                    for p, _ in self.resolve_all(a, bare=True):
                        for q in _expand(p):
                            self.removed.add(q)
                            self.made = {m for m in self.made if not _under(m, q)}
        if verb in {"cd", "pushd", "chdir"}:
            operands = [a for a in args if not (a.startswith("-") and a != "-")]
            if verb == "pushd":
                self.worlds = [w._replace(stack=(*w.stack, w.cwd)) for w in self.worlds]
            if operands and operands[0] == "-":
                if any(w.oldpwd is None for w in self.worlds):
                    # Back to where the shell was before this command (bash 3.2 has no $OLDPWD then).
                    self.chdir("$OLDPWD")
                    return
                self.set_worlds([_World(w.oldpwd, w.cwd, w.stack, OK, w.primary) for w in self.worlds])
                for w in self.worlds:
                    self.reach(w.cwd, w.primary)
            else:
                self.chdir(operands[0] if operands else None)
            return
        if verb == "popd":
            self.set_worlds([_World(w.stack[-1], w.cwd, w.stack[:-1], OK, w.primary) if w.stack
                             else w._replace(status=FAILED) for w in self.worlds])
            return
        places = {w.cwd for w in self.worlds}
        if verb == "pwd":
            self.output = str(self.cwd) if self.known and len(places) == 1 else None
            return
        operands = [a for a in args if not a.startswith("-")]
        if verb in {"realpath", "grealpath"} or (verb in {"readlink", "greadlink"} and any(
                re.fullmatch(r"-[a-zA-Z]*[fem][a-zA-Z]*", a) for a in args)):
            p = self.add(operands[0], bare=True) if operands else None
            relative = bool(operands) and not os.path.isabs(operands[0])
            self.output = str(p) if p is not None and self.known and (len(places) == 1 or not relative) else None
            return
        if verb in {"dirname", "basename"} and operands:
            self.output = (os.path.dirname if verb == "dirname" else os.path.basename)(operands[0])
            return
        if verb == "echo":
            self.output = " ".join(a for a in args if a not in {"-n", "-e", "-E"})
        elif verb == "printf" and args and args[0] in {"%s", "%s\n", "%s\\n"}:
            self.output = " ".join(args[1:])
        elif verb == "tee" or (verb == "cat" and not operands):
            self.output = stdin  # tee passes its input through, whatever files it also writes

        bare = self.cwd != self.workdir
        skip: set[int] = set()
        chdirs: list[str] = []
        code: list[str] = []
        if verb in SEARCH_SYNTAX:
            parsed = _search_args(verb, args)
            skip |= parsed["values"]
            for f in parsed["files"]:
                if not f.startswith(SYSTEM_BIN):  # --pre and --hostname-bin name programs
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
                names = (verb in {"fd", "fdfind"} or parsed["names"]) and not parsed["exec"]
                self.search(verb, "names" if names else "content",
                            [args[k] for k in positional] + list(parsed["roots"]))
        elif verb == "find":
            j = 0
            while j < len(args) and args[j] in {"-H", "-L", "-P"}:
                j += 1
            start = j
            while j < len(args) and not (args[j].startswith("-") or args[j] in {"(", "!", ","}):
                j += 1
            for k in range(j, len(args)):
                if args[k] in FIND_VALUE_TESTS and k + 1 < len(args):
                    skip.add(k + 1)
            runs = any(a in {"-exec", "-execdir", "-ok", "-okdir"} for a in args[j:])
            self.search(verb, "content" if runs else "names", args[start:j])
        elif verb in {"tree", "du"} or (verb == "ls" and any(re.match(r"-[a-zA-Z]*R", a) for a in args)):
            self.search(verb, "names", operands)
        elif verb == "ls":
            listed = [p for a in operands for p, _ in self.resolve_all(a, bare=True)] or list(places)
            if any(_at_or_above_home(r) for r in listed):
                self.notes.append("lists the home directory or above")
        if verb in DISK_SEARCH:
            self.searches.append((verb, "disk", Path("/")))
        if verb in DIR_OPTIONS:
            for j, a in enumerate(args):
                name, eq, val = a.partition("=")
                if a in DIR_OPTIONS[verb] and j + 1 < len(args):
                    chdirs.append(args[j + 1])
                elif eq and name in DIR_OPTIONS[verb]:
                    chdirs.append(val)

        syntax = CODE_SYNTAX.get(verb) or (CODE_SYNTAX["python"] if re.match(r"python\d", verb) else None)
        if syntax is not None:
            skip |= self.code_args(syntax, args, code)
        for j, a in enumerate(args):
            if j in skip:
                continue
            if a.startswith("-") and a != "-":
                if "=" in a and verb not in SEARCH_SYNTAX:  # a search tool's option values have their roles
                    self.add(a.split("=", 1)[1], bare=False, chdirs=tuple(chdirs))
                continue
            self.add(a, bare=bare, chdirs=tuple(chdirs), chdir_bare=verb in DIR_BARE)
            if any(c in a for c in "'\"()"):
                self.scan_code(a)
        for c in code:
            self.scan_code(c)
        if syntax is not None and stdin:
            self.scan_code(stdin)  # code (or data the code reads) on standard input

    def code_args(self, syntax: dict, args: list[str], code: list[str]) -> set[int]:
        """Read an interpreter's arguments: append its code to `code`, record files it reads, and
        return the indices handled here (code, and option values that are neither code nor paths)."""
        handled: set[int] = set()
        letters = {o[1] for o in syntax.get("code", ()) if len(o) == 2}
        given = False
        j = 0
        while j < len(args):
            a = args[j]
            if a == "--":
                j += 1
                break
            if not a.startswith("-") or a == "-":
                break
            name, eq, val = a.partition("=")
            if a in syntax.get("code", ()) or (len(a) > 2 and not a.startswith("--") and a[-1] in letters
                                                and a not in syntax.get("values", {})):
                if j + 1 < len(args):
                    code.append(args[j + 1])
                    handled |= {j, j + 1}
                    given = True
                j += 2
                continue
            if eq and name in syntax.get("code", ()):
                code.append(val)
                handled.add(j)
                given = True
                j += 1
                continue
            if a in syntax.get("files", {}):
                n = syntax["files"][a]
                for k in range(j + 1, min(j + 1 + n, len(args))):
                    handled.add(k)
                if j + n < len(args):
                    self.add(args[j + n], bare=True)
                handled.add(j)
                given = given or a in {"-f", "--file", "--from-file"}
                j += 1 + n
                continue
            if a in syntax.get("values", {}):
                n = syntax["values"][a]
                handled |= set(range(j, min(j + 1 + n, len(args))))
                j += 1 + n
                continue
            if a in syntax.get("empty_value", ()) and j + 1 < len(args) and args[j + 1] == "":
                handled |= {j, j + 1}  # BSD `sed -i ''`
                j += 2
                continue
            j += 1
        if syntax.get("first") and not given and j < len(args):
            code.append(args[j])
            handled.add(j)
        return handled

    def shell_command(self, verb: str, args: list[str], stdin: str | None) -> None:
        """sh, bash and the like: `-c CODE [NAME [ARGS]]`, `-s [ARGS]` or no script (code on standard
        input), or a script file. The arguments are positional parameters, and paths too. The code
        runs as that shell runs code (see DIALECTS)."""
        j, flags = 0, ""
        while j < len(args) and args[j].startswith(("-", "+")) and args[j] not in {"-", "--"}:
            if args[j] in {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}:
                j += 2
                continue
            if not args[j].startswith("--"):
                flags += args[j][1:]
            j += 1
        if j < len(args) and args[j] in {"-", "--"}:
            j += 1
        operands = args[j:]
        if "c" in flags and operands:
            code, rest = operands[0], operands[1:]
            for a in rest:
                self.add(a, bare=False)
            with self.child():
                self.dialect, self.lastpipe = DIALECTS.get(verb), False
                self.bind(rest[1:], zero=rest[0] if rest else None)
                self.run(code)
            return
        if "s" in flags or not operands:
            for a in operands:
                self.add(a, bare=False)
            if stdin:
                with self.child():
                    self.dialect, self.lastpipe = DIALECTS.get(verb), False
                    self.bind(operands)
                    self.run(stdin)  # shell code on standard input
            return
        self.add(operands[0], bare=True)  # a script file
        for a in operands[1:]:
            self.add(a, bare=False)

    def wrapper(self, verb: str, args: list[str], stdin: str | None) -> None:
        """A command that runs another: skip its own options (with their values) to the command.
        `env -C dir`, `env -S string`, `sudo -D dir` and env's NAME=VALUE are followed."""
        rest = list(args)
        values = WRAPPER_VALUES.get(verb, set())
        chdir_opts = WRAPPER_CHDIR.get(verb, set())
        chdir, split, env = None, None, {}
        while rest:
            a = rest[0]
            name, eq, val = a.partition("=")
            if a == "--":
                rest = rest[1:]
                break
            if eq and name.startswith("--"):
                if name in chdir_opts:
                    chdir = val
                elif verb == "env" and name == "--split-string":
                    split = val
                elif name in WRAPPER_FILES.get(verb, ()):
                    self.add(val, bare=True)
                rest = rest[1:]
                continue
            if a in values and len(rest) > 1:
                if a in chdir_opts:
                    chdir = rest[1]
                elif verb == "env" and a in {"-S", "--split-string"}:
                    split = rest[1]
                elif a in WRAPPER_FILES.get(verb, ()):
                    self.add(rest[1], bare=True)
                rest = rest[2:]
                continue
            if verb == "env" and ASSIGN.match(a):
                k, v = ASSIGN.match(a).groups()
                env[k] = v
                self.add(v, bare=False)
                rest = rest[1:]
                continue
            if a.startswith("-") or ASSIGN.match(a) or a == "{}" or (
                    verb in {"timeout", "nice"} and re.fullmatch(r"[\d.]+[smhd]?", a)):
                rest = rest[1:]
                continue
            break
        if split is not None:
            try:
                rest = shlex.split(split) + rest
            except ValueError:
                rest = split.split() + rest
        if verb == "xargs" and stdin:
            try:
                items = shlex.split(stdin)
            except ValueError:
                items = stdin.split()
            for item in items:
                self.add(item, bare=True)  # xargs passes these to the command as arguments
        if verb in {"env", "sudo"} and (chdir is not None or env):
            # The command runs in its own process: the directory change does not outlast it.
            with self.child():
                self.vars.update(env)
                if chdir is not None:
                    self.chdir(chdir)
                if rest:
                    self.command(rest, stdin)
            return
        if rest:
            self.command(rest, None if verb == "xargs" else stdin)


def _shell(command: str, workdir: Path) -> _Shell:
    """Read the command twice: the first pass, taking every cd as one that may have failed, finds
    the directories the command makes wherever it may be (see `_Shell.later`)."""
    first = _Shell(workdir)
    first.doubt = True
    first.run(command)
    shell = _Shell(workdir)
    shell.later = first.made_ever
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
    paths, searches, notes, weak, alt, alt_searches, unknown = [], [], [], [], [], [], []
    if tool in {"shell", "Bash"}:
        shell = _shell(inp.get("command", ""), workdir)
        paths, searches, notes, weak = shell.paths, shell.searches, shell.notes, shell.code_paths
        # Paths and searches from where the shell would be had a cd to a missing directory failed.
        alt, alt_searches = shell.alt_paths, shell.alt_searches
        unknown = shell.unknown_paths
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
    for p in unknown:
        if any(_under(p, r) or _pattern_hits(p, r) for r in roots) or _reaches_sibling(p, workdir):
            notes = [*notes, f"may reach {p}, a path with a part the audit cannot work out"]
            break
    for verb, _, r in alt_searches:
        if _at_or_above_home(r) or _covers_protected(r, roots):
            notes = [*notes, f"{verb} rooted at {r} if a cd to a directory missing at audit time failed"]
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
    # `/` alone is more often a pattern or a replacement (`rg --replace /`) than a path.
    outside = [p for p in paths if not _under(p, workdir) and p != Path("/")
               and (id(p) not in weak_ids or p.exists())]
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
