"""Hosted mode: streamable-HTTP MCP behind per-user bearer-token auth.

Every request must carry ``Authorization: Bearer <token>``. The token maps to exactly one user,
and the server runs stateless (no cross-request sessions), so a request can only ever act as the
user whose token it presented.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque

from mcp.server.transport_security import TransportSecuritySettings

from . import db
from .context import current_user, thread_connection


class RateLimiter:
    """Sliding-window limiter, in memory (per process)."""

    def __init__(self, max_events: int, window: float = 60.0):
        self.max, self.window = max_events, window
        self.events: dict = defaultdict(deque)

    def allow(self, key) -> bool:
        now = time.monotonic()
        q = self.events[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max:
            return False
        q.append(now)
        return True


async def _respond(send, status: int, body: dict, headers: list | None = None) -> None:
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), *(headers or [])]})
    await send({"type": "http.response.body", "body": payload})


class TokenAuthMiddleware:
    def __init__(self, app, *, per_user_per_min: int = 120, failures_per_ip_per_min: int = 20):
        self.app = app
        self.user_limit = RateLimiter(per_user_per_min)
        self.fail_limit = RateLimiter(failures_per_ip_per_min)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # lifespan etc.
            return await self.app(scope, receive, send)
        if scope["path"] == "/healthz":
            return await _respond(send, 200, {"status": "ok"})

        ip = (scope.get("client") or ("?", 0))[0]
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        uid = db.user_for_token(thread_connection(), token) if token else None
        if uid is None:
            if not self.fail_limit.allow(ip):
                return await _respond(send, 429, {"error": "too many failed attempts"}, [(b"retry-after", b"60")])
            return await _respond(send, 401, {"error": "missing or invalid token"},
                                  [(b"www-authenticate", b'Bearer realm="career-hub"')])
        if not self.user_limit.allow(uid):
            return await _respond(send, 429, {"error": "rate limit exceeded"}, [(b"retry-after", b"60")])

        reset = current_user.set(uid)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user.reset(reset)


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def build_app(mcp, host: str = "127.0.0.1"):
    """ASGI app: auth middleware around the stateless streamable-HTTP MCP endpoint at /mcp."""
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1", "localhost", "127.0.0.1:*", "localhost:*", *_csv("CAREER_HUB_ALLOWED_HOSTS")],
        allowed_origins=_csv("CAREER_HUB_ALLOWED_ORIGINS"),
    )
    inner = mcp.streamable_http_app(
        stateless_http=True, json_response=True, transport_security=security, host=host
    )
    return TokenAuthMiddleware(inner)
