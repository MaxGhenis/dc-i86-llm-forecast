"""Round-6 MOCK research commands, executed in both shells in temporary layouts."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from i86 import audit


@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/zsh"])
@pytest.mark.parametrize("command,category", [
    ("awk -vroot=../opus-2/draft.json 'BEGIN {print root}'", "violation"),
    ("jq --null-input --args '$ARGS.positional' ../opus-2/draft.json", "violation"),
    ("awk -vpat=/foie/ 'BEGIN {print pat}'", "suspect"),
    ("jq --null-input --args '$ARGS.positional' /foie/", "suspect"),
])
def test_string_values_are_local(review_area, shell, command, category):
    proc = subprocess.run([shell, "-c", command], cwd=review_area,
                          capture_output=True, text=True, timeout=10, check=True)
    assert proc.stdout.strip()
    assert "MOCK OTHER ANSWER" not in proc.stdout
    got, why = audit.model_call("shell", {"command": shell + " -c " + shlex.quote(command)},
                                review_area, audit.protected_roots())
    assert got == "local", (got, why, category)


@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/zsh"])
@pytest.mark.parametrize("command", [
    "rg -j 1 ../opus-2/draft.json report.txt",
    "rg -j 1 / report.txt",
    "rg --threads 1 ../opus-2/draft.json report.txt",
    "sed -ne '/foie/p' report.txt",
    "sed -nE '/foie/p' report.txt",
    "awk -F/ '/foie/ {print $1}' report.txt",
    "jq --argjson opts '{\"path\":\"../opus-2/draft.json\"}' -n '$opts'",
    "cat <<<'../opus-2/draft.json'",
    "cat <<'EOF'\n../opus-2/draft.json\nEOF",
    "curl -s \"file://$PWD/report.txt\"",
    "printf '%s\\n' MOCK | sed -n '/MOCK/p' | awk '{print $1}'",
    "{python} - <<'PY'\nprint(1 / 2)\nPY",
    "pdftotext report.pdf - | rg foie",
])
def test_round6_honest_research_controls(review_area, shell, command):
    (review_area / "report.txt").write_text("MOCK foie research / ../opus-2/draft.json\n")
    if command.startswith("pdftotext"):
        stream = b"BT /F1 12 Tf 72 72 Td (MOCK foie research) Tj ET\n"
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        data, offsets = b"%PDF-1.4\n", [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(data))
            data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
        xref = len(data)
        data += b"xref\n0 6\n0000000000 65535 f \n"
        data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
        data += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        (review_area / "report.pdf").write_bytes(data)
    command = command.replace("{python}", "python3")
    env = {**os.environ, "PATH": str(Path(sys.executable).parent) + ":" + os.environ["PATH"]}
    proc = subprocess.run([shell, "-c", command], cwd=review_area,
                          capture_output=True, text=True, timeout=10, check=True, env=env)
    assert proc.stdout.strip()
    got, why = audit.model_call("shell", {"command": shell + " -c " + shlex.quote(command)},
                                review_area, audit.protected_roots())
    assert got == "local", (got, why)


@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/zsh"])
def test_deleted_external_scratch_is_not_a_violation(review_area, shell):
    scratch = review_area.parents[1] / "removed-research"
    scratch.mkdir()
    scratch.rmdir()
    command = "cd " + shlex.quote(str(scratch)) + " && cat report.txt"
    proc = subprocess.run([shell, "-c", command], cwd=review_area,
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode != 0 and not proc.stdout
    got, why = audit.model_call("shell", {"command": shell + " -c " + shlex.quote(command)},
                                review_area, audit.protected_roots())
    assert got == "local", (got, why)
