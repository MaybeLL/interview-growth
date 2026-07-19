"""SQLite connection helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def connect_database(path: Path) -> sqlite3.Connection:
    """Open a configured SQLite connection and protect newly created files."""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    was_missing = not path.exists()
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = NORMAL")
    if was_missing:
        os.chmod(path, 0o600)
    return connection
