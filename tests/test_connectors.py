import pytest

from career_hub import connectors, db, server

GREENHOUSE = {
    "jobs": [
        {
            "title": "Backend Engineer", "company_name": "GitLab", "absolute_url": "https://gh/1",
            "location": {"name": "Remote, United States"},
            "content": "&lt;p&gt;We use Python &amp;amp; PostgreSQL.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Kubernetes&lt;/li&gt;&lt;/ul&gt;",
        },
        {
            "title": "Office Manager", "company_name": "GitLab", "absolute_url": "https://gh/2",
            "location": {"name": "Berlin"}, "content": "&lt;p&gt;Snacks&lt;/p&gt;",
        },
    ]
}
LEVER = [
    {"text": "SRE", "hostedUrl": "https://lever/1", "categories": {"location": "Paris"},
     "workplaceType": "hybrid", "descriptionPlain": "Terraform and Python"},
]
ASHBY = {
    "jobs": [
        {"title": "ML Engineer", "jobUrl": "https://ashby/1", "location": "NYC", "isRemote": True,
         "workplaceType": "Remote", "isListed": True, "descriptionPlain": "PyTorch and Python"},
        {"title": "Hidden", "jobUrl": "https://ashby/2", "isListed": False, "descriptionPlain": "x"},
    ]
}


def fake(monkeypatch, payloads):
    calls = []

    def _get(url):
        calls.append(url)
        for key, val in payloads.items():
            if key in url:
                return val
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(connectors, "_get_json", _get)
    return calls


def test_clean_html_handles_escaped_and_plain():
    assert connectors.clean_html("&lt;p&gt;A &amp;amp; B&lt;/p&gt;&lt;li&gt;C&lt;/li&gt;") == "A & B\nC"
    assert connectors.clean_html("<b>Hi</b><br>there") == "Hi\nthere"
    assert "<" not in connectors.clean_html("<div><span>x</span></div>")
    assert connectors.clean_html(None) == ""


def test_providers_normalize(monkeypatch):
    fake(monkeypatch, {"greenhouse": GREENHOUSE, "lever": LEVER, "ashby": ASHBY})
    gh = connectors.fetch_greenhouse("gitlab")
    assert gh[0]["remote"] == "remote" and "Python & PostgreSQL" in gh[0]["description"] and gh[1]["remote"] is None
    assert connectors.fetch_lever("x")[0]["remote"] == "hybrid"
    ab = connectors.fetch_ashby("x")
    assert len(ab) == 1 and ab[0]["remote"] == "remote"  # unlisted job dropped


def test_hn_thread(monkeypatch):
    fake(monkeypatch, {
        "search_by_date": {"hits": [{"objectID": "7", "title": "Ask HN: Who is hiring? (November 2026)"}]},
        "items/7": {"children": [
            {"id": 11, "text": "Acme | Backend | REMOTE | Python<p>We use Django"},
            {"id": 12, "text": None},
        ]},
    })
    jobs = connectors.fetch_hn_hiring()
    assert len(jobs) == 1 and jobs[0]["company"] == "Acme" and jobs[0]["remote"] == "remote"
    assert jobs[0]["url"].endswith("id=11")


def test_input_validation_blocks_bad_names_and_hosts():
    for bad in ("../x", "a b", "", "x" * 81, "a/b", "a?b=c"):
        with pytest.raises(connectors.ConnectorError):
            connectors.fetch_greenhouse(bad)
    with pytest.raises(connectors.ConnectorError):
        connectors._get_json("https://evil.example.com/x")
    with pytest.raises(connectors.ConnectorError):
        connectors.fetch_jobs("monster", "x")
    with pytest.raises(connectors.ConnectorError):
        connectors.fetch_github_prs("bad user")


def test_filter_jobs():
    jobs = [
        {"title": "A", "description": "python", "remote": "remote"},
        {"title": "B", "description": "java", "remote": None},
    ]
    assert len(connectors.filter_jobs(jobs, ["PYTHON"])) == 1
    assert len(connectors.filter_jobs(jobs, remote_only=True)) == 1
    assert len(connectors.filter_jobs(jobs)) == 2


def test_github_prs_skip_own_repos_and_map_status(monkeypatch):
    fake(monkeypatch, {"search/issues": {"items": [
        {"repository_url": "https://api.github.com/repos/aden-hive/hive", "title": "Fix", "html_url": "https://gh/pr/1",
         "state": "closed", "pull_request": {"merged_at": "2026-11-01T00:00:00Z"}},
        {"repository_url": "https://api.github.com/repos/me/mine", "title": "Own", "html_url": "https://gh/pr/2",
         "state": "open", "pull_request": {"merged_at": None}},
        {"repository_url": "https://api.github.com/repos/a/b", "title": "Open", "html_url": "https://gh/pr/3",
         "state": "open", "pull_request": {"merged_at": None}},
        {"repository_url": "https://api.github.com/repos/a/c", "title": "Closed", "html_url": "https://gh/pr/4",
         "state": "closed", "pull_request": {"merged_at": None}},
    ]}})
    prs = connectors.fetch_github_prs("me")
    assert [(p["repo"], p["status"]) for p in prs] == [("aden-hive/hive", "merged"), ("a/b", "open"), ("a/c", "closed")]


@pytest.fixture
def tool_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_HUB_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "t.db")
    server._state.clear()
    con, uid = server._ctx()
    db.add_item(con, uid, "skills", name="Python")
    db.add_item(con, uid, "skills", name="PostgreSQL")
    yield con, uid
    server._state.clear()


def test_search_jobs_ranks_filters_and_saves(monkeypatch, tool_ctx):
    con, uid = tool_ctx
    fake(monkeypatch, {"greenhouse": GREENHOUSE})
    r = server.search_jobs("greenhouse", "gitlab", remote_only=True, save=True)
    assert r["found"] == 1 and "untrusted" in r["note"]
    top = r["results"][0]
    assert top["title"] == "Backend Engineer" and top["saved"] is True
    assert set(top["matched"]) == {"python", "postgresql"} and top["missing"] == ["kubernetes"]
    assert db.list_items(con, uid, "jobs")[0]["description"].startswith("We use Python")
    # second run: same URL is reported as already saved, not duplicated
    again = server.search_jobs("greenhouse", "gitlab", remote_only=True, save=True)
    assert again["results"][0]["saved"] is False and len(db.list_items(con, uid, "jobs")) == 1
    with pytest.raises(ValueError):
        server.search_jobs("greenhouse", "../etc")


def test_sync_github_adds_then_updates_status(monkeypatch, tool_ctx):
    con, uid = tool_ctx
    items = {"items": [{"repository_url": "https://api.github.com/repos/a/b", "title": "T", "html_url": "https://gh/pr/9",
                        "state": "open", "pull_request": {"merged_at": None}}]}
    fake(monkeypatch, {"search/issues": items})
    assert server.sync_github_contributions("me") == {"checked": 1, "added": 1, "status_updated": 0}
    items["items"][0]["pull_request"]["merged_at"] = "2026-11-02T00:00:00Z"
    items["items"][0]["state"] = "closed"
    assert server.sync_github_contributions("me") == {"checked": 1, "added": 0, "status_updated": 1}
    assert db.list_items(con, uid, "contributions")[0]["status"] == "merged"
