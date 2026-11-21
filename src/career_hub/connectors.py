"""Read-only job-board connectors (public JSON APIs) and GitHub PR sync.

Safety: only fixed hosts are contacted, board/user names are validated before being placed in a
URL, responses are size-capped, and posting text is treated as untrusted data.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from urllib.parse import urlparse

ALLOWED_HOSTS = {
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.ashbyhq.com",
    "hn.algolia.com",
    "api.github.com",
}
MAX_BYTES = 8 * 1024 * 1024
MAX_DESC = 6000
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
GH_USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
PROVIDERS = ("greenhouse", "lever", "ashby", "hn")


class ConnectorError(ValueError):
    pass


def _get_json(url: str):
    host = urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ConnectorError(f"host not allowed: {host}")
    headers = {"User-Agent": "career-hub/0.1", "Accept": "application/json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and host == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            raw = r.read(MAX_BYTES + 1)
    except Exception as e:  # network/HTTP errors become a clear message
        raise ConnectorError(f"request failed for {host}: {e}") from e
    if len(raw) > MAX_BYTES:
        raise ConnectorError("response too large")
    return json.loads(raw)


def clean_html(s: str | None) -> str:
    if not s:
        return ""
    t = html.unescape(s)  # Greenhouse returns entity-escaped HTML
    t = re.sub(r"<(?:br|/p|/li|/div|/h\d|/tr)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def _job(title, company, url, location, remote, description, source) -> dict:
    return {
        "title": (title or "").strip()[:300],
        "company": company,
        "url": url,
        "location": location,
        "remote": remote,
        "description": clean_html(description)[:MAX_DESC],
        "source": source,
    }


def _check_name(name: str | None, what: str) -> str:
    if not name or not NAME_RE.match(name):
        raise ConnectorError(f"invalid {what}; use letters, digits, '.', '_' or '-' (max 80 chars)")
    return name


def fetch_greenhouse(board: str) -> list[dict]:
    b = _check_name(board, "board")
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        remote = "remote" if loc and "remote" in loc.lower() else None
        out.append(_job(j.get("title"), j.get("company_name") or b, j.get("absolute_url"), loc, remote, j.get("content"), "greenhouse"))
    return out


def fetch_lever(board: str) -> list[dict]:
    b = _check_name(board, "board")
    data = _get_json(f"https://api.lever.co/v0/postings/{b}?mode=json")
    out = []
    for j in data:
        wt = (j.get("workplaceType") or "").lower()
        remote = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}.get(wt)
        loc = (j.get("categories") or {}).get("location")
        out.append(_job(j.get("text"), b, j.get("hostedUrl"), loc, remote, j.get("descriptionPlain") or j.get("description"), "lever"))
    return out


def fetch_ashby(board: str) -> list[dict]:
    b = _check_name(board, "board")
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{b}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        wt = (j.get("workplaceType") or "").lower()
        remote = "remote" if j.get("isRemote") or wt == "remote" else {"hybrid": "hybrid", "onsite": "onsite"}.get(wt)
        out.append(_job(j.get("title"), b, j.get("jobUrl"), j.get("location"), remote,
                        j.get("descriptionPlain") or j.get("descriptionHtml"), "ashby"))
    return out


def fetch_hn_hiring(max_comments: int = 400) -> list[dict]:
    """Top-level comments of the latest 'Ask HN: Who is hiring?' thread."""
    hits = _get_json(
        "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=hiring&hitsPerPage=5"
    ).get("hits", [])
    thread = next((h for h in hits if (h.get("title") or "").startswith("Ask HN: Who is hiring")), None)
    if not thread:
        raise ConnectorError("could not find a 'Who is hiring' thread")
    item = _get_json(f"https://hn.algolia.com/api/v1/items/{int(thread['objectID'])}")
    out = []
    for c in (item.get("children") or [])[:max_comments]:
        text = clean_html(c.get("text"))
        if not text:
            continue
        first = text.splitlines()[0]
        company = first.split("|")[0].strip()[:80] or None
        low = text.lower()
        remote = "remote" if "remote" in low else None
        out.append(_job(first[:200], company, f"https://news.ycombinator.com/item?id={c.get('id')}", None, remote, text, "hn"))
    return out


def fetch_jobs(provider: str, board: str | None = None) -> list[dict]:
    if provider == "greenhouse":
        return fetch_greenhouse(board)
    if provider == "lever":
        return fetch_lever(board)
    if provider == "ashby":
        return fetch_ashby(board)
    if provider == "hn":
        return fetch_hn_hiring()
    raise ConnectorError(f"provider must be one of {PROVIDERS}")


def filter_jobs(jobs: list[dict], keywords: list[str] | None = None, remote_only: bool = False) -> list[dict]:
    kws = [k.lower() for k in (keywords or []) if k.strip()]
    out = []
    for j in jobs:
        if remote_only and j["remote"] != "remote":
            continue
        hay = f"{j['title']} {j['description']}".lower()
        if kws and not any(k in hay for k in kws):
            continue
        out.append(j)
    return out


def fetch_github_prs(username: str) -> list[dict]:
    """Public pull requests authored by ``username`` on repositories they do not own."""
    if not GH_USER_RE.match(username or ""):
        raise ConnectorError("invalid GitHub username")
    data = _get_json(f"https://api.github.com/search/issues?q=author:{username}+type:pr&sort=updated&per_page=50")
    out = []
    for i in data.get("items", []):
        repo = i["repository_url"].split("/repos/", 1)[1]
        if repo.split("/")[0].lower() == username.lower():
            continue
        merged = (i.get("pull_request") or {}).get("merged_at")
        status = "merged" if merged else ("open" if i["state"] == "open" else "closed")
        out.append({"repo": repo, "title": i["title"], "url": i["html_url"], "status": status})
    return out
