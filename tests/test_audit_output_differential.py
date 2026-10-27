"""The audit's model of what a shell command prints, against bash and zsh, on generated MOCK programs.

The model keeps a command's standard output as one text, a choice of texts (where the shells differ, or
branches may have run), or unknown. Programs mix echo and printf (with options and escapes), echo's
option state (bash's xpg_echo and POSIX mode, zsh's BSD_ECHO, emulate sh), variables (several in one
string), declarations that list or stay quiet, pwd, cd, dirname and basename, files written and read
back (cat FILE, < FILE), here-documents and here-strings, /dev/null, several stdout redirections on one
command, output sent to standard error or another descriptor (`2>&1` before or after the move), closed
standard output (bash 3.2 keeps what a builtin wrote, of printf the first pass of its format, and writes
it later; bash's builtins then fail, zsh's do not), exec's redirections, process substitution, pipelines
with a redirected stage (zsh's MULTIOS sends it down the pipe too), groups, subshells, functions, loops,
if, && and ||, background jobs, eval, sh -c, exit and return, unset, and writes to a readonly variable
(which end the line, the eval or the shell, or fail, by shell and kind of write). Each program sets the
variable it prints first: the audit cannot know a variable's value from the environment. Property, for
every program under bash and zsh (no startup files): when the model's output is known, what the shell
printed is one of its texts, an unknown part matching anything.
"""

import os
import re
import shlex
import signal
import subprocess
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from i86 import audit
from test_audit_shell_differential import SHELLS, layout

WORDS = ["MOCK-a", "MOCK b", "-n", "-e", "-E", "MOCK\\tc", "MOCK\\nd", "MOCK\\ce", "-", "--", ""]

printing = st.one_of(
    st.lists(st.sampled_from(WORDS), max_size=3).map(lambda ws: " ".join(["echo", *map(shlex.quote, ws)])),
    st.lists(st.sampled_from(WORDS[:2] + WORDS[5:7]), max_size=2).map(
        lambda ws: " ".join(["printf", "'%s\\n'", *map(shlex.quote, ws)])),
    st.sampled_from([
        "printf MOCK-f", "printf '%s' MOCK-g", 'echo "$x"', "echo $x", 'printf "%s|" "$x"', 'echo "$x $x"',
        'printf "%s|" "$x  ${x}" "$x $(echo MOCK-s)"',
        "pwd", "dirname a/b/c", "dirname a", "dirname /", "dirname a/", "basename a/b.txt .txt",
        "basename /", "basename a/b/", "dirname ''", "basename ''",
        "cat MOCK.txt", "cat < MOCK.txt", "cat /dev/null", "cat out.txt", "cat < out.txt", "cat - < MOCK.txt",
        "echo MOCK-h > out.txt", "echo MOCK-i >> out.txt", "echo MOCK-j >&2", "echo MOCK-k 1>&2",
        "echo MOCK-l > /dev/null | cat", "echo MOCK-m | cat", "echo MOCK-n > out.txt | cat",
        "printf MOCK-o >&2 | cat", "echo MOCK-p >&-", "echo MOCK-p >&- | cat", "{ echo MOCK-p; } >&-",
        "( echo MOCK-p >&- )", "( echo MOCK-p ) >&-", "cat <&-", "cat MOCK.txt <&-",
        "exec > log.txt", "exec >> log.txt", "exec > /dev/null", "exec >&2", "exec >&-", "exec 3>&1",
        "echo MOCK-v >&3", ": <(echo MOCK-w)", "cat <(echo MOCK-w)",
        "echo MOCK-q &",  # no `wait`: in a zsh pipeline stage it waits for the pipe's reader forever
        "sh -c 'echo -n MOCK-r'", "bash -c 'echo -e MOCK\\\\ts'", "zsh -fc 'echo MOCK\\\\nt'",
        "eval 'echo MOCK-u'",
        # Here-documents: expansions, backquotes and backslashes in the body, a quoted delimiter,
        # <<- (leading tabs go), and one sent to a file.
        "cat <<EOF\nMOCK-ha $x ${x}\nEOF", "cat <<'EOF'\nMOCK-hb $x `echo no`\nEOF",
        "cat <<-EOF\n\tMOCK-hc `echo MOCK-hd`\n\tEOF", "cat <<EOF\nMOCK-he \\$x \\\\ $(echo MOCK-hf)\nEOF",
        "cat <<EOF > out.txt\nMOCK-hg\nEOF", "cat - <<EOF | cat\nMOCK-hh $x\nEOF",
        # Several stdout redirections (zsh's MULTIOS writes to each, bash only to the last), and
        # standard error copied before standard output moves.
        "echo MOCK-ra > out.txt > /dev/null", "echo MOCK-rb > /dev/null > out.txt", "echo MOCK-rc >> out.txt > log.txt",
        "echo MOCK-rd 2>&1 > out.txt", "{ echo MOCK-re >&2; } 2>&1 > /dev/null", "exec 2>&1",
        "exec 2>&1 > log.txt",  # never read: cat out.txt into out.txt would never end
        "cat <(printf MOCK-pa) <(echo MOCK-pb)", "printf '%s-%s\\n' MOCK pc MOCK",
        'echo "$z"', 'printf "%s|" "${z+set}"',
        # A here-string (its word and a newline), descriptors named against the arrow (`1<&-`
        # closes standard output), and printf's format reused at a closed standard output.
        'cat <<< "MOCK-hs $x"', "cat <<< MOCK-ht > out.txt", "printf MOCK-pd 1<&-", "exec 1<&-",
        "{ echo MOCK-re >&2; } 2<&1", "printf '%s\\n' MOCK-pe MOCK-pf >&-",
    ]),
)
state = st.sampled_from([
    "true", "false", ":", "x=MOCK-x", "x='MOCK -n'", "x=", "typeset x", "declare x",
    "export x", "export x=MOCK-y", "readonly z=MOCK-z", "x=1 true", "cd scratch", "cd ..", "cd gone 2>/dev/null",
    "unset x", "z=MOCK-w", "z=MOCK-w true", "z=MOCK-w echo MOCK-zw", "unset z", "export z=MOCK-v", "readonly z",
    "typeset z=MOCK-t", "read z < MOCK.txt", "for z in MOCK-f; do echo MOCK-fz; done", ": $((z=1))",
    "eval 'z=MOCK-e; echo MOCK-ez'",
    # Integers, bases, zsh's padding and case, names that are not names, kept prefix assignments.
    "typeset -i z", "z=1+1", "z=0x10", "z+=1", "for z in 1+1; do :; done", "integer z 2>/dev/null",
    "let z=1+1 2>/dev/null", "(( z = 2 ))", "typeset -i 16 z 2>/dev/null", "typeset -Z 3 z 2>/dev/null",
    "typeset -u z 2>/dev/null", "typeset +i z", "export 1x 2>/dev/null", "z=MOCK-k :", "z=MOCK-l exec",
    "shopt -s xpg_echo 2>/dev/null", "set -o posix 2>/dev/null", "setopt bsd_echo 2>/dev/null",
    "setopt sh_word_split 2>/dev/null", "emulate sh 2>/dev/null", "set -o noglob", "alias e=echo",
    "exit", "exit 1", "(exit 1)", "return", "return 1 2>/dev/null",
])
atoms = st.one_of(printing, printing, state)


def compound(inner):
    name = st.integers(0, 10**6).map(lambda k: f"f{k}")
    seq = st.lists(inner, min_size=1, max_size=3).map("\n".join)
    return st.one_of(
        seq.map(lambda b: f"{{ {b}\n}}"),
        seq.map(lambda b: f"( {b}\n)"),
        st.tuples(name, seq).map(lambda t: f"{t[0]}() {{ {t[1]}\n}}\n{t[0]}\n{t[0]}"),
        st.tuples(name, seq).map(lambda t: f"{t[0]}() {{ local x; {t[1]}\n}}\n{t[0]}"),
        seq.map(lambda b: f"{{ {b}\n}} > /dev/null"),
        seq.map(lambda b: f"{{ {b}\n}} 2>&1"),
        seq.map(lambda b: f"{{ {b}\n}} > log.txt"),  # never read: no loop
        seq.map(lambda b: f"{{ {b}\n}} | cat"),
        seq.map(lambda b: f"{{ {b}\n}} > /dev/null | cat"),
        seq.map(lambda b: f"for k in 1 2; do {b}\ndone"),
        seq.map(lambda b: f"i=0; while [ $i -lt 2 ]; do {b}\ni=$((i+1)); done"),
        st.tuples(seq, seq).map(lambda t: f"if [ -d scratch ]; then {t[0]}\nelse {t[1]}\nfi"),
        st.tuples(inner, inner).map(lambda t: f"{{ {t[0]}\n}} && {{ {t[1]}\n}}"),
        st.tuples(inner, inner).map(lambda t: f"{{ {t[0]}\n}} || {{ {t[1]}\n}}"),
        seq.map(lambda b: f"eval {shlex.quote(b)}"),
        seq.map(lambda b: f"sh -c {shlex.quote(b)}"),
    )


programs = st.lists(st.recursive(atoms, compound, max_leaves=6), min_size=1, max_size=4).map(
    lambda parts: "\n".join(["x=MOCK-init", *parts]))


def matches(real: str, model: str) -> bool:
    """Whether the real output is one of the model's texts, an UNKNOWN part matching anything. So
    does a variable's name: where a new shell may have the variable from an environment the audit
    cannot see (one the program never exported to it), the audit keeps `$name`."""
    def pattern(text):
        parts = re.split(r"\x00|\$[A-Za-z_][A-Za-z0-9_]*", text)
        return "(?s:.*)".join(map(re.escape, parts))
    return any(re.fullmatch(pattern(text), real) for text in audit._choices(model))


def run_shell(shell: list[str], program: str, work: Path, env: dict) -> subprocess.CompletedProcess:
    """Run the program in its own process group, which is killed whole if it outlives the timeout
    (a background job would otherwise outlive the test)."""
    proc = subprocess.Popen([*shell, program], cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # whatever it left running in the background
        except OSError:
            pass  # the group is gone (macOS may answer EPERM for an emptied group)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def check(program: str) -> tuple[int, int]:
    """Assert the property for one program; return (known, shells) to count how often it was known."""
    known = 0
    for shell in SHELLS:
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp).resolve()
            work = layout(top)
            (work / "MOCK.txt").write_text("MOCK own research\n")
            env = {"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work), "OLDPWD": str(work)}
            proc = run_shell(shell, program, work, env)
            model = audit._shell(program, work).output
            if model is not None:
                known += 1
                assert matches(proc.stdout, model), (shell[0], program, proc.stdout, audit._choices(model))
    return known, len(SHELLS)


@settings(max_examples=int(os.environ.get("I86_DIFFERENTIAL_EXAMPLES", "300")), deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(programs)
def test_output_model_agrees_with_shells(program):
    check(program)


EXACT = [
    # Every command's output, in order, through groups, functions, loops and branches.
    "echo MOCK-a; printf '%s\\n' MOCK-b; { echo MOCK-c; echo MOCK-d; }",
    "f() { echo MOCK-a; }\nf\nf\nfor k in 1 2; do echo \"MOCK-$k\"; done",
    "i=0; while [ $i -lt 2 ]; do printf MOCK; i=$((i+1)); done; echo",
    "if [ -d scratch ]; then echo MOCK-yes; else echo MOCK-no; fi; [ -d gone ] || echo MOCK-or",
    # Quiet commands print nothing; declarations that list print the variable in zsh only.
    "x=MOCK; cd scratch; cd ..; export x; true; echo end",
    "x=MOCK; typeset x",
    # Expansions in a string keep the text between them.
    'x=MOCK-a; y=MOCK-b; echo "$x $y" "${x}  $(echo MOCK-c) $((1+2))"',
    # Files written and read back, standard error and /dev/null.
    "echo MOCK-a > out.txt; cat out.txt; cat < out.txt; echo MOCK-b >&2; echo MOCK-c > /dev/null",
    "{ echo MOCK-a; echo MOCK-b; } > out.txt; cat out.txt; cat /dev/null",
    # A redirected pipeline stage: zsh's MULTIOS sends it down the pipe too, bash does not (what
    # the file then holds is unknown in zsh, whose copier may end at the pipe first).
    "echo MOCK-a > /dev/null | cat",
    "echo MOCK-a > out.txt | cat",
    # pwd, dirname and basename end in a newline.
    "pwd; dirname a/b/c; basename a/b.txt .txt; dirname ''; basename /",
    # exit stops the program; nothing after it prints.
    "echo MOCK-a; exit; echo MOCK-b",
    "sh -c 'echo -n MOCK-a'; echo",
    # Here-documents expand the body as a double-quoted string does, backquotes included.
    "x=MOCK-x; cat <<EOF\nMOCK-a $x `echo MOCK-b` \\$x\nEOF\ncat <<'EOF'\nMOCK $x\nEOF",
    # Only the last of several stdout redirections gets the output, in bash.
    "echo MOCK-a > out.txt > /dev/null; cat out.txt; echo end",
    # zsh's arithmetic makes z an integer, so its read is arithmetic: an error that ends zsh.
    "x=MOCK-init\n{ : $((z=1))\n}\nread z < MOCK.txt\necho",
    # At a closed standard output bash keeps only the first pass of printf's format, and writes
    # it at the end, once the group's redirection is undone; a here-string ends in a newline.
    "x=MOCK-init\n{ exec >&-\nprintf '%s\\n' MOCK-a MOCK-a\n} > /dev/null",
    "cat <<< MOCK-a; cat <<< \"MOCK-b $x\" > out.txt; cat out.txt",
    # Standard error sent to standard output inside the group goes where that output goes.
    "{ { echo MOCK-j >&2; } 2>&1; } > /dev/null; echo MOCK-k",
]


# Programs whose output the model may leave unknown but must not get wrong: at a closed standard
# output bash keeps only the first pass of a printf's format, which the model follows for a printf
# alone but not inside a group, a function or an eval; standard error copied to standard output
# around a group still prints there when the group's standard output moves (the 3000-example
# search's counterexample), and after `&> f` a later `> g` leaves standard error at f.
AGREE = [
    "{ printf '%s\\n' MOCK-a MOCK-b; } >&-",
    "f() { printf '%s\\n' MOCK-a MOCK-b; }\nf >&-",
    "eval \"printf '%s\\\\n' MOCK-a MOCK-b\" >&-",
    "{ printf '%s\\n' MOCK-a MOCK-b; echo MOCK-c; } >&-; echo MOCK-d",
    "x=MOCK-init\n{ { echo MOCK-j >&2\n} > /dev/null\n} 2>&1",
    "{ echo MOCK-j >&2; } &> /dev/null > out.txt; cat out.txt; echo MOCK-k",
]


def test_output_model_agrees_where_it_may_not_know():
    for program in AGREE:
        check(program)


def test_output_model_is_known_and_right_for_plain_programs():
    for program in EXACT:
        known, shells = check(program)
        assert known == shells, program
