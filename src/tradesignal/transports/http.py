"""Транспорт: urllib, SSRF-защита, бюджет, ретраи, Retry-After.
Адаптированная версия http-транспорта job-search-collector (свой же код)."""

from __future__ import annotations

import gzip
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.request import HTTPSHandler

from ..models import RawDocument, SourceBlocked

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

RETRYABLE = {429, 500, 502, 503, 504}


class TransportError(Exception):
    def __init__(self, message: str, status: int | None = None,
                 blocked: bool = False):
        super().__init__(message)
        self.status, self.blocked = status, blocked


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SafeHandler(urllib.request.HTTPSHandler):
    """Перенаправления только на https; приватные хосты — отказ."""

    def http_open(self, req):
        raise TransportError("plain http не используется", blocked=False)

    def https_open(self, req):
        host = urllib.parse.urlsplit(req.full_url).hostname
        if not host:
            raise TransportError("нет хоста в URL")
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise TransportError(f"DNS: {exc}") from exc
        for info in infos:
            address = info[4][0]
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                continue
            if parsed.is_private or parsed.is_loopback or \
                    parsed.is_link_local or parsed.is_reserved:
                raise TransportError(f"приватный/локальный хост: {address}")
        return super().https_open(req)


def _retry_after(headers) -> float | None:
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class HttpTransport:
    def __init__(self, delay_seconds: float = 2.0, timeout: float = 30.0,
                 max_retries: int = 2, budget_requests: int = 100):
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.max_retries = max_retries
        self._budget = max(1, budget_requests)
        self._last_request_at = 0.0
        self.requests_made = 0

    def _throttle(self) -> None:
        passed = time.monotonic() - self._last_request_at
        if passed < self.delay_seconds:
            time.sleep(self.delay_seconds - passed)
        self._last_request_at = time.monotonic()

    def get(self, url: str, extra_headers: dict[str, str] | None = None,
            expect_json: bool = True) -> RawDocument:
        for attempt in range(self.max_retries + 1):
            if self.requests_made >= self._budget:
                raise TransportError("исчерпан бюджет запросов")
            self._throttle()
            request = urllib.request.Request(url, method="GET", headers={
                "User-Agent": BROWSER_UA,
                "Accept": "application/json" if expect_json else "*/*",
                "Accept-Encoding": "gzip",
                **(extra_headers or {}),
            })
            self.requests_made += 1
            try:
                opener = urllib.request.build_opener(SafeHandler, _NoRedirect)
                with opener.open(request, timeout=self.timeout) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return RawDocument(
                        url=url, status=response.status,
                        content=body.decode("utf-8", errors="replace"),
                        headers=dict(response.headers.items()))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403, 404):
                    # 401: ключа нет/неверен; 403: доступ закрыт — не ретраить
                    raise TransportError(
                        f"HTTP {exc.code}: доступ закрыт или ключ не принят",
                        status=exc.code,
                        blocked=exc.code == 403) from exc
                wait = _retry_after(exc.headers)
                if exc.code == 429:
                    # preview-канал: лимит ~1 запрос/мин; держим паузу не менее 30с
                    wait = max(wait or 0.0, 30.0)
                else:
                    wait = wait or (2.0 * (attempt + 1))
                if exc.code in RETRYABLE and attempt < self.max_retries:
                    time.sleep(min(wait, 120.0))
                    continue
                raise TransportError(f"HTTP {exc.code}", status=exc.code) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise TransportError(f"сеть: {exc}") from exc
        raise TransportError("не удалось после повторов")


def env_key(name: str, env: dict[str, str]) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise SourceBlocked(
            name.lower().replace("_key", ""),
            f"нет {name} в .env — зарегистрируй ключ (см. .env.example)")
    return value


def payload_for(doc: RawDocument) -> dict | None:
    """JSON-тело ответа или None при пустом/битом (фиксируем как partial)."""
    try:
        return json.loads(doc.content)
    except (json.JSONDecodeError, ValueError):
        return None
