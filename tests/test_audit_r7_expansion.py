"""Expansion classes against bash 3.2 and zsh, using only temporary MOCK files."""

import os
import shlex
import subprocess

import pytest

from i86 import audit


SHELLS = [("/bin/bash", "posix"), ("/bin/zsh", "zsh")]


def real(shell, program, work):
    flags = ["--norc", "--noprofile", "-c"] if shell == "/bin/bash" else ["-f", "-c"]
    return subprocess.run([shell, *flags, program], cwd=work, capture_output=True, text=True,
                          timeout=20, env={"PATH": "/usr/bin:/bin", "HOME": str(work),
                                           "PWD": str(work), "OLDPWD": str(work)})


def model(program, work, dialect):
    result = audit._Shell(work)
    result.dialect, result.shell_name = dialect, "zsh" if dialect == "zsh" else "bash"
    result.vars["HOME"] = str(work)
    result.run(program)
    return result


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("program", [
    "set -- pre{a,b}post {3..1} {x,y}{1,2}",
    "set -- {a,{b,c}} '{a,b}' \\{a,b\\}",
    "set -- {03..1} {1..3..2} {a..c..2}",
    "a=(one 'two words' ''); set -- $a",
    'a=(one "two words" ""); set -- "$a" "${a[@]}" "${a[*]}" "${#a[@]}"',
    'a=(); set -- "${a[@]}"',
    'a=(); set -- x"${a[@]}"y',
    'unset IFS; a=(one two); set -- "${a[*]}"',
    'IFS=:; a=(one two); set -- "$a" "${a[*]}"',
    'IFS=; a=(one two); set -- "$a" "${a[*]}"',
    'a=(one two); set -- pre${a[@]}post',
    'a=(one); a+=(two); set -- "${a[@]}"',
    'unset x; : ${x:=scratch}; set -- "$x"',
    'unset x; : ${x=scratch}; set -- "$x"',
    'x=; : ${x=scratch}; set -- "$x"',
    'x=; : ${x:=scratch}; set -- "$x"',
    'x=kept; : ${x:=changed}; set -- "$x"',
    'unset x; : "${x:=two words}"; set -- "$x"',
    'unset x; set -- ${x:={1,2}}',
    'set -o noglob; set -- scratch/*',
    'set -o noglob; set +o noglob; set -- scratch/*',
    '(set -o noglob); set -- scratch/*',
    'f(){ set -o noglob; }; f; set -- scratch/*',
    'if true; then set -o noglob; else set +o noglob; fi; set -- scratch/*',
    'if false; then set -o noglob; else set +o noglob; fi; set -- scratch/*',
    'set -- "scratch/*"',
    'a="scratch/*"; set -- $a',
    'a=(scratch/*); set -- "${a[@]}"',
])
def test_words_match_real_shells(review_area, shell, dialect, program):
    proc = real(shell, program + '; printf "%s\\0" "$#" "$@"', review_area)
    assert proc.returncode == 0, (program, proc.stderr)
    expected = proc.stdout.split("\0")[:-1]
    got = model(program, review_area, dialect)
    if got.notes:
        # A zsh nested parameter default has a different grammar. The audit reports its
        # uncertainty instead of giving bash's parse a definite meaning in zsh.
        assert dialect == "zsh" and program == 'unset x; set -- ${x:={1,2}}', got.notes
        assert audit.check_call("shell", {"command": shell + " -c " + shlex.quote(program)},
                                review_area, audit.protected_roots())[0] == "suspect"
        return
    count = got.vars.get("#")
    params = [] if count == "0" else got.vars.get("@", "").split(audit.SPLIT)
    assert [count, *params] == expected, (shell, program, [count, *params], expected)


@pytest.mark.parametrize("spelling", ["shwordsplit", "sh_word_split", "SH_WORD_SPLIT"])
@pytest.mark.parametrize("command", ["setopt {}", "set -o {}"])
def test_zsh_option_spellings_and_unsetting(review_area, spelling, command):
    program = (command.format(spelling) + '; x="one two"; set -- $x; n=$#; '
               'unsetopt sh_word_split; set -- $x; set -- "$n" "$#"')
    proc = real("/bin/zsh", program + '; printf "%s\\0" "$@"', review_area)
    got = model(program, review_area, "zsh")
    assert proc.stdout.split("\0")[:-1] == got.vars["@"].split(audit.SPLIT) == ["2", "1"]


@pytest.mark.parametrize("program", [
    'setopt noglob; unsetopt NO_GLOB; set -- scratch/*',
    'f(){ setopt localoptions noglob; }; f; set -- scratch/*',
    'setopt localoptions; f(){ unsetopt localoptions; setopt noglob; }; f; set -- scratch/*',
    'emulate sh; x="one two"; set -- $x',
    'a=(one two); emulate sh; set -- "$a" "${a[@]}"',
    'emulate sh; set -- {1,2}',
    'emulate sh; x="scratch/*"; set -- $x',
])
def test_zsh_expansion_options_scope(review_area, program):
    proc = real("/bin/zsh", program + '; printf "%s\\0" "$#" "$@"', review_area)
    got = model(program, review_area, "zsh")
    assert proc.returncode == 0, proc.stderr
    params = [] if got.vars["#"] == "0" else got.vars["@"].split(audit.SPLIT)
    assert [got.vars["#"], *params] == proc.stdout.split("\0")[:-1], (program, got.notes)


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("program", [
    'cd scratch; cd ~-; cd ~+',
    'pushd scratch >/dev/null; pushd deep >/dev/null; cd ~2',
    'pushd scratch >/dev/null; pushd deep >/dev/null; cd ~+1',
    'pushd scratch >/dev/null; pushd deep >/dev/null; cd ~-1',
    'pushd scratch >/dev/null; pushd deep >/dev/null; cd ~-0',
    'cd scratch; for d in ~- ~+; do cd "$d"; done',
    'cd scratch; for d in {~-,~+}; do cd "$d"; done',
    'cd scratch/deep; for d in pre{a,b}post; do cd ..; done',
    'cd scratch/deep; a=(one two); for d in "${a[@]}"; do cd ..; done',
    'cd scratch/deep; for d in "scratch/*"; do cd ..; done',
])
def test_directory_expansions_end_where_real_shell_ends(review_area, shell, dialect, program):
    proc = real(shell, program + '; pwd -P', review_area)
    assert proc.returncode == 0, proc.stderr
    got = model(program, review_area, dialect)
    assert got.known and {w.cwd for w in got.worlds} == {audit.Path(proc.stdout.strip())}, (program, got.worlds)


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("operator,initial", [("?", "unset x"), (":?", "unset x"), (":?", "x=")])
def test_failed_parameter_error_stops_the_shell(review_area, shell, dialect, operator, initial):
    program = f'{initial}; : ${{x{operator}MOCK ERROR}}; cat ../opus-2/draft.json'
    proc = real(shell, program, review_area)
    assert proc.returncode != 0 and "MOCK OTHER ANSWER" not in proc.stdout
    got = model(program, review_area, dialect)
    assert not got.worlds
    assert audit.check_call("shell", {"command": shell + " -c " + shlex.quote(program)}, review_area,
                            audit.protected_roots())[0] == "local"


@pytest.mark.parametrize("shell,dialect", SHELLS)
@pytest.mark.parametrize("name", ["MOCK:directory", "MOCK*directory"])
def test_expanded_existing_legal_directory_names_are_not_rejected(review_area, shell, dialect, name):
    (review_area / name).mkdir()
    program = f'set -o noglob; x={shlex.quote(name)}; cd "$x"'
    proc = real(shell, program + '; pwd -P', review_area)
    got = model(program, review_area, dialect)
    assert proc.returncode == 0 and {w.cwd for w in got.worlds} == {review_area / name}
    assert audit.check_call("shell", {"command": shell + " -c " + shlex.quote(program)}, review_area,
                            audit.protected_roots())[0] == "local"


@pytest.mark.parametrize("program", [
    'a=(one two); : "${a[1]}"',
    'a=(one two); a[1]=changed; : "$a"',
    'if date; then a=(one); else a=(two three); fi; : "$a"',
])
def test_unmodeled_arrays_are_reported_as_suspect(review_area, program):
    for shell, _ in SHELLS:
        category, reason = audit.check_call("shell", {"command": shell + " -c " + shlex.quote(program)},
                                            review_area, audit.protected_roots())
        assert category == "suspect" and "array" in reason, (program, category, reason)
