"""The whole job-search workflow: watchlist search -> prepare -> apply -> follow-up -> interview brief."""

import pytest

from career_hub import connectors, db, workflow

GREENHOUSE = {"jobs": [
    {"title": "Backend Engineer", "company_name": "GitLab", "absolute_url": "https://gh/1",
     "location": {"name": "Remote, US"}, "content": "&lt;p&gt;Go, Docker and Kubernetes&lt;/p&gt;"},
    {"title": "Office Manager", "company_name": "GitLab", "absolute_url": "https://gh/2",
     "location": {"name": "Berlin"}, "content": "&lt;p&gt;Snacks&lt;/p&gt;"},
]}
LEVER = [{"text": "Platform Engineer", "hostedUrl": "https://lever/1", "categories": {"location": "Paris"},
          "workplaceType": "remote", "descriptionPlain": "Python and Terraform"}]


@pytest.fixture
def ctx():
    con = db.connect(":memory:")
    uid = db.ensure_default_user(con)
    for n in ("Go", "Docker", "Python"):
        db.add_item(con, uid, "skills", name=n, years=3)
    db.add_item(con, uid, "projects", name="codive", description="Code tool", stack="Go, Dockerfile", outcome="3 stars")
    db.add_item(con, uid, "companies", name="GitLab", ats_provider="greenhouse", ats_board="gitlab", remote_policy="fully remote", priority=5)
    db.add_item(con, uid, "companies", name="Palantir", ats_provider="lever", ats_board="palantir")
    db.add_item(con, uid, "companies", name="No board")  # ignored by watchlist search
    return con, uid


def fake(monkeypatch, *, broken=()):
    seen = []

    def _get(url):
        seen.append(url)
        for name in broken:
            if name in url:
                raise connectors.ConnectorError(f"{name} down")
        if "greenhouse" in url:
            return GREENHOUSE
        if "lever" in url:
            return LEVER
        raise AssertionError(url)

    monkeypatch.setattr(connectors, "_get_json", _get)
    return seen


def test_company_board_validation(ctx):
    con, uid = ctx
    for bad in ({"ats_provider": "workday", "ats_board": "x"}, {"ats_provider": "lever", "ats_board": "../x"},
                {"ats_provider": "lever"}, {"ats_board": "x"}):
        with pytest.raises(ValueError):
            db.add_item(con, uid, "companies", name="X" + str(len(bad)) + str(bad), **bad)


def test_watchlist_search_ranks_saves_and_reports_only_new(ctx, monkeypatch):
    con, uid = ctx
    seen = fake(monkeypatch)
    first = workflow.search_watchlist(con, uid, keywords=["go", "python", "terraform"])
    assert first["companies_checked"] == 2 and first["saved_new_jobs"] == 2
    assert [r["title"] for r in first["results"]] == ["Backend Engineer", "Platform Engineer"]  # Office Manager filtered
    top = first["results"][0]
    assert top["new"] and top["job_id"] and set(top["matched"]) == {"go", "docker"} and top["missing"] == ["kubernetes"]
    assert len(seen) == 2  # the company without a board was never contacted

    second = workflow.search_watchlist(con, uid, keywords=["go", "python", "terraform"])
    assert second["results"] == [] and second["saved_new_jobs"] == 0  # nothing new since last run
    again = workflow.search_watchlist(con, uid, keywords=["go"], new_only=False)
    assert [r["title"] for r in again["results"]] == ["Backend Engineer"] and again["results"][0]["new"] is False
    assert len(db.list_items(con, uid, "jobs")) == 2  # no duplicates


def test_limit_only_caps_what_is_shown_not_what_counts_as_seen(ctx, monkeypatch):
    """Regression (found by running on real data): unshown jobs were reported as new again next run."""
    con, uid = ctx
    fake(monkeypatch)
    first = workflow.search_watchlist(con, uid, keywords=["go", "python", "terraform"], limit=1)
    assert len(first["results"]) == 1 and first["matches"] == 2 and first["saved_new_jobs"] == 2
    assert first["new_matches"] == 2 and first["not_saved_over_max_save"] == 0
    assert len(db.list_items(con, uid, "jobs")) == 2  # both saved, though only one was returned
    second = workflow.search_watchlist(con, uid, keywords=["go", "python", "terraform"], limit=1)
    assert second["results"] == [] and second["saved_new_jobs"] == 0 and second["new_matches"] == 0


def test_max_save_caps_storage_and_reports_the_rest(ctx, monkeypatch):
    con, uid = ctx
    fake(monkeypatch)
    r = workflow.search_watchlist(con, uid, keywords=["go", "python", "terraform"], max_save=1)
    assert r["saved_new_jobs"] == 1 and r["not_saved_over_max_save"] == 1 and len(db.list_items(con, uid, "jobs")) == 1
    nothing = workflow.search_watchlist(con, uid, keywords=["go", "python", "terraform"], max_save=0)
    assert nothing["saved_new_jobs"] == 0 and nothing["not_saved_over_max_save"] == 1  # only the unsaved one is still new


def test_results_say_how_much_evidence_a_score_rests_on(ctx, monkeypatch):
    con, uid = ctx
    fake(monkeypatch)
    r = workflow.search_watchlist(con, uid, keywords=["go", "python", "terraform"], save=False)
    by_title = {x["title"]: x for x in r["results"]}
    assert by_title["Backend Engineer"]["terms_considered"] == 3  # go, docker, kubernetes
    assert by_title["Platform Engineer"]["terms_considered"] == 2  # python, terraform
    assert "terms_considered" in r["note"]


def test_search_filters_and_save_false_and_partial_failure(ctx, monkeypatch):
    con, uid = ctx
    fake(monkeypatch, broken=("lever",))
    r = workflow.search_watchlist(con, uid, remote_only=True, save=False)
    assert [x["title"] for x in r["results"]] == ["Backend Engineer"] and r["saved_new_jobs"] == 0
    assert r["companies_checked"] == 1 and r["company_errors"] == [{"company": "Palantir", "error": "lever down"}]
    assert db.list_items(con, uid, "jobs") == []  # save=False really saves nothing
    high = workflow.search_watchlist(con, uid, min_score=90, save=False)
    assert high["results"] == []
    fake(monkeypatch)
    only_good = workflow.search_watchlist(con, uid, min_score=100, save=False)
    assert all(x["score"] == 100 for x in only_good["results"])


def test_search_without_boards_explains_what_to_do():
    con = db.connect(":memory:")
    uid = db.ensure_default_user(con)
    with pytest.raises(ValueError, match="ats_provider"):
        workflow.search_watchlist(con, uid)


def test_prepare_apply_followup_flow(ctx, monkeypatch):
    con, uid = ctx
    fake(monkeypatch)
    jid = workflow.search_watchlist(con, uid)["results"][0]["job_id"]

    prep = workflow.prepare_application(con, uid, jid)
    assert prep["application"]["status"] == "applying" and prep["resume_version_id"]
    assert prep["gaps"] == ["kubernetes"] and "Kubernetes" not in prep["resume_markdown"]
    assert prep["steps"][0].endswith("https://gh/1") and any("kubernetes" in s for s in prep["steps"])
    assert db.get_item(con, uid, "resume_versions", prep["resume_version_id"])["label"] == prep["resume_label"]
    assert prep["application"]["resume_version_id"] == prep["resume_version_id"]
    assert workflow.prepare_application(con, uid, jid, label=None)["resume_label"].endswith("-2")  # unique labels

    applied = workflow.mark_applied(con, uid, jid, follow_up_days=3, notes="via site")
    today = con.execute("SELECT date('now')").fetchone()[0]
    assert applied["status"] == "applied" and applied["applied_date"] == today
    assert applied["follow_up_date"] == con.execute("SELECT date('now', '+3 days')").fetchone()[0]
    assert applied["resume_version_id"] == prep["resume_version_id"] + 1  # keeps the version of the latest prepare
    with pytest.raises(ValueError, match="already applied"):
        workflow.prepare_application(con, uid, jid)
    with pytest.raises(ValueError):
        workflow.mark_applied(con, uid, jid, follow_up_days=-1)

    con.execute("UPDATE applications SET follow_up_date = date('now', '-1 day') WHERE job_id = ?", (jid,))
    assert [a["job_id"] for a in db.stale_applications(con, uid)] == [jid]  # due follow-up surfaces in the review
    assert db.weekly_review(con, uid)["needs_follow_up"][0]["job_id"] == jid


def test_prepare_without_apply_link_says_so(ctx):
    con, uid = ctx
    jid = db.add_item(con, uid, "jobs", title="Go Dev", company="X", description="Go")["id"]
    assert "No apply link" in workflow.prepare_application(con, uid, jid)["steps"][0]


def test_interview_brief_is_grounded_and_creates_prep_once(ctx, monkeypatch):
    con, uid = ctx
    fake(monkeypatch)
    jid = workflow.search_watchlist(con, uid)["results"][0]["job_id"]
    workflow.prepare_application(con, uid, jid)
    workflow.mark_applied(con, uid, jid)
    db.track_application(con, uid, jid, status="interview")

    b = workflow.interview_brief(con, uid, jid)
    assert "Go, Docker and Kubernetes" in b["job_description"]  # the full stored JD is returned
    assert b["application"]["status"] == "interview" and b["resume_used"]["id"]
    assert b["your_evidence"] == ["Go", "Docker"] and b["gaps_to_prepare"] == ["kubernetes"]
    assert b["projects_to_talk_about"][0]["name"] == "codive"
    assert b["company_notes"]["remote_policy"] == "fully remote"
    assert "untrusted" in b["instructions"] and b["prep_tasks_created"] == []

    first = workflow.interview_brief(con, uid, jid, create_prep_tasks=True)
    assert len(first["prep_tasks_created"]) == 1 and first["prep_tasks"][0]["topic"] == "Revise kubernetes for GitLab interview"
    second = workflow.interview_brief(con, uid, jid, create_prep_tasks=True)
    assert second["prep_tasks_created"] == [] and len(db.list_items(con, uid, "prep")) == 1  # idempotent


def test_other_users_cannot_use_your_jobs(ctx):
    con, uid = ctx
    other, _ = db.create_user(con, "other")
    jid = db.add_item(con, uid, "jobs", title="Mine", description="Go")["id"]
    for call in (workflow.prepare_application, workflow.mark_applied, workflow.interview_brief):
        with pytest.raises(ValueError):
            call(con, other, jid)
    v = db.add_item(con, uid, "resume_versions", label="v", content="c")
    j2 = db.add_item(con, other, "jobs", title="Theirs")["id"]
    with pytest.raises(ValueError):  # cannot attach someone else's resume version
        db.track_application(con, other, j2, resume_version_id=v["id"])
