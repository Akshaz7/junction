"""Per-IP in-memory rate limit: 30 requests per rolling 60 s window."""
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 30, window: float = 60.0):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque] = defaultdict(deque)

    def _ip(self, request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @staticmethod
    def _exempt(request) -> bool:
        """Ingestion status polling (a small local file read) must not eat the quota while an upload is processed."""
        return request.method == "GET" and request.url.path.startswith("/api/docs/") and request.url.path.endswith("/ingest")

    async def dispatch(self, request, call_next):
        if self._exempt(request):
            return await call_next(request)
        now = time.monotonic()
        q = self.hits[self._ip(request)]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": str(int(self.window))})
        q.append(now)
        return await call_next(request)
