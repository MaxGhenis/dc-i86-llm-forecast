"""The session audit's numbers against node's: a number a cell writes out folds to the string
JavaScript builds from it in a template (`_number` in `scripts/audit_codex_sessions.py`), and a
number it does not fold is one a module refuses to compile. Skipped where node is not installed."""

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

spec = importlib.util.spec_from_file_location(
    "audit_codex_sessions", Path(__file__).parent.parent / "scripts" / "audit_codex_sessions.py")
acs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acs)

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

EDGES = ["0", "0n", "0.0", ".5", "5.", "1_000", "1_000n", "0x7f", "0X7F", "0x7f_ff", "0o17", "0O17n", "0b1_0",
         "0B1n", "1e20", "1e21", "1e-7", "1e-6", "1E3", "1.5e+3", "1.5e-3", "1_0.0_1e1_0",
         "123456789012345678901234567890", "999999999999999999999", "9007199254740993", "5e-324",
         "1.7976931348623157e+308", "1e400", "1" + "0" * 400, "0x" + "f" * 300, "9007199254740993n",
         "123456789012345678901234567890n", "0x" + "f" * 30 + "n", "1" + "0" * 400 + "n"]


def built(literals: list[str]) -> list[str]:
    """The string node builds from each literal in a template, run as a module."""
    script = "console.log(JSON.stringify([" + ", ".join("`${" + literal + "}`" for literal in literals) + "]))"
    run = subprocess.run([NODE, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60,
                         check=True)
    return json.loads(run.stdout)


def written(n: int, base: int, big: bool, separated: bool) -> str:
    """A whole number as a script may write it: in a base, perhaps with `_` between digits, perhaps a BigInt."""
    digits = {16: f"{n:x}", 8: f"{n:o}", 2: f"{n:b}", 10: str(n)}[base]
    if separated:
        digits = re.sub(r"(?<=\w)(?=(?:\w{3})+$)", "_", digits)
    return {16: "0x", 8: "0o", 2: "0b", 10: ""}[base] + digits + ("n" if big else "")


def test_each_edge_folds_to_the_string_javascript_builds():
    assert [acs._number(literal) for literal in EDGES] == built(EDGES)


@settings(deadline=None, max_examples=40)
@given(doubles=st.lists(st.floats(min_value=0, allow_nan=False, allow_infinity=False), max_size=40),
       whole=st.lists(st.tuples(st.integers(min_value=0, max_value=2**90), st.sampled_from([16, 8, 2, 10]),
                                st.booleans(), st.booleans()), max_size=20))
def test_a_number_folds_to_the_string_javascript_builds(doubles, whole):
    """Differential: a double as Python writes it (`1e-05`, `1e+16`, `0.5`, each a JavaScript number
    too), and a whole number in each base, with or without `_` between its digits, as a Number or a
    BigInt, folds to the string node builds from it."""
    literals = [repr(abs(x)) for x in doubles] + [written(*parts) for parts in whole]
    assert [acs._number(literal) for literal in literals] == built(literals)


@pytest.mark.parametrize("literal", ["017", "08", "1__0", "1_", "0_1", "1._5", "1e", "0x_1", "00n", "01n", "1.5n",
                                     "1e3n", "0b2", "1_e1", "0x"])
def test_a_number_that_does_not_fold_is_one_a_module_refuses(literal):
    assert acs._number(literal) is None
    run = subprocess.run([NODE, "--input-type=module"], input=f"`${{{literal}}}`", capture_output=True, text=True,
                         timeout=60)
    assert run.returncode != 0 and "SyntaxError" in run.stderr
