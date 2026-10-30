from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil.parser import parse as parse_datetime


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in
             {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "referer"}]
    # Keep identity-bearing parameters: Novo's ?id=..., PMDA's ...?dataId=... .
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"),
                       urlencode(sorted(query)), ""))


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = compact(value)
    # Do not turn an incomplete year/month into today's month/day.
    patterns = [r"\b\d{4}-\d{1,2}-\d{1,2}(?!\d)", r"\d{4}年\d{1,2}月\d{1,2}日",
                r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}\b",
                r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{4}\b"]
    for pat in patterns:
        m = re.search(pat, value, re.I)
        if m:
            token = m.group().replace("年", "-").replace("月", "-").replace("日", "")
            try:
                return parse_datetime(token, fuzzy=False).date().isoformat()
            except (ValueError, OverflowError):
                pass
    return None


def has_term(text: str, term: str) -> bool:
    text, term = compact(text).casefold(), compact(term).casefold()
    if re.search(r"[^\x00-\x7f]", term):
        return term in text
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))


def matches(text: str, config: dict) -> tuple[list[str], list[str], list[str]]:
    molecules, brands, companies = [], [], []
    for p in config["products"]:
        if any(has_term(text, t) for t in p["aliases"] + p["brands"]):
            molecules.append(p["ingredient"])
            companies.append(p["company"])
            brands.extend(b for b in p["brands"] if has_term(text, b))
    return sorted(set(molecules)), sorted(set(brands)), sorted(set(companies))


def relevant(text: str, config: dict) -> bool:
    return bool(matches(text, config)[0]) or any(has_term(text, t) for t in config["class_terms"])


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default: object) -> object:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def clip_words(text: str, limit: int = 24) -> str:
    # Also cap scripts without whitespace, e.g. Chinese/Japanese.
    text = compact(text)
    if re.search(r"[\u3400-\u9fff\u3040-\u30ff]", text):
        return text[:70]
    return " ".join(text.split()[:limit])
