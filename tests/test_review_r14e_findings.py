"""Round-14e findings (Opus 5.5, of d0b83c8: ~/reviews/dc-i86-llm-forecast/round14/
FINDINGS-r14e.out.md), with the reviewer's reproductions, and the other places this round found a
quick call evaluating arithmetic or expanding a pattern. Each test fails on d0b83c8's source unless
it is labelled a control; a control records what the real shells do, or what the parent did. All
transcripts, files and forecasts are MOCK, in a temporary MOCK work area (runners.WORK
monkeypatched)."""

import subprocess

import numpy as np
import pytest
from test_review_r13_inputs import area, audit_lines  # noqa: F401 (area is a fixture)
from test_review_r13b_audit import OTHER, bash, records

from i86 import audit, dists
from i86.audit import _may_outlast

SHELLS = {"bash": ["/bin/bash", "--norc", "--noprofile", "-c"], "sh": ["/bin/sh", "-c"],
          "zsh": ["/bin/zsh", "-f", "-c"], "dash": ["/bin/dash", "-c"]}
WIDE = "300000000"


def raw(event, ident, command=f"cat {OTHER}"):
    return ('{"type": "%s", "item": {"id": %s, "type": "command_execution", "command": "%s"}}'
            % (event, ident, command))


# --- F1: a backslash in an unquoted word hides printf's options or its width ----------------------
# Each case: the printf call with `{w}` for the width, the probe that prints what the call stored
# (if it stores into a variable), and the shells that read the wide format there.
ESCAPED = [
    pytest.param("printf \\-\\- '[%{w}s]' x", "", {"bash", "sh", "zsh", "dash"}, id="backslash-dashes"),
    pytest.param("printf -\\- '[%{w}s]' x", "", {"bash", "sh", "zsh", "dash"}, id="dash-backslash-dash"),
    pytest.param("printf \\-vMOCK '[%{w}s]' x", '; printf %s "$MOCK"', {"bash", "sh"}, id="backslash-vNAME"),
    pytest.param("printf \\-v MOCK '[%{w}s]' x", '; printf %s "$MOCK"', {"bash", "sh", "zsh"}, id="backslash-v-NAME"),
    pytest.param("printf %\\{w}s. x", "", {"bash", "sh", "zsh", "dash"}, id="backslash-in-the-width"),
    # zsh takes an argument whose letters are all its printf's options (`-vv`: -v v) as an option,
    # and the next one holding any other letter as the format; bash rejects this call at once.
    pytest.param("printf -vv '-v[%{w}s]' x", '; printf %s "$v"', {"zsh"}, id="zsh-attached-vv"),
]


@pytest.mark.parametrize("call, probe, readers", ESCAPED)
def test_control_the_shells_read_the_width(call, probe, readers, tmp_path):
    """A labelled control: with a width of 5, the shells in `readers` print `    x` (the escaped
    word's value is an option or the width), and no other shell does."""
    for name, argv in SHELLS.items():
        out = subprocess.run([*argv, call.format(w=5) + probe], cwd=tmp_path, capture_output=True, text=True,
                             timeout=60, stdin=subprocess.DEVNULL).stdout
        assert ("    x" in out) == (name in readers), (name, out)


@pytest.mark.parametrize("call, probe, readers", ESCAPED)
def test_an_escaped_printf_option_or_width_may_outlast_its_timeout(area, tmp_path, call, probe, readers):
    """`_may_outlast` should take each call as one that may outlast a 1,000 ms timeout (measured
    here, under `eval CMD && pwd -P`: `cd /tmp; printf \\-\\- '%100000000s' x x x x > /dev/null`
    took 42 s on bash and 21 s on zsh; `printf -vv '-v%100000000s' x x x x` took 3 s on zsh), so
    that the next call holds where this one started."""
    call = call.format(w=WIDE)
    assert audit._may_outlast(call, 1000)
    out = audit_lines(area, tmp_path, [bash(f"cd MOCK-sub; {call}", timeout=1000), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


# --- F2: other quick calls that run past a second ------------------------------------------------

DOUBLING = "x0=1; " + "; ".join(f"x{k}='x{k - 1}+x{k - 1}'" for k in range(1, 21))


@pytest.mark.parametrize("call", [
    pytest.param(f"{DOUBLING}; echo $((x20))", id="arithmetic-2^20"),  # 9 s on bash, 24 s on zsh here
    pytest.param(f"{DOUBLING}; let 'y = x20'", id="let-2^20"),
    pytest.param("echo /usr/share/**/* > /dev/null", id="zsh-recursive-glob"),  # past 100 s on zsh here
])
def test_a_quick_builtin_call_that_runs_on_may_outlast_its_timeout(area, tmp_path, call):
    assert audit._may_outlast(call, 1000)
    out = audit_lines(area, tmp_path, [bash(f"cd MOCK-sub; {call}", timeout=1000), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


# --- F3: an id nested deeper than _id_key recurses -----------------------------------------------

def nested(depth):
    return "[" * depth + "1" + "]" * depth


def test_control_a_nested_id_within_the_recursion_limit(area, tmp_path):
    """A labelled control: at depth 450 the item is one call, and its read a violation."""
    out = audit_lines(area, tmp_path, [raw("item.started", nested(450)), raw("item.completed", nested(450))])
    assert out["tool_calls"] == 1 and out["violations"] and not out["suspect"], out


@pytest.mark.parametrize("depth", [600, 2000])
def test_a_deeply_nested_id_is_still_one_audited_call(area, tmp_path, depth):
    """On d665c85 (json.dumps of the id) both depths gave one call and a violation; on d0b83c8 both
    lines are suspect ("cannot follow (RecursionError)"), no call is counted and the read of another
    run's answer is no violation."""
    out = audit_lines(area, tmp_path, [raw("item.started", nested(depth)), raw("item.completed", nested(depth))])
    assert out["tool_calls"] == 1 and out["violations"], out


# --- F4: lines -----------------------------------------------------------------------------------

def test_a_list_line_holding_a_bash_call_loses_the_next_start(area, tmp_path):
    """The commit's invariant: a list line loses the next Bash start. After `cd MOCK-sub`, a list
    whose last part is `cd <work>/MOCK-sub` leaves the next call in MOCK-sub, so the read of
    `../opus-2/draft.json` is only suspect; with `[]` there it is a violation (test_review_r14c_audit)."""
    lst = '[{"type": "turn.started"}, %s]' % __import__("json").dumps(bash(f"cd {area}/MOCK-sub"))
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub"), lst, bash(f"cat {OTHER}")])
    assert any(OTHER in r["call"] for r in out["violations"]), records(out)


@pytest.mark.parametrize("line", [" ", "　", "\x0b", "\x1c", " "])
def test_a_line_of_other_whitespace_is_suspect(area, tmp_path, line):
    """The commit's invariant: no transcript line is skipped; json.loads rejects each of these."""
    out = audit_lines(area, tmp_path, [{"type": "turn.started"}, line])
    assert out["suspect"], out


# --- Tilt: the zeros a _Tilt has inside a segment are lone floats --------------------------------

def test_control_a_categorical_tilt_has_one_zero_float_near_sol_case():
    """A labelled control: in round-14c's MOCK case the computed tilt is 0 at 55.25% alone within
    200,000 floats either side, so `_off_zero` moves a draw there within NARROW_FLOATS floats (its
    nearest-float branch), never by bisection."""
    from test_review_r14c_tilt import _sol_case
    _, _, _, tilt = _sol_case()
    centre = int(dists._positions(np.array([0.5525]))[0])
    pos = np.arange(centre - 200_000, centre + 200_001, dtype=np.int64)
    zeros = pos[~(np.asarray(tilt(dists._at(pos)), dtype=float) > 0)] - centre
    assert zeros.tolist() == [0]


def test_control_off_zero_by_bisection_is_not_the_nearest():
    """A labelled control (the docstrings' "nearest" holds only for the near branch): a MOCK tilt 0
    on (0.54, 0.55 + 1e-9] and 1 elsewhere, with the anchor below, moves 0.55 to 0.54, 0.01 away,
    though a positive float lies 1e-9 above."""
    gap = 0.55 + 1e-9
    tilt = lambda v: np.where((np.asarray(v) > 0.54) & (np.asarray(v) <= gap), 0.0, 1.0)  # noqa: E731
    assert dists._off_zero(0.55, 0.5, 0.6, 0.52, tilt) == 0.54
    assert dists._off_zero(0.55, 0.5, 0.6, 0.58, tilt) == float(np.nextafter(gap, 1.0))


# --- This round's: other places a quick call evaluates arithmetic or expands a pattern -----------

EXPRESSION = "x0=1; x1='x0+x0+x0'; "  # x1 holds an expression worth 3
EVALUATES = [  # the call, and the shells that print 3: they evaluated x1 as an expression
    pytest.param("printf '%d' x1", {"zsh"}, id="zsh-printf-numeric"),
    pytest.param("set -- a b c d e f; shift x1; echo $#", {"zsh"}, id="zsh-shift"),
    pytest.param("f() { return x1; }; f; echo $?", {"zsh"}, id="zsh-return"),
    pytest.param("(exit x1); echo $?", {"zsh"}, id="zsh-exit"),
    pytest.param("export -i e=x1 2>/dev/null; echo $e", {"zsh"}, id="zsh-export-i"),
    pytest.param("readonly -i r=x1 2>/dev/null; echo $r", {"zsh"}, id="zsh-readonly-i"),
    pytest.param("typeset -i y=x1; echo $y", {"bash", "sh", "zsh"}, id="typeset-i"),
    pytest.param("[[ x1 -eq 3 ]] && echo 3", {"bash", "sh", "zsh"}, id="double-bracket-eq"),
    pytest.param("a=(9 9 3 3 9); echo ${a[x1]}", {"bash", "sh", "zsh"}, id="subscript"),
    pytest.param("s=0123456; echo ${s:x1:1}", {"bash", "sh"}, id="offset"),
    pytest.param('a=(9 9 3 9); echo "$a[x1]"', {"zsh"}, id="zsh-subscript-in-quotes"),
]


@pytest.mark.parametrize("call, readers", EVALUATES)
def test_control_the_shells_evaluate_the_expression(call, readers, tmp_path):
    """A labelled control: the shells in `readers` print 3, and no other shell does (`[` and test
    reject `x1 -eq 3`, and bash, sh and dash reject `shift x1`, `return x1` and `exit x1`)."""
    for name, argv in SHELLS.items():
        out = subprocess.run([*argv, EXPRESSION + call], cwd=tmp_path, capture_output=True, text=True,
                             timeout=60, stdin=subprocess.DEVNULL).stdout.split()
        assert (out[-1:] == ["3"]) == (name in readers), (name, out)


@pytest.mark.parametrize("call, readers", [  # the function in zsh-return made it slow on d0b83c8 already
    pytest.param(*p.values, id=("control-" if p.id == "zsh-return" else "") + p.id) for p in EVALUATES])
def test_arithmetic_on_a_variable_may_outlast_its_timeout(area, tmp_path, call, readers):
    """With x20 built by doubling in place of x1, each evaluates 2^20 terms (round 14e measured 9 s
    and 24 s for `$((x20))`): `_may_outlast` takes each as slow, so the next start holds the first."""
    assert _may_outlast(EXPRESSION + call, 1000)
    out = audit_lines(area, tmp_path, [bash(f"cd MOCK-sub; {EXPRESSION}{call}", timeout=1000), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


def test_control_an_unquoted_expansion_expands_its_pattern(tmp_path):
    """A labelled control: bash, sh and dash expand the pattern a variable holds (`/*` gives more
    than one word); zsh does not without GLOB_SUBST."""
    for name, argv in SHELLS.items():
        out = subprocess.run([*argv, "x='/*'; echo $x"], cwd=tmp_path, capture_output=True, text=True,
                             timeout=60, stdin=subprocess.DEVNULL).stdout.split()
        assert (len(out) > 1) == (name != "zsh"), (name, out)


@pytest.mark.parametrize("call", [
    "x='/*/*/*'; echo $x > /dev/null",  # bash, sh and dash expand the pattern the value holds
    "cd $MOCK_DIR",  # a value from the environment may hold a pattern too
    "echo $(echo '/*/*/*') > /dev/null",
    "echo ${MOCK:-/*/*/*} > /dev/null",
    "echo /*/*/* > /dev/null", "echo /[a-z]*/* > /dev/null", "echo /?sr/* > /dev/null",
    "setopt extendedglob; echo /^x/* > /dev/null",
    "[[ $MOCK == $MOCK_PATTERN ]]",  # an unquoted right side is a pattern
    "echo $((3**4000000000)) > /dev/null",  # 3.8 s on bash and 4.6 s on zsh here
    "PS4='$((x1))'; set -x; :", "set -x; :", "setopt xtrace; :", "set -o xtrace; :", "unsetopt noxtrace; :",
    "typeset \\-Z300000000 MOCK=1",  # a backslash hid zsh's padding option, as F1 hid printf's
    "typeset $MOCK_OPTION MOCK=1",
    "unset 'a[x20]'", "printf -v 'a[x20]' %s MOCK", "[[ -v 'a[x20]' ]]",
])
def test_a_pattern_or_option_a_quick_call_expands_may_outlast_its_timeout(area, tmp_path, call):
    assert _may_outlast(call, 1000)
    out = audit_lines(area, tmp_path, [bash(f"cd MOCK-sub; {call}", timeout=1000), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


@pytest.mark.parametrize("call", [
    "cd .", "[ -n MOCK ]", "[ MOCK -eq 1 ] 2>/dev/null; true", "echo MOCK > /dev/null",
    "printf '%s\\n' MOCK > /dev/null", "printf '%d\\n' 5 > /dev/null", "printf -q '%9s' > /dev/null 2>&1; true",
    'x=$(pwd); echo "$x" > /dev/null', "local_x=*; true", "export MOCK=$MOCK_VALUE", "cd ~ && cd -",
    "echo $((1 + 2)) $? $# ${#MOCK} > /dev/null", "(( 3 > 2 ))", "[[ 1 -eq 1 ]]", 'echo "${a[@]}" "${a[1]}" > /dev/null',
    "unset MOCK", "set -e", "set -euo pipefail; set +x", "exit 0",
])
def test_control_a_quick_call_stays_quick(area, tmp_path, call):
    """Labelled controls: calls of quick builtins with no arithmetic on a name, no pattern and no
    width stay quick, so the next call starts where this one ended (an exit keeps the start)."""
    assert not _may_outlast(call, 1000)
    out = audit_lines(area, tmp_path, [bash(f"cd MOCK-sub; {call}", timeout=1000), bash(f"cat {OTHER}")])
    if call == "exit 0":
        assert out["violations"], records(out)
    else:
        assert not out["violations"] and out["passed"], records(out)
