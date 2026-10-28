"""Check that each forecaster worked independently.

The forecasters run on machines that also hold earlier forecasts of these questions, other runs'
answers and the operator's notes. The prompt forbids reading local files; this audit reads each run's
native transcript (Claude stream-json or Codex JSONL) and checks every tool call. It guards against
accidental and casual reads; a forecaster set on hiding one could make it look like a call the model
misreads, and then only the reader of the suspect calls stands in the way.

A shell call counts as local, or web, only inside the subset whose reads `exact` knows from the
command's text (`check_call`); within its assumptions such a call reads nothing outside the run's
work directory but what the tools load to run and the ignore files rg and ugrep consult, and any
other shell call is suspect. The rest of this module models the shells for every call: it finds the
reads that exclude a run and the reasons a call is suspect. The model is not exact. What follows is
what it models; of the round-11 review's inputs, each a read in some shell (ROUND11 in
tests/test_audit_exact.py), it still took 64 of 97 as local when the subset came.

Each shell command is parsed with tree-sitter's bash grammar, so quoting, here-documents, subshells,
command substitutions, pipelines, loops, functions and redirections are read much as the shell
reads them (`cat <file` reads `file`; a quoted `';'` is an argument, and the lines of a here-document fed to
`cat` are data). The grammar misreads `!` before a compound command (`! { ...; }`, `! if ...`), a
line that starts with a backslash, and a here-document line with blanks around its delimiter
(` EOF`, which the shells take as more of the body); the audit mends those before it reads them,
and any other command it cannot fully read is suspect. It also splits an unquoted `$a$b$c/x` into
two words, which the audit does not see.

The working directory is tracked as the set of places the shell could be, each with the last
command's exit status (`_World`):

- `cd`, `pushd` and `popd` move every place, and the directory stack is kept as each shell keeps
  it (`pushd +N` and `popd -N` rotate or drop entries, `dirs -c` clears it, zsh's `cd +N` takes an
  entry, bash's `pushd -n` adds one without moving). A `cd` to a directory missing at audit time
  (often a scratch directory since deleted), or one the same command makes only later or removed
  earlier, may have worked or failed: the shell is then in either place. For a literal scratch
  directory the failed place is an alternative; an expansion-generated target keeps both as main
  places, since expansion can produce a filename rather than the intended directory.
  A `cd` to a file fails. `CDPATH` is followed where its value is known on every branch (zsh's
  `cdpath` array is not), `cd -` and `pushd -` go to `$OLDPWD`,
  and one before any `cd` in the command goes where the audit cannot follow.
- `&&`, `||`, `if`, `case` and loops run their parts only where the status allows. The audit knows
  the status of `true`, `false`, `:`, `cd`, `!`, tests of known strings and numbers (`[ a = b ]`,
  `[[ ... ]]`, `test`), file tests of things present at audit time, arithmetic (`(( ))`, `let`),
  literal `case` values, and commands that all but always succeed (`echo`, `mkdir -p`,
  assignments); after anything else, both ways may have run. Where the way was unknown, places
  reached only by the way not meant (the skipped side of `x && cd ..`) are alternatives too.
- A `for` loop over a list runs its body once per item and one over a glob once per match at audit
  time. Brace lists and ranges expand with their prefixes and suffixes; arrays keep each shell's
  scalar, list and length semantics ("${a[@]}" of an unset a is no word in bash, one empty word in
  zsh). `while`, `until` and C-style `for` loops run pass by pass while their condition allows.
  `break`, `continue` and `return`, with counts, leave the loops and functions they name. Passes
  are followed until the loop ends or repeats a state; after 12, variables still changing become
  unknown, and after 24 the audit stops following the directory.
- Arithmetic (`$(( ))`, `(( ))`, `let`, `declare -i`, C-style `for`) is evaluated where bash and zsh
  agree: they bind the shifts and bitwise operators differently, read a variable operand at
  different times (`a + (a = 2)`), and bash 3.2 also checks a skipped branch for division by zero;
  elsewhere the value is unknown.
- Words split into fields as each shell splits them: bash and sh split unquoted parameter and
  arithmetic expansions and command substitutions at `IFS`, zsh splits parameters with
  `SH_WORD_SPLIT` enabled; both drop unquoted expansions that leave nothing (`cd $empty` goes home).
  `read` splits its line at
  `IFS` (bash drops a trailing delimiter that zsh keeps), and bash 3.2 (macOS's /bin/bash) splits an
  unquoted here-string too, joining the fields with spaces. Where the shell is not named and the
  two differ, the command runs each way, or the input is unknown.
  Expansion options (`set -f`, `noglob`, zsh's option spellings and `emulate sh`) travel with each
  shell state through branches, functions and subshells; `emulate MODE -c command` runs the command
  in the current shell and then restores only the options. `${x:=word}` and `${x=word}` assign in the
  current shell, except in words a forked child expands (below), where the assignment is lost;
  failed `${x:?word}` and `${x?word}` expansions exit it, except in those words and in dash's
  here-documents, where only the command fails unless it is a special builtin (the audit follows
  both ways there; see below). An upper-case name the code never set
  may come from the environment: the audit follows `${NAME?}` on, with its value unknown.
  Bash expands a failed parameter's diagnostic word before exiting; native zsh prints its source.
  Brace expansions that duplicate substitutions with effects the audit cannot order are suspect.
- Subshells, command substitutions, pipeline stages, background jobs, `sh -c` and wrapped commands
  with their own directory (`env -C`, `sudo -D`) leave the places after them unchanged, with two
  exceptions in zsh: it runs a pipeline's last stage in the current shell (`x | cd d`,
  `x | while read d; do cd "$d"; done`), as bash does after `shopt -s lastpipe`, and of an and-or
  list ending in `&` it runs only the last pipeline in the background (`cd a && make &` leaves zsh
  in a). The audit follows the shell a command names (`zsh -c`, `bash -c`); where none is named,
  or the shell is unsupported, it keeps the places either way would leave.
- Functions run in the calling shell with their arguments as positional parameters and their
  `local` variables; aliases are followed. Variables, `read` from a known input (`while read` loops
  line by line), `set --`, `shift`, `unset`, and positional parameters for `sh -c CODE NAME ARGS`,
  `sh -s ARGS` and shell code on standard input are expanded, and `$PWD` is the directory of each
  place. A new shell (`sh -c`, a script) starts with the exported variables only (`export`,
  `export -n`, `set -a`, a command's own assignments, `env -i` and `env -u` all count) and bash's
  exported functions, resets `IFS` and starts a fresh directory stack at startup. Bash and sh
  import supported options from exported `SHELLOPTS`; zsh initializes its own options.
  Unassigned local declarations follow the
  shell's rules (bash's local `IFS` starts unset, zsh's starts empty). A variable that branches may
  each have set differently has each of their values (a local that only some of them declared
  goes back at the return only there), and a function or alias they may each have defined
  differently, or not at all, runs as each; one a branch never set is unset there. Assignments
  before a command go back after it, except where the shell keeps them: sh and dash after a
  special builtin, sh after a function, zsh after a bare `exec`.
- Integer variables (bash's and zsh's `typeset -i`, zsh's `integer`, and in native zsh a variable
  an arithmetic assignment creates) take every value as arithmetic: an assignment, before a
  command in zsh, `+=`, read, for and a declaration's value. Where the audit cannot evaluate the
  expression it follows both the error (bash and sh exit, zsh ends the eval or the shell) and the
  write. zsh shows an integer given a base in that base, and a variable with a padding or case
  attribute (-L, -R, -Z, -l, -u) changed: those values are unknown. A declaration's word that is
  not a name fails it in bash (the rest still count), ends dash, and ends zsh's eval or shell;
  zsh takes a number right after an option that takes one, and digits in an option word only
  there. dash has no `[[`, `let`, `source`, `pushd` and the like, which fail there, and its
  `((x))` is a subshell running x.
- What commands print is followed as one text, a choice of texts (where branches or the shells
  differ) or unknown, in order through groups, functions, loops and branches: `echo` and `printf`
  with each shell's options and escapes, `pwd`, `dirname`, `basename`, `cat` of a file written
  earlier or in the work directory, here-documents (the body, expanded as a double-quoted string
  is unless the delimiter is quoted, though a `)` in a comment or a `case` pattern ends a `$(...)`
  in it early), `<(code)` (a name that reads as what the code prints), and
  declarations that list. Output redirected to a file
  becomes its text (of the last of several files, the earlier ones left empty even where standard
  error was copied there; zsh's MULTIOS writes it to each); sent to
  standard error, `/dev/null` or another descriptor, it is gone, except that zsh's MULTIOS (as it
  stands when the redirections are made) also sends a redirected pipeline stage down the pipe;
  what such a stage's files then hold is unknown (zsh's copier may end at the pipe first).
  Standard input given more than once reads the last (bash, sh, dash) or, under zsh's MULTIOS, each
  in turn, after the pipe where the command is a pipeline stage fed by one (`echo in | cat < f`).
  `exec`'s redirections, `2>&1` among them, hold for the rest of the shell; the model drops one
  made as the last command of `&&` and keeps one that failed, where the shells do the reverse.
  A duplication or close
  acts on the descriptor it names, whichever way its arrow points (`1<&-` closes standard output).
  On a closed standard output (`>&-`) bash 3.2 keeps what a builtin wrote (of printf, the first
  pass of its format, where the write fails; bash keeps more where a pass does not end in a
  newline, which the model misses) and writes it with its next builtin write or at exit;
  dash and zsh drop it. bash's and dash's `echo`, `printf`, `pwd` and `type` fail there where
  zsh's succeed; another command's status is then unknown. A here-string feeds its word and a
  newline. Where standard error may be standard output (`2>&1`),
  a command that may print a diagnostic makes the output from there unknown, and so does standard
  error copied before standard output moves (`2>&1 >f`), and any command under `set -x` or `set -v`
  (the shell writes the command, or the code bash's eval reads, to its standard error).
- `set` follows each shell's letters (SET_LETTERS): bash and dash give each `o` the next word,
  zsh the rest of the cluster where letters follow it (`set -ou pipefail`), and where they read
  the words differently the audit follows each. bash checks the letters before each word's `o`
  first and, at one it lacks, changes nothing and fails (sh exits, except where `guarding`
  holds); at a later letter or option name it lacks, bash and sh keep what came before and fail.
  dash exits and zsh ends the eval or the shell, after the letters before it. Under `set -e` a command that may fail, outside the places the
  shells ignore -e, and under `set -u` a parameter that may be unset (quoted or not), may end the
  shell, as `exec CMD` does; the audit follows that ending and goes on. In an external command's
  or a subshell's redirections, which bash and zsh expand in the child they fork, such a parameter
  ends only the child, and the command fails; so does one in an external command's prefix
  assignment in zsh. dash expands redirections in the shell, a subshell's here-document apart, but
  fails only the command at a here-document for any command but a special builtin (measured). An
  option the audit does
  not follow that could change what the code reads, prints or where it runs (noclobber, keyword,
  physical, globdots and the like) makes the call suspect.
- Writes to a readonly variable follow each shell, as measured on macOS's bash 3.2, sh and dash
  and zsh 5.9: bash fails a declaration, `unset`, `for` and `read` and goes on, skips an
  assignment before a command and runs the command, and at a plain assignment drops the rest of
  the line it is on (of the program, `eval` string or sourced file, which it reads a line at a
  time; a function's locals go back) and goes on with the next, status 1, or ends the subshell
  or command substitution it is in; bash's POSIX mode (`sh`) and dash end the shell at most of these,
  but sh's `readonly` and `export` only fail before `&&` or `||`, in a condition and after `!`
  (and in the functions, groups and subshells run there), outside an eval, a sourced file and a
  command substitution; zsh ends the eval it is in, else the shell (under POSIX_BUILTINS, as
  `emulate sh` sets it, the shell at `readonly` and `export`), except where a declaration in a
  function makes a new local (zsh's `readonly` there is local unless POSIX_BUILTINS is set), and
  fails an external command after a readonly assignment without running it. Arithmetic,
  `printf -v` and `getopts` follow the READONLY_* tables. `command` and `builtin` keep a
  builtin's own error from ending bash's POSIX mode, and dash's `command` fails where the code it
  runs would end the shell; zsh's `command` runs only a file (a builtin there runs as a child
  process) unless `emulate sh` set POSIX_BUILTINS. `setopt`, `emulate` and `shopt` fail in the
  shells that lack them, and at an option name the shell lacks (the model takes some of zsh's
  aliases, `dotglob` among them, for names zsh lacks, and `nonoglob` for one it has); at `set -o` with an option it
  lacks, bash fails, dash exits and zsh ends the eval or the shell as at `readonly`.
- An EXIT trap's code runs where the shell or subshell ends, in each way it may end (an exit
  included). Code that other traps run where their signal or event comes, and zsh's EXIT trap set
  in a function, which runs at the function's return, is followed once for the paths it names, and
  the operator is told the audit does not follow where it runs.
- bash's POSIX mode (`sh`) and dash reject a line with a process substitution as they read it,
  before any of it runs: dash anywhere in the line, sh where `<(` or `>(` starts a word outside a
  command substitution (glued to text before it, or as an assignment's value, it is plain text).
  dash rejects a line with a here-string or an array value (`p=(1 2)`) too, anywhere in it.
  dash then exits; sh ends the eval or sourced file the line is in, else the shell. The line's
  paths still count, as alternatives.
- A script run by path, by a shell (`bash s.sh`, `. s.sh`) or by an interpreter is read as the
  code it holds: the text an earlier tool call wrote there (Write, Edit, a here-document, `tee`, a
  redirection), else the file at audit time if it is in the work directory or a temporary directory.
- Past 64 places the audit stops following the directory.

Local paths are then resolved from every place:

- `~`, `~+`, `~-`, directory-stack tildes (`~N`, `~+N`, `~-N`), `$HOME`, `$PWD` and the variables
  above expand in every possible shell state, and substitutions such as
  `$(cd .. && pwd)` are worked out; a path with a part the audit cannot work out is matched as a
  pattern;
  bash's directory tildes follow explicit PWD/OLDPWD assignments, while zsh uses its internal
  directory state; a leading `//` is the root, as on macOS, but after a `cd` there bash, sh and
  dash keep the `//` in `$PWD` and in what `pwd` prints, which the audit then takes as unknown;
- nested `sh -c`, `eval`, wrappers (`xargs`, `env`, `timeout` and the like, with their options'
  values) and shell code fed to a shell through a here-document or a pipe are parsed in turn;
- a command's own directory option (`git -C`, `make -C`, `tar -C`, `uv --directory`, ...) is a further
  base for its relative paths;
- interpreter code (`python -c`, `node -e`, awk and jq programs, sed scripts, code on standard input)
  is scanned for path-like strings and file URLs, never taken as a path itself, and a literal
  directory change in it (`os.chdir('x')`) moves the base for the paths after it; options are read
  with each interpreter's own syntax (clusters such as `-uc'...'`, attached values such as
  `perl -i.bak`), and jq's `--args` are strings. With a program supplied as an argument or script,
  standard input is data: path-shaped input is local when the program only prints or transforms
  it, suspect when it may supply filenames, and a read when the audit can tell it opens them.
  Awk `-v` values count only where they can reach file operations, commands or `ARGV`; literal
  `system()` commands are audited as shell code independently of unrelated values. Known input
  follows child-shell read loops, executable interpreter scripts and awk commands; print pipes
  supply their printed values, and unresolved shared input consumption remains suspect;
- running a file by path counts as reading it, and `file://` URLs count as paths;
- globs are expanded against the real filesystem at audit time, retaining protected-pattern
  checks when their matches are absent.

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
  a protected place, a path with an unknown part that could, a file operand the audit cannot work out
  at all, filenames (xargs, parallel) or code (a shell, an interpreter, `. /dev/stdin`) taken from
  input the audit does not know, trap code that runs where the audit does not follow, a command the
  parser cannot fully read,
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

import ast
import fnmatch
import functools
import glob as globlib
import itertools
import json
import math
import os
import re
import shlex
from contextlib import contextmanager, nullcontext
from fractions import Fraction
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

import tree_sitter_bash
from tree_sitter import Language, Parser

from . import exact

HOME = Path.home()
# The start of the reason for a shell call that is suspect only because it lies outside `exact`'s subset.
EXACT_REASON = "shell code the audit does not read exactly"
URL = re.compile(r"https?://[^\s'\"<>)`]+")
# Text a URL parser may read as an http(s) URL: the scheme in any case, then any number of slashes
# or backslashes (the WHATWG parser, as in Node's fetch, reads `http:host`, `HTTP:/\\host` and
# `http://host` alike).
URLISH = re.compile(r"(?i)\bhttps?:[/\\]*[^\s'\"<>)`]+")
# Text, outside URLs, that names a protected place.
PROTECTED_TEXT = re.compile(
    r"dc-i86-llm-forecast|dc-ballot|\.subfleet|\.claude\b|\.codex\b|chief-of-staff|\.brier|"
    r"(?:~|\$\{?HOME\}?|" + re.escape(str(HOME)) + r")/reviews\b|"
    r"MEMORY\.md|/memory/|/predictions/|/private/tmp/claude-|/tmp/claude-",
    re.I,
)
TERMS = re.compile(r"foie|forecast|i-?86|initiative.?86|ban_status|yes_share|response\.(?:md|json)", re.I)
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Path-like strings inside code (python -c '...', node -e '...'), quoted or after an opening bracket.
EMBEDDED_PATH = re.compile(r"""(?:^|(?<=['"\s(=,:\[]))((?:~/|\.\./|\./|/)[^\s'"(),;\]]*)""")
FILE_URL = re.compile(r"""file://(?:localhost)?(/[^\s'"(),;\]]*)""", re.I)
# A quoted string without spaces inside code, and a file name with an extension.
QUOTED = re.compile(r"""(['"])([^'"\s]+)\1""")
FILE_NAME = re.compile(r"[\w.-]+\.[A-Za-z0-9]{1,6}")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
# How each shell runs code where shells differ (see `_Shell.dialect`); unnamed and unsupported
# shells retain either behavior. On this host /bin/sh is bash in POSIX mode.
DIALECTS = {"zsh": "zsh", "bash": "posix", "sh": "posix", "dash": "posix"}
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
# Commands that all but always succeed (and `mkdir -p`), so `echo x && cd y` certainly runs the cd.
SUCCEEDS = {"true", ":", "echo", "printf", "pwd", "export", "declare", "typeset", "local", "readonly", "set",
            "unset", "shopt"}
# Commands the audit follows that change the shell they run in. As a pipeline's last stage they
# matter in zsh, which runs that stage in the current shell (see `_Shell.pipeline`); so do function
# and alias calls and compound commands.
STATEFUL = {"cd", "chdir", "pushd", "popd", "read", "export", "declare", "typeset", "local", "readonly", "alias",
            "eval", "source", ".", "exit", "shopt", "command", "builtin", "exec", "emulate", "setopt", "unsetopt",
            "set", "unset", "shift", "let", "getopts", "unalias", "unfunction", "dirs", "mapfile", "readarray",
            "integer", "float", "trap", "enable", "disable", "zparseopts", "vared", "return", "break", "continue",
            "hash", "autoload", "functions", "zmodload", "noglob", "umask"}
STDIN_FILES = {"/dev/stdin", "/dev/fd/0"}  # files that are standard input
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
# Keep awk strings separate from identifiers: a literal system("true") does not use a -v value.
AWK_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|\#[^\n]*|[A-Za-z_][A-Za-z_0-9]*|[0-9]+(?:\.[0-9]+)?|==|!=|<=|>=|&&|\|\||\+\+|--|[+*/%^\-]=|>>|\|&|[^\s]')
AWKS = {"awk", "gawk", "mawk", "nawk"}
# A literal directory change inside interpreter code: os.chdir('x'), process.chdir('x'),
# Dir.chdir('x'), chdir('x') in Perl or PHP, setwd('x') in R.
CODE_CHDIR = re.compile(r"""(?:\b(?:os\.|process\.|Dir\.)?chdir|\bsetwd)\s*\(?\s*(['"])([^'"]+)\1""")
WEB_TOOLS = {"WebSearch", "WebFetch"}
# Tools that name files, checked by the paths they name (and where those lead through links).
FILE_TOOLS = {"Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "LS", "Grep", "Glob", "file_read", "file_change"}
# Tools that read nothing: the task list, plan mode, a background Bash call's output and stopping
# it (the call itself is audited; Claude Code 2.1.308 names these TaskOutput and TaskStop and keeps
# BashOutput, KillShell and KillBash as aliases) and loading the schemas of deferred tools. Any
# other tool is suspect.
QUIET_TOOLS = {"TodoWrite", "TodoRead", "BashOutput", "TaskOutput", "KillShell", "KillBash", "TaskStop",
               "ExitPlanMode", "ToolSearch"}
# Claude Code's tools for MCP servers' resources (2.1.308's names and the aliases its table maps to
# them), which reach whatever the server reaches, as the servers' own tools (`mcp__server__tool`) do.
MCP_TOOLS = {"ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool", "ListMcpResources",
             "ReadMcpResource", "ReadMcpResourceDir"}
# Codex items that are not tool calls. An item of any other type is suspect.
CODEX_NOT_CALLS = {"agent_message", "reasoning", "todo_list", "error"}
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
# LIST, just inside an unquoted expansion's mark, says it is $@, $* or an array's [@] or [*].
Q_OPEN, Q_CLOSE, FIELD, FIELD_CMD, FIELD_END = "\x11", "\x12", "\x0e", "\x10", "\x0f"
ARRAY_OPEN, ARRAY_CLOSE, UNSET, TILDE, LIST = "\x13", "\x14", "\x15", "\x16", "\x17"
_UNMARK = str.maketrans("", "", Q_OPEN + Q_CLOSE + FIELD + FIELD_CMD + FIELD_END + LIST)
# Directories where a script a command runs may be read at audit time, besides the work directory.
TEMP_DIRS = (Path("/tmp"), Path("/private/tmp"), Path("/var/folders"), Path("/private/var/folders"))
# A command's exit status as far as the audit can tell, in each place the shell could be.
OK, FAILED, MAYBE, EXITED = "ok", "failed", "maybe", "exited"
MAX_WORLDS = 64
# test's unary operators in bash and zsh.
_TEST_UNARY = {"-" + c for c in "abcdefghknoprstuvwxzGLNORS"}
# Passes of a loop the audit follows before it stops following the directory.
MAX_PASSES = 12
# Statements after which `set -e` may end the shell (see `_Shell.errexit_end`).
ERREXIT_STATEMENTS = {"command", "redirected_statement", "pipeline", "subshell", "declaration_command", "variable_assignment", "variable_assignments", "test_command",
                      "unset_command"}
STATEMENTS = {
    "command", "redirected_statement", "pipeline", "list", "subshell", "compound_statement", "if_statement",
    "elif_clause", "else_clause", "while_statement", "for_statement", "c_style_for_statement",
    "case_statement", "case_item", "function_definition", "negated_command", "declaration_command",
    "variable_assignment", "variable_assignments", "test_command", "unset_command", "do_group", "ERROR",
}
REDIRECTS = {"file_redirect", "heredoc_redirect", "herestring_redirect"}
# Option names `set -o` takes. zsh 5.9's, as its `set -o` lists them (an option on by default
# shows as noNAME), ignoring case and underscores; bash 3.2's and dash's exactly. zsh and dash exit
# on another name; bash fails and goes on.
ZSH_OPTIONS = frozenset("""
    aliasfuncdef allexport alwaystoend appendcreate autocd autocontinue autonamedirs autopushd
    autoresume bashautolist bashrematch braceccl bsdecho casepaths cbases cdablevars cdsilent
    chasedots chaselinks clobberempty combiningchars completealiases completeinword continueonerror
    correct correctall cprecedences cshjunkiehistory cshjunkieloops cshjunkiequotes cshnullcmd
    cshnullglob dvorak emacs errexit errreturn extendedglob extendedhistory forcefloat globassign
    globcomplete globdots globstarshort globsubst hashexecutablesonly histallowclobber
    histexpiredupsfirst histfcntllock histfindnodups histignorealldups histignoredups
    histignorespace histlexwords histnofunctions histnostore histreduceblanks histsavenodups
    histsubstpattern histverify ignorebraces ignoreclosebraces ignoreeof incappendhistory
    incappendhistorytime interactive interactivecomments ksharrays kshautoload kshglob
    kshoptionprint kshtypeset kshzerosubscript listpacked listrowsfirst localloops localoptions
    localpatterns localtraps login longlistjobs magicequalsubst mailwarning markdirs menucomplete
    monitor noaliases noalwayslastprompt noappendhistory noautolist noautomenu noautoparamkeys
    noautoparamslash noautoremoveslash nobadpattern nobanghist nobareglobqual nobeep nobgnice
    nocaseglob nocasematch nocheckjobs nocheckrunningjobs noclobber nodebugbeforecmd noequals
    noevallineno noexec noflowcontrol nofunctionargzero noglob noglobalexport noglobalrcs nohashcmds
    nohashdirs nohashlistall nohistbeep nohistsavebycopy nohup nolistambiguous nolistbeep
    nolisttypes nomultibyte nomultifuncdef nomultios nonomatch nonotify nopromptcr nopromptpercent
    nopromptsp norcs noshortloops nounset nullglob numericglobsort octalzeroes overstrike pathdirs
    pathscript pipefail posixaliases posixargzero posixbuiltins posixcd posixidentifiers posixjobs
    posixstrings posixtraps printeightbit printexitvalue privileged promptbang promptsubst
    pushdignoredups pushdminus pushdsilent pushdtohome rcexpandparam rcquotes recexact rematchpcre
    restricted rmstarsilent rmstarwait sharehistory shfileexpansion shglob shinstdin shnullcmd
    shoptionletters shortrepeat shwordsplit singlecommand singlelinezle sourcetrace sunkeyboardhack
    transientrprompt trapsasync typesetsilent typesettounset verbose vi warncreateglobal
    warnnestedvar xtrace zle
""".split())
ZSH_OPTIONS |= {n[2:] for n in ZSH_OPTIONS if n.startswith("no")}
BASH_OPTIONS = frozenset("""allexport braceexpand emacs errexit errtrace functrace hashall histexpand history
    ignoreeof interactive-comments keyword monitor noclobber noexec noglob nolog notify nounset onecmd physical
    pipefail posix privileged verbose vi xtrace""".split())
DASH_OPTIONS = frozenset("""errexit noglob ignoreeof interactive monitor noexec stdin xtrace verbose vi emacs
    noclobber allexport notify nounset nolog debug""".split())
# Options that change nothing the audit follows in a shell running a script or `-c` code: job
# control, line editing, history, command hashing, notification, startup files. pipefail too, as
# the audit takes every pipeline's status as unknown, and the trap options, as traps other than
# EXIT already make the call suspect (see `trap`). Spelled as `option` reads them.
HARMLESS_OPTIONS = frozenset("""emacs vi monitor notify hashall history histexpand ignoreeof interactive-comments
    nolog debug errtrace functrace pipefail trapsasync beep bgnice autolist rmstarsilent autocd banghist
    sunkeyboardhack singlelinezle longlistjobs recexact mailwarning promptcr autoresume listtypes menucomplete
    globalrcs rcs histignorespace histignoredups interactivecomments login""".split())
# The options `set`'s letters name, as each shell takes them: bash 3.2 (also as sh), dash, and zsh
# 5.9 natively and under SH_OPTION_LETTERS (`emulate sh`), measured on macOS; spelled as `option`
# reads them. "" is a letter whose effect the audit does not follow (zsh's -s sorts the positional
# parameters, -A sets an array). A letter missing is one the shell lacks; zsh cannot change -i, -m,
# -t or -Z in a running shell, an error as a missing letter is. `o` takes an option's name.
SET_LETTERS = {
    "bash": dict(a="allexport", b="notify", e="errexit", f="noglob", h="hashall", i="", k="keyword", m="monitor",
                 n="noexec", p="privileged", r="restricted", t="onecmd", u="nounset", v="verbose", x="xtrace",
                 B="braceexpand", C="noclobber", E="errtrace", H="histexpand", I="", P="physical", T="functrace"),
    "dash": dict(a="allexport", b="notify", e="errexit", f="noglob", i="", m="monitor", s="", u="nounset",
                 v="verbose", x="xtrace", C="noclobber", E="emacs", I="ignoreeof", V="vi"),
    "zsh": {"0": "correct", "1": "printexitvalue", "2": "nobadpattern", "3": "nonomatch", "4": "globdots",
            "5": "notify", "6": "bgnice", "7": "ignoreeof", "8": "markdirs", "9": "autolist", "A": "",
            "B": "nobeep", "C": "noclobber", "D": "pushdtohome", "E": "pushdsilent", "F": "noglob", "G": "nullglob",
            "H": "rmstarsilent", "I": "ignorebraces", "J": "autocd", "K": "nobanghist", "L": "sunkeyboardhack",
            "M": "singlelinezle", "N": "autopushd", "O": "correctall", "P": "rcexpandparam", "Q": "pathdirs",
            "R": "longlistjobs", "S": "recexact", "T": "cdablevars", "U": "mailwarning", "V": "nopromptcr",
            "W": "autoresume", "X": "listtypes", "Y": "menucomplete", "a": "allexport", "d": "noglobalrcs",
            "e": "errexit", "f": "norcs", "g": "histignorespace", "h": "histignoredups", "k": "interactivecomments",
            "l": "login", "n": "noexec", "p": "privileged", "r": "restricted", "s": "", "u": "nounset",
            "v": "verbose", "w": "chaselinks", "x": "xtrace", "y": "shwordsplit"},
    "zshsh": dict(a="allexport", b="notify", e="errexit", f="noglob", l="login", n="noexec", p="privileged",
                  r="restricted", s="", u="nounset", v="verbose", x="xtrace", C="noclobber", T="trapsasync",
                  X="markdirs"),
}
# bash 3.2's shopt options; later versions have more.
BASH_SHOPTS = frozenset("""cdable_vars cdspell checkhash checkwinsize cmdhist compat31 dotglob execfail
    expand_aliases extdebug extglob extquote failglob force_fignore gnu_errfmt histappend histreedit histverify
    hostcomplete huponexit interactive_comments lithist login_shell mailwarn no_empty_cmd_completion nocaseglob
    nocasematch nullglob progcomp promptvars restricted_shell shift_verbose sourcepath xpg_echo""".split())
# zsh 5.9's builtins (`zsh -f`), and POSIX's special builtins (bash's in its POSIX mode): what an
# assignment to a readonly variable before a command does depends on them.
ZSH_BUILTINS = frozenset(""". : [ alias autoload bg bindkey break builtin bye cd chdir command compadd
    comparguments compcall compctl compdescribe compfiles compgroups compquote compset comptags comptry
    compvalues continue declare dirs disable disown echo echotc echoti emulate enable eval exec exit export false
    fc fg float functions getln getopts hash history integer jobs kill let limit local log logout noglob popd
    print printf private pushd pushln pwd r read readonly rehash return sched set setopt shift source suspend
    test times trap true ttyctl type typeset ulimit umask unalias unfunction unhash unlimit unset unsetopt vared
    wait whence where which zcompile zformat zle zmodload zparseopts zregexparse zstyle""".split())
SPECIAL_BUILTINS = frozenset(". : break continue eval exec exit export readonly return set shift times trap unset".split())
# bash 3.2's builtins (`compgen -b`), and those of zsh's that macOS also has as a file in /bin or
# /usr/bin (most of them a script that runs the builtin in a new sh), which zsh's `command` runs.
BASH_BUILTINS = frozenset(""". : [ alias bg bind break builtin caller cd command compgen complete continue declare
    dirs disown echo enable eval exec exit export false fc fg getopts hash help history jobs kill let local logout
    popd printf pushd pwd read readonly return set shift shopt source suspend test times trap true type typeset
    ulimit umask unalias unset wait""".split())
BUILTIN_FILES = frozenset("[ alias bg cd command echo false fc fg getopts hash jobs kill printf pwd read test true "
                          "type ulimit umask unalias wait which".split())
# What each shell does at a write to a readonly variable, by the kind of write: "drop" (end the
# line it is on, of the program, `eval` string or sourced file, and go on with the next, status 1;
# in a subshell, end that), "abort" (end what the nearest eval or `.` runs, which then fails, or
# else exit), "exit", "fail" (skip the write, fail, go on), "skip" (skip the write, go on) or
# "allow" (no error). "bash" is bash 3.2 out of POSIX mode, "posix" in it (as /bin/sh). Measured on
# macOS's bash 3.2, sh, dash and zsh 5.9.
READONLY_ASSIGN = {"bash": "drop", "posix": "exit", "dash": "exit", "zsh": "abort"}  # z=1
READONLY_FOR = {"bash": "fail", "posix": "exit", "dash": "exit", "zsh": "abort"}  # for z in ...
READONLY_UNSET = {"bash": "fail", "posix": "fail", "dash": "exit", "zsh": "abort"}
READONLY_READ = {"bash": "fail", "posix": "fail", "dash": "fail", "zsh": "abort"}
READONLY_GETOPTS = {"bash": "fail", "posix": "fail", "dash": "fail", "zsh": "abort"}  # getopts a z
READONLY_PRINTF = {"bash": "skip", "posix": "skip", "dash": "fail", "zsh": "abort"}  # printf -v z (dash: no -v)
# Arithmetic: in $((...)) and a C-style for, and in ((...)) and let, which then fail (dash has no
# let and reads ((...)) as nested subshells, whose assignment fails it). "go": bash goes on.
READONLY_ARITH = {"expansion": {"bash": "go", "posix": "go", "dash": "exit", "zsh": "abort"},
                  "command": {"bash": "go", "posix": "go", "dash": "go", "zsh": "go"}}
READONLY = "\0readonly:"  # the variable that marks a variable readonly ("1"; in some branches, a choice)
# The variable that marks an integer variable, whose assignments are arithmetic: "1", or "u" where
# zsh shows its value in a way the audit does not follow (in a base, `16#10`, or as a float); in
# some branches, a choice. `declare -i` and zsh's `integer` make one, and so does native zsh's
# arithmetic assignment to a variable that does not exist (see `_Shell.created`).
INTEGER = "\0integer:"
# An integer variable given a text that is not an expression the shell can evaluate: bash exits (a
# subshell or command substitution ends), zsh ends the eval or `.` it is in, else the shell. The
# same at a plain assignment, `+=`, read, for, select, printf -v, getopts and a declaration's value;
# measured on macOS's bash 3.2, sh and zsh 5.9 (dash has no integer variables).
INTEGER_ASSIGN = {"bash": "exit", "posix": "exit", "dash": "exit", "zsh": "abort"}
_BASED = re.compile(r"0[xX]|#|\[")  # base notation, in which zsh then shows the integer it sets
# The variable that marks a zsh variable whose values zsh shows changed: padded to a width (-L, -R,
# -Z) or in one case (-l, -u). Its value names those of the letters it has, and every value the
# variable takes from then on is unknown: on the declaration, an assignment (before a command too),
# arithmetic, read and for (measured on zsh 5.9; bash 3.2 and dash have none of them).
SHOWN = "\0shown:"
SHOWN_LETTERS = frozenset("LRZlu")
# bash builtins dash lacks (some zsh has too): dash looks for a program of the name, which macOS
# does not have, and fails (127) without running anything (measured on macOS's dash). dash also has
# no `[[` or `((`: see `_visit`.
DASH_LACKS = frozenset("""let pushd popd dirs source caller disown enable help logout suspend bind history
    compgen complete""".split())
# Standard output closed (`>&-`), and sent to standard error where that may be standard output
# (`{ echo a >&2; } 2>&1`), as redirection targets.
CLOSED = "\x00closed"
MAYBE_OUT = "\x00stderr"
TANGLED = "\x00tangled"  # zsh's MULTIOS with a duplication or close among the targets


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


def _real(path: Path, workdir: Path) -> Path:
    """Where a path leads at audit time, through any links; spelled from the work area where it
    lies there, so that the checks against the work directory and its siblings apply to it."""
    from .runners import WORK

    real = Path(os.path.realpath(path))
    for base in (workdir, WORK):
        resolved = Path(os.path.realpath(base))
        if _under(real, resolved):
            return base / real.relative_to(resolved)
    return real


def _covers_protected(root: Path, roots: list[Path]) -> bool:
    """A search rooted here can reach a protected place or another run's work directory."""
    from .runners import WORK

    return any(_under(r, root) for r in roots) or _under(WORK, root)


def _mask_workdir(text: str, workdir: Path) -> str:
    """Replace the run's own work directory, but not a sibling that starts with the same name."""
    return re.sub(re.escape(str(workdir)) + r"(?=[/'\"\\\s]|$)", "<workdir>", text)


def _normpath(path) -> Path:
    """`path` without `.`, `..` or repeated slashes. POSIX lets a path that starts with exactly two
    slashes mean something else, so normpath keeps them; macOS reads it as `/`."""
    text = os.path.normpath(path)
    return Path("/" + text.lstrip("/") if text.startswith("//") else text)


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
    return _normpath(cwd / token)


def _multios_tangled(redirects: list) -> bool:
    """Whether a descriptor (standard output or error) is redirected more than once with a
    duplication or close among them, which zsh's MULTIOS joins in ways the audit does not follow
    (measured on zsh 5.9: `> f >&-` leaves f empty, `> f 1>&1` writes to f and to standard output,
    `2>&1 2>/dev/null` and `2>f 2>&1` send standard error to both)."""
    seen: dict[str, list[bool]] = {"1": [], "2": []}
    for r in redirects:
        if r.type != "file_redirect":
            continue
        op = "".join(_text(c) for c in r.children if not c.is_named)
        fd = next((_text(c) for c in r.named_children if c.type == "file_descriptor"), "")
        last = _text(r.named_children[-1]) if r.named_children else ""
        both = op in {"&>", "&>>"} or op == ">&" and fd == "" and not last.isdigit() and last != "-"
        dup = op in {">&-", "<&-"} or op in {">&", "<&"} and (last.isdigit() or last == "-")
        for which in ("1", "2") if both else (fd or ("1" if op.startswith(">") else "0"),):
            if which in seen:
                seen[which].append(dup)
    return any(len(dups) > 1 and any(dups) for dups in seen.values())


def _err_state(redirects: list, err: bool) -> bool:
    """Whether standard error goes where standard output goes after these redirections, given
    whether it did before (`err`): `2>&1` and `2>/dev/stdout` send it there, and `&>` and `>&`
    with a file send both to the file; any other redirection of descriptor 2 sends it elsewhere."""
    for r in redirects:
        if r.type != "file_redirect":
            continue
        op = "".join(_text(c) for c in r.children if not c.is_named)
        fd = next((_text(c) for c in r.named_children if c.type == "file_descriptor"), "")
        dest = [_text(c) for c in r.named_children if c.type != "file_descriptor"]
        target = dest[-1] if dest else ""
        if fd == "2" and op != "<":
            err = op in {">&", "<&", ">", ">>", ">|"} and target in {"1", "/dev/stdout", "/dev/fd/1"}
        elif fd == "" and (op in {"&>", "&>>"} or op == ">&" and not target.isdigit() and target != "-"):
            err = True
    return err


def _redirects(node) -> list:
    """A simple command's redirections, and those of the statement around it."""
    out = [c for c in node.named_children if c.type in REDIRECTS]
    if node.parent is not None and node.parent.type == "redirected_statement":
        out += [c for c in node.parent.named_children if c.type in REDIRECTS]
    return out


def _alt(text: str) -> tuple[str, bool]:
    """A text without ALT marks, and whether it had any."""
    return text.replace(ALT, ""), ALT in text


def _unmark(text: str) -> str:
    return text.translate(_UNMARK)


def _array_values(value: str) -> list[str] | None:
    """Arrays live in the variable table, so branches, functions and subshells preserve them."""
    if not value.startswith(ARRAY_OPEN) or not value.endswith(ARRAY_CLOSE):
        return None
    count, _, text = value[1:-1].partition(":")
    return text.split(SPLIT) if count != "0" else []


def _array(items: list[str]) -> str:
    return ARRAY_OPEN + str(len(items)) + ":" + SPLIT.join(items) + ARRAY_CLOSE


class _ReservedWord(str):
    """An unquoted word that zsh recognizes before expansion as a reserved word."""


class _LiteralWord(str):
    """A word whose wildcard characters are quoted, rather than pathname patterns."""


class _ExpandedWord(str):
    """A field produced by a parameter, arithmetic or command expansion."""


class _ExpandedLiteralWord(_ExpandedWord, _LiteralWord):
    """An expanded field whose wildcard characters are quoted."""


def _brace_words(word: str, limit: int = 128, bash: bool = False) -> list[str] | None:
    """Brace expansion on marked, still quoted words; None means the bounded model cannot follow it.

    Parameter values are expanded later, so braces supplied by a variable stay literal. Quoted
    braces and commas stay literal too. Nested lists, numeric/letter ranges and affixes compose.
    """
    quoted, field, stack, pairs = False, False, [], []
    for i, c in enumerate(word):
        if c == Q_OPEN:
            quoted = True
        elif c == Q_CLOSE:
            quoted = False
        elif c in (FIELD, FIELD_CMD):
            field = True
        elif c == FIELD_END:
            field = False
        elif not quoted and not field and c == "{":
            stack.append(i)
        elif not quoted and not field and c == "}" and stack:
            start = stack.pop()
            pairs.append((start, i))
    for start, end in sorted(pairs):
        body = word[start + 1:end]
        quoted, field, depth, cuts = False, False, 0, []
        for i, c in enumerate(body):
            if c == Q_OPEN:
                quoted = True
            elif c == Q_CLOSE:
                quoted = False
            elif c in (FIELD, FIELD_CMD):
                field = True
            elif c == FIELD_END:
                field = False
            elif not quoted and not field:
                depth += (c == "{") - (c == "}")
                if c == "," and depth == 0:
                    cuts.append(i)
        if cuts:
            bounds = [-1, *cuts, len(body)]
            items = [body[a + 1:b] for a, b in zip(bounds, bounds[1:])]
        else:
            m = re.fullmatch(r"(-?\d+|[a-zA-Z])\.\.(-?\d+|[a-zA-Z])(?:\.\.(-?\d+))?", body)
            if not m or m[1].isalpha() != m[2].isalpha():
                continue
            letters = m[1].isalpha()
            # macOS bash 3.2 has no increment syntax or zero-padding; zsh supports numeric
            # increments, but neither shell accepts increments on letter ranges.
            if m[3] is not None and (bash or letters):
                continue
            a, b = (ord(m[1]), ord(m[2])) if letters else (int(m[1]), int(m[2]))
            step = abs(int(m[3] or "1")) or 1
            step *= 1 if b >= a else -1
            if abs(b - a) // abs(step) + 1 > limit:
                return None
            width = max(len(m[1].lstrip("-")), len(m[2].lstrip("-")))
            padded = not bash and not letters and any(x.lstrip("-").startswith("0") and len(x.lstrip("-")) > 1 for x in (m[1], m[2]))
            items = [chr(n) if letters else (str(n).zfill(width + (n < 0)) if padded else str(n))
                     for n in range(a, b + (1 if step > 0 else -1), step)]
        out = []
        for item in items:
            expanded = _brace_words(word[:start] + item + word[end + 1:], limit, bash)
            if expanded is None or len(out) + len(expanded) > limit:
                return None
            out += expanded
        return out
    return [word]


def _fields(word: str, ifs: str | None, params: bool, literal: bool = False,
            bash: bool | None = None) -> list[str]:
    """The fields an expanded word, marked as `_Shell.value` marks it, becomes (POSIX 2.6.5, with
    the shells' differences). Unquoted expansions are split at IFS (None: unset, as space, tab and
    newline): IFS white space at the start or end of a field is dropped and runs of it separate
    fields; any other IFS character, with white space around it, ends a field, so two in a row make
    an empty one and one at the very end makes none. Command substitutions are split in every
    shell, parameter and arithmetic expansions only where `params` (sh and bash; zsh splits them
    only under SH_WORD_SPLIT), and unquoted literal text only where `literal` (bash 3.2's
    here-strings). A word made only of unquoted expansions that leave nothing becomes no field;
    quoted text makes one, but in bash an empty quoted part counts only in a word with nothing
    else in it. zsh (`bash=False`) also makes an empty last field after a final IFS character
    other than white space. Where parameters are split, an unquoted $@, $* or array is joined at
IFS's first character and split with the rest (with IFS empty its separators end a field and empty
elements drop); bash's lists also start with no empty field when they begin with IFS white space
and another IFS character. $@'s separators otherwise always end a field. Where IFS, or a part
    that would be split, is not known, the word stays one field (unknown, where IFS is)."""
    bash = params if bash is None else bash
    ifs = " \t\n" if ifs in (None, UNSET) else ifs
    white = {c for c in ifs if c in " \t\n"}
    chars: list[tuple[str | None, bool, bool]] = []  # (character or None for quoting, split, expanded)
    mode = None
    listing = first_listed = seen = False  # first_listed: the word's first character is from a LIST expansion
    for c in word:
        if c == Q_OPEN:
            mode = Q_OPEN
            chars.append((None, False, False))
        elif c in (FIELD, FIELD_CMD):
            mode = c
        elif c in (Q_CLOSE, FIELD_END):
            mode, listing = None, False
        elif c == LIST:
            listing = True
        else:
            if not seen:
                first_listed, seen = listing and mode == FIELD, True
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
    if bash and any(c for c, _, _ in chars):
        # In bash, a quoted empty part ('' or "") keeps the word only if nothing else is in it:
        # `''$y` with y=' ' is no word at all.
        chars = [x for x in chars if x[0] is not None]
    if params and ifs:
        # Where parameters are split (bash, sh, zsh under SH_WORD_SPLIT), an unquoted $@, $* or
        # array is joined at IFS's first character and the result split, so with IFS=: the empty
        # element of ('' MOCK) is an empty field. With IFS empty the elements stay apart and empty
        # ones drop, as below.
        chars = [(ifs[0], s, e) if c == SPLIT and s else (c, s, e) for c, s, e in chars]
        if bash and first_listed and chars and chars[0][1] and chars[0][0] in white:
            # bash 3.2's lists, unlike its scalars, start with no empty field when they begin
            # with IFS white space and another IFS character: IFS=': ' a=(' ' M) gives M alone.
            j = 0
            while j < len(chars) and chars[j][1] and chars[j][0] in white:
                j += 1
            if j < len(chars) and chars[j][1] and chars[j][0] in ifs:
                j += 1
                while j < len(chars) and chars[j][1] and chars[j][0] in white:
                    j += 1
                chars = chars[j:]
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
    elif hard and not bash:
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
    def hidden(text) -> bool:
        return any(expanded and (piece.startswith("$(") or piece.startswith("${") and hidden(piece[2:-1]))
                   for expanded, piece in _heredoc_parts(text))

    def substitutes(n) -> bool:
        # The grammar leaves backquotes inside ${...} as literal expansion text.
        return (n.type in {"command_substitution", "process_substitution"}
                or n.type == "expansion" and hidden(_text(n)[2:-1])
                or any(map(substitutes, n.children)))
    return MAYBE if substitutes(node) else OK


def _zsh_listed(value: str) -> str | None:
    """A value as zsh's `typeset NAME` lists it: bare, or single-quoted where it holds characters
    zsh quotes (None for those the audit has not checked: control and non-ASCII characters)."""
    if value == "":
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_./:+@,%!-]+", value):
        return value
    if re.fullmatch(r"[ -~]+", value):
        return "'" + value.replace("'", "'\\''") + "'"
    return None


def _declaration_takes(kind: str, keyword: str, flags: str) -> bool:
    """Whether a shell (see `_Shell.kinds`) takes a declaration's options, as measured on macOS bash
    3.2, sh, dash and zsh 5.9: bash's export takes -f, -n and -p, its readonly -a, -f, -n and -p,
    its declare, typeset and local -a, -F, -f, -i, -p, -r, -t and -x (a `+` word after export or
    readonly is a name there, see `declaration`); dash's export and readonly only -p; zsh's
    typeset family its type flags, but export no -x or -g and readonly no -r."""
    groups = re.findall(r"([-+])([A-Za-z0-9]*)", flags)
    letters = {(sign, ch) for sign, word in groups for ch in word if not ch.isdigit()}
    if any(re.search(r"\d", word) for _, word in groups) and (
            kind != "zsh" or any(re.search(r"(^|[^EFLRZi0-9])\d", word) for _, word in groups)):
        return False  # bash and dash take no digits; zsh only after -E, -F, -L, -R, -Z or -i
    if kind == "dash":
        return all((sign, ch) == ("-", "p") for sign, ch in letters)
    if kind == "zsh":
        allowed = set("AEFHLRTUZafghilmprtux") - {"export": {"x", "g"}, "readonly": {"r"}}.get(keyword, set())
        return all(ch in allowed for _, ch in letters)
    allowed = {"export": "fnp", "readonly": "afnp"}.get(keyword, "aFfiprtx")
    return all(ch in allowed for sign, ch in letters if sign == "-" or keyword not in {"export", "readonly"})


def _declaration_words(args: list[str]) -> tuple[str, list[str]]:
    """A declaration's options, the words up to the first other one or `--` (kept last, see
    `declare`), and its names, the rest: after `--`, a word that starts with `-` is a name, and not
    a valid one."""
    flags, names = "", []
    for k, a in enumerate(args):
        if a == "--":
            return flags + "--", names + args[k + 1:]
        if not a.startswith(("-", "+")) or len(a) < 2 or ASSIGN.match(a):
            return flags, names + args[k:]
        flags += a
    return flags, names


def _option_key(name: str) -> str:
    """What `option` does with a name, for telling apart readings of `set` (see `_set_words`)."""
    n = name.lower().replace("_", "")
    if not n:
        return "unmodeled"
    return "harmless" if n in HARMLESS_OPTIONS or n.startswith("no") and n[2:] in HARMLESS_OPTIONS else n


def _set_words(args: list[str], reading: str, startup: bool = False) -> dict:
    """How `set` takes `args` in one reading (see SET_LETTERS; "posix" is bash's letters and
    dash's together): the options its letters set, as (name, on); the option names its `o`s take;
    the positional parameters it sets (None: they stay); whether it lists the options; the
    letters dash lacks ("posix"; bash's errors are `_bash_set`'s), or the one zsh stops at; and
    `effects`, which tells readings that differ apart. `startup`: a new shell's flags, where c, s, i and l are its own."""
    zsh = reading != "posix"
    table = SET_LETTERS[reading] if zsh else {**SET_LETTERS["dash"], **SET_LETTERS["bash"]}
    letters, names, missing, dash_missing = [], [], [], []
    positional, lists, j = None, False, 0
    while j < len(args) and not (zsh and missing):
        a = args[j]
        if a in {"--", "-"}:
            positional = args[j + 1:]
            break
        if not (a.startswith(("-", "+")) and len(a) > 1):
            positional = args[j:]
            break
        on, cluster = a[0] == "-", a[1:]
        for k, c in enumerate(cluster):
            if c == "o":
                if zsh and cluster[k + 1:]:
                    names.append((cluster[k + 1:], on))  # zsh: the rest of the cluster
                    break
                if j + 1 < len(args) and (zsh or args[j + 1][:1] not in {"", "-", "+"}):
                    j += 1
                    names.append((args[j], on))
                else:
                    lists = True
                    if not zsh and j + 1 < len(args):
                        dash_missing.append(c)  # dash takes `-e` as a name it lacks; bash lists
                continue
            if startup and c in "csil":
                continue
            if not zsh:
                dash_missing += [c] if c not in SET_LETTERS["dash"] else []
            if c in table:
                letters.append((table[c], on))
            else:
                missing.append(c)
                if zsh:
                    break
        j += 1
    effects = (tuple((_option_key(n), on) for n, on in letters), tuple(names),
               None if positional is None else tuple(positional), lists)
    return {"letters": letters, "names": names, "positional": positional, "lists": lists, "missing": missing,
            "dash_missing": dash_missing, "effects": effects}


def _bash_set(args: list[str]) -> tuple[list[str], list[tuple[bool, str, bool]] | None]:
    """Where bash 3.2 fails `set ARGS`. First it checks the letters of each word of options, but
    not those after an `o` in the same word (they are the `o`'s word in this check, and an `o` at
    a word's end takes the next word unless that starts with `-` or `+`): at a letter it lacks
    there, `set` fails (status 2) before it changes anything, and sh exits. Then it takes the
    words in order, each `o` the next word (or, where that is missing or starts with `-` or `+`,
    it lists the options), and stops at a letter or an option name it lacks: what came before
    stays, `set` fails (status 1), and sh goes on (measured on bash 3.2 and its sh). The letters
    the first check meets that bash lacks, and what the second applies before it stops, as
    (is a name, the letter or name, on), or None where it does not stop."""
    usage, j = [], 0
    while j < len(args):
        a = args[j]
        if a in {"--", "-"} or not (a.startswith(("-", "+")) and len(a) > 1):
            break
        cluster = a[1:]
        k = cluster.find("o")
        usage += [c for c in (cluster if k < 0 else cluster[:k]) if c not in SET_LETTERS["bash"]]
        if k == len(cluster) - 1 and j + 1 < len(args) and args[j + 1][:1] not in {"", "-", "+"}:
            j += 1
        j += 1
    if usage:
        return usage, None
    done: list[tuple[bool, str, bool]] = []
    j = 0
    while j < len(args):
        a = args[j]
        if a in {"--", "-"} or not (a.startswith(("-", "+")) and len(a) > 1):
            break
        on = a[0] == "-"
        for c in a[1:]:
            if c == "o":
                if j + 1 < len(args) and args[j + 1][:1] not in {"", "-", "+"}:
                    j += 1
                    if args[j] not in BASH_OPTIONS:
                        return usage, done
                    done.append((True, args[j], on))
            elif c not in SET_LETTERS["bash"]:
                return usage, done
            else:
                done.append((False, c, on))
        j += 1
    return usage, None


def _zsh_option(name: str) -> bool:
    """Whether zsh has an option of this name: case and underscores aside, with or without `no`."""
    n = name.lower().replace("_", "")
    return n in ZSH_OPTIONS or n.startswith("no") and n[2:] in ZSH_OPTIONS


def _merge_frames(stacks: list[list[dict]], current: list[dict]) -> list[dict]:
    """The locals of the calls around (see `_Shell.locals`) after branches that each left
    `stacks`: where they differ, what the return restores is each one's (see `_Restore`)."""
    out = []
    for i, frame in enumerate(current):
        frames = [stack[i] for stack in stacks if len(stack) > i]
        if not frames:
            out.append(frame)
            continue
        merged = {}
        for k in set().union(*frames):
            olds, keep = [], False
            for f in frames:
                if k not in f:
                    keep = True
                elif isinstance(f[k], _Restore):
                    olds += f[k].olds
                    keep = keep or f[k].keep
                else:
                    olds.append(f[k])
            olds = list(dict.fromkeys(olds))
            merged[k] = olds[0] if len(olds) == 1 and not keep else _Restore(tuple(olds), keep)
        out.append(merged)
    return out


def _assigned_name(node) -> str | None:
    """The variable an assignment sets (an array's, for an element)."""
    name = node.child_by_field_name("name")
    if name is not None and name.type == "subscript":
        name = name.child_by_field_name("name")
    return None if name is None else _text(name)


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


# Where a newline before a backslash is text, not the end of a command line.
TEXT_NODES = {"string", "raw_string", "ansi_c_string", "translated_string", "heredoc_body", "comment"}


def _misread_backslashes(data: bytes) -> list[int]:
    """Offsets of each newline the grammar misreads before a backslash. It takes a line that
    starts with one as more of the line before: `true` then `\\cat x` on the next line parses as
    `true '\\cat' x`, a backslash and newline after it joins the lines (`true cat x`), and a
    here-document body loses such a first line to its command's words. The shell ends the line
    there, as it does anywhere outside quotes and here-document bodies."""
    root = _BASH.parse(data).root_node
    out, i = [], data.find(b"\n\\")
    while i != -1:
        node = root.descendant_for_byte_range(i, i + 1)
        if node is None or node.type not in TEXT_NODES:
            out.append(i)
        i = data.find(b"\n\\", i + 1)
    return out


def _heredoc_delimiter(word: str) -> str | None:
    """The line that ends a here-document whose word is `word`: the word after quote removal
    (`E'O'F` gives `EOF`, `"\\EOF"` gives `\\EOF`). None for `$'...'` and `$"..."`, which bash and
    zsh translate and dash does not (measured)."""
    if "$'" in word or '$"' in word:
        return None
    out, quote, i = [], None, 0
    while i < len(word):
        c = word[i]
        if quote == "'":
            if c == "'":
                quote = None
            else:
                out.append(c)
        elif c == "\\" and i + 1 < len(word) and (quote is None or word[i + 1] in '$`"\\'):
            out.append(word[i + 1])
            i += 1
        elif c in "'\"" and quote in {None, c}:
            quote = None if quote else c
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _misread_heredocs(data: bytes, root=None) -> list[int]:
    """Where the grammar ends a here-document at a line the shells take as more of its body. The
    shells end it only at a line that is the delimiter exactly, once `<<-` drops the line's
    leading tabs; the grammar also ends it with blanks or a carriage return around the delimiter
    (` EOF`, `EOF `) and at the word as written (`<<E'O'F`, then `E'O'F`). Each is the offset of
    the delimiter the grammar matched, or -1 where `_parseable` cannot mend the reading: a line
    of the grammar's body that is the delimiter, or a delimiter the shells read differently. In
    a command substitution a `)` or a backquote may follow the delimiter: the grammar reads it
    as bash does (measured on bash 3.2, its sh, dash and zsh 5.9)."""
    root = root or _BASH.parse(data).root_node
    out = []
    for r in _walk(root):
        if r.type != "heredoc_redirect":
            continue
        start = next((c for c in r.named_children if c.type == "heredoc_start"), None)
        body = next((c for c in r.named_children if c.type == "heredoc_body"), None)
        end = next((c for c in r.named_children if c.type == "heredoc_end"), None)
        if start is None or end is None:
            continue
        delimiter = _heredoc_delimiter(_text(start))
        if delimiter is None:
            out.append(-1)
            continue
        tabs = any(not c.is_named and _text(c) == "<<-" for c in r.children)
        first = data.rfind(b"\n", 0, (body or end).start_byte) + 1
        last = data.rfind(b"\n", 0, end.start_byte) + 1
        stop = data.find(b"\n", end.start_byte)
        lines = data[first:last].decode(errors="replace").split("\n")[:-1]
        line = data[last:len(data) if stop == -1 else stop].decode(errors="replace")
        if tabs:
            lines = [x.lstrip("\t") for x in lines]
            line = line.lstrip("\t")
        substituted = any(a.type == "command_substitution" for a in _ancestors(r))
        if delimiter in lines:
            out.append(-1)
        elif line != delimiter and not (substituted and line[len(delimiter):][:1] in {")", "`"}
                                         and line.startswith(delimiter)):
            out.append(end.start_byte)
    return out


def _ancestors(node):
    while node.parent is not None:
        node = node.parent
        yield node


def _insert(data: bytes, added: list[int], at: list[int], byte: bytes = b" ") -> tuple[bytes, list[int]]:
    """`data` with `byte` inserted before each offset in `at`, and the offsets of every byte
    `_parseable` has added, moved to match."""
    at = sorted(set(at))
    b = bytearray(data)
    for i in reversed(at):
        b[i:i] = byte
    added = [a + sum(1 for i in at if i <= a) for a in added]
    return bytes(b), added + [i + k for k, i in enumerate(at)]


def _parseable(data: bytes) -> tuple[bytes, set[int], tuple[int, ...]]:
    """The command as the grammar can read it: a space after each newline it misreads before a
    backslash (see `_misread_backslashes`; a blank that starts a line changes nothing, outside a
    here-document's body), a byte before each delimiter it matches where the shells go on with
    the here-document (see `_misread_heredocs`), and each misread `!` blanked (offsets
    unchanged). Also where the statements those `!`s negated start, and where the added bytes
    are (`heredoc` leaves them out of the body)."""
    added: list[int] = []
    for _ in range(16):
        newlines = _misread_backslashes(data)
        if newlines:
            data, added = _insert(data, added, [i + 1 for i in newlines])
            continue
        ends = [i for i in _misread_heredocs(data) if i >= 0]
        if not ends:
            break
        for i in sorted(ends, reverse=True):
            # Any byte but the delimiter's first stops the grammar's match.
            data, added = _insert(data, added, [i], b"y" if data[i:i + 1] == b"x" else b"x")
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
    return data, negate, tuple(sorted(added))


def _expand(path: Path) -> list[Path]:
    text = str(path)
    if any(c in text for c in "*?["):
        return [Path(p) for p in globlib.glob(text)] or [path]
    return [path]


def _walk(node):
    """A node and every node under it, in source order."""
    yield node
    for c in node.children:
        yield from _walk(c)


def _rejected(nodes) -> tuple[bool, bool, bool]:
    """Whether POSIX-mode bash and dash reject a line of code (its statements) as they read it,
    before any of it runs. dash rejects a process substitution, a here-string (`<<<`) and an array
    value (`p=(1 2)`, `local p=(1)`) anywhere in the line, its command substitutions and function
    bodies included. POSIX-mode bash lacks a process substitution only as the start of a word
    outside a command substitution: glued to text before it, or as an assignment's value, `<(` is
    plain text, and a command substitution's code it reads as it runs it, where the error ends only
    the substitution (measured on macOS's /bin/sh and dash). Here-documents' bodies are left to the
    process substitution's own handling (see `value`). bash 3.2 itself, and so its sh, and dash
    reject `|&` (zsh's pipe of both outputs) the same way: the third value."""
    posix = dash = bash = False

    def walk(node, substituted):
        nonlocal posix, dash, bash
        if node.type == "heredoc_body":
            return
        if node.type in {"herestring_redirect", "array"}:
            dash = True
        if node.type == "|&":
            dash = True
            bash = bash or not substituted
        if node.type == "process_substitution":
            dash = True
            parent, prev = node.parent, node.prev_sibling
            glued = (parent is not None and parent.type == "variable_assignment"
                     or prev is not None and prev.is_named and prev.end_byte == node.start_byte)
            posix = posix or not substituted and not glued
        for c in node.children:
            walk(c, substituted or node.type == "command_substitution")

    for n in nodes:
        walk(n, False)
    return posix, dash, bash


def _body(node):
    """A redirected statement's body (the statement itself otherwise)."""
    if node.type == "redirected_statement":
        return node.child_by_field_name("body") or node
    return node


# In a double-quoted string the grammar puts the whitespace before an expansion that follows
# another (`"$x $y"`) inside the second one's node; no expansion starts with whitespace.
EXPANSIONS = {"simple_expansion", "expansion", "command_substitution", "arithmetic_expansion", "process_substitution"}


def _text(node) -> str:
    text = node.text.decode(errors="replace")
    return text.lstrip() if node.type in EXPANSIONS else text


def _lead(node) -> int:
    """How many bytes of whitespace the grammar put at the start of an expansion's node (see
    EXPANSIONS)."""
    return len(node.text) - len(node.text.lstrip()) if node.type in EXPANSIONS else 0


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
    """A loop, a function call, an `eval` or `.` (`eval`), a line of a program (`line`) or a
    subshell (`barrier`) the shell is inside, and the worlds that left it by `break`, `continue`,
    `return` or an error that aborts (`abort`, see `_Shell.abort`) or drops the line (`drop`, see
    `_Shell.drop`), each with the shell state it left with."""

    def __init__(self, kind: str):
        self.kind = kind
        # Each as [worlds, state, number]: the number orders jumps (see `_Shell.carry`).
        self.jumps: dict[str, list[list]] = {"break": [], "continue": [], "return": [], "abort": [], "drop": []}

    def take(self, what: str) -> list[tuple[list, tuple]]:
        out, self.jumps[what] = self.jumps[what], []
        return [(ws, st) for ws, st, _ in out]


class _Restore(NamedTuple):
    """In a function's locals, where branches that may each have run differ: the outer values a
    variable (or its export) goes back to at the return (`olds`, None for none), and whether in
    some branch it keeps the value it has then (`keep`: it was no local there)."""

    olds: tuple
    keep: bool


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


# Bytes an escape can stand for that the audit can hold as text: no marker (see UNKNOWN and the
# others above) and nothing past ASCII.
_PLAIN_BYTES = {*range(0x08, 0x0E), *range(0x18, 0x80)}
_LETTER_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\"}


def _byte(n: int) -> str:
    return chr(n) if n in _PLAIN_BYTES else UNKNOWN


def _unescape(text: str, zsh: bool, bare_octal: bool = False) -> tuple[str, bool]:
    """Decode the escapes echo reads (and printf's %b), as bash 3.2 and zsh 5.9 do: the letters
    above, `\\0` with up to three more octal digits, `\\x` with one or two hex digits, and `\\c`,
    which ends the output. zsh alone reads `\\e`, a `\\x` without digits (a NUL) and `\\u`/`\\U`;
    with `bare_octal` (bash's %b), `\\NNN` too. Returns the text and whether `\\c` ended it. A byte
    the audit cannot hold as text becomes UNKNOWN."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c != "\\" or i + 1 == len(text):
            out.append(c)
            i += 1
            continue
        e, rest = text[i + 1], text[i + 2:]
        if e in _LETTER_ESCAPES:
            out.append(_LETTER_ESCAPES[e])
            i += 2
        elif e == "c":
            return "".join(out), True
        elif e == "0" or (bare_octal and e in "1234567"):
            digits = re.match(r"[0-7]{0,3}" if e == "0" else r"[0-7]{0,2}", rest).group()
            out.append(_byte(int(digits or "0" if e == "0" else e + digits, 8) & 0xFF))
            i += 2 + len(digits)
        elif e == "x" and re.match(r"[0-9a-fA-F]", rest):
            digits = re.match(r"[0-9a-fA-F]{1,2}", rest).group()
            out.append(_byte(int(digits, 16)))
            i += 2 + len(digits)
        elif zsh and e in "xe":
            out.append(_byte(0 if e == "x" else 0x1B))
            i += 2
        elif zsh and e in "uU":
            digits = re.match(r"[0-9a-fA-F]{0,%d}" % (4 if e == "u" else 8), rest).group()
            out.append(UNKNOWN)  # a Unicode character, or a NUL without digits
            i += 2 + len(digits)
        else:
            out.append(c + e)
            i += 2
    return "".join(out), False


def _echo_once(words: list[str], zsh: bool, options: bool, decode_default: bool) -> str:
    """echo's output for one shell and set of options: `options` whether it reads leading -n, -e and
    -E (bash in POSIX mode, as macOS's sh is, reads none), `decode_default` whether it decodes
    escapes without -e or -E (POSIX mode, bash's xpg_echo, zsh without BSD_ECHO)."""
    j = 0
    if options:
        while j < len(words) and re.fullmatch(r"-[neE]+", words[j]):
            j += 1
    flags = "".join(a[1:] for a in words[:j])
    rest = words[j:]
    if zsh and rest[:1] == ["-"]:
        rest = rest[1:]  # zsh takes a lone `-` after the options as their end
    last = max(flags.rfind("e"), flags.rfind("E"))
    if zsh:
        decode = "e" in flags or ("E" not in flags and decode_default)  # any -e wins in zsh
    else:
        decode = flags[last] == "e" if last >= 0 else decode_default
    text, stopped = " ".join(rest), False
    if decode:
        text, stopped = _unescape(text, zsh)
    return text + ("" if stopped or "n" in flags else "\n")


def _choice_count(text: str) -> int:
    """How many values a text with CHOICE groups can take."""
    n = 1
    for m in CHOICE.finditer(text):
        n *= m.group(1).count("\x05") + 1
    return n


def _values(texts: list[str]) -> list[str] | None:
    """The different values the texts can take, or None if there are more than 64. Groups do
    not nest, so a text with groups of its own counts as each of its values."""
    if any(_choice_count(t) > 64 for t in texts):
        return None
    values = list(dict.fromkeys(c for t in texts for c in _choices(t)))
    return values if len(values) <= 64 else None


def _either_text(texts: list[str]) -> str:
    """One text, or a CHOICE of the different values the texts can take; UNKNOWN if they can take
    more than the audit follows."""
    values = _values(texts)
    if values is None:
        return UNKNOWN
    return values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"


def _either_output(outs: list[str | None]) -> str | None:
    """What one of several possible outputs is: None (unknown) if any of them is, or if together
    they can take more values than the audit follows."""
    values = None if None in outs else _values(outs)
    if values is None:
        return None
    return values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"


def _dirname(path: str) -> str:
    """What POSIX dirname prints for one operand (without the newline)."""
    trimmed = path.rstrip("/")
    if not path or (trimmed and "/" not in trimmed):
        return "."
    if not trimmed:
        return "/"
    return trimmed[:trimmed.rindex("/")].rstrip("/") or "/"


def _basename(path: str, suffix: str = "") -> str:
    """What POSIX basename prints for one operand and an optional suffix (without the newline)."""
    trimmed = path.rstrip("/")
    if not path or not trimmed:
        return "/" if path else ""
    name = trimmed[trimmed.rfind("/") + 1:]
    return name[:-len(suffix)] if suffix and name != suffix and name.endswith(suffix) else name


def _closing(text: str, i: int, open_: str, close: str) -> int:
    """Where the `close` matching the `open_` just before text[i] is (len(text) if none), past
    quotes, backslashes and nested pairs."""
    depth, quote = 1, None
    while i < len(text):
        c = text[i]
        if c == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            quote = None if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def _heredoc_parts(text: str) -> list[tuple[bool, str]]:
    """An unquoted here-document's text as (expansion?, text) parts, as the shell reads it: a
    backslash quotes `$`, a backquote, a backslash and a newline (which then goes); `$NAME`,
    `${...}`, `$(...)`, `$((...))` and backquotes expand; everything else, quotes included, is
    literal. A backquoted command comes as `$(...)`."""
    parts: list[tuple[bool, str]] = []
    lit, i = [], 0

    def expansion(piece):
        if lit:
            parts.append((False, "".join(lit)))
            lit.clear()
        parts.append((True, piece))

    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in "$`\\\n":
            if text[i + 1] != "\n":
                lit.append(text[i + 1])
            i += 2
        elif c == "$" and text[i + 1:i + 3] == "((":
            end = _closing(text, i + 3, "(", ")")
            end = _closing(text, end + 1, "(", ")") if end + 1 < len(text) and text[end + 1] == ")" else end
            expansion(text[i:end + 1])
            i = end + 1
        elif c == "$" and text[i + 1:i + 2] in {"(", "{"}:
            end = _closing(text, i + 2, text[i + 1], ")" if text[i + 1] == "(" else "}")
            expansion(text[i:end + 1])
            i = end + 1
        elif c == "$" and (m := re.match(r"[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-]", text[i + 1:])):
            expansion(text[i:i + 1 + m.end()])
            i += 1 + m.end()
        elif c == "`":
            j, inner = i + 1, []
            while j < len(text) and text[j] != "`":
                if text[j] == "\\" and j + 1 < len(text) and text[j + 1] in "$`\\":
                    j += 1
                inner.append(text[j])
                j += 1
            expansion("$(" + "".join(inner) + ")")
            i = j + 1
        else:
            lit.append(c)
            i += 1
    if lit:
        parts.append((False, "".join(lit)))
    return parts


def _concat(first: str | None, then: str | None) -> str | None:
    """Two outputs one after the other: None (unknown) if either is, or if together they can take
    more values than the audit follows."""
    if first is None or then is None:
        return None
    out = first + then
    return out if _choice_count(out) <= 64 else None


def _echo(args: list[str], shell: str | None, tilde, posix: bool | None = False, xpg: bool | None = False,
          bsd: bool | None = False) -> str | None:
    """What echo prints: one text, a CHOICE of the texts it may print, or None for a shell the audit
    does not model. bash reads -n, -e and -E, the last of -e and -E deciding, and decodes escapes
    without them under `shopt -s xpg_echo`; in POSIX mode (`set -o posix`, POSIXLY_CORRECT, and
    macOS's sh) it reads no options and always decodes. zsh reads the same options, any -e
    winning, decodes unless BSD_ECHO is set (`emulate sh` sets it), and takes a lone `-` as the end
    of the options. `shell` None is the transcript's own shell, bash or zsh; an option None was left
    set in some branches and not in others. Each possibility is followed. Escapes for bytes the
    audit cannot hold, and parts of the words it cannot work out, are UNKNOWN."""
    if shell not in {None, "bash", "zsh", "sh"}:
        return None
    regimes = set()
    if shell in {None, "bash", "sh"}:
        for p in [posix] if posix is not None else [False, True]:
            for x in [xpg] if xpg is not None else [False, True]:
                regimes.add((False, not p, p or x))
    if shell in {None, "zsh"}:
        for b in [bsd] if bsd is not None else [False, True]:
            regimes.add((True, True, not b))
    outs = []
    for combo in itertools.islice(itertools.product(*(_choices(a) for a in args)), 64):
        words = [tilde(a) for a in combo]
        outs += [_echo_once(words, *regime) for regime in sorted(regimes)]
    return _either_text(outs)


def _printf(args: list[str], shell: str | None, once: bool = False) -> str | None:
    """What printf prints, as `_echo` returns it. The format is reused while arguments remain, and
    used once if there are none (`once`: its first pass alone). Its escapes are echo's letters, `\\e`, `\\NNN` and `\\xHH`; zsh
    alone stops at `\\c`, which bash and sh print. %s prints an argument, %c its first character,
    %b decodes it as echo -e does (bash also reads `\\NNN` there), %d and %i a plain decimal integer,
    and %% a percent sign; any other conversion, a flag, width or precision, another escape, and
    -v (which assigns instead of printing) are UNKNOWN."""
    if shell not in {None, "bash", "zsh", "sh"}:
        return None
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        return None
    if args[0].startswith("-"):
        return UNKNOWN
    outs = []
    for zsh in [False, True] if shell is None else [shell == "zsh"]:
        for combo in itertools.islice(itertools.product(*(_choices(a) for a in args)), 64):
            outs.append(_printf_once(combo[0], list(combo[1:]), zsh, once))
    return _either_text(outs)


def _printf_once(fmt: str, args: list[str], zsh: bool, once: bool = False) -> str:
    out, i = [], 0
    while True:
        used, j = 0, 0
        while j < len(fmt):
            c = fmt[j]
            if c == "\\" and j + 1 < len(fmt):
                e, rest = fmt[j + 1], fmt[j + 2:]
                j += 2
                if e in _LETTER_ESCAPES:
                    out.append(_LETTER_ESCAPES[e])
                elif e == "c":
                    if zsh:
                        return "".join(out)
                    out.append("\\c")
                elif e == "e":
                    out.append(_byte(0x1B))
                elif e in "01234567":
                    digits = re.match(r"[0-7]{0,2}", rest).group()
                    out.append(_byte(int(e + digits, 8) & 0xFF))
                    j += len(digits)
                elif e == "x" and re.match(r"[0-9a-fA-F]", rest):
                    digits = re.match(r"[0-9a-fA-F]{1,2}", rest).group()
                    out.append(_byte(int(digits, 16)))
                    j += len(digits)
                else:
                    out.append(UNKNOWN)  # \', \", \? and the like differ between the shells
                continue
            if c != "%":
                out.append(c)
                j += 1
                continue
            m = re.match(r"%([-+ #0]*)(\*|\d*)(\.(?:\*|\d*))?([a-zA-Z%]?)", fmt[j:])
            j += len(m.group())
            if m.group(4) == "%" and not m.group(1) and not m.group(2) and not m.group(3):
                out.append("%")
                continue
            arg = args[i] if i < len(args) else None
            i += 1
            used += 1
            conv = m.group(4)
            if m.group(1) or m.group(2) or m.group(3) or conv not in {"s", "b", "c", "d", "i"}:
                out.append(UNKNOWN)
            elif conv == "s":
                out.append(arg or "")
            elif conv == "c":
                out.append((arg or "")[:1])
            elif conv == "b":
                piece, stopped = _unescape(arg or "", zsh, bare_octal=not zsh)
                out.append(piece)
                if stopped:
                    return "".join(out)
            else:
                v = (arg or "0").strip()
                out.append(str(int(v)) if re.fullmatch(r"-?(?:0|[1-9]\d*)", v) else UNKNOWN)
        if not used or i >= len(args) or once:
            return "".join(out)


AWK_STDIN = {"-", "/dev/stdin", "/dev/fd/0"}


def _awk_tokens(code: str) -> list[str]:
    """An awk program's tokens, comments dropped and each regexp one `<regexp>` token."""
    raw = [m.group() for m in AWK_TOKENS.finditer(code) if not m.group().startswith("#")]
    # A slash at expression start introduces a regexp, whose contents are data too. Keep
    # division ambiguous rather than recognizing file operations in regex text.
    tokens, j = [], 0
    while j < len(raw):
        t = raw[j]
        if t == "/" and (not tokens or tokens[-1] in {"{", "}", "(", ",", "~", "!", "!~", "=", ";", "&&", "||",
                                                     "print", "printf", "return", "?", ":"}):
            j += 1
            while j < len(raw):
                if raw[j] == "/" and raw[j - 1] != "\\":
                    break
                j += 1
            tokens.append("<regexp>")
        else:
            tokens.append(t)
        j += 1
    return tokens


def _awk_actions(tokens: list[str]) -> dict[int, str | None]:
    """Each token's action: "BEGIN", "END", "record" (no pattern) or "pattern"; None outside actions."""
    kind: dict[int, str | None] = {}
    depth, start, current = 0, 0, None
    for i, token in enumerate(tokens):
        if token == "{":
            if depth == 0:
                prefix = tuple(t for t in tokens[start:i] if t != ";")
                current = {("BEGIN",): "BEGIN", ("END",): "END", (): "record"}.get(prefix, "pattern")
            depth += 1
        kind[i] = current
        if token == "}":
            depth -= 1
            if depth == 0:
                start, current = i + 1, None
    return kind


def _awk_begin_exits(tokens: list[str], kind: dict[int, str | None]) -> bool:
    """Whether a BEGIN block certainly runs `exit`: one at its top level, with no condition, loop
    or function definition before it in the block. awk then reads no record; END still runs."""
    depth, control = 0, False
    for i, t in enumerate(tokens):
        if kind.get(i) != "BEGIN":
            continue
        if t == "{":
            depth += 1
            control = control and depth > 1
        elif t == "}":
            depth -= 1
        elif t in {"if", "else", "while", "for", "do", "?", "&&", "||", "function", "func"}:
            control = True
        elif t == "exit" and depth == 1 and not control:
            return True
    return False


def _awk_operands(code: str) -> str | None:
    """Whether awk reads its file operands: "unread" when it certainly never opens them, "maybe"
    when it may not or may open others instead, None when it reads them as usual.

    awk opens its operands for record actions, END blocks and getline from the main input. With
    only BEGIN blocks, or after a certain `exit` in BEGIN, it opens them only for such a getline:
    one in BEGIN or END (in a function, or under a condition, it may or may not run). ARGV and ARGC
    change which files it opens."""
    tokens = _awk_tokens(code)
    kind = _awk_actions(tokens)
    if "ARGV" in tokens or "ARGC" in tokens:
        return "maybe"
    begin_only = all(kind.get(i) == "BEGIN" or (t == "BEGIN" and tokens[i + 1:i + 2] == ["{"]) or
                     (t == ";" and kind.get(i) is None) for i, t in enumerate(tokens))
    if not tokens or not (begin_only or _awk_begin_exits(tokens, kind)):
        return None
    if {"function", "func"} & set(tokens):
        return "maybe"
    for i, t in enumerate(tokens):
        if t != "getline" or kind.get(i) not in {"BEGIN", "END"} or tokens[i - 1:i] in (["|"], ["|&"]):
            continue
        depth = 0
        for u in tokens[i + 1:]:
            if depth == 0 and u in {";", "}"}:
                break
            depth += (u in {"(", "["}) - (u in {")", "]"})
            if depth < 0:
                break
            if depth == 0 and u == "<":
                break  # a getline from a named file
        else:
            return "maybe"
        if u != "<":
            return "maybe"
    return "unread"


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
        self.added: dict[bytes, tuple[int, ...]] = {}  # bytes `_parseable` added, by parsed code
        self.prevalued: dict = {}  # a declaration's assignment nodes, by their expanded values
        # Which shell runs the code where shells differ: "zsh", "posix" (bash, dash) or None when the
        # audit cannot tell, which keeps what either would do. `lastpipe`: bash's `shopt -s lastpipe`.
        self.dialect: str | None = None
        self.shell_name: str | None = None  # the shell a command names (bash, sh, dash, zsh), if any
        self.lastpipe = False
        # Expansion options are shell state: None means branches left both settings possible.
        self.noglob: bool | None = False
        self.shwordsplit: bool | None = False
        self.localoptions: bool | None = False  # zsh restores options on function return
        self.braceexpand: bool | None = True
        self.ksharrays: bool | None = False
        self.shoptionletters: bool | None = False
        self.globsubst: bool | None = False  # zsh globs expansion results only with this option
        self.nomatch: bool | None = True  # native zsh exits on an unmatched pathname pattern
        # echo's options (see `_echo`): bash's POSIX mode (macOS's sh starts in it), bash's xpg_echo
        # and zsh's BSD_ECHO.
        self.posix: bool | None = False
        self.xpgecho: bool | None = False
        self.bsdecho: bool | None = False
        # zsh's MULTIOS: a pipeline stage's output goes down the pipe as well as to its redirections.
        self.multios: bool | None = True
        # `set -e` and `set -u`: a command that fails, or the expansion of an unset parameter, may
        # end the shell (see `may_end`).
        self.errexit: bool | None = False
        self.nounset: bool | None = False
        # `set -x` and `set -v`: the shell writes each command, or each line it reads, to standard
        # error (see `visit`).
        self.xtrace: bool | None = False
        self.verbose: bool | None = False
        # zsh's POSIX_BUILTINS (set by `emulate sh` and `emulate ksh`): `command` runs builtins.
        self.posixbuiltins: bool | None = False
        # zsh's POSIX_IDENTIFIERS (the same): an arithmetic assignment makes no integer (see
        # `created`); and TYPESET_TO_UNSET (the same): typeset leaves a new variable unset.
        self.posixidentifiers: bool | None = False
        self.typesettounset: bool | None = False
        # Shells (see `kinds`) where `command` or `builtin` keeps the builtin it runs from ending the
        # shell (or, zsh, the eval) at an error (see `prefixed`); and whether dash's `command` turns
        # such an error in the code it runs into the command's failure.
        self.unspecial: frozenset = frozenset()
        self.caught = False
        # Whether bash's POSIX mode (sh) runs this code where a special builtin's error fails it
        # instead of ending the shell (see `guarding`).
        self.guarded = False
        # Whether a cd went to a path written with two leading slashes, which bash and dash keep in
        # the text of the directory ($PWD, pwd) where zsh writes one (see `slashed_text`).
        self.slashed = False
        self.exit_traps: list[str] = []  # code `trap CODE EXIT` may have set to run when this shell ends
        # Where `exec` sent standard output for the rest of the shell: None (where it was), or the
        # targets and whether they are certain (branches may differ). See `emit`.
        self.diverted: tuple | None = None
        # What bash may still have buffered for standard output: False (nothing), a text, or None
        # (unknown). macOS's bash 3.2 keeps what a builtin wrote to a closed standard output and
        # writes it with the next builtin write, to wherever standard output then goes, and so does
        # a forked subshell; zsh drops it. See `emit`.
        self.pending: str | None | bool = False
        self.emits = 0  # how many times `emit` has run, to tell a builtin's output from routed output
        # What bash keeps of the printf that just ran, where its standard output is closed: the
        # first pass of the format, after which the write fails and printf stops (`printf '%s\n'
        # a b >&-` keeps `a`, measured on bash 3.2 and its sh). None: all it printed. `trims`
        # counts the printfs whose first pass is not all they print (see `emit`).
        self.kept: str | None = None
        self.trims = 0
        self.jumped = 0  # how many jumps (break, continue, return) and exits have been taken
        self.exits: list[list] = []  # [output, number, worlds, state] where the shell exited (see `leave`)
        # Set once a redirection names a descriptor above 2: such a descriptor may be a copy of
        # standard output, so what any later command prints is unknown.
        self.stray = False
        self.err_out = False  # whether standard error may be standard output (`2>&1` around)
        # Whether an `exec` has made standard error standard output for the rest of the shell, which
        # a command that ran it (`eval`, a function, a group) keeps after it ends.
        self.exec_err = False
        self.err_around = False  # the same outside the redirections of the simple command running
        self.noisy = 0  # commands run that may have written to standard error while err_out held
        self.child_ends = 0  # unset parameters met in words a forked child may expand
        self.open_failures = 0  # file redirections whose open may fail (see `open_may_fail`)
        # Words being expanded that bash or zsh may expand in the child a command forks: its
        # redirections, and in zsh an external command's prefix assignments (see `failed_redirect`).
        self.forked_words = 0
        # While a command's redirections expand: whether it runs in the shell itself (None: it may
        # or may not, see `runs_inline`).
        self.inline: bool | None = False
        self.subshell_words = False  # while the command whose redirections expand is a subshell
        self.shnullcmd = False  # zsh's SH_NULLCMD (see `null_command`)
        self.cshnullcmd = False  # zsh's CSH_NULLCMD rejects redirections with no command
        self.out_closed = False  # whether a redirection around has closed standard output
        self.stage = None  # the pipeline stage running, while one before the last is
        self.fed = None  # the pipeline stage running, while one after the first is (see `redirect`)
        # The options of the emulation `emulate MODE -c` runs code in, while it does: functions
        # defined there keep them (zsh's sticky emulation; see `emulate`), by body.
        self.sticky: dict | None = None
        self.sticky_functions: dict[int, tuple] = {}
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
        # Files written earlier (in the transcript, or by this command), by path, as the texts each may
        # have (None: what is on disk at audit time), like functions: a script the command runs is
        # read from here (see `scripts`). `wrote_ever`: files this command writes somewhere;
        # `wrote_later` (from the first pass): those, before it writes them.
        self.files: dict[Path, tuple] = {}
        self.wrote_ever: set[Path] = set()
        # What each `<(...)` this command made reads as, by the name it expands to (see `value`).
        self.substituted: dict[str, str | None] = {}
        self.wrote_later: set[Path] = set()
        # Each function's body and each alias's text, as a tuple of alternatives: one, or several
        # where branches that may each have run left it defined differently (None: not defined).
        self.functions: dict[str, tuple] = {}
        self.aliases: dict[str, tuple] = {}
        self.calls = 0  # depth of function calls being followed
        self.locals: list[dict[str, str | None]] = []  # per call being followed: a local's outer value
        self.local_exports: list[dict[str, object]] = []
        self.inlined = 0  # function calls followed in all
        self.feeding = 0  # > 0 while a search's results reach another command
        self.paths: list[Path] = []
        self.literal_paths: set[Path] = set()
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
        self.output: str | None = ""  # what the code printed so far (None: something unknown)
        self.memo: dict | None = None  # word values inside a test being read (see `value`)

    # Worlds

    @property
    def cwd(self) -> Path:
        return self.worlds[0].cwd if self.worlds else self.workdir

    @property
    def oldpwd(self) -> Path | None:
        return self.worlds[0].oldpwd if self.worlds else None

    def set_worlds(self, worlds: list[_World]) -> None:
        """Merge worlds in the same place, drop exited ones, primary first. Past MAX_WORLDS the
        audit stops following the directory (relative paths become suspect). No world at all is a
        state of its own: every world has left by `break`, `continue` or `return`, and nothing runs
        until the loop or function it left takes it back; or the shell has exited, and nothing runs
        until the subshell or new shell it was takes the worlds outside back."""
        live = [w for w in worlds if w.status != EXITED]
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
                dict(self.exports), dict(self.files), self.options(), self.output, self.pending, self.diverted,
                [dict(f) for f in self.locals], [dict(f) for f in self.local_exports])

    def options(self) -> dict:
        return {name: getattr(self, name) for name in
                ("noglob", "shwordsplit", "lastpipe", "allexport", "localoptions", "braceexpand", "ksharrays",
                 "shoptionletters", "globsubst", "nomatch", "posix", "xpgecho", "bsdecho", "multios",
                 "posixbuiltins", "posixidentifiers", "typesettounset", "errexit", "nounset", "xtrace",
                 "verbose", "shnullcmd", "cshnullcmd")}

    def restore_options(self, options: dict) -> None:
        for name, value in options.items():
            setattr(self, name, value)

    def restore(self, state: tuple) -> None:
        self.vars, self.made, self.removed = dict(state[0]), set(state[1]), set(state[2])
        self.functions, self.aliases, self.exports = dict(state[3]), dict(state[4]), dict(state[5])
        self.files = dict(state[6])
        self.restore_options(state[7])
        self.output, self.pending, self.diverted = state[8], state[9], state[10]
        # The locals of the calls around, from the outermost; a state from inside a call that a
        # jump left has more.
        n = len(self.locals)
        self.locals = [dict(f) for f in state[11][:n]] + self.locals[len(state[11]):]
        self.local_exports = [dict(f) for f in state[12][:n]] + self.local_exports[len(state[12]):]

    def exported(self, name: str, exports: dict | None = None) -> object:
        """Whether a variable is exported: True, False or "maybe"."""
        exports = self.exports if exports is None else exports
        return exports.get(name, self.inherit and name in INHERITED)

    def join(self, states: list[tuple]) -> None:
        """After branches that may each have run, from the same start: a variable they leave
        different has each of their values, a function or alias each of their definitions (or
        none, where one left it undefined), a file each of their texts, a directory counts as made
        only if each made it, and as removed if any removed it. What they printed is what any of
        them printed."""
        if not states:
            return
        merged = {}
        for name in set().union(*(st[0] for st in states)):
            # A variable a branch never set is unset there (see `never_set`); a mark (READONLY,
            # INTEGER, a saved value) a branch never made is empty.
            never = self.never_set(name) if IDENTIFIER.fullmatch(name) else ""
            values = list(dict.fromkeys(c for st in states for c in _choices(st[0].get(name, never))))
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
        for name in states[0][7]:
            values = {st[7][name] for st in states}
            setattr(self, name, values.pop() if len(values) == 1 else None)
        self.output = _either_output([st[8] for st in states])
        pending = [st[9] for st in states]
        texts = [t for t in pending if t is not False]
        self.pending = False if not texts else None if None in texts else _either_output(texts)
        diverted = {st[10] for st in states}
        if len(diverted) == 1:
            self.diverted = diverted.pop()
        else:
            targets = {t for d in diverted if d is not None for t in d[0]}
            self.diverted = (tuple(sorted(targets)), False)  # where later output goes is unknown
        self.locals = _merge_frames([st[11] for st in states], self.locals)
        self.local_exports = _merge_frames([st[12] for st in states], self.local_exports)
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
                 set(self.func_exports), self.inherit, self.allexport, self.options(),
                 [dict(frame) for frame in self.locals], [dict(frame) for frame in self.local_exports],
                 self.pending, self.diverted)
        self.frames = [*self.frames, _Frame("barrier")]
        memo, self.memo = self.memo, None  # a substitution's words are its own
        exits, exec_err = len(self.exits), self.exec_err
        err_out = self.err_out
        traps, self.exit_traps = self.exit_traps, []  # a subshell starts with no EXIT trap
        # It ends at its own unset parameters.
        forked, inline, self.forked_words, self.inline = self.forked_words, self.inline, 0, False
        subshell_words, self.subshell_words = self.subshell_words, False
        try:
            yield
        finally:
            self.forked_words, self.inline, self.subshell_words = forked, inline, subshell_words
            self.memo = memo
            self.exec_err, self.err_out = exec_err, err_out  # a subshell's `exec` holds in it alone
            self.run_traps(exits)
            self.exit_traps = traps
            self.finish(exits)
            self.flush()  # bash writes what it still buffers when the subshell exits
            self.pending, self.diverted = saved[-2:]
            saved = saved[:-2]
            (self.worlds, self.known, self.vars, self.functions, self.aliases, self.dialect, self.shell_name,
             self.lastpipe, self.frames, self.exports, self.func_exports, self.inherit, self.allexport,
             options, self.locals, self.local_exports) = saved
            self.restore_options(options)
            self.set_status(MAYBE)

    @contextmanager
    def process(self, verb: str | None = None):
        """A new shell process (`sh -c`, a script): like a subshell, but it starts with only the
        exported variables (one exported in only some branches is unknown), bash's exported
        functions (if the new shell is bash or sh), no aliases and no loops around it. Shell
        startup resets IFS, PWD, OLDPWD and the directory stack instead of importing their values."""
        with self.child():
            self.pending = False  # a new program starts with nothing buffered
            names = set(self.vars) | {n for n in self.exports if n not in self.vars}
            env = {}
            for name in names:
                how = self.exported(name)
                if name == "SHELLOPTS" and how is True and self.shell_name in {"bash", "sh"}:
                    env[name] = self.shellopts()
                elif (how is True and name in self.vars and self.vars[name] != UNSET
                        and _array_values(self.vars[name]) is None):
                    env[name] = self.vars[name]
                elif how == "maybe":
                    env[name] = UNKNOWN
            self.exports = {name: True for name in env}
            self.vars = env
            # These shells initialize their own splitting characters, regardless of exported IFS.
            self.vars["IFS"] = " \t\n\0" if verb == "zsh" else " \t\n"
            self.functions = {n: f for n, f in self.functions.items()
                              if n in self.func_exports and verb in {"bash", "sh", None}}
            self.func_exports = set(self.functions)
            self.aliases, self.frames, self.allexport = {}, [], False
            self.dialect, self.shell_name, self.lastpipe = DIALECTS.get(verb or ""), verb, False
            self.noglob, self.shwordsplit, self.localoptions = False, False, False
            self.braceexpand, self.ksharrays = True, False
            self.shoptionletters = False
            self.globsubst = False
            self.nomatch = True
            self.posix, self.xpgecho, self.bsdecho, self.multios = verb == "sh", False, False, True
            # Until the shell's own flags (`bash -e`) set them.
            self.errexit = self.nounset = self.xtrace = self.verbose = False
            prefix = self.unspecial, self.caught, self.guarded
            self.posixbuiltins, self.unspecial, self.caught, self.guarded = False, frozenset(), False, False
            self.posixidentifiers = self.typesettounset = False
            self.shnullcmd = False
            self.cshnullcmd = False
            # bash 3.2 (including /bin/sh) clears OLDPWD; native zsh initializes it to PWD.
            # Both discard the parent's directory stack, even when its entries still exist.
            self.worlds = [w._replace(oldpwd=w.cwd if verb == "zsh" else None, stack=()) for w in self.worlds]
            self.vars["PWD"] = self.pwd()
            self.vars["OLDPWD"] = self.pwd() if verb == "zsh" else UNSET
            self.exports.update({"PWD": True, "OLDPWD": True})
            if verb == "zsh":
                self.exports["IFS"] = False
            if verb in {"bash", "sh"} and "SHELLOPTS" in env:
                imported = env["SHELLOPTS"]
                if UNKNOWN in imported or CHOICE.search(imported) or "$" in imported:
                    self.noglob, self.braceexpand, self.allexport = None, None, None
                    self.errexit, self.nounset, self.xtrace, self.verbose = None, None, None, None
                    self.notes.append("a child shell's exported SHELLOPTS cannot be resolved")
                else:
                    # SHELLOPTS enables listed options in addition to the new shell's defaults.
                    for name in imported.split(":"):
                        if name in {"noglob", "braceexpand", "allexport", "posix", "errexit", "nounset", "xtrace",
                                    "verbose"}:
                            self.option(name, True)
            locals_, local_exports_, self.locals, self.local_exports = self.locals, self.local_exports, [], []
            sticky, self.sticky = self.sticky, None
            try:
                yield
            finally:
                self.locals = locals_
                self.local_exports = local_exports_
                self.sticky = sticky
                self.unspecial, self.caught, self.guarded = prefix

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

            def stay():
                self.set_status(FAILED if what == "return" else OK)

            if crossed:
                stay()
            elif self.shell_name in exits or self.shell_name is None and self.dialect == "zsh":
                self.leave()
            elif self.shell_name is None and self.dialect is None:
                self.either(self.leave, stay)  # bash carries on, zsh exits
            else:
                stay()
            return
        if not barrier:
            target.jumps[what].append([worlds, self.state(), self.jumped])
            self.jumped += 1
        # `sh` may be dash, which goes on in the function: there the shell stays, as an alternative.
        self.worlds = [w._replace(primary=False) for w in worlds] if crossed and self.shell_name == "sh" else []

    def abort(self) -> None:
        """An error that ends what the nearest `eval` or `.` runs, which then fails (see
        `evaluate`), and otherwise the shell (zsh, at a write to a readonly variable). A subshell
        between ends instead."""
        self.escape("abort", "eval")

    def drop(self) -> None:
        """An error that ends the line the shell is on, of the program, `eval` string or sourced
        file it runs a line at a time (see `lines`): it goes on with the next line, status 1 (bash
        out of POSIX mode, at an assignment to a readonly variable). A subshell or command
        substitution between, which bash runs whole, ends instead."""
        self.escape("drop", "line")

    def escape(self, what: str, kind: str) -> None:
        for f in reversed(self.frames):
            if f.kind == "barrier":
                break
            if f.kind == kind:
                f.jumps[what].append([self.worlds, self.state(), self.jumped])
                self.jumped += 1
                self.worlds = []
                return
        self.leave()

    def unwind(self, entries: list[tuple[list, tuple]], status: str | None = FAILED) -> list[tuple[list, tuple]]:
        """Worlds that jumped out of function calls (by `abort` or `drop`, failed; by `break` or
        `continue`, with their status, `status` None): the locals and positional parameters of each
        call they left go back, as at its return."""
        depth, out = len(self.locals), []
        for ws, st in entries:
            if len(st[11]) > depth:
                here = self.state()
                self.restore(st)
                self.locals, self.local_exports = [dict(f) for f in st[11]], [dict(f) for f in st[12]]
                while len(self.locals) > depth:
                    self.pop_locals()
                st = self.state()
                self.restore(here)
            out.append(([w._replace(status=status) for w in ws] if status is not None else ws, st))
        return out

    @contextmanager
    def guarding(self, on: bool = True):
        """Code that bash's POSIX mode runs where a special builtin's error (a readonly variable's
        `readonly` or `export`, an option they lack) fails the builtin instead of ending the shell:
        each command of an and-or list but the last, the conditions of `if`, `while` and `until`,
        and a command after `!`, with the functions, groups and subshells they run (measured on
        macOS's /bin/sh). The code of an eval, a sourced file and a command substitution is not
        (see `evaluate`, `substitute`)."""
        saved, self.guarded = self.guarded, on
        try:
            yield
        finally:
            self.guarded = saved

    def evaluate(self, run) -> None:
        """Run code as `eval` and `.` do: an error that aborts (see `abort`) ends it, failed."""
        frame = _Frame("eval")
        self.frames = [*self.frames, frame]
        unspecial, self.unspecial = self.unspecial, frozenset()  # the code's commands are not prefixed
        guarded, self.guarded = self.guarded, False
        try:
            run()
        finally:
            self.frames = self.frames[:-1]
            self.unspecial, self.guarded = unspecial, guarded
        self.rejoin(self.unwind(frame.take("abort")))

    def lines(self, node, alias: bool = False) -> None:
        """The statements of a program, `eval` string or sourced file, a line at a time, as bash
        reads them: an error that drops the line (see `drop`) skips the rest of it. The last line of
        an alias's text (`alias`) is the start of the line the alias is on."""
        self.set_status(MAYBE)
        groups: list[list] = []
        for c in node.named_children:
            prev = c.prev_named_sibling
            gap = b"\n" if prev is None else node.text[prev.end_byte - node.start_byte:c.start_byte - node.start_byte]
            if b"\n" in gap.replace(b"\\\n", b"") or not groups:
                groups.append([])
            groups[-1].append(c)
        for k, group in enumerate(groups):
            if alias and k == len(groups) - 1:
                for c in group:
                    self.part(c)
                break
            frame = _Frame("line")
            self.frames = [*self.frames, frame]
            try:
                self.line(group)
            finally:
                self.frames = self.frames[:-1]
            self.rejoin(self.unwind(frame.take("drop")))

    def line(self, group: list) -> None:
        """A line of code, which POSIX-mode bash (bash too, at `|&`) and dash may reject as they
        read it (see `_rejected`): dash then exits, and bash ends the eval or sourced file the line
        is in, failed, else the shell, with nothing of the line run. Its paths count as alternatives,
        in case the audit's parse of the line is wrong."""
        def run():
            for c in group:
                self.part(c)

        posix, dash, bash = _rejected(group)
        posix = posix or bash
        kinds = self.kinds()
        ways = {"run": any(k == "zsh" or k == "bash" and not bash or k == "posix" and not posix
                           or k == "dash" and not dash for k in kinds),
                "abort": "posix" in kinds and posix or "bash" in kinds and bash, "exit": "dash" in kinds and dash}
        if not ways["abort"] and not ways["exit"]:
            run()
            return

        def reject(end):
            def go():
                start, worlds, known = self.state(), self.worlds, self.known
                with self.child():
                    self.set_worlds([w._replace(primary=False) for w in self.worlds])
                    run()
                self.restore(start)
                self.worlds, self.known = worlds, known
                self.complain()
                self.set_status(FAILED)
                end()
            return go

        thunks = [t for t, on in [(run, ways["run"]), (reject(self.abort), ways["abort"]),
                                  (reject(self.leave), ways["exit"])] if on]
        thunks[0]() if len(thunks) == 1 else self.either(*thunks)

    def part(self, c) -> None:
        """A part of a compound command, or of a statement the audit does not follow itself."""
        if c.type in STATEMENTS or c.type in REDIRECTS:
            self.visit(c)
        elif c.type in {"command_substitution", "process_substitution", "string", "concatenation", "expansion"}:
            self.value(c)

    def kinds(self) -> list[str]:
        """The shells that may run the code, as their errors at a write to a readonly variable tell
        them apart: bash, bash in POSIX mode ("posix"), dash and zsh (see READONLY_ASSIGN)."""
        if self.shell_name == "zsh" or self.shell_name is None and self.dialect == "zsh":
            return ["zsh"]
        if self.shell_name == "dash":
            return ["dash"]
        mode = self.posix_mode()
        bash = ["posix"] if mode else ["bash"] if mode is False else ["bash", "posix"]
        if self.shell_name == "sh":
            return [*bash, "dash"]  # `sh` may be dash
        return bash if self.shell_name == "bash" or self.dialect == "posix" else [*bash, "zsh"]

    def readonly(self, name: str) -> bool | None:
        """Whether a variable is readonly: True, False, or None where it is in some branches only."""
        flag = self.vars.get(READONLY + name, "")
        return False if flag in ("", UNSET) else True if flag == "1" else None

    def integer(self, name: str) -> bool | None:
        """Whether a variable is an integer (see INTEGER): True, False, or None where it is in some
        branches only."""
        flags = set(_choices(self.vars.get(INTEGER + name, "")))
        return False if flags <= {"", UNSET} else True if flags <= {"1", "u"} else None

    def mark_integer(self, name: str, flag: str, zsh: bool = False, maybe: bool = False) -> None:
        """Mark a variable an integer (see INTEGER; "" marks it not one). `zsh`: one only zsh makes,
        so an alternative where another shell may run the code; `maybe`: an alternative anyway."""
        kinds = self.kinds()
        if zsh and "zsh" not in kinds:
            return
        if maybe or zsh and kinds != ["zsh"]:
            flags = list(dict.fromkeys([flag, *_choices(self.vars.get(INTEGER + name, ""))]))
            flag = flags[0] if len(flags) == 1 else "\x06" + "\x05".join(flags) + "\x07"
        self.vars[INTEGER + name] = flag

    def absent(self, name: str) -> bool:
        """Whether a variable is certainly not set: unset here, or never set and not one the shell
        or its environment may give it."""
        if name in self.vars:
            return self.vars[name] == UNSET
        return self.never_set(name) == UNSET

    def reshown(self, name: str) -> None:
        """After a write to a variable zsh may show changed (see SHOWN): its value is unknown."""
        if any(c not in ("", UNSET) for c in _choices(self.vars.get(SHOWN + name, ""))) and \
                self.vars.get(name, UNSET) != UNSET:
            self.vars[name] = UNKNOWN

    def never_set(self, name: str) -> str:
        """What a variable this command never set holds: unset, unless the shell or its
        environment may give it (then unknown)."""
        return UNKNOWN if name in VOLATILE or name in INHERITED or name.isupper() and self.inherit else UNSET

    def created(self, name: str) -> bool | None:
        """Whether an arithmetic assignment to `name` makes it an integer: native zsh makes one of a
        variable that does not exist (one set, declared or exported exists, even empty), unless
        POSIX_IDENTIFIERS is set (measured on zsh 5.9); other shells never do. None where the audit
        cannot tell."""
        if "zsh" not in self.kinds() or self.posixidentifiers is True or self.integer(name) is True:
            return False
        values = set(_choices(self.vars[name])) if name in self.vars else {UNSET} if self.absent(name) else {UNSET, ""}
        if UNSET not in values:
            return False
        return True if values == {UNSET} and self.posixidentifiers is False and self.integer(name) is False else None

    def numbered(self, names: list[str], made: dict, text: str, sure: bool) -> None:
        """After an arithmetic expression `text` assigned `names` (`sure`: certainly, with values the
        audit knows): those it made integers (`made`, see `created`), and zsh's integers given a
        value in base notation, which zsh then shows in that base, `16#10` (and keeps for later
        values): their values are unknown from here. One it may have made a float is as unknown."""
        if "zsh" not in self.kinds():
            return
        based = _BASED.search(text) is not None
        for n in names:
            how = made.get(n, False)
            if how is not False:
                self.mark_integer(n, "u" if based or not sure else "1", zsh=True, maybe=how is None or not sure)
            elif based and self.integer(n) is not False:
                self.mark_integer(n, "u", zsh=True, maybe=not sure)
            if "u" in _choices(self.vars.get(INTEGER + n, "")):
                self.vars[n] = UNKNOWN

    def readonly_write(self, name: str, how: dict, go, around: bool = False) -> None:
        """A write to `name`, which may be readonly: `how` says what each shell (see `kinds`) then
        does (see READONLY_ASSIGN), and `go(write, failed)` goes on after the write, given whether
        it happened and whether the command fails for it. The error message goes to standard error,
        outside the command's own redirections where `around` (bash's assignments)."""
        state = self.readonly(name)
        if state is False:
            go(True, False)
            return
        self.error_ways(how, go, around, state is None)

    def zsh_special(self) -> str | tuple:
        """What zsh does at a special builtin's error (`readonly` or `export` of a readonly variable,
        `set -o` with an option it lacks): it ends the eval or `.` it is in, else the shell
        ("abort"); under POSIX_BUILTINS (`emulate sh` sets it), the shell ("exit"), measured on
        zsh 5.9. Both where the option may be either."""
        return "abort" if self.posixbuiltins is False else "exit" if self.posixbuiltins else ("abort", "exit")

    def error_ways(self, how: dict, go, around: bool = False, allowed: bool = False) -> None:
        """An error each shell (see `kinds`) meets as `how` says (see READONLY_ASSIGN; a tuple, any of
        its ways), then `go(write, failed)` (see `readonly_write`); `allowed`: the error may not
        happen at all."""
        outcomes: dict[str, bool] = {"allow": False} if allowed else {}  # each with `around`
        for kind in self.kinds():
            for what in how[kind] if isinstance(how[kind], tuple) else (how[kind],):
                if kind in self.unspecial and what in {"exit", "abort"}:
                    what = "fail"
                elif kind == "dash" and self.caught and what == "exit":
                    what = "abort"  # to the `command` (see `prefixed`)
                outcomes[what] = outcomes.get(what, False) or around and kind != "zsh"  # zsh's honours them

        def run(what, out):
            if what == "allow":
                return lambda: go(True, False)
            then = {"skip": lambda: go(False, False), "fail": lambda: go(False, True), "exit": self.leave,
                    "abort": self.abort, "drop": self.drop}[what]
            return lambda: (self.complain(out), then())

        thunks = [run(what, out) for what, out in outcomes.items()]
        thunks[0]() if len(thunks) == 1 else self.either(*thunks)

    def complain(self, around: bool = False) -> None:
        """The shell prints an error message: where standard error may be standard output (also
        outside the command's own redirections, `around`), what the code printed is unknown from here."""
        if self.err_out or around and self.err_around:
            self.noisy += 1
            self.output = None

    def leave(self) -> None:
        """The shell exits in every world. What it printed so far is one way its output may end,
        kept until the shell (or subshell) ends (see `finish`)."""
        if self.worlds:
            self.exits.append([self.output, self.jumped, list(self.worlds), self.state()])
            self.jumped += 1
        self.set_status(EXITED)
        self.set_worlds(self.worlds)

    def may_end(self, worlds: list | None = None) -> None:
        """The shell may end here in `worlds` (every world by default): under `set -e` after a
        command that may have failed, under `set -u` at a parameter that may be unset, where `exec`
        runs a command. What it printed and left so far is one way it may end (see `leave`). The
        audit also goes on from here in every world: it does not follow each place a shell ignores
        -e (an eval in a condition, bash's command substitutions), and exec may fail."""
        ending = list(self.worlds if worlds is None else worlds)
        if not ending:
            return
        live, self.worlds = self.worlds, ending
        try:
            self.leave()
        finally:
            self.worlds = live

    def unbound(self, name: str) -> None:
        """`$name` under `set -u`: expanding an unset parameter ends the shell, as `${name?}` does
        (see `end_unbound`). bash 3.2 takes "$@" with no positional parameters as unset too; `$!` is
        unset before a background job."""
        if self.nounset is False or name in {"#", "?", "$", "-", "0"}:
            return
        count = self.vars.get("#")
        if name in {"@", "*"} or name.isdigit():
            known = count is not None and count.isdigit()
            if known and (int(count) >= int(name) if name.isdigit() else int(count) > 0):
                return
            self.end_unbound()
            return
        raw = self.vars.get(name, self.never_set(name) if IDENTIFIER.fullmatch(name) else UNSET)
        if raw == UNSET or UNKNOWN in raw or "$" in raw or UNSET in _choices(raw):
            self.end_unbound()

    def end_unbound(self, surely: bool = False) -> None:
        """The shell may end at an unset parameter under `set -u` (`surely`: it does, at a failed
        `${name?word}`), printing a message where standard error is (the command's own redirections
        may not be made yet). In words a forked child may expand (`forked_words`), only that child
        may end, the command failing (see `failed_redirect`), so the shell also goes on. Only the
        ending carries the message: where the shell goes on, the child printed it where standard
        error went as the word expanded (see `erring`), which may be standard output (`2>&1 <
        "${x?}"`), and the ending kept alongside then leaves the output unknown."""
        self.child_ends += bool(self.forked_words)
        if surely and not self.forked_words:
            self.complain(around=True)
            self.leave()
            return
        output, noisy = self.output, self.noisy
        self.complain(around=True)
        try:
            self.may_end()
        finally:
            self.output, self.noisy = output, noisy

    def failed_redirect(self) -> None:
        """A command whose redirections or here-document met an unset parameter, under `set -u` or
        at `${name?word}` (see `end_unbound`), may fail without ending the shell. bash 3.2, its sh
        and zsh 5.9 make an external command's redirections, and a subshell's, in the child they
        fork, which alone ends (zsh also an external command's prefix assignments). dash expands a
        here-document in the shell, a subshell's apart, and fails any command but a special
        builtin there. In each, the command does not run, fails, and the shell goes on (measured).
        A file redirection whose open may fail takes this failing way too (see `open_may_fail`).
        At an unset parameter, a builtin's, a function's, a group's or a loop's redirections end
        the shell, as do any command's at a file in dash and a special builtin's at a here-document
        there. The possible file-open failure keeps the shell going conservatively, including
        where a special builtin's redirection error could instead end it.
        The audit takes this way wherever a shell that may run the code does, and follows the
        ending too (see `end_unbound`). What the command's output files then hold is unknown: those
        before the failed one are opened (left empty, or holding the message where standard error
        went there: `cat > out 2>&1 < "${x?}"`), the rest untouched."""
        self.complain(around=True)
        self.set_status(FAILED)

    def trap(self, args: list[str]) -> None:
        """`trap CODE SIGNAL...`. An EXIT trap's code runs when the shell (or subshell) ends (see
        `run_traps`). Other traps' code runs in the shell wherever its signal or event comes (DEBUG
        and ERR before or after commands, RETURN at returns), and zsh runs an EXIT trap set in a
        function at the function's return; the audit runs such code once here, in a subshell, for
        the paths it names, and tells the operator it runs where the audit does not follow.
        `trap - SIGNAL`, `trap '' SIGNAL` and a signal alone reset or ignore it; -l and -p print."""
        if args[:1] == ["--"]:
            args = args[1:]
        if not args or args[0] in {"-l", "-p"}:
            self.output = None
            self.set_status(OK)
            return
        self.output = ""
        code, sigs = args[0], args[1:]
        if not sigs or code in {"-", ""} or re.fullmatch(r"\d+", code):
            self.set_status(OK)
            return
        names = {re.sub(r"^SIG", "", sig.upper()) for sig in sigs}
        exits = names & {"EXIT", "0"}
        if exits:
            self.exit_traps.append(code)
        elsewhere = names - exits or exits and self.locals and "zsh" in self.kinds()
        if elsewhere or exits and self.locals:
            files = dict(self.files)
            with self.child():
                self.evaluate(lambda: self.run(code))
            self.output = ""
            for path, text in list(self.files.items()):
                if files.get(path) != text:
                    self.files[path] = (None,)  # written when the code runs, if it does
        if elsewhere:
            self.notes.append("a trap runs code at points the audit does not follow")
            self.output = None
            self.known = False  # where the shell is after that code
        self.set_status(OK)

    def run_traps(self, mark: int) -> None:
        """At the end of a shell or subshell: the code its EXIT traps may have set may run in every
        world it may end in, including those that exited (from `exits` at `mark` on). It may not
        run: the audit does not tell which branches set a trap, or reset it (`trap - EXIT`). It runs
        with each ending's variables (`trap 'eval "$c"' EXIT; ... && exit; c=:`). What the shell
        printed is then unknown."""
        traps, self.exit_traps = list(dict.fromkeys(self.exit_traps)), []
        if not traps:
            return
        ended = [w for entry in self.exits[mark:] for w in entry[2]]
        # The code runs with the variables, functions and files of the way the shell ended.
        self.join(([self.state()] if self.worlds else []) + [entry[3] for entry in self.exits[mark:]])
        self.set_worlds([w._replace(status=MAYBE) for w in [*self.worlds, *ended]])
        frames, self.frames = self.frames, [*self.frames, _Frame("barrier")]
        try:
            for code in traps:
                self.either(lambda code=code: self.evaluate(lambda: self.run(code)), lambda: None)
        finally:
            self.frames = frames
        self.output = None
        for entry in self.exits[mark:]:
            entry[0] = None

    def finish(self, mark: int) -> None:
        """At the end of a shell or subshell: its output is what it printed where it ran to the end,
        or where it exited (`exits` from `mark` on, which end with it). Files and directories are as
        any of those left them (`( echo a > f; [ -z "$X" ] && exit; echo b > f )` may leave a)."""
        entries = self.exits[mark:]
        if entries:
            self.output = _either_output(([self.output] if self.worlds else []) + [entry[0] for entry in entries])
            states = ([(self.files, self.made, self.removed)] if self.worlds else []) + [
                (entry[3][6], entry[3][1], entry[3][2]) for entry in entries]
            self.files = {path: tuple(dict.fromkeys(a for files, _, _ in states for a in files.get(path, (None,))))
                          for path in set().union(*(files for files, _, _ in states))}
            self.made = set.intersection(*(made for _, made, _ in states))
            self.removed = set.union(*(removed for _, _, removed in states))
        del self.exits[mark:]

    def carry(self, mark: int, before: str | None, plain: bool) -> None:
        """Jumps taken since `mark` (a value of `jumped`), inside a command that started its output
        afresh, left with only what printed inside it: put what came before in front (`plain`), or,
        where the command's redirections route what it printed, take their output as unknown."""
        if self.jumped == mark:
            return
        for frame in self.frames:
            for entries in frame.jumps.values():
                for entry in entries:
                    if entry[2] >= mark:
                        st = entry[1]
                        entry[1] = (*st[:8], _concat(before, st[8]) if plain else None, *st[9:])
        for entry in self.exits:
            if entry[1] >= mark:
                entry[0] = _concat(before, entry[0]) if plain else None

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
                frozenset(self.aliases.items()), frozenset(self.exports.items()), frozenset(self.options().items()))

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
        ran = printed = cut = False
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
                    cut = True
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
                    cut = True
                    break
                self.set_worlds(staying)
                ran = True
                printing = self.output
                body()
                self.rejoin(self.unwind(frame.take("continue"), None))
                printed = printed or self.output != printing
                for ws, st in self.unwind(frame.take("break"), None):
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
        if cut and printed:
            # Passes the audit did not follow, which a repeated state does not show, print more.
            self.output = None
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
                self.rejoin(self.unwind(frame.take("continue"), None))
                for ws, st in self.unwind(frame.take("break"), None):
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

    def pop_locals(self) -> None:
        """At a function's return: its locals, their exports and the positional parameters go back
        to the values they had outside it."""
        for k, old in self.locals.pop().items():
            if isinstance(old, _Restore):  # a local in only some branches (see join)
                alts = [*old.olds, *([self.vars.get(k)] if old.keep else [])]
                values = list(dict.fromkeys(c for a in alts for c in _choices(UNSET if a is None else a)))
                old = None if alts == [None] * len(alts) else values[0] if len(values) == 1 else (
                    "\x06" + "\x05".join(values) + "\x07")
            if old is None:
                self.vars.pop(k, None)
            else:
                self.vars[k] = old
        for name, old in self.local_exports.pop().items():
            if isinstance(old, _Restore):
                alts = set(old.olds) | ({self.exports.get(name)} if old.keep else set())
                old = alts.pop() if len(alts) == 1 else "maybe"
            if old is None:
                self.exports.pop(name, None)
            else:
                self.exports[name] = old

    def call(self, body) -> None:
        """Run a function's body (or a sourced file) in the calling shell; `return` comes back here."""
        frame = _Frame("function")
        self.frames = [*self.frames, frame]
        unspecial, self.unspecial = self.unspecial, frozenset()
        try:
            self.visit(body) if not isinstance(body, str) else self.run(body)
        finally:
            self.frames = self.frames[:-1]
            self.unspecial = unspecial
        self.rejoin(frame.take("return"))

    def arith(self, text: str, command: bool = False) -> int | None:
        """Evaluate shell arithmetic, applying what it assigns; None if the audit cannot, and then
        what it may assign is unknown. `command`: in `((...))` or `let`, not `$((...))` or a C-style
        for (see READONLY_ARITH)."""
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
                fixed = {name for name in assigned if self.readonly(name) is not False}
                if fixed:
                    # A readonly variable keeps its value, and the value is then unknown (it may
                    # be what was assigned, which bash prints). Where it may be writable, the
                    # write may also happen.
                    how = READONLY_ARITH["command" if command else "expansion"]
                    ways = {how[kind] for kind in self.kinds()}
                    if any(self.readonly(name) is None for name in fixed):
                        ways.add("go")
                    runs = {"go": self.complain, "exit": lambda: (self.complain(), self.leave()),
                            "abort": lambda: (self.complain(), self.abort())}
                    thunks = [runs[w] for w in sorted(ways)]
                    thunks[0]() if len(thunks) == 1 else self.either(*thunks)
                    value = None
                kept = [name for name in assigned if name not in fixed]
                made = {name: self.created(name) for name in kept}  # before the assignments
                self.vars.update({name: assigned[name] for name in kept})
                self.numbered(kept, made, text, value is not None)
                for name in kept:
                    self.reshown(name)
        if value is None:
            targets = [name for name in _arith_targets(text) if self.readonly(name) is not True]
            made = {name: self.created(name) for name in targets}
            for name in targets:
                self.vars[name] = UNKNOWN
            self.numbered(targets, made, text, False)
        return value

    # Values

    def expand(self, word: str) -> str:
        def sub(m: re.Match) -> str:
            name = m.group(1)
            # @ and * array references are marked separately from scalar references. A bare
            # array expands to its first element in bash and every element in native zsh.
            array_ref = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\[([@*Q])\]", name)
            if array_ref:
                if array_ref[1] not in self.vars and self.inherit and array_ref[2] != "Q":
                    return "$" + array_ref[1]  # as `$name`: the environment may give it (one word)
                if array_ref[2] == "Q" and _array_values(self.vars.get(array_ref[1], UNSET)) is None:
                    raw = self.vars.get(array_ref[1], UNSET)
                    if ARRAY_OPEN in raw:
                        self.notes.append("an array has different possible values the audit cannot expand")
                        return UNKNOWN
                    # A quoted scalar follows the ordinary lookup, including PWD/OLDPWD/HOME.
                    return sub(_VAR.fullmatch("\x01" + array_ref[1] + "\x02"))
                raw = self.vars.get(array_ref[1], UNSET)
                values = _array_values(raw)
                if values is None:
                    values = [] if raw == UNSET else [raw]
                separator = " " if self.ifs() is None else self.ifs()[:1]
                if array_ref[2] == "Q":
                    bash = values[0] if values else ""
                    zsh = separator.join(values)
                    if self.dialect == "posix" or self.ksharrays is True:
                        return bash
                    if self.dialect == "zsh" and self.ksharrays is False:
                        return zsh
                    if bash != zsh:
                        self.notes.append("a quoted array expansion differs between possible shells")
                        return UNKNOWN
                    return bash
                return SPLIT.join(values) if array_ref[2] == "@" else separator.join(values)
            if name == "PWD":
                if "\0PWD" in self.vars:
                    return "" if self.vars["\0PWD"] == UNSET else self.vars["\0PWD"]
                return self.pwd()
            if name == "OLDPWD":
                if "\0OLDPWD" in self.vars:
                    return "" if self.vars["\0OLDPWD"] == UNSET else self.vars["\0OLDPWD"]
                if self.slashed_text():
                    return UNKNOWN
                return ("" if self.vars.get("OLDPWD") == UNSET else "$OLDPWD") if self.oldpwd is None else str(self.oldpwd)
            if name == "SHELLOPTS" and self.shell_name in {"bash", "sh"}:
                return self.shellopts()
            if name == "*" and "@" in self.vars:
                ifs = self.vars.get("IFS")
                return self.vars["@"].replace(SPLIT, " " if ifs is None else ifs[:1])
            if name in self.vars:
                value = self.vars[name]
                if value == UNSET:
                    return ""
                if UNSET in value and CHOICE.search(value):  # unset in some branches
                    values = list(dict.fromkeys("" if c == UNSET else c for c in _choices(value)))
                    value = values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"
                values = _array_values(value)
                if values is None and ARRAY_OPEN in value:
                    self.notes.append("an array has different possible values the audit cannot expand")
                    return UNKNOWN
                if values is not None:
                    bash = values[0] if values else ""
                    zsh = SPLIT.join(values)
                    if self.dialect == "posix" or getattr(self, "ksharrays", False) is True:
                        return bash
                    if self.dialect == "zsh":
                        return zsh
                    if bash != zsh:
                        self.notes.append("an array expansion differs between bash and zsh")
                        return UNKNOWN
                    return bash
                return value
            if name == "HOME" and self.inherit:
                return str(HOME)
            return "$" + name if self.inherit else ""

        result = _VAR.sub(sub, word)
        return _LiteralWord(result) if isinstance(word, _LiteralWord) else result

    def tilde(self, word: str, world: _World | None = None) -> str:
        """Expand an unquoted tilde prefix against its own world's PWD, OLDPWD and stack."""
        if TILDE not in word:
            return word
        if world is None:
            values = list(dict.fromkeys(("" if w.primary else ALT) + self.tilde(word, w) for w in self.worlds))
            return values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07" if values else UNKNOWN
        prefix, slash, suffix = word[1:].partition("/")
        base = None
        if prefix == "~":
            base = self.home()
        elif prefix == "~+":
            base = str(world.cwd)
        elif prefix == "~-":
            base = str(world.oldpwd) if world.oldpwd is not None else None
        elif re.fullmatch(r"~[+-]?\d+", prefix):
            text = prefix[1:]
            n = int(text.lstrip("+-"))
            dirs = self._dirs(world)
            k = len(dirs) - 1 - n if text.startswith("-") else n
            base = str(dirs[k]) if 0 <= k < len(dirs) else None
        if prefix != "~" and self.slashed_text():
            base = None
        if prefix in {"~+", "~-"}:
            name = "PWD" if prefix == "~+" else "OLDPWD"
            override = self.vars.get("\0" + name)
            if override is not None and self.dialect != "zsh":
                if self.dialect is None:
                    self.notes.append("a directory tilde depends on an overridden shell variable")
                    return UNKNOWN
                if override == UNSET:
                    return prefix + (slash + suffix if slash else "")
                base = override
        if base is None:
            self.notes.append("a tilde directory prefix the audit cannot expand")
            return UNKNOWN + (slash + suffix if slash else "")
        return str(base) + (slash + suffix if slash else "")

    def home(self) -> str | None:
        """Where `cd` with no operand goes: $HOME, or None where it is unset."""
        value = self.expand("\x01HOME\x02")
        return value or None

    def slashed_text(self) -> bool:
        """Whether the text of a directory the shell is in, or was in, may start with `//`, which
        the audit does not keep (macOS reads it as `/`; see `_normpath`)."""
        return self.slashed and self.kinds() != ["zsh"]

    def pwd(self) -> str:
        """$PWD: the directory of each place the shell could be (a choice, where there are several,
        whose alternatives from alternative places carry ALT)."""
        if self.slashed_text():
            return UNKNOWN
        places: dict[Path, bool] = {}
        for w in self.worlds:
            places[w.cwd] = places.get(w.cwd, False) or w.primary
        texts = [str(c) if primary else ALT + str(c) for c, primary in places.items()] or [str(self.workdir)]
        return texts[0] if len(texts) == 1 else "\x06" + "\x05".join(texts) + "\x07"

    def bind(self, args: list[str], zero: str | None = None) -> None:
        """Set the positional parameters ($0 to $9, $#, $@ and $*)."""
        args = [self.tilde(a) for a in args]
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
            text = re.sub(r"\\(.)", lambda m: Q_OPEN + m.group(1) + Q_CLOSE, _text(node), flags=re.S)
            first = node.parent is None or node.parent.type != "concatenation" or node.parent.children[0] == node
            return TILDE + text if text.startswith("~") and first else text
        if t == "brace_expression":
            return _text(node)
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
            array_at = re.fullmatch(r'"\$\{([A-Za-z_][A-Za-z0-9_]*)\[@\]\}"', _text(node))
            raw = self.vars.get(array_at[1]) if array_at else None
            unset = array_at is not None and (raw == UNSET or raw is None and not self.inherit)
            if array_at and (raw is not None and _array_values(raw) == [] or unset and self.dialect == "posix"):
                return ""  # An empty array's quoted @ expansion is no word, like "$@".
            if unset and self.dialect != "zsh":
                # An unset variable's is no word in bash and one empty word in zsh (measured on
                # bash 3.2 and zsh 5.9).
                self.notes.append("a quoted array expansion differs between possible shells")
                return UNKNOWN
            # Build from the source span: the grammar leaves some characters (newlines among them)
            # outside every child node.
            src, base = node.text, node.start_byte
            pos, end = (2 if t == "translated_string" else 1), len(src) - 1
            parts = []
            for c in node.named_children:
                cs, ce = c.start_byte - base + _lead(c), c.end_byte - base
                if cs > pos:
                    parts.append(_unquote_double(src[pos:cs]))
                if c.type == "string_content":
                    parts.append(_unquote_double(c.text))
                elif c.type in {"simple_expansion", "expansion"} and _text(c) in {"$*", "${*}"}:
                    self.unbound("*")
                    parts.append("\x01*\x02")  # "$*": the parameters joined by IFS's first character
                elif c.type == "expansion" and re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\[\*\]\}", _text(c)):
                    self.unbound(_text(c)[2:-4])
                    parts.append("\x01" + _text(c)[2:-1] + "\x02")
                elif c.type in {"simple_expansion", "expansion"} and (m := re.fullmatch(
                        r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", _text(c))):
                    # In native zsh "$a" joins an array at IFS's first character; bash keeps
                    # the first element. Quoted "${a[@]}" is handled separately above.
                    self.unbound(m[1])
                    parts.append("\x01" + m[1] + "[Q]\x02")
                else:
                    parts.append(self.value(c))
                pos = max(pos, ce)
            if end > pos:
                parts.append(_unquote_double(src[pos:end]))
            return Q_OPEN + "".join(parts) + Q_CLOSE
        if t == "simple_expansion":
            name = node.named_children[0] if node.named_children else None
            if name is not None and name.type in {"variable_name", "special_variable_name"}:
                self.unbound(_text(name))
                # Unquoted, $* is one word per parameter before splitting, like $@.
                listed = LIST if _text(name) in {"@", "*"} else ""
                return FIELD + listed + "\x01" + ("@" if _text(name) == "*" else _text(name)) + "\x02" + FIELD_END
            return FIELD + UNKNOWN + FIELD_END
        if t == "expansion":
            text = _text(node)
            m = re.fullmatch(r"\$\{#?([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-])(.*)\}", text, re.S)
            if m and not re.match(r":?[-=+?]", m[2]) and not text.startswith("${#}"):
                self.unbound(m[1])  # all but the forms with a default, an assignment, `+` or `?`
            m = re.fullmatch(r"\$\{(#?)([A-Za-z_][A-Za-z0-9_]*)\[([@*])\]\}", text)
            if m:
                name = m[2]
                raw = self.vars.get(name, UNSET)
                values = _array_values(raw)
                if m[1]:
                    if values is not None:
                        value = str(len(values))
                    elif raw == UNSET:
                        value = "0"
                    elif self.dialect == "zsh":
                        value = str(len(raw))
                    elif self.dialect == "posix":
                        value = "1"
                    else:
                        self.notes.append("the length of a scalar array reference differs between shells")
                        value = UNKNOWN
                    return FIELD + value + FIELD_END
                # Unquoted * splits into elements as @ does; quoted * is joined above.
                return FIELD + LIST + "\x01" + name + "[@]\x02" + FIELD_END
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#])\}", text)
            if m:
                listed = LIST if m.group(1) in {"@", "*"} else ""
                return FIELD + listed + "\x01" + ("@" if m.group(1) == "*" else m.group(1)) + "\x02" + FIELD_END
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*|[0-9]+)(:?[\-=+?])(.*)\}", text, re.S)
            if m:
                name, op = m[1], m[2]
                raw = self.vars.get(name, UNSET)
                array = _array_values(raw)
                if array is not None:
                    if self.dialect == "posix" or self.ksharrays is True:
                        raw = array[0] if array else UNSET
                    elif self.dialect == "zsh":
                        raw = SPLIT.join(array)  # Empty zsh arrays are set, but null for : operators.
                    else:
                        self.notes.append("a parameter default on an array differs between possible shells")
                        return FIELD + UNKNOWN + FIELD_END
                if name not in self.vars and name in INHERITED and self.inherit:
                    raw = self.expand("\x01" + name + "\x02")
                elif name not in self.vars and IDENTIFIER.fullmatch(name) and self.never_set(name) == UNKNOWN:
                    # Set or not as the shell or its environment gives it (CLAUDECODE, SHLVL, OPTARG):
                    # the shell may end at `?` and goes on with a value the audit does not know.
                    for c in node.named_children[1:]:
                        self.value(c)
                    if op.endswith("?"):
                        self.end_unbound()
                    elif op.endswith("="):
                        self.set_var(name, UNKNOWN)
                    return FIELD + UNKNOWN + FIELD_END
                unknown = raw != UNSET and (UNKNOWN in raw or CHOICE.search(raw) or "$" in raw)
                if unknown:
                    self.notes.append("a parameter expansion depends on an unknown variable value")
                    if op.endswith("="):
                        self.vars[name] = UNKNOWN
                    return FIELD + UNKNOWN + FIELD_END
                missing = raw == UNSET or (op.startswith(":") and raw == "")
                use_word = not missing if op.endswith("+") else missing
                if op.endswith("?") and missing:
                    # Noninteractive shells exit during expansion; neither the command nor a
                    # later command runs (including one after an && or ||).
                    if self.dialect != "zsh":
                        # Bash expands diagnostic words; native zsh prints their source.
                        if self.dialect is None:
                            with self.child():
                                self.worlds = [w._replace(primary=False) for w in self.worlds]
                                for c in node.named_children[1:]:
                                    self.value(c)
                        else:
                            for c in node.named_children[1:]:
                                self.value(c)
                    self.end_unbound(surely=True)  # an EXIT trap still runs; the files are as they are
                    return ""
                if use_word:
                    # The default word's substitutions run only when the default is used.
                    parts = node.named_children[1:]
                    if self.dialect != "posix" and m[3].count("{") != m[3].count("}"):
                        # The bash grammar closes this expansion at the first brace, whereas
                        # zsh can nest a brace list in its default word. Do not mistake the
                        # grammar's bash reading for zsh's value or side effect.
                        self.notes.append("a nested parameter default the audit cannot parse for zsh")
                        if op.endswith("="):
                            self.set_var(name, UNKNOWN)
                        return FIELD + UNKNOWN + FIELD_END
                    value = self.tilde(self.expand("".join(self.value(c) for c in parts)))
                    if op.endswith("="):
                        self.set_var(name, value)
                    return FIELD + value + FIELD_END
                return FIELD + ("" if op.endswith("+") else self.expand("\x01" + name + "\x02")) + FIELD_END
            for c in node.named_children:
                self.value(c)  # runs any command substitution inside
            if "[" in text:
                self.notes.append("an array parameter expansion the audit cannot model")
            return FIELD + UNKNOWN + FIELD_END
        if t == "command_substitution":
            return FIELD_CMD + self.substitute(node) + FIELD_END
        if t == "process_substitution":
            # `<(code)` expands to a name (/dev/fd/N, its number unknown) that reads as what the
            # code prints; `>(code)` to one whose writes are the code's standard input, and what the
            # code prints goes to the shell's standard output, at no point the audit can tell.
            if self.dialect != "zsh" and (self.shell_name in {"sh", "dash"} or self.posix is not False):
                # A syntax error in POSIX-mode bash and in dash, which ends the shell before the line
                # runs: what it prints is unknown. Its paths still count.
                self.exits.append([None, self.jumped, list(self.worlds), self.state()])
                self.jumped += 1
            reading = _text(node).startswith("<")
            self.feeding += reading  # what it prints reaches the command that reads it, not this output
            before, self.output = self.output, ""
            try:
                with self.child():
                    self.diverted = None
                    stmts = [c for c in node.named_children if c.type in STATEMENTS]
                    for c in stmts if reading else []:
                        self.visit(c)
                    if not reading and stmts:
                        self.statement(stmts[0], None) if len(stmts) == 1 else [self.visit(c) for c in stmts]
            finally:
                self.feeding -= reading
                out, self.output = self.output, before if reading else None
            name = "/dev/fd/" + UNKNOWN + str(len(self.substituted))
            self.substituted[name] = out if reading else None
            return name
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
        before, self.output = self.output, ""
        self.feeding += 1
        try:
            with self.child(), self.guarding(False):
                self.diverted, self.out_closed = None, False  # its standard output is the substitution's
                for c in node.named_children:
                    self.visit(c)
        finally:
            self.feeding -= 1
        out, self.output = self.output, before
        if out is not None and CHOICE.search(out):
            return _either_text([c.rstrip("\n") for c in _choices(out)])
        return UNKNOWN if out is None else out.rstrip("\n")

    # Paths

    def resolve(self, word: str, bare: bool) -> Path | None:
        return _resolve(self.tilde(self.expand(word), self.worlds[0] if self.worlds else None), self.cwd, bare=bare)

    def resolve_all(self, word: str, bare: bool) -> list[tuple[Path, bool]]:
        """The word as a path from each world: (path, primary)."""
        out: dict[Path, bool] = {}
        for text in _choices(self.expand(word)):
            text, alt = _alt(text)
            for w in self.worlds:
                p = _resolve(self.tilde(text, w), w.cwd, bare=bare)
                if p is not None:
                    out[p] = out.get(p, False) or (w.primary and not alt)
        return list(out.items())

    def reach(self, path: Path, primary: bool) -> None:
        (self.paths if primary else self.alt_paths).append(path)

    def add(self, word: str, bare: bool, chdirs: tuple = (), chdir_bare: bool = False,
            operand: bool | None = None) -> Path | None:
        """Record the word as a path from every world, and from the directories `chdirs` lead to
        from each (a command's own `-C dir`, a literal `os.chdir` in code); with `chdir_bare`, a
        plain name counts as a path from those. Returns the path from the first world. `operand`
        (by default `bare`): the command takes the word as a file, so a word the audit cannot work
        out at all could be any path; elsewhere (a value assigned, a test's operand, a function's
        argument) it is a word the code may later use, where the audit follows it."""
        operand = bare if operand is None else operand
        literal = isinstance(word, _LiteralWord) or getattr(self, "noglob", False) is True
        text = self.expand(word)
        if TILDE in text:
            # Keep the tilde's source world correlated with its directory, rather than taking
            # the product of every OLDPWD/stack with every possible current directory.
            saved = self.worlds
            found = []
            try:
                for w in saved:
                    self.worlds = [w]
                    target = self.tilde(text, w)
                    found.append(self.add(_LiteralWord(target) if literal else target, bare, chdirs, chdir_bare,
                                          operand))
            finally:
                self.worlds = saved
            return next((f for f in found if f is not None), None)
        if CHOICE.search(text):
            found = [self.add(c, bare, chdirs, chdir_bare, operand) for c in _choices(text)]
            return next((f for f in found if f is not None), None)
        text, alt = _alt(text)
        if UNKNOWN in text:
            # A path with a part the audit cannot work out (`../$(ls ..)/x`) could be any path of
            # that shape: as a pattern, it is reported if it could reach a protected place. One
            # with no known shape (`$(...)` whose output the audit does not know) could be any path.
            if "/" in text.replace(UNKNOWN, "") and not text.lstrip("'\"").startswith(UNKNOWN):
                pattern = re.sub(UNKNOWN + "+", "*", text)
                for w in self.worlds:
                    p = _resolve(pattern, w.cwd, bare=True)
                    if p is not None:
                        self.unknown_paths.append(p)
            elif operand:
                self.notes.append("a path the audit cannot work out")
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
                # With noglob the wildcard is an ordinary filename. A divergent option
                # state keeps the possible expansion for a person to inspect.
                glob_mode = getattr(self, "noglob", False)
                expanded = [p] if literal else _expand(p)
                if literal:
                    self.literal_paths.add(p)
                if glob_mode is None and expanded != [p]:
                    self.notes.append("pathname expansion depends on a shell option")
                for q in expanded:
                    if glob_mode is None and q != p:
                        self.alt_paths.append(q)
                        continue
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

    def run(self, text: str, stdin: str | None = None, alias: bool = False) -> None:
        """Run shell code. An alias's text (`alias`) is part of the line it is used on: its last
        line runs on into the rest of that line (see `lines`)."""
        data, negate, added = _parseable(text.encode())
        if added:
            self.added[data] = added
        tree = _BASH.parse(data)
        if (tree.root_node.has_error or _reserved_commands(tree.root_node) or _misread_backslashes(data)
                or _misread_heredocs(data, tree.root_node)):
            self.notes.append("part of a command the audit could not parse")
        saved, self.negate = self.negate, negate
        try:
            statements = [c for c in tree.root_node.named_children if c.type != "comment"]
            if stdin is not None and len(statements) == 1 and statements[0].type in {
                    "command", "redirected_statement", "while_statement", "pipeline"}:
                self.statement(statements[0], stdin)
            else:
                if stdin is not None:
                    def nodes(n):
                        yield n
                        for child in n.named_children:
                            yield from nodes(child)
                    all_nodes = list(nodes(tree.root_node))
                    readers = any(self._reads_names(n) or self._command_name(n) == "read" for n in all_nodes)
                    pure = {"echo", "printf", "read", "true", "false", ":", "pwd", "set", "shift"}
                    if readers and any(n.type == "command" and self._command_name(n) not in pure
                                       for n in all_nodes):
                        self.notes.append("shell code may use inherited input as filenames; its consumption is unresolved")
                        self.worlds = [w._replace(primary=False) for w in self.worlds]
                if alias:
                    self.lines(tree.root_node, alias=True)
                else:
                    self.visit(tree.root_node)
            if tree.root_node.has_error:
                self.output = None  # what the unparsed part prints is unknown
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
            with self.guarding():
                self.visit(node)
            swap = {OK: FAILED, FAILED: OK}
            self.worlds = [w._replace(status=swap.get(w.status, w.status)) for w in self.worlds]
            return  # `set -e` does not end the shell after `!`
        after = node.next_sibling
        if node.type in STATEMENTS and after is not None and after.type == "&":
            self.background(node)
            return
        if node.type in STATEMENTS and (self.xtrace is not False or self.verbose is not False):
            # Under `set -x` the shell writes the command to its standard error before the command's
            # own redirections; under `set -v` bash writes the code an eval or `.` reads (measured).
            self.complain()
        self._visit(node)
        self.errexit_end(node)

    def errexit_end(self, node) -> None:
        """`set -e` (errexit): after a statement that may have failed, the shell may end (see
        `may_end`), except where the shells ignore -e: each command of an and-or list but the last,
        the conditions of if, while and until, and a command after `!`, with what they run (see
        `guarding`). A function or eval whose status comes from a `!` ends bash, sh and dash, and
        not zsh, which the audit takes to end as well (measured on bash 3.2, sh, dash and zsh 5.9).
        An and-or list ends by its last command, and a compound command by the commands inside
        it."""
        if self.errexit is False or self.guarded:
            return
        if node.type not in ERREXIT_STATEMENTS:
            return
        self.may_end([w for w in self.worlds if w.status in (FAILED, MAYBE)])

    def background(self, node) -> None:
        """A statement before `&` runs in a subshell, and the shell goes on with status 0. zsh is the
        exception for an and-or list: it runs the list's last pipeline in the background and the
        pipelines before it in the current shell, so `cd a && make &` leaves zsh in a."""
        def whole():
            with self.child():
                self._visit(node)
            self.set_status(OK)

        body = _body(node)
        redirects = [c for c in node.named_children if c.type in REDIRECTS] if body is not node else None

        def split():
            self.and_or(body, redirects, None, background=True)

        before, self.output = self.output, ""
        try:
            if body.type != "list" or self.dialect == "posix":
                whole()
            elif self.dialect == "zsh":
                split()
            else:
                self.either(whole, split)
        finally:
            # What a background job prints interleaves with what follows, at no known point.
            self.output = before if self.output == "" else None

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
            self.negated(node)
        elif t == "if_statement":
            self.branches(self.if_clauses(node))
        elif t == "while_statement":
            self.while_loop(node)
        elif t == "case_statement":
            self.case(node)
        elif t == "c_style_for_statement":
            self.c_style_for(node)
        elif t == "compound_statement" and node.children and _text(node.children[0]) == "((":
            # `(( expr ))`: true where the expression is not 0. dash has no such command: there it
            # is a subshell in a subshell, running the text as a command (`(( cat f ))` reads f).
            def arithmetic():
                self.substitutions(node)
                v = self.arith(_text(node)[2:-2], command=True)
                self.set_status(MAYBE if v is None else OK if v else FAILED)

            kinds = self.kinds()
            dash = lambda: self.run("(" + _text(node)[2:-2] + ")")
            arithmetic() if "dash" not in kinds else dash() if kinds == ["dash"] else self.either(arithmetic, dash)
        elif t == "function_definition":
            name = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if body is not None:
                if name is not None:
                    self.functions[_text(name)] = (body,)
                    if self.sticky is not None:
                        self.sticky_functions[id(body)] = (body, self.sticky)
                before = self.output
                kept = dict(self.files), set(self.made), set(self.removed), self.pending
                with self.child():  # paths in a function that is never called still count
                    self.locals.append({k: self.vars.get(k) for k in POSITIONAL})  # as a call has
                    self.local_exports.append({})
                    self.call(body)
                self.output = before  # defining it prints nothing, and writes and makes nothing
                self.files, self.made, self.removed, self.pending = kept  # `wrote_ever` keeps its writes
            self.set_status(OK)
        elif t == "variable_assignment":
            self.assignments(node, [node])
        elif t == "variable_assignments":
            self.assignments(node, node.named_children)
        elif t == "declaration_command":
            words = [_text(c) for c in node.children]
            if words and not self.quiet(words[0], words[1:]):
                # A listing form, or zsh's `typeset x`, which prints x.
                listed = self.listing(words[0], words[1:]) if self.dialect != "posix" else None
                shown = None if listed is None else listed if self.dialect == "zsh" else _either_output(["", listed])
                self.output = _concat(self.output, shown)
            self.declare(node)
        elif t == "unset_command":
            self.unset([self.expand(self.value(c)) for c in node.named_children])
        elif t == "for_statement":
            self.for_loop(node)
        elif t == "test_command":
            def test():
                saved, self.memo = self.memo, {}
                try:
                    self.test_command(node)
                finally:
                    self.memo = saved

            def missing():
                # dash has no `[[`: it expands the words for a program it does not find (127).
                self.substitutions(node)
                self.complain()
                self.set_status(FAILED)

            kinds = self.kinds()
            if not _text(node).startswith("[[") or "dash" not in kinds:
                test()
            else:
                missing() if kinds == ["dash"] else self.either(test, missing)
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
        elif t == "program":
            self.lines(node)
        else:
            self.set_status(MAYBE)  # `(( x ))` and the like leave a status the audit cannot tell
            for c in node.named_children:
                self.part(c)

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
                ways = [_fields(marked, self.ifs(), p, bash=b) for p, b in self.field_modes()]
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
                with self.child() if last and background else self.guarding() if not last else nullcontext():
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
        with self.guarding():
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
                    self.bind_read(names, line, prefix.get("IFS", self.ifs()))
                    self.set_status(OK)
                return setup

            lines = stdin.splitlines()
            if len(lines) <= 4 * MAX_PASSES:
                self.each([bind(line) for line in lines], body, end=bind(""))
                self.set_status(OK)
                return
        if body is None:
            with self.guarding():
                for c in conds:
                    self.visit(c)
            self.set_status(MAYBE)
            return

        def test():
            self.set_status(MAYBE)
            with self.guarding():
                for c in conds:
                    self.visit(c)

        self.loop(test, lambda: self.visit(body), FAILED if until else OK)

    def bind_read(self, names: list[str], line: str | None, ifs: str | None = None) -> None:
        """What `read NAME...` sets from one line (None: a line the audit does not know), split at
        IFS (`ifs`: its value, None where unset)."""
        ifs = " \t\n" if ifs in (None, UNSET) else ifs
        if line is None or UNKNOWN in ifs or CHOICE.search(ifs) or "$" in ifs:
            for name in names:
                self.store(name, UNKNOWN)
            return
        ways = {"posix": [True], "zsh": [False]}.get(self.dialect, [True, False])  # bash's way, zsh's
        values = [_read_fields(line, ifs, len(names), bash=b) for b in ways]
        for k, name in enumerate(names):
            alts = list(dict.fromkeys(v[k] for v in values))
            self.store(name, alts[0] if len(alts) == 1 else "\x06" + "\x05".join(alts) + "\x07")

    def store(self, name: str, value: str) -> None:
        """What read and for set a variable to: arithmetic where it is an integer (see `set_number`)."""
        if self.integer(name) is False:
            self.vars[name] = value
            self.reshown(name)
        else:
            self.set_var(name, value)

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
        # The complete list expands before the first iteration. In particular, ~+ and ~- do
        # not change their values when an earlier iteration changes directory.
        lists = [[type(value)(self.tilde(value)) for value in values] for values in lists]
        if len(lists) == 1:
            self.for_items(name, lists[0], node)
        else:
            self.either(*(lambda items=items: self.for_items(name, items, node) for items in lists))

    def for_items(self, name: str | None, items: list[str], node, checked: bool = False) -> None:
        if name is not None and items and not checked and self.readonly(name) is not False:
            # A readonly loop variable: bash fails the loop before its first pass (READONLY_FOR).
            self.readonly_write(name, READONLY_FOR, lambda write, failed: self.set_status(FAILED) if failed else
                                self.for_items(name, items, node, True))
            return
        for item in items:
            self.add(item, bare=False)
        body = node.child_by_field_name("body")
        if body is None:
            return

        def bind(value):
            def setup():
                if name is not None:
                    self.store(name, self.tilde(value))
            return setup

        if any(any(c in x for c in "$\x06" + UNKNOWN) for x in items):
            self.loop(lambda: self.set_status(MAYBE), lambda: (bind(UNKNOWN)(), self.visit(body)), OK)
            return
        noglob = getattr(self, "noglob", False)
        globbed = noglob is not True and any(not isinstance(x, _LiteralWord) and any(c in x for c in "*?[") for x in items)
        if noglob is None and globbed:
            self.notes.append("a for list's pathname expansion depends on a shell option")
            self.either(lambda: self.for_items_mode(name, items, node, True),
                        lambda: self.for_items_mode(name, items, node, False))
            return
        values: list[str] = []
        for item in items:
            p = self.resolve(item, bare=True) if noglob is not True and not isinstance(item, _LiteralWord) and any(c in item for c in "*?[") else None
            values += [str(x) for x in _expand(p)] if p is not None else [item]
        if len(values) > 4 * MAX_PASSES:
            self.loop(lambda: self.set_status(MAYBE), lambda: (bind(UNKNOWN)(), self.visit(body)), OK)
        elif globbed:
            self.set_status(MAYBE)
            self.fork(lambda: self.each([bind(v) for v in values], body), OK)  # the matches may differ
        else:
            self.each([bind(v) for v in values], body)

    def for_items_mode(self, name: str | None, items: list[str], node, noglob: bool) -> None:
        saved, self.noglob = self.noglob, noglob
        try:
            self.for_items(name, items, node)
        finally:
            self.noglob = saved

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
        flags, names, options = "", [], True
        # Every word expands, values included, before the builtin assigns any (`a=0; export a=1
        # b=$a` sets b to 0, and a command substitution in a value runs even where the
        # declaration then fails or ends the shell): `assign` takes the values from here.
        saved, self.prevalued = self.prevalued, dict(self.prevalued)
        try:
            for c in node.named_children:
                if c.type == "variable_assignment":
                    options = False
                    names.append(c)
                    if (n := c.child_by_field_name("name")) is not None and n.type != "subscript":
                        self.prevalued[c] = self.assignment_value(c)
                elif c.type in {"word", "variable_name", "string", "raw_string", "concatenation", "simple_expansion",
                                "expansion", "number"}:
                    w = self.expand(self.value(c))
                    if options and w == "--":
                        # After it a word that starts with `-` is a name, and a number no option's
                        # argument (`typeset -i -- 16 p`); it stays last among the options.
                        flags, options = flags + "--", False
                    elif options and w.startswith(("-", "+")) and len(w) > 1:
                        flags += w
                    else:
                        options = False
                        names.append(w)
            self.declaration(keyword, flags, names, _assignment_status(node))
        finally:
            self.prevalued = saved

    def declaration(self, keyword: str, flags: str, names: list, ok: str = OK, checked: bool = False) -> None:
        """What a declaration does (see `declare`), setting the status (`ok` where nothing fails);
        each of `names` is an assignment node or a word. `readonly` and `-r` make the variables
        readonly, zsh's `+r` writable again. A write to a readonly variable is an error (see
        `readonly_write`): a value, a new local (bash), `+r` (bash); zsh makes the new local.

        Options a shell does not take (see `_declaration_takes`) make it do nothing: bash and zsh
        fail, and sh and dash exit at export and readonly, special builtins (unless `command` runs
        them, see `prefixed`, or, in sh, `guarding` holds); dash has no declare or typeset. bash's
        readonly -n assigns without making the variable readonly, and a `+` word after its export
        or readonly is a name, one that fails. A word that is certainly not a name fails bash's
        declaration (the others still count), ends dash there, and ends zsh's eval or shell after
        the others (zsh's option argument aside, see `numbered`). `checked`: the options are known
        to be taken."""
        kinds = self.kinds()
        refused = {k for k in kinds if k == "dash" and keyword in {"declare", "typeset"}
                   or not _declaration_takes(k, keyword, flags)}
        plus = keyword in {"export", "readonly"} and "+" in flags and any(k != "zsh" for k in kinds)
        if not checked and (refused or plus):
            runs = {}
            for kind in kinds:
                if kind in refused:
                    special = kind in {"posix", "dash"} and keyword in {"export", "readonly"}
                    if special and kind == "dash" and self.caught:
                        runs["abort"] = lambda: (self.complain(), self.abort())
                    elif special and kind not in self.unspecial and not (kind == "posix" and self.guarded):
                        runs["exit"] = lambda: (self.complain(), self.leave())
                    else:
                        runs["fail"] = lambda: (self.complain(), self.set_status(FAILED))
                elif kind == "zsh":
                    runs["zsh"] = lambda: self.as_dialect(
                        "zsh", lambda: self.declaration(keyword, flags, names, ok, True))
                elif plus:
                    def named():
                        # The `+` words are names, which fail; the rest of the declaration holds.
                        bare = re.sub(r"\+[A-Za-z0-9]*", "", flags)
                        self.as_dialect("posix", lambda: self.declaration(keyword, bare, names, ok, True))
                        self.set_status(FAILED)
                    runs["plus"] = named
                else:
                    runs["bash"] = lambda: self.as_dialect(
                        "posix", lambda: self.declaration(keyword, flags, names, ok, True))
            thunks = list(runs.values())
            thunks[0]() if len(thunks) == 1 else self.either(*thunks)
            return
        if keyword == "local" and not self.locals:
            def outside(then):
                # The arguments expand (see `declare`) before the shell reports local's missing
                # function scope: bash then fails it, dash exits.
                def run():
                    self.complain()
                    then()
                return run

            bash = outside(lambda: self.set_status(FAILED))
            if self.dialect == "posix":
                kinds = self.kinds()
                dash = outside(self.leave)
                if kinds == ["dash"]:
                    dash()
                elif "dash" in kinds:
                    self.either(bash, dash)
                else:
                    bash()
                return
            if self.dialect is None:
                self.either(bash, lambda: self.declaration("typeset", flags, names, ok))
                return
        if keyword == "readonly" and self.locals and "g" not in flags and self.dialect is None:
            # zsh's readonly in a function makes a local, bash's a global.
            self.either(*(lambda d=d: self.as_dialect(d, lambda: self.declaration(keyword, flags, names, ok))
                          for d in ("posix", "zsh")))
            return
        if keyword == "readonly" and self.locals and self.dialect == "zsh" and self.posixbuiltins is None:
            # Unless POSIX_BUILTINS is set, which may be so here (see `scoped`).
            def as_set(on):
                def run():
                    saved, self.posixbuiltins = self.posixbuiltins, on
                    try:
                        self.declaration(keyword, flags, names, ok)
                    finally:
                        self.posixbuiltins = saved
                return run
            self.either(as_set(True), as_set(False))
            return
        unexport = (keyword == "export" and "n" in flags.lstrip("-")) or "+x" in flags
        export = not unexport and (keyword == "export" or ("x" in flags and "-" in flags))
        functions = "f" in flags.lstrip("-+")
        on = set("".join(re.findall(r"-([A-Za-z]+)", flags)))
        off = set("".join(re.findall(r"\+([A-Za-z]+)", flags)))
        # zsh's readonly is `typeset -r`, local in a function, except under POSIX_BUILTINS (`emulate
        # sh` or ksh sets it), where it is `typeset -gr` (measured on zsh 5.9).
        scoped = bool(self.locals) and "g" not in flags and (
            keyword in {"local", "declare", "typeset"}
            or keyword == "readonly" and self.dialect == "zsh" and self.posixbuiltins is False)
        # A number first among the names, after an option that takes one, is zsh's option argument
        # (`typeset -i 16 p`: the base; -E and -F: the precision; -L, -R and -Z: the width).
        numbered = bool(names) and isinstance(names[0], str) and names[0].isdigit() and flags[-1:] in set("EFLRZi")
        items, misnamed = [], []  # for each word that is not a name, whether zsh takes it (`numbered`)
        for k, item in enumerate(names):
            if isinstance(item, str):
                m = ASSIGN.match(item)
                name, value = (m.group(1), m.group(2)) if m else (item, None)
            else:
                n = item.child_by_field_name("name")
                if n is None:
                    continue
                name, value = _text(n), None
            if IDENTIFIER.fullmatch(name):
                items.append((item, name, value))
            elif re.fullmatch(r"[^$\0-\x1f]+", name) and not (
                    isinstance(item, str) and re.match(r"[A-Za-z_][A-Za-z0-9_]*\+=", item)):
                # Certainly not a name (`1x`, `a-b`), but for zsh's option argument: see `rest`.
                zsh_takes = k == 0 and numbered
                if not (zsh_takes and self.kinds() == ["zsh"]):
                    items.append((item, None, zsh_takes))
                    misnamed.append(zsh_takes)

        def one(item, name, value):
            if functions:
                if export:
                    self.func_exports.add(name)
                elif unexport:
                    self.func_exports.discard(name)
                return
            new_local = scoped and name not in self.locals[-1]
            old = self.vars.get(name)
            absent = self.absent(name)
            if new_local:
                self.locals[-1][name] = old
                self.locals[-1][READONLY + name] = self.vars.pop(READONLY + name, None)  # the local is writable
                self.locals[-1][INTEGER + name] = self.vars.pop(INTEGER + name, None)  # and not an integer
                self.locals[-1][SHOWN + name] = self.vars.pop(SHOWN + name, None)
                self.local_exports[-1][name] = self.exports.get(name)
                if name in {"PWD", "OLDPWD"}:
                    self.locals[-1]["\0" + name] = self.vars.get("\0" + name)
                if self.dialect == "zsh":
                    self.exports[name] = False
                elif self.dialect is None and self.exported(name) is not False:
                    self.exports[name] = "maybe"
            if "i" in on:
                # zsh's `typeset -i BASE` shows the values in that base.
                based = re.search(r"i\d", flags) or numbered and flags.endswith("i") and "zsh" in self.kinds()
                self.mark_integer(name, "u" if based else "1")
            elif "i" in off:
                self.vars.pop(INTEGER + name, None)
            if on & {"F", "E"}:
                self.mark_integer(name, "u", zsh=True)  # zsh's float, which bash's -F (functions) is not
            if (on | off) & SHOWN_LETTERS and "zsh" in self.kinds():
                letters = set(self.vars.get(SHOWN + name, "")) - {"\x05", "\x06", "\x07"} - off | on & SHOWN_LETTERS
                if letters:
                    self.vars[SHOWN + name] = "".join(sorted(letters))
                else:
                    self.vars.pop(SHOWN + name, None)
            if isinstance(item, str):
                if value is not None:
                    self.set_var(name, value)
                elif new_local:
                    # bash 3.2 masks an existing outer value with an unset local; zsh makes an
                    # empty local (0 for an integer). A first declaration of a previously absent
                    # name is set-empty.
                    def local_value(value):
                        return UNSET if value not in (None, UNSET) or value is None and name in INHERITED | {"IFS"} else ""
                    choices = list(dict.fromkeys(local_value(v) for v in _choices(old))) if old is not None else [local_value(None)]
                    zsh = self.zsh_declared("i" in on)
                    values = (choices if self.dialect == "posix" else zsh if self.dialect == "zsh"
                              else list(dict.fromkeys([*choices, *zsh])))
                    self.vars[name] = values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"
                elif not scoped and keyword in {"declare", "typeset", "local"} and absent:
                    values = ([""] if self.dialect == "posix" else self.zsh_declared("i" in on) if self.dialect == "zsh"
                              else list(dict.fromkeys(["", *self.zsh_declared("i" in on)])))
                    self.vars[name] = values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"
                elif keyword in {"export", "readonly"} and absent and "zsh" in self.kinds():
                    # zsh makes the variable, empty; bash and dash leave it unset.
                    self.vars[name] = "" if self.kinds() == ["zsh"] else "\x06" + UNSET + "\x05\x07"
                elif "i" in on and not new_local and not absent and "zsh" in self.kinds():
                    # zsh evaluates the text a variable has when it becomes an integer; bash keeps it.
                    text = self.vars.get(name, UNKNOWN)
                    if self.kinds() == ["zsh"]:
                        self.set_number(name, text)
                    else:
                        self.either(lambda: self.as_dialect("zsh", lambda: self.set_number(name, text)), lambda: None)
            else:
                self.assign(item)
            if new_local and name in {"PWD", "OLDPWD"}:
                self.vars["\0" + name] = self.vars.get(name, UNSET)
            if export:
                self.exports[name] = True
            elif unexport:
                self.exports[name] = False
            if keyword == "readonly" and "n" not in on or "r" in on:
                self.vars[READONLY + name] = "1"
            elif "r" in off:
                self.vars.pop(READONLY + name, None)
            self.reshown(name)

        def rest(i: int, failed: bool) -> None:
            for j in range(i, len(items)):
                item, name, value = items[j]
                if name is None:
                    # Not a name: dash exits there (fails, under `command`, with the names after it
                    # undone); bash and zsh go on with the others, and then bash fails, zsh ends
                    # the eval or, from a function, the shell (see the end).
                    if "dash" in self.kinds() and not value:
                        def stop():
                            self.error_ways({k: "exit" if k == "dash" else "fail" for k in self.kinds()},
                                            lambda write, error: self.set_status(FAILED))
                        if self.kinds() == ["dash"]:
                            stop()
                        else:
                            self.either(stop, lambda j=j: rest(j + 1, failed))
                        return
                    continue
                valued = not isinstance(item, str) or value is not None
                new_local = scoped and name not in self.locals[-1]
                bad = valued or new_local or "r" in off
                how = {"bash": "fail" if bad else "allow",
                       "posix": ("exit" if valued and keyword in {"readonly", "export"} and not self.guarded
                                 else "fail") if bad else "allow",
                       "dash": "exit" if valued and keyword in {"readonly", "export", "local"} else "allow",
                       "zsh": (self.zsh_special() if keyword in {"readonly", "export"} else "abort")
                       if valued and not new_local else "allow"}
                if not functions and set(how.values()) != {"allow"} and self.readonly(name) is not False:
                    def go(write, error, j=j):
                        if write:
                            one(*items[j])
                        rest(j + 1, failed or error)

                    self.readonly_write(name, how, go)
                    return
                one(item, name, value)
            self.set_status(FAILED if failed else ok)
            if misnamed:
                zsh = "allow" if all(misnamed) else self.zsh_special() if keyword in {"readonly", "export"} else "abort"
                self.error_ways({k: zsh if k == "zsh" else "fail" for k in self.kinds()},
                                lambda write, error: self.set_status(FAILED) if error else None)

        rest(0, False)

    def zsh_declared(self, numeric: bool) -> list[str]:
        """The values zsh's typeset may give a variable it makes: empty, 0 for an integer, and unset
        under TYPESET_TO_UNSET (set by emulate sh and ksh; measured on zsh 5.9)."""
        made = "0" if numeric else ""
        return [UNSET] if self.typesettounset else [made] if self.typesettounset is False else [made, UNSET]

    def as_dialect(self, dialect: str, run) -> None:
        """Run `run()` as code of one dialect (where the audit follows each in turn)."""
        saved, self.dialect = self.dialect, dialect
        try:
            run()
        finally:
            self.dialect = saved

    def listing(self, verb: str, args: list[str]) -> str | None:
        """What zsh's `typeset NAME...` (or declare, or local) with no options prints: outside a
        function, `NAME=VALUE` for each set NAME, quoted as zsh quotes it; in one, nothing, as each
        NAME becomes a new local. None where the audit cannot tell."""
        names = [a for a in args if "=" not in a]
        assigned = {a.split("=", 1)[0] for a in args if "=" in a}
        if (verb not in {"declare", "typeset", "local"} or not names or set(names) & assigned
                or not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", a.split("=", 1)[0]) for a in args)):
            return None
        if self.locals:
            return None if any(n in self.locals[-1] for n in names) else ""
        texts = [""]
        for n in names:
            value = self.vars.get(n)
            if value is None and (n in VOLATILE or n in INHERITED or n.isupper() and self.inherit):
                return None  # from the environment, or the shell's own
            if value in (None, UNSET):
                continue  # zsh makes it, empty, without printing it
            if _array_values(value) is not None or UNKNOWN in value or "$" in value or ARRAY_OPEN in value:
                return None
            shown = list(dict.fromkeys(_zsh_listed(c) for c in _choices(value)))
            if None in shown:
                return None
            texts = list(dict.fromkeys(t + f"{n}={v}\n" for t in texts for v in shown))
        return texts[0] if len(texts) == 1 else "\x06" + "\x05".join(texts) + "\x07"

    def unset(self, args: list[str]) -> None:
        """`unset -f` removes functions, `unset -v` variables; with neither, bash removes the variable
        if there is one and otherwise the function, zsh only the variable. A readonly variable
        stays (see READONLY_UNSET)."""
        flags = "".join(a[1:] for a in args if a.startswith("-"))
        given = [a for a in args if not a.startswith("-")]

        def walk(i, kept, failed):
            for j in range(i, len(given)):
                if "f" not in flags and self.readonly(given[j]) is not False:
                    self.readonly_write(given[j], READONLY_UNSET, lambda write, error, j=j: walk(
                        j + 1, [*kept, given[j]] if write else kept, failed or error))
                    return
                kept = [*kept, given[j]]
            self.unset_names(flags, kept, failed)

        walk(0, [], False)

    def unset_names(self, flags: str, names: list[str], failed: bool) -> None:
        def drop_var(name):
            self.vars[name] = UNSET
            self.vars.pop(INTEGER + name, None)
            self.vars.pop(SHOWN + name, None)
            self.exports[name] = False
            if name in {"PWD", "OLDPWD"}:
                self.vars["\0" + name] = UNSET

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
        self.set_status(FAILED if failed else OK)

    def assign(self, node, around: bool = False, prefix: bool = False) -> None:
        """An assignment node (see `set_var`)."""
        name = node.child_by_field_name("name")
        if name is None:
            return
        if name.type == "subscript":
            base = name.child_by_field_name("name")
            self.notes.append("an indexed array assignment the audit cannot model")
            if base is not None:
                self.vars[_text(base)] = UNKNOWN
            return
        value = self.prevalued[node] if node in self.prevalued else self.assignment_value(node)
        append = any(not c.is_named and _text(c) == "+=" for c in node.children)
        self.set_var(_text(name), value, append, around, prefix)

    def assignment_value(self, node) -> str:
        """An assignment node's value, expanded: an array's elements as words, a scalar's text."""
        val = node.child_by_field_name("value")
        if val is not None and val.type == "array":
            lists = self.word_lists(self.marked_words(val.named_children, val))
            if len(lists) != 1:
                self.notes.append("an array assignment differs between possible shells")
                return UNKNOWN
            return _array([self.tilde(v) for v in lists[0]])
        return self.tilde(self.expand(self.value(val))).replace(SPLIT, " ") if val is not None else ""

    def set_var(self, name: str, value: str, append: bool = False, around: bool = False, prefix: bool = False) -> None:
        """Assign a variable: as arithmetic where it is an integer (see `set_number`), except that
        bash gives an assignment before a command (`prefix`) its text where zsh evaluates it (bash's
        POSIX mode evaluates what it keeps afterwards, see `with_assignments`). `around`: an error
        message goes outside the command's redirections."""
        numeric = self.integer(name)
        if numeric is not False and prefix and self.kinds() != ["zsh"]:
            numeric = None if "zsh" in self.kinds() else False
        if numeric is False:
            self.set_text(name, value, append)
        elif numeric:
            self.set_number(name, value, append, around)
        else:
            self.either(lambda: self.set_number(name, value, append, around),
                        lambda: self.set_text(name, value, append))

    def set_number(self, name: str, value: str, append: bool = False, around: bool = False) -> None:
        """An integer variable's assignment (see INTEGER): the value is an arithmetic expression
        (`+=` adds it), and one the shell cannot evaluate is an error (INTEGER_ASSIGN; where the
        audit cannot tell, either way). zsh shows a value given in base notation in that base, and
        keeps it. An array: bash evaluates each element, zsh makes an array of the texts, no longer
        an integer."""
        kinds = self.kinds()
        if _array_values(value) is not None:
            if kinds == ["zsh"]:
                self.vars.pop(INTEGER + name, None)
                self.set_text(name, value, append)
                return
            self.mark_integer(name, "", zsh=True)
            how = {**INTEGER_ASSIGN, "zsh": "allow"}
            self.error_ways(how, lambda write, failed: self.set_text(name, UNKNOWN) if write else None, around, True)
            return
        text = f"{name}+({value.strip() or 0})" if append else value
        v = self.arith(text)
        based = "zsh" in kinds and _BASED.search(text) is not None

        def go(write, failed):
            if not write:
                return
            if based:
                self.mark_integer(name, "u", zsh=True)
            shown = "zsh" not in kinds or "u" not in _choices(self.vars.get(INTEGER + name, ""))
            self.set_text(name, str(v) if v is not None and shown else UNKNOWN)

        if v is None:
            self.error_ways(INTEGER_ASSIGN, go, around, True)
        else:
            go(True, False)

    def set_text(self, name: str, value: str, append: bool = False) -> None:
        """Assign a variable its text, exporting it under `set -a`. A value that looks like a path
        counts as one."""
        if append:
            old = self.vars.get(name, "")
            left, right = _array_values(old), _array_values(value)
            if left is not None and right is not None:
                value = _array(left + right)
            elif left is not None:
                value = _array([(left[0] if left else "") + value, *left[1:]])
            else:
                value = ("" if old == UNSET else old) + value
        elif (previous := _array_values(self.vars.get(name, UNSET))) is not None and _array_values(value) is None:
            if self.dialect == "posix" or self.ksharrays is True:
                value = _array([value, *previous[1:]])
            elif self.dialect is None:
                self.notes.append("assigning a scalar to an array differs between possible shells")
                value = UNKNOWN
        self.vars[name] = value
        self.reshown(name)
        if name in {"PWD", "OLDPWD"}:
            self.vars["\0" + name] = value
        if self.allexport is True:
            self.exports[name] = True
        elif self.allexport is None and self.exported(name) is not True:
            self.exports[name] = "maybe"
        values = _array_values(value)
        for item in values if values is not None else [value]:
            self.add(item, bare=False)

    def pipeline(self, stages: list, data: str | None = None, tail: list | None = None,
                 piped: bool = False) -> None:
        """Each stage runs in a subshell, fed what the stage before it printed (when known), except
        that zsh runs the last stage in the current shell, as bash does after `shopt -s lastpipe`:
        `x | cd d`, `x | read y` and `x | while read d; do cd "$d"; done` change zsh's shell. Where
        the audit cannot tell which shell runs the code and the last stage could change the shell
        (see `_keeps_shell`), it keeps both outcomes. `tail`: redirections written after the
        pipeline, which belong to its last stage. A search whose results reach a later stage that
        reads names (xargs, a shell, a `while read` loop) is fed. `piped` marks the first stage of
        a continuation the grammar put inside a here-document: its `data` came from a pipe too."""
        if not stages:
            self.set_status(MAYBE)
            return
        here = {"zsh": [True], "posix": [False, True] if self.lastpipe is not False else [False]}.get(self.dialect, [False, True])
        ways = [False] if self._keeps_shell(stages[-1]) else here
        if len(ways) == 1:
            self._pipeline(stages, data, tail, ways[0], piped)
        else:
            self.either(*(lambda h=h: self._pipeline(stages, data, tail, h, piped) for h in ways))

    def _pipeline(self, stages: list, data: str | None, tail: list | None, here: bool,
                  piped: bool = False) -> None:
        """`pipeline` with the last stage run in the current shell if `here`. What the last stage
        prints follows what came before the pipeline."""
        before, mark = self.output, self.jumped
        out = self._stages_from(stages, data, tail, here, 0, piped)
        self.output = _concat(before, out)
        self.carry(mark, before, True)

    def _stages_from(self, stages: list, data: str | None, tail: list | None, here: bool,
                     start: int, piped: bool = False) -> str | None:
        """Run a pipeline's stages from `start`, the first fed `data`; return what the last prints.
        Where a stage may read several inputs (a CHOICE: what echo prints in different shells,
        say), the rest of the pipeline runs on each."""
        readers = [self._reads_names(s) for s in stages]
        # The first stage is fed by a pipe where the pipeline is itself a stage fed by one.
        inherited = piped or self.fed is not None and self.fed == stages[0].parent
        for i in range(start, len(stages)):
            stage = stages[i]
            if data is not None and CHOICE.search(data) and len(alts := _choices(data)) > 1:
                outs = []

                def rest(d, i=i):
                    outs.append(self._stages_from(stages, d, tail, here, i, piped))

                self.either(*(lambda d=d: rest(d) for d in alts))
                return _either_output(outs)
            last = i == len(stages) - 1
            self.output = ""
            fed = any(readers[i + 1:])
            self.feeding += fed
            outer, self.stage = self.stage, None if last else stage
            feeder, self.fed = self.fed, stage if i > 0 or inherited else None
            try:
                with nullcontext() if last and here else self.child():
                    if not last:
                        self.diverted, self.out_closed = None, False  # its standard output is the pipe
                        nxt = stage.next_sibling
                        if nxt is not None and nxt.type == "|&":
                            self.err_out = True  # zsh's `|&`: its standard error too (see `line`)
                    if tail and last:
                        self.with_redirects(stage, tail, data)
                    else:
                        self.statement(stage, data)
            finally:
                self.feeding -= fed
                self.stage, self.fed = outer, feeder
            data = self.output
        self.set_status(MAYBE)
        return data

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
        if inner is not None and inner.type in {"compound_statement", "subshell"}:
            return any(cls._reads_names(c) for c in inner.named_children if c.type in STATEMENTS)
        return cls._command_name(node) in NAME_READERS

    def statement(self, node, stdin: str | None) -> None:
        if node.type == "command":
            self.simple(node, stdin=stdin)
        elif node.type == "redirected_statement":
            self.redirected(node, stdin)
        elif node.type == "while_statement":
            self.while_loop(node, stdin)
        elif node.type == "pipeline":
            self.pipeline(self._stages(node), data=stdin)
        elif node.type in {"compound_statement", "subshell"} and len(
                children := [c for c in node.named_children if c.type in STATEMENTS]) == 1:
            # A group with one statement passes its inherited input to that statement. A loop
            # or another group may in turn pass it on, without treating inner redirections as
            # belonging to the pipeline stage around the group.
            with self.child() if node.type == "subshell" else nullcontext():
                self.statement(children[0], stdin)
        else:
            self.visit(node)

    def redirected(self, node, stdin: str | None = None, outer: list | None = None) -> None:
        body = node.child_by_field_name("body")
        redirects = [c for c in node.named_children if c.type in REDIRECTS] + list(outer or [])
        self.with_redirects(body, redirects, stdin, node)

    def negated(self, node, redirects: list | None = None, stdin: str | None = None) -> None:
        """`! command`, its status turned over. The grammar puts redirections written after it
        (`! cat < f`) outside the negation; in the shell they belong to the command, so whether
        they are made in a child is the command's to decide (see `failed_redirect`)."""
        with self.guarding():
            inner = node.named_children
            for i, c in enumerate(inner):
                if redirects and i == len(inner) - 1:
                    self.with_redirects(c, redirects, stdin)
                else:
                    self.visit(c)
        swap = {OK: FAILED, FAILED: OK}
        self.worlds = [w._replace(status=swap.get(w.status, w.status)) for w in self.worlds]

    def with_redirects(self, body, redirects: list, stdin: str | None, node=None) -> None:
        """A statement and the redirections written after it (`node`, where it has no statement:
        see `null_command`). In `cd .. && python3 - <<EOF` the grammar attaches the here-document to
        the whole list; in the shell it, like any redirection after a list or pipeline, belongs to
        the last command."""
        if body is None:
            self.null_command(node, redirects, stdin)
        elif body.type == "command":
            self.simple(body, redirects, stdin)
        elif body.type == "redirected_statement":
            self.redirected(body, stdin, redirects)
        elif body.type == "list":
            self.and_or(body, redirects, stdin)
        elif body.type == "pipeline":
            self.pipeline(self._stages(body), data=stdin, tail=redirects)
        elif body.type == "negated_command":
            self.negated(body, redirects, stdin)
        else:
            def run(data):
                self.statement(body, data)
            self.around_redirects(body, node if node is not None else body, redirects, stdin, run, body.type != "subshell",
                                  body.type == "subshell")

    def around_redirects(self, node, unit, redirects: list, stdin: str | None, run, inline: bool | None,
                         subshell: bool = False) -> None:
        """Make `redirects` and run `run(data)` inside them, `data` being what they feed standard
        input; `node` is what runs, `unit` the statement they belong to (a pipeline's stage, say),
        and `inline` and `subshell` say where its redirections expand (see `redirecting`)."""
        outs: list[tuple[str, bool]] = []
        ends = self.child_ends
        opens = self.open_failures
        with self.redirecting(inline, subshell):
            data, after = self.redirect(redirects, stdin, outs, piped=self.fed is not None and self.fed == unit)
        fails = self.child_ends > ends or self.open_failures > opens  # see `failed_redirect`
        before, self.output = self.output, ""
        diverted, emits, err, mark = self.diverted, self.emits, self.err_out, self.jumped
        closed, tees = self.out_closed, self.tees()  # MULTIOS as the redirections are made
        trims = self.trims
        if outs:
            self.diverted = None
            self.out_closed = any(target == CLOSED for target, _ in outs)
        self.err_out = _err_state(redirects, err)
        noisy = self.noisy
        try:
            self.either(lambda: run(data), self.failed_redirect) if fails else run(data)
        finally:
            if outs:
                self.diverted, self.out_closed = diverted, closed
            if self.err_out and not err and self.noisy > noisy:
                self.output = None  # diagnostics inside reached what it printed
            self.err_out = err or self.exec_err
        own = self.output
        piped = self.stage is not None and self.stage == unit
        self.carry(mark, before, not outs and not after and self.diverted is None and not self.stray)
        self.write_outs(outs, None if fails else own, tees, piped)
        self.emit(before, own, outs, after, piped, node, bool(outs) or self.emits == emits, tees,
                  False if self.trims == trims else None)

    def null_command(self, node, redirects: list, stdin: str | None, unit=None) -> None:
        """Redirections with no command (`< f`, `> f`, and in zsh a command whose words all expand
        to nothing; `unit` is the statement they belong to, `node` by default). bash, sh and dash
        make them in the shell and run nothing, with the status of the last command substitution in
        them, or 0. zsh runs a command with them, chosen in this order (measured on zsh 5.9, in the
        order of its exec.c): where NULLCMD is empty or unset, it prints "redirection with no
        command", makes no redirection, and ends what the nearest `eval`, `.` or `emulate -c` runs,
        or else the shell (see `abort`); CSH_NULLCMD gives the same error; otherwise `:` where it
        emulates sh or ksh (SH_NULLCMD);
        otherwise $READNULLCMD (`more` unless set) for one `<` on any descriptor and nothing else,
        where READNULLCMD is not empty; otherwise $NULLCMD (`cat` unless set). That command is
        looked up as a function, a builtin or a file, never an alias, and runs in the shell where it
        is a builtin or a function, so what its redirections' words assign stays. A precommand
        modifier there (`noglob`, `builtin`, `command`, `-`) gives the same error; `exec` keeps its
        redirections for the shell, and `time` is unresolved. An external `more` copies its input
        as cat does, its output not being a terminal.
        Either variable may come from the environment (see `never_set`)."""
        unit = node if unit is None else unit
        substituted = any(_assignment_status(n) == MAYBE for n in [node, *redirects])

        def posix() -> None:
            self.around_redirects(node, unit, redirects, stdin,
                                  lambda data: self.set_status(MAYBE if substituted else OK), True)

        def unknown() -> None:
            self.notes.append("a redirection with no command, which zsh runs with a NULLCMD the audit cannot tell")

            def run(data) -> None:
                self.output = None
                self.set_status(MAYBE)
            self.around_redirects(node, unit, redirects, stdin, run, None)

        def error() -> None:
            self.complain()
            self.abort()  # zsh: redirection with no command

        def verb(name: str) -> None:
            defined = self.functions.get(name)
            if name == "exec" and defined is not None and None in defined:
                # Each branch must choose between the function's temporary redirections and
                # the builtin's persistent ones before making them.
                def selected(body):
                    saved = self.functions.pop(name)
                    shadow = (body,)
                    if body is not None:
                        self.functions[name] = shadow
                    try:
                        verb(name)
                    finally:
                        if self.functions.get(name, shadow) is shadow:
                            self.functions[name] = saved
                self.either(*(lambda body=body: selected(body) for body in defined))
                return
            if name == "exec" and name not in self.functions:
                alias = self.aliases.pop(name, None)
                try:
                    self.run_words(node, [], [[name]], redirects, stdin, unit)
                finally:
                    if alias is not None and name not in self.aliases:
                        self.aliases[name] = alias
                return

            def run(data) -> None:
                alias = self.aliases.pop(name, None)  # no alias expands there
                try:
                    if name == "more" and name not in self.functions:
                        self.prefixed("command", ["cat"], data)  # external pager, no cat function or alias
                    else:
                        self.command([name], data)
                finally:
                    if alias is not None and name not in self.aliases:
                        self.aliases[name] = alias
            defined = self.functions.get(name)
            ways = {True} if name in ZSH_BUILTINS - {"command"} or defined is not None and None not in defined else \
                {True, False} if defined is not None else {False}
            self.around_redirects(node, unit, redirects, stdin, run, ways.pop() if len(ways) == 1 else None)

        def zsh() -> None:
            if self.cshnullcmd is not False:
                if self.cshnullcmd is True:
                    error()
                else:
                    saved, self.cshnullcmd = self.cshnullcmd, False
                    try:
                        self.either(error, zsh)
                    finally:
                        self.cshnullcmd = saved
                return
            lone = len(redirects) == 1 and redirects[0].type == "file_redirect" and \
                "".join(_text(c) for c in redirects[0].children if not c.is_named) == "<"
            names = ["NULLCMD", "READNULLCMD"] if lone else ["NULLCMD"]
            values = [self.vars.get(n, {"NULLCMD": "cat", "READNULLCMD": "more"}[n]
                                    if self.never_set(n) == UNSET else UNKNOWN) for n in names]
            # Each value a variable may have, "?" where the audit cannot tell it; a value counts
            # only where zsh consults it.
            def pick(value: str) -> list[str]:
                return [("?" if UNKNOWN in v or "$" in v else v) for v in _choices(value)]
            runs: dict[str, None] = {}
            for null in pick(values[0]):
                for read in pick(values[1]) if lone else [UNSET]:
                    for sh in [True, False] if self.shnullcmd is None else [self.shnullcmd]:
                        name = "?" if null == "?" else "" if null in {"", UNSET} else ":" if sh else \
                            read if read not in {"", UNSET} else null
                        runs["" if name in {"noglob", "builtin", "command", "-"} else name] = None
            thunks = [error if name == "" else unknown if name in {"?", "time"} else
                      (lambda name=name: verb(name)) for name in runs]
            thunks[0]() if len(thunks) == 1 else self.either(*thunks)

        kinds = self.kinds()
        if "zsh" not in kinds:
            posix()
        elif kinds == ["zsh"]:
            zsh()
        else:
            self.either(zsh, posix)

    def redirect(self, redirects: list, stdin: str | None, outs: list | None = None,
                 ifs: str | None | bool = False, piped: bool = False,
                 inputs: list | None = None) -> tuple[str | None, list]:
        """Note the files that redirections name; return what reaches standard input and any
        statements a here-document carries after it (the rest of a pipeline, say). Files standard
        output goes to are added to `outs`, as (target, appended).

        Standard input is `stdin` unless the redirections give it another: a file (`<`, `<>`), a
        here-document or here-string, another descriptor's input, or nothing (closed). With several,
        bash, sh and dash read the last; zsh's MULTIOS reads them all in turn, after the pipe where
        the command is a pipeline stage fed by the one before (`piped`): `echo in | cat < f` prints
        both (measured on zsh 5.9; a group's or a loop's own redirections join its pipe, the commands
        inside it do not). `inputs` gathers them for the here-document's redirections."""
        after: list = []
        top = inputs is None
        inputs = ([stdin] if piped else []) if inputs is None else inputs
        # Whether standard error is a copy of standard output as it stands before this
        # redirection: from a `2>&1` around (`{ { echo x >&2; } > f; } 2>&1`) or earlier here.
        err = self.err_out
        copied = err is not False
        if self.tees() is not False and _multios_tangled(redirects):
            self.stray = True
            if outs is not None:
                outs.append((TANGLED, False))
        for r in redirects:
            made = err  # standard error as the redirections before this one left it
            if r.type == "file_redirect":
                op = "".join(_text(c) for c in r.children if not c.is_named)
                fd = next((_text(c) for c in r.named_children if c.type == "file_descriptor"), "")
                last = _text(r.named_children[-1]) if r.named_children else ""
                both = op in {"&>", "&>>"} or op == ">&" and fd == "" and not last.isdigit() and last != "-"
                onto_err = op in {">&", "<&"} and last == "2"  # to that copy: still where it was
                if fd in {"", "1"} and op not in {"<", "<&", "<>"} and not both and not onto_err and copied:
                    # `2>&1 >f`: standard error stays where standard output was, which this
                    # command's output no longer follows: what reaches that is unknown from here.
                    self.stray = True
                if fd == "2" or both:
                    copied = op in {">&", "<&"} and last == "1" or both
                err = _err_state([r], err)
                if fd not in {"", "0", "1", "2"}:
                    self.stray = True
                # A duplication or close acts on the descriptor it names, whichever way its arrow
                # points (`1<&-` closes standard output, `2<&1` copies it); `>` names 1 by default,
                # `<` names 0 (measured on bash 3.2, its sh, dash and zsh 5.9).
                which = fd or ("1" if op.startswith(">") else "0")
                if op in {">&-", "<&-"}:
                    # Closes a descriptor: closed, standard output takes nothing, standard input
                    # gives nothing.
                    if which == "1" and outs is not None:
                        outs.append((CLOSED, False))
                    elif which == "0":
                        inputs.append(CLOSED)
                    continue
                dest = r.child_by_field_name("destination")
                if dest is None:
                    named = [c for c in r.named_children if c.type != "file_descriptor"]
                    dest = named[-1] if named else None
                if dest is None:
                    continue
                with self.child_words(), self.erring(made):
                    target = self.expand(self.value(dest))
                if op.endswith("&") and (target.isdigit() or target == "-"):
                    # Duplicates or closes a file descriptor: `>&2` sends standard output elsewhere.
                    if target not in {"-", "0", "1", "2"}:
                        self.stray = True
                    if outs is not None and which == "1" and target != "1":
                        outs.append((CLOSED if target == "-" else MAYBE_OUT if target == "2" and err else "/dev/null",
                                     False))
                    elif which == "0" and target != "0":
                        inputs.append(CLOSED if target == "-" else None)  # another descriptor's input
                    continue
                if op in {"<", "<>"} and fd in {"", "0"}:
                    inputs.append(self.file_text(target))  # standard input reads the file
                if op in {"<", "<>", ">", ">>", ">|", "&>", "&>>", ">&"}:
                    self.open_failures += self.open_may_fail(target, op)
                self.add(target, bare=True)
                if outs is not None and op in {">", ">>", ">|", "&>", "&>>", ">&"} and fd in {"", "1"}:
                    outs.append((target, op.endswith(">>")))
            elif r.type == "heredoc_redirect":
                with self.child_words(here=True), self.erring(made):
                    content = self.heredoc(r)
                fd = r.child_by_field_name("descriptor")
                if fd is None or _text(fd) == "0":
                    inputs.append(content)
                for c in r.named_children:
                    if c.type == "file_redirect":
                        self.redirect([c], None, outs, inputs=inputs)
                    elif c.type in STATEMENTS:
                        op = r.child_by_field_name("operator")
                        after.append((_text(op), c) if op is not None else c)
                        if c.type == "pipeline" and c.children and c.children[0].type == "|&":
                            self.notes.append("a here-document's command sends standard error down `|&`")
            elif r.type == "herestring_redirect":
                with self.child_words(), self.erring(made):
                    inputs.append(self.herestring(list(r.named_children), ifs))
        if not top or len(inputs) <= int(piped):
            return stdin, after
        last = "" if inputs[-1] == CLOSED else inputs[-1]
        joined = None if CLOSED in inputs else functools.reduce(_concat, inputs)  # zsh: a closed one fails
        multios = self.tees()
        return (joined if multios else last if multios is False or len(inputs) == 1 else
                _either_output([joined, last])), after

    def open_may_fail(self, target: str, op: str) -> bool:
        """A file redirection may fail where its input is missing, or its output's parent is
        missing or is a file. As with `chdir`, absence at audit time does not prove absence when
        the transcript ran: keep both success and failure, including the command's skipped
        effects and nonzero status. Files and directories made earlier in the call count as
        present. Descriptor duplications and process substitutions are handled separately."""
        text = _alt(target)[0]
        if text in self.substituted or text.startswith("/dev/"):
            return False
        if UNKNOWN in text or CHOICE.search(text) or "$" in text:
            return True
        for world in self.worlds:
            path = _resolve(text, world.cwd, bare=True)
            if path is None:
                return True
            if op == "<":
                if (path not in self.files and not path.exists()) or any(_under(path, p) for p in self.removed):
                    return True
            elif (path.parent not in self.made and not path.parent.is_dir()) or path.is_dir():
                return True
        return False

    @contextmanager
    def erring(self, err: bool):
        """Expanding a redirection's word, with standard error where the command's redirections
        before it sent it (`: 2>&1 < "${x?}"` prints the message on standard output)."""
        saved, self.err_out = self.err_out, err
        try:
            yield
        finally:
            self.err_out = saved

    @contextmanager
    def child_words(self, here: bool = False):
        """Expanding a redirection's word. bash and zsh expand it in the child a command forks,
        unless the command runs in the shell (`inline`; None where it may or may not). dash expands
        a file's in the shell, and a here-document's (`here`) there too except for a subshell, but
        fails the command without ending at a here-document for any but a special builtin
        (measured). Where the shell may go on (`forked_words`) the expansion's assignments stay
        only where it ran in the shell (see `in_child`)."""
        kinds = self.kinds()
        forks = here and "dash" in kinds or not self.inline and (here or kinds != ["dash"])
        child = [k for k in kinds if not self.inline and (k != "dash" or here and self.subshell_words)]
        self.forked_words += forks
        try:
            with self.in_child(child, maybe=self.inline is None):
                yield
        finally:
            self.forked_words -= forks

    @contextmanager
    def in_child(self, child: list[str], maybe: bool = False):
        """Expansions that the shells in `child` make in a forked child (`maybe`: or in the shell
        itself): what they assign (`${x:=word}`, `$((x=1))`) is lost there and stays in the other
        shells that may run the code."""
        if not child:
            yield
            return
        vars, exports = dict(self.vars), dict(self.exports)
        yield
        every = set(child) >= set(self.kinds()) and not maybe
        for name in set(vars) | set(self.vars):
            old, new = vars.get(name), self.vars.get(name)
            if old == new:
                continue
            if every and old is None:
                self.vars.pop(name, None)
            elif every:
                self.vars[name] = old
            else:
                never = self.never_set(name) if IDENTIFIER.fullmatch(name) else ""
                values = list(dict.fromkeys(c for v in (old, new) for c in _choices(never if v is None else v)))
                self.vars[name] = values[0] if len(values) == 1 else "\x06" + "\x05".join(values) + "\x07"
        for name in set(exports) | set(self.exports):
            if exports.get(name) != self.exports.get(name):
                if every and name not in exports:
                    self.exports.pop(name, None)
                elif every:
                    self.exports[name] = exports[name]
                else:
                    self.exports[name] = "maybe"

    @contextmanager
    def redirecting(self, inline: bool | None, subshell: bool = False):
        """Expanding the redirections of a command that runs in the shell itself (`inline`: a
        builtin, a function, a group, a loop), or that may fork (an external command, a subshell);
        `inline` None: either, as where a function is defined in some branches."""
        saved = self.inline, self.subshell_words
        self.inline, self.subshell_words = inline, subshell
        try:
            yield
        finally:
            self.inline, self.subshell_words = saved

    def runs_inline(self, words: list[str], assigns: list) -> bool | None:
        """Whether a simple command with these words runs in the shell itself (see `inline_ways`):
        True or False in every shell it may be, None where that differs or may go either way. One
        with only assignments and redirections does (measured; zsh runs a command for redirections
        alone, see `null_command`)."""
        if not words:
            return bool(assigns) or "zsh" not in self.kinds()
        ways = set().union(*(self.inline_ways(words, kind) for kind in self.kinds()))
        return ways.pop() if len(ways) == 1 else None

    def inline_ways(self, words: list[str], kind: str) -> set[bool]:
        """Whether a simple command runs in shell `kind` itself: a builtin or a function every
        branch defines; both ways for a function defined in some branches or an alias. zsh's
        modifiers are followed to the command they select, including nested `builtin command`.
        Only an unquoted `nocorrect` is reserved; `noglob` and `-` are also builtins (measured on
        zsh 5.9). A modifier with no command and redirections is handled by `simple`."""
        i, forced = 0, False
        while i < len(words):
            verb = _alt(self.expand(words[i]))[0]
            if kind == "zsh" and (verb == "noglob" or
                                     verb == "nocorrect" and isinstance(words[i], _ReservedWord)):
                i += 1
                forced = False
                continue
            if kind == "zsh" and verb == "-":
                i += 1
                continue
            if kind == "zsh" and verb == "builtin" and i + 1 < len(words):
                i += 1
                forced = True
                while i < len(words) and _alt(self.expand(words[i]))[0] in {"-", "--"}:
                    if words[i] == "-":
                        forced = False
                    i += 1
                continue
            if kind == "zsh" and verb == "command":
                j = i + 1
                while j < len(words) and _alt(self.expand(words[j]))[0].startswith("-") and words[j] != "-":
                    if _alt(self.expand(words[j]))[0] == "--":
                        j += 1
                        break
                    if set(_alt(self.expand(words[j]))[0][1:]) & {"v", "V"}:
                        return {True}  # describes the command, running nothing
                    j += 1
                if j >= len(words):
                    return {True}
                builtin = _alt(self.expand(words[j]))[0] in ZSH_BUILTINS - {"command"}
                return {True} if builtin and self.posixbuiltins is True else \
                    {False} if not builtin or self.posixbuiltins is False else {True, False}
            if forced:
                return {True}  # either a builtin or zsh's no-such-builtin error
            if verb in self.aliases:
                return {True, False}
            defined = self.functions.get(verb)
            if defined is not None and None not in defined:
                return {True}
            builtin = verb in (ZSH_BUILTINS - {"command"} if kind == "zsh" else BASH_BUILTINS)
            return {builtin, True} if defined is not None else {builtin}
        return {False} if kind == "zsh" else {True}

    def zsh_no_builtin(self, words: list[str]) -> bool:
        """Whether zsh's `builtin` names no builtin after its nested modifiers. Such an error
        makes none of the redirections (measured on zsh 5.9). `builtin command` follows command's
        selection, while `builtin -` follows the command after `-`, including functions and files."""
        i = 0
        while i < len(words):
            verb = _alt(self.expand(words[i]))[0]
            if verb in {"noglob", "-"} or verb == "nocorrect" and isinstance(words[i], _ReservedWord):
                i += 1
                continue
            if verb != "builtin" or i + 1 >= len(words):
                return False
            i += 1
            while i < len(words) and _alt(self.expand(words[i]))[0] == "--":
                i += 1
            if i >= len(words):
                return False
            name = _alt(self.expand(words[i]))[0]
            if name in {"noglob", "builtin", "-"}:
                continue
            return name not in ZSH_BUILTINS
        return False

    def heredoc(self, r) -> str | None:
        """What a here-document feeds standard input: its lines as written (`<<-` drops their
        leading tabs), and with an unquoted delimiter, expanded (see `_heredoc_parts`). The text
        comes from the source, as the grammar's parts of the body miss backquotes and `$1`."""
        start = next((c for c in r.named_children if c.type == "heredoc_start"), None)
        body = next((c for c in r.named_children if c.type == "heredoc_body"), None)
        end = next((c for c in r.named_children if c.type == "heredoc_end"), None)
        if body is None:
            return ""
        root = r
        while root.parent is not None:
            root = root.parent
        src = root.text
        first = src.rfind(b"\n", 0, body.start_byte) + 1
        last = src.rfind(b"\n", 0, end.start_byte) + 1 if end is not None else body.end_byte
        # Without the bytes added so that the grammar reads a line starting with a backslash, or
        # goes on past a line the shells do not take as the end.
        added = set(self.added.get(src, ()))
        text = bytes(c for i, c in enumerate(src[first:max(first, last)], first) if i not in added)
        text = text.decode(errors="replace")
        if any(not c.is_named and _text(c) == "<<-" for c in r.children):
            text = re.sub(r"(?m)^\t+", "", text)
        if start is not None and any(q in _text(start) for q in "'\"\\"):
            return text
        out: str | None = ""
        for expanded, piece in _heredoc_parts(text):
            if expanded:
                word = next((n for n in _walk(_BASH.parse(b'"' + piece.encode() + b'"').root_node)
                             if n.type == "string"), None)
                piece = self.expand(self.value(word)) if word is not None else UNKNOWN
            out = _concat(out, piece)
        return out

    def herestring(self, parts: list, ifs: str | None | bool = False) -> str:
        """What a here-string feeds standard input: the word, then a newline. bash 3.2, the
        /bin/bash of macOS, splits the word's unquoted parts at IFS, literal text included, and
        joins the fields with spaces (`IFS=: cat <<< a:b` prints `a b`, and a command's own `IFS=`
        counts); zsh, like later versions of bash, feeds the word as it is, with "$@" joined by
        IFS's first character. Where the shell is not known and the two differ, the input is
        unknown. `ifs`: IFS as the command's own assignments set it (False: they do not)."""
        ifs = self.ifs() if ifs is False else None if ifs == UNSET else ifs
        marked = [self.expand(self.value(c, split=True)) for c in parts]
        join = " " if ifs is None else ifs[:1]
        plain = " ".join(_unmark(m).replace(SPLIT, join) for m in marked)
        if self.dialect == "zsh":
            return _concat(plain, "\n")
        split = " ".join(" ".join(_fields(m, ifs, True, literal=True)) for m in marked)
        return _concat(split if self.dialect == "posix" or split == plain else UNKNOWN, "\n")

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
        # A here-string can be inside `command` while the following file redirection wraps the
        # statement. They still take effect in source order, including zsh's MULTIOS input join.
        redirs.sort(key=lambda r: r.start_byte)
        # Words expand, and split into fields, before the command's own assignments take effect,
        # as in the shell. Where the shells split them differently, the command runs each way.
        lists = self.word_lists(words)
        kinds = self.kinds()
        wrapped = node.parent is not None and node.parent.type == "redirected_statement"
        unit = node.parent if wrapped else node  # the statement the redirections belong to
        modifiers = [ws[0] if len(ws) == 1 and (ws[0] in {"noglob", "builtin", "command", "-"} or
                     ws[0] == "nocorrect" and isinstance(ws[0], _ReservedWord)) else None for ws in lists]
        if "zsh" in kinds and redirs and not assigns and all(modifiers):
            def modified_null():
                if all(m == "nocorrect" for m in modifiers):
                    self.null_command(node, redirs, stdin, unit)
                else:
                    # zsh rejects a lone modifier before it expands any redirection's word;
                    # the error ends the nearest eval or sourced file, or the shell itself.
                    self.complain()
                    self.abort()
            if kinds == ["zsh"]:
                modified_null()
            else:
                self.either(lambda: self.as_dialect("zsh", modified_null),
                            lambda: self.as_dialect("posix", lambda:
                                self.run_words(node, assigns, lists, redirs, stdin, unit)))
            return
        if "zsh" in kinds and not assigns and redirs and not all(lists):
            if any(lists):
                self.notes.append("a command whose words may expand to nothing, which zsh runs as redirections alone")
            else:
                self.null_command(node, redirs, stdin, unit)  # words that all expand to nothing
                return
        missing = [self.zsh_no_builtin(ws) for ws in lists] if "zsh" in kinds else []
        if any(missing):
            def nothing():
                self.complain()  # no such builtin, with none of the redirections made
                self.set_status(FAILED)
            if kinds == ["zsh"] and all(missing) and not assigns:
                nothing()
            else:
                self.either(nothing, lambda: self.run_words(node, assigns, lists, redirs, stdin, unit))
            return
        self.run_words(node, assigns, lists, redirs, stdin, unit)

    def run_words(self, node, assigns: list, lists: list[list[str]], redirs: list, stdin: str | None,
                  unit) -> None:
        """`simple` from its expanded words on: make the redirections, then run the command once
        for each way its words and standard input may be."""
        outs: list[tuple[str, bool]] = []
        ends = self.child_ends
        opens = self.open_failures
        # zsh treats literal `time` as a timed pipeline: its explicit input redirection replaces
        # this pipe rather than joining it with MULTIOS (measured on zsh 5.9).
        name = node.child_by_field_name("name")
        piped = self.fed is not None and self.fed == unit and not (name is not None and _text(name) == "time")
        with self.redirecting(self.runs_inline(lists[0], assigns)):
            stdin, after = self.redirect(redirs, stdin, outs, ifs=self.prefix_ifs(assigns), piped=piped)
        inputs = _choices(stdin) if stdin is not None and CHOICE.search(stdin) else [stdin]
        runs = [(ws, data, False) for ws in lists for data in inputs]
        if self.child_ends > ends or self.open_failures > opens:
            runs.append((lists[0], stdin, True))  # see `failed_redirect`
        if len(runs) == 1:
            self.run_simple(node, assigns, lists[0], stdin, outs, after)
        else:
            self.either(*(lambda ws=ws, data=data, fails=fails:
                          self.run_simple(node, assigns, ws, data, outs, after, fails)
                          for ws, data, fails in runs))

    def marked_words(self, nodes: list, parent) -> list[str]:
        """The marked values of a command's argument nodes. The grammar drops a backslash-escaped
        blank after an expansion or a quoted string (`$y\\ x` comes as `$y` and `x`): such
        neighbours are one word, with the blank quoted."""
        out: list[str] = []
        src, base, prev = parent.text, parent.start_byte, None
        for n in nodes:
            source = _text(n)
            value = self.value(n, split=True)
            braces = _brace_words(value, bash=self.dialect == "posix")
            if (self.braceexpand is not False and braces is not None and len(braces) > 1 and
                    ("$(" in source or "`" in source)):
                # Brace duplication precedes substitutions in bash; the grammar shares one
                # substitution node between the copies. Retain those effects as possibilities.
                self.notes.append("brace expansion duplicates substitutions the audit cannot order exactly")
                self.worlds = [w._replace(primary=False) for w in self.worlds]
            gap = src[prev.end_byte - base:n.start_byte - base] if prev is not None else b""
            if gap in (b"\\ ", b"\\\t"):
                out[-1] += Q_OPEN + gap[1:].decode() + Q_CLOSE + value
            else:
                out.append(value)
            prev = n
        return out

    def splits(self) -> list[bool]:
        """Whether unquoted parameter expansions split into fields: in sh and bash, not in zsh, and
        under SH_WORD_SPLIT in zsh; either, where the shell or option is not known."""
        zsh = [False, True] if self.shwordsplit is None else [self.shwordsplit]
        return [True] if self.dialect == "posix" else zsh if self.dialect == "zsh" else list(dict.fromkeys([True, *zsh]))

    def field_modes(self) -> list[tuple[bool, bool]]:
        zsh = [(split, False) for split in ([False, True] if self.shwordsplit is None else [self.shwordsplit])]
        return [(True, True)] if self.dialect == "posix" else zsh if self.dialect == "zsh" else [(True, True), *zsh]

    def ifs(self) -> str | None:
        value = self.vars.get("IFS")
        # Native zsh appends a literal NUL to its default IFS. NUL cannot occur in a filename
        # or an argv element; omit it for splitting instead of mistaking it for UNKNOWN.
        if self.dialect == "zsh" and value == " \t\n\0":
            return " \t\n"
        return None if value == UNSET else value

    def word_lists(self, words: list[str]) -> list[list[str]]:
        """The words marked words become after expansion and field splitting (see `_fields`), in
        each shell the audit may be in: one list, or two where the shells differ."""
        out: list[list[str]] = []
        for params, bash in self.field_modes():
            expanded = []
            for word in words:
                braces = getattr(self, "braceexpand", True)
                values = _brace_words(word, bash=bash) if braces is not False else [word]
                if values is None:
                    self.notes.append("a brace expansion exceeds the audit's bound")
                    values = [UNKNOWN]
                if braces is None and values != [word]:
                    self.notes.append("brace expansion depends on a shell option")
                    values = [UNKNOWN]
                # Brace expansion precedes tilde expansion, so {~+,~-} contains two tildes.
                expanded += [TILDE + value if value.startswith("~") else value for value in values]
            fields = []
            for w in expanded:
                from_expansion = any(c in w for c in (FIELD, FIELD_CMD, "\x01"))
                marked = self.expand(w)
                quoted, field, wildcard_modes = False, False, set()
                for c in marked:
                    if c == Q_OPEN:
                        quoted = True
                    elif c == Q_CLOSE:
                        quoted = False
                    elif c in (FIELD, FIELD_CMD):
                        field = True
                    elif c == FIELD_END:
                        field = False
                    elif c in "*?[":
                        literal = quoted or (field and not bash and self.globsubst is not True)
                        if field and not quoted and not bash and self.globsubst is None:
                            self.notes.append("pathname expansion of a variable depends on a shell option")
                        wildcard_modes.add(literal)
                literal = wildcard_modes == {True}
                if wildcard_modes == {False, True}:
                    self.notes.append("a pathname pattern mixes quoted and unquoted wildcard characters")
                    marked = UNKNOWN
                cls = _ReservedWord if w == "nocorrect" else _ExpandedLiteralWord if literal and from_expansion else _LiteralWord if literal else _ExpandedWord if from_expansion else str
                for field in _fields(marked, self.ifs(), params, bash=bash):
                    if TILDE in field and len(self.worlds) == 1:
                        field = self.tilde(field, self.worlds[0])
                    if literal or not any(c in field for c in "*?[") or self.noglob is True:
                        fields.append(cls(field))
                        continue
                    if self.noglob is None or len(self.worlds) != 1 or CHOICE.search(field) or UNKNOWN in field:
                        self.notes.append("a pathname expansion the audit cannot determine in this shell state")
                        fields.append(_ExpandedWord(UNKNOWN))
                        continue
                    target = self.tilde(field, self.worlds[0])
                    if UNKNOWN in target:
                        fields.append(_ExpandedWord(UNKNOWN))
                        continue
                    pattern = target if os.path.isabs(target) else str(self.cwd / target)
                    matches = sorted(globlib.glob(pattern))
                    if matches:
                        fields += [_ExpandedWord(m if os.path.isabs(target) else os.path.relpath(m, self.cwd))
                                   for m in matches]
                    elif not bash and self.nomatch is True and self.dialect == "zsh":
                        # Scratch files may have disappeared since the call. Keep the audit's
                        # protected-pattern check even though no later statement runs under
                        # zsh's audit-time interpretation of an unmatched glob.
                        self.add(_ExpandedWord(target), bare=False)
                        self.worlds = []
                    elif not bash and self.nomatch is not False:
                        self.notes.append("an unmatched pathname expansion depends on a shell option")
                        fields.append(_ExpandedWord(UNKNOWN))
                    else:
                        fields.append(cls(field))
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

    def run_simple(self, node, assigns: list, words: list[str], stdin: str | None, outs: list, after: list,
                   fails: bool = False) -> None:
        """Run a simple command, whose words and redirections `simple` expanded; where `fails`, the
        command does not run, as an unset parameter or a file open in its redirections failed it (see
        `failed_redirect`)."""
        before, self.output = self.output, ""
        if not fails and len(words) == 1 and _alt(self.expand(words[0]))[0] == "exec" and "exec" not in self.functions:
            # `exec` with only redirections: they hold for the rest of the shell. Standard error
            # sent where standard output goes may stay there (where a branch ran it, say).
            def redirect():
                self.err_out = self.err_out or _err_state(_redirects(node), self.err_out)
                self.exec_err = self.exec_err or self.err_out
                for target, append in outs:
                    if target != CLOSED:
                        self.wrote(target, "", append)
                targets = [t for t, _ in outs if t not in {"/dev/stdout", "/dev/fd/1"}]
                if outs:
                    # Standard error that may be standard output, or several targets (zsh's MULTIOS,
                    # bash's last): where later output goes is unknown.
                    certain = len(outs) == 1 and MAYBE_OUT not in targets
                    self.diverted = None if not targets else (tuple(targets), certain)
                self.output = before if not self.stray else None
                self.set_status(OK)

            if assigns:
                self.with_assignments(assigns, "exec", redirect, bare=not _redirects(node))
            else:
                redirect()
            return
        diverted, emits, err, mark = self.diverted, self.emits, self.err_out, self.jumped
        closed, tees = self.out_closed, self.tees()  # MULTIOS as the redirections are made
        trims, self.kept = self.trims, None
        if outs:
            self.diverted = None  # inside, standard output is the command's own (`f > file`)
            self.out_closed = any(target == CLOSED for target, _ in outs)
        around, self.err_around = self.err_around, err
        self.err_out = _err_state(_redirects(node), err)
        noisy = self.noisy
        if fails:
            self.failed_redirect()
        elif not words:
            self.assignments(node, assigns)
        else:
            verb = _alt(self.expand(words[0]))[0]
            # Transparent zsh precommands leave prefix-assignment persistence to the selected
            # command. Other shells still see the original verb.
            selected = list(words)
            while selected:
                name = _alt(self.expand(selected[0]))[0]
                if name in {"noglob", "-"} or name == "nocorrect" and isinstance(selected[0], _ReservedWord):
                    selected = selected[1:]
                elif name == "builtin" and len(selected) > 1 and selected[1] in {"-", "noglob"}:
                    selected = selected[1:]
                else:
                    break
            zsh_verb = _alt(self.expand(selected[0]))[0] if selected else verb
            ends = self.child_ends

            def runs(forked: bool) -> None:
                # zsh expands an external command's prefix assignments in its child (see
                # `failed_redirect`), losing what they assign.
                def run():
                    self.forked_words -= forked
                    try:
                        if self.child_ends > ends and forked:
                            self.either(lambda: self.command(words, stdin), self.failed_redirect)
                        else:
                            self.command(words, stdin)
                    finally:
                        self.forked_words += forked
                self.forked_words += forked
                try:
                    with self.in_child(["zsh"] if forked else []):
                        self.with_assignments(assigns, verb, run, zsh_verb=zsh_verb)
                finally:
                    self.forked_words -= forked
            ways = self.inline_ways(words, "zsh") if assigns and "zsh" in self.kinds() else {True}
            if len(ways) == 1:
                runs(not ways.pop())
            else:
                self.either(lambda: runs(True), lambda: runs(False))
        kept = False if self.trims == trims else self.kept  # see `kept`: unknown when nested
        self.kept = None
        if outs:
            self.diverted, self.out_closed = diverted, closed
        if self.err_out and not self.quiet_errors(words, outs):
            self.noisy += 1
            self.output = None  # its diagnostics went where its output went
        elif self.err_out and not err and self.noisy > noisy:
            self.output = None  # diagnostics from a substitution or pipe inside reached it too
        self.err_out, self.err_around = err or self.exec_err, around
        own = self.output if words else ""
        if words and own != "":
            self.closed_status(words, own, outs)
        self.carry(mark, before, not outs and not after and self.diverted is None and not self.stray)
        self.write_outs(outs, None if fails else own, tees, self.stage is not None and self.stage in (node, node.parent))
        self.emit(before, own, outs, after, self.stage is not None and self.stage in (node, node.parent), node,
                  bool(outs) or self.emits == emits, tees, kept)

    def with_assignments(self, assigns: list, verb: str, run, bare: bool = False,
                         zsh_verb: str | None = None) -> None:
        """Run `run`, the command `verb` after the assignments `assigns`, which hold for it alone,
        exported to it. One to a readonly variable is skipped; in bash's POSIX mode before a special
        builtin, dash, and zsh before a builtin or function, it ends the shell; zsh then fails an
        external command.

        Afterwards bash and native zsh put the old values back, over any the command set; sh and dash
        keep what the command left before a special builtin, sh also before a function, and zsh
        before an `exec` with no redirections (`bare`), or with POSIX_BUILTINS before functions and
        special builtins. sh's stay exported, as do zsh's before a function with POSIX_BUILTINS;
        sh then takes an integer's value as arithmetic (see INTEGER). `zsh_verb` is the command
        selected by transparent zsh precommands. Measured on bash 3.2, its sh, dash and zsh
        5.9."""
        saved, exports = {}, {}
        zsh_verb = verb if zsh_verb is None else zsh_verb
        builtin = zsh_verb in self.functions or zsh_verb in ZSH_BUILTINS - {"command"}  # zsh's command: external
        special = verb in SPECIAL_BUILTINS
        prefix = {"bash": "skip", "posix": "exit" if special else "skip", "dash": "exit",
                  "zsh": "abort" if builtin else "fail"}
        defined = self.functions.get(verb)
        function = False if defined is None else True if None not in defined else None
        zsh_defined = self.functions.get(zsh_verb)
        zsh_function = False if zsh_defined is None else True if None not in zsh_defined else None
        zsh_keeps = (True if zsh_verb == "exec" and bare else
                     self.posixbuiltins if zsh_verb in SPECIAL_BUILTINS or zsh_function is True else
                     False if zsh_function is False or self.posixbuiltins is False else None)
        zsh_function_exports = (False if zsh_function is False or self.posixbuiltins is False else
                                True if zsh_function is True and self.posixbuiltins is True else None)
        kept = {"bash": False, "posix": True if special else function, "dash": special, "zsh": zsh_keeps}

        def prefix_from(i):
            for j in range(i, len(assigns)):
                a = assigns[j]
                name = _assigned_name(a)
                if name is not None and name not in saved:
                    saved[name] = self.vars.get(name)
                    exports[name] = self.exports.get(name)
                if name is not None and self.readonly(name) is not False:
                    def go(write, failed, a=a, j=j, name=name):
                        if write:
                            self.assign(a, around=True, prefix=True)
                            self.exports[name] = True
                        if failed:
                            self.set_status(FAILED)
                        else:
                            prefix_from(j + 1)

                    self.readonly_write(name, prefix, go, around=True)
                    return
                self.assign(a, around=True, prefix=True)
                if name is not None:
                    self.exports[name] = True
            run()

        def put_back(values: bool = True):
            for name, old in saved.items() if values else ():
                if old is None:
                    self.vars.pop(name, None)
                else:
                    self.vars[name] = old
            for name, old in exports.items():
                if old is None:
                    self.exports.pop(name, None)
                else:
                    self.exports[name] = old

        def sh_keeps():
            for name in saved:
                if name in self.vars and self.integer(name) is not False:
                    self.set_var(name, self.vars[name], around=True)

        def zsh_keeps_prefix():
            if zsh_function_exports is False:
                put_back(values=False)
            elif zsh_function_exports is None:
                self.either(lambda: None, lambda: put_back(values=False))

        prefix_from(0)
        ways = {}
        for kind in self.kinds():
            if kept[kind] is not True:
                ways["back"] = put_back
            if kept[kind] is not False:
                ways[kind] = (sh_keeps if kind == "posix" else zsh_keeps_prefix if kind == "zsh" else
                              lambda: put_back(values=False))
        thunks = list(ways.values())
        thunks[0]() if len(thunks) == 1 else self.either(*thunks)

    def assignments(self, node, assigns: list) -> None:
        """Assignments with no command. One to a readonly variable is an error that ends the shell
        or the eval it is in (READONLY_ASSIGN); bash prints it outside the redirections."""
        def assign_from(i):
            for j in range(i, len(assigns)):
                name = _assigned_name(assigns[j])
                if name is not None and self.readonly(name) is not False:
                    def go(write, failed, j=j):
                        if write:
                            self.assign(assigns[j], around=True)
                        assign_from(j + 1)

                    self.readonly_write(name, READONLY_ASSIGN, go, around=True)
                    return
                self.assign(assigns[j], around=True)
            self.set_status(_assignment_status(node))

        assign_from(0)

    def tees(self) -> bool | None:
        """Whether a pipeline stage's output still goes down the pipe after a redirection: zsh's
        MULTIOS (on in zsh, off in its sh and ksh emulations; bash has no such option)."""
        if self.dialect == "posix":
            return False
        if self.dialect == "zsh":
            return self.multios
        return False if self.multios is False else None

    def buffers(self) -> bool:
        """Whether the shell may be bash, which buffers what builtins print (see `pending`); zsh
        and dash drop what a builtin wrote to a closed standard output (measured on zsh 5.9 and
        macOS's dash)."""
        return self.dialect != "zsh" and self.kinds() != ["dash"]

    def forked(self, node) -> bool:
        """Whether a redirection on this command or compound lasts as long as its process: it is a
        subshell, or a pipeline stage that runs in a subshell. Otherwise the shell undoes it after."""
        if node.type == "subshell":
            return True
        unit = node.parent if node.parent is not None and node.parent.type == "redirected_statement" else node
        pipeline = unit.parent
        if pipeline is None or pipeline.type != "pipeline":
            return False
        last = pipeline.named_children[-1].start_byte == unit.start_byte
        return not last or self.lastpipe is False  # bash runs the last stage here with lastpipe

    def write_outs(self, outs: list, own: str | None, tees: bool | None, piped: bool = False) -> None:
        """What a command printed (`own`) reaches the files its standard output was sent to: each
        of them under zsh's MULTIOS (`tees`, as the redirections were made), else only the last,
        the others opened (`>` empties them) and left. A pipeline stage's under MULTIOS (`piped`)
        goes through a process zsh starts to copy it to the pipe and the files, which may end at
        the pipe before it writes them (`echo x > f | true`): what they hold is then unknown."""
        if piped and tees is not False or any(target == TANGLED for target, _ in outs):
            own = None
        for k, (target, append) in enumerate(outs):
            last = k == len(outs) - 1
            self.wrote(target, own if last or tees is True else "" if tees is False else _either_output([own, ""]),
                       append)

    def emit(self, before: str | None, own: str | None, outs: list, after: list, piped: bool,
             node=None, direct: bool = True, tees: bool | None | str = "now",
             kept: str | None | bool = False) -> None:
        """Where what a command printed (`own`) goes, given its standard output redirections
        (`outs`), then run what its here-document carries after it (`after`). Redirected away, it
        reaches neither what follows nor a pipe, unless the command is a stage before a pipe's end
        and zsh's MULTIOS sends it down the pipe too. Closed (`>&-`), it reaches nothing; bash keeps
        what a builtin wrote then, unless the redirection lasts as long as the process (`node`
        forked), and writes it later (see `pending`). Output that reaches the shell's standard
        output goes where `exec` sent it, if it did, unless the commands inside this one sent it
        there already (`direct` false: `eval 'echo a; exec > f'` prints a first). `tees` is MULTIOS
        where the redirections were made (`emulate sh` inside a group turns it off after). `kept`
        is what bash keeps of `own` for a closed standard output (False: all of it; see `kept`)."""
        self.emits += 1
        closed = any(target == CLOSED for target, _ in outs)
        away = any(target not in {"/dev/stdout", "/dev/fd/1"} for target, _ in outs)
        pipe = any(not isinstance(stmt, tuple) and stmt.type == "pipeline" for stmt in after)
        tees = self.tees() if tees == "now" else tees
        reach = False if closed else True if not away else tees if piped or pipe else False
        if any(target == MAYBE_OUT for target, _ in outs):
            reach = None  # standard error may be standard output
            if piped or pipe:
                self.stray = True  # a stage's standard error passes the pipe, to the output around it
        shown = own if reach else "" if reach is False else _either_output([own, ""])
        held = own if kept is False else kept
        if closed and own != "" and self.buffers() and not (node is not None and self.forked(node)):
            self.hold(held)
        if pipe:
            # `cat <<EOF | python3`: the rest of the pipeline reads what this command printed.
            self.output = before
        elif self.diverted is None or not direct:
            self.output = _concat(before, shown)
        else:
            targets, certain = self.diverted
            for target in targets:
                if target == CLOSED:
                    if shown != "" and self.buffers():
                        self.hold(held if shown == own else _either_output([held, ""]))
                else:
                    self.wrote(target, shown if certain else None, True)
            self.output = before if certain else None
        if self.stray:
            self.output = None
        def steps(stmt, op=None):
            # The grammar attaches `&&`/`||` and their right side to a here-document. Flatten
            # that continuation so `false <<E && true || echo x` keeps the list's usual left
            # associativity instead of treating its right side as a single guarded group.
            if stmt.type == "list":
                for child in stmt.children:
                    if not child.is_named:
                        op = _text(child)
                    elif child.type in STATEMENTS:
                        yield from steps(child, op)
                        op = None
            else:
                yield op, stmt

        continuations = [part for stmt in after for part in
                         (steps(stmt[1], stmt[0]) if isinstance(stmt, tuple) else steps(stmt))]
        for k, (op, stmt) in enumerate(continuations):
            def run(stmt=stmt, k=k, op=op):
                with self.guarding() if k < len(continuations) - 1 else nullcontext():
                    if stmt.type == "pipeline" and op is None:
                        self.pipeline(self._stages(stmt), shown, piped=True)
                    else:
                        self.visit(stmt)
            if op in {"&&", "||"}:
                self.fork(run, OK if op == "&&" else FAILED)
            else:
                run()

    def quiet_errors(self, words: list[str], outs: list) -> bool:
        """Whether a simple command certainly writes nothing to standard error: a few builtins
        that cannot fail as used, and commands that run others (whose own commands count)."""
        closed = any(target == CLOSED for target, _ in outs) or not outs and (
            self.out_closed or self.diverted is not None and CLOSED in self.diverted[0])
        if not words or closed:
            return not words  # writing to a closed standard output is an error
        verb = _alt(self.expand(words[0]))[0]
        args = [_alt(self.expand(w))[0] for w in words[1:]]
        if verb in {"echo", ":", "true", "false", "pwd", "exit", "wait", "eval", "export", "typeset",
                    "declare", "unset", "alias", "setopt", "unsetopt", "emulate", "shopt", "set",
                    "shift"} or verb in self.functions or verb in SHELLS:
            return True
        if verb == "printf":
            return bool(args) and re.fullmatch(r"(?:[^%]|%%|%s)*", args[0]) is not None
        if verb in {"return", "local"}:
            return any(f.kind == "function" for f in self.frames)
        if verb in {"cd", "pushd", "popd"}:
            return all(w.status == OK for w in self.worlds)
        if verb in {"dirname", "basename"}:
            return 1 <= len(args) <= (1 if verb == "dirname" else 2) and not any(a.startswith("-") for a in args)
        return False

    def closed_status(self, words: list[str], own: str | None, outs: list) -> None:
        """A simple command that printed `own` to a closed standard output: bash's and dash's
        echo, printf, pwd and type fail, zsh's do not; cat and dirname fail, other programs may
        not. Functions, eval and the like run commands of their own, which decide."""
        targets = [t for t, _ in outs] or (
            [CLOSED] if self.out_closed else list(self.diverted[0]) if self.diverted is not None else [])
        if CLOSED not in targets:
            return
        certain = set(targets) == {CLOSED} and (outs or self.out_closed or self.diverted[1])
        names = [_alt(self.expand(w))[0] for w in words]
        while len(names) > 1 and names[0] in {"command", "builtin"}:
            names = names[1:]
        verb = names[0]
        if verb in self.functions and words[0] == verb or verb in {"eval", "source", ".", "exec"}:
            return
        if verb not in {"echo", "printf", "pwd", "print", "type"}:
            self.set_status(MAYBE)
            return
        fails = [kind != "zsh" for kind in self.kinds()]
        if all(fails) and certain and own is not None and "" not in _choices(own):
            self.set_status(FAILED)
        elif any(fails):
            self.set_status(MAYBE)

    def hold(self, text: str | None) -> None:
        """Note that bash may still buffer `text` for standard output (see `pending`)."""
        self.pending = text if self.pending is False else _concat(self.pending, text)

    def flush(self) -> None:
        """At a shell's exit, bash writes what it may still buffer to its standard output."""
        if self.pending is False or not self.buffers():
            return
        if self.diverted is None:
            self.output = _either_output([self.output, _concat(self.output, self.pending)])
            return
        targets, certain = self.diverted
        for target in targets:
            if target != CLOSED:
                self.wrote(target, _either_output(["", self.pending]) if certain else None, True)
        if not certain:
            self.output = None

    # Commands

    def cd_candidates(self, target: str, cwd: Path) -> list[Path]:
        """Where `cd target` may go from cwd, in the order the shell tries them: each CDPATH entry
        first (for a relative target not starting with . or ..), then cwd itself."""
        out = []
        cdpath = self.vars.get("CDPATH")
        if re.match(r"//(?!/)", target):
            self.slashed = True
        if cdpath and not target.startswith(("/", "~", "./", "../")) and target not in {".", ".."}:
            for entry in cdpath.split(":"):
                if re.match(r"//(?!/)", entry):
                    self.slashed = True
                base = cwd if entry in {"", "."} else _resolve(entry, cwd, bare=True)
                p = _resolve(target, base, bare=True) if base is not None else None
                if p is not None:
                    out.append(p)
        p = _resolve(target, cwd, bare=True)
        return [*dict.fromkeys(out + ([p] if p is not None else [cwd]))]

    def chdir(self, target: str | None, push: bool = False) -> None:
        """cd in every world (with no target, to $HOME; where HOME is unset, the cd fails). A target
        missing at audit time forks the world: the cd may have worked (it was there then) or failed,
        leaving the shell where it was. For a literal scratch directory the failed place is an
        alternative; an expanded target also keeps failure primary, since expansion can produce
        a name rather than the intended directory. A target that is a file fails. `push`: pushd, which adds the directory it
        leaves to the stack only where it moves."""
        expanded = isinstance(target, _ExpandedWord)
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
                t = self.tilde(t, w)
                if UNKNOWN in t:
                    self.known = False
                    out.append(w._replace(status=MAYBE))
                    continue
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
                    out.append(w._replace(status=FAILED, primary=primary if expanded else False))
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
        self._command(words, stdin)
        if words and os.path.basename(words[0]) in {"cd", "chdir", "pushd", "popd"}:
            # A successful directory builtin refreshes bash's directory variables. Preserve
            # explicit overrides after failure; mixed outcomes cannot retain one exact value.
            for name in ("PWD", "OLDPWD"):
                key = "\0" + name
                if key not in self.vars:
                    continue
                statuses = {w.status for w in self.worlds}
                if statuses == {OK}:
                    self.vars.pop(key, None)
                elif statuses != {FAILED}:
                    self.vars[key] = UNKNOWN
                    self.notes.append("a directory variable has different possible values after cd")

    def _command(self, words: list[str], stdin: str | None = None) -> None:
        """Run a simple command. What it prints follows what the commands before it printed to the
        same place (`output`): the handlers below set what this one prints, starting from nothing."""
        before, self.output = self.output, ""
        mark = self.jumped
        try:
            self._run_command(words, stdin)
            if self.pending is not False and self.buffers():
                # bash writes what it buffers before a builtin's next write, which empties it.
                own = self.output
                self.output = _either_output([own, _concat(self.pending, own)])
                if own != "":
                    self.pending = _either_output(["", self.pending])
        finally:
            self.output = _concat(before, self.output)
            self.carry(mark, before, True)

    def quiet(self, verb: str, args: list[str]) -> bool:
        """Whether a builtin or file command certainly prints nothing on standard output. The
        listing forms print: `set` and `set -o`, `export -p`, `declare -f`, zsh's `typeset x` (for
        a set x), `alias x`, `cd -` (the new directory), pushd and popd (the stack), `-v` (each file)."""
        flags = [a for a in args if a.startswith(("-", "+")) and len(a) > 1 and not ASSIGN.match(a)]
        names = [a for a in args if a not in flags]
        if verb in {"true", "false", ":", "test", "[", "[[", "unset", "exit", "return", "break", "continue",
                    "let", "shift", "unalias", "unfunction", "getopts", "read"}:
            return True
        if verb in {"cd", "chdir"}:
            return "-" not in args
        if verb == "set":
            return bool(args) and args not in (["-o"], ["+o"])
        if verb in {"export", "readonly", "declare", "typeset", "local"}:
            if not names or any(re.search(r"[pfF]", f) for f in flags):
                return False
            return verb in {"export", "readonly"} or self.dialect == "posix" or all("=" in n for n in names)
        if verb == "alias":
            return bool(args) and all("=" in a for a in args)
        if verb in {"mkdir", "touch", "cp", "mv", "rm", "rmdir", "ln", "chmod"}:
            return not any(re.fullmatch(r"-[a-zA-Z]*v[a-zA-Z]*", a) or a == "--verbose" for a in args)
        if verb in {"setopt", "unsetopt"}:
            return bool(args)
        if verb == "shopt":
            return bool({"-s", "-u", "-q"} & set(args))
        if verb == "emulate":
            return bool(names) and not any("l" in f for f in flags)
        return False

    def _run_command(self, words: list[str], stdin: str | None = None, lacking: bool = True) -> None:
        """Run a command (`lacking`: where dash may lack its builtin, see DASH_LACKS)."""
        if not words:
            return
        self.set_status(MAYBE)
        verb_word, args = words[0], words[1:]
        if "/" in verb_word and not verb_word.startswith(SYSTEM_BIN):
            self.add(verb_word, bare=True)  # running a file by path reads it
            if self.with_script(verb_word, lambda text: self.run_script(verb_word, text, None, args, stdin=stdin)):
                return
        verb = os.path.basename(verb_word)
        if (verb in {"noglob", "-"} or verb == "nocorrect" and isinstance(verb_word, _ReservedWord)) and \
                "zsh" in self.kinds():
            def modified():
                self.command(args, stdin)
            if self.kinds() == ["zsh"]:
                modified()
            else:
                self.either(lambda: self.as_dialect("zsh", modified),
                            lambda: self.as_dialect("posix", lambda: self._run_command(words, stdin, lacking)))
            return
        for kind in ("aliases", "functions"):
            alts = getattr(self, kind).get(verb, ())
            if len(alts) > 1:
                # Defined in only some of the branches that may have run, or differently there.
                self.either(*(lambda a=a: self.shadowed(kind, verb, a, words, stdin) for a in alts))
                return
        if verb in self.aliases and self.calls < 4 and self.inlined < 256:
            # Whether the alias expands: zsh expands aliases in scripts, but reads a `-c` string
            # whole before it runs it, so not one defined in the same string; bash only when told to
            # (expand_aliases). The audit follows both.
            def expanded():
                self.calls += 1
                self.inlined += 1
                try:
                    self.run(" ".join([self.aliases[verb][0], *map(shlex.quote, args)]), alias=True)
                finally:
                    self.calls -= 1
            self.either(expanded, lambda: self.shadowed("aliases", verb, None, words, stdin))
            return
        if verb in self.functions and self.calls < 4 and self.inlined < 256:
            # A function runs in the calling shell, with its own positional parameters and locals.
            for a in args:
                self.add(a, bare=False)
            # The call's locals, with the positional parameters, which go back at the return too.
            self.locals.append({k: self.vars.get(k) for k in POSITIONAL})
            self.local_exports.append({})
            self.bind(args)
            self.calls += 1
            self.inlined += 1
            options = self.options()
            body = self.functions[verb][0]
            sticky = self.sticky_functions.get(id(body))
            sticky = sticky[1] if sticky is not None and sticky[0] is body else None
            outer_sticky = self.sticky
            if sticky is not None:
                # Sticky emulation: the function runs with the options it was defined under, and
                # functions it defines keep them too.
                self.restore_options(sticky)
                self.sticky = sticky
            try:
                self.call(body)
            finally:
                self.calls -= 1
                self.sticky = outer_sticky
                if sticky is not None:
                    self.restore_options(options)
                elif self.localoptions is True:
                    self.restore_options(options)
                elif self.localoptions is None:
                    self.restore_options({name: value if value == options[name] else None
                                          for name, value in self.options().items()})
                # zsh always restores LOCAL_OPTIONS itself, even if the function disables it
                # and deliberately leaves its other option changes in the caller.
                self.localoptions = options["localoptions"]
                self.pop_locals()
            return
        if lacking and verb in DASH_LACKS and "dash" in self.kinds():
            def missing():
                self.complain()
                self.output = ""
                self.set_status(FAILED)
            if self.kinds() == ["dash"]:
                missing()
            else:
                self.either(lambda: self._run_command(words, stdin, lacking=False), missing)
            return
        # What the rest print: nothing for a quiet builtin, what the code prints where the cases
        # below run code, and otherwise what they work out, or unknown.
        self.output = "" if self.quiet(verb, args) else None
        if verb in SUCCEEDS or (verb == "mkdir" and any(re.fullmatch(r"-[a-zA-Z]*p[a-zA-Z]*", a) for a in args)):
            self.set_status(OK)
        if verb in {"true", ":"}:
            return
        if verb == "shopt":
            # zsh and dash have no shopt. bash's takes -p, -q, -s, -u and -o, in clusters too;
            # another, or both -s and -u, fail it, changing nothing. It fails a name it lacks (a
            # later bash has more), and without -s or -u its status says whether the option is on.
            kinds = set(self.kinds())
            if kinds <= {"zsh", "dash"} or self.dialect == "zsh":
                self.complain()
                self.set_status(FAILED)
                return
            if kinds & {"zsh", "dash"}:
                self.complain()  # where the shell lacks it
            flags, j = set(), 0
            while j < len(args) and args[j].startswith("-") and len(args[j]) > 1:
                j += 1
                if args[j - 1] == "--":
                    break
                flags |= set(args[j - 1][1:])
            names = args[j:]
            if not flags <= set("pqsuo") or {"s", "u"} <= flags:
                self.complain()
                self.set_status(FAILED)
                return
            if {"s", "u"} & flags:
                enabled = "s" in flags
                for name in names:
                    if "o" in flags:
                        self.option(name, enabled)  # `shopt -o -s posix` is `set -o posix`
                    elif name == "xpg_echo":
                        self.xpgecho = enabled if self.dialect == "posix" or self.xpgecho == enabled else None
                    elif name == "lastpipe":
                        self.lastpipe = enabled
            known = all(n in (BASH_OPTIONS if "o" in flags else BASH_SHOPTS) for n in names)
            self.set_status(OK if kinds <= {"bash", "posix"} and self.dialect == "posix" and known and
                            {"s", "u"} & flags else MAYBE)
            return
        if verb == "false":
            self.set_status(FAILED)
            return
        if verb == "exit":
            self.leave()  # the shell has ended: nothing after it runs
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
                v = self.arith(a, command=True)
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
        if verb in {"setopt", "unsetopt"}:
            if self.dialect == "posix":
                self.set_status(FAILED)
            else:
                for option in args:
                    if option.startswith(("-", "+")):
                        enabled = (verb == "setopt") == option.startswith("-")
                        for letter in option[1:]:
                            name = {"y": "shwordsplit", "F": "noglob"}.get(letter)
                            if name:
                                self.option(name, enabled)
                            else:
                                self.notes.append("a shell option letter the audit cannot model")
                    else:
                        self.option(option, verb == "setopt")
                # zsh fails an option it lacks; bash has no setopt.
                bad = any(not o.startswith(("-", "+")) and not _zsh_option(o) for o in args)
                self.set_status(FAILED if bad else OK if self.dialect == "zsh" else MAYBE)
            return
        if verb == "emulate":
            if self.dialect == "posix":
                self.set_status(FAILED)
            elif self.dialect == "zsh":
                self.emulate(args)
            else:
                self.either(lambda: self.emulate(args), lambda: self.set_status(FAILED))  # bash has no emulate
            return
        if verb in {"test", "["}:
            for a in args:
                if a not in {"]", "!"} and not re.fullmatch(r"-[a-zA-Z]+", a):
                    self.add(a, bare=self.cwd != self.workdir, operand=False)
            self.set_status(self.test_args(args[:-1] if verb == "[" and args[-1:] == ["]"] else args))
            return
        if verb == "read":
            lines = stdin.splitlines() if stdin is not None else None
            names = _read_names(args)
            if any(re.fullmatch(r"-[A-Za-z]*[aA][A-Za-z]*", a) for a in args):
                # An array read (bash's -a NAME, zsh's -A; each fails in the other shell): what it
                # sets the audit does not follow.
                for a in args:
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", a) and self.readonly(a) is not True:
                        self.vars[a] = UNKNOWN
                self.set_status(MAYBE)
                return

            def read(write, failed):
                if failed:  # a readonly name: what read set of the others is unknown
                    for n in names:
                        if self.readonly(n) is not True:
                            self.vars[n] = UNKNOWN
                    self.set_status(FAILED)
                    return
                self.bind_read(names, None if lines is None else lines[0] if lines else "", self.ifs())
                self.set_status(MAYBE if lines is None else OK if lines else FAILED)

            stuck = next((n for n in names if self.readonly(n) is not False), None)
            if stuck is None:
                read(True, False)
            else:
                self.readonly_write(stuck, READONLY_READ, read)
            return
        if verb == "alias":
            for a in args:
                m = re.match(r"^([^=\s]+)=(.*)$", a, re.S)
                if m:
                    self.aliases[m.group(1)] = (m.group(2),)
            self.set_status(OK)
            return
        if verb in {"export", "declare", "typeset", "local", "readonly"}:
            self.declaration(verb, *_declaration_words(args))
            return
        if verb in {"integer", "float"} and "zsh" in self.kinds() and verb not in self.functions:
            # zsh's `integer` is `typeset -i` and `float` `typeset -F`; other shells have neither.
            flags, names = _declaration_words(args)
            # The `-` ends the option it implies: a number right after `integer` is a name, not a base.
            zsh = lambda: self.as_dialect("zsh", lambda: self.declaration(
                "typeset", ("-i" if verb == "integer" else "-F") + "-" + flags, names))
            if self.kinds() == ["zsh"]:
                zsh()
            else:
                self.either(zsh, lambda: (self.complain(), self.set_status(FAILED)))
            return
        if verb in SHELLS:
            self.shell_command(verb, args, stdin)
            return
        if verb == "eval":
            self.output = ""
            self.evaluate(lambda: self.run(" ".join(args)))
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
                    self.output = ""
                    try:
                        self.evaluate(lambda: self.call(text))
                    finally:
                        self.calls -= 1
                        for k, old in saved.items():
                            if old is None:
                                self.vars.pop(k, None)
                            else:
                                self.vars[k] = old

                if _alt(self.expand(args[0]))[0] in STDIN_FILES:
                    # Code on standard input, which the shell reads as the file.
                    if stdin is None or UNKNOWN in stdin:
                        self.notes.append("a program reads code from input the audit does not know")
                    else:
                        source(stdin)
                else:
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
            self.output = str(self.cwd) + "\n" if self.known and len(places) == 1 and not self.slashed_text() else None
            return
        operands = [a for a in args if not a.startswith("-")]
        if verb in {"realpath", "grealpath"} or (verb in {"readlink", "greadlink"} and any(
                re.fullmatch(r"-[a-zA-Z]*[fem][a-zA-Z]*", a) for a in args)):
            p = self.add(operands[0], bare=True) if operands else None
            relative = bool(operands) and not os.path.isabs(operands[0])
            self.output = (str(p) + "\n" if p is not None and self.known and (len(places) == 1 or not relative)
                           else None)
            return
        if verb in {"dirname", "basename"} and len(args) == len(operands) and 1 <= len(operands) <= (
                1 if verb == "dirname" else 2):
            # POSIX's dirname and basename (with a suffix to drop); other forms differ by system.
            self.output = (_dirname(operands[0]) if verb == "dirname" else _basename(*operands)) + "\n"
            return
        if verb == "trap":
            self.trap(args)
            return
        if verb == "printf" and args[:1] == ["-v"] and len(args) >= 3:
            self.printf_v(args[1], args[2:])
            return
        if verb == "getopts" and len(args) >= 2:
            self.getopts(args[1])
            return
        if verb in {"echo", "printf"}:
            if verb == "echo":
                self.output = _echo(args, self.shell_name, self.tilde, self.posix_mode(), self.xpgecho, self.bsdecho)
            else:
                self.output = _printf(args, self.shell_name)
                first = _printf(args, self.shell_name, once=True)
                if first != self.output:
                    self.kept, self.trims = first, self.trims + 1
            return  # the words echo and printf print are data, including words that look like paths
        elif verb == "tee" or (verb == "cat" and not operands):
            self.output = stdin  # tee passes its input through, whatever files it also writes
        elif verb == "cat" and not any(a.startswith("-") and a != "-" for a in args):
            # The files' texts one after the other, where the audit has each (see `file_text`).
            out: str | None = ""
            for a in args:
                out = _concat(out, stdin if a == "-" else self.file_text(a))
            self.output = out
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
        stdin_code, assignments = False, {}
        if syntax is not None:
            handled, stdin_code, assignments = self.code_args(verb, syntax, args, code, scripts)
            skip |= handled
        for word in scripts:
            code += [t for t in self.scripts(word) if t is not None]  # a script or program file it runs
        if stdin_code and (stdin is None or UNKNOWN in stdin):
            self.notes.append("a program reads code from input the audit does not know")
        if stdin_code and stdin:
            code.append(stdin)
        # awk may never open its file operands, or may open others instead.
        awk_operands = _awk_operands("\n".join(code)) if verb in AWKS and code else None
        for j, a in enumerate(args):
            if j in skip:
                continue
            if a.startswith("-") and a != "-":
                if "=" in a and verb not in SEARCH_SYNTAX:  # a search tool's option values have their roles
                    self.add(a.split("=", 1)[1], bare=False, chdirs=tuple(chdirs))
                continue
            if awk_operands and not re.fullmatch(r"[A-Za-z_]\w*=.*", a, re.S):
                if awk_operands == "maybe":
                    n = len(self.paths)
                    self.add(a, bare=bare, chdirs=tuple(chdirs), operand=True)
                    self.alt_paths += self.paths[n:]
                    del self.paths[n:]
                continue
            self.add(a, bare=bare, chdirs=tuple(chdirs), chdir_bare=verb in DIR_BARE, operand=True)
            if any(c in a for c in "'\"()"):
                self.scan_code(a)
        if verb in AWKS:
            # awk's operands after the program are files, and `name=value` assignments.
            files = [a for j, a in enumerate(args)
                     if j not in skip and not re.fullmatch(r"[A-Za-z_]\w*=.*", a, re.S)]
            from_stdin = [a in AWK_STDIN for a in files]
            # An operand `RS=...` changes the record separator for the files after it.
            resplit = any(re.match(r"RS=", a) for j, a in enumerate(args) if j not in skip)
            self.awk_code("\n".join(code), assignments, None if stdin_code else stdin,
                          True if all(from_stdin) else False if not any(from_stdin) else None, resplit)
        else:
            for c in code:
                self.scan_code(c)
            if syntax is not None and not stdin_code:
                self.interpreter_input(verb, "\n".join(code), stdin)

    def printf_v(self, name: str, args: list[str]) -> None:
        """`printf -v NAME FORMAT...` (bash and zsh): what printf would print goes to NAME. dash has
        no -v and fails, printing nothing. At a readonly NAME, bash skips the write, zsh aborts."""
        self.output = ""
        text = _printf(args, self.shell_name)

        def write():
            def go(write, failed):
                if write:
                    self.set_var(name, UNKNOWN if text is None else text)
                self.set_status(FAILED if failed else OK)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                self.readonly_write(name, READONLY_PRINTF, go)
            else:
                self.set_status(FAILED)

        def dash():
            self.complain()
            self.set_status(FAILED)

        kinds = self.kinds()
        if kinds == ["dash"]:
            dash()
        elif "dash" in kinds:
            self.either(write, dash)
        else:
            write()

    def getopts(self, name: str) -> None:
        """`getopts OPTSTRING NAME [ARG...]`: NAME, OPTARG and OPTIND take values the audit does not
        follow. At a readonly NAME, bash and dash fail, zsh aborts."""
        self.output = ""

        def go(write, failed):
            if write:
                for k in (name, "OPTARG", "OPTIND"):
                    if self.readonly(k) is not True:
                        self.vars[k] = UNKNOWN
                if self.integer(name) is not False:
                    # The option letter (or `?`) as an expression (INTEGER_ASSIGN).
                    self.error_ways(INTEGER_ASSIGN, lambda write, failed: None, allowed=True)
            self.set_status(FAILED if failed else MAYBE)

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            self.readonly_write(name, READONLY_GETOPTS, go)
        else:
            self.set_status(MAYBE)

    def option(self, spelling: str, enabled: bool) -> None:
        """Option names the audit follows. zsh ignores case and underscores and accepts `noNAME`.
        Another option a shell has that could change what the code reads, prints or where it runs
        (noclobber, keyword, physical, cdablevars, globdots and the like; see HARMLESS_OPTIONS for
        the rest) makes the call suspect."""
        name = spelling.lower().replace("_", "")
        if name == "posix":
            # bash's POSIX mode; zsh has no option of that name.
            if self.dialect != "zsh":
                self.posix = enabled if self.dialect == "posix" or self.posix == enabled else None
            return
        options = {"noglob": ("noglob", True), "glob": ("noglob", False), "bsdecho": ("bsdecho", True),
                   "shwordsplit": ("shwordsplit", True), "localoptions": ("localoptions", True),
                   "allexport": ("allexport", True), "braceexpand": ("braceexpand", True),
                   "ignorebraces": ("braceexpand", False), "ksharrays": ("ksharrays", True),
                   "shoptionletters": ("shoptionletters", True), "globsubst": ("globsubst", True),
                   "nomatch": ("nomatch", True), "multios": ("multios", True),
                   "posixbuiltins": ("posixbuiltins", True), "posixidentifiers": ("posixidentifiers", True),
                   "typesettounset": ("typesettounset", True), "errexit": ("errexit", True),
                   "nounset": ("nounset", True), "unset": ("nounset", False), "xtrace": ("xtrace", True),
                   "verbose": ("verbose", True), "shnullcmd": ("shnullcmd", True),
                   "cshnullcmd": ("cshnullcmd", True)}
        if name.startswith("no") and name not in options and name[2:] in options:
            name, enabled = name[2:], not enabled
        if name not in options:
            harmless = name in HARMLESS_OPTIONS or name.startswith("no") and name[2:] in HARMLESS_OPTIONS
            if not harmless and (_zsh_option(name) or spelling in BASH_OPTIONS or spelling in DASH_OPTIONS):
                self.notes.append("a shell option the audit does not model")
            return
        attr, positive = options[name]
        value = enabled == positive
        if self.dialect is None and spelling not in {"noglob", "allexport", "braceexpand", "errexit", "nounset",
                                                     "xtrace", "verbose"}:
            # An unnamed bash does not recognize zsh's options; keep that possibility.
            current = getattr(self, attr)
            value = value if current == value else None
        setattr(self, attr, value)

    def posix_mode(self) -> bool | None:
        """bash's POSIX mode: `set -o posix`, or POSIXLY_CORRECT while it is set."""
        value = self.vars.get("POSIXLY_CORRECT")
        if value is None or value == UNSET or self.posix is True:
            return self.posix
        return None if CHOICE.search(value) or UNKNOWN in value else True

    def emulate(self, args: list[str]) -> None:
        """zsh's `emulate [-lLR] [MODE [FLAGS] [-c CODE]]`. The mode sets the options it is known to
        set, and FLAGS (`-o NAME`, `+o NAME`, `-L`) set theirs. With -c, CODE runs in the current
        shell under that emulation, after which only the options are restored: its directory
        changes, variables and functions outlast it, and the functions it defines keep the emulation
        (zsh's sticky emulation: they run with its options, which are restored when they return).
        An error that aborts (see `abort`) ends the code, which fails, as in eval. zsh rejects an option before the mode other than -l, -L and -R, -c without a mode or code,
        -l or -L before the mode with -c, an argument after the code, and an option name it lacks
        (`-o NAME`, `+o NAME`); nothing then changes or runs."""
        k = 0
        while k < len(args) and re.fullmatch(r"-[lLR]+", args[k]):
            k += 1
        pre = "".join(a[1:] for a in args[:k])
        mode, flags, code = (args[k] if k < len(args) else None), args[k + 1:], None
        if mode is not None and mode.startswith(("-", "+")):
            self.set_status(FAILED)  # `emulate -c CODE`, `emulate -o NAME sh`: bad option
            return
        if "-c" in flags:
            c = flags.index("-c")
            if c + 2 != len(flags) or set(pre) & {"l", "L"}:
                self.set_status(FAILED)
                return
            code, flags = flags[c + 1], flags[:c]
        if mode is None or "l" in pre:
            self.set_status(OK)  # prints the emulation or its options, and changes nothing
            return
        names = [flags[j + 1] if j + 1 < len(flags) else None for j, f in enumerate(flags) if f in {"-o", "+o"}]
        if not all(n is not None and _zsh_option(n) for n in names):
            self.complain()  # zsh: no such option, and nothing changes or runs
            self.set_status(FAILED)
            return
        before = self.options()
        if mode in {"sh", "ksh", "zsh"}:
            self.shwordsplit = mode != "zsh"
            self.ksharrays = mode != "zsh"
            self.shoptionletters = mode != "zsh"
            self.globsubst = mode != "zsh"
            self.nomatch = mode == "zsh"
            self.braceexpand = mode == "zsh"
            self.noglob = False
            self.bsdecho = mode == "sh"
            self.multios = mode == "zsh"
            self.posixbuiltins = mode != "zsh"
            self.posixidentifiers = self.typesettounset = mode != "zsh"
            self.shnullcmd = mode != "zsh"
            self.cshnullcmd = False
        else:
            self.notes.append("shell emulation the audit cannot model")
        if "L" in pre:
            self.localoptions = True
        j = 0
        while j < len(flags):
            f = flags[j]
            if f in {"-o", "+o"} and j + 1 < len(flags):
                self.option(flags[j + 1], f == "-o")
                j += 2
                continue
            if re.fullmatch(r"[-+]L+", f):
                self.localoptions = f[0] == "-"
            elif not re.fullmatch(r"[-+]R+", f):
                self.notes.append("an emulate option the audit cannot model")
            j += 1
        self.set_status(OK)
        if code is None:
            return
        sticky, self.sticky = self.sticky, self.options()
        try:
            self.evaluate(lambda: self.run(code))  # an error that aborts ends the code, as in eval
        finally:
            self.sticky = sticky
            self.restore_options(before)

    def shellopts(self) -> str:
        """The supported expansion options in bash's live, readonly SHELLOPTS variable."""
        options = {"noglob": self.noglob, "braceexpand": self.braceexpand, "allexport": self.allexport,
                   "posix": self.posix_mode(), "errexit": self.errexit, "nounset": self.nounset,
                   "xtrace": self.xtrace, "verbose": self.verbose}
        if any(v is None for v in options.values()):
            return UNKNOWN
        return ":".join(name for name, enabled in options.items() if enabled)

    def set_readings(self) -> list[str]:
        """How the shells that may run the code read `set`'s words (see SET_LETTERS): "posix" for
        bash, its sh and dash, "zsh" and, under SH_OPTION_LETTERS, "zshsh"."""
        kinds = self.kinds()
        out = ["posix"] if any(k != "zsh" for k in kinds) else []
        if "zsh" in kinds:
            out += {False: ["zsh"], True: ["zshsh"]}.get(self.shoptionletters, ["zsh", "zshsh"])
        return out

    def set_builtin(self, args: list[str], startup: bool = False) -> None:
        """`set`: `--` (or a first operand) sets the positional parameters; a letter turns an
        option on (`-`) or off (`+`), as each shell names them (see SET_LETTERS); each `o` takes
        the next word as an option's name, except that zsh takes the rest of the cluster where
        letters follow it, and bash lists the options where the next word starts with `-` or `+`;
        an `o` with no word after it lists the options. Where the shells read the words
        differently, the audit follows each reading. At a letter or option name it lacks, bash
        fails, before it changes anything or after what came before (see `_bash_set`; sh exits in
        the first case, except where `guarding` holds); dash exits there and zsh ends the eval or
        the shell (see `zsh_special`), each after the letters before it. `startup`: a new shell's own flags (`bash -ec`), where c,
        s, i and l are the shell's; one it lacks stops it before the code runs, which the audit
        follows anyway (measured on bash 3.2 and its sh, dash and zsh 5.9)."""
        readings = self.set_readings()
        words = {r: _set_words(args, r, startup) for r in readings}
        if len({w["effects"] for w in words.values()}) > 1:
            def follow(reading):
                def run():
                    if reading != "posix":
                        self.shoptionletters = reading == "zshsh"
                    self.as_dialect("posix" if reading == "posix" else "zsh", lambda: self.set_builtin(args, startup))
                return run

            self.either(*(follow(r) for r in readings))
            return
        w, start = words[readings[0]], self.state()
        for name, on in w["letters"]:
            if name:
                self.option(name, on)
            else:
                self.notes.append("a shell option the audit does not model")
        for name, on in w["names"]:
            self.option(name, on)
        if w["lists"]:
            self.output = None  # set lists the options
        if w["positional"] is not None:
            self.bind(w["positional"])
        self.set_status(OK)
        if startup:
            return
        named = [name for name, _ in w["names"]]
        posix, zsh = words.get("posix", {}), [words[r] for r in readings if r != "posix"]
        dash_letters = posix.get("dash_missing")
        bash_usage, bash_done = _bash_set(args) if posix else ([], None)
        bash_bad = bool(bash_usage) or bash_done is not None
        zsh_letters = any(z["missing"] for z in zsh)
        zsh_bad = zsh_letters or not all(map(_zsh_option, named))
        dash_bad = dash_letters or any(n not in DASH_OPTIONS for n in named)
        if not (zsh_bad or bash_bad or dash_bad):
            return
        if dash_letters and "dash" in self.kinds() and ("dash" in self.unspecial or self.caught):
            # dash keeps the letters before the one it lacks, which the audit does not tell apart.
            self.notes.append("a shell option the audit does not model")
        # A letter or option name the shell lacks (see `_bash_set`): bash fails, and sh exits at a
        # letter its first check meets; dash exits, also in an eval; zsh ends the eval or the shell
        # (see `zsh_special`). Measured on macOS's shells.
        posix_letter = "fail" if self.guarded else "exit"
        how = {"bash": "fail" if bash_bad else "allow",
               "posix": posix_letter if bash_usage else "fail" if bash_bad else "allow",
               "dash": "exit" if dash_bad else "allow", "zsh": self.zsh_special() if zsh_bad else "allow"}

        def go(write, failed):
            if failed and bash_bad:
                self.restore(start)  # bash changed nothing, or what came before where it stopped
                for is_name, name, on in bash_done or ():
                    if is_name or SET_LETTERS["bash"][name]:
                        self.option(name if is_name else SET_LETTERS["bash"][name], on)
                    else:
                        self.notes.append("a shell option the audit does not model")
            if failed:
                self.set_status(FAILED)

        self.error_ways(how, go)

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
        if text in self.substituted:
            return [self.substituted[text]]  # a `<(...)`
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

    def file_text(self, word: str) -> str | None:
        """A file's text, or a choice of the texts it may have, where the audit has them (see
        `scripts`); /dev/null's is empty, and a `<(...)`'s what its code printed."""
        text = _alt(self.expand(word))[0]
        if text == "/dev/null":
            return ""
        if text in self.substituted:
            return self.substituted[text]
        texts = self.scripts(word)
        return _either_output(list(texts)) if texts else None

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

    def run_script(self, word: str, content: str, verb: str | None, args: list[str],
                   startup: list[str] | tuple = (), stdin: str | None = None) -> None:
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
                self.output = None  # what other code prints is not followed
                self.scan_code(content)
                if stdin is not None:
                    self.interpreter_input(prog, content, stdin)
                return
            verb = prog
        if self.calls >= 4 or self.inlined >= 256:
            self.output = None
            return
        self.calls += 1
        self.inlined += 1
        try:
            with self.process(verb or "sh"):
                self.set_builtin(startup, startup=True)
                self.bind(args, zero=word)
                self.output = ""
                self.run(content, stdin)
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
        contents = [None] if content is None else _choices(content)
        if None in contents:
            self.files[p] = (None,)
        elif append:
            # Appended to a text the audit does not have: what is on disk at audit time.
            self.files[p] = tuple(dict.fromkeys(None if a is None else a + c
                                                for a in self.files.get(p, (None,)) for c in contents))
        else:
            self.files[p] = tuple(dict.fromkeys(contents))

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

    def interpreter_input(self, verb: str, code: str, stdin: str | None) -> None:
        """Treat stdin as data, following proven filename uses and flagging opaque programs.

        Python's small straight-line evaluator consumes known input in order. A conditional,
        indirect call or unsupported operation only establishes a possible read, never a violation.
        """
        if verb == "jq":
            return  # jq opens fixed option/program paths; input/inputs only consume JSON values.
        if verb in {"sed", "gsed"}:
            # r/w filenames are operands in the program (scan_code handles them). GNU e can
            # instead execute a command from the pattern space, including substitution results.
            if not code:
                self.notes.append("sed program is unavailable; its input may supply commands")
            elif re.search(r"(?:^|[;\n}])\s*(?:[\d,$/\\ .-]+)?e\b|"
                           r"s(?P<sep>[^A-Za-z0-9\\\s]).*?(?P=sep).*?(?P=sep)[A-Za-z0-9]*e", code):
                self.notes.append("sed may execute commands taken from standard input")
            return
        if not re.fullmatch(r"python\d*(?:\.\d+)?", verb):
            if stdin is not None and not ("/" in stdin or FILE_URL.search(stdin)):
                return
            # These interpreters have no general data-flow evaluator. Only simple print/filter
            # programs have a known absence of filename operations; opaque calls remain suspect.
            calls = re.findall(r"([\w.]+)\s*\(", code)
            safe = {"print", "printf", "puts", "p", "gets", "chomp", "chop", "split", "join",
                    "console.log", "JSON.parse", "JSON.stringify", "readline", "readLines",
                    "cat", "scan", "str", "as.character"}
            if not code or any(call not in safe for call in calls) or re.search(
                    r"\b(?:open|sysopen|require|load|eval|exec|system|include|include_once)\b", code):
                self.notes.append(f"{verb} may use standard input as filenames or executable code")
            return
        if not code:
            self.notes.append("Python program is unavailable; its input may supply filenames")
            return
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            self.notes.append("Python standard input may supply filenames to code the audit cannot parse")
            return
        values: dict[str, tuple[object, bool]] = {}
        remaining = stdin
        flow_uncertain = False
        safe_modules = {"sys", "json", "csv", "re", "math", "statistics", "collections", "itertools",
                        "functools", "string", "base64", "html", "unicodedata"}
        safe_calls = {"print", "len", "str", "repr", "int", "float", "bool", "list", "tuple", "dict",
                      "set", "sorted", "enumerate", "zip", "range", "min", "max", "sum", "abs", "round"}
        safe_methods = {"strip", "lstrip", "rstrip", "split", "splitlines", "join", "replace", "format",
                        "lower", "upper", "casefold", "startswith", "endswith", "encode", "decode",
                        "read", "readline", "readlines", "write", "writelines", "flush", "close"}

        def dotted(n):
            if isinstance(n, ast.Name):
                return n.id
            if isinstance(n, ast.Attribute):
                return dotted(n.value) + "." + n.attr
            return ""

        def possible():
            self.notes.append("Python may use standard input as filenames or executable code")

        def evaluate(n, certain=True):
            nonlocal remaining, flow_uncertain
            if n is None:
                return None, False
            if isinstance(n, ast.Constant):
                return n.value, False
            if isinstance(n, ast.Name):
                return values.get(n.id, (None, False))
            if isinstance(n, (ast.BoolOp, ast.IfExp, ast.Lambda, ast.ListComp, ast.SetComp,
                              ast.DictComp, ast.GeneratorExp)):
                # Short circuiting and deferred bodies are not straight-line evaluation.
                for c in ast.iter_child_nodes(n):
                    evaluate(c, False)
                return None, True
            if isinstance(n, ast.Call):
                f = dotted(n.func)
                certain = certain and not flow_uncertain
                if f.split(".")[0] in values and f.split(".")[0] in imported_aliases:
                    possible()
                    flow_uncertain = True
                    remaining = None
                    certain = False
                    f = "<import alias>"
                if f in {"exit", "quit", "sys.exit"}:
                    flow_uncertain = True
                    return None, False
                if f in values:
                    f = "<shadowed>"
                if f in {"input", "builtins.input", "sys.stdin.read", "sys.stdin.readline"}:
                    for a in n.args:
                        evaluate(a, certain)
                    if not certain or remaining is None:
                        remaining = None
                        return None, True
                    if f in {"input", "builtins.input", "sys.stdin.readline"}:
                        if n.args and f == "sys.stdin.readline":
                            remaining = None
                            return None, True
                        if not remaining and f in {"input", "builtins.input"}:
                            flow_uncertain = True
                            return None, True
                        line, sep, rest = remaining.partition("\n")
                        remaining = rest if sep else ""
                        return line + (sep if f == "sys.stdin.readline" else ""), True
                    if n.args or n.keywords:
                        remaining = None
                        return None, True
                    result, remaining = remaining, ""
                    return result, True
                receiver = evaluate(n.func.value, certain) if isinstance(n.func, ast.Attribute) else (None, False)
                args = [evaluate(a, certain) for a in n.args]
                keywords = {k.arg: evaluate(k.value, certain) for k in n.keywords}
                arg = None
                if f in {"open", "builtins.open", "io.open", "os.open"}:
                    arg = args[0] if args else keywords.get("file", keywords.get("path"))
                elif isinstance(n.func, ast.Attribute) and n.func.attr in {
                        "open", "read_text", "read_bytes", "write_text", "write_bytes"}:
                    arg = receiver
                if arg is not None:
                    v, taint = arg
                    if certain and isinstance(v, str):
                        self.add(v, bare=True)
                    else:
                        possible()
                    return None, taint
                if f in {"Path", "pathlib.Path"} and len(args) == 1:
                    return args[0]
                if isinstance(n.func, ast.Attribute) and isinstance(receiver[0], str) and n.func.attr in {
                        "strip", "lstrip", "rstrip", "lower", "upper", "casefold", "replace"}:
                    if all(v is not None for v, _ in args) and not keywords:
                        try:
                            return getattr(receiver[0], n.func.attr)(*(v for v, _ in args)), receiver[1]
                        except (TypeError, ValueError):
                            pass
                stream = (isinstance(n.func, ast.Attribute) and
                          (dotted(n.func.value) in {"sys.stdin", "sys.stdout", "sys.stderr"} or
                           isinstance(n.func.value, ast.Call) and dotted(n.func.value.func) in {
                               "open", "builtins.open", "io.open", "os.open"}))
                trusted = (f in safe_calls or f.split(".")[0] in safe_modules or
                           isinstance(n.func, ast.Attribute) and n.func.attr in safe_methods and
                           (isinstance(receiver[0], str) or stream))
                if not trusted:
                    possible()
                    flow_uncertain = True
                if f.startswith("sys.stdin.") or any(dotted(a) == "sys.stdin" for a in n.args):
                    remaining = None
                return None, receiver[1] or any(t for _, t in args) or any(t for _, t in keywords.values())
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                a, at = evaluate(n.left, certain)
                b, bt = evaluate(n.right, certain)
                return (a + b if isinstance(a, str) and isinstance(b, str) else None), at or bt
            children = [evaluate(c, certain) for c in ast.iter_child_nodes(n)]
            return None, any(t for _, t in children)

        def statements(body, certain=True):
            nonlocal flow_uncertain
            for stmt in body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    # An import can replace a builtin or a trusted module name. Resolve
                    # unfamiliar aliases conservatively before proving any later filename.
                    for alias in stmt.names:
                        bound = alias.asname or alias.name.split(".")[0]
                        if alias.asname and alias.asname != alias.name or bound in safe_calls:
                            values[bound] = (None, False)
                            imported_aliases.add(bound)
                    continue
                if isinstance(stmt, ast.Assign):
                    result = evaluate(stmt.value, certain)
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            values[target.id] = result if certain else (None, result[1])
                elif isinstance(stmt, ast.Expr):
                    evaluate(stmt.value, certain)
                else:
                    flow_uncertain = True
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        values[stmt.name] = (None, False)
                    # Unsupported control flow invalidates values it might assign. Calls under
                    # it are possibilities, including a filename taken directly from input().
                    for child in ast.iter_child_nodes(stmt):
                        evaluate(child, False)
                    for child in ast.walk(stmt):
                        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                            values[child.id] = (None, True)
        imported_aliases: set[str] = set()
        statements(tree.body)

    def awk_code(self, code: str, data: dict[str, str], stdin: str | None, stdin_main: bool | None = True,
                 records_unknown: bool = False) -> None:
        """Trace awk values to file/command operands; merely printing a -v value is data.

        Exact straight-line values prove an operation. Branches, unknown expressions and indirect
        functions remain suspect. Literal system commands are parsed as shell commands separately.
        Actions are followed in the order awk runs them: BEGIN blocks, then the record actions, then
        END blocks. `stdin_main` says whether standard input is the main input (True), file operands
        are (False), or both may be (None). A plain or `getline var` in a straight-line BEGIN block
        reads the next known record, and the record actions get the records left: none means they
        never run, and neither do they after a certain `exit` in BEGIN. They run once per record, so
        with more than one record a name they or a pattern assign may hold, anywhere in them and in
        END, what an earlier record left: such names start the record actions unknown. The records
        are unknown where the input has unknown parts, the program mentions RS, ARGV or ARGC, an
        operand assigns RS (`records_unknown`), or a getline reads a file that may be standard input
        (`-`, `/dev/stdin`, a name the audit cannot work out): record actions then may or may not run.
        """
        if not code:
            self.notes.append("awk program is unavailable; its data may supply filenames")
            return
        tokens = _awk_tokens(code)
        # awk decodes escapes in -v values. Until that syntax is evaluated, an escaped value
        # reaching a file operation is a possibility, not a literal filename to prove or dismiss.
        known: dict[str, str | None] = {name: None if "\\" in value else value for name, value in data.items()}

        def expression(start, stops):
            out, depth = [], 0
            for t in tokens[start:]:
                if depth == 0 and t in stops:
                    break
                if t in {"(", "["}:
                    depth += 1
                elif t in {")", "]"}:
                    if depth == 0:
                        break
                    depth -= 1
                out.append(t)
            return out

        def text(expr):
            if expr == ["$", "0"] and line is not None:
                return line
            parts = []
            for t in expr:
                if t.startswith('"'):
                    try:
                        parts.append(json.loads(t))
                    except ValueError:
                        return None
                elif t in known and known[t] is not None:
                    parts.append(known[t])
                elif t in {"(", ")"}:
                    continue
                else:
                    return None
            return "".join(parts) if parts else None

        uncertain = any(t in {"if", "function", "?", "&&", "||", "exit", "next", "nextfile", "return", "for", "do"}
                        for t in tokens)
        while_conditions = []
        for i, t in enumerate(tokens[:-1]):
            if t == "while" and tokens[i + 1] == "(":
                depth, end = 1, i + 2
                while end < len(tokens) and depth:
                    depth += (tokens[end] == "(") - (tokens[end] == ")")
                    end += 1
                while_conditions.append((i + 2, end - 1))
        # A loop nested in another loop may never reach its condition. Until the full
        # control structure is evaluated, only a single loop's first test can be certain.
        uncertain = uncertain or len(while_conditions) > 1
        # Each top-level action has its own guard. A BEGIN block does not make an unrelated
        # record action run, and a pattern may reject every record. Keep assignments in such
        # actions unknown rather than letting them prove a later filename. `kind` gives each
        # token's action: "BEGIN", "END", "record" (no pattern) or "pattern"; None outside actions.
        kind = _awk_actions(tokens)
        order = ([i for i in kind if kind[i] == "BEGIN"] + [i for i in kind if kind[i] not in {"BEGIN", "END"}]
                 + [i for i in kind if kind[i] == "END"])
        # The main input's records not yet read, while known; `records` is what the record actions
        # get once BEGIN has run, and `line` is $0 in them while it is known (a single record).
        main = stdin.splitlines() if stdin is not None and stdin_main is True else None
        if main is not None and (UNKNOWN in stdin or CHOICE.search(stdin)):
            main = None  # parts of the input are unknown, and with them where its lines end
        if records_unknown or "RS" in tokens or "RS" in data or "ARGV" in tokens or "ARGC" in tokens:
            # A changed record separator splits the input elsewhere; a changed ARGV may read another.
            main = None
        records: list[str] | None = None
        line: str | None = None
        exits = _awk_begin_exits(tokens, kind)

        def status(index) -> tuple[bool, bool]:
            """Whether the action holding a token certainly runs, and whether it is a record action."""
            k = kind.get(index)
            if k in {"BEGIN", "END"}:
                return True, False
            if k == "record":
                return bool(records), True
            return False, False

        def consume(expr, index, command=False, close=False, inherit_input=True, command_input=None):
            nonlocal stdin, line, main
            v = text(expr)
            guaranteed_action, record = status(index)
            if "$" in expr and not record:
                v = None
            certain = (guaranteed_action and not uncertain and not close and
                       (not while_conditions or any(a <= index < b for a, b in while_conditions)))
            if v is not None and certain:
                if command:
                    data_input = stdin if inherit_input else command_input
                    if data_input is None and re.search(r"\b(?:xargs|read|eval|source)\b", v):
                        self.notes.append("an awk shell command may use unresolved input as filenames or code")
                    with self.process("sh"):
                        self.run(v, data_input)
                    if inherit_input:
                        # A system/pipe-read command shares awk's input descriptor and may
                        # consume it. Later record values cannot reuse the original input.
                        stdin = line = None
                        if stdin_main is not False:
                            main = None
                else:
                    self.add(v, bare=True)
            elif expr:
                self.notes.append("awk may use a data value as a filename or shell command")

        builtins = {"atan2", "cos", "sin", "exp", "log", "sqrt", "int", "rand", "srand", "gsub", "sub",
                    "index", "length", "match", "split", "sprintf", "substr", "tolower", "toupper",
                    "systime", "strftime", "mktime", "fflush", "system", "close"}
        # The names the record actions and patterns may assign, as the walk below assigns them;
        # None when they call a function, which may assign any.
        carried: set[str] | None = set()
        for i, t in enumerate(tokens[:-1]):
            if kind.get(i) in {"BEGIN", "END"} or carried is None:
                continue
            if re.fullmatch(r"[A-Za-z_]\w*", t) and (
                    tokens[i + 1] in {"=", "++", "--", "+=", "-=", "*=", "/=", "%=", "^="} or
                    tokens[max(0, i - 1):i] in [["++"], ["--"]]):
                carried.add(t)
            elif t == "getline":
                expr = expression(i + 1, {";", "}"})
                if expr and re.fullmatch(r"[A-Za-z_]\w*", expr[0]):
                    carried.add(expr[0])
            elif t in {"sub", "gsub", "split", "match"} and tokens[i + 1] == "(":
                carried.update(expression(i + 2, {")"}))
            elif re.fullmatch(r"[A-Za-z_]\w*", t) and tokens[i + 1] == "(" and t not in builtins | {"if", "while", "for", "print", "printf"}:
                carried = None
        begun = False
        for i in order:
            t = tokens[i]
            if not begun and kind[i] != "BEGIN":
                # After a certain `exit` in BEGIN no record action runs; END still does.
                begun, records = True, [] if exits else main
                line = records[0] if records is not None and len(records) == 1 else None
                if records is None or len(records) > 1:
                    # On a later record they read what an earlier one assigned.
                    known.update({name: None for name in known if carried is None or name in carried})
            if kind[i] in {"record", "pattern"} and records == []:
                continue  # no record is left for this action, so it never runs
            if re.fullmatch(r"[A-Za-z_]\w*", t) and tokens[i + 1:i + 2] == ["="]:
                certain_action, _ = status(i)
                known[t] = text(expression(i + 2, {";", "}", ","})) if not uncertain and certain_action else None
            elif re.fullmatch(r"[A-Za-z_]\w*", t) and (
                    tokens[i + 1:i + 2] in [[op] for op in {"++", "--", "+=", "-=", "*=", "/=", "%=", "^="}] or
                    tokens[max(0, i - 1):i] in [["++"], ["--"]]):
                known[t] = None
            if t == "$" and tokens[i + 2:i + 3] == ["="]:
                stdin = line = None
            if t in {"sub", "gsub", "split", "match"} and tokens[i + 1:i + 2] == ["("]:
                # These builtins mutate an argument (or $0). Until those transforms are
                # evaluated, a preceding -v value cannot prove the later filename.
                expr = expression(i + 2, {")"})
                for name in expr:
                    if name in known:
                        known[name] = None
                stdin = line = None
            if t in {"system", "close"} and tokens[i + 1:i + 2] == ["("]:
                consume(expression(i + 2, {",", ")"}), i, command=t == "system", close=t == "close")
            elif t == "getline":
                expr = expression(i + 1, {";", "}"})
                value = None  # the text read, if known
                if "<" in expr:
                    target = expr[expr.index("<") + 1:]
                    if stdin_main is not False and (text(target) is None or text(target) in AWK_STDIN):
                        # Standard input under another name, or a name the audit cannot work out, may
                        # read the main input, and how much of it awk then buffers is unknown.
                        main = None
                        stdin = line = None
                    consume(target, i)
                elif tokens[i - 1:i] not in (["|"], ["|&"]):
                    # The main input's next record. Only a getline that runs exactly once before any
                    # record is read, in a straight-line BEGIN block, knows which.
                    if kind[i] == "BEGIN" and not uncertain and not while_conditions and main is not None:
                        # At the end of the input macOS's awk empties the variable; it stays unknown.
                        value = main.pop(0) if main else None
                    else:
                        main = None
                    if stdin_main is not False:
                        stdin = None
                if expr and re.fullmatch(r"[A-Za-z_]\w*", expr[0]):
                    known[expr[0]] = value
                else:
                    stdin = line = None
            elif t in {"print", "printf"}:
                expr = expression(i + 1, {";", "}"})
                depth = 0
                for k, op in enumerate(expr):
                    if op in {"(", "["}:
                        depth += 1
                    elif op in {")", "]"}:
                        depth -= 1
                    elif depth == 0 and op in {">", ">>", "|", "|&"}:
                        printed = text(expr[:k]) if t == "print" else None
                        consume(expr[k + 1:], i, command=op in {"|", "|&"}, inherit_input=False,
                                command_input=printed + "\n" if printed is not None else None)
                        break
            elif t in {"|", "|&"} and "getline" in tokens[i + 1:i + 3]:
                start = i - 1
                while start >= 0 and tokens[start] not in {";", "{", "}"}:
                    start -= 1
                consume(tokens[start + 1:i], i, command=True)
            elif t == "ARGV":
                end = i + 1
                while end < len(tokens) and tokens[end] not in {"=", ";", "}"}:
                    end += 1
                if tokens[end:end + 1] == ["="]:
                    # Changing ARGV does not itself open a file (ARGC, exit and later actions
                    # decide whether it is consumed), so retain this as a possibility.
                    consume(expression(end + 1, {";", "}"}), i, close=True)
            elif re.fullmatch(r"[A-Za-z_]\w*", t) and tokens[i + 1:i + 2] == ["("] and t not in builtins | {"if", "while", "for", "print", "printf"}:
                self.notes.append("awk calls a function whose filename effects the audit cannot resolve")
                known = {name: None for name in known}
                stdin = line = None

    def code_args(self, verb: str, syntax: dict, args: list[str], code: list[str], scripts: list[str]) -> tuple[set[int], bool, dict[str, str]]:
        """Read an interpreter's arguments: append its code to `code` and the files it runs as code (a
        script, `awk -f`) to `scripts`, record files it reads, and return the indices handled here
        (code, and option values that are neither code nor paths). See CODE_SYNTAX for clusters and
        attached values. awk's `-v name=value` values are data, unless its code reads files or runs
        commands using that value; jq's operands after `--args` or `--jsonargs` are values. Also
        return whether stdin supplies the program, and awk's -v assignments."""
        handled: set[int] = set()
        codes, values, files = syntax.get("code", ()), syntax.get("values", {}), syntax.get("files", {})
        attached = syntax.get("attached", ())
        next_only = syntax.get("next_only", False)
        given = module = False
        data: dict[str, str] = {}
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
                    name, _, value = vals[0].partition("=")
                    data[name] = value
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
        stdin_code = not syntax.get("first") and not given and not module and not operands
        if not syntax.get("first") and not given and not module and operands and verb not in {"osascript"}:
            if args[operands[0][0]] == "-":
                handled.add(operands[0][0])
                stdin_code = True
            else:
                scripts.append(args[operands[0][0]])  # the script file the interpreter runs
        for k, value in operands:
            if value:
                handled.add(k)  # jq --args: a string, not a file
        return handled, stdin_code, data

    def shell_command(self, verb: str, args: list[str], stdin: str | None) -> None:
        """sh, bash and the like: `-c CODE [NAME [ARGS]]`, `-s [ARGS]` or no script (code on standard
        input), or a script file (run when the audit has its text; see `script`). The arguments are
        positional parameters, and paths too. The code runs in a new shell process (see `process`),
        as that shell runs code (see DIALECTS)."""
        j, flags, startup = 0, "", []
        while j < len(args) and args[j].startswith(("-", "+")) and args[j] not in {"-", "--"}:
            if args[j] in {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}:
                if args[j] in {"-o", "+o"}:
                    startup += args[j:j + 2]
                j += 2
                continue
            if not args[j].startswith("--"):
                flags += args[j][1:]
                startup.append(args[j])
            j += 1
        if j < len(args) and args[j] in {"-", "--"}:
            j += 1
        operands = args[j:]
        if "c" in flags and operands:
            code, rest = operands[0], operands[1:]
            for a in rest:
                self.add(a, bare=False)
            with self.process(verb):
                self.set_builtin(startup, startup=True)
                self.bind(rest[1:], zero=rest[0] if rest else None)
                self.output = ""
                self.run(code, stdin)
            return
        if "s" in flags or not operands:
            for a in operands:
                self.add(a, bare=False)
            if stdin is None or UNKNOWN in stdin:
                self.notes.append("a program reads code from input the audit does not know")
            if stdin:
                with self.process(verb):
                    self.set_builtin(startup, startup=True)
                    self.bind(operands)
                    self.output = ""
                    self.run(stdin)  # shell code on standard input
            return
        self.add(operands[0], bare=True)  # a script file
        for a in operands[1:]:
            self.add(a, bare=False)
        self.with_script(operands[0], lambda text: self.run_script(operands[0], text, verb, operands[1:], startup, stdin))

    def prefixed(self, verb: str, args: list[str], stdin: str | None) -> None:
        """`command` and `builtin` before a command, as measured on macOS bash 3.2, sh, dash and zsh
        5.9. Both skip functions (and the alias table, which their word is outside of). bash's run
        the builtin (`builtin`: only a builtin, else they fail) without a POSIX special builtin's
        power to end the shell at an error; an error in code it runs (an eval's, a sourced file's)
        still does. dash has no `builtin`; its `command` turns an error that would end the shell,
        in the code it runs too, into the command's failure (as `abort` does to an eval). zsh's
        `builtin` runs the builtin as usual. zsh's `command` runs a builtin only with
        POSIX_BUILTINS (as `emulate sh` sets it), and then one an error leaves failed; otherwise it
        runs a file: a builtin that macOS has none of (readonly, export, eval, set) is not found,
        and one it has (cd, read, umask: /usr/bin scripts that run it in a new sh; /bin/echo, whose
        escapes differ) runs in a child process and changes nothing here. `builtin -` follows the
        command after `-` with ordinary function, builtin and file lookup. `-v` and `-V` describe
        the command without running it."""
        j = 0
        while j < len(args) and args[j].startswith("-") and len(args[j]) > 1:
            j += 1
            if args[j - 1] == "--":
                break
        opts, rest = args[:j], args[j:]
        if verb == "builtin" and rest[:1] == ["-"] and "zsh" in self.kinds():
            if self.kinds() != ["zsh"]:
                self.either(lambda: self.as_dialect("zsh", lambda: self.command(rest[1:], stdin)),
                            lambda: self.as_dialect("posix", lambda: self.prefixed(verb, args, stdin)))
                return
            self.command(rest[1:], stdin)
            return
        if not rest or verb == "command" and any(set(o[1:]) & {"v", "V"} for o in opts if o != "--"):
            if verb == "builtin" and any(k == "dash" for k in self.kinds()):
                self.complain()
            self.output = "" if not rest else None
            self.set_status(OK if not rest else MAYBE)
            return
        name = rest[0]
        self.output = ""  # what the command prints, from here

        def bare(run=None):
            # The command with no function or alias of its name.
            saved = {kind: getattr(self, kind).pop(name, None) for kind in ("functions", "aliases")}
            try:
                (run or (lambda: self.command(rest, stdin)))()
            finally:
                for kind, alts in saved.items():
                    if alts is not None and name not in getattr(self, kind):
                        getattr(self, kind)[name] = alts

        def missing():
            self.complain()
            self.output = ""
            self.set_status(FAILED)

        def unspecial(kinds):
            def run():
                saved, self.unspecial = self.unspecial, frozenset(kinds)
                try:
                    bare()
                finally:
                    self.unspecial = saved
            return run

        def caught():
            saved, self.caught = self.caught, True
            try:
                self.evaluate(bare)
            finally:
                self.caught = saved

        def child():
            with self.child():
                bare()
                out = self.output
            if name == "echo":
                # macOS's /bin/echo: `-n` first, and no escapes but `\c`, where output stops.
                words = rest[1:]
                nl = words[:1] != ["-n"]
                text = " ".join(words if nl else words[1:])
                out = None if "\\" in text or out is None else text + ("\n" if nl else "")
            elif name not in {"printf", "true", "false", "test", "[", "cd", "read", "getopts", "umask"}:
                out = None
            self.output = out

        ways: dict[str, object] = {}
        for kind in self.kinds():
            if verb == "builtin":
                if kind == "dash":
                    ways["missing"] = missing
                elif name not in (ZSH_BUILTINS if kind == "zsh" else BASH_BUILTINS):
                    ways["missing"] = missing
                else:
                    key = "builtin" if kind == "zsh" else "unspecial-bash"
                    ways[key] = bare if kind == "zsh" else unspecial({"bash", "posix"})
            elif kind == "dash":
                ways["caught"] = caught
            elif kind != "zsh":
                ways["unspecial-bash"] = unspecial({"bash", "posix"})
            else:
                if self.posixbuiltins is not False:
                    ways["unspecial-zsh"] = unspecial({"zsh"})
                if self.posixbuiltins is not True:
                    if name not in ZSH_BUILTINS:
                        ways["file"] = bare
                    elif name in BUILTIN_FILES:
                        ways["child"] = child
                    else:
                        ways["missing"] = missing
        runs = list(ways.values())
        runs[0]() if len(runs) == 1 else self.either(*runs)

    def wrapper(self, verb: str, args: list[str], stdin: str | None) -> None:
        """A command that runs another: skip its own options (with their values, attached or not) to
        the command. `env -C dir`, `env -S string`, `env -i`, `env -u NAME`, `sudo -D dir` and env's
        NAME=VALUE are followed."""
        if verb in {"command", "builtin"}:
            self.prefixed(verb, args, stdin)
            return
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
        if verb in {"xargs", "parallel"} and (stdin is None or UNKNOWN in stdin) and not (
                verb == "parallel" and any(a in {":::", "::::"} for a in args)):
            self.notes.append("a command takes names from input the audit does not know")
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
                    self.output = ""
                    self.command(rest, stdin)
            return
        if rest:
            self.output = ""
            self.command(rest, None if verb == "xargs" else stdin)
            if verb in {"xargs", "parallel", "watch"}:
                self.output = None  # the command runs on other arguments, or again and again
            if verb == "exec":
                self.may_end()  # the command replaces the shell, which ends with it


def _shell(command: str, workdir: Path, files: dict | None = None, place: dict | None = None) -> _Shell:
    """Read the command twice: the first pass, taking every cd as one that may have failed, finds
    the directories the command makes wherever it may be (see `_Shell.later`). `files`: what earlier
    calls wrote, by path (see `_Shell.files`), updated with what this command writes. `place`: where
    the command may start, as `_next_place` left it for the call before ({} for the work directory),
    updated with where the next call may start."""
    files = {} if files is None else files
    passes = []
    for doubt in (True, False):
        shell = _Shell(workdir)
        if place:
            shell.set_worlds(list(place["worlds"]))
            shell.known = place["known"]
        if doubt:
            shell.doubt = True
        else:
            shell.later = passes[0].made_ever
            shell.wrote_later = passes[0].wrote_ever
        shell.files = dict(files)
        shell.run(command)
        passes.append(shell)
    if place is not None:
        place.update(_next_place(shell, workdir, place, slow=_may_outlast(command)))
    shell.run_traps(0)
    shell.finish(0)
    shell.flush()  # bash's exit
    files.clear()
    files.update(shell.files)
    return shell


def _next_place(shell: _Shell, workdir: Path, place: dict, slow: bool = True) -> dict:
    """Where the next Claude Code Bash call may start, once `shell` has run (before its EXIT trap,
    which the shell runs after Claude Code has read where it is, and before `finish`). Claude Code
    2.1.308 runs a call as `eval CMD && pwd -P >| FILE` and starts the next where FILE says, so where
    this one ended only if it ran to its end with status 0; after an exit, a failing status, or a
    call moved to the background at its timeout, the next starts where this one started (measured
    on 2.1.284 and 2.1.308). So a place where the shell ended with status 0 for certain
    (a builtin's, as `cd sub; echo` ends) is the only one only if the call cannot outlast its
    timeout (`slow`, see `_may_outlast`); where it may have failed or run on, the start is one too.
    A `pwd` the call made a function or an alias prints what it likes, so the next start is then
    unknown. Claude Code moves a shell that ends outside the directories it allows back to where
    the session started, the work directory here; the audit does not know which other directories
    it allows, so a place outside the work directory keeps both."""
    began = place.get("worlds") or [_World(workdir, None)]
    worlds = [w for w in shell.worlds if w.status != FAILED]
    if (slow or shell.exits or not worlds or len(worlds) < len(shell.worlds)
            or any(w.status != OK for w in worlds)):
        worlds += began
    if any(not _under(w.cwd, workdir) for w in worlds):
        worlds.append(_World(workdir, None))
    # A new shell: no $OLDPWD of the command's, no pushd stack.
    worlds = list({(w.cwd, w.primary): _World(w.cwd, None, (), MAYBE, w.primary) for w in worlds}.values())
    return {"worlds": worlds, "known": shell.known and "pwd" not in shell.functions and "pwd" not in shell.aliases}


# Builtins that return at once whatever their arguments: a call of only these, with no loop, no
# function and no redirection other than to /dev/null or a descriptor, cannot outlast its timeout.
QUICK_BUILTINS = {"cd", "chdir", "pushd", "popd", "dirs", "pwd", "true", "false", ":", "echo", "printf", "print",
                  "export", "unset", "set", "setopt", "unsetopt", "shopt", "shift", "local", "declare", "typeset",
                  "readonly", "test", "[", "let", "umask", "return", "exit"}


def _may_outlast(command: str) -> bool:
    """Whether a Bash call may run longer than Claude Code's timeout (which moves it to the
    background, so that the next call starts where this one started): anything but a call
    whose every command, in any branch and any substitution, is a literal QUICK_BUILTINS name, with
    no loop, no function or alias defined, and no redirection that opens a file other than
    /dev/null (opening a FIFO waits for its other end)."""
    root = _BASH.parse(command.encode()).root_node
    if root.has_error:
        return True
    for node in _walk(root):
        if node.type in {"while_statement", "for_statement", "c_style_for_statement", "function_definition"}:
            return True
        if node.type == "command":
            name = node.child_by_field_name("name")
            if (name is None or len(name.named_children) != 1 or name.named_children[0].type != "word"
                    or _text(name) not in QUICK_BUILTINS):
                return True
        if node.type == "file_redirect":
            op = "".join(_text(c) for c in node.children if not c.is_named)
            dest = node.child_by_field_name("destination")
            target = _text(dest) if dest is not None else ""
            if not (target == "/dev/null" or op.endswith("&") and (target.isdigit() or target == "-")):
                return True
    return False


def _unwritable(value) -> bool:
    """Whether a tool input holds text no file name or argument can hold: a NUL, or a lone surrogate
    (a JSON escape a transcript may hold that no encoding writes)."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return True
        return "\x00" in value
    if isinstance(value, dict):
        return any(_unwritable(k) or _unwritable(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_unwritable(v) for v in value)
    return False


def _strings(value):
    """Every string in a JSON value, its keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


# What ends a URL's host for the WHATWG parser in an http(s) URL, and the code points it rejects in
# a host (a space, `<`, `^`, a control...): a reading with one names no host, since the parser fails.
HOST_END = re.compile(r"[/\\?#]")
HOST_FAILS = re.compile(r"[\x00-\x20<>\[\]^|\x7f]")
C0_OR_SPACE = "".join(map(chr, range(0x21)))


def _web_hosts(text: str):
    """The hosts the WHATWG URL parser, which Node's fetch uses, reads in the http(s) URLs a text may
    hold: from each `http:` or `https:` (in any case, after any character) to the end of the text,
    and to the first space or quote, each with its tabs and newlines removed as the parser removes
    them. The parser skips any slashes and backslashes after the scheme, ends the host at a slash,
    backslash, `?` or `#`, takes it after the last `@` (`http://example.org @127.0.0.1/` is
    127.0.0.1's) and before a port. An IPv6 host (`[::1]`) is yielded whole."""
    for m in re.finditer(r"(?i)https?:", text):
        rest = text[m.end():]
        # The parser strips spaces and controls at the ends of what it reads.
        for reading in (rest.rstrip(C0_OR_SPACE), re.split(r"[\s'\"<>)`]", rest, maxsplit=1)[0]):
            reading = re.sub(r"[\t\n\r]", "", reading).lstrip("/\\")
            host = HOST_END.split(reading, maxsplit=1)[0].rpartition("@")[2]
            if host.startswith("[") and "]" in host:
                host = host[: host.index("]") + 1]
            else:
                host = host.split(":", 1)[0]
                if not host or HOST_FAILS.search(host):
                    continue
            yield host


def _scrubbed(value):
    """A tool input with each NUL and lone surrogate replaced by U+FFFD, which every path and
    argument can hold."""
    if isinstance(value, str):
        return re.sub(r"[\x00\ud800-\udfff]", "�", value)
    if isinstance(value, dict):
        return {_scrubbed(k): _scrubbed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrubbed(v) for v in value]
    return value


def _shell_command(inp) -> str | None:
    """A shell call's command as text: a string, or a list of strings taken as one command's argument
    vector (joined with shlex.join, which a shell splits back into the same words); None for anything
    else (a missing or null command, or another type), which the audit cannot read."""
    command = inp.get("command") if isinstance(inp, dict) else None
    if isinstance(command, str):
        return command
    if isinstance(command, list) and command and all(isinstance(w, str) for w in command):
        return shlex.join(command)
    return None


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
            yield part.get("name", "?"), part.get("input", {})
    item = line.get("item")
    event = line.get("type")
    if item is None or event == "item.started" or event == "item.updated":
        return  # Codex repeats an item as started, updated and completed; `audit_transcript` counts it once.
    if not isinstance(item, dict) or not (event is None or event == "item.completed"):
        yield "codex_item", item  # an item the audit cannot read, or in an event it does not know
        return
    kind = item.get("type")
    if not isinstance(kind, str):
        yield "codex_item", item
    elif kind == "command_execution":
        yield "shell", {"command": item.get("command")}
    elif kind in {"file_read", "file_change"}:
        # What the item names; not its status, which changes from start to completion.
        yield kind, {k: item[k] for k in ("path", "file_path", "changes") if k in item}
    elif kind == "mcp_tool_call":
        yield f"mcp:{item.get('server', '?')}/{item.get('tool', '?')}", item.get("arguments") or {}
    elif kind == "web_search":
        # The query, the page it opened (an open_page action has a URL and may have no query) and
        # the rest of the action (a search's queries), whose URLs are read as a fetch would read them.
        # A search starts with an action that names only its kind (`{"type": "other"}`); with no
        # colon it holds no URL, and kept it would stop the completed item from covering its start.
        action = item.get("action")
        if isinstance(action, dict) and set(action) <= {"type"} and ":" not in str(action.get("type", "")):
            action = None
        url = action.get("url") if isinstance(action, dict) else None
        yield "web_search", {"query": item.get("query", ""), **({"url": str(url)} if url else {}),
                             **({"action": action} if action not in (None, "", [], {}) else {})}
    elif kind == "collab_tool_call":
        yield "collab", item
    elif kind not in CODEX_NOT_CALLS:
        yield f"codex:{kind}", item


def check_call(tool: str, inp: dict, workdir: Path, roots: list[Path], files: dict | None = None,
               start=..., place: dict | None = None) -> tuple[str, str]:
    """('web' | 'violation' | 'suspect' | 'local' | 'other', reason) for one tool call: the shell
    model's verdict (`model_call`), except that a shell call it finds local or web is suspect unless
    it lies in the subset whose reads `exact.outside` knows exactly. `start`: where a shell call may
    start (see `exact.outside`); by default the work directory for Claude Code's Bash, and unknown
    for Codex's shell, which may run a command in a directory its transcript does not record.
    `place`: where the model takes a shell call to start (see `model_call`)."""
    verdict, why = model_call(tool, inp, workdir, roots, files, place)
    if tool in {"shell", "Bash"} and verdict in {"local", "web"}:
        if start is ...:
            start = [workdir] if tool == "Bash" else None
        beyond, _ = exact.outside(_shell_command(inp), workdir, start)
        if beyond:
            return "suspect", f"{EXACT_REASON}: {beyond}"
    return verdict, why


def model_call(tool: str, inp: dict, workdir: Path, roots: list[Path], files: dict | None = None,
               place: dict | None = None) -> tuple[str, str]:
    """The shell model's verdict on one tool call: ('web' | 'violation' | 'suspect' | 'local' |
    'other', reason). `files`: what earlier calls in the transcript wrote, by path, so that a script
    written by one call and run by a later one is read as it was written; updated with what this
    call writes. `place`: for a shell call, where it may start ({} or None: the work directory),
    updated with where the next may start (see `_next_place`). An input the audit cannot read (not
    an object, or a shell call without a command it can read) is suspect."""
    if not isinstance(tool, str):
        return "suspect", "a tool call without a name the audit can read"
    if _unwritable(inp):
        # Read as if each NUL and lone surrogate were another character, for what it reaches: such
        # a call is suspect, and excludes the run where it names a protected place or is an MCP
        # call. Where the next Bash call starts is either way (the call may not have run).
        before = dict(place) if place is not None else None
        verdict, why = model_call(tool, _scrubbed(inp), workdir, roots, files, place)
        if place is not None:
            place.update(worlds=list({(w.cwd, w.primary): w for w in [
                *(before.get("worlds") or [_World(workdir, None)]), *(place.get("worlds") or [_World(workdir, None)])]}.values()),
                known=before.get("known", True) and place.get("known", True))
        if verdict == "violation":
            return verdict, why
        return "suspect", "an input with text no file name can hold (a NUL, or a lone surrogate)"
    text = json.dumps(inp) if not isinstance(inp, str) else inp
    outside_urls = URL.sub("", text)
    if tool.startswith("mcp:") or tool.startswith("mcp__") or tool in MCP_TOOLS:
        return "violation", "MCP tool"
    if tool == "collab":
        return "suspect", "sub-agent call; its work is not in this transcript"
    if tool == "codex_item" or tool.startswith("codex:"):
        return "suspect", f"a Codex item the audit does not know ({tool})"
    if not isinstance(inp, dict):
        return "suspect", "a tool input the audit cannot read"
    if tool in WEB_TOOLS or tool == "web_search":
        if OWN_REPO.search(text):
            return "suspect", "opens this project's repository on the web"
        # The URL WebFetch fetches, or the page Codex's search opened, read exactly; a URL elsewhere
        # in the input (a query, a prompt) as the WHATWG parser would read it (`_web_hosts`).
        fetched = [inp.get("url")] if tool == "WebFetch" or "url" in inp else []
        local = next((why for u in fetched if (why := exact.web_url(u)) is not None), None)
        local = local or next((why for s in _strings(inp) for host in _web_hosts(s)
                               if (why := exact.remote_url(f"http://{host}/", globs=False)) is not None), None)
        if local:
            return "suspect", f"a web call that may reach this machine or its network: {local}"
        return "web", ""
    paths, searches, notes, weak, alt, alt_searches, unknown = [], [], [], [], [], [], []
    literal_paths: set[Path] = set()
    if tool in {"shell", "Bash"}:
        command = _shell_command(inp)
        if command is None:
            if place is not None:
                place.update(worlds=[_World(workdir, None)], known=False)
            return "suspect", "a shell call without a command the audit can read"
        shell = _shell(command, workdir, files, place)
        paths, searches, notes, weak = shell.paths, shell.searches, shell.notes, shell.code_paths
        # Paths and searches from where the shell would be had a cd to a missing directory failed.
        alt, alt_searches = shell.alt_paths, shell.alt_searches
        unknown = shell.unknown_paths
        literal_paths = shell.literal_paths
    elif tool in {"Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "LS"}:
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
            elif tool in {"Edit", "MultiEdit", "NotebookEdit"}:
                files.pop(p, None)  # changed in a way the audit does not follow: read from disk
    elif tool in {"Grep", "Glob"}:
        base = _resolve(str(inp.get("path") or "."), workdir, bare=True) or workdir
        paths = [base]
        searches = [(tool, "content" if tool == "Grep" else "names", base)]
        pattern = str(inp.get("pattern") or "") if tool == "Glob" else ""
        if pattern:
            paths += _expand(_normpath(base / pattern))
    elif tool in {"file_read", "file_change"}:
        named = [inp.get(key) for key in ("path", "file_path")]
        changes = inp.get("changes")
        # A list of {path, kind}, as `codex exec --json` writes them, or a mapping from path to change.
        if isinstance(changes, dict):
            named += list(changes)
        elif isinstance(changes, list) and all(isinstance(c, dict) for c in changes):
            named += [c.get("path") for c in changes]
        elif changes is not None:
            return "suspect", "a file change the audit cannot read"
        if any(n is not None and not isinstance(n, str) for n in named):
            return "suspect", "a file change the audit cannot read"
        for name in named:
            if name:
                p = _resolve(str(name), workdir, bare=True)
                paths += [p] if p else []
    if tool in FILE_TOOLS:
        # Through a link in the work directory (`up -> ..`), a path there may lead anywhere.
        paths += [r for p in list(paths) if (r := _real(p, workdir)) != p]
        searches += [(verb, kind, r) for verb, kind, base in list(searches) if (r := _real(base, workdir)) != base]
    for p in paths:
        for root in roots:
            if _under(p, root) or (p not in literal_paths and _pattern_hits(p, root)):
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
    if tool in FILE_TOOLS:
        beyond = next((p for p in paths if not _under(p, workdir)), None)
        if beyond is not None:
            return "suspect", f"a file outside the work directory: {beyond}"
    if tool in {"shell", "Bash"} and URL.search(text) and re.search(r"\b(?:curl|wget)\b", text):
        return "web", ""
    if tool in {"shell", "Bash"} or tool in FILE_TOOLS:
        return "local", ""
    if tool in QUIET_TOOLS:
        return "other", ""
    return "suspect", f"a tool the audit does not know ({tool})"


def _id_key(value):
    """A Codex item's id as a key: numbers that are equal (1 and 1.0) alike, compared exactly
    (2^53 and 2^53 + 1 differ, and an integer of any size is read), anything else by its JSON text."""
    if not isinstance(value, bool) and (isinstance(value, int) or isinstance(value, float) and math.isfinite(value)):
        return ("number", Fraction(value))
    return ("json", json.dumps(value, sort_keys=True, default=str))


def _covers(done: list, begun: list) -> bool:
    """Whether a completed Codex item's calls cover a started one's: the same tools, each input the
    same where the started one gave a value (a search starts with an empty query), apart from an
    item's status, which changes from start to completion."""
    if [t for t, _ in done] != [t for t, _ in begun]:
        return False
    for (_, a), (_, b) in zip(done, begun):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            if a != b:
                return False
            continue
        if any(k != "status" and v not in (None, "", [], {}) and a.get(k) != v for k, v in b.items()):
            return False
    return True


def audit_transcript(path: Path, workdir: str) -> dict:
    work = Path(workdir) if workdir else Path("/nonexistent-workdir")
    roots = protected_roots()
    files: dict[Path, tuple] = {}  # what the run's calls wrote so far, by path (see `_Shell.files`)
    # Where the next Claude Code Bash call may start: where the last one ended if it ran to its end
    # in the foreground with status 0, and otherwise where the last one started (see `_next_place`).
    # The subset follows it with the places `exact.outside` gives, which hold the start too.
    bash_start: list[Path] | None = [work]
    bash_place: dict = {}
    events = calls = web = 0
    lists: dict[str, list] = {"violations": [], "suspect": [], "local_calls": []}
    urls: list[str] = []
    # Codex items started and not yet completed: one that never completes (a killed run) ran all
    # the same, and is audited as it started. A completion covers the started item with its id,
    # or, without an id, one whose calls it covers (see `_covers`); any other stays to be audited.
    started: list[tuple] = []

    def lose_place() -> None:
        """The next Bash call may start anywhere the audit can tell (a call it could not follow)."""
        nonlocal bash_start
        bash_start = None
        bash_place.update(worlds=[_World(work, None)], known=False)

    def audit_calls(line: dict) -> None:
        nonlocal calls, web, bash_start
        for tool, inp in _tool_calls(line):
            calls += 1
            # A call run in the background leaves the next where it found it (Claude Code reads no
            # place back from one). The flag is read as JSON's true or false (false if absent); a
            # call whose flag is anything else (null, 1, "yes") may have done either.
            background = inp.get("run_in_background", False) if tool == "Bash" and isinstance(inp, dict) else False
            place = bash_place if background is False else dict(bash_place)
            try:
                text = json.dumps(inp, default=str)
                verdict, why = check_call(tool, inp, work, roots, files,
                                          **({"start": bash_start, "place": place} if tool == "Bash" else {}))
                if tool == "Bash":
                    command = _shell_command(inp)
                    ended = None if command is None else exact.outside(command, work, bash_start)[1]
                    if background is not True:
                        bash_start = ended  # what `outside` returns holds where the call started
                    if background is not True and background is not False:
                        bash_place.update(worlds=list({(w.cwd, w.primary): w for w in [
                            *(bash_place.get("worlds") or [_World(work, None)]), *place.get("worlds", [])]}.values()),
                            known=bash_place.get("known", True) and place.get("known", True))
            except Exception as e:  # noqa: BLE001 - a call the audit cannot follow is suspect, never skipped
                verdict, why = "suspect", f"the audit could not follow this call ({type(e).__name__})"
                text = repr(inp)
                if tool == "Bash" and background is not True:
                    lose_place()
            if verdict == "web":
                web += 1
                found = URLISH.findall(text)
                urls.extend(found or [f"search: {inp.get('query', '') if isinstance(inp, dict) else ''}"[:200]])
                continue
            record = {"tool": tool if isinstance(tool, str) else repr(tool), "call": text[:4000],
                      **({"why": why} if why else {})}
            key = {"violation": "violations", "suspect": "suspect", "local": "local_calls"}.get(verdict)
            if key:
                lists[key].append(record)

    def audit_line(line, raw: str) -> None:
        nonlocal events
        if isinstance(line, list):
            # A line holding a list (no transcript writes one) is read as the events in it.
            for part in line:
                audit_line(part, raw)
            return
        if not isinstance(line, dict):
            lists["suspect"].append({"tool": "?", "call": raw[:4000], "why": "a transcript line that is not an event"})
            return
        events += 1
        item = line.get("item")
        event = line.get("type")
        if (event == "item.started" or event == "item.updated") and item is not None:
            key = _id_key(item.get("id")) if isinstance(item, dict) and "id" in item else None
            begun = list(_tool_calls({**line, "type": "item.completed"}))
            # An update stands for the item started (or updated) before whose calls it covers, and
            # is a start of its own otherwise.
            same = [i for i, (k, earlier, _) in enumerate(started) if k == key and _covers(begun, earlier)]
            if event == "item.updated" and same:
                started[same[0]] = (key, begun, line)
            else:
                started.append((key, begun, line))
        elif event == "item.completed" and item is not None:
            key = _id_key(item.get("id")) if isinstance(item, dict) and "id" in item else None
            done = list(_tool_calls(line))
            same = [i for i, (k, begun, _) in enumerate(started) if k == key and _covers(done, begun)]
            if same:
                started.pop(same[0])
        audit_calls(line)

    # Lines end at a newline alone: JSON text may hold U+2028 and the other characters that
    # str.splitlines also splits at.
    for raw in path.read_text(errors="replace").split("\n"):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except (ValueError, RecursionError) as e:
            # A line the audit cannot read (damaged, nested deeper than Python's parser goes, or with
            # an integer longer than it converts) may hold a call; it is not an event, so a
            # transcript of nothing else still fails.
            lists["suspect"].append({"tool": "?", "call": raw[:4000],
                                     "why": f"a transcript line the audit cannot read ({type(e).__name__})"})
            continue
        try:
            audit_line(line, raw)
        except Exception as e:  # noqa: BLE001 - a line the audit cannot follow is suspect, never skipped
            lists["suspect"].append({"tool": "?", "call": raw[:4000],
                                     "why": f"a transcript line the audit cannot follow ({type(e).__name__})"})
            lose_place()
    for _, _, line in started:
        try:
            audit_calls({**line, "type": "item.completed"})
        except Exception as e:  # noqa: BLE001
            lists["suspect"].append({"tool": "?", "call": repr(line)[:4000],
                                     "why": f"a transcript line the audit cannot follow ({type(e).__name__})"})
    return {
        "events": events,
        "tool_calls": calls,
        "web_calls": web,
        "urls": sorted(set(urls)),
        **lists,
        "passed": events > 0 and not lists["violations"],
    }
