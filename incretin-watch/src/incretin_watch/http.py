from __future__ import annotations

import json
import re
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup

from .common import digest, load_json, write_json


class FetchError(RuntimeError):
    def __init__(self, message, category="parse_error", http_status=None):
        super().__init__(message)
        self.category = category
        self.http_status = http_status


def failure_details(error: Exception) -> dict:
    """Public diagnostics never include response bodies, credentials or local paths."""
    if isinstance(error, FetchError):
        result = {"failure_type": error.category}
        if error.http_status is not None:
            result["http_status"] = error.http_status
        return result
    return {"failure_type": "parse_error" if isinstance(error, (ValueError, KeyError, TypeError)) else "internal_error"}


def public_error(error: Exception) -> str:
    info = failure_details(error)
    return info["failure_type"] + (f" (HTTP {info['http_status']})" if "http_status" in info else "")


def reject_block_page(body: bytes) -> None:
    """Stop on explicit challenges, including HTTP 200/503 response bodies."""
    if body.startswith(b"%PDF") or re.search(br"<(?:rss|feed|rdf:RDF)\b", body[:500], re.I):
        return
    if b"<" not in body[:200]:
        if re.fullmatch(br"\s*(?:access denied|forbidden|verify (?:that )?you are human)[.!\s]*", body, re.I):
            raise FetchError("access challenge; manual review required", "access_restricted")
        return
    soup = BeautifulSoup(body, "html.parser")
    headings = " ".join(n.get_text(" ", strip=True) for n in soup.select("title,h1"))
    if (re.search(r"verify (?:that )?you are human|checking your browser|just a moment|access denied|^forbidden$", headings, re.I)
            or soup.select_one("form#challenge-form, #cf-challenge-running, .g-recaptcha, .h-captcha")):
        raise FetchError("access challenge; manual review required", "access_restricted")


def allowed_url(url: str, domains: list[str]) -> bool:
    try:
        p = urlsplit(url)
        private_params = {"api_key", "apikey", "key", "token", "access_token", "authorization", "password", "secret"}
        return (p.scheme == "https" and not p.username and not p.password and p.port in (None, 443)
                and not any(k.lower() in private_params for k, _ in parse_qsl(p.query))
                and any(p.hostname == d or (p.hostname or "").endswith("." + d) for d in domains))
    except ValueError:
        return False


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, domains):
        self.domains = domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl, self.domains):
            raise FetchError("redirect outside configured official domains", "policy_rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, cache: Path, domains: list[str], timeout=18, retries=2):
        self.cache, self.domains = cache, domains
        self.timeout, self.retries = timeout, retries
        self.opener = build_opener(SafeRedirect(domains))
        self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> tuple[bytes, str]:
        if not allowed_url(url, self.domains):
            raise FetchError("URL outside configured official domains", "policy_rejected")
        key = digest(url)
        raw, meta = self.cache / (key + ".bin"), self.cache / (key + ".json")
        prior = load_json(meta, {})
        headers = {"User-Agent": "IncretinWatch/0.1 (primary-source research)",
                   "Accept": "text/html,application/rss+xml,application/atom+xml,application/json,application/pdf;q=0.9,*/*;q=0.8"}
        if raw.exists():
            for source, target in [("etag", "If-None-Match"), ("modified", "If-Modified-Since")]:
                if prior.get(source):
                    headers[target] = prior[source]
        for attempt in range(self.retries + 1):
            try:
                with self.opener.open(Request(url, headers=headers), timeout=self.timeout) as r:
                    body = r.read(8_000_001)
                    if len(body) > 8_000_000:
                        raise FetchError("response exceeds 8 MB limit", "invalid_response")
                    reject_block_page(body)
                    raw.write_bytes(body)
                    mime = r.headers.get("Content-Type", "")
                    write_json(meta, {"etag": r.headers.get("ETag"), "modified": r.headers.get("Last-Modified"), "mime": mime})
                    return body, mime
            except HTTPError as e:
                if e.code == 304 and raw.exists():
                    cached = raw.read_bytes()
                    reject_block_page(cached)
                    return cached, prior.get("mime", "")
                if e.code in (500, 502, 503, 504):
                    reject_block_page(e.read(16_000))
                category = ("access_restricted" if e.code in (401, 403, 407, 412, 451) else
                            "rate_limited" if e.code == 429 else
                            "http_not_found" if e.code in (404, 410) else
                            "http_server_error" if e.code >= 500 else "http_error")
                if e.code not in (500, 502, 503, 504) or attempt == self.retries:
                    raise FetchError(f"HTTP {e.code}", category, e.code) from e
                delay = e.headers.get("Retry-After", "")
                # Never retry earlier than requested; long/date-form delays wait for a later manual run.
                if delay and (not delay.isdigit() or int(delay) > 15):
                    raise FetchError(f"HTTP {e.code}", category, e.code) from e
                time.sleep(int(delay) if delay.isdigit() else 2 ** attempt)
            except (URLError, socket.timeout, TimeoutError, OSError) as e:
                if attempt == self.retries:
                    reason = getattr(e, "reason", e)
                    category = "timeout" if isinstance(reason, (socket.timeout, TimeoutError)) else "network_error"
                    raise FetchError(type(e).__name__, category) from e
                time.sleep(2 ** attempt)
        raise FetchError("request exhausted")
