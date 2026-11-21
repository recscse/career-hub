"""Opt-in checks against the REAL services (RUN_LIVE=1). They catch upstream format changes.

Run:  RUN_LIVE=1 uv run pytest tests/test_live.py -q
CI runs them weekly. They send no personal data: only public board names and a public GitHub user.
"""

import os
import re

import pytest

from career_hub import connectors

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to hit real services")

REQUIRED = {"title", "company", "url", "location", "remote", "description", "source"}


def check_jobs(jobs, source):
    assert jobs, f"{source} returned no jobs"
    assert all(REQUIRED <= set(j) for j in jobs)
    assert all(j["title"] and (j["url"] or "").startswith("http") for j in jobs), f"{source}: missing title or url"
    # real HTML tags must be gone (a bare "<" such as "<2 calls" is legitimate text)
    assert not any(re.search(r"</?[A-Za-z][^>]*>", j["description"]) for j in jobs), f"{source}: HTML leaked"


def test_greenhouse():
    check_jobs(connectors.fetch_greenhouse("gitlab"), "greenhouse")


def test_lever():
    check_jobs(connectors.fetch_lever("palantir"), "lever")


def test_ashby():
    check_jobs(connectors.fetch_ashby("ramp"), "ashby")


def test_hacker_news_hiring_thread():
    jobs = connectors.fetch_hn_hiring()
    assert len(jobs) > 20 and all(j["url"].startswith("https://news.ycombinator.com/item?id=") for j in jobs)


def test_github_public_profile():
    repos = connectors.fetch_user_repos("octocat", include_forks=True)
    assert repos and {"name", "full_name", "url", "pushed_at"} <= set(repos[0])
    langs = connectors.fetch_repo_languages(repos[0]["full_name"])
    assert isinstance(langs, dict)
