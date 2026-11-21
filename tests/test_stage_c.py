import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from career_hub import db, resume


@pytest.fixture
def ctx():
    con = db.connect(":memory:")
    return con, db.ensure_default_user(con)


def test_company_priority_validation_and_uniqueness(ctx):
    con, uid = ctx
    c = db.add_item(con, uid, "companies", name="Grafana", remote_policy="fully remote", priority=5)
    assert c["priority"] == 5
    for bad in (0, 6):
        with pytest.raises(ValueError):
            db.add_item(con, uid, "companies", name=f"X{bad}", priority=bad)
    with pytest.raises(ValueError):
        db.add_item(con, uid, "companies", name="Grafana")


def test_prep_status_validation_and_plan_order(ctx):
    con, uid = ctx
    a = db.add_item(con, uid, "prep", topic="System design", due_date="2026-12-10")
    b = db.add_item(con, uid, "prep", topic="SQL", due_date="2026-12-01")
    db.add_item(con, uid, "prep", topic="Undated")
    c = db.add_item(con, uid, "prep", topic="Done thing")
    db.update_item(con, uid, "prep", c["id"], status="done")
    with pytest.raises(ValueError):
        db.update_item(con, uid, "prep", a["id"], status="finished")
    plan = db.prep_plan(con, uid)
    assert [p["topic"] for p in plan["open"]] == ["SQL", "System design", "Undated"]
    assert plan["counts"] == {"todo": 3, "doing": 0, "done": 1}
    assert b["status"] == "todo"


def test_resume_versions_and_diff(ctx):
    con, uid = ctx
    db.set_profile(con, uid, name="Ada", headline="Backend dev")
    db.add_item(con, uid, "skills", name="Python", years=5)
    v1 = db.add_item(con, uid, "resume_versions", label="base", content=resume.export_markdown(con, uid))
    db.add_item(con, uid, "skills", name="Go", years=1)
    v2 = db.add_item(con, uid, "resume_versions", label="golang-role", target_role="Go dev",
                     content=resume.export_markdown(con, uid, focus_skills=["Go"]))
    d = db.diff_versions(con, uid, v1["id"], v2["id"])
    assert "-Python" in d and "+Go, Python" in d
    assert db.diff_versions(con, uid, v1["id"], v1["id"]) == "(no differences)"
    listing = db.list_resume_versions(con, uid)
    assert [v["label"] for v in listing] == ["base", "golang-role"] and "content" not in listing[0]
    with pytest.raises(ValueError):
        db.add_item(con, uid, "resume_versions", label="base", content="x")  # labels are unique


def test_versions_isolated_between_users(ctx):
    con, uid = ctx
    other, _ = db.create_user(con, "other")
    v = db.add_item(con, uid, "resume_versions", label="mine", content="secret")
    with pytest.raises(ValueError):
        db.diff_versions(con, other, v["id"], v["id"])
    assert db.list_resume_versions(con, other) == []


def test_weekly_review(ctx):
    con, uid = ctx
    j = db.add_item(con, uid, "jobs", title="Dev")["id"]
    db.track_application(con, uid, j, status="applied", follow_up_date="2000-01-01")
    db.add_item(con, uid, "prep", topic="Overdue", due_date="2000-01-01")
    db.add_item(con, uid, "prep", topic="Future", due_date="2999-01-01")
    db.add_item(con, uid, "contributions", repo="a/b", url="u1", status="merged")
    db.add_item(con, uid, "companies", name="Low", priority=1)
    db.add_item(con, uid, "companies", name="High", priority=5)
    db.add_item(con, uid, "companies", name="Unranked")
    r = db.weekly_review(con, uid)
    assert r["pipeline"]["by_status"]["applied"] == 1
    assert [x["job_id"] for x in r["needs_follow_up"]] == [j]
    assert [p["topic"] for p in r["prep_due_or_overdue"]] == ["Overdue"]
    assert r["contributions_by_status"] == {"merged": 1}
    assert [c["name"] for c in r["top_target_companies"]] == ["High", "Low"]


def _text(result):
    return "".join(c.text for c in result.content if getattr(c, "text", None))


@pytest.mark.asyncio
async def test_stage_c_tools_over_mcp(tmp_path):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "career_hub.server"], env={"CAREER_HUB_DB": str(tmp_path / "c.db")}
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        await s.call_tool("set_profile", {"name": "Ada"})
        await s.call_tool("add_skill", {"name": "Python"})
        await s.call_tool("add_company", {"name": "PostHog", "priority": 5, "remote_policy": "remote-first"})
        t = json.loads(_text(await s.call_tool("add_prep_task", {"topic": "SQL", "due_date": "2026-12-01"})))
        done = json.loads(_text(await s.call_tool("set_prep_status", {"task_id": t["id"], "status": "done"})))
        assert done["status"] == "done"

        v = json.loads(_text(await s.call_tool("save_resume_version", {"label": "base"})))  # snapshot of stored data
        assert v["chars"] > 0 and "content" not in v
        await s.call_tool("add_skill", {"name": "Go"})
        v2 = json.loads(_text(await s.call_tool("save_resume_version", {"label": "v2"})))
        diff = _text(await s.call_tool("diff_resume_versions", {"a_id": v["id"], "b_id": v2["id"]}))
        assert "Go" in diff

        review = json.loads(_text(await s.call_tool("weekly_review", {})))
        assert review["top_target_companies"][0]["name"] == "PostHog"
        bad = await s.call_tool("set_prep_status", {"task_id": t["id"], "status": "nope"})
        assert bad.is_error
