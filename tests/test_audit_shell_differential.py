"""The audit's shell model against the real shells, on generated MOCK programs.

Each program mixes directory changes (to directories present, missing or made on the way),
statuses, && and ||, if, case, loops, functions (with arguments), subshells, background jobs,
pipelines (whose last stage zsh runs in the current shell), sh, bash and zsh -c (with positional
parameters), eval, read, variables and pushd/popd, then prints its
directory and reads a relative path, in one of several ways, that may reach another run's MOCK
answer or a protected place. It runs under bash and zsh (no startup files) in a fresh temporary layout, and the
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
DIRS = ["scratch", "scratch/deep", "..", "../..", "gone", "scratch/gone", "-", "newd", '"$x"']
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
                     "popd >/dev/null 2>&1", "shopt -s lastpipe 2>/dev/null"]),
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
    )


# The final read, of target t.
READS = [
    "cat {t}", "cat < {t}", "sh -c 'cat \"$1\"' sh {t}", "echo {t} | xargs cat", "f(){{ cat \"$1\"; }}; f {t}",
    "echo {t} | while read f; do cat \"$f\"; done", "(cd scratch && cat ../{t})", "env -C scratch cat ../{t}",
    "y={t}; cat $y", "zsh -f -c 'true | cd scratch; cat ../{t}'", "bash -c 'true | cd scratch; cat ../{t}'",
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
    read = bool(lines) and lines[-1] == ANSWER
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
            program = f'{prefix}echo "PWD=$(pwd -P)"; {read_with.format(t=target)} 2>/dev/null'
            cwd, read = run(shell, program, work, top)
            roots = [top / "repository", top / "staging"]
            with mock.patch.object(runners, "WORK", top / "work"), \
                    mock.patch.object(audit, "protected_roots", lambda: roots):
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
