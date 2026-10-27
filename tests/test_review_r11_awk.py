"""awk runs its record actions once per record, so a later record reads what an earlier one assigned.

Each program reads MOCK files only, under real shells; with one record the actions run once and a
name they assign later in them is never read again.
"""
import shlex
import subprocess

import pytest

from i86 import audit


@pytest.mark.parametrize("shell", ["bash", "zsh", "sh"])
@pytest.mark.parametrize("program,lines,verdict,reads", [
    # The 3000-example awk search's counterexample: `getline q` reads the next record into q.
    ('{getline l < q; print l; getline q}', ["MOCK.txt", "../opus-2/draft.json", "MOCK.txt"], "suspect", True),
    ('{getline l < q; print l; q = "../opus-2/draft.json"}', ["a", "b"], "suspect", True),
    ('{getline l < q; print l; sub(/MOCK.txt/, "../opus-2/draft.json", q)}', ["a", "b"], "suspect", True),
    # In END, a name holds what the last record left.
    ('{n = q; q = "../opus-2/draft.json"} END {getline l < n; print l}', ["a", "b"], "suspect", True),
    # One record: the actions run once.
    ('{getline l < q; print l; q = "../opus-2/draft.json"}', ["a"], "local", False),
    ('{n = q; q = "../opus-2/draft.json"} END {getline l < n; print l}', ["a"], "local", False),
    # A value assigned before it is read is the same on every record.
    ('{q = "MOCK.txt"; getline l < q; print l}', ["a", "b", "c"], "local", False),
])
def test_record_actions_carry_names(review_area, shell, program, lines, verdict, reads):
    (review_area / "MOCK.txt").write_text("MOCK own research\n")
    command = (f"printf '%s\\n' {' '.join(map(shlex.quote, lines))} | "
               f"awk -vq=MOCK.txt {shlex.quote(program)}")
    proc = subprocess.run(["/bin/" + shell, "-c", command], cwd=review_area,
                          capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0 and ("MOCK OTHER ANSWER" in proc.stdout) == reads, (command, proc)
    got, why = audit.check_call("shell", {"command": shell + " -c " + shlex.quote(command)},
                                review_area, audit.protected_roots())
    assert got == verdict, (command, got, why)
