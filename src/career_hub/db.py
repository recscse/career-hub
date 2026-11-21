"""Data layer: all SQL lives here so the database can be swapped later.

Every row belongs to a ``user_id`` so the hub can serve more than one person.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(os.environ.get("CAREER_HUB_DB", "data/career.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    token_hash  TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS profile (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id),
    name        TEXT, headline TEXT, summary TEXT,
    location    TEXT, links TEXT, preferences TEXT
);
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL, level TEXT, years REAL, evidence TEXT,
    visibility TEXT NOT NULL DEFAULT 'private',
    UNIQUE(user_id, name)
);
CREATE TABLE IF NOT EXISTS experience (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL, company TEXT, start_date TEXT, end_date TEXT,
    summary TEXT, achievements TEXT,
    visibility TEXT NOT NULL DEFAULT 'private'
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL, description TEXT, stack TEXT, url TEXT, outcome TEXT,
    visibility TEXT NOT NULL DEFAULT 'private'
);
CREATE TABLE IF NOT EXISTS contributions (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
    repo TEXT NOT NULL, title TEXT, url TEXT, status TEXT,
    visibility TEXT NOT NULL DEFAULT 'private',
    UNIQUE(user_id, url)
);
"""

CREATE_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_experience ON experience
    (user_id, role, COALESCE(company, ''), COALESCE(start_date, ''));
CREATE UNIQUE INDEX IF NOT EXISTS uq_projects ON projects (user_id, name);
"""

# Whitelist of editable columns per table. Table and column names never come
# from user input directly, so they are safe to interpolate into SQL.
COLUMNS: dict[str, tuple[str, ...]] = {
    "skills": ("name", "level", "years", "evidence", "visibility"),
    "experience": ("role", "company", "start_date", "end_date", "summary", "achievements", "visibility"),
    "projects": ("name", "description", "stack", "url", "outcome", "visibility"),
    "contributions": ("repo", "title", "url", "status", "visibility"),
}
PROFILE_COLUMNS = ("name", "headline", "summary", "location", "links", "preferences")
VISIBILITY = ("private", "public")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(path or DEFAULT_DB)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    con.executescript(CREATE_INDEXES)
    return con


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(con: sqlite3.Connection, name: str) -> tuple[int, str]:
    """Create a user and return ``(user_id, token)``. Only the token's hash is stored."""
    token = secrets.token_urlsafe(32)
    cur = con.execute("INSERT INTO users(name, token_hash) VALUES (?, ?)", (name, _hash(token)))
    con.commit()
    return int(cur.lastrowid), token


def user_for_token(con: sqlite3.Connection, token: str) -> int | None:
    row = con.execute("SELECT id FROM users WHERE token_hash = ?", (_hash(token),)).fetchone()
    return int(row["id"]) if row else None


def ensure_default_user(con: sqlite3.Connection, name: str = "me") -> int:
    """Single-user mode (local stdio): use the first user, creating it if needed."""
    row = con.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if row:
        return int(row["id"])
    cur = con.execute("INSERT INTO users(name) VALUES (?)", (name,))
    con.commit()
    return int(cur.lastrowid)


def _check(table: str, fields: dict) -> dict:
    allowed = COLUMNS[table]
    unknown = [k for k in fields if k not in allowed]
    if unknown:
        raise ValueError(f"unknown fields for {table}: {unknown}. Allowed: {list(allowed)}")
    if "visibility" in fields and fields["visibility"] not in VISIBILITY:
        raise ValueError(f"visibility must be one of {VISIBILITY}")
    return {k: v for k, v in fields.items()}


def set_profile(con: sqlite3.Connection, user_id: int, **fields: str) -> dict:
    unknown = [k for k in fields if k not in PROFILE_COLUMNS]
    if unknown:
        raise ValueError(f"unknown profile fields: {unknown}. Allowed: {list(PROFILE_COLUMNS)}")
    con.execute("INSERT OR IGNORE INTO profile(user_id) VALUES (?)", (user_id,))
    for k, v in fields.items():
        con.execute(f"UPDATE profile SET {k} = ? WHERE user_id = ?", (v, user_id))
    con.commit()
    return get_profile(con, user_id)


def get_profile(con: sqlite3.Connection, user_id: int) -> dict:
    row = con.execute("SELECT * FROM profile WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else {}


def add_item(con: sqlite3.Connection, user_id: int, table: str, **fields) -> dict:
    fields = _check(table, fields)
    cols = ["user_id", *fields]
    marks = ", ".join("?" for _ in cols)
    try:
        cur = con.execute(
            f"INSERT INTO {table}({', '.join(cols)}) VALUES ({marks})", (user_id, *fields.values())
        )
    except sqlite3.IntegrityError as e:
        raise ValueError(f"could not add to {table}: {e}") from e
    con.commit()
    return get_item(con, user_id, table, int(cur.lastrowid))


def get_item(con: sqlite3.Connection, user_id: int, table: str, item_id: int) -> dict:
    row = con.execute(f"SELECT * FROM {table} WHERE id = ? AND user_id = ?", (item_id, user_id)).fetchone()
    if not row:
        raise ValueError(f"{table} item {item_id} not found")
    return dict(row)


def list_items(con: sqlite3.Connection, user_id: int, table: str, visibility: str | None = None) -> list[dict]:
    if table not in COLUMNS:
        raise ValueError(f"unknown table {table!r}. Choose from {list(COLUMNS)}")
    sql, args = f"SELECT * FROM {table} WHERE user_id = ?", [user_id]
    if visibility:
        sql += " AND visibility = ?"
        args.append(visibility)
    return [dict(r) for r in con.execute(sql + " ORDER BY id", args)]


def update_item(con: sqlite3.Connection, user_id: int, table: str, item_id: int, **fields) -> dict:
    fields = _check(table, fields)
    if not fields:
        raise ValueError("nothing to update")
    get_item(con, user_id, table, item_id)  # ownership + existence check
    sets = ", ".join(f"{k} = ?" for k in fields)
    con.execute(f"UPDATE {table} SET {sets} WHERE id = ? AND user_id = ?", (*fields.values(), item_id, user_id))
    con.commit()
    return get_item(con, user_id, table, item_id)


def delete_item(con: sqlite3.Connection, user_id: int, table: str, item_id: int) -> None:
    get_item(con, user_id, table, item_id)
    con.execute(f"DELETE FROM {table} WHERE id = ? AND user_id = ?", (item_id, user_id))
    con.commit()


def summary(con: sqlite3.Connection, user_id: int) -> str:
    """Markdown summary of the whole developer context, meant to be given to an AI."""
    p = get_profile(con, user_id)
    out = [f"# {p.get('name') or 'Developer'}"]
    if p.get("headline"):
        out.append(f"**{p['headline']}**")
    for key in ("location", "summary", "preferences", "links"):
        if p.get(key):
            out.append(f"\n{key.capitalize()}: {p[key]}")
    skills = list_items(con, user_id, "skills")
    if skills:
        out.append("\n## Skills")
        for s in skills:
            extra = ", ".join(x for x in (s["level"], f"{s['years']:g}y" if s["years"] else None) if x)
            out.append(f"- {s['name']}" + (f" ({extra})" if extra else "") + (f": {s['evidence']}" if s["evidence"] else ""))
    exp = list_items(con, user_id, "experience")
    if exp:
        out.append("\n## Experience")
        for e in exp:
            out.append(f"- {e['role']} @ {e['company'] or '?'} ({e['start_date'] or '?'} - {e['end_date'] or 'present'})")
            for k in ("summary", "achievements"):
                if e[k]:
                    out.append(f"  - {e[k]}")
    projects = list_items(con, user_id, "projects")
    if projects:
        out.append("\n## Projects")
        for pr in projects:
            out.append(f"- {pr['name']}: {pr['description'] or ''} [{pr['stack'] or ''}] {pr['url'] or ''}".rstrip())
            if pr["outcome"]:
                out.append(f"  - Outcome: {pr['outcome']}")
    contribs = list_items(con, user_id, "contributions")
    if contribs:
        out.append("\n## Open-source contributions")
        for c in contribs:
            out.append(f"- {c['repo']}: {c['title'] or ''} ({c['status'] or '?'}) {c['url'] or ''}".rstrip())
    return "\n".join(out)
