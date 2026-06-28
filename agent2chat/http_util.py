"""Tiny stdlib HTTP helper: JSON requests with exponential-backoff retries.

Kept dependency-free on purpose (no ``requests``). Used by the Slack and Teams
connectors; the Telegram connector has its own thin client for parity with upstream.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("agent2chat.http")


class HttpError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    json_body: dict | None = None,
    form_body: dict | None = None,
    timeout: float = 30,
    max_retries: int = 4,
) -> dict:
    """Perform an HTTP request and decode the JSON response.

    Exactly one of *json_body* / *form_body* may be given. Retries transient network
    errors and 5xx/429 with exponential backoff; raises :class:`HttpError` otherwise.
    """
    headers = dict(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
    elif form_body is not None:
        data = urllib.parse.urlencode(form_body, doseq=True).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    attempt = 0
    while True:
        attempt += 1
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as e:
            body = _read(e)
            if e.code == 429 or (e.code >= 500 and attempt <= max_retries):
                wait = _retry_after(e) or min(2 ** attempt, 30)
                log.warning("%s %s -> HTTP %s, retry %d in %ss", method, url, e.code, attempt, wait)
                time.sleep(wait)
                continue
            raise HttpError(f"{method} {url}: HTTP {e.code}", status=e.code, body=body) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            if attempt <= max_retries:
                log.warning("%s %s -> %s, retry %d", method, url, e, attempt)
                time.sleep(min(2 ** attempt, 30))
                continue
            raise HttpError(f"{method} {url}: {e}") from e


def _read(err: urllib.error.HTTPError) -> str:
    try:
        return err.read().decode("utf-8")
    except Exception:
        return ""


def _retry_after(err: urllib.error.HTTPError) -> int | None:
    try:
        return int(err.headers.get("Retry-After", "")) or None
    except (TypeError, ValueError):
        return None
