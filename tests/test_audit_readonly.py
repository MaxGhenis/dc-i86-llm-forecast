"""Writes to readonly variables and to a closed standard output, against bash and zsh. All MOCK.

Measured on macOS's bash 3.2 and zsh 5.9: out of POSIX mode, bash fails a readonly declaration,
`unset`, `for` and `read` and goes on, skips a readonly assignment before a command and runs the
command, and at a plain assignment drops the rest of the line it is on (bash reads a program, an
`eval` string and a sourced file a line at a time, and a compound command that spans lines is one
line) and goes on with the next, status 1; a subshell or command substitution ends. zsh ends the
shell, or the eval it is in, at each of these, except where a declaration in a function makes a new
local, and fails an external command after a readonly assignment without running it. Either way a
function the error leaves gets its locals and positional parameters back. A builtin that writes to
a closed standard output fails in bash and succeeds in zsh.

Each program is checked as the output differential checks its programs (what the shell printed is
one of the audit's texts), and the audit must flag every read of another run's MOCK answer that a
shell made, and only those, where it knows which shell runs the code.
"""

import shlex
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from i86 import audit, runners
from test_audit_output_differential import check
from test_audit_shell_differential import ANSWER, layout

# Statuses printed through && and || (the audit does not resolve `$?` in output).
PROGRAMS = [
    "readonly z=1; readonly z=2 && echo s0 || echo s1; echo z=$z",
    "readonly z=1; export z=2 && echo s0 || echo s1; echo z=$z",
    "readonly z=1; declare z=2 && echo s0 || echo s1; echo z=$z",
    "readonly z=1; readonly z && echo s0 || echo s1",
    "readonly z=1; readonly y=1 z=2 w=3 && echo s0 || echo s1; echo $y $w",
    "readonly z=1; f() { local z=2 && echo s0 || echo s1; echo in:$z; }; f && echo f0 || echo f1; echo out:$z",
    "readonly z=1; f() { typeset z=2 && echo s0 || echo s1; echo in:$z; }; f; echo out:$z",
    "readonly z=1; f() { readonly z=2 && echo s0 || echo s1; echo in:$z; }; f; echo out:$z",
    "readonly z=1; f() { export z=2 && echo s0 || echo s1; echo in:$z; }; f; echo out:$z",
    "f() { readonly z=1; }; f; z=2 && echo s0 || echo s1; echo z=$z",
    "f() { local -r z=1; }; f; z=2 && echo s0 || echo s1; echo z=$z",
    "( readonly z=1 ); z=2 && echo s0 || echo s1; echo z=$z",
    "readonly z=1; z=2 && echo s0 || echo s1",
    "readonly z=1; { z=2; echo in; }; echo after",
    "readonly z=1; ( z=2; echo in ) && echo s0 || echo s1",
    "readonly z=1; f() { z=2; echo in; }; f; echo after",
    "readonly z=1; if true; then z=2; fi; echo after",
    "readonly z=1; eval 'z=2; echo e' && echo s0 || echo s1",
    "readonly z=1; f() { z=2; echo in; }; eval 'f; echo e2' && echo s0 || echo s1",
    "readonly z=1; eval 'eval \"z=2\"; echo e2' && echo s0 || echo s1",
    "readonly z=1; eval 'readonly z=2; echo e2' && echo s0 || echo s1",
    "readonly z=1; z=2 true && echo s0 || echo s1",
    "readonly z=1; z=2 echo hi && echo s0 || echo s1",
    "readonly z=1; z=2 /bin/echo hi && echo s0 || echo s1",
    "readonly z=1; f() { echo f=$z; }; z=2 f && echo s0 || echo s1",
    "readonly z=1; x=1 z=2 y=3 && echo s0 || echo s1; echo $x $y",
    "readonly z=1; unset z && echo s0 || echo s1; echo z=$z",
    "readonly z=1; y=1; unset y z && echo s0 || echo s1; echo y=$y z=$z",
    "readonly z=1; for z in a b; do echo in=$z; done && echo s0 || echo s1",
    "readonly z=1; read z < /dev/null && echo s0 || echo s1",
    "readonly z=1; : $((z=3)) && echo s0 || echo s1",
    "readonly z=1; z=2 | cat && echo s0 || echo s1",
    "readonly z=1; echo | { z=2; echo in; } && echo s0 || echo s1",
    "readonly z=1; sh -c 'readonly z=2 && echo c0 || echo c1; echo cz=$z'",
    "for k in 1 2; do readonly z=MOCK-z && echo s0 || echo s1; done",
    "y=1; if [ -d gone ]; then unset y; fi; echo \"y=$y\"",
    "f() { z=0; [ -d gone ] && local z=1; z=2; }; z=5; f; echo z=$z",
    "f() { [ -d scratch ] && local z=1; z=2; }; z=5; f; echo z=$z",
    # bash drops the rest of the line, and goes on with the next.
    "readonly z=1\nz=2; echo same\necho next",
    "readonly z=1\n{ z=2\necho in\n}\necho after",
    "readonly z=1\nf() { z=2\necho in\n}\nf && echo s0 || echo s1\necho next",
    "readonly z=1\nf() { z=2\n}\nf\n[ $? = 1 ] && echo one",
    "readonly z=1\nfor k in 1 2; do\nz=2\necho in$k\ndone\necho after",
    "readonly z=1\necho a;\nz=2\necho b",
    "readonly z=1\necho a; z=2 # c\necho b",
    "readonly z=1\neval 'z=2; echo e1\necho e2' && echo s0 || echo s1",
    "readonly z=1\neval 'echo a\nz=2' && echo s0 || echo s1",
    "readonly z=1\neval 'z=2\ntrue' && echo s0 || echo s1",
    "readonly z=1\nf() { eval 'z=2\necho e2'; echo f; }\nf",
    "readonly z=1\nprintf 'z=2\\necho src\\n' > s.sh\n. ./s.sh && echo s0 || echo s1\necho next",
    "readonly z=1\n( z=2\necho sub ) && echo s0 || echo s1",
    "readonly z=1\nx=$(z=2\necho in); echo \"x=$x\"",
    "readonly z=1\nbash -c 'z=2\necho c' && echo s0 || echo s1",
    # zsh's `emulate MODE -c` ends its code at the error, as eval does; bash has no emulate.
    "readonly z=1; emulate sh -c 'z=2; echo in' 2>/dev/null && echo s0 || echo s1; echo after",
    "readonly z=1; f() { z=2; echo in; }; emulate sh -c f 2>/dev/null && echo s0 || echo s1",
    "readonly z=1; emulate sh -c 'eval z=2; echo in' 2>/dev/null && echo s0 || echo s1",
    # A function the error leaves gets its locals and positional parameters back.
    "readonly z=1\nf() { local x=in; z=2; }\nx=out\nf\necho x=$x",
    "readonly z=1\nf() { local x=in; eval 'z=2'; echo x=$x; }\nx=out\nf\necho x=$x",
    "readonly z=1\nf() { set -- a b; z=2; }\nset -- o\nf\necho \"$# $1\"",
    "readonly z=1\nf() { local x=in; z=2; }\nx=out\neval 'f\necho e=$x'\necho x=$x",
    # A closed standard output.
    "echo MOCK-a >&- && echo s0 || echo s1",
    "printf MOCK-a >&- && echo s0 || echo s1",
    "pwd >&- && echo s0 || echo s1",
    "cat MOCK.txt >&- && echo s0 || echo s1",
    "{ echo MOCK-p; } >&- && echo s0 || echo s1",
    "{ echo MOCK-p; true; } >&- && echo s0 || echo s1",
    "f() { echo a; }; f >&- && echo s0 || echo s1",
    "eval 'echo a' >&- && echo s0 || echo s1",
    "builtin echo a >&- && echo s0 || echo s1",
    "printf '' >&- && echo s0 || echo s1",
    "for k in 1 2; do printf '%s\\n' 'MOCK b'\necho MOCK-p >&-\necho MOCK-p >&-\ndone",
    # Options other shells lack.
    "setopt sh_word_split 2>/dev/null && echo s0 || echo s1",
    "setopt nosuchopt 2>/dev/null && echo s0 || echo s1",
    "unsetopt no_bsd_echo 2>/dev/null && echo s0 || echo s1",
    "shopt -s xpg_echo 2>/dev/null && echo s0 || echo s1",
    "zsh -fc 'shopt -s xpg_echo 2>/dev/null && echo s0 || echo s1; setopt bsd_echo && echo t0 || echo t1'",
    # MULTIOS holds as a group's redirections are made, whatever the group sets after.
    "{ { echo MOCK-m | cat\necho\nemulate sh 2>/dev/null\n} > /dev/null | cat\n}",
]


def test_programs_agree_with_shells():
    for program in PROGRAMS:
        known, shells = check("x=MOCK-init\n" + program)
        assert known, program  # the audit knows the output for at least one shell


# (code, which shells read the MOCK answer): the code runs as `bash -c` and `zsh -f -c`, so the
# audit knows the shell; it must flag exactly those reads.
READS = [
    ("readonly z=1; readonly z=2 || cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; z=2 || cat ../opus-2/draft.json", set()),
    ("readonly z=1; eval 'z=2'; cat ../opus-2/draft.json", {"bash", "zsh"}),
    ("readonly z=1; z=2 /bin/echo hi || cat ../opus-2/draft.json", {"zsh"}),
    ("readonly z=1; z=2 true && cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; for z in 1; do :; done || cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; unset z || cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; read z < /dev/null || cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; f() { local z=2 || cat ../opus-2/draft.json; }; f", {"bash"}),
    ("readonly z=1; f() { local z=2 && cat ../opus-2/draft.json; }; f", {"zsh"}),
    ("f() { readonly z=1; }; f; z=2; cat ../opus-2/draft.json", {"zsh"}),
    ("echo ../opus-2/draft.json >&- || cat ../opus-2/draft.json", {"bash"}),
    ("{ { echo MOCK-p; } >&-; } || { cat ../opus-2/draft.json; }", {"bash"}),
    ("pwd >&- && cat ../opus-2/draft.json", {"zsh"}),
    ("setopt sh_word_split 2>/dev/null || cat ../opus-2/draft.json", {"bash"}),
    ("shopt -s xpg_echo 2>/dev/null || cat ../opus-2/draft.json", {"zsh"}),
    ("readonly z=1\nz=2\ncat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; emulate sh -c 'z=2' 2>/dev/null; cat ../opus-2/draft.json", {"bash", "zsh"}),
    ("readonly z=1; emulate sh -c 'z=2; cat ../opus-2/draft.json' 2>/dev/null", set()),
    ("readonly z=1\nz=2; cat ../opus-2/draft.json", set()),
    ("readonly z=1\neval 'z=2\ncat ../opus-2/draft.json'", {"bash"}),
    ("readonly z=1\nf() { local d=.; z=2; }\nd=MOCK\nf\ncat \"$d./opus-2/draft.json\"", set()),
    ("readonly z=1\nf() { local d=MOCK; z=2; }\nd=.\nf\ncat \"$d./opus-2/draft.json\"", {"bash"}),
    ("readonly z=1\nf() { set -- .; z=2; }\nset -- MOCK\nf\ncat \"$1./opus-2/draft.json\"", set()),
]
SHELL_RUNS = {"bash": ["/bin/bash", "--norc", "--noprofile", "-c"], "zsh": ["/bin/zsh", "-f", "-c"]}


def test_reads_are_flagged_exactly():
    for code, readers in READS:
        for name, shell in SHELL_RUNS.items():
            with tempfile.TemporaryDirectory() as tmp:
                top = Path(tmp).resolve()
                work = layout(top)
                proc = subprocess.run([*shell, code], cwd=work, capture_output=True, text=True, timeout=20,
                                      stdin=subprocess.DEVNULL,
                                      env={"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work)})
                read = ANSWER in proc.stdout
                assert read == (name in readers), (name, code, proc.stdout, proc.stderr)
                roots = [top / "repository", top / "staging"]
                with mock.patch.object(runners, "WORK", top / "work"), \
                        mock.patch.object(audit, "protected_roots", lambda: roots), \
                        mock.patch.object(audit, "HOME", top / "home"):
                    command = " ".join([*map(shlex.quote, shell[:-1]), "-c", shlex.quote(code)])
                    verdict, why = audit.check_call("shell", {"command": command}, work, roots)
                assert (verdict in {"violation", "suspect"}) == read, (name, code, verdict, why)
