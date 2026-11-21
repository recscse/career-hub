"""Start the real server over stdio and talk to it with an MCP client."""
import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _text(result):
    return "".join(c.text for c in result.content if getattr(c, "text", None))


@pytest.mark.asyncio
async def test_agent_flow(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "career_hub.server"],
        env={"CAREER_HUB_DB": str(tmp_path / "c.db")},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = {t.name for t in (await s.list_tools()).tools}
        assert {"get_summary", "add_skill", "update_item", "log_contribution"} <= tools

        await s.call_tool("set_profile", {"name": "Ada", "headline": "Backend dev"})
        await s.call_tool("add_skill", {"name": "Python", "level": "advanced", "years": 5})
        c = await s.call_tool("log_contribution", {"repo": "aden-hive/hive", "url": "https://x/7533", "status": "claimed"})
        cid = json.loads(_text(c))["id"]
        await s.call_tool("update_item", {"table": "contributions", "item_id": cid, "fields": {"status": "merged"}})

        res = await s.read_resource("career://summary")
        text = res.contents[0].text
        assert "Ada" in text and "Python" in text and "merged" in text

        bad = await s.call_tool("update_item", {"table": "skills", "item_id": 1, "fields": {"bogus": 1}})
        assert bad.is_error


@pytest.mark.asyncio
async def test_import_and_export_tools(tmp_path):
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Ada\nPython, 5 years", encoding="utf-8")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "career_hub.server"],
        env={"CAREER_HUB_DB": str(tmp_path / "c.db")},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        res = await s.call_tool("import_resume", {"path": str(resume_file)})
        assert "Python, 5 years" in _text(res) and "add_skill" in _text(res)
        bad = await s.call_tool("import_resume", {"path": str(tmp_path / "nope.txt")})
        assert bad.is_error

        await s.call_tool("add_skill", {"name": "Python", "years": 5})
        md = _text(await s.call_tool("export_resume", {"focus_skills": ["Python"]}))
        assert "## Skills" in md and "Python" in md


@pytest.mark.asyncio
async def test_job_search_flow(tmp_path):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "career_hub.server"], env={"CAREER_HUB_DB": str(tmp_path / "c.db")}
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        await s.call_tool("add_skill", {"name": "Python", "years": 5})
        job = json.loads(_text(await s.call_tool("add_job", {
            "title": "Backend Engineer", "company": "Acme", "url": "https://acme/1",
            "description": "Python and Kubernetes required"})))
        cmp = json.loads(_text(await s.call_tool("compare_job_to_profile", {"job_id": job["id"]})))
        assert cmp["score"] == 50 and cmp["missing"] == ["kubernetes"]
        await s.call_tool("track_application", {"job_id": job["id"], "status": "applied", "applied_date": "2026-11-18"})
        assert "Backend Engineer" in _text(await s.call_tool("list_applications", {"status": "applied"}))
        stats = json.loads(_text(await s.call_tool("pipeline_stats", {})))
        assert stats["by_status"]["applied"] == 1
        bad = await s.call_tool("track_application", {"job_id": job["id"], "status": "nope"})
        assert bad.is_error


@pytest.mark.asyncio
async def test_validation_messages_reach_the_ai_client(tmp_path):
    """The SDK hides plain exceptions; our ValueErrors must surface as readable tool errors."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "career_hub.server"], env={"CAREER_HUB_DB": str(tmp_path / "c.db")}
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        bad = await s.call_tool("update_item", {"table": "skills", "item_id": 1, "fields": {"bogus": 1}})
        assert bad.is_error and "unknown fields" in _text(bad) and "Allowed" in _text(bad)
        job = json.loads(_text(await s.call_tool("add_job", {"title": "Dev"})))
        bad = await s.call_tool("track_application", {"job_id": job["id"], "status": "nope"})
        assert bad.is_error and "status must be one of" in _text(bad)
