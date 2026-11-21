import sqlite3

import pytest

NEEDS_DROP_COLUMN = pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 35), reason="needs SQLite 3.35+ (DROP COLUMN)")


@pytest.fixture
def downgrade():
    """Return a function that turns a current database into a genuine older-version one.

    v2 = before job boards / resume-per-application columns (schema v3).
    v1 = also before the GitHub repos table (schema v2).
    """

    def _downgrade(con: sqlite3.Connection, version: int) -> None:
        assert version in (1, 2)
        con.execute("ALTER TABLE companies DROP COLUMN ats_provider")
        con.execute("ALTER TABLE companies DROP COLUMN ats_board")
        con.execute("ALTER TABLE applications DROP COLUMN resume_version_id")
        if version == 1:
            con.execute("DROP TABLE repos")
        con.execute(f"PRAGMA user_version = {version}")
        con.commit()

    return _downgrade
