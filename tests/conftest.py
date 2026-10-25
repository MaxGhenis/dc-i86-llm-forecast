import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from i86 import graph as graph_mod  # noqa: E402


@pytest.fixture(scope="session")
def graph():
    return graph_mod.load()
