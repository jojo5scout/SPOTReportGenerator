"""Settings read from the environment.

Functions take the environment as a mapping (``os.environ`` in production, a plain
dict in tests), so there is no global state. What a command does when a setting is
absent is decided by the command, not here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

ARCHIVE_DIR_VAR = "SPOT_ARCHIVE_DIR"


def archive_dir(env: Mapping[str, str]) -> Path | None:
    """The bundle archive root from ``SPOT_ARCHIVE_DIR``; ``None`` if unset or empty."""
    value = env.get(ARCHIVE_DIR_VAR, "").strip()
    return Path(value) if value else None
