"""The audit's shell model, construct by construct, against bash and zsh (MOCK layouts only).

Differential properties check the arithmetic evaluator and `read`'s field splitting against the real
shells on generated inputs; the examples check loops, jumps, the directory stack, child shells'
environments, attached option values, `$PWD` and scripts carried from one tool call to the next.
"""

import json
import os
import shlex
import subprocess

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from i86 import audit

BASH, ZSH = "/bin/bash", "/bin/zsh"
EXAMPLES = int(os.environ.get("I86_DIFFERENTIAL_EXAMPLES", "300"))


def sh(shell: str, code: str, cwd=None) -> subprocess.CompletedProcess:
    args = [shell, "-f", "-c", code] if shell == ZSH else [shell, "--norc", "--noprofile", "-c", code]
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=20,
                          env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-home"})


# Arithmetic

names = st.sampled_from(["a", "b", "n"])
leaf = st.one_of(st.integers(0, 99).map(str), names)
UNARY = ["-", "!", "~"]
BINARY = ["+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!=", "&&", "||", "&", "|", "^", "<<", ">>"]


def expressions(inner):
    return st.one_of(
        st.tuples(inner, st.sampled_from(BINARY), inner).map(lambda t: f"{t[0]} {t[1]} {t[2]}"),
        st.tuples(st.sampled_from(UNARY), inner).map(lambda t: f"{t[0]}({t[1]})"),
        inner.map(lambda e: f"({e})"),
        st.tuples(inner, inner, inner).map(lambda t: f"{t[0]} ? {t[1]} : {t[2]}"),
        st.tuples(names, st.sampled_from(["=", "+=", "-=", "*="]), inner).map(lambda t: f"{t[0]} {t[1]} ({t[2]})"),
        names.map(lambda n: f"{n}++"), names.map(lambda n: f"--{n}"),
        st.tuples(inner, inner).map(lambda t: f"{t[0]}, {t[1]}"),
    )


arith = st.recursive(leaf, expressions, max_leaves=8)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(arith, st.integers(-9, 9), st.integers(-9, 9))
def test_arithmetic_matches_bash_and_zsh(expr, a, b):
    """Wherever the audit evaluates an expression, its value and assignments are bash's and zsh's
    (division by zero, overflow and the like it declines, as unknown)."""
    try:
        value, assigned = audit._arith(expr, lambda name: {"a": str(a), "b": str(b)}.get(name, ""))
    except audit._ArithError:
        assume(False)
    assume(-(2 ** 31) < value < 2 ** 31)
    code = f"a={a}; b={b}; echo $(( {expr} )); echo \"$a $b ${{n:-}}\""
    for shell in (BASH, ZSH):
        proc = sh(shell, code)
        assert proc.returncode == 0, (shell, expr, proc.stderr)
        got, env = proc.stdout.split("\n")[:2]
        want = {"a": str(a), "b": str(b), "n": "", **assigned}
        assert int(got) == value, (shell, expr, got, value)
        assert env.split(" ") == [want["a"], want["b"], want["n"]] or env == f"{want['a']} {want['b']} ", (shell, expr, env, want)


# read and IFS

@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text(alphabet=" \t:/ab", max_size=12), st.sampled_from([" \t\n", ":", ": ", "/", " /", ""]),
       st.integers(1, 3))
def test_read_fields_match_bash_and_zsh(line, ifs, n):
    vars_ = ["x", "y", "z"][:n]
    # The line is always quoted: bash 3.2 splits an unquoted here-string (see the next tests).
    code = (f"IFS={shlex.quote(ifs)} read -r {' '.join(vars_)} <<< '{line}'; "
            + "printf '%s\\0' " + " ".join(f'"${v}"' for v in vars_))
    for shell, bash in ((BASH, True), (ZSH, False)):
        got = sh(shell, code).stdout.split("\0")[:n]
        assert got == audit._read_fields(line, ifs, n, bash=bash), (shell, line, ifs, n, got)


# Field splitting: what unquoted expansions become, in each shell (the audit's model run as that shell)

def _model(program: str, workdir, dialect: str | None) -> "audit._Shell":
    shell = audit._Shell(workdir)
    shell.dialect = dialect
    shell.run(program)
    return shell


WORDS = ['$y', '"$y"', 'x$y', '$y"q"', '$y$y', '"$y"$y', "''$y", '${y}', '\\:$y', '$y\\ $y',
         '$(echo "$y")', '"$(echo "$y")"', 'a:b', '"$@"', '$@', '$*', '${n:-$y}']


# The review_area fixture is only read, so one layout serves every example.
FIXTURE_OK = [HealthCheck.too_slow, HealthCheck.function_scoped_fixture]


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from([None, " \t\n", ":", ": ", "", "/", " :"]), st.text(alphabet=" :/ab", max_size=6),
       st.lists(st.sampled_from(WORDS), min_size=1, max_size=3))
def test_field_splitting_matches_bash_and_zsh(review_area, ifs, y, words):
    setup = ("" if ifs is None else f"IFS='{ifs}'; ") + f"y='{y}'; set -- 'p q' ''; set -- {' '.join(words)}"
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        real = sh(shell, setup + "; printf '%s\\0' \"$#\" \"$@\"", cwd=review_area).stdout.split("\0")[:-1]
        model = _model(setup, review_area, dialect)
        n = model.vars.get("#")
        params = model.vars.get("@", "").split(audit.SPLIT) if n != "0" else []
        assume(n is not None and all(audit.UNKNOWN not in x and "\x06" not in x for x in [n, *params]))
        assert [n, *params] == real, (shell, setup, [n, *params], real)


@pytest.mark.parametrize("program", [
    'a=".. x"; cd $a',
    'a="scratch deep"; for d in $a; do cd $d; done',
    'set -- $(echo scratch deep); cd $1; cd $2',
    'e=; cd $e scratch',
    'IFS=:; a="scratch:deep"; set -- $a; cd "$1/$2"',
    'c="cd scratch"; $c',
    'a="1 -eq 2"; [ $a ] || cd scratch',
    'e=; [ $e = x ] || cd scratch',
    'f(){ cd "$@"; }; cd scratch; f; cd "$OLDPWD"',
])
@pytest.mark.parametrize("shell,dialect", [(BASH, "posix"), (ZSH, "zsh"), (BASH, None), (ZSH, None)])
def test_field_splitting_ends_where_the_shell_ends(review_area, monkeypatch, program, shell, dialect):
    monkeypatch.setattr(audit, "HOME", review_area / "scratch" / "deep")
    proc = subprocess.run([shell, "-f" if shell == ZSH else "--norc", "-c", program + "; pwd -P"], cwd=review_area,
                          capture_output=True, text=True, timeout=20,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(review_area / "scratch" / "deep")})
    real = audit.Path(proc.stdout.strip().splitlines()[-1])
    model = _model(program, review_area, dialect)
    places = {w.cwd for w in model.worlds}
    assert real in places or not model.known, (program, places, real)
    if dialect is not None:
        # A cd to a directory missing at audit time may also have worked, as far as the audit
        # knows; every other place the model keeps is a mistake.
        assert model.known and places - {real} <= {p for p in places if not p.exists()}, (program, places, real)


# Here-strings: bash 3.2 (/bin/bash) splits an unquoted one at IFS and joins the fields with spaces

@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from([None, ":", ": ", "", "/"]), st.sampled_from([None, ":", " "]),
       st.text(alphabet=" :/ab", max_size=6), st.sampled_from(["$y", '"$y"', "a:$y", "$y'q:r'", "::", "a\\:b:c"]))
def test_herestrings_match_bash_and_zsh(review_area, ifs, prefix, y, word):
    setup = ("" if ifs is None else f"IFS='{ifs}'; ") + f"y='{y}'; " + ("" if prefix is None else f"IFS='{prefix}' ")
    program = setup + f"read -r x <<< {word}"
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        real = sh(shell, program + "; printf '%s' \"$x\"", cwd=review_area).stdout
        model = _model(program, review_area, dialect)
        assert model.vars.get("x") == real, (shell, program, model.vars.get("x"), real)
    # Where the shell is not known: both shells' values, or unknown.
    either = _model(program, review_area, None).vars.get("x", audit.UNKNOWN)
    ways = {_model(program, review_area, d).vars.get("x") for d in ("posix", "zsh")}
    assert audit.UNKNOWN in either or ways <= set(audit._choices(either)), (program, either, ways)


def test_a_split_herestring_that_reaches_another_run_is_caught(review_area):
    # bash 3.2 turns `..:x` into `.. x`; split again at a space, `cd` goes to `..` (MOCK layout).
    command = 'IFS=: read -r a <<< ..:x; IFS=" "; cd $a; cat opus-2/draft.json'
    proc = sh(BASH, command, cwd=review_area)
    assert "MOCK OTHER ANSWER" in proc.stdout
    assert audit.check_call("shell", {"command": command}, review_area, audit.protected_roots())[0] != "local"
    assert audit.check_call("shell", {"command": f"bash -c {shlex.quote(command)}"}, review_area,
                            audit.protected_roots())[0] == "violation"


@pytest.mark.parametrize("command", [
    'a=".. x"; cd $a; cat opus-2/draft.json',
    'set -- $(echo .. x); cd $1; cat opus-2/draft.json',
    'c="cat ../opus-2/draft.json"; $c',
    'e=; f(){ cd "$@"; cat ../../../opus-2/draft.json; }; f',
])
def test_split_words_that_reach_another_run_are_caught(review_area, monkeypatch, command):
    monkeypatch.setattr(audit, "HOME", review_area / "scratch" / "deep")
    proc = subprocess.run([BASH, "--norc", "-c", command], cwd=review_area, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(review_area / "scratch" / "deep")})
    assert "MOCK OTHER ANSWER" in proc.stdout, proc
    assert audit.check_call("shell", {"command": command}, review_area, audit.protected_roots())[0] == "violation"
    assert audit.check_call("shell", {"command": f"bash -c {shlex.quote(command)}"}, review_area,
                            audit.protected_roots())[0] == "violation"


# Loops and jumps, in both shells: where they end. Every cd here is to a directory that exists, so the
# model, which treats a cd to a missing directory as possibly made earlier, should know the one place.

LOOPS = [
    "for i in 1; do break; cd scratch; done",
    "for d in scratch deep; do cd $d; continue; cd ..; done",
    "for i in 1 2; do for j in 1 2; do break 2; done; cd scratch; done",
    "f(){ return; cd scratch; }; f",
    "f(){ for i in 1; do return 1; done; cd scratch; }; f || cd scratch/deep",
    "i=0; while [ \"$i\" -lt 3 ]; do cd scratch; cd ..; i=$((i+1)); done; [ $i -eq 3 ] && cd scratch",
    "for ((i=0; i<2; i++)); do cd scratch/deep; cd ../..; done; ((i == 2)) && cd scratch",
    "n=3; until [ $n -eq 0 ]; do let n-=1; done; [ $n -eq 0 ] && cd scratch",
    "((1 + 1 == 2)) && cd scratch",
    "x=$(( 2 > 1 )); [ $x = 1 ] && cd scratch",
    "(for i in 1; do break; done; cd scratch)",
    "for i in 1; do (break; cd scratch); cd scratch; done",
    "f(){ local d=scratch; cd \"$d\"; }; f; d=..; cd \"$d\"",
]


@pytest.mark.parametrize("shell", [BASH, ZSH])
@pytest.mark.parametrize("program", LOOPS)
def test_loops_and_jumps_end_where_the_shell_ends(review_area, shell, program):
    proc = sh(shell, program + "; pwd -P", cwd=review_area)
    assert proc.returncode == 0, proc.stderr
    model = audit._shell(program, review_area)
    assert model.known
    assert {w.cwd for w in model.worlds} == {audit.Path(proc.stdout.strip())}, (program, model.worlds)


def test_a_loop_that_keeps_moving_stops_being_followed(review_area):
    model = audit._shell("while [ -n \"$(date)\" ]; do cd scratch; done; cat x", review_area)
    assert not model.known or len({w.cwd for w in model.worlds}) > 1


def test_a_counting_loop_without_a_directory_change_stays_known(review_area):
    model = audit._shell("i=0; while [ $i -lt 1000 ]; do curl -s https://example.org/$i; i=$((i+1)); done; cat notes.md",
                         review_area)
    assert model.known and {w.cwd for w in model.worlds} == {review_area}
    verdict, why = audit.check_call("shell", {"command": "i=0; while [ $i -lt 1000 ]; do i=$((i+1)); done; cat notes.md"},
                                    review_area, audit.protected_roots())
    assert verdict == "local", why


# The directory stack

STACK = [
    "pushd scratch >/dev/null; pushd +1 >/dev/null",
    "pushd scratch >/dev/null; pushd scratch/deep >/dev/null 2>&1; pushd -0 >/dev/null",
    "pushd scratch >/dev/null; pushd >/dev/null",
    "pushd scratch >/dev/null; pushd deep >/dev/null; popd +1 >/dev/null",
    "pushd scratch >/dev/null; pushd deep >/dev/null; popd -0 >/dev/null; popd >/dev/null",
    "pushd scratch >/dev/null; dirs -c; popd >/dev/null 2>&1",
    "pushd gone >/dev/null 2>&1; popd >/dev/null 2>&1",
    "cd scratch; pushd - >/dev/null",
]


@pytest.mark.parametrize("shell", [BASH, ZSH])
@pytest.mark.parametrize("program", STACK)
def test_directory_stack(review_area, shell, program):
    proc = sh(shell, program + "; pwd -P", cwd=review_area)
    model = audit._shell(program, review_area)
    assert audit.Path(proc.stdout.strip().splitlines()[-1]) in {w.cwd for w in model.worlds}, (program, model.worlds)


def test_zsh_cd_from_the_stack(review_area):
    program = "pushd scratch >/dev/null; pushd deep >/dev/null; cd +2"
    proc = sh(ZSH, program + "; pwd -P", cwd=review_area)
    model = audit._shell(f"zsh -f -c {shlex.quote(program + '; cat ../opus-2/draft.json')}", review_area)
    assert audit.Path(proc.stdout.strip()) == review_area
    assert audit.check_call("shell", {"command": f"zsh -c {shlex.quote(program + '; cat ../opus-2/draft.json')}"},
                            review_area, audit.protected_roots())[0] == "violation"
    assert model.known


# What child shells see

@pytest.mark.parametrize("program,moves", [
    ("d=scratch; sh -c 'cd \"$d\"; pwd -P'", False),
    ("export d=scratch; sh -c 'cd \"$d\"; pwd -P'", True),
    ("d=scratch sh -c 'cd \"$d\"; pwd -P'", True),
    ("set -a; d=scratch; sh -c 'cd \"$d\"; pwd -P'", True),
    ("export d=scratch; export -n d; bash -c 'cd \"$d\"; pwd -P'", False),
    ("export d=scratch; env -i sh -c 'cd \"$d\"; pwd -P'", False),
    ("export d=scratch; env -u d sh -c 'cd \"$d\"; pwd -P'", False),
    ("f(){ cd scratch; }; sh -c 'f 2>/dev/null; pwd -P'", False),
    ("f(){ cd scratch; }; export -f f; bash -c 'f; pwd -P'", True),
])
def test_child_shells_see_exported_variables_only(review_area, program, moves):
    proc = sh(BASH, program, cwd=review_area)
    assert (audit.Path(proc.stdout.strip()) == review_area / "scratch") == moves, proc
    read = program.replace("pwd -P", "cat ../../opus-2/draft.json")
    verdict, _ = audit.check_call("shell", {"command": read}, review_area, audit.protected_roots())
    assert (verdict == "violation") == moves, (program, verdict)


# Generated expansion inputs in the MOCK work area. Compare the actual argument vector rather
# than only a final directory: an extra/missing word can change every later loop iteration.

def _assert_expanded_parameters(review_area, program, shell, dialect):
    real = sh(shell, program + "; printf '%s\\0' \"$#\" \"$@\"", cwd=review_area)
    assert real.returncode == 0, (shell, program, real.stderr)
    model = _model(program, review_area, dialect)
    n = model.vars.get("#")
    params = model.vars.get("@", "").split(audit.SPLIT) if n != "0" else []
    assert [n, *params] == real.stdout.split("\0")[:-1], (shell, program, [n, *params], real.stdout)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from(["~+", "~-", "~0", "~1", "~2", "~+0", "~+1", "~+2", "~-0", "~-1", "~-2"]),
       st.sampled_from(["", "/MOCK", "/..", "/../MOCK"]), st.booleans())
def test_directory_tilde_arguments_match_real_shells(review_area, tilde, suffix, in_function):
    setup = "pushd scratch >/dev/null; pushd deep >/dev/null; "
    expansion = f"set -- {tilde}{suffix}"
    # A function gives its positional parameters back, so carry the expanded result in a variable.
    if in_function:
        program = setup + f'f(){{ x={tilde}{suffix}; }}; f; set -- "$x"'
    else:
        program = setup + expansion
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        _assert_expanded_parameters(review_area, program, shell, dialect)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.integers(-3, 3), st.integers(-3, 3), st.sampled_from(["", "MOCK", "scratch/"]),
       st.sampled_from(["", ".txt", "/MOCK"]), st.booleans(), st.booleans())
def test_brace_words_and_loop_lists_match_real_shells(review_area, start, end, prefix, suffix, listing, loop):
    expression = f"{prefix}{{{start},{end}}}{suffix}" if listing else f"{prefix}{{{start}..{end}}}{suffix}"
    program = (f'x=; for d in {expression}; do x="$x|$d"; done; set -- "$x"'
               if loop else f"set -- {expression}")
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        _assert_expanded_parameters(review_area, program, shell, dialect)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.lists(st.sampled_from(["MOCK", "scratch", "a b", "a:b", ""]), max_size=4),
       st.sampled_from(["$a", '"${a[@]}"', "${a[*]}", '"${a[*]}"', "${#a[@]}"]),
       st.sampled_from([None, ":", "", " "]))
def test_array_expansions_match_real_shells(review_area, values, expression, ifs):
    setup = "" if ifs is None else f"IFS={shlex.quote(ifs)}; "
    program = setup + "a=(" + " ".join(map(shlex.quote, values)) + f"); set -- {expression}"
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        _assert_expanded_parameters(review_area, program, shell, dialect)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.lists(st.sampled_from(["", "MOCK", "a b", "a:b", " "]), max_size=4),
       st.sampled_from(["${a[*]}", "${a[@]}", "$a", "$*", "$@", "x${a[*]}y"]),
       st.sampled_from([None, ":", ": ", " :", "\t:", "::", "x", "", " "]), st.booleans())
def test_unquoted_lists_join_then_split_like_real_shells(review_area, values, expression, ifs, wordsplit):
    """Where parameters are split, an unquoted list is joined at IFS's first character and then
    split, so empty elements can become empty fields (IFS=: and ('' MOCK) give two)."""
    setup = ("setopt shwordsplit 2>/dev/null; " if wordsplit else "") + (
        "" if ifs is None else f"IFS={shlex.quote(ifs)}; ")
    listing = " ".join(map(shlex.quote, values))
    program = setup + f"a=({listing}); set -- {listing}; set -- {expression}"
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        _assert_expanded_parameters(review_area, program, shell, dialect)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from([None, "", "MOCK", "scratch"]), st.sampled_from(["=", ":="]),
       st.sampled_from(["MOCK", "scratch", "a b", ""]), st.booleans())
def test_assigning_expansions_preserve_assigned_values(review_area, initial, operator, default, subshell):
    setup = "unset x; " if initial is None else f"x={shlex.quote(initial)}; "
    expansion = ': "${x' + operator + default + '}"'
    body = f"( {expansion} )" if subshell else expansion
    program = setup + body + '; set -- "${x+SET}" "${x-UNSET}"'
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        _assert_expanded_parameters(review_area, program, shell, dialect)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from([None, "", "MOCK"]), st.sampled_from(["?", ":?"]), st.booleans())
def test_failing_parameter_checks_exit_before_later_commands(review_area, initial, operator, subshell):
    setup = "unset x; " if initial is None else f"x={shlex.quote(initial)}; "
    check = ': "${x' + operator + 'MOCK required}"'
    program = setup + (f"( {check} )" if subshell else check) + "; echo MOCK reached"
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        real = sh(shell, program, cwd=review_area)
        model = _model(program, review_area, dialect)
        assert bool(model.worlds) == ("MOCK reached" in real.stdout), (shell, program, model.worlds, real)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from(["local", "typeset", "declare"]), st.sampled_from(["x", "IFS"]),
       st.sampled_from([None, "", ":", "MOCK"]), st.booleans())
def test_unassigned_local_values_match_real_shells(review_area, declaration, name, outer, twice):
    setup = f"unset {name}; " if outer is None else f"{name}={shlex.quote(outer)}; "
    declarations = f"{declaration} {name}; " * (2 if twice else 1)
    program = (setup + f'f(){{ {declarations} result="${{{name}+SET}}|${{{name}-UNSET}}"; }}; f; '
               f'set -- "$result" "${{{name}+SET}}" "${{{name}-UNSET}}"')
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        # zsh typeset/local prints a repeated existing declaration; suppress declaration output.
        _assert_expanded_parameters(review_area, program.replace(f"{declaration} {name};", f"{declaration} {name} >/dev/null;"),
                                    shell, dialect)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from(["local", "typeset", "declare"]), st.sampled_from([None, "", "MOCK"]), st.booleans())
def test_unassigned_top_level_declarations_match_real_shells(review_area, declaration, outer, negate):
    setup = "unset x; " if outer is None else f"x={shlex.quote(outer)}; "
    command = ("! " if negate else "") + f"{declaration} x >/dev/null"
    program = (setup + 'marker=failed; if ' + command + '; then marker=ok; fi; '
               'set -- "$marker" "${x+SET}" "${x-UNSET}"')
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        _assert_expanded_parameters(review_area, program, shell, dialect)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from(["bash", "sh", "zsh"]), st.sampled_from([None, "", ":", " /"]),
       st.sampled_from(["x=MOCK", "export x=MOCK", "x=MOCK; export -n x", "export x=MOCK; unset x",
                        "a=(MOCK scratch); export a"]), st.booleans())
def test_child_shell_startup_resets_ifs_and_filters_environment(review_area, child, ifs, setup, clear):
    parent = "unset IFS; " if ifs is None else f"export IFS={shlex.quote(ifs)}; "
    # A known output from each child can be compared without observing its private variables.
    code = 'echo "${x+SET}|${x-UNSET}|${a+SET}|${a-UNSET}|$IFS"'
    command = f"{'env -i ' if clear else ''}{child} -c {shlex.quote(code)}"
    program = parent + setup + "; " + command
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        real = sh(shell, program, cwd=review_area)
        # zsh has no export -n; its failed command does not clear the export flag.
        model = _model(program, review_area, dialect)
        assert model.output == real.stdout, (shell, program, model.output, real)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from(["bash", "sh", "zsh"]), st.booleans(), st.booleans())
def test_child_shell_initializes_directory_variables_and_stack(review_area, child, clear, changed):
    setup = "pushd scratch >/dev/null; pushd deep >/dev/null; " if changed else ""
    code = 'echo "${OLDPWD+SET}|${OLDPWD-UNSET}|$PWD"'
    program = setup + f"{'env -i ' if clear else ''}{child} -c {shlex.quote(code)}"
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        real = sh(shell, program, cwd=review_area)
        model = _model(program, review_area, dialect)
        assert model.output == real.stdout, (shell, program, model.output, real)
    # Native shells start with one stack entry, so ~1 is unresolved after child startup.
    proc = sh(BASH, setup + f"{child} -c 'echo ~1'", cwd=review_area)
    assert proc.stdout.strip() == "~1" or child == "zsh" and not proc.stdout, proc
    model = _model(setup + f"{child} -c 'echo ~1'", review_area, "posix")
    assert model.notes, (child, model.output)


@pytest.mark.parametrize("child", ["bash", "sh", "zsh"])
@pytest.mark.parametrize("options", ["noglob", "braceexpand:noglob", "hashall:noglob"])
def test_bash_and_sh_import_exported_shellopts(review_area, child, options):
    # env supplies SHELLOPTS because bash's variable is readonly in the parent shell.
    code = "set -- scratch/*; echo \"$#|$*\""
    program = f"env SHELLOPTS={shlex.quote(options)} {child} -c {shlex.quote(code)}"
    for shell, dialect in ((BASH, "posix"), (ZSH, "zsh")):
        real = sh(shell, program, cwd=review_area)
        model = _model(program, review_area, dialect)
        assert model.output == real.stdout, (shell, program, model.output, real)


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from(["set -o noglob", "set -f", "setopt noglob", "setopt NO_GLOB", "set -o no_glob"]),
       st.sampled_from(["", "set +o noglob; ", "unsetopt noglob; "]),
       st.sampled_from(["", "( {option}; ); ", "f(){{ {option}; }}; f; "]))
def test_globbing_option_state_matches_real_shells(review_area, option, reset, scope):
    # Only zsh accepts all setopt spellings; bash's portable controls have their own generated case.
    program = (scope.format(option=option) if scope else option + "; ") + reset + "set -- scratch/*"
    _assert_expanded_parameters(review_area, program, ZSH, "zsh")
    if option in {"set -o noglob", "set -f"} and "unsetopt" not in reset:
        _assert_expanded_parameters(review_area, program, BASH, "posix")


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=FIXTURE_OK)
@given(st.sampled_from(["setopt shwordsplit", "setopt sh_word_split", "setopt SH_WORD_SPLIT",
                        "set -o shwordsplit", "set -o SH_WORD_SPLIT", "emulate sh"]),
       st.sampled_from(["", "unsetopt SH_WORD_SPLIT; "]),
       st.sampled_from(["", "( {option}; ); ", "f(){{ {option}; }}; f; "]))
def test_zsh_field_splitting_option_state_matches_real_shell(review_area, option, reset, scope):
    program = (scope.format(option=option) if scope else option + "; ") + reset + "x='MOCK scratch'; set -- $x"
    _assert_expanded_parameters(review_area, program, ZSH, "zsh")


# Attached option values and interpreter data

@pytest.mark.parametrize("command,verdict", [
    ("python3 -uc'print(open(\"../opus-2/draft.json\").read())'", "violation"),
    ("python3 -Wignore -c 'print(1)'", "local"),
    ("node -pe 'require(\"fs\").readFileSync(\"../opus-2/draft.json\", \"utf8\")'", "violation"),
    ("perl -lne 'print' ../opus-2/draft.json", "violation"),
    ("perl -i.bak -pe 's/a/b/' notes.txt", "local"),
    ("awk -F: -vOFS=, '{print $1, $2}' notes.txt", "local"),
    ("awk -v p=../opus-2/draft.json 'BEGIN { print p }'", "local"),
    ("awk -v p=../opus-2/draft.json 'BEGIN { while ((getline l < p) > 0) print l }'", "violation"),
    ("jq -n '$ARGS.positional' --args ../opus-2/draft.json /foie", "local"),
    ("jq -n --arg p ../opus-2/draft.json '$p'", "local"),
    ("jq . ../opus-2/draft.json", "violation"),
    ("jq -n --rawfile p ../opus-2/draft.json '$p'", "violation"),
    ("sed -n -e'/x/p' -e'r ../opus-2/draft.json' notes.txt", "violation"),
    ("env -iC.. cat opus-2/draft.json", "violation"),
    ("nice -n10 cat ../opus-2/draft.json", "violation"),
    ("xargs -I{} cat {} <<< ../opus-2/draft.json", "violation"),
    ("timeout -k5 10 curl -s https://example.org", "web"),
])
def test_interpreter_and_wrapper_options(review_area, command, verdict):
    got, why = audit.check_call("shell", {"command": command}, review_area, audit.protected_roots())
    assert got == verdict, (command, got, why)


# $PWD from every place

def test_pwd_expands_from_every_possible_place(review_area):
    # zsh runs the last pipeline stage in this shell, bash does not; the audit cannot tell which.
    got, _ = audit.check_call("shell", {"command": 'true | cd scratch; cat "$PWD/../../opus-2/draft.json"'},
                              review_area, audit.protected_roots())
    assert got == "violation"
    # From an alternative place only (a cd to a directory missing at audit time that may have failed).
    got, why = audit.check_call("shell", {"command": 'cd gone; cat "$PWD/../opus-2/draft.json"'},
                                review_area, audit.protected_roots())
    assert got in {"suspect", "violation"}, why


# Scripts written in one call and run in another

def _claude_transcript(tmp_path, calls):
    path = tmp_path / "transcript.jsonl"
    lines = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": i}]}}
             for n, i in calls]
    path.write_text("\n".join(map(json.dumps, lines)) + "\n")
    return path


@pytest.mark.parametrize("run", ["bash s.sh", "sh ./s.sh", ". ./s.sh", "source s.sh", "chmod +x s.sh; ./s.sh"])
def test_a_script_written_by_one_call_and_run_by_another(tmp_path, review_area, run):
    write = ("Write", {"file_path": str(review_area / "s.sh"), "content": "cd ..\ncat opus-2/draft.json\n"})
    report = audit.audit_transcript(_claude_transcript(tmp_path, [write, ("Bash", {"command": run})]), str(review_area))
    assert not report["passed"], report


def test_a_script_written_by_a_heredoc_and_run_later(tmp_path, review_area):
    calls = [("Bash", {"command": "cat > fetch.py <<'EOF'\nprint(open('../opus-2/draft.json').read())\nEOF"}),
             ("Bash", {"command": "python3 fetch.py"})]
    report = audit.audit_transcript(_claude_transcript(tmp_path, calls), str(review_area))
    assert not report["passed"], report


def test_a_script_on_disk_is_read_when_the_transcript_lacks_it(tmp_path, review_area):
    # Codex reports apply_patch edits without their text: the file in the work directory is read.
    (review_area / "probe.sh").write_text("cat ../opus-2/draft.json\n")
    report = audit.audit_transcript(_claude_transcript(tmp_path, [("Bash", {"command": "bash probe.sh"})]),
                                    str(review_area))
    assert not report["passed"], report


def test_an_honest_script_stays_local(tmp_path, review_area):
    calls = [("Write", {"file_path": str(review_area / "fetch.sh"),
                        "content": "curl -s https://example.org > page.html\nwc -l page.html\n"}),
             ("Bash", {"command": "bash fetch.sh"})]
    report = audit.audit_transcript(_claude_transcript(tmp_path, calls), str(review_area))
    assert report["passed"] and not report["suspect"], report


# Codex web_search items that open a page

def test_codex_open_page_url_is_checked():
    line = {"type": "item.completed", "item": {"type": "web_search", "query": "",
                                               "action": {"type": "open_page",
                                                          "url": "https://github.com/MaxGhenis/dc-i86-llm-forecast"}}}
    calls = list(audit._tool_calls(line))
    assert calls == [("web_search", {"query": "", "url": "https://github.com/MaxGhenis/dc-i86-llm-forecast"})]
    verdict, _ = audit.check_call(*calls[0], audit.Path("/nonexistent"), [])
    assert verdict == "suspect"  # MOCK event: this project's own repository, opened on the web


# A path that starts with two slashes, which macOS reads as one

@pytest.mark.parametrize("command", [
    "cat /{other}", "cat //{other_rel}", "cd /; cd \"$PWD/..\"; cat {other_rel}", "cd //; cat {other_rel}",
    "cat //{protected_rel}", "ls //{other_dir_rel}",
])
def test_leading_double_slash_is_root(review_area, command):
    other = review_area.parent / "opus-2" / "draft.json"
    protected = audit.protected_roots()[0] / "draft.json"
    command = command.format(other=other, other_rel=str(other)[1:], protected_rel=str(protected)[1:],
                             other_dir_rel=str(other.parent)[1:])
    assert "MOCK OTHER ANSWER" in sh(BASH, command, cwd=review_area).stdout or command.startswith("ls")
    assert audit.check_call("shell", {"command": command}, review_area, audit.protected_roots())[0] == "violation", command
