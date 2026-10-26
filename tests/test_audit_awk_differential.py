"""The audit's awk model against the real awk, on generated MOCK programs.

Each program gives awk -v values, a BEGIN block, a record action and an END block, built from
getline (from the main input, into $0 or a variable, and from a file named by $0 or a variable),
assignments and prints. Its main input is standard input (a here-string or a printf pipe, with
zero to three lines) or a file operand. Lines and values name this run's MOCK file, another run's
MOCK answer or nothing that exists. Properties, under bash and zsh:

- soundness: if awk printed the other run's MOCK answer, the audit reports a violation or a suspect;
- precision: if awk ran to the end without printing it, the audit reports no violation.
"""

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from i86 import audit, runners
from test_audit_shell_differential import ANSWER, SHELLS, layout

NAMES = ["MOCK.txt", "../opus-2/draft.json", "MOCK-missing.txt"]
BEGIN = ["getline", "getline p", "getline q", "getline line < p; print line", "getline line < q; print line",
         'p = "MOCK.txt"', "q = p", 'print "MOCK"']
RECORD = ["getline line < $0; print line", "getline line < p; print line", "getline line < q; print line",
          "getline", "getline q", "q = $0", "print"]
END = ["getline line < p; print line", "getline line < q; print line", 'print "MOCK end"']


def block(name, statements):
    return f"{name} {{{'; '.join(statements)}}}" if statements else ""


programs = st.fixed_dictionaries({
    "p": st.sampled_from(NAMES), "q": st.sampled_from(NAMES),
    "begin": st.lists(st.sampled_from(BEGIN), max_size=3),
    "record": st.lists(st.sampled_from(RECORD), max_size=3),
    "end": st.lists(st.sampled_from(END), max_size=2),
    "lines": st.lists(st.sampled_from(NAMES), max_size=3),
    "feed": st.sampled_from(["here", "printf", "file", "dash"]),
})


def command(case) -> str:
    code = " ".join(b for b in [block("BEGIN", case["begin"]), block("", case["record"]),
                                block("END", case["end"])] if b) or "BEGIN {}"
    awk = f"awk -vp={shlex.quote(case['p'])} -vq={shlex.quote(case['q'])} {shlex.quote(code)}"
    lines = case["lines"]
    if case["feed"] == "here" and len(lines) == 1:
        return f"{awk} <<< {shlex.quote(lines[0])}"
    printed = "printf '%s\\n' " + " ".join(map(shlex.quote, lines)) if lines else "printf '%s' ''"
    if case["feed"] == "file":
        return f"{printed} > MOCK-lines.txt; {awk} MOCK-lines.txt < /dev/null"
    return f"{printed} | {awk}" + (" -" if case["feed"] == "dash" else "")


@settings(max_examples=int(os.environ.get("I86_DIFFERENTIAL_EXAMPLES", "300")), deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(programs)
def test_audit_agrees_with_awk(case):
    program = command(case)
    for shell in SHELLS:
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp).resolve()
            work = layout(top)
            (work / "MOCK.txt").write_text("MOCK own research\n")
            env = {"PATH": "/usr/bin:/bin", "HOME": str(top / "home"), "PWD": str(work)}
            proc = subprocess.run([*shell, program], cwd=work, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=20)
            read = ANSWER in proc.stdout.splitlines()
            roots = [top / "repository", top / "staging"]
            with mock.patch.object(runners, "WORK", top / "work"), \
                    mock.patch.object(audit, "protected_roots", lambda: roots), \
                    mock.patch.object(audit, "HOME", top / "home"):
                verdict, why = audit.check_call("shell", {"command": program}, work, roots)
            label = f"{shell[0]}: {program!r} -> read {read}, exit {proc.returncode}, audit {verdict} ({why})"
            if read:
                assert verdict in {"violation", "suspect"}, label
            elif proc.returncode == 0:
                assert verdict != "violation", label
