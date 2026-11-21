"""Regression tests for cross-user access through crafted table names (found 2026-11-21)."""

import json

import pytest
from starlette.testclient import TestClient

from career_hub import db, server
from career_hub.http import build_app

BAD_TABLES = [
    "skills AS s WHERE 1=1 OR ? = ? --",  # the original exploit: bypassed the user_id filter
    "users",
    "applications",  # real table, but not part of the generic item API
    "skills; DROP TABLE skills",
    "skills WHERE 1=1 --",
    "",
    "SKILLS",
    None,
    7,
]


@pytest.fixture
def two_users():
    con = db.connect(":memory:")
    attacker = db.ensure_default_user(con)
    victim, _ = db.create_user(con, "victim")
    row = db.add_item(con, victim, "skills", name="victim-secret-skill")
    return con, attacker, victim, row["id"]


@pytest.mark.parametrize("table", BAD_TABLES)
def test_crafted_table_names_are_rejected_everywhere_and_victim_data_survives(two_users, table):
    con, attacker, victim, victim_row = two_users
    calls = [
        lambda: db.get_item(con, attacker, table, victim_row),
        lambda: db.delete_item(con, attacker, table, victim_row),
        lambda: db.update_item(con, attacker, table, victim_row, name="pwned"),
        lambda: db.add_item(con, attacker, table, name="x"),
        lambda: db.list_items(con, attacker, table),
    ]
    for call in calls:
        with pytest.raises(ValueError, match="unknown table"):
            call()
    assert db.get_item(con, victim, "skills", victim_row)["name"] == "victim-secret-skill"
    assert con.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 1  # nothing created, changed or deleted


def test_every_allowed_table_still_works(two_users):
    con, attacker, _, _ = two_users
    assert set(db.COLUMNS) >= {"skills", "experience", "projects", "contributions", "jobs", "companies", "prep",
                               "resume_versions", "repos"}
    for table in db.COLUMNS:
        assert db.list_items(con, attacker, table) == []  # valid names are accepted (and empty for this user)


HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_over_http_a_second_user_cannot_touch_the_first_users_rows(tmp_path, monkeypatch):
    path = tmp_path / "s.db"
    monkeypatch.setenv("CAREER_HUB_MODE", "hosted")
    monkeypatch.setattr(db, "DEFAULT_DB", path)
    con = db.connect(path)
    ada, ada_tok = db.create_user(con, "ada")
    _, bob_tok = db.create_user(con, "bob")
    skill = db.add_item(con, ada, "skills", name="ada-private-skill")
    con.close()

    def call(token, tool, args):
        r = client.post("/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        return res.get("isError", False), "".join(c["text"] for c in res["content"] if c.get("type") == "text")

    with TestClient(build_app(server.mcp), base_url="http://localhost", raise_server_exceptions=False) as client:
        evil = "skills AS s WHERE 1=1 OR ? = ? --"
        for tool, args in (
            ("delete_item", {"table": evil, "item_id": skill["id"]}),
            ("update_item", {"table": evil, "item_id": skill["id"], "fields": {"name": "pwned"}}),
            ("list_items", {"table": evil}),
            ("delete_item", {"table": "skills", "item_id": skill["id"]}),  # legit table, someone else's row
        ):
            is_err, text = call(bob_tok, tool, args)
            assert is_err, f"{tool} {args} should have failed but returned: {text}"
        is_err, view = call(ada_tok, "get_summary", {})
        assert not is_err and "ada-private-skill" in view and "pwned" not in view
        assert json.loads(call(ada_tok, "list_items", {"table": "skills"})[1])["name"] == "ada-private-skill"
