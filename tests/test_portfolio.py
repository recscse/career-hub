import json
from html.parser import HTMLParser

import pytest

from career_hub import db, portfolio, server


@pytest.fixture
def ctx():
    con = db.connect(":memory:")
    uid = db.ensure_default_user(con)
    db.set_profile(con, uid, name="Ada <b>Lovelace</b>", headline="Backend dev", summary="Builds things",
                   location="Remote", links="https://github.com/ada javascript:alert(1) example.com",
                   preferences="SECRET: wants 250k, open to relocation")
    db.add_item(con, uid, "skills", name="Go", level="advanced", years=3, evidence="Code in ada/PRIVATE-REPO (90%)", visibility="public")
    db.add_item(con, uid, "skills", name="Cobol", visibility="private")
    db.add_item(con, uid, "experience", role="Dev", company="PublicCo", start_date="2022-01",
                achievements="Cut latency 40%\n- Led migration", visibility="public")
    db.add_item(con, uid, "experience", role="Secret role", company="HiddenCorp")
    pub = db.add_item(con, uid, "projects", name="codive", description="<script>alert(1)</script>Code tool",
                      stack="Go", url="https://github.com/ada/codive", outcome="3 stars", visibility="public")
    priv = db.add_item(con, uid, "projects", name="private-proj", description="top secret", stack="Rust")
    pub_repo = db.upsert_repo(con, uid, "ada/codive", visibility="public", languages=json.dumps({"Go": 88.2, "Shell": 11.8}),
                              stars=3, homepage="https://codive.dev", my_commits=41, url="https://github.com/ada/codive")
    db.sync_repo_project(con, uid, pub_repo["id"], name="codive", stack="Go", outcome="3 stars")
    priv_repo = db.upsert_repo(con, uid, "ada/private-proj", visibility="private", languages=json.dumps({"Rust": 100.0}), stars=9)
    con.execute("UPDATE repos SET project_id = ? WHERE id = ?", (priv["id"], priv_repo["id"]))
    con.commit()
    db.add_item(con, uid, "contributions", repo="aden-hive/hive", title="Fix tracker", url="https://github.com/aden-hive/hive/pull/1",
                status="merged", visibility="public")
    db.add_item(con, uid, "contributions", repo="a/b", title="Open one", url="https://x/2", status="open", visibility="public")
    db.add_item(con, uid, "contributions", repo="c/d", title="Private merged", url="https://x/3", status="merged")
    return con, uid


def test_only_public_items_and_no_private_fields_leak(ctx):
    con, uid = ctx
    data = portfolio.build_site_data(con, uid)
    blob = json.dumps(data) + portfolio.render_html(data)
    for secret in ("SECRET", "250k", "Cobol", "HiddenCorp", "Secret role", "private-proj", "top secret",
                   "PRIVATE-REPO", "Private merged", "Open one"):
        assert secret not in blob, secret
    assert "preferences" not in data["profile"]
    assert all(set(s) == {"name", "level", "years"} for s in data["skills"])  # evidence is never exported
    assert [p["name"] for p in data["projects"]] == ["codive"]
    assert data["projects"][0]["languages_pct_by_bytes"] == {"Go": 88.2, "Shell": 11.8}
    assert data["projects"][0]["stars"] == 3 and data["projects"][0]["my_commits_lower_bound"] == 41
    assert [c["repo"] for c in data["open_source"]] == ["aden-hive/hive"]  # only merged + public


def test_private_repo_facts_not_joined_to_a_public_project(ctx):
    con, uid = ctx
    db.update_item(con, uid, "projects", 2, visibility="public")  # project public, its repo still private
    data = portfolio.build_site_data(con, uid)
    proj = next(p for p in data["projects"] if p["name"] == "private-proj")
    assert "languages_pct_by_bytes" not in proj and "stars" not in proj


class Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.hrefs = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.hrefs += [v for k, v in attrs if k == "href"]


def test_html_is_escaped_script_free_and_links_are_safe(ctx):
    con, uid = ctx
    page = portfolio.render_html(portfolio.build_site_data(con, uid))
    p = Collect()
    p.feed(page)
    assert "script" not in p.tags and "<script" not in page.lower()
    assert "&lt;b&gt;Lovelace&lt;/b&gt;" in page and "&lt;script&gt;" in page  # user text is escaped
    assert all(h.startswith("https://") for h in p.hrefs)  # no javascript: / relative links
    assert "javascript:alert(1)" in page  # shown as inert text only, never as a link
    assert 'rel="noopener noreferrer"' in page and "http-equiv" not in page
    for tag in ("html", "main", "h1", "section"):
        assert tag in p.tags


def test_safe_url():
    assert portfolio.safe_url("https://a.dev/x") and portfolio.safe_url("http://a.dev")
    for bad in ("javascript:alert(1)", "data:text/html,x", "//evil.com", "ftp://x.com", "", None, "https://", "a.dev"):
        assert portfolio.safe_url(bad) is None


def test_build_writes_files_and_is_repeatable(ctx, tmp_path):
    con, uid = ctx
    res = portfolio.build(con, uid, tmp_path / "site")
    assert sorted(res["files"]) == ["data.json", "index.html", "resume.md"]
    assert res["included"]["projects"] == 1
    data = json.loads((tmp_path / "site" / "data.json").read_text(encoding="utf-8"))
    assert data["generator"] == "career-context-hub"
    resume_md = (tmp_path / "site" / "resume.md").read_text(encoding="utf-8")
    assert "Cobol" not in resume_md and "HiddenCorp" not in resume_md and "Go" in resume_md
    portfolio.build(con, uid, tmp_path / "site")  # regenerating our own files is allowed


def test_refuses_to_overwrite_foreign_files(ctx, tmp_path):
    con, uid = ctx
    site = tmp_path / "mysite"
    site.mkdir()
    (site / "index.html").write_text("<h1>My hand-made portfolio</h1>", encoding="utf-8")
    with pytest.raises(portfolio.PortfolioError, match="did not generate"):
        portfolio.build(con, uid, site)
    assert "hand-made" in (site / "index.html").read_text(encoding="utf-8")  # untouched
    assert not (site / "data.json").exists()  # nothing partial was written
    portfolio.build(con, uid, site, overwrite=True)
    assert "hand-made" not in (site / "index.html").read_text(encoding="utf-8")


def test_empty_profile_still_builds(tmp_path):
    con = db.connect(":memory:")
    uid = db.ensure_default_user(con)
    portfolio.build(con, uid, tmp_path / "s")
    page = (tmp_path / "s" / "index.html").read_text(encoding="utf-8")
    assert "<title>Portfolio</title>" in page and "Skills" not in page


def test_tools_and_hosted_mode_restriction(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "t.db")
    server._state.clear()
    con, uid = server._ctx()
    db.set_profile(con, uid, name="Ada")
    db.add_item(con, uid, "skills", name="Go", visibility="public")
    assert server.portfolio_data()["skills"] == [{"name": "Go", "level": None, "years": None}]
    out = server.build_portfolio(str(tmp_path / "out"))
    assert (tmp_path / "out" / "index.html").exists() and out["included"]["skills"] == 1
    monkeypatch.setenv("CAREER_HUB_MODE", "hosted")
    with pytest.raises(ValueError, match="disabled in hosted mode"):
        server.build_portfolio(str(tmp_path / "out2"))
    assert not (tmp_path / "out2").exists()
    server._state.clear()
