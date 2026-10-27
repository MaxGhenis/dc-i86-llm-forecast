"""Round-12 review probes (Opus findings 1, 2, 6 and 7, and the reads of `-` and /dev/null found while
verifying them): reads the exact subset or the shell model let through at da5be89, each now outside
the subset or flagged. All MOCK. Measured on macOS's bash 3.2, sh, dash, zsh 5.9 and BSD tail
(`tail -1000c F` is the obsolete form of `tail -c -1000 F`).
"""

import json
import subprocess

import pytest

from i86 import audit, exact
from test_audit_exact import ANSWER, PATH, SHELLS, exact_layout, patched, run

# BSD tail rewrites a leading `-NUMc` to `-c -NUM`, so the next word is a file, while the subset takes
# it as -c's value and never checks it.
TAIL_HOLES = ["tail -1000c ../opus-2/draft.json report.txt", "tail -1000c up/opus-2/draft.json",
              "tail -r -1000c ../opus-2/draft.json /dev/null", "tail -1000c ../opus-2/draft.json -5q -"]


def test_tail_obsolete_count_reads_in_every_shell(tmp_path):
    """The reads happen: this half documents the shells, and passes."""
    top = tmp_path.resolve()
    work = exact_layout(top)
    for code in TAIL_HOLES:
        for name in SHELLS:
            out, _ = run(name, code, work, top)
            assert ANSWER in out, (name, code, out)


def test_tail_obsolete_count_is_outside_the_subset(tmp_path):
    top = tmp_path.resolve()
    work = exact_layout(top)
    passed = [code for code in TAIL_HOLES if exact.outside(code, work, [work])[0] is None]
    assert not passed, passed


def _audit(top, work, lines):
    path = top / "MOCK-transcript.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    roots, patches = patched(top)
    for p in patches:
        p.start()
    try:
        return audit.audit_transcript(path, str(work))
    finally:
        for p in reversed(patches):
            p.stop()


def _bash(command):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                                                          "input": {"command": command}}]}}


def test_bash_read_after_an_earlier_cd_is_not_local(tmp_path):
    """Claude Code's Bash starts where the last call ended. After `cd scratch`, the second call reads
    the sibling's answer (shown below); da5be89's audit took both calls as local and passed the run."""
    top = tmp_path.resolve()
    work = exact_layout(top)
    (work / "up").unlink()
    second = "tail -100000c ../../opus-2/draft.json /dev/null"
    proc = subprocess.run(["/bin/zsh", "-f", "-c", second], cwd=work / "scratch", env={"PATH": PATH},
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert ANSWER in proc.stdout, proc
    result = _audit(top, work, [_bash("cd scratch"), _bash(second)])
    assert result["violations"] or result["suspect"], result


def test_codex_tail_in_an_unrecorded_directory_is_not_local(tmp_path):
    """Codex's shell tool takes a working directory the transcript does not record. Run in the
    sibling's directory, `tail -100000c draft.json` prints its answer; da5be89's audit passed the run."""
    top = tmp_path.resolve()
    work = exact_layout(top)
    code = "/bin/zsh -lc 'tail -100000c draft.json'"
    proc = subprocess.run(["/bin/zsh", "-f", "-c", "tail -100000c draft.json"], cwd=top / "work" / "opus-2",
                          env={"PATH": PATH}, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert ANSWER in proc.stdout, proc
    result = _audit(top, work, [{"type": "item.completed", "item": {"type": "command_execution", "command": code}}])
    assert result["violations"] or result["suspect"], result


# Model misses (check_call makes each suspect, as each lies outside the subset; the model's verdict
# decides whether the run is excluded). Each reads the answer in the shells listed.
MODEL_MISSES = [
    # `!` before an external command whose redirection meets an unset parameter: the command fails
    # and bash, sh and zsh go on, as they do without `!`
    ('! cat < "${x?}"\ncat ../opus-2/draft.json', {"bash", "sh", "zsh"}, {}),
    ('! cat > "${x:?w}"\ncat ../opus-2/draft.json', {"bash", "sh", "zsh"}, {}),
    # a variable Claude Code's shell sets, which the model took as unset at `${x?}`, ending the shell
    (': "${CLAUDECODE?}"\ncat ../opus-2/draft.json', {"bash", "sh", "dash", "zsh"}, {"CLAUDECODE": "1"}),
]


@pytest.mark.parametrize("code, readers, env", MODEL_MISSES)
def test_model_misses_read(tmp_path, code, readers, env):
    top = tmp_path.resolve()
    work = exact_layout(top)
    argv = {"bash": ["/bin/bash", "--norc", "--noprofile", "-c"], "sh": ["/bin/sh", "-c"],
            "dash": ["/bin/dash", "-c"], "zsh": ["/bin/zsh", "-f", "-c"]}
    for name, shell in argv.items():
        proc = subprocess.run([*shell, code], cwd=work, env={"PATH": "/usr/bin:/bin", **env},
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        assert (ANSWER in proc.stdout) == (name in readers), (name, code, proc)


@pytest.mark.parametrize("code, readers, env", MODEL_MISSES)
def test_model_flags_the_read(tmp_path, code, readers, env):
    top = tmp_path.resolve()
    work = exact_layout(top)
    roots, patches = patched(top)
    for p in patches:
        p.start()
    try:
        assert audit.model_call("Bash", {"command": code}, work, roots)[0] == "violation", code
    finally:
        for p in reversed(patches):
            p.stop()


def test_a_list_command_does_not_crash_the_audit(tmp_path):
    top = tmp_path.resolve()
    work = exact_layout(top)
    line = {"type": "item.completed", "item": {"type": "command_execution",
                                               "command": ["bash", "-lc", "cat ../opus-2/draft.json"]}}
    result = _audit(top, work, [line])
    assert result["violations"] or result["suspect"], result


# Found while verifying round 12: macOS's head, tail and sed read a file named `-` where the GNU tools
# read standard input, and the subset skipped `-` for every tool. From an unknown start (a Codex call)
# the shell may be in another run's directory.
DASH_READS = ["head -", "head -n 1 -", "tail -", "tail -n 1 -", "sed -n 1p -"]


def test_bsd_tools_read_a_file_named_dash_in_every_shell(tmp_path):
    top = tmp_path.resolve()
    work = exact_layout(top)
    other = top / "work" / "opus-2"
    (other / "-").write_text(ANSWER + "\n")
    for code in DASH_READS:
        for name in SHELLS:
            out, _ = run(name, code, other, top)
            assert ANSWER in out, (name, code, out)
        assert exact.outside(code, work, None)[0] is not None, code


def test_dev_null_times_are_outside_the_subset(tmp_path):
    """`ls -l` and `find -newer` read /dev/null's times, the host's, which change between calls."""
    top = tmp_path.resolve()
    work = exact_layout(top)
    for code in ["ls -ld /dev/null", "ls -l /dev/null", "find /dev/null -newer report.txt", "find . -newer /dev/null"]:
        assert exact.outside(code, work, [work])[0] is not None, code
    for code in ["head -n 1 /dev/null", "wc -l /dev/null", "cat /dev/null", "sed -n 1p /dev/null"]:
        assert exact.outside(code, work, [work])[0] is None, code
