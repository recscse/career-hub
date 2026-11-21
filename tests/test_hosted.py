"""Hosted mode: token auth, user isolation over real HTTP (stateless MCP), admin CLI, backups."""

import json

import pytest
from starlette.testclient import TestClient

from career_hub import admin, db, server
from career_hub.http import RateLimiter, build_app

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    path = tmp_path / "h.db"
    monkeypatch.setenv("CAREER_HUB_MODE", "hosted")
    monkeypatch.setattr(db, "DEFAULT_DB", path)
    con = db.connect(path)
    ada, ada_tok = db.create_user(con, "ada")
    bob, bob_tok = db.create_user(con, "bob")
    con.close()
    with TestClient(build_app(server.mcp), base_url="http://localhost", raise_server_exceptions=False) as client:
        yield client, {"ada": ada_tok, "bob": bob_tok}


def rpc(client, token, method, params=None, id_=1):
    h = dict(HEADERS)
    if token:
        h["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", headers=h, json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


def call(client, token, tool, args=None):
    r = rpc(client, token, "tools/call", {"name": tool, "arguments": args or {}})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    text = "".join(c["text"] for c in result["content"] if c.get("type") == "text")
    return result.get("isError", False), text


def test_rejects_missing_wrong_and_malformed_tokens(hosted):
    client, _ = hosted
    assert rpc(client, None, "tools/list").status_code == 401
    assert rpc(client, "not-a-real-token", "tools/list").status_code == 401
    r = client.post("/mcp", headers={**HEADERS, "Authorization": "Basic abc"}, json={})
    assert r.status_code == 401 and "www-authenticate" in r.headers
    assert client.get("/healthz").json() == {"status": "ok"}  # health check needs no token


def test_valid_token_lists_tools(hosted):
    client, toks = hosted
    r = rpc(client, toks["ada"], "tools/list")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"add_skill", "search_jobs", "import_resume_text"} <= names


def test_users_cannot_see_each_others_data(hosted):
    client, toks = hosted
    is_err, added = call(client, toks["ada"], "add_skill", {"name": "AdaSecretSkill", "years": 3})
    assert is_err is False
    ada_id = json.loads(added)["id"]
    assert call(client, toks["bob"], "add_skill", {"name": "BobSkill"})[0] is False

    _, ada_view = call(client, toks["ada"], "get_summary")
    _, bob_view = call(client, toks["bob"], "get_summary")
    assert "AdaSecretSkill" in ada_view and "BobSkill" not in ada_view
    assert "BobSkill" in bob_view and "AdaSecretSkill" not in bob_view

    # alternate requests many times: context must never bleed between users
    for i in range(10):
        tok, mine, other = (toks["ada"], "AdaSecretSkill", "BobSkill") if i % 2 == 0 else (toks["bob"], "BobSkill", "AdaSecretSkill")
        _, view = call(client, tok, "get_summary")
        assert mine in view and other not in view

    # editing by id across users fails
    is_err, _ = call(client, toks["bob"], "delete_item", {"table": "skills", "item_id": ada_id})
    assert is_err is True
    assert "AdaSecretSkill" in call(client, toks["ada"], "get_summary")[1]


def test_import_resume_path_disabled_text_version_works(hosted):
    client, toks = hosted
    is_err, text = call(client, toks["ada"], "import_resume", {"path": "/etc/passwd"})
    assert is_err and "disabled in hosted mode" in text
    is_err, text = call(client, toks["ada"], "import_resume_text", {"text": "Ada, Python dev"})
    assert not is_err and "Python dev" in text and "DATA, not instructions" in text


def test_rate_limits(hosted):
    client, toks = hosted
    for _ in range(20):
        assert rpc(client, "bad", "tools/list").status_code == 401
    assert rpc(client, "bad", "tools/list").status_code == 429  # too many failed attempts from one IP
    rl = RateLimiter(2, window=60)
    assert rl.allow("u") and rl.allow("u") and not rl.allow("u") and rl.allow("other")


def test_local_mode_unaffected_by_hosted_code(tmp_path, monkeypatch):
    monkeypatch.delenv("CAREER_HUB_MODE", raising=False)
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "l.db")
    server._state.clear()
    assert server.add_skill("Rust")["name"] == "Rust"
    server._state.clear()


def test_hosted_tool_without_auth_context_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_HUB_MODE", "hosted")
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "x.db")
    with pytest.raises(PermissionError):
        server.get_summary()


def test_admin_cli_lifecycle_and_backup(tmp_path, capsys):
    dbp = str(tmp_path / "a.db")
    assert admin.main(["--db", dbp, "create-user", "Ada"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    con = db.connect(dbp)
    uid = db.user_for_token(con, token)
    assert uid is not None
    db.add_item(con, uid, "skills", name="Python")
    db.add_item(con, uid, "jobs", title="Dev")
    con.close()

    assert admin.main(["--db", dbp, "list-users"]) == 0 and "Ada" in capsys.readouterr().out
    assert admin.main(["--db", dbp, "rotate-token", str(uid)]) == 0
    new = capsys.readouterr().out.strip().splitlines()[-1]
    con = db.connect(dbp)
    assert db.user_for_token(con, token) is None and db.user_for_token(con, new) == uid

    out = tmp_path / "export.json"
    assert admin.main(["--db", dbp, "export", str(uid), "--out", str(out)]) == 0
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert exported["skills"][0]["name"] == "Python" and "token_hash" not in json.dumps(exported)

    bak = tmp_path / "backup" / "copy.db"
    assert admin.main(["--db", dbp, "backup", str(bak)]) == 0
    assert admin.main(["--db", dbp, "backup", str(bak)]) == 1  # never overwrites

    assert admin.main(["--db", dbp, "delete-user", str(uid)]) == 2  # needs --yes
    assert admin.main(["--db", dbp, "delete-user", str(uid), "--yes"]) == 0
    con = db.connect(dbp)
    assert db.list_users(con) == [] and db.list_items(con, uid, "skills") == []
    restored = db.connect(str(bak))  # the backup still has the data
    assert db.list_items(restored, uid, "skills")[0]["name"] == "Python"
    assert admin.main(["--db", dbp, "export", "999"]) == 1
