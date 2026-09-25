from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from stocknews.config import Paths

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCES = REPO_ROOT / "Skins" / "AIStockNews" / "@Resources"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    """Isolated resources and config folders containing a copy of the real example config."""
    resources = tmp_path / "resources"
    resources.mkdir()
    shutil.copyfile(RESOURCES / "config.example.ini", resources / "config.example.ini")
    return Paths(resources=resources, config_dir=tmp_path / "config")
