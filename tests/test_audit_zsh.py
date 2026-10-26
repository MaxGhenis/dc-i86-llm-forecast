"""Where zsh and other shells differ, the audit follows the shell a command names and otherwise keeps
both outcomes. Each case was run in zsh 5.9, bash 3.2 and dash first; the generated programs of
test_audit_shell_differential.py found the background-list case."""

import pytest

from i86 import audit
from i86.audit import FAILED


@pytest.fixture
def work(tmp_path):
    w = tmp_path.resolve() / "w"
    (w / "a" / "a").mkdir(parents=True)
    return w


def places(command, work):
    return {w.cwd for w in audit._shell(command, work).worlds}


def reached(command, work):
    return set(audit._shell(command, work).paths)


@pytest.mark.parametrize("command", ["cd a && true &", "cd a && make > log 2>&1 &", "true | cd a",
                                     "true | { cd a; }", "f(){ cd a; }; true | f",
                                     'echo a | while read d; do cd "$d"; done'])
def test_unnamed_shell_keeps_both_outcomes(command, work):
    # zsh: the and-or list's first pipeline, or the pipeline's last stage, runs in the current shell.
    assert places(command, work) == {work, work / "a"}


@pytest.mark.parametrize("command", ["true && cd a &", "cd a | cat", "true | (cd a)", "true | cat", "cat ./x | grep y"])
def test_same_in_every_shell(command, work):
    assert places(command, work) == {work}


@pytest.mark.parametrize("shell, base", [("zsh -f -c", "a"), ("bash -c", ""), ("dash -c", "")])
@pytest.mark.parametrize("code", ["cd a && true & cat ./x", "true | cd a; cat ./x", 'echo a | while read d; do cd "$d"; done; cat ./x'])
def test_named_shell_is_followed(shell, base, code, work):
    assert reached(f"{shell} '{code}'", work) & {work / "x", work / "a" / "x"} == {work / base / "x"}


def test_lastpipe_in_bash_keeps_both(work):
    got = reached("bash -c 'shopt -s lastpipe; true | cd a; cat ./x'", work)
    assert {work / "x", work / "a" / "x"} <= got


def test_read_at_end_of_pipeline_sets_variable_in_zsh(work):
    assert work / "a" / "x" in reached("zsh -f -c 'echo a | read d; cat \"./$d/x\"'", work)
    assert work / "a" / "x" not in reached("bash -c 'echo a | read d; cat \"./$d/x\"'", work)


def test_bang_before_group_negates_only_the_group(work):
    shell = audit._shell("! { cd a; } && mkdir n 2>/dev/null", work)
    assert [(w.cwd, w.status) for w in shell.worlds] == [(work / "a", FAILED)]
