from __future__ import annotations

import sqlite3

import pytest

from docmancer.core.sqlite import connect


def test_context_managed_connection_closes_its_file_descriptor(tmp_path) -> None:
    connection = connect(tmp_path / "state.sqlite")

    with connection as active:
        active.execute("CREATE TABLE state (value TEXT NOT NULL)")
        active.execute("INSERT INTO state (value) VALUES ('saved')")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT value FROM state")

    with connect(tmp_path / "state.sqlite") as reopened:
        assert reopened.execute("SELECT value FROM state").fetchone() == ("saved",)
