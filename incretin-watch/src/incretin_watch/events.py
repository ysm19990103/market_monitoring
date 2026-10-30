from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

from .common import compact, digest, has_term, matches, parse_date, relevant


CATEGORIES = [
    ("safety", "安全性信号", r"safety|adverse|pancreatitis|suicid|NAION|optic neuropathy|recall|安全|不良反应|副作用|风险|precautions|seguran|pancreatite|警告"),
    ("regulatory", "监管政策", r"policy|compound|shortage|warning letter|reimburse|coverage|Medicare|Medicaid|医保|政策|短缺|定价|advertis|prescri|falsif|counterfeit"),
    ("approval", "批准/审评进展", r"\bapproval\b|approves\b|approved (?:for|in|by)|authoris|authoriz|CHMP|positive opinion|获批|批准|受理|aprov|承認"),
    ("launch", "产品上市", r"launch|now available|commercial availability|上市|availability|lança"),
    ("clinical", "临床研究", r"trial|phase [23]|phase III|randomi[sz]|study|studies|results|endpoint|研究|试验|結果|estudo"),
    ("competition", "竞争与市场", r"sales|revenue|price|pricing|supply|manufactur|capacity|earnings|financial|market|销售|营收|产能|价格|竞争|利润")]


def classify(title: str, text: str) -> tuple[list[str], str]:
    head = compact(title + " " + text[:1600])
    categories = [key for key, _label, pat in CATEGORIES if re.search(pat, title, re.I)]
    if not categories:
        categories = [key for key, _label, pat in CATEGORIES if re.search(pat, head, re.I)]
    if re.search(r"financial results|quarter.*results|earnings|营收|财报", title, re.I):
        return ["competition"], "financial_report"
    stage = "reported_development"
    # Order matters: a CHMP opinion / accepted application is not marketing authorisation.
    if re.search(r"positive opinion|CHMP.*recommend|recommends? approv|建议批准|积极意见", head, re.I):
        stage = "positive_opinion"
    elif re.search(r"application.*(accept|submit)|submitted.*application|申请.*(受理|提交)", head, re.I):
        stage = "application"
    elif re.search(r"\bnot approv|\bunapproved|\bnot authori[sz]|未获批|未经批准", title, re.I):
        stage = "unapproved_products_notice"
    elif re.search(r"\bapproves\b|\bapproval\b|approved (?:for|in|by)|获批|批准上市|grants? .*authori", title, re.I):
        stage = "approval_report"
    elif re.search(r"now available|launch(?:ed|es)?\b|上市销售", title, re.I):
        stage = "launch_report"
    elif re.search(r"to present|will present|upcoming|将.*公布|将.*发布", title, re.I):
        stage = "conference_preview"
    elif "clinical" in categories:
        stage = "results_report"
    return categories, stage


def event_date(row: dict) -> tuple[str | None, str]:
    # Article publication is the event for publication of a research result only.
    if row["source_type"] == "research" and row.get("published_date"):
        return row["published_date"], "研究首次发表日期；不是试验完成日期"
    lead = row.get("text", "")[:4000]
    _categories, stage = classify(row["title"], lead)
    action = {"approval_report": r"approved|granted|批准", "positive_opinion": r"adopted|通过",
              "launch_report": r"launched|上市"}.get(stage)
    if not action:
        return None, "未找到与本次事件唯一对应的明确日期；公告日期另列"
    # Require an explicit date connected to an action; multiple possible dates -> unknown.
    candidates = []
    for sentence in re.split(r"(?<=[.!?。])\s+|\n", lead):
        if re.search(r"\bon\b|于\d{4}年", sentence, re.I) and re.search(action, sentence, re.I):
            # Two distinct dates in one sentence are ambiguous (e.g. approval then launch).
            if len(re.findall(r"\b\d{4}\b", sentence)) != 1:
                continue
            d = parse_date(sentence)
            if d:
                candidates.append(d)
    if len(set(candidates)) == 1:
        return candidates[0], "原文明确日期与行动相连；仍需按原文确认具体事件"
    if row.get("published_date") and re.search(r"\btoday\s+(?:\w+\s+){0,2}(?:" + action + r")", lead, re.I):
        return row["published_date"], "原文明确 today 与该行动相连，并有公告发布日期"
    return None, "原文未能唯一确认；不以公告日期或抓取日期替代"


def jurisdiction(row: dict) -> str:
    head = (row["title"] + " " + row.get("text", "")[:1300]).lower()
    countries = []
    for region, pattern in [("US", r"\bfda\b|united states|\bu\.s\.|美国"),
                            ("EU", r"\bchmp\b|european commission|european union|欧盟"),
                            ("UK", r"\bmhra\b|united kingdom|英国"),
                            ("CN", r"\bnmpa\b|中国|china"), ("JP", r"\bpmda\b|japan|日本"),
                            ("CA", r"health canada|canada|加拿大"), ("AU", r"\btga\b|australia|澳大利亚")]:
        if re.search(pattern, head):
            countries.append(region)
    if row["source_type"] == "regulator" and row["source_region"] != "Global":
        return row["source_region"]
    return ",".join(sorted(countries)) or "未明确"


def prepare(row: dict, config: dict) -> dict | None:
    # Drug mentions in corporate boilerplate must not make unrelated news relevant.
    title = compact(row["title"])
    text = row.get("text", "")
    if row["source_type"] == "company":
        text = re.split(r"\n(?:About (?:Lilly|Novo|Mounjaro|Zepbound|Wegovy|Foundayo)|IMPORTANT SAFETY|INDICATION AND SAFETY|Forward-Looking Statements)", text, maxsplit=1, flags=re.I)[0]
    lead = title + " " + text[:6000]
    if not relevant(lead, config):
        return None
    molecules, brands, companies = matches(lead, config)
    cats, stage = classify(title, text)
    if not cats:
        return None
    if row["source_type"] == "research":
        # Prioritize human clinical evidence and pharmacovigilance; exclude obvious laboratory-only work.
        if re.search(r"\b(mice|murine|rats|in vitro|cell line|molecular docking)\b", title, re.I):
            return None
        if re.search(r"\b(mice|murine|rats|rat model|mouse model)\b", text, re.I) and not re.search(r"\b(patients|participants|clinical trial|human subjects)\b", text, re.I):
            return None
        if re.search(r"(?:systematic|narrative|scoping|critical|comprehensive) review|:\s*a review[.!]?$|meta.analysis|\bprotocol\b|computational|trial evidence.*implications", title, re.I):
            return None
        if not re.search(r"randomi[sz]|phase (?:3|iii)|cardiovascular|head.to.head|mortality|cohort|comparative|safety|adverse|pharmacovigilance|real.world|kidney|liver|obstructive|trial", lead, re.I) and not row.get("correction"):
            return None
        stage = "correction_or_retraction" if row.get("correction") else "study_publication"
        cats = list(dict.fromkeys(["clinical"] + cats))
    focus = [compact(s) for s in re.split(r"\n|(?<=[.!?。])\s+(?=[A-Z\u4e00-\u9fff])", text)
             if len(compact(s)) >= 30 and relevant(s, config)]
    # Keep a bounded body for analysis; full source documents never enter git state.
    evidence_text = compact(title + "\n" + text[:18000])
    meaningful = compact(title + " " + text[:4000] + " " + " ".join(focus[:18])) or evidence_text[:6000]
    d, basis = event_date(row)
    priority = 20 + (20 if any(c in config["focus_companies"] for c in companies) else 0)
    priority += 20 if row["source_type"] == "regulator" else 0
    priority += 15 if any(c in cats for c in ["approval", "safety", "regulatory"]) else 0
    priority -= 15 if re.search(r"case report|two.*children", title, re.I) and "safety" not in cats else 0
    priority += 20 if re.search(r"phase (?:3|iii)|head.to.head", lead, re.I) else (12 if re.search(r"randomi[sz]|primary endpoint", lead, re.I) else 0)
    priority -= 25 if stage == "conference_preview" else 0
    priority -= 20 if row.get("body_status") in ("unavailable", "metadata_only") else 0
    def information_score(sentence):
        return (3 * bool(re.search(r"\d+(?:\.\d+)?%|hazard ratio|confidence interval|primary endpoint|\bHR\b|\bCI\b", sentence, re.I))
                + 2 * bool(re.search(r"reduced|reduction|increased|improved|approved|reported|results|compared|生效|降低|批准|风险", sentence, re.I))
                - 4 * bool(re.search(r"\b(background|aims|objective|we aimed|we investigated|may|might)\b", sentence, re.I)))
    excerpt = max(focus, key=information_score) if focus else title
    return {**row, "title": title, "text": evidence_text, "molecules": molecules, "brands": brands,
            "companies": companies, "categories": cats, "stage": stage, "jurisdiction": jurisdiction(row),
            "event_date": d, "event_date_basis": basis, "priority": priority,
            "fingerprint": digest(meaningful), "trial_ids": sorted(set(re.findall(r"\bNCT\d{8}\b", evidence_text, re.I))),
            "excerpt_candidate": excerpt}


def title_tokens(title: str) -> set[str]:
    stop = {"the", "a", "an", "of", "for", "and", "in", "to", "with", "on", "at", "by", "lilly", "novo", "nordisk", "eli"}
    return set(re.findall(r"[a-z0-9]+", title.lower())) - stop


def same_event(a: dict, b: dict) -> bool:
    if a.get("url") == b.get("url") and a.get("fingerprint") == b.get("fingerprint"):
        return True
    # DOI is study identity, but a separately published correction must remain a new event.
    if a.get("doi") and a.get("doi") == b.get("doi") and a["stage"] == b["stage"]:
        return True
    if a["stage"] != b["stage"] or a["jurisdiction"] != b["jurisdiction"]:
        return False
    if set(a["molecules"]) != set(b["molecules"]) or not a["molecules"]:
        return False
    if a.get("brands") and b.get("brands") and not set(a["brands"]) & set(b["brands"]):
        return False
    da, db = a.get("event_date") or a.get("published_date"), b.get("event_date") or b.get("published_date")
    if not da or not db or abs((date.fromisoformat(da) - date.fromisoformat(db)).days) > 7:
        return False
    # Do not merge updates with different numeric endpoints or new populations/doses.
    na, nb = set(re.findall(r"\b\d+(?:\.\d+)?%?", a["title"])), set(re.findall(r"\b\d+(?:\.\d+)?%?", b["title"]))
    if na != nb:
        return False
    ta, tb = title_tokens(a["title"]), title_tokens(b["title"])
    similarity = len(ta & tb) / max(1, len(ta | tb))
    return similarity >= 0.67 or SequenceMatcher(None, compact(a["title"]).lower(), compact(b["title"]).lower()).ratio() >= 0.9


def public_record(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("text", "excerpt_candidate")}


def stage_events(rows: list[dict], config: dict, state: dict, since: str, until: str):
    state.setdefault("schema_version", 1)
    if state["schema_version"] != 1:
        raise ValueError("unsupported state schema; restore a compatible state file")
    docs, events = state.setdefault("documents", {}), state.setdefault("events", {})
    fresh, review, skipped = [], [], 0
    for row in rows:
        r = prepare(row, config)
        if not r:
            continue
        key = digest(r["url"])
        old = docs.get(key)
        baseline_now_dated = bool(old and old.get("baseline") and r.get("published_date") and since <= r["published_date"] <= until)
        if old and r["fingerprint"] in old.get("revisions", []) and not baseline_now_dated:
            skipped += 1
            continue
        dates = [r.get("event_date"), r.get("published_date"), r.get("modified_date")]
        dates = [d for d in dates if d]
        if any(d > until for d in dates if d == r.get("published_date")):
            review.append({"title": r["title"], "url": r["url"], "reason": "publication date is in the future"})
            continue
        if r.get("body_status") in ("unavailable", "metadata_only"):
            review.append({"title": r["title"], "url": r["url"], "reason": "full article or abstract unavailable; retry next run"})
            continue
        changed = bool(old and r["fingerprint"] not in old.get("revisions", []))
        if not dates and not changed:
            review.append({"title": r["title"], "url": r["url"], "reason": "date unverified; not treated as recent news"})
            # Keep baseline for rolling pages, but not a false recent event.
            docs[key] = {"url": r["url"], "revisions": [r["fingerprint"]], "last_seen": until, "baseline": True}
            continue
        if dates and max(dates) < since and not changed:
            docs[key] = {"url": r["url"], "revisions": [r["fingerprint"]], "last_seen": until, "baseline": True}
            continue
        if changed:
            r["update_note"] = "同一来源出现新的相关正文版本；这是内容变更，不代表新的监管决定。"
            r["event_date"], r["event_date_basis"] = None, "页面变更首次观察于 " + until + "；实际事件日期待确认"
        fresh.append(r)
    # Highest evidence level leads each cluster; all supporting links are retained.
    fresh.sort(key=lambda r: (-r["priority"], r.get("published_date") or "", r["url"]))
    groups = []
    for r in fresh:
        previous = next((e for e in events.values() if same_event(r, e["representative"]) and not r.get("update_note")), None)
        if previous:
            # Newly found coverage of an already-reported event augments its source list.
            previous["source_urls"] = sorted(set(previous["source_urls"] + [r["url"]]))
            docs[digest(r["url"])] = {"url": r["url"], "revisions": [r["fingerprint"]], "last_seen": until}
            skipped += 1
            continue
        group = next((g for g in groups if same_event(r, g["representative"]) and not r.get("update_note")), None)
        if group:
            group["sources"].append(r)
        else:
            groups.append({"id": digest(r["url"] + r["fingerprint"])[:20], "representative": r, "sources": [r]})
    return groups, review, skipped


def mark_emitted(groups: list[dict], state: dict, until: str):
    for g in groups:
        state["events"][g["id"]] = {"representative": public_record(g["representative"]),
                                   "source_urls": sorted({s["url"] for s in g["sources"]}), "reported_at": until}
        for r in g["sources"]:
            key = digest(r["url"])
            old = state["documents"].get(key, {})
            state["documents"][key] = {"url": r["url"], "revisions": sorted(set(old.get("revisions", []) + [r["fingerprint"]])), "last_seen": until}
