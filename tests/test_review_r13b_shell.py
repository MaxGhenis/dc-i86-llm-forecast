"""Round-13b shell regressions, measured against macOS's real shells in temporary MOCK layouts.

Each case failed against 3d8e9ce. Output checks allow the model to cover uncertainty, while the
measurement assertions record what the named shell actually did with these MOCK programs.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from i86 import audit
from test_audit_output_differential import matches
from test_audit_readonly import SHELL_RUNS, flagged, layout
from test_review_r13_shell import model_in

R = "cat ../opus-2/draft.json"  # another run's MOCK answer
P = "printf '../opus-2/draft.json\\n'"


READS = [
    # 1: follow nested precommand modifiers when deciding where redirections expand.
    ("nested-builtin-command", "zsh", 'builtin command cat < "${x?}" 2>/dev/null; ' + R),
    # 5: quoted nocorrect is an external command; a bare modifier has its own null-command rules.
    ("quoted-nocorrect", "zsh", '"nocorrect" : < "${x:=/dev/null}" 2>/dev/null; '
     '[ "${x-unset}" = unset ] && ' + R),
    ("null-nocorrect", "zsh", 'nocorrect < "${x:=/dev/null}" 2>/dev/null; '
     '[ "${x-unset}" = unset ] && ' + R),
    *[("bare-" + verb, "zsh", "eval '" + verb + ' < "${x:=/dev/null}"\' 2>/dev/null; '
       '[ "${x-unset}" = unset ] && ' + R) for verb in ("command", "noglob", "builtin")],
    # 6: MULTIOS joins the pipe before the final stage's own input redirection.
    ("multios-loop", "zsh", P + ' | while read l; do cat "$l"; done < /dev/null'),
    ("multios-heredoc-stage", "zsh", 'cat <<E | xargs cat < /dev/null 2>/dev/null\n'
     '../opus-2/draft.json\nE'),
    # 7: the builtin after a zsh precommand modifier must run in the current shell.
    *[("eval-after-" + verb, "zsh", verb + " eval '" + R + "'")
      for verb in ("noglob", "nocorrect")],
    # A leading '-' is an option to zsh -c, so place the precommand after a real statement.
    ("eval-after-dash", "zsh", "true; - eval '" + R + "'"),
    ("cd-after-noglob", "zsh", 'noglob cd ..; cat opus-2/draft.json'),
    ("read-after-noglob", "zsh", P + ' > f; noglob read p < f; cat "$p"'),
    ("read-after-builtin-dash", "zsh", P + ' > f; builtin - read p < f; cat "$p"'),
    ("cat-after-builtin-dash", "zsh", 'builtin - ' + R),
    # 8: the last substitution, even inside ${...}, sets a POSIX null command's status.
    *[("null-backquote-" + name, name, '> /dev/null"${u:-`false`}" || ' + R)
      for name in ("bash", "sh", "dash")],
    # 9: && and || following the delimiter start are commands, not here-document body text.
    *[("heredoc-" + name + "-" + op, name, verb + ' <<E ' + op + ' exit\nx\nE\n' + R)
      for name in SHELL_RUNS for verb, op in (("true", "||"), ("false", "&&"))],
]


@pytest.mark.parametrize("case,name,program", READS, ids=[row[0] for row in READS])
def test_a_measured_mock_answer_read_is_flagged(case, name, program):
    read, flag, seen = flagged(program, name)
    assert read, ("measurement", case, name, seen)
    assert flag, ("miss", case, name, seen)


OUTPUTS = [
    # 2: functions take precedence over special handling of ':' and the default pager 'more'.
    ("readnull-function-more", "zsh", 'more() { y=MOCK; }; NULLCMD=cat; READNULLCMD=more; '
     '< /dev/null; echo "${y-unset}"', "MOCK\n"),
    ("null-function-more", "zsh", 'more() { y=MOCK; }; NULLCMD=more; '
     '> /dev/null; echo "${y-unset}"', "MOCK\n"),
    ("null-function-colon", "zsh", ':() { y=MOCK; }; NULLCMD=:; '
     '> /dev/null; echo "${y-unset}"', "MOCK\n"),
    # 3: descriptor 2's here-document contributes nothing to cat's standard input.
    ("stderr-heredoc", "zsh", "echo MOCK-in | cat 2<<EOF\nMOCK-err\nEOF", "MOCK-in\n"),
    # 4: POSIX_BUILTINS keeps assignments preceding functions and special builtins.
    ("posixbuiltins-function", "zsh", 'setopt posixbuiltins; f() { x=MOCK; }; y=1 f; '
     'echo "${x-unset}:${y-unset}"', "MOCK:1\n"),
    ("posixbuiltins-eval", "zsh", "setopt posixbuiltins; y=1 eval 'x=MOCK'; "
     'echo "${x-unset}:${y-unset}"', "MOCK:1\n"),
    ("posixbuiltins-function-export", "zsh", 'setopt posixbuiltins; f() { :; }; x=MOCK f; '
     '/bin/sh -c \'echo "${x-unset}"\'', "MOCK\n"),
    # 6: stage input order includes the pipe first, then each redirection in source order.
    ("multios-loop-output", "zsh", "printf 'MOCK-f\\n' > f; echo MOCK-in | "
     'while read l; do echo "$l"; done < f', "MOCK-in\nMOCK-f\n"),
    ("multios-heredoc-output", "zsh", "printf 'MOCK-f\\n' > f; cat <<E | cat < f\nMOCK-here\nE",
     "MOCK-here\nMOCK-f\n"),
    ("herestring-first-bash", "bash", "printf 'MOCK-f\\n' > f; cat <<< MOCK-s < f", "MOCK-f\n"),
    ("herestring-first-zsh", "zsh", "printf 'MOCK-f\\n' > f; cat <<< MOCK-s < f", "MOCK-s\nMOCK-f\n"),
    ("time-stage", "zsh", "printf 'MOCK-f\\n' > f; echo MOCK-in | time cat < f", "MOCK-f\n"),
    # 8: CSH_NULLCMD aborts; exec as NULLCMD keeps the output redirection after it returns.
    ("cshnullcmd", "zsh", "setopt cshnullcmd; > /dev/null; echo MOCK-after", ""),
    ("nullcmd-exec", "zsh", "NULLCMD=exec; > /dev/null; echo MOCK-after", ""),
    ("nullcmd-maybe-exec-function", "zsh", '[ -n "$X" ] && exec() { :; }; '
     'NULLCMD=exec; > /dev/null; echo MOCK-after', ""),
]


@pytest.mark.parametrize("case,name,program,expected", OUTPUTS, ids=[row[0] for row in OUTPUTS])
def test_output_for_the_measured_shell(case, name, program, expected):
    real, model = model_in(name, program)
    assert real == expected, ("measurement", case, name, real)
    assert model is None or matches(real, model), (case, name, real, audit._choices(model))


def test_a_group_with_its_own_input_preserves_the_pipeline_input():
    """6: the redirected unit may be a group containing the loop; its output is fully known."""
    program = "printf 'MOCK-f\\n' > f; echo MOCK-in | { while read l; do echo \"$l\"; done; } < f"
    real, model = model_in("zsh", program)
    assert real == "MOCK-in\nMOCK-f\n", ("measurement", real)
    assert model is not None and matches(real, model), (real, model)


@pytest.mark.parametrize("command", ["f", "eval ':'"], ids=["function", "eval"])
def test_posixbuiltins_keeps_assignments_before_a_modified_command(command):
    """4 and 7: a transparent modifier keeps this fully known assignment in the parent shell."""
    program = 'setopt posixbuiltins; f() { :; }; y=MOCK noglob ' + command + '; echo "${y-unset}"'
    real, model = model_in("zsh", program)
    assert real == "MOCK\n", ("measurement", real)
    assert model is not None and matches(real, model), (real, model)


@pytest.mark.parametrize("name", SHELL_RUNS)
@pytest.mark.parametrize("command", ["echo MOCK > missing/out.txt", "true < missing.txt"])
def test_a_builtin_redirection_failure_has_failing_status(name, command):
    """10: compare the shell's printed $? and the model's success/failure status directly."""
    with tempfile.TemporaryDirectory() as tmp:
        top = Path(tmp).resolve()
        work = layout(top)
        program = "cd scratch; " + command
        proc = subprocess.run([*SHELL_RUNS[name], program + '; printf \'%s\\n\' "$?"'], cwd=work,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work)},
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        assert proc.stdout == ("2\n" if name == "dash" else "1\n"), ("measurement", name, proc)
        # A shell wrapper's process status is unknown, so run its body in a named shell model.
        model = audit._Shell(work)
        model.shell_name = name
        model.dialect = "zsh" if name == "zsh" else "posix"
        model.posix = name == "sh"
        model.run(program)
        assert any(w.status in {audit.FAILED, audit.MAYBE} for w in model.worlds), (name, model.worlds)
