"""Writes to readonly variables and to a closed standard output, against bash, zsh, sh and dash.
All MOCK.

Measured on macOS's bash 3.2, sh (bash's POSIX mode), dash and zsh 5.9: out of POSIX mode, bash
fails a readonly declaration, `unset`, `for` and `read` and goes on, skips a readonly assignment
before a command and runs the command, and at a plain assignment drops the rest of the line it is on
(bash reads a program, an `eval` string and a sourced file a line at a time, and a compound command
that spans lines is one line) and goes on with the next, status 1; a subshell or command
substitution ends. sh and dash exit at most of these; sh's `readonly` and `export` fail instead
before `&&` or `||`, in a condition and after `!`, outside an eval, a sourced file and a command
substitution. zsh ends the shell, or the eval it is in, at each of these, except where a
declaration in a function makes a new local, and fails an external command after a readonly
assignment without running it. Either way a function the error leaves gets its locals and
positional parameters back. `command` and `builtin`, arithmetic, `printf -v`, `getopts`, traps and
declaration options are among the reads below. A builtin that writes to a closed standard output
fails in bash and succeeds in zsh. sh and dash reject a line with a process substitution as they
read it, before any of it runs: dash anywhere in the line, sh where `<(` starts a word outside a
command substitution; dash then exits, and sh ends the eval or sourced file, else the shell.

Each program is checked as the output differential checks its programs (what the shell printed is
one of the audit's texts), and the audit must flag every read of another run's MOCK answer that a
shell made, and only those (OVER lists the known exceptions, which may only flag more), where it
knows which shell runs the code.
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


# (code, which shells read the MOCK answer): the code runs as `bash -c`, `zsh -f -c`, `sh -c` and
# `dash -c`, so the audit knows the shell, except that `sh` may be bash's POSIX mode or dash (macOS's
# /bin/sh runs the one /private/var/select/sh names). It must flag exactly those reads, and under sh
# those that either shell makes.
READS = [
    ("readonly z=1; readonly z=2 || cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; z=2 || cat ../opus-2/draft.json", set()),
    ("readonly z=1; eval 'z=2'; cat ../opus-2/draft.json", {"bash", "zsh"}),
    ("readonly z=1; z=2 /bin/echo hi || cat ../opus-2/draft.json", {"zsh"}),
    ("readonly z=1; z=2 true && cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; for z in 1; do :; done || cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; unset z || cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; read z < /dev/null || cat ../opus-2/draft.json", {"bash", "dash", "sh"}),
    ("readonly z=1; f() { local z=2 || cat ../opus-2/draft.json; }; f", {"bash", "sh"}),
    ("readonly z=1; f() { local z=2 && cat ../opus-2/draft.json; }; f", {"zsh"}),
    ("f() { readonly z=1; }; f; z=2; cat ../opus-2/draft.json", {"zsh"}),
    ("echo ../opus-2/draft.json >&- || cat ../opus-2/draft.json", {"bash", "dash", "sh"}),
    ("{ { echo MOCK-p; } >&-; } || { cat ../opus-2/draft.json; }", {"bash", "dash", "sh"}),
    ("pwd >&- && cat ../opus-2/draft.json", {"zsh"}),
    ("setopt sh_word_split 2>/dev/null || cat ../opus-2/draft.json", {"bash", "dash", "sh"}),
    ("shopt -s xpg_echo 2>/dev/null || cat ../opus-2/draft.json", {"dash", "zsh"}),
    ("readonly z=1\nz=2\ncat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; emulate sh -c 'z=2' 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; emulate sh -c 'z=2; cat ../opus-2/draft.json' 2>/dev/null", set()),
    ("readonly z=1\nz=2; cat ../opus-2/draft.json", set()),
    ("readonly z=1\neval 'z=2\ncat ../opus-2/draft.json'", {"bash"}),
    ("readonly z=1\nf() { local d=.; z=2; }\nd=MOCK\nf\ncat \"$d./opus-2/draft.json\"", set()),
    ("readonly z=1\nf() { local d=MOCK; z=2; }\nd=.\nf\ncat \"$d./opus-2/draft.json\"", {"bash"}),
    ("readonly z=1\nf() { set -- .; z=2; }\nset -- MOCK\nf\ncat \"$1./opus-2/draft.json\"", set()),
    ("readonly z=1; readonly z=2 && echo X; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; true && readonly z=2; cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; if readonly z=2; then :; fi; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; ! readonly z=2; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; while readonly z=2; do :; done; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; until readonly z=2; do break; done; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; f(){ readonly z=2; cat ../opus-2/draft.json; }; f || echo X", {"bash", "sh", "zsh"}),
    ("readonly z=1; f(){ readonly z=2; cat ../opus-2/draft.json; }; f", {"bash", "zsh"}),
    ("readonly z=1; { readonly z=2; cat ../opus-2/draft.json; } || echo X", {"bash", "sh"}),
    ("readonly z=1; ( readonly z=2; cat ../opus-2/draft.json ) || echo X", {"bash", "sh"}),
    ("readonly z=1; eval 'readonly z=2' || cat ../opus-2/draft.json", {"bash", "zsh"}),
    ("readonly z=1; eval 'readonly z=2 || cat ../opus-2/draft.json'", {"bash", "sh"}),
    ("readonly z=1; export z=2 || cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; export z=2; cat ../opus-2/draft.json", {"bash"}),
    ("readonly z=1; readonly z=2 || readonly z=3; cat ../opus-2/draft.json", {"bash"}),
    ("export -Z 2>/dev/null || cat ../opus-2/draft.json", {"bash", "sh"}),
    ("export -Z 2>/dev/null; cat ../opus-2/draft.json", {"bash", "zsh"}),
    ("readonly z=1; if true; then readonly z=2; cat ../opus-2/draft.json; fi || echo X", {"bash", "sh"}),
    ("readonly z=1; case a in a) readonly z=2; cat ../opus-2/draft.json;; esac || echo X", {"bash", "sh"}),
    ("readonly z=1; command eval 'readonly z=2' || cat ../opus-2/draft.json", {"bash", "dash", "zsh"}),
    ("readonly z=1; f(){ eval 'readonly z=2'; cat ../opus-2/draft.json; }; f || echo X", {"bash", "zsh"}),
    ("readonly z=1; printf 'readonly z=2\ncat ../opus-2/draft.json\n' > s.sh; . ./s.sh || echo X", {"bash"}),
    ("readonly z=1; sh -c 'readonly z=2; cat ../opus-2/draft.json' || echo X", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; for k in 1; do readonly z=2; cat ../opus-2/draft.json; done || echo X", {"bash", "sh"}),
    ("shopt -p xpg_echo >/dev/null 2>&1 || cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("x=.; f() { local x=MOCK; break; }; for k in 1; do f; done; cat \"$x./opus-2/draft.json\"", {"bash", "dash", "sh", "zsh"}),
    ("x=MOCK; f() { local x=.; break; }; for k in 1; do f; done; cat \"$x./opus-2/draft.json\"", set()),
    ("set -- .; f() { set -- MOCK; continue; }; for k in 1 2; do f; done; cat \"$1./opus-2/draft.json\"", {"bash", "dash", "sh", "zsh"}),
    ("x=.; f() { local x=MOCK; g() { local x=NOPE; break 2; }; g; }; for k in 1; do for j in 1; do f; done; done; cat \"$x./opus-2/draft.json\"", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; command readonly z=2 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; builtin readonly z=2 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh"}),
    ("readonly z=1; command export z=2 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; command unset z 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; command eval 'z=2' 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "zsh"}),
    ("readonly z=1; command eval 'readonly z=2; cat ../opus-2/draft.json' 2>/dev/null", {"bash"}),
    ("readonly z=1; z=2 command true 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    ("readonly z=1; emulate sh -c 'command readonly z=2; cat ../opus-2/draft.json' 2>/dev/null", {"zsh"}),
    ("command cd scratch; cat ../opus-2/draft.json", {"zsh"}),
    ("builtin cd scratch 2>/dev/null; cat ../opus-2/draft.json", {"dash"}),
    ("f() { cd scratch; }; command f 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("export -r z=1 2>/dev/null; z=2; cat ../opus-2/draft.json", {"bash"}),
    ("readonly -x z=1 2>/dev/null; z=2; cat ../opus-2/draft.json", {"bash"}),
    ("declare -r z=1 2>/dev/null; z=2; cat ../opus-2/draft.json", {"dash"}),
    ("readonly -n z=1 2>/dev/null; z=2; cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    ("typeset -n z=1 2>/dev/null; z=2; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("shopt -Z 2>/dev/null || cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("shopt -sZ xpg_echo 2>/dev/null || cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("shopt -p xpg_echo >/dev/null || cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("emulate zsh -o no_such_option -c 'cd scratch' 2>/dev/null || cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("emulate sh +o no_such 2>/dev/null || cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("trap 'cat ../opus-2/draft.json' EXIT; cd scratch", set()),
    ("trap 'cat ../opus-2/draft.json' EXIT; exit 3", {"bash", "dash", "sh", "zsh"}),
    ("(trap 'cat ../opus-2/draft.json' EXIT; true)", {"bash", "dash", "sh", "zsh"}),
    ("f(){ trap 'cd ..' EXIT; }; f; cat opus-2/draft.json", {"zsh"}),
    ("trap 'cd ..' INT; kill -INT $$; cat opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("trap 'cd ..' EXIT; cat opus-2/draft.json", set()),
    ("(trap 'cd ..' EXIT; true); cat opus-2/draft.json", set()),
    ("trap 'cat ../opus-2/draft.json' INT; kill -INT $$", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; : $((z=2)) 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; eval ': $((z=2))' 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    ("readonly z=1; (( z=2 )) 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; let z=2 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    ("readonly z=1; for ((z=0; z<1; z++)); do :; done 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; printf -v z %s 2 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh"}),
    ("readonly z=1; getopts a z -a 2>/dev/null; cat ../opus-2/draft.json", {"bash", "dash", "sh"}),
    ("printf -v d %s . 2>/dev/null; cat \"$d./opus-2/draft.json\"", {"bash", "sh", "zsh"}),
    # Lines sh and dash reject as they read them, at a process substitution.
    ("echo a; : <(echo b)\ncat ../opus-2/draft.json", {"bash", "zsh"}),
    ("eval ': <(echo b)'; cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    ("if false; then : <(echo b); fi\ncat ../opus-2/draft.json", {"bash", "zsh"}),
    ("f() { : <(echo b); }\ncat ../opus-2/draft.json", {"bash", "zsh"}),
    ('echo "$(: <(echo b))"\ncat ../opus-2/draft.json', {"bash", "sh", "zsh"}),
    ("eval 'cat ../opus-2/draft.json\n: <(echo b)'", {"bash", "dash", "sh", "zsh"}),
    ("x=<(echo b)\ncat ../opus-2/draft.json", {"bash", "sh", "zsh"}),  # sh: plain text, glued or a value
    ("echo x<(echo b)\ncat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    # dash and zsh have no shopt; dash's local outside a function ends the shell.
    ("shopt -s xpg_echo 2>/dev/null && cat ../opus-2/draft.json", {"bash", "sh"}),
    ("local x=1 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    # A trap's code runs when the signal comes, with the variables as they are then.
    ("trap 'cat \"$f\"' INT; f=../opus-2/draft.json; kill -INT $$", {"bash", "dash", "sh", "zsh"}),
    ("a=/x; b=/y; trap 'cat \"$a$b\"' INT; a=$(cd .. && pwd); b=/opus-2/draft.json; kill -INT $$",
     {"bash", "dash", "sh", "zsh"}),
    # zsh's readonly in a function is global under POSIX_BUILTINS; typeset -r stays local.
    ("f(){ emulate sh; readonly z=1; }; f; f; cat ../opus-2/draft.json", {"bash"}),
    ("setopt posix_builtins 2>/dev/null; f(){ readonly z=1; }; f; f 2>/dev/null; cat ../opus-2/draft.json", {"bash"}),
    ("emulate sh 2>/dev/null; f(){ typeset -r z=1; }; f; f; cat ../opus-2/draft.json", {"bash", "dash", "sh", "zsh"}),
    # `set -o` with an option the shell lacks: bash fails, dash exits (also in an eval), zsh ends the
    # eval or, under POSIX_BUILTINS, the shell; so do zsh's readonly and export at a readonly variable.
    ("eval 'set -o no_such' 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    ("emulate sh 2>/dev/null; eval 'set -o no_such' 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh"}),
    ("readonly z=1; emulate sh 2>/dev/null; eval 'readonly z=2' 2>/dev/null; cat ../opus-2/draft.json", {"bash"}),
    ("set -o pipefail 2>/dev/null; cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    ("eval 'f(){ set -o posix 2>/dev/null; }; f; cat ../opus-2/draft.json'; cat ../opus-2/draft.json",
     {"bash", "sh", "zsh"}),
    # A function's body, read where it is defined, and a trap's code write nothing then.
    ("echo ../opus-2/draft.json > p.txt; f(){ echo . > p.txt; }; cat p.txt | xargs cat", {"bash", "dash", "sh", "zsh"}),
    ("echo ../opus-2/draft.json > p.txt; trap 'echo . > p.txt' INT; cat p.txt | xargs cat", {"bash", "dash", "sh", "zsh"}),
    # Integers (measured on zsh 5.9, bash 3.2 and its sh; dash has none): an assignment to one is
    # arithmetic, also by read, for, `+=` and a declaration's value. Native zsh makes one of a variable
    # an arithmetic assignment creates (not of one that exists, under emulate sh, or where it does not
    # run), and shows one given a value in a base in that base; its `export p` and `readonly p` make p.
    (': $((p=1)); p=abc; [ "$p" = 0 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('let p=1; p=abc; [ "$p" = 0 ] && cat ../opus-2/draft.json', {'zsh'}),
    (': $((p=1)); read p <<< \'abc\'; [ "$p" = 0 ] && cat ../opus-2/draft.json', {'zsh'}),
    (': $((p=1)); for p in abc; do [ "$p" = 0 ] && cat ../opus-2/draft.json; done', {'zsh'}),
    (': $((p=1)); p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'zsh'}),
    (': $((p=1)); p+=1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('p=; : $((p=1)); p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', set()),
    ('export p; : $((p=1)); p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', set()),
    ('emulate sh; : $((p=1)); p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', set()),
    ('true || : $((p=1)); p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', set()),
    ('typeset -i p; p=abc; [ "$p" = 0 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('typeset -i p; read p <<< 1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('typeset -i p; for p in 1+1; do [ "$p" = 2 ] && cat ../opus-2/draft.json; done', {'bash', 'sh', 'zsh'}),
    ('typeset -i p; p+=1; p+=1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('typeset -i p; export p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('typeset -i p; readonly p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('q=0x10; typeset -i p; p=q; [ "$p" = 16 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('p=1+1; typeset -i p; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('integer p; p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('f(){ local -i p; p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json; }; f', {'bash', 'sh', 'zsh'}),
    ('typeset -i p; f(){ local p; p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json; }; f', set()),
    ('typeset -i p; f(){ local p; }; f; p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json',
     {'bash', 'sh', 'zsh'}),
    ('typeset -i p; unset p; p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', set()),
    ('typeset -i p; (p=1+); cat ../opus-2/draft.json', {'bash', 'dash', 'sh', 'zsh'}),
    ('typeset -i p; p=1+1 :; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'sh'}),
    ('typeset -i p; p=1+1 eval \'[ "$p" = 2 ] && cat ../opus-2/draft.json\'', {'zsh'}),
    ('typeset -i p; p=1+1 eval \'[ "$p" = 1+1 ] && cat ../opus-2/draft.json\'', {'bash', 'dash', 'sh'}),
    ('float p; p=1+1; [ "$p" = 2 ] || cat ../opus-2/draft.json', {'bash', 'dash', 'sh', 'zsh'}),
    ('typeset -i p; p=0x10; [ "$p" = 16#10 ] && cat ../opus-2/draft.json', {'zsh'}),
    (': $((p=0x10)); [ "$p" = 16#10 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -i p; p=0x10; p=5; [ "$p" = 16#5 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -i p; p=0x10; [ "$p" != 16 ] && cat ../opus-2/draft.json', {'dash', 'zsh'}),
    ('typeset -i 16 p; p=255; [ "$p" = 255 ] || cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -i 2 p=5; [ "$p" = 5 ] || cat ../opus-2/draft.json', {'dash', 'zsh'}),
    ('export p; [ -n "${p+x}" ] && cat ../opus-2/draft.json', {'zsh'}),
    ('readonly p; [ -n "${p+x}" ] && cat ../opus-2/draft.json', {'zsh'}),
    ('emulate sh; typeset -i p; [ -n "${p+x}" ] || cat ../opus-2/draft.json', {'dash', 'zsh'}),
    # zsh's padding (-L, -R, -Z) and case (-l, -u) attributes change every value the variable takes;
    # unset and +Z drop them, and a local masks them.
    ('typeset -Z 3 p; p=1; [ "$p" = 001 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -R 3 p; p=1; [ "$p" = 1 ] || cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -L 3 p; p=1; [ "$p" = 1 ] || cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -l p; p=AbC; [ "$p" = abc ] && cat ../opus-2/draft.json', {'zsh'}),
    ('p=AbC; typeset -u p; [ "$p" = AbC ] || cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -Z 3 p; read p <<< 7; [ "$p" = 7 ] || cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -Z 3 p; for p in 8; do [ "$p" = 8 ] || cat ../opus-2/draft.json; done', {'zsh'}),
    ('typeset -Z 3 p; (( p = 5 )); [ "$p" = 5 ] || cat ../opus-2/draft.json', {'dash', 'zsh'}),
    ('typeset -Z 3 p; unset p; p=1; [ "$p" = 1 ] || cat ../opus-2/draft.json', set()),
    ('typeset -Z 3 p; typeset +Z p; p=1; [ "$p" = 1 ] || cat ../opus-2/draft.json', set()),
    ('typeset -u p; f(){ local p; p=ab; [ "$p" = ab ] || cat ../opus-2/draft.json; }; f', set()),
    ('typeset -u p; f(){ local p; }; f; p=cd; [ "$p" = cd ] || cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -u p; export p=ab; [ "$p" = ab ] || cat ../opus-2/draft.json', {'zsh'}),
    ('integer -Z 3 p; p=1; [ "$p" = 1 ] || cat ../opus-2/draft.json', {'zsh'}),
    # A declaration's word that is not a name: bash fails it (declaring the rest), dash exits at it
    # (under `command`, fails there), zsh ends the eval or the shell; zsh takes a number right after
    # an option that takes one, and digits in an option word only there.
    ('typeset -x1 p || cat ../opus-2/draft.json', {'bash', 'dash', 'sh', 'zsh'}),
    ('typeset -i 16 p || cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    ('typeset -i -- 16 p; cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    ('integer 16 p; cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    ('float 3 p; cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    ('declare 1x || cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    ('export 1x || cat ../opus-2/draft.json', {'bash', 'sh'}),
    ('readonly 1x || cat ../opus-2/draft.json', {'bash', 'sh'}),
    ('typeset 1x; cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    ('export a-b || cat ../opus-2/draft.json', {'bash', 'sh'}),
    ('f(){ local 1x || cat ../opus-2/draft.json; }; f', {'bash', 'sh'}),
    ("eval 'export 1x'; cat ../opus-2/draft.json", {'bash', 'sh', 'zsh'}),
    ('command export y=1 1x z=2; [ -z "${z+x}" ] && cat ../opus-2/draft.json', {'dash', 'zsh'}),
    ("emulate sh; eval 'export 1x'; cat ../opus-2/draft.json", {'bash', 'sh'}),
    ('f(){ typeset 1x; }; f; cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    ('v=1x; export $v || cat ../opus-2/draft.json', {'bash', 'sh'}),
    ('export "$(date +x%s)"; cat ../opus-2/draft.json', {'bash', 'dash', 'sh', 'zsh'}),
    # A variable one branch sets and another never does is unset in that one.
    ('if [ -e nosuch ]; then p=; fi; [ -n "${p+x}" ] || cat ../opus-2/draft.json',
     {'bash', 'dash', 'sh', 'zsh'}),
    ('[ -e nosuch ] && p=; [ -n "${p+x}" ] || cat ../opus-2/draft.json', {'bash', 'dash', 'sh', 'zsh'}),
    ('case $(cat nosuch 2>/dev/null) in x) p=;; esac; [ -n "${p+x}" ] || cat ../opus-2/draft.json',
     {'bash', 'dash', 'sh', 'zsh'}),
    # One the shell's environment may give stays as it may be there.
    ('[ -d gone ] && unset HOME; cat "${HOME+../opus-2/draft.json}"', {'bash', 'dash', 'sh', 'zsh'}),
    # Assignments before a command: sh and dash keep them after a special builtin (an exec with only
    # redirections too), sh after a function, zsh after a bare exec; bash puts the old values back.
    ('x=a; x=b :; [ "$x" = b ] && cat ../opus-2/draft.json', {'dash', 'sh'}),
    ('x=a; x=b eval :; [ "$x" = b ] && cat ../opus-2/draft.json', {'dash', 'sh'}),
    ('x=a; f(){ :; }; x=b f; [ "$x" = b ] && cat ../opus-2/draft.json', {'sh'}),
    ('x=a; x=b exec; [ "$x" = b ] && cat ../opus-2/draft.json', {'dash', 'sh', 'zsh'}),
    ('x=a; x=b exec 3>&-; [ "$x" = b ] && cat ../opus-2/draft.json', {'dash', 'sh'}),
    ('x=a; x=b eval \'x=c\'; [ "$x" = a ] && cat ../opus-2/draft.json', {'bash', 'zsh'}),
    ('x=a; x=b command :; [ "$x" = b ] && cat ../opus-2/draft.json', set()),
    ('x=$(cat ../opus-2/draft.json > o.txt) exec 3>&-; cat o.txt', {'bash', 'dash', 'sh', 'zsh'}),
    # bash builtins dash lacks fail there (127), and dash runs `((x))` as a subshell running x.
    ('[[ -n x ]] || cat ../opus-2/draft.json', {'dash'}),
    ('let x=1 || cat ../opus-2/draft.json', {'dash'}),
    ('(( 1 )) || cat ../opus-2/draft.json', {'dash'}),
    ('pushd . >/dev/null || cat ../opus-2/draft.json', {'dash'}),
    ('dirs >/dev/null || cat ../opus-2/draft.json', {'dash'}),
    ('f(){ let x=1; }; f || cat ../opus-2/draft.json', {'dash'}),
    ('(( p = 5 )); [ "$p" = 5 ] || cat ../opus-2/draft.json', {'dash'}),
    ('p=1; let p=5; [ "$p" = 5 ] || cat ../opus-2/draft.json', {'dash'}),
    ('(( $(cat ../opus-2/draft.json > o.txt; echo 1) )); cat o.txt', {'bash', 'dash', 'sh', 'zsh'}),
    ('[[ $(cat ../opus-2/draft.json > o.txt) ]]; cat o.txt', {'bash', 'dash', 'sh', 'zsh'}),
    ('x=1; [[ $x = 1 ]] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    # dash rejects a line with a here-string or an array value as it reads it, and exits.
    ('[ -z "$(/bin/dash -c \'cat <<< x\')" ] && cat ../opus-2/draft.json', {'bash', 'dash', 'sh', 'zsh'}),
    ('[ -z "$(/bin/dash -c \'echo x; p=(1)\')" ] && cat ../opus-2/draft.json', {'bash', 'dash', 'sh', 'zsh'}),
    ('[ -z "$(/bin/dash -c \'echo x; f() { local p=(1); }\')" ] && cat ../opus-2/draft.json',
     {'bash', 'dash', 'sh', 'zsh'}),
    ("/bin/dash -c 'p=(1)\ncat ../opus-2/draft.json'", set()),
    ("/bin/dash -c 'f() { local p=(1); }\ncat ../opus-2/draft.json'", set()),
    ("/bin/dash -c 'cat <<< x\ncat ../opus-2/draft.json'", set()),
    # A here-string feeds its word and a newline.
    ('x=$(/bin/bash -c \'cat <<< a; printf .\'); [ "$x" = "a\n." ] && cat ../opus-2/draft.json',
     {'bash', 'dash', 'sh', 'zsh'}),
    # bash and its sh keep what a builtin wrote to a closed standard output and write it with the
    # next write, or at the end, of a standard output that is open; of printf only the first pass
    # of its format, after which the write fails. dash and zsh drop it.
    ('cat "$(printf \'%s\n\' ../opus-2/draft.json MOCK-b >&-)"', {'bash', 'sh'}),
    ('cat "$( { printf \'%s\n\' ../opus-2/draft.json MOCK-b; } >&- )"', {'bash', 'sh'}),
    ('cat "$( { exec >&-; printf \'%s\n\' ../opus-2/draft.json MOCK-b; } > /dev/null )"', {'bash', 'sh'}),
    ('x=$(printf \'%s\n\' ../opus-2/draft.json MOCK-b 2>/dev/null >&-; :); cat "$x"', {'bash', 'sh'}),
    # A duplication or close acts on the descriptor it names, whichever way its arrow points.
    ('{ echo ../opus-2/draft.json >&2; } 2<&1 | xargs cat', {'bash', 'dash', 'sh', 'zsh'}),
    ('{ echo ../opus-2/draft.json >&2; } 2<&1 > /dev/null | xargs cat', {'bash', 'dash', 'sh', 'zsh'}),
    ('x=$(printf ../opus-2/draft.json 1<&2 2>/dev/null); [ -z "$x" ] && cat ../opus-2/draft.json',
     {'bash', 'dash', 'sh', 'zsh'}),
    # Standard error copied to standard output around a group stays there when the group's own
    # standard output moves.
    ('{ { echo ../opus-2/draft.json >&2; } > /dev/null; } 2>&1 | xargs cat', {'bash', 'dash', 'sh', 'zsh'}),
    ('f() { echo ../opus-2/draft.json >&2; }; { f > /dev/null; } 2>&1 | xargs cat',
     {'bash', 'dash', 'sh', 'zsh'}),
    ('{ (echo ../opus-2/draft.json >&2) > out.txt; } 2>&1 | xargs cat', {'bash', 'dash', 'sh', 'zsh'}),
    # After `&> f` (or `>& f`) a later `> g` moves only standard output: standard error stays at f.
    ('/bin/bash -c \'{ echo ../opus-2/draft.json >&2; } &> out.txt > /dev/null; cat "$(cat out.txt)"\'',
     {'bash', 'dash', 'sh', 'zsh'}),
    ('/bin/bash -c \'{ echo ../opus-2/draft.json >&2; } >& out.txt > /dev/null; cat "$(cat out.txt)"\'',
     {'bash', 'dash', 'sh', 'zsh'}),
]
# Reads the audit flags in more shells than make them, for the reason given: each shell that reads
# must still be flagged.
OVER = [
    # an assignment's status after a command substitution is unknown
    ("readonly z=1; x=$(readonly z=2; echo .) || cat \"$x./opus-2/draft.json\"", set()),
    # the grammar misreads an assignment with only a redirection, which the audit then notes
    ("command readonly y=1 2>/dev/null; y=2 2>/dev/null; cat ../opus-2/draft.json", {"zsh"}),
    # zsh does not run the EXIT trap after the error ends it
    ("readonly z=1; trap 'cat ../opus-2/draft.json' EXIT; z=2 2>/dev/null", {"bash", "dash", "sh"}),
    # a DEBUG trap is noted in every shell (dash has none)
    ("readonly z=1; trap 'cat ../opus-2/draft.json' DEBUG; z=2 2>/dev/null", {"bash", "sh", "zsh"}),
    # zsh's EXIT trap in a function is noted (it runs at the function's return)
    ("f(){ trap 'cd ..' EXIT; }; f; cd scratch; cat ../../opus-2/draft.json", {"bash", "dash", "sh"}),
    # what getopts sets is unknown
    ("getopts a d -a; cat \"../opus-2/draft.json$d\"", set()),
    # a file operand the audit cannot work out at all could be any path (dash's printf has no %q)
    ("cat \"$(printf %q ../opus-2/draft.json)\"", {"bash", "sh", "zsh"}),
    # a line sh or dash rejects: its paths count as alternatives, in case the audit's parse is wrong
    ("x=<(echo b); cat ../opus-2/draft.json", {"bash", "sh", "zsh"}),
    ("echo x<(echo b) ../opus-2/draft.json | xargs cat", {"bash", "sh", "zsh"}),
    ("set -o posix\n: <(echo b); cat ../opus-2/draft.json", set()),
    # zsh runs an EXIT trap set in a function at its return, a point the audit does not follow; the
    # others run it at the end, after the read (what its code writes is then unknown)
    ("f(){ trap 'echo . > p.txt' EXIT; }; echo ../opus-2/draft.json > p.txt; f; cat p.txt | xargs cat",
     {"bash", "sh", "dash"}),
    # a name the command never set (the shell lacks the builtin or option that would set it, or a
    # child shell starts afresh) may come from the environment, which the audit leaves unresolved
    ('typeset -i p; [ -n "$p" ] && cat ../opus-2/draft.json', {'zsh'}),
    ('integer p; [ "$p" = 0 ] && cat ../opus-2/draft.json', {'zsh'}),
    ('typeset -Z 3 p; [ "$p" = \'   \' ] && cat ../opus-2/draft.json', {'zsh'}),
    ('eval \'typeset y=1 1x z=2\'; [ "$z" = 2 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('typeset -i p; printf -v p 1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    ('x=a; x=b :; /bin/sh -c \'[ "$x" = b ] && cat ../opus-2/draft.json\'', {'sh'}),
    # an expression the audit cannot evaluate may still be valid: it follows both the error (bash and
    # sh exit, zsh ends the eval or the shell) and the assignment
    ('typeset -i p; p=1+; cat ../opus-2/draft.json', {'dash'}),
    ('typeset -i p; p=1+ || :; cat ../opus-2/draft.json', {'dash'}),
    ("typeset -i p; eval 'p=1+'; cat ../opus-2/draft.json", {'dash', 'zsh'}),
    ('typeset -i p; f(){ p=1+; }; f; cat ../opus-2/draft.json', {'dash'}),
    ('typeset -i p; p=1+ :; cat ../opus-2/draft.json', {'bash', 'dash'}),
    ('p=abc+; typeset -i p; cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    (': $((p=1)); p=../a; cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    # the audit does not evaluate `1.5`: bash, sh and dash end there, zsh makes a float
    (': $((p=1.5)); p=1; [ "$p" = 1 ] || cat ../opus-2/draft.json', {'zsh'}),
    # what getopts sets is unknown
    ('typeset -i p; getopts a p -a; [ "$p" = 0 ] && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    # dash rejects a line with an array value as it reads it; the audit still counts the line's
    # paths there, in case its parse of the line is wrong
    ('typeset -i p; p=(1 2); [ "$p" = 1 ] && cat ../opus-2/draft.json', {'bash', 'sh'}),
    # sh may be bash or dash, and the audit joins what the two leave after each typeset: it no longer
    # knows that only bash's made p an integer
    ('typeset -i p; typeset +i p; p=1+1; [ "$p" = 2 ] && cat ../opus-2/draft.json', set()),
    # what an array read sets is unknown
    ('p=x; read -a p <<< ../opus-2/draft.json; cat "$p"', {'bash', 'sh'}),
    ('p=x; echo ../opus-2/draft.json > q.txt; read -A p < q.txt; cat "$p"', {'zsh'}),
    # zsh shows the value in base 16, which the audit leaves unknown
    ('typeset -i16 p; p=1+1; [ "$p" = 1+1 ] && cat ../opus-2/draft.json', {'bash', 'dash', 'sh'}),
    # dash runs the text as a command, `p`, whose status the audit does not know
    ('p=1; (( p = 5 )) && cat ../opus-2/draft.json', {'bash', 'sh', 'zsh'}),
    # bash keeps what printf wrote to the closed descriptor and writes it at the substitution's
    # end, which the audit follows as a choice
    ('x=$(printf a 1<&-); [ -z "$x" ] && cat ../opus-2/draft.json', {'dash', 'zsh'}),
    # dash does not set SHLVL, which the audit takes as unknown in every shell
    ('[ -d gone ] && SHLVL=1; cat "${SHLVL+../opus-2/draft.json}"', {'bash', 'sh', 'zsh'}),
    # the audit takes what `$(echo 1x)` prints in dash as unknown
    ('export "$(echo 1x)" || cat ../opus-2/draft.json', {'bash', 'sh'}),
]
SHELL_RUNS = {"bash": ["/bin/bash", "--norc", "--noprofile", "-c"], "zsh": ["/bin/zsh", "-f", "-c"],
              "sh": ["/bin/sh", "-c"], "dash": ["/bin/dash", "-c"]}


def flagged(code: str, name: str) -> tuple[bool, bool, str]:
    """Run `code` in shell `name`: whether it read the MOCK answer, whether the audit flags the
    command, and what the shell printed (for messages)."""
    shell = SHELL_RUNS[name]
    with tempfile.TemporaryDirectory() as tmp:
        top = Path(tmp).resolve()
        work = layout(top)
        proc = subprocess.run([*shell, code], cwd=work, capture_output=True, text=True, timeout=20,
                              stdin=subprocess.DEVNULL,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work)})
        roots = [top / "repository", top / "staging"]
        with mock.patch.object(runners, "WORK", top / "work"), \
                mock.patch.object(audit, "protected_roots", lambda: roots), \
                mock.patch.object(audit, "HOME", top / "home"):
            command = " ".join([*map(shlex.quote, shell[:-1]), "-c", shlex.quote(code)])
            verdict, why = audit.check_call("shell", {"command": command}, work, roots)
    return ANSWER in proc.stdout, verdict in {"violation", "suspect"}, f"{proc.stdout}{proc.stderr}{why}"


def test_reads_are_flagged_exactly():
    for code, readers in READS:
        for name in SHELL_RUNS:
            read, flag, seen = flagged(code, name)
            assert read == (name in readers), (name, code, seen)
            assert flag == (name in readers or name == "sh" and "dash" in readers), (name, code, seen)


def test_over_flagged_reads_are_still_flagged():
    for code, readers in OVER:
        for name in SHELL_RUNS:
            read, flag, seen = flagged(code, name)
            assert read == (name in readers), (name, code, seen)
            assert flag or not read, (name, code, seen)
