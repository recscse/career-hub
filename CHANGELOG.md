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
- Job-search workflow: `search_watchlist` (new jobs across target companies' boards), `prepare_application`, `mark_applied`, `interview_brief`; schema v3 (company job boards, resume used per application).
- Data now lives in `~/.career-hub/career.db` by default (was relative to the launch folder).
- **Security fix:** the generic item tools (`get`/`update`/`delete`/`add`/`list`) now validate the table name against an allow-list. Before, a crafted table name could let one hosted-mode user read or delete another user's rows. Local single-user mode was not affected and no hosted deployment is known to have existed.
- Tests: full workflow over MCP, tool registry/description check, regression tests for the above, and opt-in live tests against real job boards (run weekly in CI).
- `build_portfolio` / `portfolio_data`: static portfolio (HTML, JSON, resume.md) generated only from public items; escaped output, no scripts or external requests; never overwrites files it did not create.
