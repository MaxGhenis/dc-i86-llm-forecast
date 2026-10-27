"""Round-13 shell-model findings, each measured on macOS's /bin/bash 3.2, /bin/sh, /bin/dash and
/bin/zsh 5.9 as test_audit_readonly and test_audit_output_differential measure them. Every layout is
a temporary MOCK one; the answer read is the MOCK draft of another run (`../opus-2/draft.json`).

The misses: a null command's status in bash, sh and dash; zsh's null command (the error that ends
only an `eval`, a sourced file or `emulate -c`; READNULLCMD for one input redirection on any
descriptor; a builtin or function NULLCMD, which runs in the shell; words that expand to nothing);
zsh's precommand modifiers `noglob` and `builtin`; prefix assignments before an alias or a
function defined in some branches; zsh's MULTIOS joining of standard input."""

import shlex
import tempfile
from pathlib import Path

import pytest

from i86 import audit
from test_audit_output_differential import check, matches, run_shell
from test_audit_readonly import SHELL_RUNS, flagged, layout
from test_review_r12_shell import flagged_in

R = "cat ../opus-2/draft.json"
P = "printf '../opus-2/draft.json\\n'"

# (program, the shells that read the answer), as measured. The audit flags every shell that reads;
# it may flag others too.
READS = [
    # zsh's "redirection with no command" ends only the eval or the sourced file.
    (f"unset NULLCMD; eval '> /dev/null' 2>/dev/null; {R}", {"bash", "sh", "dash", "zsh"}),
    (f"unset NULLCMD; echo '> /dev/null' > s; . ./s 2>/dev/null; {R}", {"bash", "sh", "dash", "zsh"}),
    # A null command's status is its last command substitution's (POSIX; zsh gives 0).
    (f'> /dev/null"$(false)" || {R}', {"bash", "sh", "dash"}),
    # zsh runs READNULLCMD for one input redirection on any descriptor.
    (f"NULLCMD=:; {P} | 2</dev/null | xargs cat 2>/dev/null", {"zsh"}),
    # zsh's MULTIOS joins a pipe with `<`.
    (f"{P} | xargs cat < /dev/null 2>/dev/null", {"zsh"}),
    (f"NULLCMD=cat; READNULLCMD=cat; {P} | < /dev/null | xargs cat 2>/dev/null", {"zsh"}),
    # zsh runs NULLCMD or READNULLCMD where the words expand to nothing.
    (f"e=; {P} > f; $e < f | xargs cat 2>/dev/null", {"zsh"}),
    # A builtin or function NULLCMD runs in zsh itself, which keeps what its words assign.
    (f'NULLCMD=echo; > "${{y:=/dev/null}}"; [ "${{y-unset}}" = /dev/null ] && {R}', {"bash", "sh", "dash", "zsh"}),
    (f'NULLCMD=cat; READNULLCMD=echo; < "${{y:=/dev/null}}"; [ "${{y-unset}}" = /dev/null ] && {R}',
     {"bash", "sh", "dash", "zsh"}),
    (f'f() {{ :; }}; NULLCMD=f; > "${{y:=/dev/null}}"; [ "${{y-unset}}" = /dev/null ] && {R}',
     {"bash", "sh", "dash", "zsh"}),
    # zsh's `noglob` and `builtin` are precommand modifiers: the command after them decides.
    (f'noglob cat < "${{x?}}" 2>/dev/null; {R}', {"bash", "sh", "zsh"}),
    (f'builtin cat < "${{x?}}" 2>/dev/null; {R}', {"zsh"}),
    (f'noglob cat < "${{x:=/dev/null}}"; [ "${{x-unset}}" = unset ] && {R}', {"bash", "sh", "zsh"}),
    (f'builtin noglob cat < "${{x?}}" 2>/dev/null; {R}', {"zsh"}),
    # A prefix assignment before an alias of a builtin (zsh expands an alias inside `eval`).
    (f"{P} > f; alias rd=read; eval 'IFS= rd -r p < f'; cat \"$p\"", {"sh", "dash", "zsh"}),
]


@pytest.mark.parametrize("code,readers", READS, ids=[c for c, _ in READS])
def test_every_shell_that_reads_is_flagged(code, readers):
    """The model flags the call in each shell that reads another run's MOCK answer. The measurement
    half asserts which shells read, so a change in the shells shows too."""
    for name in SHELL_RUNS:
        read, flag, seen = flagged(code, name)
        assert read == (name in readers), ("measurement", name, code, seen)
        assert flag or not read, ("miss", name, code, seen)


def test_a_prefix_assignment_keeps_what_a_function_defined_in_some_branches_assigns():
    """With X set in the environment, zsh defines g, runs it in the shell and keeps p, so every
    shell reads the answer; the model follows both ways g may be defined."""
    code = f'{P} > f; [ -n "$X" ] && g() {{ IFS= read -r p; }}; y=1 g < f 2>/dev/null; cat "$p"'
    for name in SHELL_RUNS:
        read, flag, seen = flagged_in(code, name, {"X": "1"})
        assert read, ("measurement", name, seen)
        assert flag, ("miss", name, seen)


def model_in(name: str, program: str) -> tuple[str, str | None]:
    """The shell's standard output for `program` in a MOCK layout, and the model's for the same call
    wrapped as `flagged` wraps it (`/bin/zsh -f -c '...'` and the like), so the model knows the shell."""
    shell = SHELL_RUNS[name]
    with tempfile.TemporaryDirectory() as tmp:
        top = Path(tmp).resolve()
        work = layout(top)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work), "OLDPWD": str(work)}
        proc = run_shell(shell, program, work, env)
        command = " ".join([*map(shlex.quote, shell[:-1]), "-c", shlex.quote(program)])
        return proc.stdout, audit._shell(command, work).output


# (shell, program): the model's output for the named shell is the shell's, or unknown.
OUTPUTS = [
    # An empty or unset NULLCMD ends zsh, even under SH_NULLCMD and for a lone `<` with READNULLCMD set.
    ("zsh", "NULLCMD=; READNULLCMD=cat; < /dev/null; echo MOCK-after"),
    ("zsh", "emulate sh 2>/dev/null; NULLCMD=; < /dev/null; echo MOCK-after"),
    ("zsh", "setopt shnullcmd 2>/dev/null; unset NULLCMD; < /dev/null; echo MOCK-after"),
    # READNULLCMD for `2< f`; the error in an eval ends only the eval.
    ("zsh", "printf 'MOCK-f\\n' > f; NULLCMD=echo; READNULLCMD=cat; 2< f"),
    ("zsh", 'unset NULLCMD; eval "> /dev/null" 2>/dev/null; echo MOCK-after'),
    # MULTIOS input: the pipe and then the file, or the file twice.
    ("zsh", "printf 'MOCK-f\\n' > f; echo MOCK-in | cat < f"),
    ("zsh", "printf 'MOCK-f\\n' > f; cat < f < f"),
    # A null command's status is its last command substitution's.
    ("bash", '> /dev/null"$(false)" || echo MOCK-or'),
    ("dash", '> /dev/null"$(false)" || echo MOCK-or'),
]


@pytest.mark.parametrize("name,program", OUTPUTS, ids=[f"{n}:{p}" for n, p in OUTPUTS])
def test_output_for_the_named_shell(name, program):
    """The model's standard output for a call that names its shell is that shell's, or unknown."""
    real, model = model_in(name, program)
    assert model is None or matches(real, model), (name, program, real, audit._choices(model))


@pytest.mark.parametrize("program", [
    "NULLCMD=; READNULLCMD=cat; < /dev/null; echo MOCK-after",
    "printf 'MOCK-f\\n' > f; echo MOCK-in | cat < f",
    "printf 'MOCK-f\\n' > f; cat < f < f",
])
def test_output_model_agrees(program):
    """The output differential (bash and zsh, the shell not named) agrees on these."""
    check(program)
