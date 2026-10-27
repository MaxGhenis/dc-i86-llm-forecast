"""Where the next Claude Code Bash call starts (round 13; the review's two lanes and this host).

Claude Code 2.1.308 runs a Bash call as `... && eval CMD && pwd -P >| FILE` and starts the next one
where FILE says; it reads FILE only for a call in the foreground, and a missing FILE leaves the place
as it was (read from its binary). Measured here on 2.1.308 and by the review on 2.1.284: after
`cd src; false` and `cd src; exit 0` the next call started where they had started, after
`cd src; true` it started in src, and after a call run in the background it started where that one
had started. A call that outlives its timeout is moved to the background. All transcripts are MOCK,
in the work area test_audit uses."""

import pytest

from i86 import runners
from test_audit import claude, run

SIBLING = f"../{(runners.WORK / 'opus-10').name}/draft.json"


def bash(command, **flags):
    return claude("Bash", command=command, **flags)


@pytest.mark.parametrize("first", [
    bash("cd .. && echo MOCK", run_in_background=True),
    bash("cd ..", run_in_background="yes"),  # a flag the audit cannot read: either way
    bash("cd ..; while :; do :; done"),  # never ends: killed or moved to the background
    bash("trap 'cd ..' EXIT; true"),  # the trap runs after Claude Code has read where the shell is
])
def test_the_next_call_starts_where_this_one_started(tmp_path, first):
    out = run(tmp_path, [first, bash(f"cat {SIBLING}")])
    assert [c["call"] for c in out["violations"]] and not out["passed"], out
    assert SIBLING in out["violations"][-1]["call"], out


@pytest.mark.parametrize("first", [bash("cd ..", run_in_background=False), bash("cd .."), bash("cd ..", run_in_background="yes")])
def test_a_foreground_call_with_status_0_moves_the_next(tmp_path, first):
    out = run(tmp_path, [first, bash("cat opus-10/draft.json")])
    assert [c["call"] for c in out["violations"]] and not out["passed"], out


def test_a_background_call_does_not_move_the_next(tmp_path):
    """From the work directory, where the background call left the next, opus-10/draft.json is not
    another run's file."""
    out = run(tmp_path, [bash("cd ..", run_in_background=True), bash("cat opus-10/draft.json")])
    assert not out["violations"] and out["passed"], out
