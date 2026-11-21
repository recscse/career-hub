# Changelog

## 0.1.0 (unreleased)
- Local-first MCP server: profile, skills, experience, projects, contributions.
- Resume import (PDF/DOCX/TXT/MD) and Markdown export; resume versions with diff.
- Jobs, keyword job-to-profile matching, application tracking, prep tracker, company watchlist, weekly review.
- Job search via Greenhouse, Lever, Ashby and the Hacker News "Who is hiring" thread; GitHub PR sync.
- Hosted mode: HTTP MCP with per-user bearer tokens, rate limits, admin CLI (users, tokens, export, delete, backup).
- Versioned schema migrations (schema v2); Dockerfile.
- GitHub profile sync: opt-in repo import (languages by code bytes, README excerpt, your commit count) with linked projects, user-owned summaries that survive re-sync, and skill suggestions from your code.
- `tailor_resume`: job-specific resume that reorders skills and selects the most relevant projects (with a why-report); never adds unproven skills.
