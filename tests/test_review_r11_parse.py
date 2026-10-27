"""Round-11 parse checks: a line that starts with a backslash, which tree-sitter-bash folds into the
line before. MOCK commands only."""

from i86 import audit


def test_misread_backslash_the_audit_cannot_mend_is_noted(monkeypatch, tmp_path):
    """Where a newline before a backslash is still misread (here `_parseable` is made to leave it),
    the audit cannot see the command on that line: it says so, and the call is suspect."""
    monkeypatch.setattr(audit, "_parseable", lambda data: (data, set(), ()))
    shell = audit._shell("true\n\\cat ../MOCK-other.txt", tmp_path)
    assert "part of a command the audit could not parse" in shell.notes


def test_mended_backslash_line_is_read(tmp_path):
    """With the space `_parseable` adds, the command on that line is a command of its own (a path
    outside the working directory is one the audit reports)."""
    work = tmp_path.resolve() / "work"
    work.mkdir()
    shell = audit._shell("true\n\\cat ../MOCK-other.txt", work)
    assert shell.paths == [work.parent / "MOCK-other.txt"]
    assert not shell.notes
