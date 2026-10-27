"""Round-7 MOCK stdin-data and child-environment probes, checked in both shells."""

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from i86 import audit


class AuditMisclassification(AssertionError):
    """Only the classifier assertion is an expected failure."""


def run(review_area, shell, code):
    proc = subprocess.run([shell, "-c", code], cwd=review_area, capture_output=True, text=True,
                          timeout=10, env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"})
    assert proc.returncode == 0, proc
    verdict, reason = audit.model_call("shell", {"command": shell + " -c " + shlex.quote(code)},
                                       review_area, audit.protected_roots())
    return proc.stdout, verdict, reason


@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/zsh"])
@pytest.mark.parametrize("code", [
    "jq -r '.x' <<'JSON'\n{\"x\": \"../opus-2/draft.json\"}\nJSON",
    "jq -r '.x' <<< '{\"x\":\"../opus-2/draft.json\"}'",
    "sed -n '1p' <<'EOF'\n../opus-2/draft.json\nEOF",
    "awk '{print}' <<'EOF'\n../opus-2/draft.json\nEOF",
    "python3 -c 'import sys; print(sys.stdin.read())' <<'EOF'\n../opus-2/draft.json\nEOF",
    "awk -vp=../opus-2/draft.json 'BEGIN{print p; system(\"true\")}'",
])
def test_path_shaped_stdin_is_data(review_area, shell, code):
    out, verdict, reason = run(review_area, shell, code)
    assert "../opus-2/draft.json" in out and "MOCK OTHER ANSWER" not in out
    if verdict != "local":
        raise AuditMisclassification((verdict, reason))


@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/zsh"])
def test_child_bash_resets_exported_ifs(review_area, shell):
    code = "export IFS=:; export x=scratch:..; bash -c 'cd $x; cat ../opus-2/draft.json'"
    out, verdict, reason = run(review_area, shell, code)
    assert "MOCK OTHER ANSWER" in out
    if verdict != "violation":
        raise AuditMisclassification((verdict, reason))
