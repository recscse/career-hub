"""Daily job digest: check the watchlist, save new postings, write the best new ones to a Markdown file.

    uv run python scripts/daily_digest.py            # writes ~/.career-hub/digest.md
Env: DIGEST_KEYWORDS (comma list), DIGEST_LOCATIONS (comma list of words that make a location acceptable).
"""
from __future__ import annotations

import datetime
import os
import pathlib
import re

from career_hub import server as s

KEYWORDS = [k.strip() for k in os.environ.get("DIGEST_KEYWORDS", "backend,software engineer,python,golang,java").split(",") if k.strip()]
OK_LOC = [k.strip().lower() for k in os.environ.get("DIGEST_LOCATIONS", "india,global,worldwide,anywhere,apac,asia").split(",") if k.strip()]
OUT = pathlib.Path.home() / ".career-hub" / "digest.md"


def location_ok(loc: str) -> bool:
    low = (loc or "").lower()
    return any(re.search(rf"\b{re.escape(w)}\b", low) for w in OK_LOC)


def main() -> None:
    r = s.search_watchlist(keywords=KEYWORDS, remote_only=True, new_only=True, save=True, limit=100)
    rows = [x for x in r["results"] if location_ok(x["location"])][:10]
    lines = [f"# Job digest {datetime.date.today()}", "",
             f"{len(r['results'])} new remote matches on the watchlist, {len(rows)} open to India/global. "
             f"Errors: {r.get('company_errors') or 'none'}.", ""]
    for x in rows:
        lines.append(f"- **{x['fit']}** [{x['title']}]({x['url']}) - {x['company']} ({x['location']}); "
                     f"matches: {', '.join(x['matched']) or 'none'}; missing: {', '.join(x['missing'][:4]) or 'none'}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(rows)} jobs)")


if __name__ == "__main__":
    main()
