"""Opt-in GitHub profile sync: list candidates (dry run), import the ones you choose, derive skills."""

from __future__ import annotations

import json
import sqlite3

from . import connectors, db

MIN_LANG_PERCENT = 5.0


def language_percentages(langs: dict[str, int]) -> dict[str, float]:
    total = sum(langs.values())
    if not total:
        return {}
    return {k: round(100 * v / total, 1) for k, v in sorted(langs.items(), key=lambda kv: -kv[1])}


def stack_from(langs: dict[str, int], limit: int = 4) -> str:
    pct = language_percentages(langs)
    return ", ".join([k for k, v in pct.items() if v >= MIN_LANG_PERCENT][:limit])


def candidates(
    con: sqlite3.Connection,
    user_id: int,
    username: str,
    include_forks: bool = False,
    include_archived: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Dry run: what could be imported. Saves nothing."""
    have = {r["full_name"] for r in db.list_items(con, user_id, "repos")}
    repos = connectors.fetch_user_repos(username, include_forks, include_archived)
    return [
        {
            "full_name": r["full_name"],
            "description": r["description"],
            "language": r["language"],
            "stars": r["stars"],
            "pushed_at": (r["pushed_at"] or "")[:10],
            "is_fork": bool(r["is_fork"]),
            "url": r["url"],
            "already_imported": r["full_name"] in have,
        }
        for r in repos[: max(1, min(int(limit), 300))]
    ]


def import_repos(con: sqlite3.Connection, user_id: int, username: str, names: list[str], public: bool = False) -> dict:
    """Fetch details for the chosen repos and store them, plus a linked project for each."""
    if not names:
        raise ValueError("pass the repository names to import (use list_github_repos first)")
    listing = {
        r["name"].lower(): r for r in connectors.fetch_user_repos(username, include_forks=True, include_archived=True)
    }
    imported, problems = [], []
    for raw in names:
        short = raw.split("/")[-1].lower()
        meta = listing.get(short)
        if meta is None or ("/" in raw and raw.split("/")[0].lower() != meta["owner"].lower()):
            problems.append({"repo": raw, "problem": f"not found among {username}'s public repositories"})
            continue
        warnings: list[str] = []
        try:
            langs = connectors.fetch_repo_languages(meta["full_name"])
        except connectors.ConnectorError as e:
            langs = {}
            warnings.append(f"languages unavailable: {e}")
        readme = connectors.fetch_repo_readme(meta["full_name"])
        commits = connectors.fetch_my_commit_count(meta["full_name"], username)
        repo = db.upsert_repo(
            con,
            user_id,
            meta["full_name"],
            visibility="public" if public else "private",
            description=meta["description"],
            language=meta["language"],
            languages=json.dumps(language_percentages(langs)),
            topics=meta["topics"],
            stars=meta["stars"],
            homepage=meta["homepage"],
            url=meta["url"],
            is_fork=meta["is_fork"],
            pushed_at=meta["pushed_at"],
            readme_excerpt=readme,
            my_commits=commits,
        )
        facts = [f"{meta['stars']} stars"] if meta["stars"] else []
        if commits:
            facts.append(f"{commits} commits by you (lower bound)")
        project = db.sync_repo_project(
            con, user_id, repo["id"], name=meta["name"], stack=stack_from(langs), outcome="; ".join(facts) or None
        )
        imported.append(
            {
                "repo": meta["full_name"],
                "repo_id": repo["id"],
                "project_id": project["id"],
                "languages_pct_by_bytes": language_percentages(langs),
                "my_commits": commits,
                "has_readme": readme is not None,
                "visibility": repo["visibility"],
                "warnings": warnings,
            }
        )
    return {"imported": imported, "problems": problems}


def suggest_skills(con: sqlite3.Connection, user_id: int, apply: bool = False, include_forks: bool = False) -> dict:
    """Skills evidenced by imported repos' languages; optionally add the missing ones.

    Uses the share of code bytes across imported repos. It shows what you have written, not how well.
    """
    totals: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    for r in db.list_items(con, user_id, "repos"):
        if r["is_fork"] and not include_forks:
            continue
        for lang, pct in json.loads(r["languages"] or "{}").items():
            if pct >= MIN_LANG_PERCENT:
                totals[lang] = totals.get(lang, 0) + pct
                evidence.setdefault(lang, []).append(f"{r['full_name']} ({pct:g}%)")
    have = {s["name"].lower() for s in db.list_items(con, user_id, "skills")}
    out, added = [], []
    for lang, _ in sorted(totals.items(), key=lambda kv: -kv[1]):
        row = {
            "skill": lang,
            "evidence": "Code in " + ", ".join(evidence[lang][:5]),
            "already_in_profile": lang.lower() in have,
        }
        out.append(row)
        if apply and lang.lower() not in have:
            db.add_item(con, user_id, "skills", name=lang, evidence=row["evidence"])
            added.append(lang)
    return {"suggestions": out, "added": added}
