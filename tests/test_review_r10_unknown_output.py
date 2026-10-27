"""Unresolved printf output must retain possible filename consumption. All MOCK."""
import shlex
import subprocess

import pytest

from i86 import audit


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_printf_q_to_xargs_is_not_local(review_area, shell):
    command = "printf '%q' ../opus-2/draft.json | xargs cat"
    real = subprocess.run(["/bin/" + shell, "-c", command], cwd=review_area,
                          capture_output=True, text=True, timeout=5)
    assert real.returncode == 0 and real.stdout == "MOCK OTHER ANSWER\n", real
    category, reason = audit.model_call(
        "shell", {"command": shell + " -c " + shlex.quote(command)},
        review_area, audit.protected_roots())
    assert category in {"violation", "suspect"}, (category, reason)
