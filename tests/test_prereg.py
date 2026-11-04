"""`i86 prereg` hashes what a reader can check from this repository, and replaces the previous proof
instead of leaving it beside a manifest it does not prove, once a dated folder keeps both. MOCK files
in a temporary root."""

import argparse
import os

import pytest

from i86 import cli, runners


def area(tmp_path, monkeypatch, dated=True):
    """A MOCK repository root: map, prompt, template and brief, no runs or outputs, and a previous
    manifest with its proof, which a dated folder keeps unless `dated` is false."""
    for rel in ("graph/graph.yaml", "prompts/forecaster.md", "schemas/template.json", "context/brief.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(f"MOCK {rel}\n")
    prereg = tmp_path / "prereg"
    for folder in (prereg / "2026-01-01-MOCK", prereg) if dated else (prereg,):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SHA256SUMS").write_text("MOCK OLD MANIFEST\n")
        (folder / "SHA256SUMS.ots").write_text("MOCK OLD PROOF\n")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "PROMPT_PATH", tmp_path / "prompts" / "forecaster.md")
    monkeypatch.setattr(cli, "TEMPLATE_PATH", tmp_path / "schemas" / "template.json")
    monkeypatch.setattr(cli, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(cli, "PREREG", prereg)
    monkeypatch.setattr(runners, "RUNS", tmp_path / "runs")
    return prereg


def test_a_new_manifest_gets_a_new_proof(tmp_path, monkeypatch):
    prereg = area(tmp_path, monkeypatch)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, (prereg / "SHA256SUMS.ots").exists()))
        (prereg / "SHA256SUMS.ots").write_text("MOCK NEW PROOF\n")
        return argparse.Namespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.cmd_prereg(argparse.Namespace(no_stamp=False)) == 0
    [(cmd, old_proof_present)] = calls
    assert cmd[-2:] == ["stamp", str(prereg / "SHA256SUMS")]
    assert not old_proof_present
    assert (prereg / "SHA256SUMS.ots").read_text() == "MOCK NEW PROOF\n"
    assert "MOCK OLD MANIFEST" not in (prereg / "SHA256SUMS").read_text()


def test_a_codex_runs_session_audit_and_attempts_are_hashed_and_its_logs_are_not(tmp_path, monkeypatch):
    """The logs stay out of this public repository, so a manifest that listed them could not be
    checked from it; the audit, which the manifest lists, records each log's SHA-256."""
    prereg = area(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no stamp")))
    sessions = tmp_path / "runs" / "sol-1" / "codex-sessions"
    sessions.mkdir(parents=True)
    (sessions.parent / "meta.json").write_text("MOCK meta\n")
    for name in ("rollout-MOCK.jsonl", "audit.json", "attempts.json", "MOCK-notes.txt"):
        (sessions / name).write_text(f"MOCK {name}\n")
    (tmp_path / "runs" / "opus-1").mkdir()
    (tmp_path / "runs" / "opus-1" / "meta.json").write_text("MOCK meta\n")
    assert cli.cmd_prereg(argparse.Namespace(no_stamp=True)) == 0
    manifest = (prereg / "SHA256SUMS").read_text()
    for rel in ("runs/sol-1/meta.json", "runs/sol-1/codex-sessions/audit.json",
                "runs/sol-1/codex-sessions/attempts.json", "runs/opus-1/meta.json"):
        assert f"  {rel}\n" in manifest
    assert "rollout-MOCK.jsonl" not in manifest and "MOCK-notes.txt" not in manifest
    assert "opus-1/codex-sessions" not in manifest


@pytest.mark.parametrize("name", ["codex-sessions/attempts.json", "codex-sessions/audit.json", "transcript.jsonl"])
@pytest.mark.parametrize("kind", ["a folder", "a pipe", "a link to nothing"])
def test_a_run_file_that_is_not_a_regular_file_stops_prereg(tmp_path, monkeypatch, name, kind):
    """Review 6: prereg hashes each run's files; a folder, a link to nothing or a pipe (whose read
    would wait for a writer forever) where one should be stops it, by name, before it writes a manifest."""
    prereg = area(tmp_path, monkeypatch)
    path = tmp_path / "runs" / "sol-1" / name
    path.parent.mkdir(parents=True)
    (tmp_path / "runs" / "sol-1" / "meta.json").write_text("MOCK meta\n")
    {"a folder": path.mkdir, "a pipe": lambda: os.mkfifo(path),
     "a link to nothing": lambda: path.symlink_to(path.with_name("MOCK-gone"))}[kind]()
    with pytest.raises(SystemExit, match=f"runs/sol-1/{name} is not a regular file"):
        cli.cmd_prereg(argparse.Namespace(no_stamp=True))
    assert (prereg / "SHA256SUMS").read_text() == "MOCK OLD MANIFEST\n"


def test_hashing_without_a_stamp_drops_the_old_proof(tmp_path, monkeypatch):
    prereg = area(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no stamp")))
    assert cli.cmd_prereg(argparse.Namespace(no_stamp=True)) == 0
    assert not (prereg / "SHA256SUMS.ots").exists()
    assert "graph/graph.yaml" in (prereg / "SHA256SUMS").read_text()
    assert (prereg / "2026-01-01-MOCK" / "SHA256SUMS.ots").read_text() == "MOCK OLD PROOF\n"


@pytest.mark.parametrize("folder", [None, "MOCK OTHER PROOF\n", "MOCK OLD PROOF\n"])
def test_a_proof_no_dated_folder_keeps_stops_prereg(tmp_path, monkeypatch, folder):
    """Review finding 11: without a dated copy of the proof and of the manifest it stamps, byte for
    byte, `prereg` would leave the proof only in git's history. It stops before it writes anything."""
    prereg = area(tmp_path, monkeypatch, dated=False)
    if folder is not None:  # a dated folder with another proof, or with this proof and another manifest
        (prereg / "2026-01-01-MOCK").mkdir()
        (prereg / "2026-01-01-MOCK" / "SHA256SUMS.ots").write_text(folder)
        (prereg / "2026-01-01-MOCK" / "SHA256SUMS").write_text("MOCK OTHER MANIFEST\n")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no stamp")))
    with pytest.raises(SystemExit, match="in no dated folder"):
        cli.cmd_prereg(argparse.Namespace(no_stamp=True))
    assert (prereg / "SHA256SUMS").read_text() == "MOCK OLD MANIFEST\n"
    assert (prereg / "SHA256SUMS.ots").read_text() == "MOCK OLD PROOF\n"


def test_a_first_manifest_needs_no_dated_folder(tmp_path, monkeypatch):
    prereg = area(tmp_path, monkeypatch, dated=False)
    for name in ("SHA256SUMS", "SHA256SUMS.ots"):
        (prereg / name).unlink()
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no stamp")))
    assert cli.cmd_prereg(argparse.Namespace(no_stamp=True)) == 0
    assert "graph/graph.yaml" in (prereg / "SHA256SUMS").read_text()
