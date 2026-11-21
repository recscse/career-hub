# Career Context Hub

Your developer context (profile, skills, experience, projects, open-source work) in one
SQLite database, served to AI agents over MCP. Every row has a `user_id` and a
`visibility` (`private` by default) so it can grow to more users later.

## Run
    uv sync
    uv run career-hub            # stdio MCP server; DB at ./data/career.db (override: CAREER_HUB_DB)
    uv run pytest

## Connect Claude Code
    claude mcp add career-hub -- uv --directory <path-to-this-folder> run career-hub

## MCP surface
Resources: `career://summary` (give this to an AI as context), `career://profile`,
`career://skills`, `career://experience`, `career://projects`, `career://contributions`.
Tools: `get_summary`, `set_profile`, `add_skill`, `add_experience`, `add_project`,
`log_contribution`, `list_items`, `update_item`, `delete_item`,
`import_resume(path)` (PDF/DOCX/TXT/MD -> text + instructions; the agent saves the data),
`export_resume(focus_skills, public_only)` (Markdown resume),
`add_job`, `compare_job_to_profile` (keyword skill match: matched/missing/score), `track_application`,
`list_applications`, `stale_applications`, `pipeline_stats`.

Set `CAREER_HUB_IMPORT_DIR` to restrict which folder `import_resume` may read (recommended on a server).

## Roadmap
Next: prep tracker, company watchlist, resume versions, job-board connectors, HTTP transport + token auth, Docker.
