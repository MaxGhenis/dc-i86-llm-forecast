"""The audit's shell model against the real shells, on generated MOCK programs.

Each program mixes directory changes (to directories present, missing or made on the way),
statuses, && and ||, if, case, loops (while, until, for, C-style, with counters), break, continue
and return, arithmetic, file tests, functions (with arguments and locals), subshells, background
jobs, pipelines (whose last stage zsh runs in the current shell), sh, bash and zsh -c (with
positional parameters), exported and unexported variables, env -i, eval, read (with IFS), set --
and shift, unset, variables, pushd/popd/dirs with stack rotations, and scripts written and then
sourced or run, then prints its directory and reads a relative path, in one of several ways, that
may reach another run's MOCK answer or a protected place. It runs under bash and zsh (no startup files) in a fresh temporary layout, and the
audit then reads it. Properties, for every program and both shells:

- soundness: if the shell printed a MOCK answer, the audit reports a violation or a suspect call;
- the directory the shell ended in is one of the audit's possible working directories (unless the
  audit says it lost track);
- when the audit has one possible directory and has not lost track, it is the shell's.
"""

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from i86 import audit, runners

ANSWER = "MOCK OTHER ANSWER"
SHELLS = [["/bin/bash", "--norc", "--noprofile", "-c"], ["/bin/zsh", "-f", "-c"]]
DIRS = ["scratch", "scratch/deep", "..", "../..", "gone", "scratch/gone", "-", "newd", '"$x"', '"$1"',
        '"$PWD/.."', "report.txt", "~+", "~-", "~0", "~1", "~+1", "~-0", "~-1"]
TARGETS = [
    "../opus-2/draft.json", "opus-2/draft.json", "../../opus-2/draft.json", "../../../opus-2/draft.json",
    "repository/draft.json", "../repository/draft.json", "../../repository/draft.json",
    "../../../repository/draft.json", "../../../../staging/draft.json", "draft.json",
]

atoms = st.one_of(
    st.sampled_from(DIRS).map(lambda d: f"cd {d}"),
    st.sampled_from(["true", "false", ":", "[ a = a ]", "[ a = b ]", "[ ! a = b ]", "[ -d scratch ]",
                     "[ -d gone ]", "[ -d newd ]", '[ "$x" = .. ]', "x=..", "x=scratch", "x=gone",
                     "mkdir -p newd", "mkdir newd 2>/dev/null", "rmdir newd 2>/dev/null",
                     "popd >/dev/null 2>&1", "shopt -s lastpipe 2>/dev/null",
                     # loops' and functions' exits, arithmetic and file tests
                     "break", "continue", "break 2", "return", "return 1", "[ -d report.txt ]",
                     "[ -f scratch ]", "[ -f report.txt ]", "[ -e newd ]", "i=0", "i=$((i+1))", "((i++))",
                     "let i+=1", '[ "$i" -lt 2 ]', "(( i < 2 ))", ": $((i+=2))",
                     # the directory stack
                     "pushd +1 >/dev/null 2>&1", "pushd -0 >/dev/null 2>&1", "pushd >/dev/null 2>&1",
                     "popd +1 >/dev/null 2>&1", "popd -0 >/dev/null 2>&1", "dirs -c",
                     # what functions, variables and child shells see
                     "unset -f g", "unset x", "export x", "export -n x 2>/dev/null", "set -- .. scratch",
                     "shift", 'IFS=: read y x <<< "scratch:.."', "x=$PWD",
                     # Expansion state, arrays, assigning parameters and shell startup (MOCK values).
                     "set -f", "set +f", "set -o noglob", "set +o noglob",
                     "setopt sh_word_split 2>/dev/null", "unsetopt SH_WORD_SPLIT 2>/dev/null",
                     "setopt noglob 2>/dev/null", "unsetopt noglob 2>/dev/null", "emulate sh 2>/dev/null",
                     "a=(scratch ..)", "a=(1 2)", 'set -- "${a[@]}"', "set -- ${a[*]}",
                     ": ${x:=..}", ": ${x=scratch}", ": ${x:?MOCK}", ": ${x?MOCK}",
                     "export IFS=:; export x=scratch:..; bash -c 'cd $x'",
                     # scripts written, then sourced or run
                     "echo 'cd ..' > s.sh", "echo 'cd scratch' > s.sh", ". ./s.sh 2>/dev/null", "sh s.sh"]),
    st.sampled_from(DIRS).map(lambda d: f"pushd {d} >/dev/null 2>&1"),
    st.sampled_from(DIRS).map(lambda d: f"cd {d} | cat"),
    st.sampled_from(DIRS).map(lambda d: f"eval {shlex.quote('cd ' + d)}"),
    st.sampled_from(DIRS).map(lambda d: f"x=$(cd {d} && pwd)"),
    st.sampled_from(DIRS).map(lambda d: f"read x <<< {d}"),
    st.sampled_from(DIRS).map(lambda d: f"sh -c 'cd \"$1\"' sh {d}"),
    st.sampled_from(DIRS).map(lambda d: f"g(){{ cd \"$1\"; }}; g {d}"),
    st.sampled_from(DIRS).map(lambda d: f"true | cd {d}"),
    st.sampled_from(DIRS).map(lambda d: f"echo {d} | while read d; do cd \"$d\"; done"),
    st.sampled_from(DIRS).map(lambda d: f"echo {d} | read x"),
)


def compound(inner):
    name = st.integers(0, 10**9).map(lambda k: f"f{k}")
    return st.one_of(
        st.tuples(inner, st.sampled_from(["&&", "||"]), inner).map(lambda t: " ".join(t)),
        inner.map(lambda a: f"! {{ {a}; }}"),
        st.tuples(inner, inner, inner).map(lambda t: f"if {t[0]}; then {t[1]}; else {t[2]}; fi"),
        st.tuples(inner, inner).map(lambda t: f"if {t[0]}; then {t[1]}; fi"),
        inner.map(lambda a: f"( {a} )"),
        inner.map(lambda a: f"{{ {a}; }}"),
        st.tuples(name, inner).map(lambda t: f"{t[0]}(){{ {t[1]}; }}; {t[0]}"),
        st.tuples(st.sampled_from(["x", "y", '"$x"']), st.sampled_from(["x", "y", "x*", "*", ".."]), inner)
        .map(lambda t: f"case {t[0]} in {t[1]}) {t[2]};; esac"),
        inner.map(lambda a: f"while false; do {a}; done"),
        inner.map(lambda a: f"until true; do {a}; done"),
        inner.map(lambda a: f"for d in 1; do {a}; done"),
        st.tuples(st.sampled_from(["sh -c", "bash -c", "zsh -f -c"]), inner).map(lambda t: f"{t[0]} {shlex.quote(t[1])}"),
        # Loops with counters no generated atom touches, so each ends.
        st.tuples(name, inner).map(lambda t: f"{t[0]}=0; while [ $(({t[0]}+=1)) -le 2 ]; do {t[1]}; done"),
        st.tuples(name, inner).map(lambda t: f"{t[0]}=0; until [ $(({t[0]}+=1)) -gt 2 ]; do {t[1]}; done"),
        st.tuples(name, inner).map(lambda t: f"for (({t[0]}=0; {t[0]}<2; {t[0]}++)); do {t[1]}; done"),
        inner.map(lambda a: f"for d in 1 2; do {a}; done"),
        st.tuples(st.sampled_from(["{1..2}", "{2..1}", "pre{a,b}post", "{x,y}{1,2}",
                                  "$a", '"${a[@]}"', "${a[*]}"]), inner)
        .map(lambda t: f"for d in {t[0]}; do {t[1]}; done"),
        st.tuples(name, st.sampled_from(["local", "typeset", "declare"]), inner)
        .map(lambda t: f"{t[0]}(){{ {t[1]} IFS x; {t[2]}; }}; {t[0]}"),
        st.tuples(inner, inner).map(lambda t: f"for d in 1 2; do for e in 1 2; do {t[0]}; done; {t[1]}; done"),
        st.tuples(name, inner, inner).map(lambda t: f"{t[0]}(){{ {t[1]}; return 1; {t[2]}; }}; {t[0]}"),
        st.tuples(name, inner).map(lambda t: f"{t[0]}(){{ local x=scratch; {t[1]}; }}; {t[0]}"),
        st.tuples(name, inner).map(lambda t: f"{t[0]}(){{ {t[1]}; }}; export -f {t[0]} 2>/dev/null; bash -c {t[0]}"),
    )


# The final read, of target t.
READS = [
    "cat {t}", "cat < {t}", "sh -c 'cat \"$1\"' sh {t}", "echo {t} | xargs cat", "f(){{ cat \"$1\"; }}; f {t}",
    "echo {t} | while read f; do cat \"$f\"; done", "(cd scratch && cat ../{t})", "env -C scratch cat ../{t}",
    "y={t}; cat $y", "zsh -f -c 'true | cd scratch; cat ../{t}'", "bash -c 'true | cd scratch; cat ../{t}'",
    # child shells see exported variables only; env -i, none
    "sh -c 'cd \"$x\" 2>/dev/null; cat {t}'", "env -i sh -c 'cd \"$x\" 2>/dev/null; cat {t}'",
    "env -C.. cat opus-1/{t}", "env -S'cat {t}'", "cat \"$PWD/{t}\"",
    # interpreters with attached option values and awk reading a -v path
    "python3 -c\"print(open('{t}').read(), end='')\"", "awk -vf={t} 'BEGIN {{ while ((getline l < f) > 0) print l }}'",
    "IFS=/ read a b <<< '{t}'; cat \"$a/$b\"",
    # a script written, then run or sourced
    "echo 'cat {t}' > r.sh; sh r.sh", "printf 'cat %s\\n' {t} > r.sh; . ./r.sh",
    "cat > r.sh <<'EOF'\ncat {t}\nEOF\nbash r.sh",
    "cat ~+/{t}", "cd scratch; cat ~-/{t}", "pushd scratch >/dev/null; cat ~1/{t}",
    "export IFS=:; export x=scratch:..; bash -c 'cd $x 2>/dev/null; cat {t}'",
    "cat {t}{{,}}",  # duplicate MOCK operands from brace expansion
]


def joined(parts):
    """Statements joined by separators; a statement before & runs in the background (it is
    waited for, so the read comes after it)."""
    return st.lists(st.sampled_from(["; ", "\n", " & wait; "]), min_size=len(parts), max_size=len(parts)).map(
        lambda seps: "".join(p + sep for p, sep in zip(parts, seps)))


programs = st.tuples(
    st.lists(st.recursive(atoms, compound, max_leaves=6), min_size=1, max_size=4).flatmap(joined),
    st.sampled_from(READS), st.sampled_from(TARGETS))


def layout(top: Path) -> Path:
    """The review_area layout (see conftest.py) under top; returns this run's work directory."""
    work = top / "work" / "opus-1"
    (work / "scratch" / "deep").mkdir(parents=True)
    (work / "report.txt").write_text("MOCK own report\n")
    for root in [top / "work" / "opus-2", top / "repository", top / "staging"]:
        root.mkdir(parents=True)
        (root / "draft.json").write_text(ANSWER + "\n")
    (top / "home").mkdir()
    return work


def run(shell: list[str], program: str, work: Path, top: Path) -> tuple[Path | None, bool]:
    """Where the shell ended (None if it never printed it) and whether it printed a MOCK answer."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work), "OLDPWD": str(work)}
    for attempt in range(3):  # a shell stalled on a loaded host says nothing about the audit
        try:
            proc = subprocess.run([*shell, program], cwd=work, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=20)
            break
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise
    lines = proc.stdout.splitlines()
    read = ANSWER in lines
    marker = [line for line in lines if line.startswith("PWD=")]
    # No marker: the shell rejected the program (zsh does not parse `x=1 &`) or exited before the
    # end, so it never reached the read either.
    return (Path(marker[-1][4:]) if marker else None), read


@settings(max_examples=int(os.environ.get("I86_DIFFERENTIAL_EXAMPLES", "300")), deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(programs)
def test_audit_agrees_with_bash_and_zsh(case):
    prefix, read_with, target = case
    for shell in SHELLS:
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp).resolve()
            work = layout(top)
            program = (f'{prefix}echo "PWD=$(pwd -P)"; {read_with.format(t=target)} 2>/dev/null; '
                       'echo "PWD=$(pwd -P)"')
            cwd, read = run(shell, program, work, top)
            roots = [top / "repository", top / "staging"]
            with mock.patch.object(runners, "WORK", top / "work"), \
                    mock.patch.object(audit, "protected_roots", lambda: roots), \
                    mock.patch.object(audit, "HOME", top / "home"):
                model = audit._shell(program, work)
                verdict, why = audit.check_call("shell", {"command": program}, work, roots)
            places = {w.cwd for w in model.worlds}
            label = f"{shell[0]}: {program!r} -> cwd {cwd}, read {read}, audit {verdict} ({why}), worlds {model.worlds}"
            if read:
                assert verdict in {"violation", "suspect"}, label
            if model.known and cwd is not None:
                assert cwd in places, label
                if len(places) == 1:
                    assert places == {cwd}, label
