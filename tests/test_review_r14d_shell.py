"""Round-14d shell findings, measured on real shells in temporary MOCK layouts.

Every non-control parameter fails against d0b83c8. The finding-1 and finding-2 regression
parameters also pass against 19d1303; pre-existing conservative alternatives are labelled controls.
"""

import shlex
import subprocess
import tempfile
from pathlib import Path

import pytest

from i86 import audit
from test_audit_output_differential import matches
from test_audit_readonly import SHELL_RUNS, flagged, layout
from test_review_r13_shell import model_in

R = "cat ../opus-2/draft.json"  # another run's MOCK answer


def _r14d_scope(program, scope):
    if scope == "eval":
        return "eval " + shlex.quote(program)
    if scope == "subshell":
        return "( " + program + "\n)"
    if scope == "function":
        return "f() { " + program + "\n}; f"
    return program


LAST_STAGE_HEREDOC = [
    (f"{verb}-{scope}-{fd or 'stdin'}", name,
     _r14d_scope(f"! {verb} | {verb} {fd}<<E {op} {R}{tail}\nMOCK-body\nE", scope))
    for name in SHELL_RUNS
    for verb, op, tail, scope, fd in [
        ("true", "||", "", "plain", ""),
        ("false", "&&", " || echo MOCK-or", "plain", ""),
        ("true", "||", "", "plain", "3"),
        ("true", "||", "", "eval", ""),
        ("false", "&&", " || echo MOCK-or", "subshell", ""),
        ("true", "||", "", "function", ""),
    ]
]


@pytest.mark.parametrize("case,name,program", LAST_STAGE_HEREDOC,
                         ids=[f"{r[1]}-{r[0]}" for r in LAST_STAGE_HEREDOC])
def test_finding3_last_stage_heredoc_waits_for_pipeline_negation(case, name, program):
    read, flag, detail = flagged(program, name)
    assert read, ("measurement", case, name, detail)
    assert flag, (case, name, detail)
    real, model = model_in(name, program)
    assert real == "MOCK OTHER ANSWER\n", ("measurement", name, case, real)
    assert model is None or matches(real, model), (case, name, real, model)


COMMAND_BUILTIN_PREFIX = [
    (("control-" if name != "sh" else "") + case, name, program)
    for name in SHELL_RUNS
    for case, program in [
        ("plain", "y=MOCK command builtin eval ':'"),
        ("posixbuiltins", "setopt posixbuiltins; y=MOCK command builtin eval ':'"),
        ("nested-builtin", "y=MOCK command builtin builtin eval ':'"),
        ("eval", "eval \"y=MOCK command builtin eval ':'\""),
        ("subshell", "( y=MOCK command builtin eval ':'; "
         'echo "MOCK-${y-unset}"; [ "${y-unset}" = MOCK ] && ' + R + " )"),
        ("function", "f() { y=MOCK command builtin eval ':'; "
         'echo "MOCK-${y-unset}"; [ "${y-unset}" = MOCK ] && ' + R + "; }; f"),
    ]
]


@pytest.mark.parametrize("case,name,prefix", COMMAND_BUILTIN_PREFIX,
                         ids=[f"{r[1]}-{r[0]}" for r in COMMAND_BUILTIN_PREFIX])
def test_finding6_command_builtin_keeps_sh_special_prefix(case, name, prefix):
    scoped = case.removeprefix("control-") in {"subshell", "function"}
    program = prefix if scoped else prefix + '; [ "${y-unset}" = MOCK ] && ' + R
    read, flag, detail = flagged(program, name)
    assert read == (name == "sh"), ("measurement", case, name, detail)
    assert not read or flag, (case, name, detail)
    real, model = model_in(name, prefix if scoped else prefix + '; echo "MOCK-${y-unset}"')
    expected = "MOCK-MOCK\n" if name == "sh" else "MOCK-unset\n"
    if scoped and name == "sh":
        expected += "MOCK OTHER ANSWER\n"
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, model)


# Findings 2, 5 and 7: all test programs and temporary answer data are MOCK.
MODIFIER_SHELLS = ("bash", "sh", "dash", "zsh")
MAYBE_NOGLOB_OUTPUTS = [
    ("grep", 'grep MOCK /dev/null >/dev/null && noglob() { :; }; '
     "eval 'noglob < /dev/null; echo MOCK-inner' 2>/dev/null; echo MOCK-after"),
    ("condition", '[ -n "$X" ] && noglob() { :; }; '
     "eval 'noglob < /dev/null; echo MOCK-inner' 2>/dev/null; echo MOCK-after"),
    ("function", 'grep MOCK /dev/null >/dev/null && noglob() { :; }; '
     "f() { eval 'noglob < /dev/null; echo MOCK-inner' 2>/dev/null; }; f; echo MOCK-after"),
    ("subshell", 'grep MOCK /dev/null >/dev/null && noglob() { :; }; '
     "( eval 'noglob < /dev/null; echo MOCK-inner' 2>/dev/null; echo MOCK-after )"),
]


def _modifier_rows(programs):
    # The other shells already cover these programs: explicitly labelled controls.
    return [pytest.param(case, name, program, id=("control-" if name != "zsh" else "") + case + "-" + name)
            for case, program in programs for name in MODIFIER_SHELLS]


@pytest.mark.parametrize("case,name,program", _modifier_rows(MAYBE_NOGLOB_OUTPUTS))
def test_maybe_undefined_modifier_function_keeps_the_error_branch(case, name, program):
    """2: undefined and defined alternatives must both reach the pre-redirection modifier check."""
    real, model = model_in(name, program)
    expected = "MOCK-after\n" if name == "zsh" else "MOCK-inner\nMOCK-after\n"
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


BUILTIN_NOGLOB_READS = [
    ("plain", 'noglob() { p=MOCK; }; builtin noglob noglob :; [ "${p-unset}" = MOCK ] && ' + R),
    ("eval", 'noglob() { p=MOCK; }; eval \'builtin noglob noglob :\'; [ "${p-unset}" = MOCK ] && ' + R),
    ("function", 'noglob() { p=MOCK; }; f() { builtin noglob noglob :; }; f; [ "${p-unset}" = MOCK ] && ' + R),
    ("subshell", 'noglob() { p=MOCK; }; ( builtin noglob noglob :; [ "${p-unset}" = MOCK ] && ' + R + ' )'),
]


@pytest.mark.parametrize("case,name,program", _modifier_rows(BUILTIN_NOGLOB_READS))
def test_builtin_selects_only_its_immediate_modifier_word(case, name, program):
    """5: the second noglob retains ordinary function lookup, including nested callers."""
    read, flag, detail = flagged(program, name)
    assert read == (name == "zsh"), ("measurement", case, name, detail)
    assert not read or flag, (case, name, detail)


@pytest.mark.parametrize("case,name,program", _modifier_rows(BUILTIN_NOGLOB_READS))
def test_builtin_modifier_function_assignment_output(case, name, program):
    """5: use output to check the function's variable effect directly."""
    program = program.replace('[ "${p-unset}" = MOCK ] && ' + R, 'echo "MOCK-${p-unset}"')
    real, model = model_in(name, program)
    expected = "MOCK-MOCK\n" if name == "zsh" else "MOCK-unset\n"
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


VANISHED_NOCORRECT_READS = [
    ("plain", 'empty=; $empty nocorrect eval \'p=MOCK\'; [ "${p-unset}" = unset ] && ' + R),
    ("eval", 'empty=; eval \'$empty nocorrect eval "p=MOCK"\'; [ "${p-unset}" = unset ] && ' + R),
    ("function", 'empty=; f() { $empty nocorrect eval \'p=MOCK\'; }; f; [ "${p-unset}" = unset ] && ' + R),
    ("subshell", 'empty=; ( $empty nocorrect eval \'p=MOCK\'; [ "${p-unset}" = unset ] && ' + R + ' )'),
]


@pytest.mark.parametrize("case,name,program", _modifier_rows(VANISHED_NOCORRECT_READS))
def test_vanished_leading_word_does_not_promote_nocorrect(case, name, program):
    """7: reserved-word recognition precedes the first word's empty expansion."""
    read, flag, detail = flagged(program, name)
    assert read, ("measurement", case, name, detail)
    assert flag, (case, name, detail)


@pytest.mark.parametrize("case,name,program", _modifier_rows(VANISHED_NOCORRECT_READS))
def test_vanished_leading_word_nocorrect_output(case, name, program):
    """7: no shell executes the inner eval after an ordinary nocorrect command."""
    program = program.replace("'p=MOCK'", "'echo MOCK-inner'").replace('"p=MOCK"', '"echo MOCK-inner"')
    program = program.replace('[ "${p-unset}" = unset ] && ' + R, 'echo MOCK-after')
    real, model = model_in(name, program)
    assert real == "MOCK-after\n", ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


# Findings 1 and 4: redirections and temporary MOCK answers.
_R14D_SUBSTITUTION_PROGRAMS = [
    ("missing", 'true < "$(true < /dev/null/MOCK-missing; echo /dev/null)" || ' + R),
    ("noclobber", 'echo MOCK-old > f; true < "$(set -C; true > f; echo /dev/null)" || ' + R),
    ("function", 'f() { true < /dev/null/MOCK-missing; echo /dev/null; }; true < "$(f)" || ' + R),
    ("eval", 'true < "$(eval \'true < /dev/null/MOCK-missing; echo /dev/null\')" || ' + R),
    ("nested-subshell", 'true < "$( ( true < /dev/null/MOCK-missing; echo /dev/null ) )" || ' + R),
]
_R14D_SUBSTITUTIONS = [
    (("control-" if name in {"bash", "zsh"} else "prior-defect-" if name == "dash" else "regression-")
     + case + "-" + name, name, program)
    for case, program in _R14D_SUBSTITUTION_PROGRAMS for name in SHELL_RUNS
]


@pytest.mark.parametrize("case,name,program", _R14D_SUBSTITUTIONS,
                         ids=[row[0] for row in _R14D_SUBSTITUTIONS])
def test_substitution_open_failures_do_not_fail_the_parent(case, name, program):
    """1: all four real shells print nothing and leave the MOCK answer unread."""
    read, flag, seen = flagged(program, name)
    assert not read, ("measurement", case, name, seen)
    # 19d1303 leaves noclobber unknown and suspects it; the regression is the invented read.
    assert not flag or "noclobber" in case, (case, name, seen)
    with tempfile.TemporaryDirectory() as tmp:
        work = layout(Path(tmp).resolve())
        shell = SHELL_RUNS[name]
        command = " ".join([*map(shlex.quote, shell[:-1]), "-c", shlex.quote(program)])
        modeled = audit._shell(command, work)
        answer = work.parent / "opus-2" / "draft.json"
        assert answer not in [*modeled.paths, *modeled.alt_paths], (case, name, modeled.paths)
    real, model = model_in(name, program)
    assert real == "", ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


_R14D_CLOSED_PROGRAMS = [
    ("stderr", "true 2>&- <&2"),
    ("stdin", "true 0<&- 2>&0"),
    ("stdout", "true 1>&- 0<&1"),
    ("function", "f() { :; }; f 2>&- <&2"),
    ("eval", "eval 'true 2>&- <&2'"),
    ("group-inherited-close", "{ true <&2; } 2>&-"),
    ("function-inherited-close", "f() { true <&2; }; f 2>&-"),
    ("eval-inherited-close", "eval 'true <&2' 2>&-"),
    # A subshell's previously unknown status already kept the failing branch possible.
    ("control-subshell", "( true 2>&- <&2 )"),
]
_R14D_CLOSED_READS = [
    (case + "-" + name, name, program + " || " + R)
    for case, program in _R14D_CLOSED_PROGRAMS for name in SHELL_RUNS
]


@pytest.mark.parametrize("case,name,program", _R14D_CLOSED_READS,
                         ids=[row[0] for row in _R14D_CLOSED_READS])
def test_an_explicitly_closed_standard_descriptor_cannot_be_duplicated(case, name, program):
    """4: measured failures run the continuation and print the other run's MOCK answer."""
    read, flag, seen = flagged(program, name)
    assert read, ("measurement", case, name, seen)
    assert flag, (case, name, seen)
    real, model = model_in(name, program)
    assert real == "MOCK OTHER ANSWER\n", ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


_R14D_CLOSED_STATUSES = [
    (case + "-" + name, name, "cd scratch; " + program)
    for case, program in _R14D_CLOSED_PROGRAMS if not case.startswith("control-")
    for name in SHELL_RUNS
]


@pytest.mark.parametrize("case,name,program", _R14D_CLOSED_STATUSES,
                         ids=[row[0] for row in _R14D_CLOSED_STATUSES])
def test_a_closed_descriptor_duplication_keeps_the_measured_failing_status(case, name, program):
    """4: a failed call cannot make its final directory the only possible next start."""
    with tempfile.TemporaryDirectory() as tmp:
        top = Path(tmp).resolve()
        work = layout(top)
        proc = subprocess.run([*SHELL_RUNS[name], program], cwd=work,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work)},
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        assert proc.returncode == (2 if name == "dash" else 1), ("measurement", case, name, proc)
        model = audit._Shell(work)
        model.shell_name = name
        model.dialect = "zsh" if name == "zsh" else "posix"
        model.posix = name == "sh"
        model.run(program)
        assert model.worlds and all(w.cwd == work / "scratch" for w in model.worlds), (case, model.worlds)
        assert any(w.status in {audit.FAILED, audit.MAYBE} for w in model.worlds), (case, name, model.worlds)


@pytest.mark.parametrize("name", SHELL_RUNS)
def test_control_reopening_a_closed_descriptor_allows_duplication(name):
    """4 control: a later successful open replaces the explicit close in every shell."""
    program = "true 2>&- 2>/dev/null <&2 || " + R
    read, flag, seen = flagged(program, name)
    assert not read and not flag, ("measurement/control", name, seen)
    real, model = model_in(name, program)
    assert real == "", ("measurement", name, real)
    assert model is None or matches(real, model), (name, real, audit._choices(model))


@pytest.mark.parametrize("name", SHELL_RUNS)
def test_control_heredoc_continuation_restores_the_previous_descriptors(name):
    """4 control: the close belongs only to the command preceding the here-document's &&."""
    program = "true 2>&- <<E && true <&2 || " + R + "\nMOCK-body\nE"
    read, flag, seen = flagged(program, name)
    assert not read and not flag, ("measurement/control", name, seen)
    real, model = model_in(name, program)
    assert real == "", ("measurement", name, real)
    assert model is None or matches(real, model), (name, real, audit._choices(model))


_R14D_REOPEN_CONTROLS = [
    ("pipe-stdin", 'f() { true <&0; }; { echo MOCK | f; } 0<&-; echo MOCK-after', "MOCK-after\n"),
    ("substitution-stdout", '{ p=$(true <&1 && echo MOCK); } 1>&-; echo "MOCK-${p-unset}"',
     "MOCK-MOCK\n"),
]


@pytest.mark.parametrize("case,program,expected", _R14D_REOPEN_CONTROLS,
                         ids=[row[0] for row in _R14D_REOPEN_CONTROLS])
@pytest.mark.parametrize("name", SHELL_RUNS)
def test_control_pipe_descriptors_replace_inherited_closes(case, program, expected, name):
    """4 controls: a pipe's new endpoints replace descriptors closed by an outer command."""
    real, model = model_in(name, program)
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))
    with tempfile.TemporaryDirectory() as tmp:
        work = layout(Path(tmp).resolve())
        direct = audit._Shell(work)
        direct.shell_name = name
        direct.dialect = "zsh" if name == "zsh" else "posix"
        direct.posix = name == "sh"
        direct.run(program)
        assert direct.open_failures == 0, (case, name, direct.open_failures)
