import sqlite3

import pytest
from conftest import NEEDS_DROP_COLUMN

from career_hub import db


def version(path) -> int:
    con = sqlite3.connect(str(path))
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


def test_fresh_database_is_stamped_with_current_version(tmp_path):
    p = tmp_path / "a.db"
    db.connect(p).close()
    assert version(p) == db.schema_version()


@NEEDS_DROP_COLUMN
def test_database_created_before_versioning_is_adopted_without_data_loss(tmp_path, downgrade):
    p = tmp_path / "old.db"
    con = db.connect(p)
    uid = db.ensure_default_user(con)
    db.add_item(con, uid, "skills", name="Python")
    downgrade(con, 1)
    con.execute("PRAGMA user_version = 0")  # a pre-versioning install: old schema, no version stamp
    con.commit()
    con.close()
    con = db.connect(p)
    assert [s["name"] for s in db.list_items(con, uid, "skills")] == ["Python"]
    assert version(p) == db.schema_version()


def test_pending_migrations_run_once_in_order_and_keep_data(tmp_path, monkeypatch):
    p = tmp_path / "m.db"
    con = db.connect(p)
    uid = db.ensure_default_user(con)
    db.add_item(con, uid, "skills", name="Go")
    con.close()

    base = db.schema_version()
    monkeypatch.setattr(db, "MIGRATIONS", [
        *db.MIGRATIONS,
        "ALTER TABLE skills ADD COLUMN note TEXT;",
        "UPDATE skills SET note = 'migrated';",
    ])
    con = db.connect(p)
    row = con.execute("SELECT name, note FROM skills").fetchone()
    assert (row["name"], row["note"]) == ("Go", "migrated")
    assert version(p) == base + 2
    con.close()
    db.connect(p).close()  # reopening must not re-run (ALTER would fail on a duplicate column)
    assert version(p) == base + 2


def test_failed_migration_rolls_back_and_keeps_old_version(tmp_path, monkeypatch):
    p = tmp_path / "f.db"
    db.connect(p).close()
    base = db.schema_version()
    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, "ALTER TABLE skills ADD COLUMN ok TEXT; SELECT * FROM no_such_table;"])
    with pytest.raises(sqlite3.Error):
        db.connect(p)
    assert version(p) == base
    con = sqlite3.connect(str(p))
    assert "ok" not in [r[1] for r in con.execute("PRAGMA table_info(skills)")]  # partial change undone


@NEEDS_DROP_COLUMN
def test_v2_database_gains_job_board_and_resume_columns_keeping_data(tmp_path, downgrade):
    p = tmp_path / "v2.db"
    con = db.connect(p)
    uid = db.ensure_default_user(con)
    db.add_item(con, uid, "companies", name="Grafana", priority=5)
    job = db.add_item(con, uid, "jobs", title="Dev")
    db.track_application(con, uid, job["id"], status="applied")
    downgrade(con, 2)
    assert "ats_provider" not in [r[1] for r in con.execute("PRAGMA table_info(companies)")]
    con.close()

    con = db.connect(p)
    assert version(p) == db.schema_version()
    assert {"ats_provider", "ats_board"} <= {r[1] for r in con.execute("PRAGMA table_info(companies)")}
    assert db.list_items(con, uid, "companies")[0]["name"] == "Grafana"
    assert db.list_applications(con, uid)[0]["status"] == "applied"
    v = db.add_item(con, uid, "resume_versions", label="x", content="c")
    assert db.track_application(con, uid, job["id"], resume_version_id=v["id"])["resume_version_id"] == v["id"]


def test_newer_database_is_refused(tmp_path):
    p = tmp_path / "n.db"
    db.connect(p).close()
    con = sqlite3.connect(str(p))
    con.execute("PRAGMA user_version = 99")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="newer than this"):
        db.connect(p)
