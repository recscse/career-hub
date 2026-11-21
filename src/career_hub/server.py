"""MCP server: exposes the career context to AI agents (stdio by default)."""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from . import db, matching, resume

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


@mcp.tool()
def import_resume(path: str) -> str:
    """Read a resume file (.pdf, .docx, .txt, .md) and return its text with instructions.

    Follow the returned instructions to save the data with the add_* tools. The server does not
    parse the resume itself; you do the mapping, and the user should confirm what is saved.
    """
    try:
        return resume.import_payload(path)
    except resume.ResumeError as e:
        raise ValueError(str(e)) from e


@mcp.tool()
def export_resume(focus_skills: list[str] | None = None, public_only: bool = False) -> str:
    """Build a Markdown resume from stored data. focus_skills are listed first (tailor to a role).

    public_only=True includes only rows marked visibility='public'.
    """
    con, uid = _ctx()
    return resume.export_markdown(con, uid, focus_skills=focus_skills, public_only=public_only)


@mcp.tool()
def add_job(
    title: str,
    company: str | None = None,
    url: str | None = None,
    location: str | None = None,
    remote: str | None = None,
    description: str | None = None,
    required_skills: str | None = None,
    source: str | None = None,
) -> dict:
    """Save a job posting. Paste the full description for better matching. required_skills is a
    comma-separated list that extends skills detected from the description."""
    con, uid = _ctx()
    return db.add_item(
        con, uid, "jobs", title=title, company=company, url=url, location=location, remote=remote,
        description=description, required_skills=required_skills, source=source,
    )


@mcp.tool()
def compare_job_to_profile(job_id: int | None = None, description: str | None = None) -> dict:
    """Score a saved job (job_id) or pasted text (description) against the stored skills.

    Returns matched skills, missing skills and a 0-100 keyword score. It is a rough estimate of
    named technologies only; add your own judgement about seniority and fit.
    """
    con, uid = _ctx()
    return matching.compare(con, uid, job_id=job_id, description=description)


@mcp.tool()
def track_application(
    job_id: int,
    status: str | None = None,
    applied_date: str | None = None,
    follow_up_date: str | None = None,
    notes: str | None = None,
) -> dict:
    """Create or update the application for a saved job. status: saved, applying, applied,
    interview, offer, rejected, ghosted or withdrawn. Dates are YYYY-MM-DD."""
    con, uid = _ctx()
    return db.track_application(
        con, uid, job_id, status=status, applied_date=applied_date, follow_up_date=follow_up_date, notes=notes
    )


@mcp.tool()
def list_applications(status: str | None = None) -> list[dict]:
    """List applications with their job, newest update first. Optionally filter by status."""
    con, uid = _ctx()
    return db.list_applications(con, uid, status=status)


@mcp.tool()
def stale_applications(days: int = 7) -> list[dict]:
    """Applied/interview applications with no update for `days` days, or whose follow-up date has come."""
    con, uid = _ctx()
    return db.stale_applications(con, uid, days)


@mcp.tool()
def pipeline_stats() -> dict:
    """Counts of applications per status and the interview rate."""
    con, uid = _ctx()
    return db.funnel(con, uid)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
