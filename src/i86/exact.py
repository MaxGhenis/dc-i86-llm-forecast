"""The shell calls whose reads the audit knows exactly.

`outside` finds what in a shell command lies outside a small subset whose reads follow from its text
alone, or reaches beyond the run's work directory. `audit.check_call` takes a shell call as local
only when it finds nothing. The subset:

- Words are literal: letters, digits and `_ . / , : @ % + = -` outside quotes, single-quoted text,
  and double-quoted text without `$`, a backquote, a backslash or `!`; no word starts with an
  unquoted `=`, after nothing but empty quotes (zsh's `=cmd`, which `''=cmd` is too). There is no
  expansion, substitution, glob, redirection, assignment, comment, group, subshell or background
  job, so bash, zsh, sh and dash read the same words.
- Commands are joined by `;`, `&&`, `||`, `|` and newlines.
- A command is a tool in TOOLS with options from its list, before its operands; find with the
  primaries in FIND; or `cd DIR` alone in its pipeline, DIR not starting with `-` or `+`. No listed
  option makes a tool follow a link, run a program, write a file or open one it is not given, in
  the GNU or the BSD tool of that name. curl's operands must be http(s) URLs. `bash`, `zsh`, `sh`
  or `dash` with `-c`, `-lc` or `-l -c` and one more word, as the whole command, runs that word as
  a command in the subset.
- The files a tool may open must resolve, from every place the shell may be, inside the work
  directory, part by part with no link on the way and no `..` above it (as the disk is at audit
  time; no command in the subset makes a link). They are its operands other than a pattern, script
  or filter; the current directory, for a tool that searches it when given no path or only `-`
  (ugrep's `-r` searches both standard input and the current directory then); and `find -newer`'s
  file. `-` (standard input) and `/dev/null` open nothing else to check.
- Where a call starts is a list of places, or None when the transcript does not say: Codex's shell
  tool may run a command in a directory its transcript does not record. From an unknown place a
  relative path is outside. Only `cd` moves the shell, and a `cd` may fail.

It takes the tools the names find to be the standard ones (or, for grep and find, the ugrep and bfs
that Claude Code's shell runs in their place), and the environment a call starts with, its startup
files included, to set none of the variables, options, aliases and files that change them (`CDPATH`,
`GREP_OPTIONS`, `RIPGREP_CONFIG_PATH`, zsh's `cdablevars` and `rcquotes`, a `.curlrc` or `~/.jq`),
and to move no shell. rg and ugrep also read ignore files, which only choose among the files under
the paths they search.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Characters a word may have outside quotes.
WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./,:@%+=-")
SHELLS = {prefix + name for prefix in ["", "/bin/", "/usr/bin/", "/usr/local/bin/", "/opt/homebrew/bin/"]
          for name in ["bash", "zsh", "sh", "dash"]}


@dataclass(frozen=True)
class Tool:
    flags: str = ""  # short options without a value
    valued: str = ""  # short options with one
    long: dict = field(default_factory=dict)  # long option: values it takes (0, 1, 2; -1: only `=value`)
    first: str = ""  # what its first operand is when no option gives it: "pattern", "script", "filter"
    urls: bool = False  # its operands are http(s) URLs (curl), not files
    searches: bool = False  # reads the current directory when given no path (or only `-`)
    digits: bool = False  # `-50`, as head and tail take it
    files: bool = True  # whether it opens files at all (echo never does)
    operands: int | None = None  # most operands (uniq writes a second one)


def _long(none: str = "", one: str = "", optional: str = "") -> dict:
    return {**{n: 0 for n in none.split()}, **{n: 1 for n in one.split()}, **{n: -1 for n in optional.split()}}


# grep is macOS's BSD grep, GNU grep or Claude Code's ugrep. Its long options take a value only after
# `=`: BSD grep reads `--context 1 X f` as the pattern 1 and the files X and f. `-d` is left out, as
# ugrep's `-d dereference-recurse` follows links.
GREP = Tool(flags="abcEFGHhIiLlnoqrsUvwx", valued="ABCem", long=_long(
    "count extended-regexp files-with-matches files-without-match fixed-strings ignore-case invert-match "
    "line-number line-regexp no-filename no-messages only-matching quiet recursive silent text "
    "with-filename word-regexp", "",
    "after-context before-context binary-files color colour context exclude exclude-dir include "
    "max-count regexp"), first="pattern", searches=True)
TOOLS = {
    "cat": Tool(flags="benstuv"),
    "head": Tool(flags="qv", valued="nc", digits=True),
    "tail": Tool(flags="qrv", valued="nc", digits=True),
    "wc": Tool(flags="clmwL"),
    "sort": Tool(flags="bdfghiMnrRsuV", valued="kt"),
    "uniq": Tool(flags="cdiu", valued="fs", operands=1),
    "cut": Tool(flags="nsw", valued="bcdf"),
    "tr": Tool(files=False),
    "ls": Tool(flags="1@%AaBbCcdeFfGghiklmnOopqRrSsTtUuWwx", searches=True),
    "grep": GREP, "egrep": GREP, "fgrep": GREP,
    "rg": Tool(flags=".0cFHhIilNnoqSsuvwx", valued="ABCdegjMmrTt", long=_long(
        "case-sensitive column count count-matches files files-with-matches files-without-match "
        "fixed-strings heading hidden ignore-case invert-match json line-number line-regexp multiline "
        "multiline-dotall no-config no-filename no-heading no-ignore no-ignore-dot no-ignore-parent "
        "no-ignore-vcs no-line-number null only-matching quiet smart-case stats text trim vimgrep "
        "with-filename word-regexp",
        "after-context before-context color colors context glob iglob max-columns max-count max-depth "
        "regexp replace sort sortr threads type type-not"), first="pattern", searches=True),
    "sed": Tool(flags="En", valued="e", first="script"),
    "jq": Tool(flags="aCcejMnRrSs", long=_long(
        "ascii-output color-output compact-output exit-status join-output monochrome-output null-input "
        "raw-input raw-output slurp sort-keys tab", "indent") | {"arg": 2, "argjson": 2}, first="filter"),
    "echo": Tool(files=False), "printf": Tool(files=False),
    "true": Tool(files=False), "false": Tool(files=False), ":": Tool(files=False),
    "pwd": Tool(flags="LP", operands=0),
    "curl": Tool(flags="fIiLsSv", valued="Am", long=_long(
        "compressed fail head include location show-error silent verbose",
        "connect-timeout max-time retry user-agent"), urls=True),
}
# find's primaries and how many values each takes; `(`, `)` and `!` join them. Of the values, only
# `-newer`'s names a file it opens (for its time).
FIND = {**{p: 0 for p in "-a -and -depth -empty -false -ls -not -o -or -print -print0 -prune -true".split()},
        **{p: 1 for p in "-amin -atime -cmin -ctime -group -ipath -iname -iregex -iwholename -maxdepth "
           "-mindepth -mmin -mtime -name -newer -path -perm -regex -regextype -size -type -user "
           "-wholename".split()}}
# sed scripts that only print or delete numbered lines, or quit.
SED_STEP = r"(?:(?:\d+|\$)(?:,(?:\d+|\$))?[pd]|\d+q)"
SED_SCRIPT = re.compile(rf"{SED_STEP}(?:;{SED_STEP})*;?")


def _lex(text: str) -> list[str | tuple[str]] | str:
    """The words (str) and operators (1-tuples; a newline is `("\\n",)`), or why the text is outside."""
    out: list = []
    word: str | None = None
    i = 0
    while i < len(text):
        c = text[i]
        if c in " \t\n;|&":
            if word is not None:
                out.append(word)
                word = None
            if text.startswith("&&", i) or text.startswith("||", i):
                out.append((text[i:i + 2],))
                i += 1
            elif c == "&":
                return "`&`"
            elif c != " " and c != "\t":
                out.append((c,))
        elif c in "'\"":
            end = text.find(c, i + 1)
            if end < 0:
                return "an unclosed quote"
            inner = text[i + 1:end]
            if c == '"' and any(ch in inner for ch in "$`\\!"):
                return "an expansion or escape in double quotes"
            word = (word or "") + inner
            i = end
        elif c in WORD:
            if c == "=" and not word:  # zsh expands `=a` and `''=a` alike
                return "a word starting with `=`"
            word = (word or "") + c
        else:
            return f"`{c}`" if c.isprintable() else f"character {ord(c):#x}"
        i += 1
    if word is not None:
        out.append(word)
    return out


def _pipelines(tokens: list) -> list[tuple[str, list[list[str]]]] | str:
    """(the operator before it: ";", "&&" or "||"; its commands, as word lists) for each pipeline,
    or why the tokens do not parse."""
    pipelines: list[tuple[str, list[list[str]]]] = []
    current: list[list[str]] = []
    command: list[str] = []
    before, need = ";", False  # need: an operator came last, so a command must follow
    for token in tokens:
        if isinstance(token, str):
            command.append(token)
            need = False
            continue
        op = token[0]
        if op == "\n" and not command and (need or not current):
            continue  # a blank line, or a line break after `&&`, `||` or `|`
        if not command:
            return f"`{op}` with no command before it"
        current.append(command)
        command = []
        if op == "|":
            need = True
            continue
        pipelines.append((before, current))
        current = []
        before, need = (op, True) if op in {"&&", "||"} else (";", False)
    if need:
        return "an operator with no command after it"
    if command:
        current.append(command)
    if current:
        pipelines.append((before, current))
    return pipelines


def _options(tool: Tool, words: list[str]) -> tuple[list[str], list[str]] | str:
    """(operands; patterns or scripts given by options), or the word outside the tool's options.

    Options must come before the operands: GNU tools read options anywhere, BSD tools stop at the
    first operand and take the words after it as files (`--` too)."""
    operands, given = [], []
    i, ended = 0, False
    while i < len(words):
        w = words[i]
        i += 1
        if ended or w == "-" or not w.startswith("-"):
            operands.append(w)
            continue
        if operands:
            return f"`{w}` after an operand"
        if w == "--":
            ended = True
            continue
        if w.startswith("--"):
            name, eq, value = w[2:].partition("=")
            n = tool.long.get(name)
            if n is None or (eq and n not in {1, -1}):
                return f"`{w}`"
            taken = [value] if eq else words[i:i + max(n, 0)]
            if not eq and n > 0:
                if i + n > len(words):
                    return f"`{w}` with no value"
                i += n
            if name == "regexp":
                given += taken
            continue
        for k, c in enumerate(w[1:], 1):
            if c in tool.valued:
                value = w[k + 1:]
                if not value:
                    if i == len(words):
                        return f"`{w}` with no value"
                    value = words[i]
                    i += 1
                if c == "e":
                    given.append(value)
                break
            if c not in tool.flags and not (tool.digits and c.isdigit()):
                return f"`{w}`"
    return operands, given


def _find(words: list[str]) -> list[str] | str:
    """The words find may open as files, or the word outside."""
    opened, i = [], 0
    while i < len(words) and not (words[i].startswith("-") or words[i] in {"(", ")", "!"}):
        opened.append(words[i])
        i += 1
    if not opened:
        opened.append(".")
    while i < len(words):
        w = words[i]
        i += 1
        if w in {"(", ")", "!"}:
            continue
        n = FIND.get(w)
        if n is None or i + n > len(words):
            return f"`find {w}`"
        if w == "-newer":
            opened.append(words[i])
        i += n
    return opened


def _opened(name: str, args: list[str]) -> list[str] | str:
    """The words a command may open as files, or what is outside the subset."""
    if name == "find":
        return _find(args)
    tool = TOOLS.get(name)
    if tool is None:
        return f"`{name}`, which is not in the subset"
    if not tool.files:
        return []
    parsed = _options(tool, args)
    if isinstance(parsed, str):
        return f"`{name}` with {parsed}"
    operands, given = parsed
    if tool.operands is not None and len(operands) > tool.operands:
        return f"`{name}` with more than {tool.operands} operand(s)"
    # The pattern, script or filter is the first operand unless an option gave it (rg --files has none).
    lead = 1 if tool.first and not given and not (name == "rg" and "--files" in args) else 0
    if tool.first and lead and not operands:
        return f"`{name}` with no {tool.first}"
    if name == "sed" and not all(SED_SCRIPT.fullmatch(s) for s in given or operands[:1]):
        return "a sed script other than numbered prints, deletes and quits"
    if name == "jq" and lead and re.search(r"\b(?:import|include)\b", operands[0]):
        return "a jq module"
    paths = operands[lead:]
    if tool.urls:
        if not operands or not all(re.fullmatch(r"https?://\S+", w) for w in operands):
            return f"`{name}` with an operand other than an http(s) URL"
        return []  # none of these options opens a file
    # A search with no path searches the working directory, and so does ugrep's `-r` with only `-`.
    return paths + (["."] if tool.searches and not [w for w in paths if w != "-"] else [])


def _resolve(word: str, places: list[Path] | None, workdir: Path) -> list[Path] | None:
    """Where a word names from each place, if each is in the work directory with no link on the way.

    The parts are followed one by one, as the system does: `l/..` is the parent of where the link l
    points, so a `..` may not cancel a link, and no `..` may go above the work directory."""
    if word.startswith("/"):
        bases = [Path("/")]
    elif places is None:
        return None
    else:
        bases = places
    found = []
    for base in bases:
        current = base
        for part in word.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if not current.is_relative_to(workdir) or current == workdir:
                    return None
                current = current.parent
                continue
            current = current / part
            if current.is_relative_to(workdir) and current.is_symlink():
                return None
        if not current.is_relative_to(workdir):
            return None
        found.append(current)
    return found


def _union(a: list[Path] | None, b: list[Path] | None) -> list[Path] | None:
    return None if a is None or b is None else list(dict.fromkeys([*a, *b]))


def outside(command: str, workdir: Path, start: list[Path] | None, nested: bool = False
            ) -> tuple[str | None, list[Path] | None]:
    """(What in the command lies outside the subset, or None; the places the shell may end in, None
    when unknown). `start`: the places it may start in, None when unknown."""
    tokens = _lex(command)
    if isinstance(tokens, str):
        return tokens, None
    pipelines = _pipelines(tokens)
    if isinstance(pipelines, str):
        return pipelines, None
    if (not nested and len(pipelines) == 1 and len(pipelines[0][1]) == 1 and pipelines[0][1][0][0] in SHELLS
            and pipelines[0][1][0][1:-1] in (["-c"], ["-lc"], ["-l", "-c"])):
        # A child shell starts where this one is, and its cd leaves this one's place alone.
        why, _ = outside(pipelines[0][1][0][-1], workdir, start, nested=True)
        return why, start if why is None else None
    # Where the shell may be once the last pipeline succeeded, and once it failed.
    ok: list[Path] | None = start
    failed: list[Path] | None = []
    for before, pipeline in pipelines:
        if before == "&&":
            places, skipped_ok, skipped_failed = ok, [], failed
        elif before == "||":
            places, skipped_ok, skipped_failed = failed, ok, []
        else:
            places, skipped_ok, skipped_failed = _union(ok, failed), [], []
        moved = None
        for words in pipeline:
            name, args = words[0], words[1:]
            if name == "cd":
                if len(pipeline) > 1:
                    return "`cd` in a pipeline", None
                # zsh reads `cd +0` and `cd -1` as places on its directory stack.
                if len(args) != 1 or args[0][:1] in {"-", "+"}:
                    return "`cd` without exactly one directory", None
                moved = _resolve(args[0], places, workdir)
                if moved is None:
                    return f"`cd {args[0]}` from a place that is unknown or leaves the work directory", None
                continue
            opened = _opened(name, args)
            if isinstance(opened, str):
                return opened, None
            for word in opened:
                if word not in {"-", "/dev/null"} and _resolve(word, places, workdir) is None:
                    return f"`{word}`, from a place that is unknown or leaves the work directory", None
        ok = _union(moved if moved is not None else places, skipped_ok)
        failed = _union(places, skipped_failed)
    return None, _union(ok, failed)
