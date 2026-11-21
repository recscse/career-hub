"""Transparent keyword matching of a job against the stored profile.

This is a rough estimate, not a judgement: it finds named technologies, it cannot assess
seniority or context. The calling AI agent is expected to add the nuance.
"""

from __future__ import annotations

import re
import sqlite3

from . import db

# Common technologies/terms used to detect requirements in a job description.
VOCAB = (
    "python java javascript typescript go rust c++ c# ruby php kotlin swift scala sql nosql bash "
    "react vue angular svelte next.js node.js express django flask fastapi spring rails laravel .net "
    "postgresql mysql sqlite mongodb redis elasticsearch kafka rabbitmq graphql grpc rest "
    "docker kubernetes terraform ansible aws gcp azure linux git ci/cd jenkins github-actions "
    "prometheus grafana opentelemetry microservices serverless "
    "machine-learning deep-learning pytorch tensorflow scikit-learn pandas numpy spark airflow dbt "
    "llm rag langchain mcp prompt-engineering "
    "html css tailwind webpack vite jest pytest cypress playwright"
).split()

ALIASES = {
    "js": "javascript", "ts": "typescript", "k8s": "kubernetes", "postgres": "postgresql",
    "node": "node.js", "nodejs": "node.js", "nextjs": "next.js", "golang": "go", "reactjs": "react",
    "vuejs": "vue", "tf": "terraform", "ml": "machine-learning", "scikit": "scikit-learn",
    "sklearn": "scikit-learn", "github actions": "github-actions", "cicd": "ci/cd",
    "dockerfile": "docker",  # GitHub reports Docker usage as the "Dockerfile" language
}
# Aliases that appear in text under another spelling.
TEXT_FORMS = {
    "machine-learning": ("machine learning",), "deep-learning": ("deep learning",),
    "prompt-engineering": ("prompt engineering",), "github-actions": ("github actions",),
    "scikit-learn": ("scikit-learn", "sklearn"), "node.js": ("node.js", "nodejs"),
    "next.js": ("next.js", "nextjs"), "go": ("golang",), "kubernetes": ("kubernetes", "k8s"),
    "postgresql": ("postgresql", "postgres"), "javascript": ("javascript",), "typescript": ("typescript",),
}


def norm(name: str) -> str:
    n = name.strip().lower()
    return ALIASES.get(n, n)


def _present(term: str, text_lower: str, text_raw: str) -> bool:
    if term == "go":  # ambiguous English word: only match the capitalised language name or "golang"
        return bool(re.search(r"(?<![\w])Go(?![\w])", text_raw)) or "golang" in text_lower
    forms = TEXT_FORMS.get(term, (term,))
    for f in forms:
        pat = r"(?<![A-Za-z0-9+#.])" + re.escape(f).replace(r"\-", r"[- ]") + r"(?![A-Za-z0-9+#])"
        if re.search(pat, text_lower):
            return True
    return False


def detect_terms(text: str, extra: list[str] | None = None) -> list[str]:
    low = text.lower()
    seen: list[str] = []
    for t in [*VOCAB, *(norm(x) for x in (extra or []))]:
        if t not in seen and _present(t, low, text):
            seen.append(t)
    return seen


def compare(con: sqlite3.Connection, user_id: int, *, job_id: int | None = None, description: str | None = None) -> dict:
    if (job_id is None) == (description is None):
        raise ValueError("pass exactly one of job_id or description")
    title = None
    declared: list[str] = []
    if job_id is not None:
        job = db.get_item(con, user_id, "jobs", job_id)
        title = job["title"]
        text = f"{job['title']}\n{job['description'] or ''}"
        declared = [norm(x) for x in (job["required_skills"] or "").split(",") if x.strip()]
    else:
        text = description or ""

    mine = {norm(s["name"]): s for s in db.list_items(con, user_id, "skills")}
    wanted = list(dict.fromkeys([*declared, *detect_terms(text, extra=list(mine))]))
    matched = [t for t in wanted if t in mine]
    missing = [t for t in wanted if t not in mine]
    score = round(100 * len(matched) / len(wanted)) if wanted else None
    return {
        "job": title,
        "score": score,
        "terms_considered": len(wanted),
        "matched": [{"skill": t, "level": mine[t]["level"], "years": mine[t]["years"]} for t in matched],
        "missing": missing,
        "note": (
            "Keyword-based estimate of named technologies only. It does not judge seniority, domain, "
            "or soft requirements; review the description yourself."
            if wanted
            else "No known technologies detected in the text; paste a fuller description or set required_skills."
        ),
    }
