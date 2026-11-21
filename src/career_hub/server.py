"""MCP server: exposes the career context to AI agents (stdio by default)."""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from . import db

mcp = MCPServer(
    "career-hub",
    instructions=(
        "Personal developer career context. Read career://summary to learn about the developer. "
        "Use the add_/update_/delete_ tools to keep it current. New rows are private by default."
    ),
)

_state: dict = {}


def _ctx():
    """Open the database lazily; single-user mode uses the first user."""
    if "con" not in _state:
        con = db.connect()
        _state["con"] = con
        _state["user"] = db.ensure_default_user(con)
    return _state["con"], _state["user"]


# ---- resources (read-only context for the AI) --------------------------------


@mcp.resource("career://summary")
def summary_resource() -> str:
    con, uid = _ctx()
    return db.summary(con, uid)


@mcp.resource("career://profile")
def profile_resource() -> str:
    con, uid = _ctx()
    return json.dumps(db.get_profile(con, uid), indent=2)


def _list_json(table: str) -> str:
    con, uid = _ctx()
    return json.dumps(db.list_items(con, uid, table), indent=2)


@mcp.resource("career://skills")
def skills_resource() -> str:
    return _list_json("skills")


@mcp.resource("career://experience")
def experience_resource() -> str:
    return _list_json("experience")


@mcp.resource("career://projects")
def projects_resource() -> str:
    return _list_json("projects")


@mcp.resource("career://contributions")
def contributions_resource() -> str:
    return _list_json("contributions")


# ---- tools (actions) ----------------------------------------------------------


@mcp.tool()
def get_summary() -> str:
    """Markdown summary of the developer's whole career context (use as AI context)."""
    return summary_resource()


@mcp.tool()
def set_profile(
    name: str | None = None,
    headline: str | None = None,
    summary: str | None = None,
    location: str | None = None,
    links: str | None = None,
    preferences: str | None = None,
) -> dict:
    """Create or update the profile. Only the fields you pass are changed."""
    con, uid = _ctx()
    fields = {k: v for k, v in locals().items() if k not in ("con", "uid") and v is not None}
    return db.set_profile(con, uid, **fields)


@mcp.tool()
def add_skill(name: str, level: str | None = None, years: float | None = None, evidence: str | None = None) -> dict:
    """Add a skill. level e.g. beginner/intermediate/advanced; evidence = where you used it."""
    con, uid = _ctx()
    return db.add_item(con, uid, "skills", name=name, level=level, years=years, evidence=evidence)


@mcp.tool()
def add_experience(
    role: str,
    company: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    summary: str | None = None,
    achievements: str | None = None,
) -> dict:
    """Add a work experience entry. Prefer measurable achievements."""
    con, uid = _ctx()
    return db.add_item(
        con, uid, "experience", role=role, company=company, start_date=start_date,
        end_date=end_date, summary=summary, achievements=achievements,
    )


@mcp.tool()
def add_project(
    name: str,
    description: str | None = None,
    stack: str | None = None,
    url: str | None = None,
    outcome: str | None = None,
) -> dict:
    """Add a project."""
    con, uid = _ctx()
    return db.add_item(con, uid, "projects", name=name, description=description, stack=stack, url=url, outcome=outcome)


@mcp.tool()
def log_contribution(repo: str, title: str | None = None, url: str | None = None, status: str | None = None) -> dict:
    """Record an open-source issue/PR. status e.g. claimed/open/merged. url must be unique."""
    con, uid = _ctx()
    return db.add_item(con, uid, "contributions", repo=repo, title=title, url=url, status=status)


@mcp.tool()
def list_items(table: str) -> list[dict]:
    """List rows. table is one of: skills, experience, projects, contributions."""
    con, uid = _ctx()
    return db.list_items(con, uid, table)


@mcp.tool()
def update_item(table: str, item_id: int, fields: dict) -> dict:
    """Update fields of one row, e.g. table='contributions', item_id=1, fields={'status': 'merged'}."""
    con, uid = _ctx()
    return db.update_item(con, uid, table, item_id, **fields)


@mcp.tool()
def delete_item(table: str, item_id: int) -> str:
    """Delete one row."""
    con, uid = _ctx()
    db.delete_item(con, uid, table, item_id)
    return f"deleted {table} {item_id}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
