from __future__ import annotations

import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from urllib.parse import urlencode, urljoin, urlsplit

import feedparser
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .common import canonical_url, compact, parse_date, relevant
from .http import Client, FetchError, allowed_url, failure_details, public_error, reject_block_page


def extract_page(body: bytes, mime: str) -> dict:
    if "pdf" in mime.lower() or body[:4] == b"%PDF":
        pdf = PdfReader(io.BytesIO(body))
        text = "\n".join(p.extract_text() or "" for p in pdf.pages[:40])
        return {"text": text[:100_000], "published_date": None, "modified_date": None, "page_title": ""}
    reject_block_page(body)
    soup = BeautifulSoup(body, "html.parser")
    dates = {}
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or "").lower()
        if key in ("article:published_time", "date", "dc.date.issued", "dcterms.issued", "dc.date", "citation_publication_date", "datepublished"):
            dates.setdefault("published_date", parse_date(m.get("content")))
        elif key in ("article:modified_time", "dcterms.modified", "dc.date.modified", "datemodified"):
            dates.setdefault("modified_date", parse_date(m.get("content")))
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("datePublished", "dateModified") and isinstance(v, str):
                    dates.setdefault("published_date" if k == "datePublished" else "modified_date", parse_date(v))
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            pass
    for node in soup.select("time[datetime]"):
        context = compact((node.parent.parent if node.parent and node.parent.parent else node).get_text(" ", strip=True))
        if re.search(r"Content current as of|Last updated|Last modified|更新日期", context, re.I):
            dates["modified_date"] = parse_date(node.get("datetime")) or dates.get("modified_date")
    h1 = soup.find("h1")
    title = compact(h1.get_text(" ", strip=True)) if h1 else ""
    # Prefer article body, excluding navigation, company boilerplate and footer dates.
    root = (soup.select_one(".field--name-body") or soup.select_one(".news-details-content") or
            soup.find("article") or soup.find("main") or soup.select_one('[role="main"]') or soup.body or soup)
    for x in root.select("script,style,nav,footer,header,form,noscript,.breadcrumb,.breadcrumbs,[aria-hidden='true']"):
        x.decompose()
    lines = [compact(x) for x in root.get_text("\n", strip=True).splitlines()]
    lines = [x for x in lines if x and not x.startswith("{{")]
    text = "\n".join(lines)
    # Only explicit publication/date labels; never take the first trial date in prose.
    if not dates.get("published_date"):
        for idx, line in enumerate(lines[:80]):
            if re.search(r"^(For Immediate Release:|Published:?|Publication date:?|Date published:?|发布时间[：:]?|发布日期[：:]?)$", line, re.I):
                dates["published_date"] = parse_date(" ".join(lines[idx:idx+3]))
                break
            if re.match(r"^(Published|发布时间|发布日期)\s*[:：]", line, re.I):
                dates["published_date"] = parse_date(line)
                break
    return {"text": text[:100_000], "page_title": title,
            "published_date": dates.get("published_date"), "modified_date": dates.get("modified_date")}


def feed_records(body: bytes, source: dict) -> list[dict]:
    reject_block_page(body)
    feed = feedparser.parse(body)
    if feed.bozo or not feed.get("version"):
        raise FetchError("invalid or empty non-feed response")
    rows = []
    for entry in feed.entries:
        url = entry.get("link", "")
        if not url:
            continue
        # FDA's own RSS currently emits legacy HTTP links. Upgrade only explicitly
        # verified hosts; never make an HTTP request or broaden the allowlist.
        try:
            parsed = urlsplit(url)
            if (parsed.scheme == "http" and parsed.hostname in source.get("https_link_hosts", [])
                    and not parsed.username and not parsed.password and parsed.port in (None, 80)):
                url = parsed._replace(scheme="https", netloc=parsed.hostname).geturl()
        except ValueError:
            continue
        rows.append({"url": url, "title": compact(BeautifulSoup(entry.get("title", ""), "html.parser").get_text(" ")),
                     "published_date": parse_date(entry.get("published")),
                     "modified_date": parse_date(dict(entry).get("updated")),
                     "text": BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)})
    return rows


def html_records(body: bytes, source: dict, config: dict) -> list[dict]:
    reject_block_page(body)
    soup = BeautifulSoup(body, "html.parser")
    rows, seen, article_links = [], set(), 0
    links = soup.select(source.get("selector", "main a[href], article a[href]"))
    if not links:
        raise FetchError("no article links: source layout may have changed")
    for a in links:
        url = canonical_url(urljoin(source["url"], a.get("href", "")))
        title = compact(a.get_text(" ", strip=True))
        # FDA embeds the publication date inside the link. Keep the same title
        # as RSS so a fallback does not look like a new version of the article.
        time_node = a.select_one("time[datetime]")
        if time_node:
            date_label = compact(time_node.get_text(" ", strip=True))
            if date_label and title.startswith(date_label):
                title = title[len(date_label):].lstrip(" -–—:")
        # Novo renders the date using Vue but embeds the ISO timestamp server-side.
        title = re.sub(r"\{\{.*?\}\}", "", title).strip()
        title = re.sub(r"\s+Read more$", "", title)
        if not title or url in seen or url == canonical_url(source["url"]) or not allowed_url(url, config["allowed_domains"]):
            continue
        if source.get("link_pattern") and not re.search(source["link_pattern"], url):
            continue
        article_links += 1
        seen.add(url)
        # Inspect all source-scoped article links, then relevance-filter title/context.
        parent = a.find_parent(["li", "tr", "article"]) or a.parent
        context = compact(parent.get_text(" ", strip=True))[:1500] if parent else title
        timestamp = parent.select_one("time[datetime]") if parent else None
        published = parse_date(timestamp.get("datetime")) if timestamp else parse_date(context)
        if not published and source.get("date_order") in ("mdy", "dmy"):
            match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", context)
            if match:
                a, b, y = map(int, match.groups())
                try:
                    published = date(y, a, b).isoformat() if source["date_order"] == "mdy" else date(y, b, a).isoformat()
                except ValueError:
                    pass
        rows.append({"url": url, "title": title, "published_date": published,
                     "modified_date": None, "text": "", "discovery_text": context})
    if not article_links:
        category = "dynamic_listing" if re.search(r"Carregando|Loading", soup.get_text(" "), re.I) else "parse_error"
        raise FetchError("no links matched article pattern: source layout may have changed", category)
    return rows


def literature(client: Client, source: dict, config: dict, since: str, until: str) -> tuple[list[dict], list[str]]:
    terms = " OR ".join('"' + p["ingredient"] + '"' for p in config["products"])
    query = f'({terms}) AND (FIRST_PDATE:[{since} TO {until}] OR FIRST_IDATE:[{since} TO {until}]) AND SRC:MED'
    cursor, rows, warnings = "*", [], []
    total = 0
    for _ in range(source.get("max_pages", 6)):
        url = source["url"] + "?" + urlencode({"query": query, "format": "json", "resultType": "core",
                                                 "pageSize": 100, "cursorMark": cursor})
        body, _mime = client.get(url)
        data = json.loads(body)
        if "resultList" not in data or "hitCount" not in data:
            raise FetchError("unexpected Europe PMC schema")
        total = data["hitCount"]
        items = data["resultList"].get("result", [])
        for p in items:
            types = p.get("pubTypeList", {}).get("pubType", [])
            types = [str(t).lower() for t in types]
            if any(t in types for t in ("review", "systematic review", "meta-analysis", "editorial", "comment", "letter")):
                continue
            # Freshly indexed records often lack publication-type tags.
            if re.search(r"(?:systematic|narrative|scoping|critical|comprehensive) review|:\s*a review[.!]?$|meta.analysis|bibliometric|\bprotocol\b|computational.*comparison|evidence.based comparison|trial evidence.*implications", p.get("title", ""), re.I):
                continue
            if "published erratum" in types or "retracted publication" in types:
                correction = True
            else:
                correction = False
            abstract = BeautifulSoup(p.get("abstractText", ""), "html.parser").get_text(" ", strip=True)
            doi = (p.get("doi") or "").lower().removeprefix("https://doi.org/")
            pmid = p.get("pmid") or p.get("id")
            rows.append({"url": "https://pubmed.ncbi.nlm.nih.gov/" + str(pmid) + "/",
                         "title": p.get("title", ""), "text": abstract,
                         "published_date": p.get("firstPublicationDate"), "modified_date": None,
                         "indexed_date": p.get("firstIndexDate"), "doi": doi, "pmid": str(pmid),
                         "publication_types": types, "correction": correction,
                         "research_status": "indexed_primary_candidate",
                         "journal": p.get("journalInfo", {}).get("journal", {}).get("title", "")})
        next_cursor = data.get("nextCursorMark")
        if not items or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    else:
        warnings.append(f"literature pagination cap reached; {total} indexed hits; increase max_pages")
    return rows, warnings


def novo_news(client: Client, source: dict, since: str, until: str):
    """Novo's own public archive API, as used by its news-search JavaScript."""
    rows, warnings = [], []
    for page in range(source.get("max_pages", 10)):
        params = {"searchtext": "", "start": since, "end": until,
                  "newspath": "/content/dam/nncorp/global/en/investors/content-fragments/ir-materials",
                  "limit": 50, "currentresults": page * 50, "function": "search", "language": "all",
                  "type": "5355,5356", "disablesearchfromdb": "false"}
        body, _mime = client.get(source["url"] + "?" + urlencode(params))
        data = json.loads(body)
        if data.get("status") != 200 or "resultBeanList" not in data.get("data", {}):
            raise FetchError("unexpected Novo archive schema")
        items = data["data"]["resultBeanList"]
        for item in items:
            if not item.get("id"):
                continue
            rows.append({"url": "https://www.novonordisk.com/news-and-media/news-and-ir-materials/news-details.html?id=" + str(item["id"]),
                         "title": item["title"], "published_date": parse_date(item.get("date")), "modified_date": None,
                         "text": BeautifulSoup(item.get("newsContent", ""), "html.parser").get_text("\n", strip=True)})
        if not items or (page+1)*50 >= data["data"]["numberOfResults"]:
            break
    else:
        warnings.append("Novo archive pagination cap reached")
    return rows, warnings


def discover(source: dict, config: dict, client: Client, since: str, until: str):
    kind = source["kind"]
    if kind == "novo":
        return novo_news(client, source, since, until)
    if kind == "europepmc":
        return literature(client, source, config, since, until)
    body, mime = client.get(source["url"])
    if kind == "rss":
        records = feed_records(body, source)
        dates = [r["published_date"] or r["modified_date"] for r in records]
        dates = [d for d in dates if d]
        warnings = []
        if not records:
            warnings.append("empty valid feed; current source coverage cannot be established")
        elif not dates:
            warnings.append("feed has no reliable dates; requested lookback cannot be verified")
        elif min(dates) > since:
            warnings.append("feed window shorter than requested lookback; archives not exhaustively searched")
        return records, warnings
    if kind == "html":
        return html_records(body, source, config), ["current listing only; no claim of exhaustive regional coverage"]
    if kind == "page":
        doc = extract_page(body, mime)
        if len(doc["text"]) < 120:
            raise FetchError("page body missing or too short", "invalid_response")
        return [{"url": source["url"], "title": doc.pop("page_title") or source["name"], **doc}], []
    raise FetchError("unsupported source adapter")


def collect_source(source: dict, config: dict, client: Client, since: str, until: str) -> tuple[list[dict], dict]:
    health = {"id": source["id"], "name": source["name"], "region": source["region"],
              "url": source["url"] if allowed_url(source["url"], config["allowed_domains"]) else "[rejected URL]",
              "status": "ok", "discovered": 0, "accepted": 0,
              "warnings": [], "attempts": [], "article_failures": []}
    stage = "discovery"
    try:
        # Alternatives are explicitly configured public endpoints, not synthesized URLs.
        # Never try an alternative after an access restriction or rate limit.
        candidates = [source] + [dict(source, **alt) for alt in source.get("alternatives", [])]
        for index, endpoint in enumerate(candidates):
            attempt = {"url": endpoint["url"] if allowed_url(endpoint["url"], config["allowed_domains"]) else "[rejected URL]",
                       "kind": endpoint["kind"]}
            health["attempts"].append(attempt)
            try:
                records, warnings = discover(endpoint, config, client, since, until)
                attempt["status"] = "ok"
                health["endpoint_used"] = endpoint["url"]
                health["warnings"].extend(warnings)
                kind = endpoint["kind"]
                if index:
                    health["warnings"].append("primary endpoint failed; using a published alternative with potentially narrower coverage")
                break
            except Exception as e:
                attempt.update(status="failed", **failure_details(e))
                if (index == len(candidates) - 1 or failure_details(e)["failure_type"] not in
                        {"http_not_found", "http_server_error", "network_error", "timeout", "parse_error", "invalid_response", "dynamic_listing"}):
                    raise
        health["discovered"] = len(records)
        stage = "articles"
        result = []
        restricted_hosts = set()
        for r in records:
            if not allowed_url(r["url"], config["allowed_domains"]):
                health["warnings"].append("rejected off-domain article link")
                continue
            if not relevant(r["title"] + " " + r.get("text", "") + " " + r.pop("discovery_text", ""), config):
                continue
            known_date = r.get("modified_date") or r.get("published_date")
            if known_date and known_date < since and kind != "page":
                continue
            if kind in ("html", "rss"):
                try:
                    host = urlsplit(r["url"]).hostname
                    if host in restricted_hosts:
                        raise FetchError("article host already restricted in this source run", "access_restricted")
                    article, mime = client.get(r["url"])
                    page = extract_page(article, mime)
                    if len(page["text"]) < 120:
                        raise FetchError("article body missing or too short", "invalid_response")
                    r["text"] = page["text"]
                    for field in ("published_date", "modified_date"):
                        r[field] = page.get(field) or r.get(field)
                    r["body_status"] = "fetched"
                except Exception as e:
                    r["body_status"] = "unavailable"
                    details = failure_details(e)
                    if details["failure_type"] in ("access_restricted", "rate_limited"):
                        restricted_hosts.add(host)
                    health["article_failures"].append({"url": canonical_url(r["url"]), **details})
                    health["warnings"].append(f"article fetch failed: {canonical_url(r['url'])} ({public_error(e)})")
            elif kind == "europepmc":
                r["body_status"] = "abstract_only" if r.get("text") else "metadata_only"
            else:
                r["body_status"] = "fetched"
            r.update({"source_id": source["id"], "source_name": source["name"], "source_type": source["type"],
                      "source_region": source["region"], "url": canonical_url(r["url"])})
            result.append(r)
        health["accepted"] = len(result)
        if health["warnings"]:
            health["status"] = "partial"
        return result, health
    except Exception as e:
        # Exceptions are visible; a blocked country is not reported as having no events.
        health.update(status="failed", failure_stage=stage, error=public_error(e), **failure_details(e))
        return [], health


def collect(config: dict, client: Client, since: str, until: str, selected: set[str] | None = None):
    sources = [s for s in config["sources"] if s.get("enabled", True) and (not selected or s["id"] in selected)]
    if not sources:
        raise ValueError("no configured sources selected")
    rows, health = [], []
    with ThreadPoolExecutor(max_workers=config.get("workers", 4)) as pool:
        futures = [pool.submit(collect_source, s, config, client, since, until) for s in sources]
        for f in as_completed(futures):
            records, status = f.result()
            rows.extend(records)
            health.append(status)
            print(f"{status['id']}: {status['status']}; {len(records)} relevant records", flush=True)
    return sorted(rows, key=lambda r: (r["source_id"], r["url"])), sorted(health, key=lambda h: h["id"])
