import json

import pytest

from career_hub import db, resume, server


@pytest.fixture
def ctx():
    con = db.connect(":memory:")
    uid = db.ensure_default_user(con)
    db.set_profile(con, uid, name="Ada", headline="Backend dev")
    for name, years in (("Python", 6), ("Go", 2), ("Docker", 3), ("PostgreSQL", 4), ("Cobol", 9)):
        db.add_item(con, uid, "skills", name=name, years=years)
    db.add_item(con, uid, "projects", name="codive", description="Code intelligence tool", stack="Go, Dockerfile",
                outcome="3 stars; 41 commits by you (lower bound)")
    db.add_item(con, uid, "projects", name="billing-api", description="REST service on PostgreSQL", stack="Python, PostgreSQL")
    db.add_item(con, uid, "projects", name="color-flipper", description="Toy page", stack="HTML, CSS")
    db.add_item(con, uid, "experience", role="Dev", company="Acme", start_date="2022-01")
    return con, uid


JOB = "Backend engineer. You will write Go services, ship with Docker, and use Kubernetes and Terraform."


def test_tailor_orders_skills_and_projects_by_relevance(ctx):
    con, uid = ctx
    r = resume.tailor(con, uid, description=JOB, max_projects=2)
    md = r["markdown"]
    assert r["emphasised_skills"] == ["Go", "Docker"]
    skills_line = next(line for line in md.splitlines() if "Go," in line and "Cobol" in line)
    assert skills_line.index("Go") < skills_line.index("Python")  # matched skills first
    assert [p["name"] for p in r["projects_shown"]] == ["codive", "billing-api"]
    assert r["projects_shown"][0]["why"] == ["docker", "go"]
    assert r["projects_left_out"] == ["color-flipper"]
    assert "color-flipper" not in md and "codive" in md and "41 commits" in md


def test_tailor_never_adds_unproven_skills_and_reports_gaps(ctx):
    con, uid = ctx
    r = resume.tailor(con, uid, description=JOB)
    assert set(r["gaps"]) == {"kubernetes", "terraform"}
    assert "Kubernetes" not in r["markdown"] and "Terraform" not in r["markdown"]
    assert "nothing was added" in r["note"]
    assert r["match_score"] == 50


def test_tailor_by_job_id_and_max_projects_zero(ctx):
    con, uid = ctx
    job = db.add_item(con, uid, "jobs", title="Go Engineer", description="Go and PostgreSQL")
    r = resume.tailor(con, uid, job_id=job["id"], max_projects=0)
    assert r["job"] == "Go Engineer" and r["projects_shown"] == []
    assert "## Projects" not in r["markdown"]
    assert set(r["projects_left_out"]) == {"codive", "billing-api", "color-flipper"}


def test_public_only_excludes_private_items(ctx):
    con, uid = ctx
    db.update_item(con, uid, "projects", 1, visibility="public")
    db.update_item(con, uid, "skills", 2, visibility="public")  # Go
    r = resume.tailor(con, uid, description=JOB, public_only=True)
    assert [p["name"] for p in r["projects_shown"]] == ["codive"]
    assert r["emphasised_skills"] == ["Go"] and "Python" not in r["markdown"]


def test_project_ids_filter_is_backward_compatible(ctx):
    con, uid = ctx
    full = resume.export_markdown(con, uid)
    assert "codive" in full and "billing-api" in full and "color-flipper" in full  # unchanged default
    only = resume.export_markdown(con, uid, project_ids=[3, 1, 999])
    assert only.index("color-flipper") < only.index("codive") and "billing-api" not in only


def test_tool_saves_version_and_rejects_bad_input(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "t.db")
    server._state.clear()
    con, uid = server._ctx()
    db.add_item(con, uid, "skills", name="Go")
    db.add_item(con, uid, "projects", name="codive", stack="Go")
    out = server.tailor_resume(description="We use Go", save_as="go-role")
    assert out["saved_version_id"] and "codive" in db.get_item(con, uid, "resume_versions", out["saved_version_id"])["content"]
    with pytest.raises(ValueError):  # duplicate label
        server.tailor_resume(description="We use Go", save_as="go-role")
    with pytest.raises(ValueError):  # neither job nor text
        server.tailor_resume()
    server._state.clear()
    assert json.dumps(out)  # result is JSON-serialisable for MCP
