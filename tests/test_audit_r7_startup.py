"""Shell startup and directory-variable semantics against real shells in a MOCK work area."""

import shlex
import subprocess

import pytest

from i86 import audit


SHELLS = [("/bin/bash", "posix"), ("/bin/zsh", "zsh")]


def real(shell, program, work):
    flags = ["--norc", "--noprofile", "-c"] if shell == "/bin/bash" else ["-f", "-c"]
    return subprocess.run(
        [shell, *flags, program], cwd=work, capture_output=True, text=True, timeout=20,
        env={"PATH": "/usr/bin:/bin", "HOME": str(work), "PWD": str(work), "OLDPWD": str(work)},
    )


def model(program, work, dialect):
    result = audit._Shell(work)
    result.dialect = dialect
    result.shell_name = "zsh" if dialect == "zsh" else "bash"
    if dialect == "zsh":
        result.worlds = [world._replace(oldpwd=work) for world in result.worlds]
    result.vars["HOME"] = str(work)
    result.run(program)
    return result


def assert_protected_read(shell, program, work):
    proc = real(shell, program, work)
    assert proc.returncode == 0 and "MOCK OTHER ANSWER" in proc.stdout, (program, proc)
    verdict, reason = audit.check_call(
        "shell", {"command": shell + " -c " + shlex.quote(program)}, work, audit.protected_roots(),
    )
    assert verdict == "violation", (program, verdict, reason)


@pytest.mark.parametrize("setup", [
    "set -f", "set -o noglob", "f(){ set -f; }; f", "set -f; (set +f)",
])
def test_exported_bash_shellopts_tracks_live_option_state(review_area, setup):
    code = 'set -- scratch/*; echo "$#|$*"'
    program = setup + "; export SHELLOPTS; /bin/bash -c " + shlex.quote(code)
    proc = real("/bin/bash", program, review_area)
    result = model(program, review_area, "posix")
    assert proc.returncode == 0, proc.stderr
    assert result.output == proc.stdout.removesuffix("\n"), (program, result.output, proc)


@pytest.mark.parametrize("setup", ["set -f", "set -o noglob"])
def test_exported_live_shellopts_prevents_glob_and_exposes_mock_read(review_area, setup):
    code = 'for d in scratch/*; do cd "$d"; cd ..; done; cat opus-2/draft.json'
    program = setup + "; export SHELLOPTS; /bin/bash -c " + shlex.quote(code)
    assert_protected_read("/bin/bash", program, review_area)


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("child,options", [
    ("/bin/bash", "-f"), ("/bin/bash", "-o noglob"),
    ("/bin/sh", "-f"), ("/bin/sh", "-o noglob"),
    ("/bin/zsh", "-F"), ("/bin/zsh", "-o noglob"),
])
def test_startup_options_apply_to_script_files(review_area, shell, dialect, child, options):
    script = review_area / "MOCK-options.sh"
    script.write_text(
        '# MOCK program: disabled globbing makes the literal cd fail before moving to the parent.\n'
        'for d in scratch/*; do cd "$d"; cd ..; done\n'
        'cat opus-2/draft.json\n'
    )
    assert_protected_read(shell, f"{child} {options} {script.name}", review_area)


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("setup,expression", [
    ("PWD=..", "~+/opus-2/draft.json"),
    ("OLDPWD=..", "~-/opus-2/draft.json"),
    ("cd scratch; PWD=../..", "~+/opus-2/draft.json"),
    ("cd scratch; OLDPWD=../..", "~-/opus-2/draft.json"),
    ("f(){ local PWD; PWD=..; set -- ~+/opus-2/draft.json; result=$1; }; f", '"$result"'),
    ("f(){ local OLDPWD; OLDPWD=..; set -- ~-/opus-2/draft.json; result=$1; }; f", '"$result"'),
])
def test_directory_tildes_use_current_special_variable_values(review_area, shell, dialect, setup, expression):
    program = setup + "; set -- " + expression
    proc = real(shell, program + '; printf "%s\\0" "$#" "$@"', review_area)
    assert proc.returncode == 0, (shell, program, proc.stderr)
    result = model(program, review_area, dialect)
    count = result.vars.get("#")
    params = [] if count == "0" else result.vars.get("@", "").split(audit.SPLIT)
    assert [count, *params] == proc.stdout.split("\0")[:-1], (shell, program, result.notes)


@pytest.mark.parametrize("setup,expression", [
    ("PWD=..", "~+/opus-2/draft.json"),
    ("OLDPWD=..", "~-/opus-2/draft.json"),
    ("cd scratch; PWD=../..", "~+/opus-2/draft.json"),
    ("cd scratch; OLDPWD=../..", "~-/opus-2/draft.json"),
])
def test_overridden_directory_variable_tildes_report_mock_reads(review_area, setup, expression):
    assert_protected_read("/bin/bash", setup + "; cat " + expression, review_area)
