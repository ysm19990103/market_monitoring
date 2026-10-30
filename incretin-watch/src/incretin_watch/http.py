from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .common import digest, load_json, write_json


class FetchError(RuntimeError):
    pass


def allowed_url(url: str, domains: list[str]) -> bool:
    p = urlsplit(url)
    return p.scheme == "https" and not p.username and not p.password and p.port in (None, 443) and any(
        p.hostname == d or (p.hostname or "").endswith("." + d) for d in domains)


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, domains):
        self.domains = domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl, self.domains):
            raise FetchError("redirect outside configured official domains")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, cache: Path, domains: list[str], timeout=18, retries=2):
        self.cache, self.domains = cache, domains
        self.timeout, self.retries = timeout, retries
        self.opener = build_opener(SafeRedirect(domains))
        self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> tuple[bytes, str]:
        if not allowed_url(url, self.domains):
            raise FetchError("URL outside configured official domains")
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
                        raise FetchError("response exceeds 8 MB limit")
                    raw.write_bytes(body)
                    mime = r.headers.get("Content-Type", "")
                    write_json(meta, {"etag": r.headers.get("ETag"), "modified": r.headers.get("Last-Modified"), "mime": mime})
                    return body, mime
            except HTTPError as e:
                if e.code == 304 and raw.exists():
                    return raw.read_bytes(), prior.get("mime", "")
                if e.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise FetchError(f"HTTP {e.code}") from e
                delay = e.headers.get("Retry-After", "")
                time.sleep(min(int(delay), 15) if delay.isdigit() else 2 ** attempt)
            except (URLError, socket.timeout, TimeoutError, OSError) as e:
                if attempt == self.retries:
                    raise FetchError(type(e).__name__) from e
                time.sleep(2 ** attempt)
        raise FetchError("request exhausted")
