"""SQLite helpers with explicit connection lifetime management."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back a context-managed transaction, then close it."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def connect(database: str | Path, *args: Any, **kwargs: Any) -> ClosingConnection:
    """Open a connection whose context manager also releases its descriptor."""
    kwargs.setdefault("factory", ClosingConnection)
    return sqlite3.connect(database, *args, **kwargs)
