"""Round-8 real-shell close variants, confined to temporary MOCK work areas."""

import shlex
import subprocess

import pytest

from i86 import audit
from test_review_r7_audit_gaps import assert_protected_read


class AuditDefect(AssertionError):
    """Only an incorrect verdict is an expected failure."""


@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/zsh"])
@pytest.mark.parametrize("command", [
    "cd scratch; cat ~-/../../repository/draft.json ~-/../../staging/draft.json",
    "pushd scratch; pushd deep; cat ~2/../opus-2/draft.json",
    "cd scratch; for d in {1..3}; do cd ..; done; cat work/opus-2/draft.json",
    'a=(1 2); cd scratch; for d in "${a[@]}"; do cd ..; done; cat opus-2/draft.json',
    'f(){ local x; : ${x:=..}; cd "$x"; }; cd scratch; f; cat ../opus-2/draft.json',
    'f(){ local x; unset x; : ${x=..}; cd "$x"; }; cd scratch; f; cat ../opus-2/draft.json',
    'set -o noglob; (set +o noglob); for d in scratch/*; do cd "$d"; cd ..; done; cat opus-2/draft.json',
    'export IFS=:; export x=scratch:..; env -u IFS bash -c \'cd $x; cat ../opus-2/draft.json\'',
    'unset x; : ${x:=~+}; cd scratch; cat "$x/../opus-2/draft.json"',
])
def test_round7_close_variants(review_area, monkeypatch, shell, command):
    category, reason = assert_protected_read(review_area, monkeypatch, shell, command)
    assert category == "violation", reason


@pytest.mark.parametrize("mode", ["zsh", "sh"])
def test_emulate_command_directory_persists(review_area, monkeypatch, mode):
    command = f"emulate {mode} -c 'cd scratch'; cat ../../opus-2/draft.json"
    category, reason = assert_protected_read(review_area, monkeypatch, "/bin/zsh", command)
    if category != "violation":
        raise AuditDefect((category, reason))


def test_emulate_command_own_file_stays_local(review_area):
    own = review_area / "opus-2"
    own.mkdir()
    (own / "draft.json").write_text("MOCK OWN DATA\n")
    command = "emulate zsh -c 'cd scratch'; cat ../opus-2/draft.json"
    real = subprocess.run(["/bin/zsh", "-f", "-c", command], cwd=review_area,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(review_area)},
                          capture_output=True, text=True, timeout=20)
    assert real.returncode == 0 and real.stdout == "MOCK OWN DATA\n", real
    category, reason = audit.check_call("shell", {"command": "/bin/zsh -c " + shlex.quote(command)},
                                       review_area, audit.protected_roots())
    if category != "local":
        raise AuditDefect((category, reason))
