"""Round-14b shell review regressions measured on the four real shells. All data is MOCK."""

import os
import shlex
import signal
import subprocess
import tempfile
from pathlib import Path

import pytest

from i86 import audit
from test_audit_output_differential import matches
from test_audit_readonly import SHELL_RUNS, flagged
from test_audit_shell_differential import layout
from test_review_r13_shell import model_in

R = "cat ../opus-2/draft.json"  # another run's MOCK answer

# Finding 1: a here-document's &&/|| continuation tests the negated status.
NEGATED_HEREDOC = [
    (f'{verb}-{scope}-{fd}', name,
     (lambda p: p if scope == 'plain' else 'eval ' + shlex.quote(p) if scope == 'eval' else
      '( ' + p + '\n)' if scope == 'subshell' else p.replace('! ' + verb, '! { ' + verb + '; }', 1) if scope == 'group' else 'f() { ' + p + '\n}; f')
     (f'! {verb} {fd}<<E {op} {R}\nMOCK-body\nE'))
    for name in SHELL_RUNS
    for verb, op in [('true', '||'), ('false', '&&')]
    for scope, fd in [('plain', ''), ('eval', ''), ('subshell', ''), ('function', '2'), ('group', '')]
]

NEGATED_HEREDOC += [
    (f'pipeline-{verb}', name, f'! {verb} <<E | {last} {op} {R}\nMOCK-body\nE')
    for name in SHELL_RUNS
    for verb, last, op in [('true', 'true', '||'), ('cat', 'false', '&&')]
]


@pytest.mark.parametrize('case,name,program', NEGATED_HEREDOC,
                         ids=[f'{r[1]}-{r[0]}' for r in NEGATED_HEREDOC])
def test_negated_heredoc_reads_and_output(case, name, program):
    read, flag, detail = flagged(program, name)
    assert read, ('measurement', case, name, detail)
    assert flag, ('miss', case, name, detail)
    real, model = model_in(name, program)
    assert model is None or matches(real, model), (case, name, real, model)


# Finding 10: only the zsh hang cases are regressions; the others are labelled controls.
PIPELINE_NULL_EXEC = [
    ('reader', '> /dev/null | cat', True),
    ('append-reader', '>> /dev/null | cat', True),
    ('control-nonreader', '> /dev/null | :', False),
    ('control-no-multios', 'unsetopt multios 2>/dev/null; > /dev/null | cat', False),
    ('control-group', '{ > /dev/null; } | cat', False),
]


@pytest.mark.parametrize('name', SHELL_RUNS)
@pytest.mark.parametrize('case,body,waits', PIPELINE_NULL_EXEC,
                         ids=[r[0] for r in PIPELINE_NULL_EXEC])
def test_null_exec_pipeline_timeout_or_output(name, case, body, waits):
    """The zsh timeout is an observed bound, not a claim that it can never finish.

    B/S/D, and the explicitly labelled zsh controls, already agree on the baseline.
    Kill the process group on timeout so zsh's MULTIOS helper cannot outlive the test.
    """
    program = 'NULLCMD=exec; ' + body + '; echo MOCK-after'
    with tempfile.TemporaryDirectory() as tmp:
        top = Path(tmp).resolve()
        work = layout(top)
        shell = SHELL_RUNS[name]
        proc = subprocess.Popen([*shell, program], cwd=work, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True,
                                env={'PATH': '/usr/bin:/bin', 'HOME': str(top / 'home'), 'PWD': str(work)})
        timed_out = False
        try:
            try:
                out, err = proc.communicate(timeout=2 if waits and name == 'zsh' else 15)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                out, err = proc.communicate()
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        assert timed_out == (waits and name == 'zsh'), ('measurement', name, case, out, err)
        command = ' '.join(map(shlex.quote, [*shell, program]))
        model = audit._shell(command, work)
        if timed_out:
            assert model.output is None, (case, model.output)
            assert any('NULLCMD=exec' in note and 'pipeline' in note for note in model.notes), model.notes
        else:
            assert out == 'MOCK-after\n', ('measurement', name, case, out, err)
            assert model.output is None or matches(out, model.output), (name, case, out, model.output)


MODIFIER_READS = [
    ("2-function-noglob", "zsh", 'noglob() { p=MOCK; }; noglob :; [ "${p-unset}" = MOCK ] && ' + R),
    ("2-quoted-function-noglob", "zsh", 'noglob() { p=MOCK; }; "noglob" :; '
     '[ "${p-unset}" = MOCK ] && ' + R),
    ("2-function-noglob-cd", "zsh", 'noglob() { cd ..; }; noglob :; cat opus-2/draft.json'),
    ("2-function-noglob-eval", "zsh", "eval 'noglob() { p=MOCK; }; noglob :'; "
     '[ "${p-unset}" = MOCK ] && ' + R),
    ("2-function-noglob-subshell", "zsh", '(noglob() { p=MOCK; }; noglob :; '
     '[ "${p-unset}" = MOCK ] && ' + R + ')'),
    *[("5-builtin-eval-" + name, name, "setopt posixbuiltins; y=MOCK builtin eval ':'; "
       '[ "${y-unset}" = MOCK ] && ' + R) for name in ("sh", "zsh")],
    *[("5-source-" + name, name, "printf ':\\n' > s; setopt posixbuiltins; y=MOCK source ./s; "
       '[ "${y-unset}" = MOCK ] && ' + R) for name in ("sh", "zsh")],
    *[("5-special-" + verb, "zsh", 'setopt posixbuiltins; y=MOCK ' + verb + ' z=1; '
       '[ "${y-unset}" = MOCK ] && ' + R) for verb in ("declare", "integer", "local", "typeset", "float")],
    ("5-nested-builtin-eval", "zsh", "setopt posixbuiltins; y=MOCK builtin builtin eval ':'; "
     '[ "${y-unset}" = MOCK ] && ' + R),
    ("6-nocorrect-after-noglob", "zsh", 'noglob nocorrect : < "${x:=/dev/null}" 2>/dev/null; '
     '[ "${x-unset}" = unset ] && ' + R),
    ("6-nocorrect-after-noglob-eval", "zsh", 'eval \'noglob nocorrect : < "${x:=/dev/null}"\' '
     '2>/dev/null; [ "${x-unset}" = unset ] && ' + R),
    *[("7-nullcmd-function-" + verb, "zsh", verb + '() { p=MOCK; }; NULLCMD=' + verb + '; '
       '> /dev/null; [ "${p-unset}" = MOCK ] && ' + R) for verb in ("noglob", "command", "builtin")],
    ("7-readnullcmd-function-noglob", "zsh", 'noglob() { p=MOCK; }; NULLCMD=cat; READNULLCMD=noglob; '
     '< /dev/null; [ "${p-unset}" = MOCK ] && ' + R),
    ("7-readnullcmd-function-command-fd3", "zsh", 'command() { p=MOCK; }; NULLCMD=cat; READNULLCMD=command; '
     '3< /dev/null; [ "${p-unset}" = MOCK ] && ' + R),
]


@pytest.mark.parametrize("case,name,program", MODIFIER_READS, ids=[row[0] for row in MODIFIER_READS])
def test_modifier_mock_reads_are_flagged(case, name, program):
    read, flag, seen = flagged(program, name)
    assert read, ("measurement", case, name, seen)
    assert flag, ("miss", case, name, seen)


MODIFIER_OUTPUTS = [
    *[("5-builtin-eval-output-" + name, name, "setopt posixbuiltins; y=MOCK builtin eval ':'; "
       'echo "MOCK-${y-unset}"', "MOCK-MOCK\n") for name in ("sh", "zsh")],
    *[("6-nocorrect-after-" + prefix, "zsh", prefix + " nocorrect eval 'echo MOCK-inner'; "
       "echo MOCK-after", "MOCK-after\n") for prefix in ("noglob", "command")],
    ("6-nocorrect-subshell", "zsh", "(noglob nocorrect eval 'echo MOCK-inner'); echo MOCK-after",
     "MOCK-after\n"),
    ("6-nocorrect-eval", "zsh", "eval \"command nocorrect eval 'echo MOCK-inner'\"; echo MOCK-after",
     "MOCK-after\n"),
    ("8-builtin-double-dash", "zsh", "builtin -- eval 'echo MOCK-inner'; echo MOCK-after", "MOCK-after\n"),
    ("8-builtin-double-dash-subshell", "zsh", "(builtin -- eval 'echo MOCK-inner'); echo MOCK-after",
     "MOCK-after\n"),
    ("8-builtin-double-dash-eval", "zsh", "eval \"builtin -- eval 'echo MOCK-inner'\"; echo MOCK-after",
     "MOCK-after\n"),
    ("8-nested-bare-noglob-read", "zsh", 'eval \'builtin noglob < "${x:=/dev/null}"; ' + R +
     "' 2>/dev/null", ""),
    *[("8-nested-bare-" + prefix.replace(" ", "-"), "zsh", "eval '" + prefix +
       ' < "${x:=/dev/null}"; echo MOCK-inner\' 2>/dev/null; echo MOCK-after', "MOCK-after\n")
      for prefix in ("builtin command", "builtin builtin noglob", "noglob builtin noglob")],
]


@pytest.mark.parametrize("case,name,program,expected", MODIFIER_OUTPUTS,
                         ids=[row[0] for row in MODIFIER_OUTPUTS])
def test_modifier_output_matches_measured_shell(case, name, program, expected):
    real, model = model_in(name, program)
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


@pytest.mark.parametrize("name", ("bash", "sh", "dash", "zsh"))
def test_control_command_suppresses_special_assignment_persistence(name):
    """Control: `command eval` does not gain assignment persistence through POSIX_BUILTINS."""
    real, model = model_in(name, "setopt posixbuiltins; y=MOCK command eval ':'; "
                           'echo "MOCK-${y-unset}"')
    assert real == "MOCK-unset\n", ("measurement", name, real)
    assert model is None or matches(real, model), (name, real, audit._choices(model))


# Findings 3, 4 and 9: failure ordering, failed opens, and stdout opened for reading.
# Each unlabelled-control parameter fails on 19d1303. All fixtures and file content are MOCK.
_R14B_REDIRECT_READ_PROGRAMS = [
    ("plain", 'true < missing.txt < "${x:=/dev/null}"; [ "${x-unset}" = unset ] && ' + R),
    ("function", 'f() { :; }; f < missing.txt < "${x:=/dev/null}"; '
     '[ "${x-unset}" = unset ] && ' + R),
    ("eval", 'eval \'true < missing.txt < "${x:=/dev/null}"; '
     '[ "${x-unset}" = unset ] && ' + R + "'"),
    ("subshell", '( true < missing.txt < "${x:=/dev/null}"; '
     '[ "${x-unset}" = unset ] && ' + R + ' )'),
    ("other-descriptors", 'true 3< missing.txt 4< "${x:=/dev/null}"; '
     '[ "${x-unset}" = unset ] && ' + R),
]
_R14B_REDIRECT_READS = [
    (("control-dash-" if name == "dash" else "") + case + "-" + name, name, program)
    for case, program in _R14B_REDIRECT_READ_PROGRAMS for name in SHELL_RUNS
]


@pytest.mark.parametrize("case,name,program", _R14B_REDIRECT_READS,
                         ids=[row[0] for row in _R14B_REDIRECT_READS])
def test_redirection_failure_keeps_unreached_expansions_unset(case, name, program):
    """3: bash/sh/zsh stop before the later assignment; dash's eager expansion is a control."""
    read, flag, seen = flagged(program, name)
    assert read == (name != "dash"), ("measurement", case, name, seen)
    assert not read or flag, (case, name, seen)


_R14B_REDIRECT_OUTPUT_PROGRAMS = [
    ("failed-open", 'true < missing.txt < "${x:=/dev/null}"; echo "MOCK-${x-unset}"'),
    ("failed-open-function", 'f() { :; }; f < missing.txt < "${x:=/dev/null}"; '
     'echo "MOCK-${x-unset}"'),
    ("failed-open-eval", 'eval \'true < missing.txt < "${x:=/dev/null}"; '
     'echo "MOCK-${x-unset}"\''),
    ("failed-open-subshell", '( true < missing.txt < "${x:=/dev/null}"; '
     'echo "MOCK-${x-unset}" )'),
    ("noclobber", 'echo MOCK-old > f; set -C; true > f || echo MOCK-fail'),
    ("noclobber-eval", "echo MOCK-old > f; set -C; eval 'true > f || echo MOCK-fail'"),
    ("noclobber-function", 'echo MOCK-old > f; set -C; f() { :; }; f > f || echo MOCK-fail'),
    ("stdout-heredoc", 'echo MOCK-in | cat 1<<EOF\nMOCK-err\nEOF'),
    ("stdout-heredoc-group", 'echo MOCK-in | { cat; } 1<<EOF\nMOCK-err\nEOF'),
    ("stdout-heredoc-subshell", 'echo MOCK-in | ( cat ) 1<<EOF\nMOCK-err\nEOF'),
    ("stdout-heredoc-eval", "eval 'echo MOCK-in | cat 1<<EOF\nMOCK-err\nEOF'"),
]
_R14B_REDIRECT_OUTPUTS = [
    (("control-dash-" if name == "dash" and case.startswith(("failed-open", "stdout-heredoc")) else "")
     + case + "-" + name, name, program,
     ("MOCK-/dev/null\n" if name == "dash" else "MOCK-unset\n") if case.startswith("failed-open") else
     "MOCK-fail\n" if case.startswith("noclobber") else "")
    for case, program in _R14B_REDIRECT_OUTPUT_PROGRAMS for name in SHELL_RUNS
]


@pytest.mark.parametrize("case,name,program,expected", _R14B_REDIRECT_OUTPUTS,
                         ids=[row[0] for row in _R14B_REDIRECT_OUTPUTS])
def test_output_after_redirection_failures_or_readonly_stdout(case, name, program, expected):
    """3/4/9: model the measured output or leave it unknown. Dash's existing unknowns are controls."""
    real, model = model_in(name, program)
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


_R14B_REDIRECT_STATUS_PROGRAMS = [
    ("closed-fd9", 'cd scratch; true <&9'),
    ("closed-fd8", 'cd scratch; true <&8'),
    ("closed-fd-eval", "cd scratch; eval 'true <&9'"),
    ("closed-fd-function", 'cd scratch; f() { :; }; f <&9'),
    ("dev-null-parent-file", 'cd scratch; true < /dev/null/MOCK-missing'),
    ("noclobber", 'echo MOCK-old > f; set -C; true > f'),
]
_R14B_REDIRECT_STATUSES = [
    (case + "-" + name, name, program)
    for case, program in _R14B_REDIRECT_STATUS_PROGRAMS for name in SHELL_RUNS
]


@pytest.mark.parametrize("case,name,program", _R14B_REDIRECT_STATUSES,
                         ids=[row[0] for row in _R14B_REDIRECT_STATUSES])
def test_redirections_allow_the_measured_failure_status(case, name, program):
    """4: failure must remain possible so a failed call cannot carry only its final directory."""
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
        assert any(w.status in {audit.FAILED, audit.MAYBE} for w in model.worlds), (case, name, model.worlds)


_R14B_REDIRECT_CONTROLS = [
    ("control-force-clobber-" + name, name,
     'echo MOCK-old > f; set -C; true >| f || echo MOCK-fail; echo MOCK-after', "MOCK-after\n")
    for name in SHELL_RUNS
] + [
    ("control-stderr-heredoc-" + name, name,
     'echo MOCK-in | cat 2<<EOF\nMOCK-err\nEOF', "MOCK-in\n")
    for name in SHELL_RUNS
] + [
    ("control-stdin-heredoc-" + name, name,
     'echo MOCK-in | cat 0<<EOF\nMOCK-err\nEOF',
     "MOCK-in\nMOCK-err\n" if name == "zsh" else "MOCK-err\n")
    for name in SHELL_RUNS
]


@pytest.mark.parametrize("case,name,program,expected", _R14B_REDIRECT_CONTROLS,
                         ids=[row[0] for row in _R14B_REDIRECT_CONTROLS])
def test_redirection_order_and_descriptor_controls(case, name, program, expected):
    """Labelled controls: >| bypasses noclobber, while here-documents on 0 and 2 still work."""
    real, model = model_in(name, program)
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


@pytest.mark.parametrize("name", ["bash", "sh"])
def test_noclobber_is_imported_from_exported_shellopts(name):
    """4: an exported SHELLOPTS carries noclobber into a new bash process (fails on 19d1303)."""
    program = ("echo MOCK-old > f; set -C; export SHELLOPTS; "
               "/bin/bash -c 'true > f || echo MOCK-fail'")
    real, model = model_in(name, program)
    assert real == "MOCK-fail\n", ("measurement", name, real)
    assert model is None or matches(real, model), (name, real, audit._choices(model))


@pytest.mark.parametrize("name", SHELL_RUNS)
def test_control_noclobber_resets_in_a_new_shell(name):
    """Labelled control: without exported SHELLOPTS, a fresh bash allows replacing f."""
    program = ("echo MOCK-old > f; set -C; /bin/bash -c 'true > f || echo MOCK-fail'; "
               "echo MOCK-after")
    real, model = model_in(name, program)
    assert real == "MOCK-after\n", ("measurement", name, real)
    assert model is None or matches(real, model), (name, real, audit._choices(model))


# zsh without APPEND_CREATE: under noclobber, `>>` to a file that does not exist fails (found while
# integrating the round-14b build). bash and sh create the file; `emulate sh` and `setopt
# appendcreate` give zsh the same behavior.
_APPEND = "echo x >> MOCK-new.txt && echo MOCK-ok || echo MOCK-fail"
_NOCLOBBER_APPEND = [
    ("set-C", f"set -C; {_APPEND}"),
    ("setopt", f"setopt noclobber 2>/dev/null || set -C; {_APPEND}"),
    ("eval", f"set -C; eval {shlex.quote(_APPEND)}"),
    ("function", "set -C; f() { echo x; }; f >> MOCK-new.txt && echo MOCK-ok || echo MOCK-fail"),
    ("subshell", f"set -C; ( {_APPEND} )"),
]
_NOCLOBBER_APPEND_OUTPUTS = [
    (("" if name == "zsh" else "control-") + case + "-" + name, name, program,
     "MOCK-fail\n" if name == "zsh" else "MOCK-ok\n")
    for case, program in _NOCLOBBER_APPEND for name in SHELL_RUNS
] + [
    ("control-emulate-sh-zsh", "zsh", f"emulate sh; set -C; {_APPEND}", "MOCK-ok\n"),
    ("control-appendcreate-zsh", "zsh", f"set -C; setopt appendcreate; {_APPEND}", "MOCK-ok\n"),
    ("control-existing-zsh", "zsh", f"echo MOCK-old > MOCK-new.txt; set -C; {_APPEND}", "MOCK-ok\n"),
    ("control-existing-bash", "bash", f"echo MOCK-old > MOCK-new.txt; set -C; {_APPEND}", "MOCK-ok\n"),
    ("both-zsh", "zsh", "set -C; true &>> MOCK-new.txt && echo MOCK-ok || echo MOCK-fail", "MOCK-fail\n"),
]  # bash 3.2 has no `&>>`


@pytest.mark.parametrize("case,name,program,expected", _NOCLOBBER_APPEND_OUTPUTS,
                         ids=[row[0] for row in _NOCLOBBER_APPEND_OUTPUTS])
def test_zsh_noclobber_append_to_a_missing_file_may_fail(case, name, program, expected):
    """zsh's noclobber rejects `>>` to a missing file unless APPEND_CREATE is set; bash and sh
    create it. Rows labelled control pass on 19d1303 too."""
    real, model = model_in(name, program)
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


@pytest.mark.parametrize("name", SHELL_RUNS)
def test_control_zsh_noclobber_append_failure_reads(name):
    """The failure branch reads another run's answer in zsh only; the zsh model flags it. A labelled
    control: 19d1303's model flags it too."""
    read, flag, seen = flagged(f"set -C; true >> MOCK-new.txt || {R}", name)
    assert read == (name == "zsh"), ("measurement", name, seen)
    assert not read or flag, (name, seen)
