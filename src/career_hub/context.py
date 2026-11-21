"""Per-request user and per-thread database connection (shared by server and HTTP layer)."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextvars import ContextVar

from . import db

# Set by the HTTP auth middleware for the duration of one request (hosted mode).
current_user: ContextVar[int | None] = ContextVar("current_user", default=None)

_tls = threading.local()


def hosted() -> bool:
    return os.environ.get("CAREER_HUB_MODE", "local").lower() == "hosted"


def thread_connection() -> sqlite3.Connection:
    """One SQLite connection per thread (sqlite3 connections must not cross threads)."""
    path = str(db.DEFAULT_DB)
    if getattr(_tls, "path", None) != path:
        _tls.con = db.connect(path)
        _tls.path = path
    return _tls.con
