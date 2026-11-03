"""Shared helpers: a fixture as raw text cells and bundles written to disk."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "synthetic_300.csv"

BundleWriter = Callable[[pd.DataFrame], Path]


def manifest_dict(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": 1,
        "school": {"id": "demo", "name": "Demo School"},
        "wave": {"label": "2026", "fieldwork_end": "2026-05-15"},
        "survey": {"questionnaire_version": "2026.1"},
        "responses": {"file": "responses.csv", "format": "csv"},
    }
    manifest.update(overrides)
    return manifest


@pytest.fixture
def raw_fixture() -> pd.DataFrame:
    """The 300-response synthetic fixture, every cell as text, empty cells as ""."""
    return pd.read_csv(FIXTURE_CSV, dtype=str, keep_default_na=False)


@pytest.fixture
def write_bundle(tmp_path: Path) -> BundleWriter:
    """Write a bundle (manifest.json and responses.csv from raw text cells)."""

    def write(raw: pd.DataFrame) -> Path:
        (tmp_path / "manifest.json").write_text(json.dumps(manifest_dict()))
        raw.to_csv(tmp_path / "responses.csv", index=False, lineterminator="\n")
        return tmp_path

    return write
