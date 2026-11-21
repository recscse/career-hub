import base64
import json
import sqlite3

import pytest
from conftest import NEEDS_DROP_COLUMN

from career_hub import connectors, db, github_sync, matching, server

USER_REPOS = [
    {"name": "codive", "full_name": "me/codive", "owner": {"login": "me"}, "fork": False, "archived": False,
     "description": "Code intelligence", "language": "Go", "stargazers_count": 3, "topics": ["mcp", "go"],
     "homepage": "https://codive.dev", "html_url": "https://github.com/me/codive", "pushed_at": "2026-11-17T10:00:00Z"},
    {"name": "tutorial", "full_name": "me/tutorial", "owner": {"login": "me"}, "fork": False, "archived": True,
     "description": "old", "language": "HTML", "stargazers_count": 0, "html_url": "https://github.com/me/tutorial",
     "pushed_at": "2020-01-01T00:00:00Z"},
    {"name": "hive", "full_name": "me/hive", "owner": {"login": "me"}, "fork": True, "archived": False,
     "description": "fork", "language": "Python", "stargazers_count": 0, "html_url": "https://github.com/me/hive",
     "pushed_at": "2026-11-18T10:00:00Z"},
]
LANGS = {"me/codive": {"Go": 8200, "Dockerfile": 1000, "Shell": 100}, "me/hive": {"Python": 5000}}
CONTRIBUTORS = {"me/codive": [{"login": "someone", "contributions": 9}, {"login": "Me", "contributions": 41}]}
README = "# Codive\n![badge](x.png)\nIndexes code for AI agents.\n<script>bad()</script>"


def install_fake(monkeypatch, *, fail_languages=False):
    calls = []

    def _get(url):
        calls.append(url)
        if "/users/me/repos" in url:
            return USER_REPOS if "page=1" in url else []
        for full in ("me/codive", "me/hive"):
            if f"/repos/{full}/languages" in url:
                if fail_languages:
                    raise connectors.ConnectorError("rate limited")
                return LANGS[full]
            if f"/repos/{full}/contributors" in url:
                return CONTRIBUTORS.get(full, [])
            if f"/repos/{full}/readme" in url:
                if full == "me/hive":
                    raise connectors.ConnectorError("404")
                return {"encoding": "base64", "content": base64.b64encode(README.encode()).decode()}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(connectors, "_get_json", _get)
    return calls


@pytest.fixture
def ctx():
    con = db.connect(":memory:")
    return con, db.ensure_default_user(con)


def test_dry_run_saves_nothing_and_hides_forks_and_archived(monkeypatch, ctx):
    con, uid = ctx
    install_fake(monkeypatch)
    names = [r["full_name"] for r in github_sync.candidates(con, uid, "me")]
    assert names == ["me/codive"]
    assert db.list_items(con, uid, "repos") == [] and db.list_items(con, uid, "projects") == []
    both = github_sync.candidates(con, uid, "me", include_forks=True, include_archived=True)
    assert {r["full_name"] for r in both} == {"me/codive", "me/tutorial", "me/hive"}


def test_import_only_selected_with_facts_and_linked_project(monkeypatch, ctx):
    con, uid = ctx
    calls = install_fake(monkeypatch)
    res = github_sync.import_repos(con, uid, "me", ["codive", "nope"])
    assert [i["repo"] for i in res["imported"]] == ["me/codive"]
    assert res["problems"][0]["repo"] == "nope"
    assert not any("tutorial" in c or "me/hive" in c for c in calls if "/repos/" in c)  # others never fetched

    imp = res["imported"][0]
    assert imp["my_commits"] == 41 and imp["visibility"] == "private" and imp["has_readme"] is True
    assert imp["languages_pct_by_bytes"] == {"Go": 88.2, "Dockerfile": 10.8, "Shell": 1.1}
    repo = db.list_items(con, uid, "repos")[0]
    assert "badge" not in repo["readme_excerpt"] and "<script" not in repo["readme_excerpt"]
    proj = db.get_item(con, uid, "projects", imp["project_id"])
    assert proj["stack"] == "Go, Dockerfile"  # Shell is under 5%
    assert proj["outcome"] == "3 stars; 41 commits by you (lower bound)"
    assert proj["visibility"] == "private" and proj["url"] == "https://github.com/me/codive"


def test_public_flag_and_resync_keeps_user_owned_text(monkeypatch, ctx):
    con, uid = ctx
    install_fake(monkeypatch)
    first = github_sync.import_repos(con, uid, "me", ["codive"], public=True)["imported"][0]
    assert first["visibility"] == "public"
    db.set_repo_summary(con, uid, first["repo_id"], "My own words about codive")
    db.update_item(con, uid, "repos", first["repo_id"], visibility="private")

    USER_REPOS[0]["stargazers_count"] = 10
    try:
        again = github_sync.import_repos(con, uid, "me", ["me/codive"], public=True)["imported"][0]
    finally:
        USER_REPOS[0]["stargazers_count"] = 3
    assert again["repo_id"] == first["repo_id"] and len(db.list_items(con, uid, "repos")) == 1
    repo = db.get_item(con, uid, "repos", first["repo_id"])
    assert repo["stars"] == 10  # facts refresh
    assert repo["summary"] == "My own words about codive" and repo["visibility"] == "private"  # user choices survive
    proj = db.get_item(con, uid, "projects", repo["project_id"])
    assert proj["description"] == "My own words about codive" and proj["outcome"].startswith("10 stars")
    assert len(db.list_items(con, uid, "projects")) == 1


def test_existing_project_with_same_name_is_linked_not_overwritten(monkeypatch, ctx):
    con, uid = ctx
    install_fake(monkeypatch)
    mine = db.add_item(con, uid, "projects", name="codive", description="Hand written text")
    imp = github_sync.import_repos(con, uid, "me", ["codive"])["imported"][0]
    assert imp["project_id"] == mine["id"]
    proj = db.get_item(con, uid, "projects", mine["id"])
    assert proj["description"] == "Hand written text" and proj["stack"] == "Go, Dockerfile"


def test_partial_failure_is_reported_not_fatal(monkeypatch, ctx):
    con, uid = ctx
    install_fake(monkeypatch, fail_languages=True)
    imp = github_sync.import_repos(con, uid, "me", ["codive"])["imported"][0]
    assert imp["warnings"] and "languages unavailable" in imp["warnings"][0]
    assert imp["languages_pct_by_bytes"] == {} and db.list_items(con, uid, "repos")[0]["my_commits"] == 41


def test_unknown_commit_count_is_none_not_zero_when_api_fails(monkeypatch, ctx):
    con, uid = ctx
    install_fake(monkeypatch)
    real = connectors._get_json

    def flaky(url):
        if "contributors" in url:
            raise connectors.ConnectorError("boom")
        return real(url)

    monkeypatch.setattr(connectors, "_get_json", flaky)
    imp = github_sync.import_repos(con, uid, "me", ["codive"])["imported"][0]
    assert imp["my_commits"] is None
    assert db.get_item(con, uid, "projects", imp["project_id"])["outcome"] == "3 stars"  # no invented commit claim


def test_suggest_skills_apply_and_improves_job_match(monkeypatch, ctx):
    con, uid = ctx
    install_fake(monkeypatch)
    github_sync.import_repos(con, uid, "me", ["codive", "hive"])  # hive is a fork
    job = "We build backend services in Go and Docker."
    before = matching.compare(con, uid, description=job)  # no skills yet: everything is missing
    assert before["score"] == 0 and before["missing"] == ["go", "docker"]

    preview = github_sync.suggest_skills(con, uid)
    assert [s["skill"] for s in preview["suggestions"]] == ["Go", "Dockerfile"]  # fork's Python excluded
    assert db.list_items(con, uid, "skills") == []  # preview changes nothing

    done = github_sync.suggest_skills(con, uid, apply=True)
    assert done["added"] == ["Go", "Dockerfile"]
    assert "me/codive" in db.list_items(con, uid, "skills")[0]["evidence"]
    assert github_sync.suggest_skills(con, uid, apply=True)["added"] == []  # idempotent
    r = matching.compare(con, uid, description=job)
    assert {m["skill"] for m in r["matched"]} == {"go", "docker"} and r["missing"] == [] and r["score"] == 100


def test_repos_are_isolated_and_deleted_with_user(monkeypatch, ctx):
    con, uid = ctx
    other, _ = db.create_user(con, "other")
    install_fake(monkeypatch)
    imp = github_sync.import_repos(con, uid, "me", ["codive"])["imported"][0]
    assert db.list_items(con, other, "repos") == []
    with pytest.raises(ValueError):
        db.set_repo_summary(con, other, imp["repo_id"], "hijack")
    assert db.export_user(con, uid)["repos"][0]["full_name"] == "me/codive"
    removed = db.delete_user(con, uid)
    assert removed["repos"] == 1 and removed["projects"] == 1
    assert con.execute("SELECT COUNT(*) FROM repos").fetchone()[0] == 0


def test_only_user_editable_fields_via_generic_update(ctx):
    con, uid = ctx
    r = db.upsert_repo(con, uid, "me/x", description="d")
    db.update_item(con, uid, "repos", r["id"], summary="s")
    with pytest.raises(ValueError):
        db.update_item(con, uid, "repos", r["id"], stars=99999)  # sync-owned facts can't be edited by hand


def test_invalid_names_are_rejected_before_any_request():
    for bad in ("../x", "a b", "", "x" * 81):
        with pytest.raises(connectors.ConnectorError):
            connectors.fetch_user_repos(bad)
    with pytest.raises(connectors.ConnectorError):
        connectors.fetch_repo_languages("no-slash")
    with pytest.raises(connectors.ConnectorError):
        connectors.fetch_repo_languages("a/../b")


@NEEDS_DROP_COLUMN
def test_v1_database_upgrades_to_current_keeping_data(tmp_path, downgrade):
    p = tmp_path / "v1.db"
    con = db.connect(p)
    uid = db.ensure_default_user(con)
    db.add_item(con, uid, "skills", name="Python")
    downgrade(con, 1)
    assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'repos'").fetchone() is None
    con.close()
    con = db.connect(p)
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.schema_version()
    assert db.list_items(con, uid, "skills")[0]["name"] == "Python"
    assert db.upsert_repo(con, uid, "me/x")["full_name"] == "me/x"


@pytest.fixture
def tool_ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "t.db")
    server._state.clear()
    yield server._ctx()
    server._state.clear()


def test_tools_end_to_end(monkeypatch, tool_ctx):
    con, uid = tool_ctx
    install_fake(monkeypatch)
    listing = server.list_github_repos("me")
    assert "Nothing has been saved" in listing["note"] and [r["full_name"] for r in listing["repos"]] == ["me/codive"]
    res = server.import_github_repos("me", ["codive"])
    server.set_repo_summary(res["imported"][0]["repo_id"], "Indexes code for AI agents")
    out = server.suggest_skills_from_repos(apply=True)
    assert out["added"] == ["Go", "Dockerfile"]
    assert "Indexes code for AI agents" in server.get_summary() and "Go" in server.get_summary()
    with pytest.raises(ValueError):
        server.import_github_repos("me", [])
    with pytest.raises(ValueError):
        server.list_github_repos("bad user")
    assert isinstance(sqlite3.connect(":memory:"), sqlite3.Connection)
