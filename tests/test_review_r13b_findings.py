"""Round-13b review of e68ca57 (Opus lane): reproductions of the findings in FINDINGS.md.

Each test marked `xfail(strict=True)` states the behaviour the README, the commit message or a
docstring promises, and fails on e68ca57; once a fix makes it pass, strict xfail reports XPASS as a
failure, so drop the marker with the fix. The unmarked test covers a fix of e68ca57's that no other
test exercises. All transcripts, files and forecasts are MOCK, in a temporary MOCK work area
(runners.WORK monkeypatched), as in tests/test_review_r13_inputs.py."""

import json
from fractions import Fraction

import numpy as np
import pytest

from i86 import dists
from i86.simulate import _breaks, exact_tilt
from test_review_r13_inputs import area, audit_lines, claude, held  # noqa: F401 (area is a fixture)
from test_review_r13_tilt import GRAPH, _full

OTHER = "../opus-2/draft.json"  # another run's MOCK answer, from the work directory


def bash(command, **flags):
    return claude("Bash", {"command": command, **flags})


# --- M1: text no file name can hold outranks a violation ---------------------------------------

@pytest.mark.parametrize("call", [
    ("Bash", {"command": f"cat {OTHER}", "description": "MOCK\u0000"}),
    ("Read", {"file_path": "{other}", "MOCK": "\ud800"}),
    ("mcp__mock__tool", {"q": "MOCK\u0000"}),
])
def test_unwritable_text_does_not_hide_a_violation(area, tmp_path, call):
    name, inp = call
    inp = {k: v.replace("{other}", str(area.parent / "opus-2" / "draft.json")) for k, v in inp.items()}
    out = audit_lines(area, tmp_path, [claude(name, inp)])
    assert out["violations"] and not out["passed"], out


# --- M2 and m5: where the next Bash call starts -------------------------------------------------

@pytest.mark.parametrize("first", [bash("cd MOCK-sub; sleep 300; true"),
                                   bash("cd MOCK-sub; sleep 300; true", timeout=1000)])
def test_a_call_that_outlives_its_timeout_keeps_the_start(area, tmp_path, first):
    """Claude Code kills the call or moves it to the background at its timeout (120 s unless set), so
    it never reaches `pwd -P` and the next call starts where this one started."""
    out = audit_lines(area, tmp_path, [first, bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], out


@pytest.mark.parametrize("first", ["cd MOCK-sub; echo MOCK > missing/out.txt", "cd MOCK-sub; true < missing.txt"])
def test_a_builtin_whose_redirection_fails_keeps_the_start(area, tmp_path, first):
    """bash, sh, dash and zsh give status 1 or 2 here, so `pwd -P` does not run."""
    out = audit_lines(area, tmp_path, [bash(first), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], out


@pytest.mark.parametrize("flag", [0, 0.0])
def test_a_flag_that_is_not_a_boolean_gives_both_from_the_start(area, tmp_path, flag):
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub", run_in_background=flag), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], out


@pytest.mark.parametrize("flag", [1, 1.0])
def test_a_flag_that_is_not_a_boolean_gives_both_from_the_end(area, tmp_path, flag):
    """From MOCK-sub, ../../opus-2 is another run's directory; from the work directory it is not."""
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub", run_in_background=flag),
                                       bash("cat ../../opus-2/draft.json")])
    assert out["violations"] and not out["passed"], out


# --- m1: URLs elsewhere in a web call's input --------------------------------------------------

@pytest.mark.parametrize("query", ["MOCK\nhttp://127.0.0.1/", "MOCK\thttp://127.0.0.1/",
                                   "http://example.org\t@127.0.0.1/", "http://example.org @127.0.0.1/",
                                   "http://example.org'@127.0.0.1/"])
def test_a_url_in_a_web_input_is_read_as_whatwg_reads_it(area, tmp_path, query):
    """Node's `new URL()` reads each URL here as 127.0.0.1's; the README makes such a call suspect."""
    out = audit_lines(area, tmp_path, [claude("WebSearch", {"query": query})])
    assert out["web_calls"] == 0 and out["suspect"], out


# --- m2 and m3: lines that crash the audit or are skipped ----------------------------------------

@pytest.mark.parametrize("line", [
    json.dumps({"type": [], "item": {"type": "agent_message"}}),
    json.dumps({"type": "item.completed", "item": {"type": []}}),
    '{"type":"item.started","item":{"id":1' + "0" * 309 + ',"type":"command_execution","command":"ls"}}',
    '{"type":"MOCK","n":' + "1" * 5000 + "}",
])
def test_a_line_that_still_crashes_the_audit(area, tmp_path, line):
    out = audit_lines(area, tmp_path, [claude("Read", {"file_path": str(area / "MOCK-own.txt")}), line])
    assert held(out), out


@pytest.mark.parametrize("kind", ["array", "item.updated", "u2028"])
def test_a_line_holding_a_call_is_not_skipped(area, tmp_path, kind):
    other = str(area.parent / "opus-2" / "draft.json")
    if kind == "array":
        line = json.dumps([claude("Read", {"file_path": other})])
    elif kind == "item.updated":
        line = json.dumps({"type": "item.updated", "item": {"id": "i", "type": "command_execution",
                                                             "command": f"cat {other}"}})
    else:  # a valid JSON line holding U+2028 raw, as JSON.stringify writes it
        line = json.dumps(claude("Read", {"file_path": other, "MOCK ": 1}), ensure_ascii=False)
    out = audit_lines(area, tmp_path, [claude("Read", {"file_path": str(area / "MOCK-own.txt")}), line])
    assert out["violations"] and not out["passed"], out


# --- m6 and m7: the shell model against zsh (measured on macOS's /bin/zsh 5.9) ------------------

R = "cat ../opus-2/draft.json"


@pytest.mark.xfail(strict=True, reason="FINDINGS m6: regressions from 5fc7b11, which flagged each")
@pytest.mark.parametrize("code", [
    '"nocorrect" : < "${x:=/dev/null}" 2>/dev/null; [ "${x-unset}" = unset ] && ' + R,
    'nocorrect < "${x:=/dev/null}" 2>/dev/null; [ "${x-unset}" = unset ] && ' + R,
    "eval 'command < \"${x:=/dev/null}\"' 2>/dev/null; [ \"${x-unset}\" = unset ] && " + R,
])
def test_zsh_precommand_regressions_are_flagged(code):
    from test_audit_readonly import flagged
    read, flag, seen = flagged(code, "zsh")
    assert read, ("measurement", seen)
    assert flag, ("miss", seen)


@pytest.mark.xfail(strict=True, reason="FINDINGS m7: MULTIOS join missing for these stages")
@pytest.mark.parametrize("code", [
    "printf '../opus-2/draft.json\\n' | while read l; do cat \"$l\"; done < /dev/null",
    "cat <<E | xargs cat < /dev/null 2>/dev/null\n../opus-2/draft.json\nE",
])
def test_zsh_multios_stages_are_flagged(code):
    from test_audit_readonly import flagged
    read, flag, seen = flagged(code, "zsh")
    assert read, ("measurement", seen)
    assert flag, ("miss", seen)


@pytest.mark.xfail(strict=True, reason="FINDINGS m7: the outer statement's redirections come first in `simple`")
@pytest.mark.parametrize("name", ["bash", "zsh"])
def test_a_herestring_before_a_file_redirection_reads_in_order(name):
    from test_audit_output_differential import matches
    from test_review_r13_shell import model_in
    real, model = model_in(name, "printf 'MOCK-f\\n' > f; cat <<< MOCK-s < f")
    assert model is None or matches(real, model), (real, model)


# --- the narrow-segment read (dists.py:146-147), which no other test exercises -------------------

def test_a_one_float_segment_is_read_at_its_right_end():
    """MOCK: a Yes share uniform on (30%, 90%], the band (prev(50%), next(50%)] of two one-float
    segments, a failing answer of 0.9 and a passing one of 0.001. The tilt's mass is exactly each
    segment's probability times its own side's answer; reading the passing segment at 50% gave the
    failing answer there (2.5e-16 against 1.0e-16)."""
    cdf = [min(1.0, max(0.0, (x - 0.3) / 0.6)) for x in GRAPH.share_grid]
    answers = {"yes_42.0": 0.9, "yes_49.5": 0.9, "yes_50.5": 0.001, "yes_60.0": 0.001, "yes_72.0": 0.001}
    band = (float(np.nextafter(0.5, 0.0)), float(np.nextafter(0.5, 1.0)))
    fc = _full("dc_animal_initiative_filed", answers, cdf)
    _, tilt, breaks = exact_tilt(GRAPH, fc, {"dc_animal_initiative_filed": {True}}, band)
    a, b, m = dists.share_segments(GRAPH.share_grid, np.asarray(cdf), GRAPH.share_floor, GRAPH.share_ceiling,
                                   *band, _breaks(GRAPH))
    assert len(a) == 2 and all(float(np.nextafter(x, 1.0)) == y for x, y in zip(a, b)) and (m > 0).all()
    exact = Fraction(float(m[0])) * Fraction(0.9) + Fraction(float(m[1])) * Fraction(0.001)
    _, z = dists.sample_share_tilted(GRAPH.share_grid, np.asarray(cdf), GRAPH.share_floor, GRAPH.share_ceiling,
                                     *band, np.array([0.5]), tilt, breaks, log2_scale=tilt.scale)
    assert z == float(exact), (z, float(exact))
