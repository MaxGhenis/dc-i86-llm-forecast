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

- `cd`, `pushd` and `popd` move every place, and the directory stack is kept as each shell keeps
  it (`pushd +N` and `popd -N` rotate or drop entries, `dirs -c` clears it, zsh's `cd +N` takes an
  entry, bash's `pushd -n` adds one without moving). A `cd` to a directory missing at audit time
  (often a scratch directory since deleted), or one the same command makes only later or removed
  earlier, may have worked or failed: the shell is then in either place, and the failed one is an
  alternative. A `cd` to a file fails. `CDPATH` is followed, `cd -` and `pushd -` go to `$OLDPWD`,
  and one before any `cd` in the command goes where the audit cannot follow.
- `&&`, `||`, `if`, `case` and loops run their parts only where the status allows. The audit knows
  the status of `true`, `false`, `:`, `cd`, `!`, tests of known strings and numbers (`[ a = b ]`,
  `[[ ... ]]`, `test`), file tests of things present at audit time, arithmetic (`(( ))`, `let`),
  literal `case` values, and commands that all but always succeed (`echo`, `mkdir -p`,
  assignments); after anything else, both ways may have run. Where the way was unknown, places
  reached only by the way not meant (the skipped side of `x && cd ..`) are alternatives too.
- A `for` loop over a list runs its body once per item and one over a glob once per match at audit
  time; `while`, `until` and C-style `for` loops run pass by pass while their condition allows.
  `break`, `continue` and `return`, with counts, leave the loops and functions they name. Passes
  are followed until the loop ends or repeats a state; after 12, variables still changing become
  unknown, and after 24 the audit stops following the directory.
- Arithmetic (`$(( ))`, `(( ))`, `let`, `declare -i`, C-style `for`) is evaluated where bash and zsh
  agree: they bind the shifts and bitwise operators differently, read a variable operand at
  different times (`a + (a = 2)`), and bash 3.2 also checks a skipped branch for division by zero;
  elsewhere the value is unknown.
- Words split into fields as each shell splits them: bash and sh split unquoted parameter and
  arithmetic expansions and command substitutions at `IFS`, zsh only command substitutions; both
  drop unquoted expansions that leave nothing (`cd $empty` goes home). `read` splits its line at
  `IFS` (bash drops a trailing delimiter that zsh keeps), and bash 3.2 (macOS's /bin/bash) splits an
  unquoted here-string too, joining the fields with spaces. Where the shell is not named and the
  two differ, the command runs each way, or the input is unknown.
- Subshells, command substitutions, pipeline stages, background jobs, `sh -c` and wrapped commands
  with their own directory (`env -C`, `sudo -D`) leave the places after them unchanged, with two
  exceptions in zsh: it runs a pipeline's last stage in the current shell (`x | cd d`,
  `x | while read d; do cd "$d"; done`), as bash does after `shopt -s lastpipe`, and of an and-or
  list ending in `&` it runs only the last pipeline in the background (`cd a && make &` leaves zsh
  in a). The audit follows the shell a command names (`zsh -c`, `bash -c`); where none is named,
  or it is `sh`, it keeps the places either way would leave.
- Functions run in the calling shell with their arguments as positional parameters and their
  `local` variables; aliases are followed. Variables, `read` from a known input (`while read` loops
  line by line), `set --`, `shift`, `unset`, and positional parameters for `sh -c CODE NAME ARGS`,
  `sh -s ARGS` and shell code on standard input are expanded, and `$PWD` is the directory of each
  place. A new shell (`sh -c`, a script) starts with the exported variables only (`export`,
  `export -n`, `set -a`, a command's own assignments, `env -i` and `env -u` all count) and bash's
  exported functions. A variable that branches may each have set differently has each of their
  values, and a function or alias they may each have defined differently, or not at all, runs as each.
- A script run by path, by a shell (`bash s.sh`, `. s.sh`) or by an interpreter is read as the
  code it holds: the text an earlier tool call wrote there (Write, Edit, a here-document, `tee`, a
  redirection), else the file at audit time if it is in the work directory or a temporary directory.
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
  directory change in it (`os.chdir('x')`) moves the base for the paths after it; options are read
  with each interpreter's own syntax (clusters such as `-uc'...'`, attached values such as
  `perl -i.bak`), an awk `-v` value is data unless the program reads files, and jq's `--args` are
  strings;
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
  a web call (a search, or a Codex web_search that opens a page) that reaches this project's own
  repository (public, but without answers until every run has finished), and sub-agent calls whose
  contents the transcript does not show.
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
# Short options cluster (`-uc`, `-ne`) and take a value attached (`-c'...'`, `-F:`, `-vx=1`), except
# where `next_only` (node: `-pe CODE`); `attached`: options whose value can only be attached and may
# be empty (perl `-i.bak`); `digits`: those whose attached value is digits only (perl `-l`, `-0`);
# `anywhere`: options may follow operands (jq). With no code option,
# the first operand of an interpreter without `first` is a script file it runs.
_PYTHON = {"code": {"-c"}, "values": {"-m": 1, "-W": 1, "-X": 1}}
_AWK = {"code": {"-e", "--source"}, "values": {"-F": 1, "-v": 1, "--assign": 1, "--field-separator": 1},
        "files": {"-f": 1, "--file": 1}, "first": True}
CODE_SYNTAX = {
    "python": _PYTHON, "python3": _PYTHON,
    **dict.fromkeys(["node", "nodejs"], {"code": {"-e", "--eval", "-p", "--print"},
                                         "files": {"-r": 1, "--require": 1, "--import": 1}, "next_only": True}),
    "perl": {"code": {"-e", "-E"}, "values": {"-I": 1, "-M": 1, "-m": 1}, "attached": {"-i", "-x", "-d"},
             "digits": {"-l", "-0"}},
    "ruby": {"code": {"-e"}, "values": {"-I": 1, "-r": 1}, "attached": {"-i", "-x", "-K"},
             "digits": {"-0", "-W", "-T"}},
    "php": {"code": {"-r"}, "values": {"-d": 1}},
    "Rscript": {"code": {"-e"}},
    "osascript": {"code": {"-e"}, "values": {"-l": 1}},
    **dict.fromkeys(["awk", "gawk", "mawk", "nawk"], _AWK),
    "jq": {"values": {"--arg": 2, "--argjson": 2, "--indent": 1},
           "files": {"-f": 1, "--from-file": 1, "--slurpfile": 2, "--rawfile": 2, "-L": 1}, "first": True,
           "anywhere": True},
    **dict.fromkeys(["sed", "gsed"], {"code": {"-e", "--expression"}, "values": {"-l": 1},
                                      "files": {"-f": 1, "--file": 1}, "first": True, "empty_value": {"-i"},
                                      "attached": {"-i"}}),
}
# Options whose file is the program itself (awk -f, sed -f, jq -f): its text is code.
PROGRAM_FILES = {"-f", "--file", "--from-file"}
# awk code that reads files or runs commands named by its variables: then `-v name=value` values may
# be paths; otherwise they are data.
AWK_READS = re.compile(r"getline|system\s*\(|close\s*\(|\|\s*getline|print[^;}]*[>|]")
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
# Variables a shell may have from its environment, and so exports, unless the command says otherwise.
INHERITED = {"HOME", "PATH", "PWD", "OLDPWD", "CDPATH", "TMPDIR", "USER", "LOGNAME", "SHELL", "LANG", "TERM"}
# Variables whose value the audit never knows, in arithmetic or elsewhere.
VOLATILE = {"RANDOM", "SRANDOM", "SECONDS", "EPOCHSECONDS", "EPOCHREALTIME", "LINENO", "BASHPID", "PPID", "UID",
            "EUID", "SHLVL", "COLUMNS", "LINES", "OPTIND", "OPTARG", "HISTCMD", "REPLY"}
# Marks a choice's alternative (see CHOICE) seen only from an alternative place: `$PWD` there.
ALT = "\x04"
# Marks inside a word's value until it is split into fields (see `_fields`): quoted text
# (\x11...\x12), an unquoted parameter or arithmetic expansion (\x0e...\x0f) and an unquoted
# command substitution (\x10...\x0f). `_Shell.value` leaves them out unless asked for them.
Q_OPEN, Q_CLOSE, FIELD, FIELD_CMD, FIELD_END = "\x11", "\x12", "\x0e", "\x10", "\x0f"
_UNMARK = str.maketrans("", "", Q_OPEN + Q_CLOSE + FIELD + FIELD_CMD + FIELD_END)
# Directories where a script a command runs may be read at audit time, besides the work directory.
TEMP_DIRS = (Path("/tmp"), Path("/private/tmp"), Path("/var/folders"), Path("/private/var/folders"))
# A command's exit status as far as the audit can tell, in each place the shell could be.
OK, FAILED, MAYBE, EXITED = "ok", "failed", "maybe", "exited"
MAX_WORLDS = 64
# test's unary operators in bash and zsh.
_TEST_UNARY = {"-" + c for c in "abcdefghknoprstuvwxzGLNORS"}
# Passes of a loop the audit follows before it stops following the directory.
MAX_PASSES = 12
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


def _alt(text: str) -> tuple[str, bool]:
    """A text without ALT marks, and whether it had any."""
    return text.replace(ALT, ""), ALT in text


def _unmark(text: str) -> str:
    return text.translate(_UNMARK)


def _fields(word: str, ifs: str | None, params: bool, literal: bool = False) -> list[str]:
    """The fields an expanded word, marked as `_Shell.value` marks it, becomes (POSIX 2.6.5, with
    the shells' differences). Unquoted expansions are split at IFS (None: unset, as space, tab and
    newline): IFS white space at the start or end of a field is dropped and runs of it separate
    fields; any other IFS character, with white space around it, ends a field, so two in a row make
    an empty one and one at the very end makes none. Command substitutions are split in every
    shell, parameter and arithmetic expansions only where `params` (sh and bash; zsh splits them
    only under SH_WORD_SPLIT), and unquoted literal text only where `literal` (bash 3.2's
    here-strings). A word made only of unquoted expansions that leave nothing becomes no field;
    quoted text makes one, but in bash an empty quoted part counts only in a word with nothing
    else in it. zsh (not `params`) also makes an empty last field after a final IFS character
    other than white space. $@'s separators always end a field. Where IFS, or a part
    that would be split, is not known, the word stays one field (unknown, where IFS is)."""
    ifs = " \t\n" if ifs is None else ifs
    white = {c for c in ifs if c in " \t\n"}
    chars: list[tuple[str | None, bool, bool]] = []  # (character or None for quoting, split, expanded)
    mode = None
    for c in word:
        if c == Q_OPEN:
            mode = Q_OPEN
            chars.append((None, False, False))
        elif c in (FIELD, FIELD_CMD):
            mode = c
        elif c in (Q_CLOSE, FIELD_END):
            mode = None
        else:
            split = mode == FIELD_CMD or (mode == FIELD and params) or (mode is None and literal)
            chars.append((c, split, mode in (FIELD, FIELD_CMD)))
    live = "".join(c for c, split, _ in chars if split and c)
    if live and any(m in ifs for m in (UNKNOWN, "$", "\x01", "\x06")):
        return [UNKNOWN]
    if UNKNOWN in live or "$" in live or "\x01" in live:
        return [_unmark(word)]
    if "\x06" in live and any(not alt or any(c in ifs for c in alt)
                              for m in CHOICE.finditer(_unmark(word)) for alt in m.group(1).split("\x05")):
        return [UNKNOWN]
    if params and any(c for c, _, _ in chars):
        # In bash, a quoted empty part ('' or "") keeps the word only if nothing else is in it:
        # `''$y` with y=' ' is no word at all.
        chars = [x for x in chars if x[0] is not None]
    out: list[str] = []
    cur: list[str] = []
    started = hard = False  # hard: the last delimiter had an IFS character other than white space
    i, n = 0, len(chars)
    while i < n:
        c, split, expanded = chars[i]
        i += 1
        if c is None:
            started = True
        elif c == SPLIT:
            # Quoted, "$@" keeps every parameter, empty ones included; unquoted, it drops them.
            if started or cur or not expanded:
                out.append("".join(cur))
            cur, started = [], not expanded
        elif split and c in ifs:
            space = c in white
            if space and not (started or cur):
                continue
            out.append("".join(cur))
            cur, started, hard = [], False, not space
            while i < n and chars[i][1] and chars[i][0] and chars[i][0] in ifs:
                if chars[i][0] in white:
                    i += 1
                elif space:
                    space, hard = False, True
                    i += 1
                else:
                    break
        else:
            cur.append(c)
            started, hard = True, False
    if started or cur:
        out.append("".join(cur))
    elif hard and not params:
        out.append("")  # zsh: `a:` split at `:` is `a` and an empty field
    return out


def _read_fields(line: str, ifs: str, n: int, bash: bool = True) -> list[str]:
    """What `read` with n names sets from one line, splitting it at IFS as the shell does: runs of
    IFS white space (space, tab, newline) and single other IFS characters, with any white space
    around them, separate fields; leading and trailing IFS white space is dropped; the last name
    takes the rest of the line. Where that rest is one field and a delimiter, bash drops the
    delimiter (`IFS=: read a b <<< a:b:` sets b to `b`) and zsh keeps it (`b:`)."""
    white = {c for c in ifs if c in " \t\n"}
    hard = {c for c in ifs if c not in " \t\n"}
    i, end = 0, len(line)
    while i < end and line[i] in white:
        i += 1
    while end > i and line[end - 1] in white:
        end -= 1
    fields: list[str] = []
    while len(fields) < n - 1 and i < end:
        j = i
        while j < end and line[j] not in white and line[j] not in hard:
            j += 1
        fields.append(line[i:j])
        while j < end and line[j] in white:
            j += 1
        if j < end and line[j] in hard:
            j += 1
            while j < end and line[j] in white:
                j += 1
        i = j
    if len(fields) < n:
        last = line[i:end]
        j = 0
        while j < len(last) and last[j] not in white and last[j] not in hard:
            j += 1
        tail = last[j:]
        if bash and tail and sum(c in hard for c in tail) == 1 and all(c in white or c in hard for c in tail):
            last = last[:j]
        fields.append(last)
    return fields + [""] * (n - len(fields))


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


class _ArithError(Exception):
    """An arithmetic expression the audit cannot evaluate."""


_ARITH_TOKEN = re.compile(r"""\s*(?:(0[xX][0-9a-fA-F]+|\d+)|([A-Za-z_][A-Za-z0-9_]*)|"""
                          r"""(\+\+|--|\*\*=?|<<=|>>=|<=|>=|==|!=|&&|\|\||[-+*/%&^|]=|<<|>>|[-+*/%<>=!~&^|?:,()]))""")
# Binary operators by precedence, loosest first; all left-associative except ** (POW, right-
# associative). bash uses C's order; zsh (without C_PRECEDENCES) binds the shifts and the bitwise
# operators tighter than ** and the rest, so `2 * 3 & 1` is 0 in bash and 2 in zsh.
POW = frozenset({"**"})
_ARITH_BINARY = {
    "bash": [{"||"}, {"&&"}, {"|"}, {"^"}, {"&"}, {"==", "!="}, {"<", ">", "<=", ">="}, {"<<", ">>"},
             {"+", "-"}, {"*", "/", "%"}, POW],
    "zsh": [{"||"}, {"&&"}, {"==", "!="}, {"<", ">", "<=", ">="}, {"+", "-"}, {"*", "/", "%"}, POW,
            {"|"}, {"^"}, {"&"}, {"<<", ">>"}],
}
_ARITH_ASSIGN = {"=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "^=", "|=", "**="}


def _arith_parse(text: str, shell: str = "bash"):
    """An arithmetic expression (bash and zsh `$(( ))`, `(( ))`, `let`) as a tree, read with that
    shell's operator precedence."""
    table = _ARITH_BINARY[shell]
    tokens, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = _ARITH_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise _ArithError(text)
        num, name, op = m.groups()
        if num is not None:
            if len(num) > 1 and num.startswith("0") and not num[1:2] in {"x", "X"}:
                raise _ArithError(num)  # octal in bash, decimal in zsh
            tokens.append(("num", int(num, 0)))
        elif name is not None:
            tokens.append(("name", name))
        elif op is not None:
            tokens.append(("op", op))
        pos = m.end()
    i = 0

    def peek():
        return tokens[i] if i < len(tokens) else ("end", None)

    def take(value=None):
        nonlocal i
        tok = peek()
        if value is not None and tok != ("op", value):
            raise _ArithError(text)
        i += 1
        return tok

    def comma():
        node = assign()
        while peek() == ("op", ","):
            take()
            node = ("comma", node, assign())
        return node

    def assign():
        if peek()[0] == "name" and i + 1 < len(tokens) and tokens[i + 1][0] == "op" and tokens[i + 1][1] in _ARITH_ASSIGN:
            name = take()[1]
            op = take()[1]
            return ("assign", op, name, assign())
        return ternary()

    def ternary():
        # Both branches parse as conditionals: `c ? x : a = 1` is an error in both shells, and an
        # assignment or comma between `?` and `:` is accepted by bash but not by zsh.
        cond = binary(0)
        if peek() == ("op", "?"):
            take()
            yes = ternary()
            take(":")
            return ("cond", cond, yes, ternary())
        return cond

    def binary(level):
        if level == len(table):
            return unary()
        node = binary(level + 1)
        if table[level] is POW:
            if peek() == ("op", "**"):
                take()
                return ("bin", "**", node, binary(level))
            return node
        while peek()[0] == "op" and peek()[1] in table[level]:
            op = take()[1]
            node = ("bin", op, node, binary(level + 1))
        return node

    def unary():
        tok = peek()
        if tok[0] == "op" and tok[1] in {"++", "--"}:
            take()
            name = take()
            if name[0] != "name":
                raise _ArithError(text)
            return ("pre", tok[1], name[1])
        if tok[0] == "op" and tok[1] in {"+", "-", "!", "~"}:
            take()
            return ("un", tok[1], unary())
        return postfix()

    def postfix():
        tok = take()
        if tok[0] == "num":
            return tok
        if tok[0] == "name":
            if peek()[0] == "op" and peek()[1] in {"++", "--"}:
                return ("post", take()[1], tok[1])
            return ("var", tok[1])
        if tok == ("op", "("):
            node = comma()
            take(")")
            return node
        raise _ArithError(text)

    tree = comma() if tokens else ("num", 0)
    if i != len(tokens):
        raise _ArithError(text)
    return tree


def _arith(text: str, lookup, depth: int = 0) -> tuple[int, dict[str, str]]:
    """Evaluate an arithmetic expression: its value, and the variables it assigns (`i++`, `x=2`).
    `lookup(name)` gives a variable's value, or None when the audit does not know it; an empty or
    unset one counts as 0, and a value that is itself an expression is evaluated, as the shells do.
    Raises _ArithError for anything else (an unknown variable, division by zero, overflow), and
    where bash and zsh disagree. They differ in three ways. zsh binds the shifts and bitwise
    operators tighter (see _ARITH_BINARY). bash reads a variable operand when it reaches it, zsh a
    plain variable (`a`, `(a)`) only when the operator applies, after the right side has run, so
    `a + (a = 2)` is 3 in bash and 4 in zsh. And bash 3.2 also checks the branch it skips, in
    `?:`, `&&` and `||`, for division by zero."""
    if depth > 8:
        raise _ArithError(text)
    bash = _arith_run(text, _arith_parse(text, "bash"), lookup, depth, late=False, checks_skipped=True)
    zsh = _arith_run(text, _arith_parse(text, "zsh"), lookup, depth, late=True, checks_skipped=False)
    if bash != zsh:
        raise _ArithError(text)
    return bash


def _arith_run(text: str, tree, lookup, depth: int, late: bool, checks_skipped: bool) -> tuple[int, dict[str, str]]:
    """Evaluate a parsed expression (see `_arith`), reading plain variable operands late, as zsh
    does, or when reached, as bash does; `checks_skipped`: evaluate a skipped branch too, for its
    errors only, as bash 3.2 does."""
    env: dict[str, str] = {}

    def get(name):
        raw = env[name] if name in env else lookup(name)
        if raw is None or UNKNOWN in raw or CHOICE.search(raw) or "$" in raw or "\x01" in raw:
            raise _ArithError(name)
        return _arith(raw, lambda n: env.get(n, lookup(n)), depth + 1)[0] if raw.strip() else 0

    def check(v):
        if not -(2 ** 63) <= v < 2 ** 63:
            raise _ArithError(text)
        return v

    def binop(op, a, b):
        if op in {"/", "%"}:
            if b == 0:
                raise _ArithError(text)
            q = abs(a) // abs(b) * (1 if (a >= 0) == (b >= 0) else -1)  # truncates toward zero
            return q if op == "/" else a - b * q
        if op == "**":
            if b < 0 or b > 64:
                raise _ArithError(text)
            return a ** b
        if op in {"<<", ">>"}:
            if not 0 <= b < 64:
                raise _ArithError(text)
            return a << b if op == "<<" else a >> b
        return {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b,
                "==": int(a == b), "!=": int(a != b), "<": int(a < b), ">": int(a > b),
                "<=": int(a <= b), ">=": int(a >= b)}[op]

    def ev(node):
        kind = node[0]
        if kind == "num":
            return check(node[1])
        if kind == "var":
            return get(node[1])
        if kind == "un":
            x = ev(node[2])
            return {"+": x, "-": -x, "!": int(x == 0), "~": ~x}[node[1]]
        if kind in {"pre", "post"}:
            old = get(node[2])
            new = check(old + (1 if node[1] == "++" else -1))
            env[node[2]] = str(new)
            return new if kind == "pre" else old
        if kind == "assign":
            op, name = node[1], node[2]
            if op == "=":
                value = ev(node[3])
            elif late:
                x = ev(node[3])
                value = binop(op[:-1], get(name), x)
            else:
                old = get(name)
                value = binop(op[:-1], old, ev(node[3]))
            env[name] = str(check(value))
            return check(value)
        if kind == "cond":
            taken, skipped = (node[2], node[3]) if ev(node[1]) else (node[3], node[2])
            skip(skipped)
            return ev(taken)
        if kind == "comma":
            ev(node[1])
            return ev(node[2])
        op = node[1]
        if late and op not in {"&&", "||"} and node[2][0] == "var":
            b = ev(node[3])
            return check(binop(op, get(node[2][1]), b))
        a = ev(node[2])
        if op == "&&":
            if not a:
                skip(node[3])
            return int(bool(a) and bool(ev(node[3])))
        if op == "||":
            if a:
                skip(node[3])
            return int(bool(a) or bool(ev(node[3])))
        return check(binop(op, a, ev(node[3])))

    def skip(node):
        nonlocal env
        if checks_skipped:
            saved = dict(env)
            ev(node)  # raises where the branch would; what it assigns is discarded
            env = saved

    return ev(tree), env


def _arith_targets(text: str) -> set[str]:
    """Variables an arithmetic expression may assign, read from its text."""
    names = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\+\+|--|(?:\*\*|<<|>>|[-+*/%&^|])?=(?!=))", text))
    return names | set(re.findall(r"(?:\+\+|--)\s*([A-Za-z_][A-Za-z0-9_]*)", text))


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


class _Frame:
    """A loop, a function call or a subshell (`barrier`) the shell is inside, and the worlds that
    left it by `break`, `continue` or `return`, each with the shell state it left with."""

    def __init__(self, kind: str):
        self.kind = kind
        self.jumps: dict[str, list[tuple[list, tuple]]] = {"break": [], "continue": [], "return": []}

    def take(self, what: str) -> list[tuple[list, tuple]]:
        out, self.jumps[what] = self.jumps[what], []
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
        self.shell_name: str | None = None  # the shell a command names (bash, sh, dash, zsh), if any
        self.lastpipe = False
        # The loops, function calls and subshells the shell is inside (see `jump`).
        self.frames: list[_Frame] = []
        self.vars: dict[str, str] = {}
        # Whether each variable is exported (True), not (False), or only in some of the branches that
        # may have run ("maybe"); a variable not listed is exported if INHERITED. `inherit`: False in a
        # command `env -i` runs, which has no environment. `allexport`: `set -a`.
        self.exports: dict[str, object] = {}
        self.func_exports: set[str] = set()  # bash `export -f`
        self.inherit = True
        self.allexport = False
        self.integers: set[str] = set()  # `declare -i`: assignments to these are arithmetic
        # Files written earlier (in the transcript, or by this command), by path, as the texts each may
        # have (None: what is on disk at audit time), like functions: a script the command runs is
        # read from here (see `scripts`). `wrote_ever`: files this command writes somewhere;
        # `wrote_later` (from the first pass): those, before it writes them.
        self.files: dict[Path, tuple] = {}
        self.wrote_ever: set[Path] = set()
        self.wrote_later: set[Path] = set()
        # Each function's body and each alias's text, as a tuple of alternatives: one, or several
        # where branches that may each have run left it defined differently (None: not defined).
        self.functions: dict[str, tuple] = {}
        self.aliases: dict[str, tuple] = {}
        self.calls = 0  # depth of function calls being followed
        self.locals: list[dict[str, str | None]] = []  # per call being followed: a local's outer value
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
        self.memo: dict | None = None  # word values inside a test being read (see `value`)

    # Worlds

    @property
    def cwd(self) -> Path:
        return self.worlds[0].cwd if self.worlds else self.workdir

    @property
    def oldpwd(self) -> Path | None:
        return self.worlds[0].oldpwd if self.worlds else None

    def set_worlds(self, worlds: list[_World]) -> None:
        """Merge worlds in the same place, drop exited ones while any other remains, primary first.
        Past MAX_WORLDS the audit stops following the directory (relative paths become suspect).
        No world at all is a state of its own: every world has left by `break`, `continue` or
        `return`, and nothing runs until the loop or function it left takes it back."""
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
        self.worlds = out

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
        return (dict(self.vars), set(self.made), set(self.removed), dict(self.functions), dict(self.aliases),
                dict(self.exports), dict(self.files))

    def restore(self, state: tuple) -> None:
        self.vars, self.made, self.removed = dict(state[0]), set(state[1]), set(state[2])
        self.functions, self.aliases, self.exports = dict(state[3]), dict(state[4]), dict(state[5])
        self.files = dict(state[6])

    def exported(self, name: str, exports: dict | None = None) -> object:
        """Whether a variable is exported: True, False or "maybe"."""
        exports = self.exports if exports is None else exports
        return exports.get(name, self.inherit and name in INHERITED)

    def join(self, states: list[tuple]) -> None:
        """After branches that may each have run, from the same start: a variable they leave
        different has each of their values, a function or alias each of their definitions (or
        none, where one left it undefined), a file each of their texts, a directory counts as made
        only if each made it, and as removed if any removed it."""
        if not states:
            return
        merged = {}
        for name in set().union(*(st[0] for st in states)):
            values = list(dict.fromkeys(c for st in states for c in _choices(st[0].get(name, ""))))
            merged[name] = values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"
        self.vars = merged
        self.made = set.intersection(*(st[1] for st in states))
        self.removed = set.union(*(st[2] for st in states))
        exports = {}
        for name in set().union(*(st[5] for st in states)):
            seen = {self.exported(name, st[5]) for st in states}
            exports[name] = seen.pop() if len(seen) == 1 else "maybe"
        self.exports = exports
        self.files = {path: tuple(dict.fromkeys(a for st in states for a in st[6].get(path, (None,))))
                      for path in set().union(*(st[6] for st in states))}
        for k, key in ((3, lambda b: None if b is None else _text(b)), (4, lambda a: a)):
            table = {}
            for name in set().union(*(st[k] for st in states)):
                alts = {key(a): a for st in states for a in st[k].get(name, (None,))}
                table[name] = tuple(alts.values())
            if k == 3:
                self.functions = table
            else:
                self.aliases = table

    def not_directory(self, p: Path) -> bool:
        """Whether p is, at audit time, something other than a directory that this command did not
        make, remove or make later: then a cd to it certainly failed."""
        if p in self.made or p in self.later or any(_under(p, r) for r in self.removed):
            return False
        try:
            return p.exists() and not p.is_dir()
        except OSError:
            return False

    def exists(self, p: Path, directory: bool = True) -> bool:
        if p in self.made:
            return True
        if self.doubt or p in self.later or any(_under(p, r) for r in self.removed):
            return False
        return p.is_dir() if directory else p.exists()

    @contextmanager
    def child(self):
        """A subshell: directory changes, variables, functions and aliases inside it do not outlast it.
        It keeps the loops and functions around it, so a `break` or `return` inside it ends it."""
        saved = (list(self.worlds), self.known, dict(self.vars), dict(self.functions), dict(self.aliases),
                 self.dialect, self.shell_name, self.lastpipe, self.frames, dict(self.exports),
                 set(self.func_exports), self.inherit, self.allexport, set(self.integers))
        self.frames = [*self.frames, _Frame("barrier")]
        memo, self.memo = self.memo, None  # a substitution's words are its own
        try:
            yield
        finally:
            self.memo = memo
            (self.worlds, self.known, self.vars, self.functions, self.aliases, self.dialect, self.shell_name,
             self.lastpipe, self.frames, self.exports, self.func_exports, self.inherit, self.allexport,
             self.integers) = saved
            self.set_status(MAYBE)

    @contextmanager
    def process(self, verb: str | None = None):
        """A new shell process (`sh -c`, a script): like a subshell, but it starts with only the
        exported variables (one exported in only some branches is unknown), bash's exported
        functions (if the new shell is bash or sh), no aliases and no loops around it."""
        with self.child():
            names = set(self.vars) | {n for n in self.exports if n not in self.vars}
            env = {}
            for name in names:
                how = self.exported(name)
                if how is True and name in self.vars:
                    env[name] = self.vars[name]
                elif how == "maybe":
                    env[name] = UNKNOWN
            self.vars = env
            self.exports = {name: True for name in env}
            self.functions = {n: f for n, f in self.functions.items()
                              if n in self.func_exports and verb in {"bash", "sh", None}}
            self.func_exports = set(self.functions)
            self.aliases, self.frames, self.allexport, self.integers = {}, [], False, set()
            self.dialect, self.shell_name, self.lastpipe = DIALECTS.get(verb or ""), verb, False
            locals_, self.locals = self.locals, []
            try:
                yield
            finally:
                self.locals = locals_

    # Loops, functions and jumps

    def jump(self, what: str, n: int = 1, status: str | None = None) -> None:
        """`break n`, `continue n` or `return` in every world: the worlds leave for the nth loop
        around them (or the outermost, if there are fewer) or the function call, taking the shell
        state with them. Functions are transparent to break and continue (dash ignores those that
        would leave a function, and `sh` may be dash), and loops to return. Where the target lies
        outside a subshell, the subshell just ends. With no target, bash carries on (return fails)
        while zsh exits; dash exits on return only. `status`: the status `return n` sets."""
        if not self.worlds:
            return
        worlds = [w if status is None else w._replace(status=status) for w in self.worlds]
        target, barrier, loops, crossed = None, False, 0, False
        for f in reversed(self.frames):
            if f.kind == "barrier":
                barrier = True
            elif what == "return":
                if f.kind == "function":
                    target = f
                    break
            elif f.kind == "function":
                crossed = True
            elif f.kind == "loop":
                target, loops = f, loops + 1
                if loops >= n:
                    break
        if crossed and self.shell_name == "dash":
            target = None  # dash ignores a break or continue that would leave a function
        if target is None:
            exits = {"zsh", "dash"} if what == "return" else {"zsh"}
            if self.shell_name in exits and not crossed:
                self.set_status(EXITED)
            elif what == "return":
                self.set_status(FAILED)
            else:
                self.set_status(OK)
            return
        if not barrier:
            target.jumps[what].append((worlds, self.state()))
        # `sh` may be dash, which goes on in the function: there the shell stays, as an alternative.
        self.worlds = [w._replace(primary=False) for w in worlds] if crossed and self.shell_name == "sh" else []

    def rejoin(self, entries: list[tuple[list, tuple]]) -> None:
        """Take back worlds that left by a jump, joining the shell state they left with."""
        if entries:
            states = [st for _, st in entries]
            self.join([self.state(), *states] if self.worlds else states)
            self.set_worlds(self.worlds + [w for ws, _ in entries for w in ws])

    def loop_key(self) -> tuple:
        """The shell's state at a loop's head; a loop whose head repeats a state has no new pass."""
        return (frozenset(self.worlds), frozenset(self.vars.items()), frozenset(self.made), frozenset(self.removed),
                frozenset((k, tuple(None if b is None else _text(b) for b in v)) for k, v in self.functions.items()),
                frozenset(self.aliases.items()), frozenset(self.exports.items()))

    def loop(self, test, body, when: str, update=None) -> None:
        """A while, until or C-style for loop: `test()` sets the status, the body runs where it
        is `when` (or unknown), `update()` runs after each pass. The audit follows the passes,
        through `continue` and `break`, until the loop ends in every world or its head repeats a
        state it has had (further passes add nothing). After MAX_PASSES passes, variables still
        changing from pass to pass (a counter) become unknown, so that the passes after cover
        every value; after twice as many, the audit stops following the directory. Where the
        condition was unknown before the first pass, places reached only by not running the body at
        all are alternatives, as in `fork`."""
        frame = _Frame("loop")
        self.frames = [*self.frames, frame]
        exits: list[_World] = []
        states: list[tuple] = []
        zero: list[_World] = []  # left before any pass, where the condition was unknown
        zero_definite = False
        seen: set = set()
        last: dict[str, str] = {}
        ran = False
        try:
            for k in range(2 * MAX_PASSES + 1):
                if not self.worlds:
                    break
                if k == MAX_PASSES:
                    for name, value in self.vars.items():
                        if last.get(name, value) != value:
                            self.vars[name] = UNKNOWN
                last = dict(self.vars)
                key = self.loop_key()
                if key in seen:
                    self.worlds = []  # these worlds' further passes were followed already
                    break
                seen.add(key)
                test()
                live = [w for w in self.worlds if w.status != EXITED]
                gone = [w for w in self.worlds if w.status == EXITED]
                staying = [w for w in live if w.status in (when, MAYBE)]
                leaving = [w for w in live if w.status != when] + gone
                if leaving:
                    states.append(self.state())
                    if k == 0:
                        zero += [w for w in leaving if w.status == MAYBE]
                        zero_definite = any(w.primary for w in leaving if w.status != MAYBE)
                        exits += [w for w in leaving if w.status != MAYBE]
                    else:
                        exits += leaving
                if not staying:
                    self.worlds = []
                    break
                if k == 2 * MAX_PASSES:
                    if self.known:
                        self.notes.append("a loop that runs more times than the audit follows")
                    self.known = False
                    exits += staying
                    states.append(self.state())
                    self.worlds = []
                    break
                self.set_worlds(staying)
                ran = True
                body()
                self.rejoin(frame.take("continue"))
                for ws, st in frame.take("break"):
                    exits += ws
                    states.append(st)
                if update is not None and self.worlds:
                    update()
        finally:
            self.frames = self.frames[:-1]
        cwds = {w.cwd for w in exits if w.primary and w.status != EXITED}
        if zero and cwds and not zero_definite:
            zero = [w if w.cwd in cwds else w._replace(primary=False) for w in zero]
        if states:
            self.join(states)
        self.set_worlds(exits + zero)
        self.set_status(MAYBE if ran else OK)

    def each(self, setups: list, body, end=None) -> None:
        """A loop whose passes are known (a literal `for` list, `while read` on known input): before
        pass k, `setups[k]()` binds the loop variable; `end()` runs where the loop runs out."""
        frame = _Frame("loop")
        self.frames = [*self.frames, frame]
        exits: list[_World] = []
        states: list[tuple] = []
        try:
            for setup in setups:
                if not self.worlds:
                    break
                setup()
                self.visit(body)
                self.rejoin(frame.take("continue"))
                for ws, st in frame.take("break"):
                    exits += ws
                    states.append(st)
        finally:
            self.frames = self.frames[:-1]
        if self.worlds:
            if end is not None:
                end()
            exits += self.worlds
            states.append(self.state())
        if states:
            self.join(states)
        self.set_worlds(exits)
        if not setups:
            self.set_status(OK)

    def call(self, body) -> None:
        """Run a function's body (or a sourced file) in the calling shell; `return` comes back here."""
        frame = _Frame("function")
        self.frames = [*self.frames, frame]
        try:
            self.visit(body) if not isinstance(body, str) else self.run(body)
        finally:
            self.frames = self.frames[:-1]
        self.rejoin(frame.take("return"))

    def arith(self, text: str) -> int | None:
        """Evaluate shell arithmetic, applying what it assigns; None if the audit cannot, and then
        what it may assign is unknown."""
        if "$(" in text or "`" in text:
            value = None
        else:
            def lookup(name):
                # A variable this command never set is unset (0), unless it may come from the
                # environment or is one of the shell's own.
                if name in self.vars:
                    return self.vars[name]
                return None if name in VOLATILE or (name.isupper() and self.inherit) else ""

            def known(m: re.Match) -> str:
                v = lookup(m.group(1))
                return UNKNOWN if v is None else v

            expanded = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*|[0-9#])\}?", known, text)
            try:
                value, assigned = _arith(expanded, lookup)
            except _ArithError:
                value = None
            else:
                self.vars.update(assigned)
        if value is None:
            for name in _arith_targets(text):
                self.vars[name] = UNKNOWN
        return value

    # Values

    def expand(self, word: str) -> str:
        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name == "PWD":
                return self.pwd()
            if name == "OLDPWD":
                return "$OLDPWD" if self.oldpwd is None else str(self.oldpwd)
            if name == "*" and "@" in self.vars:
                ifs = self.vars.get("IFS")
                return self.vars["@"].replace(SPLIT, " " if ifs is None else ifs[:1])
            if name in self.vars:
                return self.vars[name]
            if name == "HOME" and self.inherit:
                return str(HOME)
            return "$" + name if self.inherit else ""

        return _VAR.sub(sub, word)

    def home(self) -> str | None:
        """Where `cd` with no operand goes: $HOME, or None where it is unset."""
        value = self.expand("\x01HOME\x02")
        return value or None

    def pwd(self) -> str:
        """$PWD: the directory of each place the shell could be (a choice, where there are several,
        whose alternatives from alternative places carry ALT)."""
        places: dict[Path, bool] = {}
        for w in self.worlds:
            places[w.cwd] = places.get(w.cwd, False) or w.primary
        texts = [str(c) if primary else ALT + str(c) for c, primary in places.items()] or [str(self.workdir)]
        return texts[0] if len(texts) == 1 else "\x06" + "\x05".join(texts) + "\x07"

    def bind(self, args: list[str], zero: str | None = None) -> None:
        """Set the positional parameters ($0 to $9, $#, $@ and $*)."""
        if zero is not None:
            self.vars["0"] = zero
        for i in range(1, 10):
            self.vars[str(i)] = args[i - 1] if i <= len(args) else ""
        self.vars["#"] = str(len(args))
        self.vars["@"] = SPLIT.join(args)
        self.vars["*"] = " ".join(args)

    def value(self, node, split: bool = False) -> str:
        """A word's value after quote removal, with variables marked for `expand`. Command
        substitutions and arithmetic inside it are run along the way (once, in a test the audit
        reads several ways: see `memo`). `split`: keep the marks `_fields` splits by (quoted text
        and unquoted expansions), for words the shell splits into fields."""
        if self.memo is None:
            marked = self._value(node)
        else:
            key = (node.id, node.start_byte, node.end_byte)
            if key not in self.memo:
                self.memo[key] = self._value(node)
            marked = self.memo[key]
        return marked if split else _unmark(marked)

    def _value(self, node) -> str:
        t = node.type
        if t == "word":
            # A backslash quotes the character after it.
            return re.sub(r"\\(.)", lambda m: Q_OPEN + m.group(1) + Q_CLOSE, _text(node), flags=re.S)
        if t == "raw_string":
            return Q_OPEN + _text(node)[1:-1] + Q_CLOSE
        if t == "ansi_c_string":
            try:
                return Q_OPEN + _text(node)[2:-1].encode().decode("unicode_escape") + Q_CLOSE
            except UnicodeDecodeError:
                return Q_OPEN + _text(node)[2:-1] + Q_CLOSE
        if t in {"string", "translated_string"}:
            if _text(node) in {'"$@"', '"${@}"'} and self.vars.get("#") == "0":
                return ""  # "$@" with no parameters is no word at all
            # Build from the source span: the grammar leaves some characters (newlines among them)
            # outside every child node.
            src, base = node.text, node.start_byte
            pos, end = (2 if t == "translated_string" else 1), len(src) - 1
            parts = []
            for c in node.named_children:
                cs, ce = c.start_byte - base, c.end_byte - base
                if cs > pos:
                    parts.append(_unquote_double(src[pos:cs]))
                if c.type == "string_content":
                    parts.append(_unquote_double(c.text))
                elif c.type in {"simple_expansion", "expansion"} and _text(c) in {"$*", "${*}"}:
                    parts.append("\x01*\x02")  # "$*": the parameters joined by IFS's first character
                else:
                    parts.append(self.value(c))
                pos = max(pos, ce)
            if end > pos:
                parts.append(_unquote_double(src[pos:end]))
            return Q_OPEN + "".join(parts) + Q_CLOSE
        if t == "simple_expansion":
            name = node.named_children[0] if node.named_children else None
            if name is not None and name.type in {"variable_name", "special_variable_name"}:
                # Unquoted, $* is one word per parameter before splitting, like $@.
                return FIELD + "\x01" + ("@" if _text(name) == "*" else _text(name)) + "\x02" + FIELD_END
            return FIELD + UNKNOWN + FIELD_END
        if t == "expansion":
            text = _text(node)
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#])\}", text)
            if m:
                return FIELD + "\x01" + ("@" if m.group(1) == "*" else m.group(1)) + "\x02" + FIELD_END
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*|[0-9]+):?[-=]([^}$`]*)\}", text)
            if m:
                return FIELD + ("\x01" + m.group(1) + "\x02" if self.vars.get(m.group(1)) else m.group(2)) + FIELD_END
            for c in node.named_children:
                self.value(c)  # runs any command substitution inside
            return FIELD + UNKNOWN + FIELD_END
        if t == "command_substitution":
            return FIELD_CMD + self.substitute(node) + FIELD_END
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
            self.substitutions(node)
            text = _text(node)
            v = self.arith(text[3:-2] if text.startswith("$((") else text[2:-1])
            return FIELD + (UNKNOWN if v is None else str(v)) + FIELD_END
        if node.child_count == 0:
            return _text(node)
        if t == "concatenation":
            return "".join(self.value(c, split=True) for c in node.children)
        return "".join(self.value(c, split=True) for c in node.named_children) or _text(node)

    def substitutions(self, node) -> None:
        """Run the command substitutions inside a node (in arithmetic, say)."""
        for c in node.named_children:
            if c.type in {"command_substitution", "process_substitution"}:
                self.value(c)
            else:
                self.substitutions(c)

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
            text, alt = _alt(text)
            for w in self.worlds:
                p = _resolve(text, w.cwd, bare=bare)
                if p is not None:
                    out[p] = out.get(p, False) or (w.primary and not alt)
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
        text, alt = _alt(text)
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
                    self.reach(q, (w.primary or not relative) and not alt)
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
        if not self.worlds:
            return  # every place has left by break, continue or return: nothing here runs
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
        if not self.worlds:
            return
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
            self.c_style_for(node)
        elif t == "compound_statement" and node.children and _text(node.children[0]) == "((":
            # `(( expr ))`: true where the expression is not 0.
            self.substitutions(node)
            v = self.arith(_text(node)[2:-2])
            self.set_status(MAYBE if v is None else OK if v else FAILED)
        elif t == "function_definition":
            name = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if body is not None:
                if name is not None:
                    self.functions[_text(name)] = (body,)
                with self.child():  # paths in a function that is never called still count
                    self.call(body)
            self.set_status(OK)
        elif t == "variable_assignment":
            self.assign(node)
            self.set_status(_assignment_status(node))
        elif t == "variable_assignments":
            for c in node.named_children:
                self.assign(c)
            self.set_status(_assignment_status(node))
        elif t == "declaration_command":
            self.declare(node)
        elif t == "unset_command":
            self.unset([self.expand(self.value(c)) for c in node.named_children])
        elif t == "for_statement":
            self.for_loop(node)
        elif t == "test_command":
            saved, self.memo = self.memo, {}
            try:
                self.test_command(node)
            finally:
                self.memo = saved
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

    def test_command(self, node) -> None:
        for c in node.named_children:
            self.test_words(c)
        pattern = _text(node).startswith("[[")
        tokens = self.test_tokens(node, split=not pattern)[1:-1]  # without the brackets
        if not {"&&", "||", "-a", "-o", "(", ")"} & set(tokens):
            # As `test` reads its arguments: the grammar takes `[ ! a = b ]` as `(! a) = b`.
            self.set_status(self.test_args(tokens, pattern))
        elif not pattern and tokens != self.test_tokens(node)[1:-1]:
            self.set_status(MAYBE)  # field splitting changed the expression the grammar read
        else:
            exprs = node.named_children
            self.set_status(self.test_eval(exprs[0], pattern) if len(exprs) == 1 else MAYBE)

    def test_status(self, op: str, word: str) -> str:
        """`[ -e x ]`, `[ -d x ]` and `[ -f x ]`, judged by what x is at audit time (most likely what
        it was when the command ran) and what the command itself made or removed: true if x is
        there and of that kind, false if it is there and of another kind, and otherwise unknown,
        since x may have been there then. Other file tests are unknown."""
        p = self.resolve(word, bare=True)
        if p is None or op not in {"-e", "-a", "-d", "-f"}:
            return MAYBE
        if p in self.made:
            return FAILED if op == "-f" else OK
        if self.doubt or p in self.later or any(_under(p, r) for r in self.removed) or not p.exists():
            return MAYBE
        if op in {"-e", "-a"}:
            return OK
        return OK if (p.is_dir() if op == "-d" else p.is_file()) else FAILED

    def test_args(self, ops: list[str], pattern: bool = False) -> str:
        """The status of `test` (or `[`) with these arguments, when the audit can tell: string and
        integer comparisons of known values, -z and -n, and file tests (see `test_status`).
        `pattern`: in `[[ ]]`, the right side of == and = is a glob pattern."""
        ops = [o.replace(ALT, "") for o in ops]
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
            if op not in _TEST_UNARY:
                return FAILED  # `[ = x ]`, `[ a b ]`: an error, status 2, in bash and zsh
            return self.test_status(op, x)
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

    def test_tokens(self, node, split: bool = False) -> list[str]:
        """A test expression's operators and operand values, in order. `split`: in `[ ]`, where
        operands are command words, split operands into fields (an operand the shells the audit may
        be in split differently is unknown)."""
        out: list[str] = []
        for c in node.children:
            if c.type in {"unary_expression", "binary_expression", "parenthesized_expression"}:
                out += self.test_tokens(c, split)
            elif not c.is_named or c.type == "test_operator":
                out.append(_text(c))
            elif split:
                marked = self.expand(self.value(c, split=True))
                ways = [_fields(marked, self.vars.get("IFS"), p) for p in self.splits()]
                out += ways[0] if all(w == ways[0] for w in ways) else [UNKNOWN]
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
                and self._command_name(conds[0]) == "read" and not conds[0].children_by_field_name("redirect")):
            # `while read x; do ...; done` on input the audit knows: one pass per line, in order.
            cond = conds[0]
            words = [self.expand(self.value(c)) for c in cond.children_by_field_name("argument")]
            prefix = {}
            for c in cond.named_children:
                if c.type == "variable_assignment" and c.child_by_field_name("name") is not None:
                    v = c.child_by_field_name("value")
                    prefix[_text(c.child_by_field_name("name"))] = self.expand(self.value(v)) if v else ""
            names = _read_names(words)

            def bind(line):
                def setup():
                    self.bind_read(names, line, prefix.get("IFS", self.vars.get("IFS")))
                    self.set_status(OK)
                return setup

            lines = stdin.splitlines()
            if len(lines) <= 4 * MAX_PASSES:
                self.each([bind(line) for line in lines], body, end=bind(""))
                self.set_status(OK)
                return
        if body is None:
            for c in conds:
                self.visit(c)
            self.set_status(MAYBE)
            return

        def test():
            self.set_status(MAYBE)
            for c in conds:
                self.visit(c)

        self.loop(test, lambda: self.visit(body), FAILED if until else OK)

    def bind_read(self, names: list[str], line: str | None, ifs: str | None = None) -> None:
        """What `read NAME...` sets from one line (None: a line the audit does not know), split at
        IFS (`ifs`: its value, None where unset)."""
        ifs = " \t\n" if ifs is None else ifs
        if line is None or UNKNOWN in ifs or CHOICE.search(ifs) or "$" in ifs:
            for name in names:
                self.vars[name] = UNKNOWN
            return
        ways = {"posix": [True], "zsh": [False]}.get(self.dialect, [True, False])  # bash's way, zsh's
        values = [_read_fields(line, ifs, len(names), bash=b) for b in ways]
        for k, name in enumerate(names):
            alts = list(dict.fromkeys(v[k] for v in values))
            self.vars[name] = alts[0] if len(alts) == 1 else "\x06" + "\x05".join(alts) + "\x07"

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
        """A `for` loop: over a literal list, the body runs once per item, in order; over a glob, once
        per match at audit time, or not at all; over a list the audit cannot work out (or a long
        one), as a loop with an unknown item (see `loop`)."""
        var = node.child_by_field_name("variable")
        name = _text(var) if var is not None else None
        words = node.children_by_field_name("value")
        lists = self.word_lists(self.marked_words(words, node))
        if not words and any(not c.is_named and _text(c) == "in" for c in node.children):
            lists = [[]]
        elif not words:
            lists = [self.vars.get("@", "").split(SPLIT) if self.vars.get("@") else []]  # `for x; do`
        if len(lists) == 1:
            self.for_items(name, lists[0], node)
        else:
            self.either(*(lambda items=items: self.for_items(name, items, node) for items in lists))

    def for_items(self, name: str | None, items: list[str], node) -> None:
        for item in items:
            self.add(item, bare=False)
        body = node.child_by_field_name("body")
        if body is None:
            return

        def bind(value):
            def setup():
                if name is not None:
                    self.vars[name] = value
            return setup

        if any(any(c in x for c in "$\x06" + UNKNOWN) for x in items):
            self.loop(lambda: self.set_status(MAYBE), lambda: (bind(UNKNOWN)(), self.visit(body)), OK)
            return
        globbed = any(any(c in x for c in "*?[") for x in items)
        values: list[str] = []
        for item in items:
            p = self.resolve(item, bare=True) if any(c in item for c in "*?[") else None
            values += [str(x) for x in _expand(p)] if p is not None else [item]
        if len(values) > 4 * MAX_PASSES:
            self.loop(lambda: self.set_status(MAYBE), lambda: (bind(UNKNOWN)(), self.visit(body)), OK)
        elif globbed:
            self.set_status(MAYBE)
            self.fork(lambda: self.each([bind(v) for v in values], body), OK)  # the matches may differ
        else:
            self.each([bind(v) for v in values], body)

    def c_style_for(self, node) -> None:
        """`for (( init; cond; update ))`, as a while loop on the arithmetic (an empty condition is true)."""
        parts: dict[str, list[str]] = {"initializer": [], "condition": [], "update": []}
        for i, c in enumerate(node.children):
            field = node.field_name_for_child(i)
            if field in parts:
                parts[field].append(_text(c))
                self.substitutions(c)
        text = {k: "".join(v) for k, v in parts.items()}
        body = node.child_by_field_name("body")
        if text["initializer"]:
            self.arith(text["initializer"])

        def test():
            v = self.arith(text["condition"]) if text["condition"].strip() else 1
            self.set_status(MAYBE if v is None else OK if v else FAILED)

        def update():
            if text["update"].strip():
                self.arith(text["update"])

        self.loop(test, (lambda: self.visit(body)) if body is not None else (lambda: None), OK, update)

    def declare(self, node) -> None:
        """export, declare, typeset, local and readonly: assignments, with `-x` (and export) exporting,
        `-n` (export) or `+x` unexporting, `-i` making the variable arithmetic, `-f` naming functions."""
        keyword = _text(node.children[0]) if node.children else ""
        flags, names = "", []
        for c in node.named_children:
            if c.type == "variable_assignment":
                names.append(c)
            elif c.type in {"word", "variable_name", "string", "raw_string", "concatenation", "simple_expansion",
                            "expansion"}:
                w = self.expand(self.value(c))
                if w.startswith(("-", "+")) and len(w) > 1 and not names:
                    flags += w
                else:
                    names.append(w)
        self.declaration(keyword, flags, names)
        self.set_status(_assignment_status(node))

    def declaration(self, keyword: str, flags: str, names: list) -> None:
        """What a declaration does (see `declare`); each of `names` is an assignment node or a word."""
        unexport = (keyword == "export" and "n" in flags.lstrip("-")) or "+x" in flags
        export = not unexport and (keyword == "export" or ("x" in flags and "-" in flags))
        functions = "f" in flags.lstrip("-+")
        for item in names:
            if isinstance(item, str):
                m = ASSIGN.match(item)
                name, value = (m.group(1), m.group(2)) if m else (item, None)
            else:
                n = item.child_by_field_name("name")
                if n is None:
                    continue
                name, value = _text(n), None
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            if functions:
                if export:
                    self.func_exports.add(name)
                elif unexport:
                    self.func_exports.discard(name)
                continue
            if "i" in flags.lstrip("-"):
                self.integers.add(name)
            if self.locals and (keyword == "local" or keyword in {"declare", "typeset"} and "g" not in flags):
                self.locals[-1].setdefault(name, self.vars.get(name))
            if isinstance(item, str):
                if value is not None:
                    self.set_var(name, value)
                elif keyword == "local" and name not in self.vars:
                    self.vars[name] = ""
            else:
                self.assign(item)
            if export:
                self.exports[name] = True
            elif unexport:
                self.exports[name] = False

    def unset(self, args: list[str]) -> None:
        """`unset -f` removes functions, `unset -v` variables; with neither, bash removes the variable
        if there is one and otherwise the function, zsh only the variable."""
        flags = "".join(a[1:] for a in args if a.startswith("-"))
        names = [a for a in args if not a.startswith("-")]

        def drop_var(name):
            self.vars[name] = ""
            self.exports[name] = False

        def bash_way():
            for n in names:
                if n in self.vars and self.vars[n] != "" or n not in self.functions:
                    drop_var(n)
                else:
                    self.functions.pop(n, None)

        def zsh_way():
            for n in names:
                drop_var(n)

        if "f" in flags:
            for n in names:
                self.functions.pop(n, None)
                self.func_exports.discard(n)
        elif "v" in flags or not any(n in self.functions for n in names) or self.dialect == "zsh":
            zsh_way()
        elif self.dialect == "posix":
            bash_way()
        else:
            self.either(bash_way, zsh_way)
        self.set_status(OK)

    def assign(self, node) -> None:
        name = node.child_by_field_name("name")
        val = node.child_by_field_name("value")
        if name is None:
            return
        value = self.expand(self.value(val)).replace(SPLIT, " ") if val is not None else ""
        append = any(not c.is_named and _text(c) == "+=" for c in node.children)
        self.set_var(_text(name), value, append)

    def set_var(self, name: str, value: str, append: bool = False) -> None:
        """Assign a variable, as arithmetic if it is an integer (`declare -i`), exporting it under
        `set -a`. A value that looks like a path counts as one."""
        if name in self.integers:
            v = self.arith(f"{name}+({value})" if append else value or "0")
            value = UNKNOWN if v is None else str(v)
        elif append:
            value = self.vars.get(name, "") + value
        self.vars[name] = value
        if self.allexport:
            self.exports[name] = True
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

    def redirect(self, redirects: list, stdin: str | None, outs: list | None = None,
                 ifs: str | None | bool = False) -> tuple[str | None, list]:
        """Note the files that redirections name; return what reaches standard input (a
        here-document or here-string, when there is one) and any statements a here-document
        carries after it (the rest of a pipeline, say). Files standard output goes to are added to
        `outs`, as (target, appended)."""
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
                fd = next((_text(c) for c in r.named_children if c.type == "file_descriptor"), "")
                if outs is not None and op in {">", ">>", ">|", "&>", "&>>"} and fd in {"", "1"}:
                    outs.append((target, op.endswith(">>")))
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
                        self.redirect([c], None, outs)
                    elif c.type in STATEMENTS:
                        after.append(c)
            elif r.type == "herestring_redirect":
                stdin = self.herestring(list(r.named_children), ifs)
        return stdin, after

    def herestring(self, parts: list, ifs: str | None | bool = False) -> str:
        """What a here-string feeds standard input (without its final newline). bash 3.2, the
        /bin/bash of macOS, splits the word's unquoted parts at IFS, literal text included, and
        joins the fields with spaces (`IFS=: cat <<< a:b` prints `a b`, and a command's own `IFS=`
        counts); zsh, like later versions of bash, feeds the word as it is, with "$@" joined by
        IFS's first character. Where the shell is not known and the two differ, the input is
        unknown. `ifs`: IFS as the command's own assignments set it (False: they do not)."""
        ifs = self.vars.get("IFS") if ifs is False else ifs
        marked = [self.expand(self.value(c, split=True)) for c in parts]
        join = " " if ifs is None else ifs[:1]
        plain = " ".join(_unmark(m).replace(SPLIT, join) for m in marked)
        if self.dialect == "zsh":
            return plain
        split = " ".join(" ".join(_fields(m, ifs, True, literal=True)) for m in marked)
        return split if self.dialect == "posix" or split == plain else UNKNOWN

    def simple(self, node, redirects: list | None = None, stdin: str | None = None) -> None:
        if not self.worlds:
            return
        assigns, words, args, redirs = [], [], [], list(redirects or [])
        for c in node.named_children:
            if c.type == "variable_assignment":
                assigns.append(c)
            elif c.type in REDIRECTS:
                redirs.append(c)
            elif c.type == "command_name":
                inner = c.named_children[0] if c.named_children else c
                words.append(self.value(inner, split=True) if inner is not c else _text(c))
            elif c.type != "comment":
                args.append(c)
        words += self.marked_words(args, node)
        # Words expand, and split into fields, before the command's own assignments take effect,
        # as in the shell. Where the shells split them differently, the command runs each way.
        lists = self.word_lists(words)
        outs: list[tuple[str, bool]] = []
        stdin, after = self.redirect(redirs, stdin, outs, ifs=self.prefix_ifs(assigns))
        if len(lists) == 1:
            self.run_simple(node, assigns, lists[0], stdin, outs, after)
        else:
            self.either(*(lambda ws=ws: self.run_simple(node, assigns, ws, stdin, outs, after) for ws in lists))

    def marked_words(self, nodes: list, parent) -> list[str]:
        """The marked values of a command's argument nodes. The grammar drops a backslash-escaped
        blank after an expansion or a quoted string (`$y\\ x` comes as `$y` and `x`): such
        neighbours are one word, with the blank quoted."""
        out: list[str] = []
        src, base, prev = parent.text, parent.start_byte, None
        for n in nodes:
            value = self.value(n, split=True)
            gap = src[prev.end_byte - base:n.start_byte - base] if prev is not None else b""
            if gap in (b"\\ ", b"\\\t"):
                out[-1] += Q_OPEN + gap[1:].decode() + Q_CLOSE + value
            else:
                out.append(value)
            prev = n
        return out

    def splits(self) -> list[bool]:
        """Whether unquoted parameter expansions split into fields: in sh and bash, not in zsh, and
        either, where the shell is not known."""
        return {"posix": [True], "zsh": [False]}.get(self.dialect, [True, False])

    def word_lists(self, words: list[str]) -> list[list[str]]:
        """The words marked words become after expansion and field splitting (see `_fields`), in
        each shell the audit may be in: one list, or two where the shells differ."""
        out: list[list[str]] = []
        for params in self.splits():
            fields = [f for w in words for f in _fields(self.expand(w), self.vars.get("IFS"), params)]
            if fields not in out:
                out.append(fields)
        return out

    def prefix_ifs(self, assigns: list) -> str | None | bool:
        """IFS as a command's own assignments set it (`IFS=: cmd`), which bash 3.2 uses to split a
        here-string: its value, UNKNOWN where it is not a plain word, or False where they do not
        set it."""
        for a in reversed(assigns):
            name, val = a.child_by_field_name("name"), a.child_by_field_name("value")
            if name is not None and _text(name) == "IFS":
                if val is None:
                    return ""
                plain = val.type in {"word", "raw_string"} or (
                    val.type == "string" and all(c.type == "string_content" for c in val.named_children))
                return self.value(val) if plain else UNKNOWN
        return False

    def run_simple(self, node, assigns: list, words: list[str], stdin: str | None, outs: list, after: list) -> None:
        if not words:
            for a in assigns:
                self.assign(a)
            self.set_status(_assignment_status(node))
        else:
            # Assignments before a command hold for it alone, exported to it.
            saved, exports = {}, {}
            for a in assigns:
                name = a.child_by_field_name("name")
                if name is not None:
                    saved[_text(name)] = self.vars.get(_text(name))
                    exports[_text(name)] = self.exports.get(_text(name))
                self.assign(a)
                if name is not None:
                    self.exports[_text(name)] = True
            self.command(words, stdin)
            for name, old in saved.items():
                if old is None:
                    self.vars.pop(name, None)
                else:
                    self.vars[name] = old
            for name, old in exports.items():
                if old is None:
                    self.exports.pop(name, None)
                else:
                    self.exports[name] = old
        for target, append in outs:
            self.wrote(target, self.output if words else "", append)
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

    def chdir(self, target: str | None, push: bool = False) -> None:
        """cd in every world (with no target, to $HOME; where HOME is unset, the cd fails). A target
        missing at audit time forks the world: the cd may have worked (it was there then) or failed,
        leaving the shell where it was (not primary). A target that is a file fails. `push`: pushd, which adds the directory it
        leaves to the stack only where it moves."""
        if target is None:
            target = self.home()
            if target is None:
                self.set_status(FAILED)
                return
        if "$" in target or UNKNOWN in target:
            self.known = False
            self.notes.append(f"cd to {target.replace(UNKNOWN, '<unknown>')}, which the audit cannot expand")
            self.set_status(MAYBE)
            return
        out = []
        for w in self.worlds:
            stack = (*w.stack, w.cwd) if push else w.stack
            # A target with several possible values goes to each of them.
            for choice in _choices(target):
                t, alt = _alt(choice)
                primary = w.primary and not alt
                cands = self.cd_candidates(t, w.cwd)
                for c in cands:
                    self.reach(c, primary)
                there = [c for c in cands if self.exists(c)]
                if there:
                    out.append(_World(there[0], w.cwd, stack, OK, primary))
                elif all(self.not_directory(c) for c in cands):
                    out.append(w._replace(status=FAILED))  # a file, not a directory: the cd fails
                else:
                    out.append(_World(cands[-1], w.cwd, stack, OK, primary))
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
            if self.with_script(verb_word, lambda text: self.run_script(verb_word, text, None, args)):
                return
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
            # A function runs in the calling shell, with its own positional parameters and locals.
            for a in args:
                self.add(a, bare=False)
            saved = {k: self.vars.get(k) for k in POSITIONAL}
            self.bind(args)
            self.calls += 1
            self.inlined += 1
            self.locals.append({})
            try:
                self.call(self.functions[verb][0])
            finally:
                self.calls -= 1
                for k, old in [*self.locals.pop().items(), *saved.items()]:
                    if old is None:
                        self.vars.pop(k, None)
                    else:
                        self.vars[k] = old
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
        if verb in {"break", "continue"}:
            n = int(args[0]) if args and args[0].isdigit() and int(args[0]) > 0 else 1
            self.jump(verb, n)
            return
        if verb == "return":
            status = None  # the status of the last command
            if args:
                status = (OK if int(args[0]) % 256 == 0 else FAILED) if re.fullmatch(r"-?\d+", args[0]) else MAYBE
            self.jump("return", status=status)
            return
        if verb == "let":
            v = None
            for a in args:
                v = self.arith(a)
            self.set_status(FAILED if not args else MAYBE if v is None else OK if v else FAILED)
            return
        if verb == "unset":
            self.unset(args)
            return
        if verb == "unalias":
            if "-a" in args:
                self.aliases = {}
            for a in args:
                self.aliases.pop(a, None)
            self.set_status(OK)
            return
        if verb == "shift":
            params = self.vars["@"].split(SPLIT) if self.vars.get("@") else []
            n = int(args[0]) if args and args[0].isdigit() else 1 if not args else None
            if n is None:
                self.set_status(MAYBE)
            elif n > len(params):
                self.set_status(FAILED)
            else:
                self.bind(params[n:])
                self.set_status(OK)
            return
        if verb == "set":
            self.set_builtin(args)
            return
        if verb in {"test", "["}:
            for a in args:
                if a not in {"]", "!"} and not re.fullmatch(r"-[a-zA-Z]+", a):
                    self.add(a, bare=self.cwd != self.workdir)
            self.set_status(self.test_args(args[:-1] if verb == "[" and args[-1:] == ["]"] else args))
            return
        if verb == "read":
            lines = stdin.splitlines() if stdin is not None else None
            self.bind_read(_read_names(args), None if lines is None else lines[0] if lines else "", self.vars.get("IFS"))
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
            flags = "".join(a for a in args if a.startswith(("-", "+")) and len(a) > 1 and not ASSIGN.match(a))
            self.declaration(verb, flags, [a for a in args if not (a.startswith(("-", "+")) and len(a) > 1)])
            self.set_status(OK)
            return
        if verb in SHELLS:
            self.shell_command(verb, args, stdin)
            return
        if verb == "eval":
            self.run(" ".join(args))
            return
        if verb in {"source", "."}:
            if args and self.calls < 4 and self.inlined < 256:
                self.add(args[0], bare=True)

                def source(text):
                    # A sourced file runs in this shell; `return` in it returns from the source.
                    saved = {k: self.vars.get(k) for k in POSITIONAL} if args[1:] else {}
                    if args[1:]:
                        self.bind(args[1:])
                    self.calls += 1
                    self.inlined += 1
                    try:
                        self.call(text)
                    finally:
                        self.calls -= 1
                        for k, old in saved.items():
                            if old is None:
                                self.vars.pop(k, None)
                            else:
                                self.vars[k] = old

                self.with_script(args[0], source)
            elif args:
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
        if verb in {"cd", "chdir"}:
            j = 0
            while j < len(args) and re.fullmatch(r"-[LPe@]+", args[j]):
                j += 1
            if args[j:j + 1] == ["--"]:
                j += 1
            operands = args[j:]
            target = operands[0] if operands else None
            if target is not None and re.fullmatch(r"[+-]\d+", target):
                # zsh takes `cd +N` and `cd -N` from the directory stack; bash, as a directory
                # (+N) or an option it does not have (-N).
                def stack():
                    self.set_worlds([self.stack_cd(w, int(target[1:]), target[0]) for w in self.worlds])

                def literal():
                    self.chdir(target) if target[0] == "+" else self.set_status(FAILED)

                {"zsh": stack, "posix": literal}.get(self.dialect, lambda: self.either(stack, literal))()
                return
            if target == "-":
                if any(w.oldpwd is None for w in self.worlds):
                    # Back to where the shell was before this command (bash 3.2 has no $OLDPWD then).
                    self.chdir("$OLDPWD")
                    return
                self.set_worlds([_World(w.oldpwd, w.cwd, w.stack, OK, w.primary) for w in self.worlds])
                for w in self.worlds:
                    self.reach(w.cwd, w.primary)
            else:
                self.chdir(target)
            return
        if verb == "pushd":
            self.pushd(args)
            return
        if verb == "popd":
            self.popd(args)
            return
        if verb == "dirs":
            if "-c" in args:
                self.worlds = [w._replace(stack=()) for w in self.worlds]
            self.set_status(OK)
            return
        if verb == "apply_patch" and stdin:
            self.patch(stdin)
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
        if verb == "tee":
            for a in operands:
                self.wrote(a, stdin, append=any(re.fullmatch(r"-[a-z]*a[a-z]*", x) for x in args))

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
        scripts: list[str] = []
        if syntax is not None:
            skip |= self.code_args(verb, syntax, args, code, scripts)
        for word in scripts:
            code += [t for t in self.scripts(word) if t is not None]  # a script or program file it runs
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

    def set_builtin(self, args: list[str]) -> None:
        """`set`: `--` (or a first operand) sets the positional parameters; `-a`/`+a` and
        `-o allexport` turn exporting every assignment on and off."""
        j, positional = 0, None
        while j < len(args):
            a = args[j]
            if a in {"--", "-"}:
                positional = args[j + 1:]
                break
            if a in {"-o", "+o"}:
                if args[j + 1:j + 2] == ["allexport"]:
                    self.allexport = a == "-o"
                j += 2
                continue
            if a.startswith(("-", "+")) and len(a) > 1:
                if "a" in a[1:]:
                    self.allexport = a[0] == "-"
                j += 1
                continue
            positional = args[j:]
            break
        if positional is not None:
            self.bind(positional)
        self.set_status(OK)

    @staticmethod
    def _dirs(w: _World) -> list[Path]:
        """A world's directory stack as `dirs` prints it: the current directory first."""
        return [w.cwd, *reversed(w.stack)]

    @staticmethod
    def _world(w: _World, dirs: list[Path], moved: bool) -> _World:
        return _World(dirs[0], w.cwd if moved else w.oldpwd, tuple(reversed(dirs[1:])), OK, w.primary)

    def stack_cd(self, w: _World, n: int, sign: str) -> _World:
        """zsh `cd +N` / `cd -N`: to the Nth stack entry (counting from the left or the right),
        which leaves the stack; the current directory is dropped."""
        dirs = self._dirs(w)
        k = n if sign == "+" else len(dirs) - 1 - n
        if not 0 <= k < len(dirs):
            return w._replace(status=FAILED)
        self.reach(dirs[k], w.primary)
        return self._world(w, [dirs[k], *(d for i, d in enumerate(dirs) if i not in {0, k})], k != 0)

    def pushd(self, args: list[str]) -> None:
        """pushd DIR (a pushd that fails leaves the stack as it was), pushd +N / -N (rotate the
        stack to its Nth entry), pushd with no operand (swap the top two), and bash's `pushd -n DIR`
        (add DIR without going there; zsh takes `-n` as a string to replace, and fails)."""
        no_cd = any(re.fullmatch(r"-[qsLP]*n[qsLP]*", a) for a in args)
        operands = [a for a in args if not re.fullmatch(r"-[nqsLP]+", a)]
        target = operands[0] if operands else None
        if target is not None and re.fullmatch(r"[+-]\d+", target):
            out = []
            for w in self.worlds:
                dirs = self._dirs(w)
                k = int(target[1:]) if target[0] == "+" else len(dirs) - 1 - int(target[1:])
                if not 0 <= k < len(dirs):
                    out.append(w._replace(status=FAILED))
                    continue
                self.reach(dirs[k], w.primary)
                out.append(self._world(w, dirs[k:] + dirs[:k], k != 0))
            self.set_worlds(out)
            return
        if target is None:
            out, lone = [], []
            for w in self.worlds:
                dirs = self._dirs(w)
                if len(dirs) < 2:
                    lone.append(w)
                else:
                    self.reach(dirs[1], w.primary)
                    out.append(self._world(w, [dirs[1], dirs[0], *dirs[2:]], True))
            if lone and self.dialect != "posix":
                # zsh: with nothing to swap, pushd goes to $HOME as `pushd ~` would.
                self.set_worlds(lone)
                self.chdir(None, push=True)
                out += self.worlds
            if lone and self.dialect != "zsh":
                out += [w._replace(status=FAILED) for w in lone]
            self.set_worlds(out)
            return
        if target == "-" and not no_cd:
            # pushd -: to OLDPWD, as `cd -` goes.
            if any(w.oldpwd is None for w in self.worlds):
                self.chdir("$OLDPWD", push=True)
                return
            self.set_worlds([_World(w.oldpwd, w.cwd, (*w.stack, w.cwd), OK, w.primary) for w in self.worlds])
            for w in self.worlds:
                self.reach(w.cwd, w.primary)
            return
        if no_cd:
            def bash():
                out = []
                for w in self.worlds:
                    p = self.resolve(target, bare=True)
                    if p is None:
                        out.append(w._replace(status=FAILED))
                        continue
                    self.reach(p, w.primary)
                    dirs = self._dirs(w)
                    out.append(self._world(w, [dirs[0], p, *dirs[1:]], False))
                self.set_worlds(out)

            {"zsh": lambda: self.set_status(FAILED), "posix": bash}.get(
                self.dialect, lambda: self.either(bash, lambda: self.set_status(FAILED)))()
            return
        self.chdir(target, push=True)

    def popd(self, args: list[str]) -> None:
        """popd (to the next stack entry, which it takes off), popd +N / -N (take the Nth entry off;
        the 0th is the current directory, so the shell moves) and bash's `popd -n` (take the next
        entry off without moving). With too few entries it fails and nothing changes."""
        no_cd = any(re.fullmatch(r"-q*nq*", a) for a in args)
        operands = [a for a in args if not re.fullmatch(r"-[nq]+", a)]
        target = operands[0] if operands else None
        if no_cd and self.dialect != "posix":
            self.set_status(MAYBE)  # zsh's popd -n: left alone
            if self.dialect == "zsh":
                return
        out = []
        for w in self.worlds:
            dirs = self._dirs(w)
            if target is None:
                k = 1 if no_cd else 0
            elif re.fullmatch(r"[+-]\d+", target):
                k = int(target[1:]) if target[0] == "+" else len(dirs) - 1 - int(target[1:])
            else:
                out.append(w._replace(status=FAILED))
                continue
            if len(dirs) < 2 and k == 0 and target is not None:
                # `popd +0` with an empty stack: zsh leaves it alone, bash fails.
                out.append(w._replace(status={"zsh": OK, "posix": FAILED}.get(self.dialect, MAYBE)))
                continue
            if len(dirs) < 2 or not 0 <= k < len(dirs):
                out.append(w._replace(status=FAILED))
                continue
            if k == 0:
                self.reach(dirs[1], w.primary)
                out.append(self._world(w, dirs[1:], True))
            else:
                out.append(self._world(w, dirs[:k] + dirs[k + 1:], False))
        self.set_worlds(out + ([w for w in self.worlds] if no_cd and self.dialect is None else []))

    def scripts(self, word: str) -> list[str | None]:
        """Each text a file the command runs (a script, a sourced file, an awk or sed program) may
        have had, as far as the audit has it (None: none, or no such file): written earlier in the
        transcript or in this command (`files`), or else read now from disk, if it lies in the work
        directory or a temporary directory. A file on disk that this command writes only later may
        not have been there yet."""
        text, _ = _alt(self.expand(word))
        if UNKNOWN in text or CHOICE.search(text) or "$" in text:
            return []
        p = _resolve(text, self.cwd, bare=True)
        if p is None:
            return []
        out: list[str | None] = []
        for alt in self.files.get(p, (None,)):
            if alt is not None:
                out.append(alt)
                continue
            out.append(self.disk(p))
            if out[-1] is not None and p in self.wrote_later:
                out.append(None)
        return list(dict.fromkeys(out))

    def disk(self, p: Path) -> str | None:
        if not (_under(p, self.workdir) or any(_under(p, t) for t in TEMP_DIRS)) or PROTECTED_TEXT.search(str(p)):
            return None
        try:
            if p.is_file() and p.stat().st_size <= 256_000:
                return p.read_text(errors="replace")
        except OSError:
            pass
        return None

    def with_script(self, word: str, run) -> bool:
        """`run(text)` for each text the file may have had (see `scripts`), keeping what any leaves;
        False if the audit has none."""
        alts = self.scripts(word)
        if not any(a is not None for a in alts):
            return False
        runs = [(lambda a=a: run(a) if a is not None else None) for a in alts]
        runs[0]() if len(runs) == 1 else self.either(*runs)
        return True

    def run_script(self, word: str, content: str, verb: str | None, args: list[str]) -> None:
        """Run a script: shell code in a new shell process (the shell its `#!` line names; with none,
        the calling shell runs it as sh), other code scanned for paths (see `scan_code`)."""
        first = content.split("\n", 1)[0]
        if verb is None and first.startswith("#!"):
            parts = first[2:].split()
            prog = os.path.basename(parts[0]) if parts else ""
            if prog == "env":
                rest = [x for x in parts[1:] if not x.startswith("-")]
                prog = os.path.basename(rest[0]) if rest else ""
            if prog not in SHELLS:
                self.scan_code(content)
                return
            verb = prog
        if self.calls >= 4 or self.inlined >= 256:
            return
        self.calls += 1
        self.inlined += 1
        try:
            with self.process(verb or "sh"):
                self.bind(args, zero=word)
                self.run(content)
        finally:
            self.calls -= 1
        self.set_status(MAYBE)

    def wrote(self, word: str, content: str | None, append: bool = False) -> None:
        """Note what a command wrote to a file (None: something the audit does not know)."""
        text, _ = _alt(self.expand(word))
        if UNKNOWN in text or CHOICE.search(text) or "$" in text or text in {"/dev/null", "/dev/stdout", "/dev/stderr"}:
            return
        p = _resolve(text, self.cwd, bare=True)
        if p is None:
            return
        self.wrote_ever.add(p)
        if content is not None and content and not content.endswith("\n"):
            content += "\n"
        if content is None:
            self.files[p] = (None,)
        elif append:
            # Appended to a text the audit does not have: what is on disk at audit time.
            self.files[p] = tuple(None if a is None else a + content for a in self.files.get(p, (None,)))
        else:
            self.files[p] = (content,)

    def patch(self, text: str) -> None:
        """What `apply_patch` writes: an added file's lines, and the lines an update adds (its
        whole text is not in the patch)."""
        path, lines, adding = None, [], False

        def flush():
            if path is not None:
                added = "".join(x + "\n" for x in lines)
                self.wrote_ever.add(path)
                # An update's whole text is on disk at audit time; the added lines alone are a part.
                self.files[path] = (added,) if adding else (added, None)

        for line in text.splitlines():
            m = re.match(r"\*\*\* (Add|Update|Delete) File: (.+)$", line)
            if m:
                flush()
                p = _resolve(m.group(2).strip(), self.cwd, bare=True)
                path, lines, adding = (p if m.group(1) != "Delete" else None), [], m.group(1) == "Add"
                if m.group(1) == "Delete" and p is not None:
                    self.files[p] = ("",)
                if p is not None:
                    self.reach(p, True)
            elif path is not None and line.startswith("+"):
                lines.append(line[1:])
        flush()

    def code_args(self, verb: str, syntax: dict, args: list[str], code: list[str], scripts: list[str]) -> set[int]:
        """Read an interpreter's arguments: append its code to `code` and the files it runs as code (a
        script, `awk -f`) to `scripts`, record files it reads, and return the indices handled here
        (code, and option values that are neither code nor paths). See CODE_SYNTAX for clusters and
        attached values. awk's `-v name=value` values are data, unless its code reads files or runs
        commands (AWK_READS); jq's operands after `--args` or `--jsonargs` are values."""
        handled: set[int] = set()
        codes, values, files = syntax.get("code", ()), syntax.get("values", {}), syntax.get("files", {})
        attached = syntax.get("attached", ())
        next_only = syntax.get("next_only", False)
        given = module = False
        data: list[tuple[int, str]] = []
        operands: list[tuple[int, bool]] = []  # (index, a value after jq's --args)
        as_values = False

        def option(opt: str, att: str | None, j: int) -> int:
            """Handle an option at args[j] with its attached value, if any; return the next index."""
            nonlocal given, module
            if opt in codes:
                if att is not None:
                    code.append(att)
                elif j + 1 < len(args):
                    code.append(args[j + 1])
                    handled.add(j + 1)
                    j += 1
                given = True
            elif opt in files or opt in values:
                n = files.get(opt) or values.get(opt)
                vals = ([att] if att is not None else []) + args[j + 1:j + 1 + n - (att is not None)]
                handled.update(range(j + 1, j + 1 + n - (att is not None)))
                j += n - (att is not None)
                if opt in files and len(vals) == n:
                    self.add(vals[-1], bare=True)
                    if opt in PROGRAM_FILES:
                        scripts.append(vals[-1])
                        given = True
                if opt in {"-v", "--assign"} and vals:
                    data.append((j, vals[0]))
                module = module or opt == "-m"
            handled.add(j)
            return j + 1

        j = 0
        while j < len(args):
            a = args[j]
            if a == "--":
                handled.add(j)
                operands += [(k, as_values) for k in range(j + 1, len(args))]
                break
            if not a.startswith("-") or a == "-":
                if not syntax.get("anywhere"):
                    operands += [(k, as_values) for k in range(j, len(args))]
                    break
                operands.append((j, as_values))
                j += 1
                continue
            if a.startswith("--"):
                name, eq, val = a.partition("=")
                if verb == "jq" and name in {"--args", "--jsonargs"}:
                    as_values = True
                    handled.add(j)
                    j += 1
                    continue
                j = option(name, val if eq else None, j)
                continue
            if a in syntax.get("empty_value", ()) and j + 1 < len(args) and args[j + 1] == "":
                handled |= {j, j + 1}  # BSD `sed -i ''`
                j += 2
                continue
            k, nxt = 1, j + 1
            while k < len(a):
                opt, rest = "-" + a[k], a[k + 1:] or None
                if opt in attached:
                    break
                if opt in syntax.get("digits", ()):
                    k += 1
                    while k < len(a) and a[k].isalnum() and (a[k].isdigit() or a[k] in "xX"):
                        k += 1
                    continue
                if opt in codes or opt in files or opt in values:
                    if next_only and rest is not None:
                        # node: `-pe CODE` — the code is the next argument; the cluster goes on.
                        handled.add(j)
                        k += 1
                        if opt in codes and all("-" + c in codes for c in rest):
                            continue
                        rest = None
                    nxt = option(opt, rest, j)
                    break
                k += 1
            handled.add(j)
            j = max(nxt, j + 1)
        if syntax.get("first") and not given and operands:
            k, _ = operands.pop(0)
            code.append(args[k])
            handled.add(k)
        elif not syntax.get("first") and not given and not module and operands and verb not in {"osascript"}:
            scripts.append(args[operands[0][0]])  # the script file the interpreter runs
        for k, value in operands:
            if value:
                handled.add(k)  # jq --args: a string, not a file
        if verb in {"awk", "gawk", "mawk", "nawk"} and (any(AWK_READS.search(c) for c in code) or scripts):
            for _, v in data:
                self.add(v.partition("=")[2], bare=False)
        return handled

    def shell_command(self, verb: str, args: list[str], stdin: str | None) -> None:
        """sh, bash and the like: `-c CODE [NAME [ARGS]]`, `-s [ARGS]` or no script (code on standard
        input), or a script file (run when the audit has its text; see `script`). The arguments are
        positional parameters, and paths too. The code runs in a new shell process (see `process`),
        as that shell runs code (see DIALECTS)."""
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
            with self.process(verb):
                self.bind(rest[1:], zero=rest[0] if rest else None)
                self.run(code)
            return
        if "s" in flags or not operands:
            for a in operands:
                self.add(a, bare=False)
            if stdin:
                with self.process(verb):
                    self.bind(operands)
                    self.run(stdin)  # shell code on standard input
            return
        self.add(operands[0], bare=True)  # a script file
        for a in operands[1:]:
            self.add(a, bare=False)
        self.with_script(operands[0], lambda text: self.run_script(operands[0], text, verb, operands[1:]))

    def wrapper(self, verb: str, args: list[str], stdin: str | None) -> None:
        """A command that runs another: skip its own options (with their values, attached or not) to
        the command. `env -C dir`, `env -S string`, `env -i`, `env -u NAME`, `sudo -D dir` and env's
        NAME=VALUE are followed."""
        rest = list(args)
        values = WRAPPER_VALUES.get(verb, set())
        chdir_opts = WRAPPER_CHDIR.get(verb, set())
        chdir, split, env, unset, clear = None, None, {}, [], False
        while rest:
            a = rest[0]
            name, eq, val = a.partition("=")
            if a == "--":
                rest = rest[1:]
                break
            if verb == "env" and a in {"-", "-i", "--ignore-environment"}:
                clear = True
                rest = rest[1:]
                continue
            if re.fullmatch(r"-[A-Za-z]{2,}.*", a) or (len(a) > 2 and a[:2] in values and not a.startswith("--")):
                # A cluster of short options (`-i0`), or one with its value attached (`-C..`, `-n10`,
                # `-S'cmd'`): split it into the option and its value.
                k = 1
                while k < len(a) and "-" + a[k] not in values:
                    if verb == "env" and a[k] == "i":
                        clear = True
                    k += 1
                if k < len(a):
                    opt, att = "-" + a[k], a[k + 1:]
                    rest = [opt, att, *rest[1:]] if att else [opt, *rest[1:]]
                else:
                    rest = rest[1:]
                continue
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
                elif verb == "env" and a in {"-u", "--unset"}:
                    unset.append(rest[1])
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
        if verb in {"env", "sudo"} and (chdir is not None or env or unset or clear):
            # The command runs in its own process, with env's environment (`-i`: only the
            # assignments): the directory change does not outlast it.
            with self.child():
                if clear:
                    self.vars, self.exports, self.inherit, self.func_exports = {}, {}, False, set()
                for name in unset:
                    self.vars[name] = ""
                    self.exports[name] = False
                for name, value in env.items():
                    self.vars[name] = value
                    self.exports[name] = True
                if chdir is not None:
                    self.chdir(chdir)
                if rest:
                    self.command(rest, stdin)
            return
        if rest:
            self.command(rest, None if verb == "xargs" else stdin)


def _shell(command: str, workdir: Path, files: dict | None = None) -> _Shell:
    """Read the command twice: the first pass, taking every cd as one that may have failed, finds
    the directories the command makes wherever it may be (see `_Shell.later`). `files`: what earlier
    calls wrote, by path (see `_Shell.files`), updated with what this command writes."""
    files = {} if files is None else files
    first = _Shell(workdir)
    first.doubt = True
    first.files = dict(files)
    first.run(command)
    shell = _Shell(workdir)
    shell.later = first.made_ever
    shell.wrote_later = first.wrote_ever
    shell.files = dict(files)
    shell.run(command)
    files.clear()
    files.update(shell.files)
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
        # The query, and the page it opened (an open_page action has a URL and may have no query).
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        yield "web_search", {"query": item.get("query", ""),
                             **({"url": str(action["url"])} if action.get("url") else {})}
    elif kind == "collab_tool_call":
        yield "collab", item


def check_call(tool: str, inp: dict, workdir: Path, roots: list[Path], files: dict | None = None) -> tuple[str, str]:
    """('web' | 'violation' | 'suspect' | 'local' | 'other', reason) for one tool call. `files`: what
    earlier calls in the transcript wrote, by path, so that a script written by one call and run by
    a later one is read as it was written; updated with what this call writes."""
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
        shell = _shell(inp.get("command", ""), workdir, files)
        paths, searches, notes, weak = shell.paths, shell.searches, shell.notes, shell.code_paths
        # Paths and searches from where the shell would be had a cd to a missing directory failed.
        alt, alt_searches = shell.alt_paths, shell.alt_searches
        unknown = shell.unknown_paths
    elif tool in {"Read", "Edit", "Write", "NotebookEdit", "LS"}:
        p = _resolve(str(inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""), workdir,
                     bare=True)
        paths = [p] if p else []
        if p is not None and files is not None:
            if tool == "Write" and isinstance(inp.get("content"), str):
                files[p] = (inp["content"],)
            elif tool == "Edit" and p in files and isinstance(inp.get("old_string"), str):
                new = str(inp.get("new_string") or "")
                files[p] = tuple(None if a is None else a.replace(inp["old_string"], new, -1 if inp.get("replace_all") else 1)
                                 for a in files[p])
            elif tool in {"Edit", "NotebookEdit"}:
                files.pop(p, None)  # changed in a way the audit does not follow: read from disk
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
    files: dict[Path, tuple] = {}  # what the run's calls wrote so far, by path (see `_Shell.files`)
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
            verdict, why = check_call(tool, inp, work, roots, files)
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
