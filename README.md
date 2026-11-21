# Career Context Hub

Keep your developer career context (resume, skills, experience, projects, open-source work, job
search) in **one place on your own machine**, and let any MCP-capable AI tool read and update it.

**The problem it solves:** you paste your resume into every AI chat, get inconsistent answers, and
your job search lives in scattered tabs. Here, one local database is the source of truth. Ask your
AI "tailor my resume to this posting", "what skills am I missing for this job?" or "what should I
follow up on this week?" and it works from the same facts every time.

Local-first: data lives in a SQLite file you own. Nothing is uploaded; the server only fetches the
public job boards or GitHub data you ask for.

## Install (local mode)
Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

    # Claude Code
    claude mcp add career-hub -- uvx career-context-hub

    # Any other MCP client: run this command over stdio
    uvx career-context-hub

Your data is stored in one file, `~/.career-hub/career.db` (created automatically), no matter which
folder you start your editor in. Set `CAREER_HUB_DB=/path/to/career.db` only if you want it elsewhere.
That is the only setting; everything else works out of the box.

## First steps (ask your AI)
1. "Import my resume from `~/resume.pdf`" - it reads the file, proposes what to save, and saves it
   once you confirm.
2. "Show my career summary" - the context any AI can reuse.
3. "List my GitHub repos, then import `codive` and `my-api`", then "suggest skills from my repos" - so matching uses what you have actually built.
4. "Search Greenhouse board `gitlab` for remote Python jobs and rank them against my skills."
5. "Tailor my resume to job 3 and save it as `acme-backend`" - skills and projects are reordered for the job; anything you lack is listed as a gap, never added.
6. "Mark codive public, then build my portfolio into `~/site`" - a static page and a `data.json` you can host anywhere (e.g. GitHub Pages) or feed to an existing site.
7. "Track an application for job 3 as applied today" / "what needs a follow-up?" / "weekly review".

## What it can do
| Area | Tools |
|---|---|
| Context | `get_summary`, `set_profile`, `add_skill`, `add_experience`, `add_project`, `log_contribution`, `list_items`, `update_item`, `delete_item` + `career://` resources |
| Resume | `import_resume` (PDF/DOCX/TXT/MD), `export_resume`, `tailor_resume` (per-job: matching skills first, most relevant projects, gaps report), `save_resume_version`, `diff_resume_versions` |
| Jobs | `add_job`, `search_jobs` (Greenhouse, Lever, Ashby, HN "Who is hiring"), `compare_job_to_profile` |
| Workflow | `search_watchlist` (all your target companies, new jobs only), `prepare_application`, `mark_applied`, `interview_brief` |
| Tracking | `track_application`, `list_applications`, `stale_applications`, `pipeline_stats`, `weekly_review` |
| Prep | `add_company` (watchlist), `add_prep_task`, `set_prep_status`, `prep_plan` |
| Portfolio | `build_portfolio` (static `index.html` + `data.json` + `resume.md` from items marked **public**), `portfolio_data` |
| GitHub | `list_github_repos` (dry run), `import_github_repos` (only the repos you pick: languages, README, your commits), `set_repo_summary`, `suggest_skills_from_repos`, `sync_github_contributions` (your public PRs to other repos) |

## The job-search workflow
```
find  ->  shortlist  ->  prepare  ->  apply (you)  ->  follow up  ->  interview
```
1. **Find.** Add target companies with their job board (`add_company ... ats_provider=greenhouse ats_board=gitlab`),
   then run `search_watchlist` whenever you like (your AI client can schedule it). It ranks by *your* stored
   skills and saves only jobs it has not seen before, so each run shows what is new.
   For any other site (LinkedIn, company pages, newsletters) your AI client reads the posting and calls `add_job`;
   it enters the same pipeline. The hub does not scrape sites that forbid it.
2. **Prepare.** `prepare_application` saves a resume tailored to the job (never adding skills you lack),
   lists the gaps, and gives you the apply link.
3. **Apply.** You submit on the employer's site. The hub does not apply for you. Then `mark_applied` records
   the date and sets a follow-up date.
4. **Follow up.** `stale_applications` / `weekly_review` show what needs a nudge.
5. **Interview.** When you are shortlisted, `interview_brief` returns the full stored job description, your
   evidence, the projects to talk about and your gaps (optionally as prep tasks). Your AI writes likely
   questions from the description and answers only from your stored facts.

## Privacy model
Everything you add is **private by default**. The portfolio contains only items you mark `public`. Profile `name`, `headline`, `summary`, `location` and `links` are published when you build one (leave blank what you do not want shown); `preferences` and skill `evidence` are never published. `build_portfolio` refuses to overwrite files it did not generate.

## Honest limitations
- Job matching is a **keyword** check for named technologies. It cannot judge seniority, domain or
  soft requirements; treat the score as a starting point.
- Resume parsing is done by *your* AI client following the server's instructions, so quality depends
  on that client. Scanned (image-only) PDFs are not supported.
- Job-board connectors use public APIs; their availability and terms can change.

## Hosted mode (optional, for you or a small group)
`CAREER_HUB_MODE=hosted career-hub` serves MCP over HTTP at `/mcp` with per-user bearer tokens, rate
limits and DNS-rebinding protection. Manage users with `career-hub-admin` (create-user, rotate-token,
export, delete-user, backup). See [DEPLOY.md](DEPLOY.md). `import_resume` (reads server files) is
disabled there; use `import_resume_text`.

## Development
    uv sync && uv run pytest

Schema changes need a migration; see [RELEASING.md](RELEASING.md). License: MIT.
