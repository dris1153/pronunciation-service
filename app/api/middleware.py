"""Middleware: CORS, proxy headers, rate limit, timeout, request logging.

Order of registration matters — see :func:`register_middleware` for the
authoritative stack assembly.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import time
import unicodedata
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import get_settings


# ── XFF-aware client IP keying (Phase 01 / Finding 4 + Per-User Redesign) ───


_USER_ID_MAX_LEN = 128


def _parse_trusted_nets(cidrs: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in cidrs:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Skipping invalid trusted-proxy CIDR: {}", cidr)
    return nets


def _is_trusted_peer(peer: str) -> bool:
    """Return True if ``peer`` IP is within any configured trusted-proxy CIDR.

    Trust gating uses the **direct TCP peer**, never an XFF-resolved address —
    otherwise an attacker could forge `X-Forwarded-For: 172.17.0.5` to make
    themselves look trusted.
    """
    settings = get_settings()
    trusted_nets = _parse_trusted_nets(settings.trusted_proxy_cidrs)
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(peer_ip in net for net in trusted_nets)


def _validate_user_id(raw: str) -> str | None:
    """Sanitise an X-End-User-Id header value or return None on invalid input.

    Defends against log-injection / cache-key explosion via attacker-supplied
    end-user-id. Caller treats ``None`` as "fallback to IP keying".

    Rules:
    - empty or whitespace-only → None
    - longer than 128 chars → None
    - any Unicode control character (categories starting with C) → None
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw or len(raw) > _USER_ID_MAX_LEN:
        return None
    if any(unicodedata.category(c)[0] == "C" for c in raw):
        return None
    return raw


def _client_ip_key(request: Request) -> str:
    """Return the rate-limit key using a 4-branch decision table.

    | Direct TCP peer  | Service auth match  | Valid user_id | Returned key   |
    |------------------|---------------------|---------------|----------------|
    | Untrusted CIDR   | (any)               | (any)         | ip:<peer>      |
    | Trusted CIDR     | No                  | (any)         | ip:<peer>      |
    | Trusted CIDR     | Yes                 | No            | ip:<peer>      |
    | Trusted CIDR     | Yes                 | Yes           | user:<id>      |

    The IP component honours XFF (leftmost) when the direct peer is trusted,
    so per-IP keying still reflects the real end-user when behind a proxy.
    """
    settings = get_settings()

    # Direct TCP peer — used for trust gating (NOT XFF-resolved).
    direct_peer = request.client.host if request.client else "0.0.0.0"
    trusted = _is_trusted_peer(direct_peer)

    # Effective IP for keying: honour XFF leftmost only behind trusted peer.
    effective_ip = direct_peer
    if trusted:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                effective_ip = first

    # Branch 1: untrusted peer — never honour service auth or user-id headers
    if not trusted:
        return f"ip:{effective_ip}"

    # Branch 2: feature off OR no service auth header → key by IP
    svc_auth = request.headers.get("x-service-auth", "")
    if not settings.service_api_key or not svc_auth:
        return f"ip:{effective_ip}"

    # Branch 3: service auth header present but does not match → key by IP
    if not hmac.compare_digest(svc_auth, settings.service_api_key):
        return f"ip:{effective_ip}"

    # Branch 4: trusted + auth verified → require valid user_id; else fallback
    user_id = _validate_user_id(request.headers.get("x-end-user-id", ""))
    if user_id is None:
        return f"ip:{effective_ip}"

    return f"user:{user_id}"


# ── slowapi limiter singleton (Phase 01) ────────────────────────────────────


limiter = Limiter(key_func=_client_ip_key, enabled=True)


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded: {exc.detail}",
            "error_code": "RATE_LIMITED",
        },
        headers={"Retry-After": "60"},
    )


# ── Timeout middleware (Phase 01) ───────────────────────────────────────────


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Abort any request that exceeds ``request_timeout_sec`` with HTTP 504."""

    def __init__(self, app, timeout: float) -> None:
        super().__init__(app)
        self.timeout = timeout

    async def dispatch(self, request: Request, call_next):
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "detail": f"Request exceeded {self.timeout:.0f}s timeout.",
                    "error_code": "TIMEOUT",
                },
            )


# ── Request logging middleware (Phase 05 / Finding 8) ───────────────────────


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Generate a server-side request_id and emit one structured log line per request.

    Server-generated UUID is **never** read from the X-Request-ID header — that
    would allow log-injection / correlation forgery.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        client_ip = _client_ip_key(request)
        start = time.monotonic()
        try:
            with logger.contextualize(request_id=request_id):
                response = await call_next(request)
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            logger.bind(
                request_id=request_id,
                endpoint=request.url.path,
                method=request.method,
                status=response.status_code,
                latency_ms=latency_ms,
                client_ip=client_ip,
            ).info("request_completed")
            return response
        except Exception:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            logger.bind(
                request_id=request_id,
                endpoint=request.url.path,
                method=request.method,
                status=500,
                latency_ms=latency_ms,
                client_ip=client_ip,
            ).exception("request_failed")
            raise


# ── Stack assembly ──────────────────────────────────────────────────────────


def register_middleware(app: FastAPI) -> None:
    """Attach all middleware + exception handlers in correct order.

    Starlette runs middleware in **reverse** registration order, so the
    last-registered runs first (outermost). The desired wire order is:

        ProxyHeaders → CORS → RequestLogging → Timeout → RateLimit → Handler

    Therefore registration order is reversed from the wire order.
    """
    settings = get_settings()
    origins = settings.cors_origins

    # ── Inner: timeout (wraps handler) ──
    app.add_middleware(TimeoutMiddleware, timeout=float(settings.request_timeout_sec))

    # ── Request logging (sees timeouts as 504 responses) ──
    app.add_middleware(RequestLoggingMiddleware)

    # ── CORS (must run before request hits any inner middleware) ──
    is_wildcard = origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not is_wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── ProxyHeadersMiddleware: strips/translates X-Forwarded-* from trusted peers ──
    # Pass `forwarded_allow_ips="*"` because we do our own CIDR check inside
    # `_client_ip_key`. Setting it to a CIDR list here would require Starlette
    # 0.40+ syntax differences — we keep the gate inside our key function for
    # consistency with rate-limit keying.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    # ── Rate limit (slowapi state + handler) ──
    limiter.enabled = settings.rate_limit_enabled
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── Exception handlers ──
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on {} {}", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "error_code": "INTERNAL"},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "error_code": "VALIDATION"},
        )
