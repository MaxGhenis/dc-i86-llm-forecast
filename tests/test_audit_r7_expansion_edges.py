"""Expansion boundary cases checked against real shells in temporary MOCK layouts."""

import shlex
import subprocess

import pytest

from i86 import audit


SHELLS = [("/bin/bash", "posix"), ("/bin/zsh", "zsh")]


def run_shell(shell, program, workdir):
    flags = ["--norc", "--noprofile", "-c"] if shell == "/bin/bash" else ["-f", "-c"]
    return subprocess.run([shell, *flags, program], cwd=workdir, capture_output=True, text=True,
                          timeout=20, env={"PATH": "/usr/bin:/bin", "HOME": str(workdir)})


def model(program, workdir, dialect):
    result = audit._Shell(workdir)
    result.dialect = dialect
    result.shell_name = "zsh" if dialect == "zsh" else "bash"
    result.vars["HOME"] = str(workdir)
    result.run(program)
    return result


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("operator", ["?", ":?"])
def test_parameter_error_diagnostic_expansion_matches_real_shell(review_area, shell, dialect, operator):
    program = f'unset x; : "${{x{operator}$(cat ../opus-2/draft.json)}}"; echo MOCK reached'
    real = run_shell(shell, program, review_area)
    assert real.returncode != 0 and "MOCK reached" not in real.stdout
    # Bash expands the error message before exiting; zsh prints its source literally.
    assert ("MOCK OTHER ANSWER" in real.stderr) == (dialect == "posix"), real
    verdict, why = audit.model_call("shell", {"command": shell + " -c " + shlex.quote(program)},
                                    review_area, audit.protected_roots())
    assert verdict == ("violation" if dialect == "posix" else "local"), why
    assert not model(program, review_area, dialect).worlds


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("setup", ["unset a", "a=(); unset a"])
def test_unset_quoted_array_at_matches_real_shell(review_area, shell, dialect, setup):
    program = setup + '; set -- "${a[@]}"'
    real = run_shell(shell, program + '; printf "%s\\0" "$#" "$@"', review_area)
    assert real.returncode == 0, real.stderr
    expected = real.stdout.split("\0")[:-1]
    got = model(program, review_area, dialect)
    count = got.vars.get("#")
    params = [] if count == "0" else got.vars.get("@", "").split(audit.SPLIT)
    assert [count, *params] == expected, (shell, program, [count, *params], expected)


@pytest.mark.parametrize("program", [
    'setopt -y; x="MOCK one"; set -- $x',
    'set -y; x="MOCK one"; set -- $x',
    'setopt -y; unsetopt -y; x="MOCK one"; set -- $x',
    'set -y; set +y; x="MOCK one"; set -- $x',
    'setopt -F; set -- scratch/*',
    'set -F; set -- scratch/*',
    'setopt -F; unsetopt -F; set -- scratch/*',
    'set -F; set +F; set -- scratch/*',
    '(setopt -y); x="MOCK one"; set -- $x',
    'f(){ setopt -y; }; f; x="MOCK one"; set -- $x',
    'f(){ setopt localoptions -y; }; f; x="MOCK one"; set -- $x',
    'setopt -y; emulate sh -c "set -- MOCK one"; x="MOCK one"; set -- $x',
])
def test_zsh_expansion_option_letters_match_real_shell(review_area, program):
    real = run_shell("/bin/zsh", program + '; printf "%s\\0" "$#" "$@"', review_area)
    assert real.returncode == 0, real.stderr
    expected = real.stdout.split("\0")[:-1]
    got = model(program, review_area, "zsh")
    count = got.vars.get("#")
    params = [] if count == "0" else got.vars.get("@", "").split(audit.SPLIT)
    assert [count, *params] == expected, (program, [count, *params], expected, got.notes)


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("setup", ['a=()', 'a=("" two)'])
@pytest.mark.parametrize("operator", ["=", ":=", "?", ":?"])
def test_array_default_and_error_parameter_semantics(review_area, shell, dialect, setup, operator):
    program = setup + '; : "${a' + operator + 'MOCK}"; set -- "$a" "${#a[@]}"'
    real = run_shell(shell, program + '; printf "%s\\0" "$#" "$@"', review_area)
    got = model(program, review_area, dialect)
    if real.returncode:
        assert not got.worlds, (program, real, got.worlds)
    else:
        count = got.vars.get("#")
        params = [] if count == "0" else got.vars.get("@", "").split(audit.SPLIT)
        assert [count, *params] == real.stdout.split("\0")[:-1], (program, got.vars, real.stdout)


@pytest.mark.parametrize("shell,dialect", SHELLS)
def test_braces_with_repeated_side_effects_are_suspect(review_area, shell, dialect):
    program = 'i=0; set -- {a,b}$((i++)); printf "MOCK %s\\n" "$i"'
    real = run_shell(shell, program, review_area)
    assert real.returncode == 0 and "MOCK" in real.stdout
    category, reason = audit.model_call("shell", {"command": shell + " -c " + shlex.quote(program)},
                                      review_area, audit.protected_roots())
    assert category == "suspect" and "brace" in reason


@pytest.mark.parametrize("shell,dialect", SHELLS)
def test_protected_glob_survives_removed_audit_time_matches(review_area, shell, dialect):
    program = 'cat ../opus-*/draft.json'
    real = run_shell(shell, program, review_area)
    assert real.returncode == 0 and "MOCK OTHER ANSWER" in real.stdout
    (review_area.parent / "opus-2" / "draft.json").unlink()
    category, reason = audit.model_call("shell", {"command": shell + " -c " + shlex.quote(program)},
                                      review_area, audit.protected_roots())
    assert category == "violation", reason
