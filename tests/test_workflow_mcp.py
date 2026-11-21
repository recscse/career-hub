"""The whole job-search workflow driven the way an AI client would: over MCP, as a separate process."""

import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from career_hub import server


def _text(result):
    return "".join(c.text for c in result.content if getattr(c, "text", None))


def _jl(result):
    assert not result.is_error, f"tool call failed: {_text(result)}"
    return json.loads(_text(result))


@pytest.mark.asyncio
async def test_job_added_from_any_website_through_interview(tmp_path):
    """A job found anywhere (e.g. pasted from LinkedIn by the user's browsing agent) goes through the same flow."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "career_hub.server"], env={"CAREER_HUB_DB": str(tmp_path / "w.db")}
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for name in ("Python", "Docker"):
            await s.call_tool("add_skill", {"name": name, "years": 4})
        await s.call_tool("add_project", {"name": "billing-api", "stack": "Python, PostgreSQL", "description": "REST service"})
        await s.call_tool("add_company", {"name": "Acme", "remote_policy": "remote-first", "priority": 4})

        job = _jl(await s.call_tool("add_job", {
            "title": "Backend Engineer", "company": "Acme", "url": "https://www.linkedin.com/jobs/view/123",
            "source": "linkedin (added by user)", "description": "Python, Docker and Kubernetes on AWS."}))

        prep = _jl(await s.call_tool("prepare_application", {"job_id": job["id"]}))
        assert prep["application"]["status"] == "applying" and prep["steps"][0].endswith("/123")
        assert set(prep["gaps"]) == {"kubernetes", "aws"}

        applied = _jl(await s.call_tool("mark_applied", {"job_id": job["id"], "follow_up_days": 5}))
        assert applied["status"] == "applied" and applied["follow_up_date"]

        again = await s.call_tool("prepare_application", {"job_id": job["id"]})
        assert again.is_error and "already applied" in _text(again)  # the AI sees why, not a generic failure

        await s.call_tool("track_application", {"job_id": job["id"], "status": "interview"})
        brief = _jl(await s.call_tool("interview_brief", {"job_id": job["id"], "create_prep_tasks": True}))
        assert "Kubernetes on AWS" in brief["job_description"] and len(brief["prep_tasks_created"]) == 2
        assert brief["resume_used"]["id"] == prep["resume_version_id"]
        assert brief["company_notes"]["remote_policy"] == "remote-first"

        review = _jl(await s.call_tool("weekly_review", {}))
        assert review["pipeline"]["by_status"]["interview"] == 1 and review["prep_counts"]["todo"] == 2
        versions = json.loads("[" + ",".join(c.text for c in (await s.call_tool("list_resume_versions", {})).content) + "]")
        assert len(versions) == 1

        no_boards = await s.call_tool("search_watchlist", {})
        assert no_boards.is_error and "ats_provider" in _text(no_boards)  # actionable guidance reaches the AI


@pytest.mark.asyncio
async def test_every_tool_is_registered_described_and_stable():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    expected = {
        "get_summary", "set_profile", "add_skill", "add_experience", "add_project", "log_contribution",
        "list_items", "update_item", "delete_item", "import_resume", "import_resume_text", "export_resume",
        "tailor_resume", "add_job", "compare_job_to_profile", "track_application", "list_applications",
        "stale_applications", "pipeline_stats", "add_company", "add_prep_task", "set_prep_status", "prep_plan",
        "save_resume_version", "list_resume_versions", "get_resume_version", "diff_resume_versions",
        "weekly_review", "search_jobs", "search_watchlist", "sync_github_contributions", "list_github_repos",
        "import_github_repos", "set_repo_summary", "suggest_skills_from_repos", "portfolio_data",
        "build_portfolio", "prepare_application", "mark_applied", "interview_brief",
    }
    assert set(tools) == expected, f"added: {set(tools) - expected}; removed: {expected - set(tools)}"
    for name, t in tools.items():
        assert t.description and len(t.description) > 30, f"{name} needs a real description"
        assert t.input_schema.get("type") == "object", name
