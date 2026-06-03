"""
Byparr client — stateless safe fetcher (health + retry + validate).

Alleen aanroepen via byparr_traffic.submit(), niet direct vanuit scrapers.
"""
from __future__ import annotations

import os
import time
import logging
from enum import Enum

import requests

logger = logging.getLogger(__name__)

BYPARR_HEALTH_URL = os.getenv("BYPARR_HEALTH_URL", "http://byparr:8191/health")
BYPARR_URL = os.getenv("BYPARR_URL", "http://byparr:8191/v1")
HEALTH_TIMEOUT = float(os.getenv("BYPARR_HEALTH_TIMEOUT", "2"))
HEALTH_RETRY_WAIT = float(os.getenv("BYPARR_HEALTH_RETRY_WAIT", "3"))
BYPARR_MAX_TIMEOUT_SEC = int(os.getenv("BYPARR_MAX_TIMEOUT_SEC", "25"))
# Ruimer dan Byparr-page timeout: queue + browser kan 25–35s duren
BYPARR_READ_TIMEOUT = float(os.getenv("BYPARR_READ_TIMEOUT", str(BYPARR_MAX_TIMEOUT_SEC + 25)))
BYPARR_CONNECT_TIMEOUT = float(os.getenv("BYPARR_CONNECT_TIMEOUT", "5"))
BYPARR_MIN_HTML_BYTES = int(os.getenv("BYPARR_MIN_HTML_BYTES", "500"))
BYPARR_REQUEST_RETRIES = int(os.getenv("BYPARR_REQUEST_RETRIES", "2"))
_RETRY_BACKOFF = (1.0, 3.0)

_session = requests.Session()
_session.headers.update({"User-Agent": "huiszoeker-byparr/1.0"})


class ByparrFailureKind(str, Enum):
    UNAVAILABLE = "unavailable"
    UPSTREAM_HTTP = "upstream_http"
    INVALID_JSON = "invalid_json"
    COMMAND_ERROR = "command_error"
    EMPTY_HTML = "empty_html"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    CIRCUIT_OPEN = "circuit_open"
    ROUTE_BLOCKED = "route_blocked"
    DEGRADED = "degraded"
    BACKPRESSURE = "backpressure"
    UNKNOWN = "unknown"


class ByparrError(RuntimeError):
    def __init__(self, kind: ByparrFailureKind, message: str, *, status: int | None = None, body_len: int = 0):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.body_len = body_len


class ByparrUnavailable(ByparrError):
    def __init__(self, message: str = "ByparrUnavailable"):
        super().__init__(ByparrFailureKind.UNAVAILABLE, message)


def byparr_health_check() -> bool:
    """
    GET /health. True = bereikbaar of bezig (timeout tijdens scrape ≠ offline).
    Alleen connection refused / connect-fout = False.
    """
    t0 = time.monotonic()
    try:
        r = _session.get(BYPARR_HEALTH_URL, timeout=HEALTH_TIMEOUT)
        ok = r.status_code == 200
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            f"[byparr-health] status={'ok' if ok else 'down'} "
            f"latency_ms={latency_ms} http={r.status_code}",
        )
        return ok
    except requests.Timeout:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            f"[byparr-health] status=busy latency_ms={latency_ms} "
            f"(health timeout — Byparr verwerkt waarschijnlijk een request)",
        )
        return True
    except requests.ConnectionError as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.warning(
            f"[byparr-health] status=down latency_ms={latency_ms} err={e}",
        )
        return False
    except requests.RequestException as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.warning(
            f"[byparr-health] status=down latency_ms={latency_ms} err={e}",
        )
        return False


def _ensure_byparr_available() -> None:
    """Blokkeer alleen bij echt offline (geen TCP). Timeout = busy → fetch gewoon proberen."""
    if byparr_health_check():
        return
    time.sleep(HEALTH_RETRY_WAIT)
    if byparr_health_check():
        return
    raise ByparrUnavailable("Byparr niet bereikbaar (connection refused)")


def _parse_byparr_response(r: requests.Response) -> str:
    body_len = len(r.content or b"")
    status = r.status_code

    if status >= 500:
        raise ByparrError(
            ByparrFailureKind.UPSTREAM_HTTP,
            f"HTTP {status}",
            status=status,
            body_len=body_len,
        )

    try:
        data = r.json()
    except ValueError as e:
        raise ByparrError(
            ByparrFailureKind.INVALID_JSON,
            f"JSON parse error (status={status}, len={body_len})",
            status=status,
            body_len=body_len,
        ) from e

    if data.get("status") != "ok":
        msg = data.get("message") or data.get("status")
        raise ByparrError(
            ByparrFailureKind.COMMAND_ERROR,
            f"Byparr: {msg}",
            status=status,
            body_len=body_len,
        )

    html = (data.get("solution") or {}).get("response") or ""
    if not isinstance(html, str) or len(html) < BYPARR_MIN_HTML_BYTES:
        raise ByparrError(
            ByparrFailureKind.EMPTY_HTML,
            f"te korte HTML ({len(html)} bytes)",
            status=status,
            body_len=body_len,
        )
    return html


def _request_once(target_url: str) -> str:
    r = _session.post(
        BYPARR_URL,
        json={
            "cmd": "request.get",
            "url": target_url,
            "max_timeout": BYPARR_MAX_TIMEOUT_SEC,
        },
        timeout=(BYPARR_CONNECT_TIMEOUT, BYPARR_READ_TIMEOUT),
    )
    return _parse_byparr_response(r)


def _is_retryable(exc: BaseException) -> bool:
    # ReadTimeout: Byparr kan nog bezig zijn — geen tweede POST (veroorzaakt parallel browsers)
    if isinstance(exc, requests.ReadTimeout):
        return False
    if isinstance(exc, requests.ConnectionError):
        return True
    if isinstance(exc, ByparrError):
        return exc.kind in {
            ByparrFailureKind.UPSTREAM_HTTP,
            ByparrFailureKind.INVALID_JSON,
            ByparrFailureKind.CONNECTION,
        }
    return False


def fetch(target_url: str, *, scraper: str = "unknown") -> str:
    """
    Interne HTTP-fetch met health-check en max 2 retries (1s, 3s backoff).
    Gebruik byparr_traffic.submit() als publieke API.
    """
    _ensure_byparr_available()

    last_err: BaseException | None = None
    max_attempts = 1 + BYPARR_REQUEST_RETRIES

    for retry_count in range(max_attempts):
        t0 = time.monotonic()
        try:
            html = _request_once(target_url)
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                f"[byparr] scraper={scraper} outcome=ok retry_count={retry_count} "
                f"latency_ms={latency_ms}",
            )
            return html
        except Exception as e:
            last_err = e
            latency_ms = int((time.monotonic() - t0) * 1000)
            outcome = (
                e.kind.value
                if isinstance(e, ByparrError)
                else type(e).__name__.lower()
            )
            logger.warning(
                f"[byparr] scraper={scraper} outcome={outcome} retry_count={retry_count} "
                f"latency_ms={latency_ms} msg={e}",
            )
            if retry_count >= BYPARR_REQUEST_RETRIES or not _is_retryable(e):
                break
            time.sleep(_RETRY_BACKOFF[min(retry_count, len(_RETRY_BACKOFF) - 1)])

    if isinstance(last_err, ByparrError):
        raise last_err
    if isinstance(last_err, requests.RequestException):
        raise ByparrError(ByparrFailureKind.CONNECTION, str(last_err)) from last_err
    raise ByparrError(ByparrFailureKind.UNKNOWN, str(last_err or "onbekende fout"))


__all__ = [
    "ByparrError",
    "ByparrFailureKind",
    "ByparrUnavailable",
    "byparr_health_check",
    "fetch",
]
