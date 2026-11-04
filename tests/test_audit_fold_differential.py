"""The session audit's strings against node's: each string `_fold` reads from a cell's constants
(`scripts/audit_codex_sessions.py`) is the string JavaScript builds, unit for UTF-16 unit, and `_fold`
reads exactly the expressions it says it reads. Skipped where node is not installed."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

spec = importlib.util.spec_from_file_location(
    "audit_codex_sessions", Path(__file__).parent.parent / "scripts" / "audit_codex_sessions.py")
acs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acs)

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

# What a string or a template may hold: escapes, among them each half of a surrogate pair alone and a
# backslash before CR LF, CR, LF or a line or paragraph separator, and characters written out.
ESCAPES = ["\\n", "\\t", "\\\\", "\\'", '\\"', "\\`", "\\$", "\\x41", "\\x00", "\\u00e9", "\\uD83D", "\\uDE00",
           "\\uDBFF", "\\uDFFF", "\\u{1F600}", "\\u{D83D}", "\\u{10FFFF}", "\\\n", "\\\r\n", "\\\r", "\\ ",
           "\\ "]
WRITTEN = ["a", "Z", "7", " ", "{", "}", "é", "\U0001f600", " ", " "]
# A template may also hold line breaks, and a `$` that no `{` follows.
IN_TEMPLATE = [*ESCAPES, *WRITTEN, "'", '"', "$a", "\n", "\r", "\r\n"]
NUMBERS = ["0", "7", "1.5", ".5", "1e21", "1e-7", "0x7f", "0o17", "0b101", "1_000", "127n", "0x1fn",
           "9007199254740993", "9007199254740993n"]
# What `_fold` leaves to a script's run: names, a unary operator, an array, an object.
OPAQUE = ["undefined", "NaN", "-1", "[1, 2]", "({})"]


# An expression: its source; "string" if JavaScript holds it as a string, "primitive" if as a number,
# a boolean or null, and None if the test does not say; whether `_fold` reads it; and whether it is a `+`.
def _string(quote: str):
    other = {'"': "'", "'": '"'}[quote]
    return st.lists(st.sampled_from([*ESCAPES, *WRITTEN, other, "`", "$"]), max_size=6).map(
        lambda pieces: (quote + "".join(pieces) + quote, "string", True, False))


def _plus(pair) -> tuple:
    (a, kind_a, folds_a, _), (b, kind_b, folds_b, plus_b) = pair
    kind = "string" if "string" in (kind_a, kind_b) else "primitive" if kind_a == kind_b == "primitive" else None
    return f"{a} + ({b})" if plus_b else f"{a} + {b}", kind, folds_a and folds_b and kind == "string", True


def _template(parts) -> tuple:
    source, folds = "`", True
    for part in parts:
        if isinstance(part, str):
            source += part
        else:
            source += "${" + part[0] + "}"
            folds = folds and part[2]
    return source + "`", "string", folds, False


LEAVES = st.one_of(_string('"'), _string("'"),
                   st.sampled_from(NUMBERS).map(lambda n: (n, "primitive", True, False)),
                   st.sampled_from(["true", "false", "null"]).map(lambda k: (k, "primitive", True, False)),
                   st.sampled_from(OPAQUE).map(lambda o: (o, None, False, False)))
EXPRESSIONS = st.recursive(LEAVES, lambda inner: st.one_of(
    st.tuples(inner, inner).map(_plus),
    inner.map(lambda e: (f"({e[0]})", e[1], e[2], False)),
    st.lists(st.one_of(st.sampled_from(IN_TEMPLATE), inner), max_size=5).map(_template)), max_leaves=8)


def built(sources: list[str]) -> list:
    """The string node builds from each expression, evaluated in a module (strict code), or None where
    evaluating it throws."""
    script = (f"const out = [];\nfor (const source of {json.dumps(sources)}) {{\n"
              "  try { out.push(String(eval(`(${source})`))); } catch { out.push(null); }\n}\n"
              "console.log(JSON.stringify(out));\n")
    run = subprocess.run([NODE, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60,
                         check=True)
    return json.loads(run.stdout)


def fold(source: str) -> str | None:
    src = f"x = {source};".encode()
    tree = acs._JS.parse(src)
    assert not tree.root_node.has_error, source
    return acs._fold(tree.root_node.named_children[0].named_children[0].child_by_field_name("right"), src)


def units(text: str) -> bytes:
    return text.encode("utf-16-le", "surrogatepass")


@settings(deadline=None, max_examples=60)
@given(expressions=st.lists(EXPRESSIONS, min_size=1, max_size=25))
@example(expressions=[('"\\uD83D" + "\\uDE00"', "string", True, True), ("`a\r\nb\\\r\nc\rd`", "string", True, False),
                      ('"a" + true + 1', "string", True, True), ('true + 1 + "a"', "string", False, True),
                      ("`a\rb${'c'}d\r\ne`", "string", True, False)])
def test_a_constant_folds_to_the_string_javascript_builds(expressions):
    """Differential: `_fold` reads strings, numbers, `true`, `false`, `null`, templates whose
    substitutions it reads, parentheses and a `+` with a string on one side, and nothing else; and each
    string it reads is the string node builds, unit for UTF-16 unit."""
    for (source, _, folds, _), value in zip(expressions, built([e[0] for e in expressions]), strict=True):
        folded = fold(source)
        assert (folded is not None) == folds, source
        if folded is not None:
            assert value is not None and units(folded) == units(value), source


def cooked(sources: list[str]) -> list:
    """The text node cooks between the substitutions of each template, as a tag function receives it."""
    script = (f"const out = [];\nfor (const source of {json.dumps(sources)}) {{\n"
              "  out.push(eval(`((strings) => [...strings])${source}`));\n}\n"
              "console.log(JSON.stringify(out));\n")
    run = subprocess.run([NODE, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60,
                         check=True)
    return json.loads(run.stdout)


# A template whose substitutions are `${0}`: the text between them is what the test reads.
TEMPLATES = st.lists(st.one_of(st.sampled_from(IN_TEMPLATE), st.none()), max_size=8).map(
    lambda parts: "`" + "".join("${0}" if part is None else part for part in parts) + "`")


@settings(deadline=None, max_examples=60)
@given(templates=st.lists(TEMPLATES, min_size=1, max_size=25))
@example(templates=["`\\uD83D\\uDE00${0}\\uD83D${0}\\uDE00`", "`a\rb${0}c\r\nd${0}e\rf`"])
def test_a_templates_text_reads_as_javascript_cooks_it(templates):
    """Differential: the text `_template_parts` reads between a template's substitutions is the text
    node cooks for a tag function, string for string: its escapes decoded, each CR LF or CR as LF,
    and the two halves of a character its escapes spell joined."""
    for source, strings in zip(templates, cooked(templates), strict=True):
        src = f"x = {source};".encode()
        tree = acs._JS.parse(src)
        assert not tree.root_node.has_error, source
        node = tree.root_node.named_children[0].named_children[0].child_by_field_name("right")
        assert [part for part in acs._template_parts(node, src) if isinstance(part, str)] == strings, source
