import pytest

from career_hub import db, matching


@pytest.fixture
def ctx():
    con = db.connect(":memory:")
    uid = db.ensure_default_user(con)
    for name in ("Python", "Docker", "PostgreSQL", "Go"):
        db.add_item(con, uid, "skills", name=name, level="advanced", years=3)
    return con, uid


def test_compare_detects_matched_and_missing(ctx):
    con, uid = ctx
    r = matching.compare(
        con, uid,
        description="We need Python, Postgres and Kubernetes. Nice to have: React, Docker. Next.js a plus.",
    )
    assert {m["skill"] for m in r["matched"]} == {"python", "postgresql", "docker"}
    assert {"kubernetes", "react", "next.js"} <= set(r["missing"])
    assert r["score"] == 50


def test_compare_go_only_matches_language_not_word(ctx):
    con, uid = ctx
    r = matching.compare(con, uid, description="Ready to go the extra mile with Python")
    assert [m["skill"] for m in r["matched"]] == ["python"]
    r = matching.compare(con, uid, description="Backend in Go and Python")
    assert {m["skill"] for m in r["matched"]} == {"go", "python"}


def test_compare_uses_declared_skills_and_job_id(ctx):
    con, uid = ctx
    job = db.add_item(con, uid, "jobs", title="Dev", description="Build things", required_skills="Python, Terraform")
    r = matching.compare(con, uid, job_id=job["id"])
    assert [m["skill"] for m in r["matched"]] == ["python"] and r["missing"] == ["terraform"]
    assert r["score"] == 50


def test_compare_no_terms_and_arg_validation(ctx):
    con, uid = ctx
    assert matching.compare(con, uid, description="Be nice")["score"] is None
    with pytest.raises(ValueError):
        matching.compare(con, uid)
    with pytest.raises(ValueError):
        matching.compare(con, uid, job_id=1, description="x")


def test_symbol_terms(ctx):
    con, uid = ctx
    r = matching.compare(con, uid, description="C++, C# and .NET experience")
    assert {"c++", "c#", ".net"} <= set(r["missing"])


def test_application_lifecycle(ctx):
    con, uid = ctx
    job = db.add_item(con, uid, "jobs", title="Backend", company="Acme", url="https://acme/1")
    assert db.track_application(con, uid, job["id"])["status"] == "saved"
    a = db.track_application(con, uid, job["id"], status="applied", applied_date="2026-11-01", notes="via site")
    assert a["status"] == "applied" and a["notes"] == "via site"
    assert len(db.list_applications(con, uid)) == 1  # one application per job
    assert db.list_applications(con, uid, status="saved") == []
    with pytest.raises(ValueError):
        db.track_application(con, uid, job["id"], status="bogus")
    with pytest.raises(ValueError):
        db.track_application(con, uid, 999, status="applied")
    with pytest.raises(ValueError):  # duplicate job url
        db.add_item(con, uid, "jobs", title="Backend", url="https://acme/1")


def test_stale_and_funnel(ctx):
    con, uid = ctx
    j1 = db.add_item(con, uid, "jobs", title="A")["id"]
    j2 = db.add_item(con, uid, "jobs", title="B")["id"]
    j3 = db.add_item(con, uid, "jobs", title="C")["id"]
    db.track_application(con, uid, j1, status="applied")
    db.track_application(con, uid, j2, status="interview")
    db.track_application(con, uid, j3, status="applied", follow_up_date="2000-01-01")
    con.execute("UPDATE applications SET updated_at = datetime('now', '-10 days') WHERE job_id = ?", (j1,))
    stale = {s["job_id"] for s in db.stale_applications(con, uid, days=7)}
    assert stale == {j1, j3}  # j1 by age, j3 by follow-up date; j2 is fresh
    f = db.funnel(con, uid)
    assert f["total"] == 3 and f["by_status"]["interview"] == 1 and f["interview_rate_pct"] == 33


def test_application_isolation(ctx):
    con, uid = ctx
    other, _ = db.create_user(con, "other")
    job = db.add_item(con, uid, "jobs", title="Mine")
    with pytest.raises(ValueError):
        db.track_application(con, other, job["id"], status="applied")
    assert db.list_applications(con, other) == []
