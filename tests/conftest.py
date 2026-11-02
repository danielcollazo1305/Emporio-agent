import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["AGENT_NOW"] = "2026-03-25T10:30:00"  # Wednesday, inside the dataset snapshot

from emporio_agent.tools import ToolBox  # noqa: E402


@pytest.fixture
def tb():
    return ToolBox()
