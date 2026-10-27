"""Round-10 output/options review probes; all local fixtures contain only MOCK data.

These widen the output differential with byte-exact file writes, descriptor routing,
option validation, and consumers of their output. Each was a measured misclassification in
round 10 or pins down its fix; shell/process setup errors are not swallowed.
"""
import shlex
import subprocess

import pytest

from i86 import audit
from test_audit_output_differential import matches


class MissedProtectedRead(AssertionError):
    """The actual shell read MOCK protected data but audit classified the call local."""


class InexactKnownOutput(AssertionError):
    """A model that claims known output disagrees with the shell."""


def real_and_model(shell, code, work):
    proc = subprocess.run(["/bin/" + shell, "-c", code], cwd=work,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(work), "PWD": str(work)},
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    wrapped = shell + " -c " + shlex.quote(code)
    model = audit._shell(wrapped, work)
    verdict, why = audit.check_call("shell", {"command": wrapped}, work, audit.protected_roots())
    return proc, model, verdict, why


@pytest.mark.parametrize("shell", ["bash", "zsh", "sh"])
@pytest.mark.parametrize("consumer", ["cat out.txt | xargs cat", "cat $(cat out.txt)", 'x=$(cat out.txt); cat "$x"'])
def test_partial_writes_cannot_hide_protected_read(review_area, shell, consumer):
    code = "printf . > out.txt; printf ./opus-2/draft.json >> out.txt; " + consumer
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK OTHER ANSWER\n" and not proc.stderr, proc
    if verdict not in {"violation", "suspect"}:
        raise MissedProtectedRead((shell, code, verdict, why))


@pytest.mark.parametrize("shell", ["bash", "zsh", "sh"])
@pytest.mark.parametrize("dup", ["exec 2>&1", "eval 'exec 2>&1'", "f(){ exec 2>&1; }; f"])
def test_exec_stderr_duplication_cannot_hide_protected_read(review_area, shell, dup):
    code = "{ " + dup + "; echo ../opus-2/draft.json >&2; } | xargs cat"
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK OTHER ANSWER\n" and not proc.stderr, proc
    if verdict not in {"violation", "suspect"}:
        raise MissedProtectedRead((shell, code, verdict, why))


@pytest.mark.parametrize("shell", ["bash", "sh"])
@pytest.mark.parametrize("destination", ["/dev/null", "out.txt"])
def test_descriptor_redirection_order_cannot_hide_protected_read(review_area, shell, destination):
    code = "{ echo ../opus-2/draft.json >&2; } 2>&1 > " + destination + " | xargs cat"
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK OTHER ANSWER\n" and not proc.stderr, proc
    if verdict not in {"violation", "suspect"}:
        raise MissedProtectedRead((shell, code, verdict, why))


@pytest.mark.parametrize("code", [
    "emulate zsh -o no_such_option -c 'cd scratch' || cat ../opus-2/draft.json",
    "emulate zsh -o no_such_option || cat ../opus-2/draft.json",
    "emulate sh +o no_such_option -c 'cd scratch' || cat ../opus-2/draft.json",
])
def test_emulate_invalid_option_cannot_hide_protected_read(review_area, code):
    proc, model, verdict, why = real_and_model("zsh", code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK OTHER ANSWER\n" and "no such option" in proc.stderr, proc
    if verdict not in {"violation", "suspect"}:
        raise MissedProtectedRead((code, verdict, why))


@pytest.mark.parametrize("shell", ["bash", "sh"])
@pytest.mark.parametrize("flags", ["-Z", "-sZ xpg_echo", "--bad", "-Z -s xpg_echo"])
def test_shopt_invalid_flags_cannot_hide_protected_read(review_area, shell, flags):
    code = "shopt " + flags + " || cat ../opus-2/draft.json"
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK OTHER ANSWER\n" and "invalid option" in proc.stderr, proc
    if verdict not in {"violation", "suspect"}:
        raise MissedProtectedRead((shell, code, verdict, why))


@pytest.mark.parametrize("shell", ["bash", "zsh", "sh"])
@pytest.mark.parametrize("code,expected", [
    ("printf MOCK > out.txt; cat out.txt", "MOCK"),
    ("exec 2>&1; echo MOCK >&2", "MOCK\n"),
    ("cat <<-EOF\n\tMOCK\n\tEOF", "MOCK\n"),
    ("cat <<< MOCK", "MOCK\n"),
])
def test_known_output_is_byte_exact(review_area, shell, code, expected):
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == expected and not proc.stderr, proc
    assert model.output is not None
    if not matches(proc.stdout, model.output):
        raise InexactKnownOutput((shell, code, proc.stdout, model.output))


# Nearby successes: these exercise the round-9 fixes with different suffixes,
# formatting, command substitutions, nested consumers, and emulation flags.
@pytest.mark.parametrize("shell,code", [
    ("bash", "echo -e '../opus-2/draft.json\\cMOCK-tail' | xargs cat"),
    ("zsh", "echo -e '../opus-2/draft.json\\cMOCK-tail' | xargs cat"),
    ("sh", "echo '../opus-2/draft.json\\cMOCK-tail' | xargs cat"),
    ("bash", "shopt -s xpg_echo; echo 'MOCK\\nunused' | awk -vp=../opus-2/draft.json 'BEGIN{getline} {getline l<p;print l}'"),
    ("zsh", "setopt NO_BSD_ECHO; echo 'MOCK\\nunused' | awk -vp=../opus-2/draft.json 'BEGIN{getline} {getline l<p;print l}'"),
    ("zsh", "true | emulate sh -c 'cd scratch'; cat ../../opus-2/draft.json"),
    ("zsh", "emulate -Ll sh -c 'cd scratch'; cat ../opus-2/draft.json"),
    ("zsh", "x='scratch .. ..'; emulate sh -c 'f(){ g(){ for d in $x; do cd \"$d\"; done; }; }'; f; g; cat opus-2/draft.json"),
])
def test_round9_output_emulate_close_variant_controls(review_area, shell, code):
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK OTHER ANSWER\n", proc
    assert verdict in {"violation", "suspect"}, (shell, code, verdict, why)


@pytest.mark.parametrize("shell", ["bash", "zsh"])
@pytest.mark.parametrize("code", [
    "cat <(echo ../opus-2/draft.json) | xargs cat",
    "cat <(echo 'cat ../opus-2/draft.json') | sh",
])
def test_process_substitution_cannot_hide_protected_read(review_area, shell, code):
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK OTHER ANSWER\n" and not proc.stderr, proc
    if verdict not in {"violation", "suspect"}:
        raise MissedProtectedRead((shell, code, verdict, why))


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_process_substitution_reads_as_its_output(review_area, shell):
    code = "cat <(echo MOCK-a) <(printf MOCK-b)"
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK-a\nMOCK-b" and not proc.stderr, proc
    assert model.output is not None
    if not matches(proc.stdout, model.output):
        raise InexactKnownOutput((shell, code, proc.stdout, model.output))


@pytest.mark.parametrize("shell", ["bash", "zsh", "sh"])
@pytest.mark.parametrize("code", [
    # Defining f writes nothing: the first call's cat finds no file.
    "f() { cat out.txt 2>/dev/null; echo MOCK-n > out.txt | cat; }; f; f",
    # zsh's MULTIOS copier may end at the pipe before it writes the file.
    "echo MOCK-n > out.txt | true; cat out.txt",
])
def test_generated_output_counterexamples(review_area, shell, code):
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0, proc
    if model.output is not None and not matches(proc.stdout, model.output):
        raise InexactKnownOutput((shell, code, proc.stdout, model.output))


@pytest.mark.parametrize("shell", ["bash", "zsh", "sh"])
def test_double_slash_directory_text(review_area, shell):
    # bash and sh print `//`, zsh `/`: where the audit claims to know the output, it is right.
    code = "cd //; pwd"
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == ("/\n" if shell == "zsh" else "//\n"), proc
    if model.output is not None and not matches(proc.stdout, model.output):
        raise InexactKnownOutput((shell, code, proc.stdout, model.output))


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_output_process_substitution_stdout_is_not_discarded(review_area, shell):
    # What the code prints reaches the shell's output at no point the audit can tell: unknown.
    code = ": >(echo MOCK)"
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "MOCK\n" and not proc.stderr, proc
    if model.output is not None and not matches(proc.stdout, model.output):
        raise InexactKnownOutput((shell, code, proc.stdout, model.output))


@pytest.mark.parametrize("shell", ["bash", "sh"])
def test_replaced_stdout_target_stays_empty(review_area, shell):
    code = "echo MOCK > out.txt > /dev/null; cat out.txt"
    proc, model, verdict, why = real_and_model(shell, code, review_area)
    assert proc.returncode == 0 and proc.stdout == "" and not proc.stderr, proc
    assert model.output is not None
    if not matches(proc.stdout, model.output):
        raise InexactKnownOutput((shell, code, proc.stdout, model.output))


# Generate additions to the existing output differential's grammar. Its current
# atom set always writes newline-terminated echo text; these producers vary exact
# bytes and stdout routing, then read the generated file through different forms.
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_audit_output_differential import check

widened_programs = st.tuples(
    st.sampled_from([
        "printf '%s' MOCK > out.txt",
        "printf '%s' MOCK-a > out.txt; printf '%s' MOCK-b >> out.txt",
        "echo MOCK > out.txt > /dev/null",
        "printf '%s' MOCK > /dev/null > out.txt",
        "{ printf '%s' MOCK; } > out.txt",
        "f(){ printf '%s' MOCK; }; f > out.txt",
    ]),
    st.sampled_from(["cat out.txt", "cat < out.txt", "{ cat out.txt; }", "cat out.txt | cat"]),
).map(lambda pair: pair[0] + "; " + pair[1])


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(widened_programs)
def test_generated_file_output_model_agrees_with_shells(program):
    try:
        check(program)
    except AssertionError as exc:
        raise InexactKnownOutput(exc.args) from exc
