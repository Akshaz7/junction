"""Per-IP in-memory rate limit per rolling 60 s window."""
import os
import re
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int | None = None, window: float = 60.0,
                 burst_limit: int | None = None, burst_window: float = 1.0):
        super().__init__(app)
        if limit is None:
            try:
                limit = int(os.environ.get("RATE_LIMIT_PER_MIN") or "600")
            except ValueError:
                limit = 600
            if limit < 1:
                limit = 600
        if burst_limit is None:
            try:
                burst_limit = max(1, int(os.environ.get("RATE_LIMIT_BURST") or "30"))
            except ValueError:
                burst_limit = 30
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque] = defaultdict(deque)
        self.burst_limit = burst_limit
        self.burst_window = burst_window

    def _ip(self, request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @staticmethod
    def _exempt(request) -> bool:
        """Health, viewer assets and ingestion polling do not consume the quota.

        BaseHTTPMiddleware also passes WebSocket upgrades through without dispatch.
        """
        if request.method != "GET":
            return False
        path = request.url.path
        return path == "/api/health" or re.fullmatch(
            r"/api/docs/[^/]+/(?:files/[^/]+|pages/[^/]+/image|scene|ingest)", path
        ) is not None

    async def dispatch(self, request, call_next):
        if self._exempt(request):
            return await call_next(request)
        now = time.monotonic()
        q = self.hits[self._ip(request)]
        while q and now - q[0] >= self.window:
            q.popleft()
        retry = 0.0
        if len(q) >= self.limit:
            retry = q[0] + self.window - now
        elif len(q) >= self.burst_limit and now - q[-self.burst_limit] < self.burst_window:
            retry = q[-self.burst_limit] + self.burst_window - now
        if retry > 0:
            import math
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": str(max(1, math.ceil(retry)))})
        q.append(now)
        return await call_next(request)
