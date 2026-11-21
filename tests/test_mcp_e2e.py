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
