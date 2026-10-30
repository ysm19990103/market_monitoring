from __future__ import annotations

import csv
from pathlib import Path

from .common import compact, write_json
from .events import CATEGORIES, public_record


def md(value) -> str:
    text = compact(str(value or ""))
    for token in "\\`*_{}[]<>|":
        text = text.replace(token, "\\" + token)
    return text


def safe_csv(value):
    text = str(value or "")
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def export_groups(groups):
    return [{"id": g["id"], "event": public_record(g["representative"]), "analysis": g["analysis"],
             "sources": [public_record(s) for s in g["sources"]]} for g in groups]


def render(groups: list[dict], health: list[dict], review: list[dict], metadata: dict) -> str:
    labels = dict((k, label) for k, label, _ in CATEGORIES)
    out = ["# 全球肠促胰素药物重要进展", "",
           f"生成时间：{metadata['generated_at']}（Asia/Shanghai）",
           f"检索窗口：{metadata['since']} 至 {metadata['until']}；新事件/实质更新 {len(groups)} 条；抑制重复 {metadata['duplicates']} 条。", "",
           "重点为礼来、诺和诺德已上市产品；其他药物仅作竞争背景。不同司法辖区、品牌、剂型和适应证分别判断。", "",
           "**阅读规则：**“来源记载”反映监管文件、公司披露或研究报告中的内容；公司声明和观察性关联不自动成为独立证实的事实。"
           "三个影响维度均为待验证的分析，不能与事实混读。规则模式保留原文短摘录，模型模式提供中文归纳；两者均需复核。", ""]
    if metadata.get("analysis_note"):
        out += [md(metadata["analysis_note"]), ""]
    if not groups:
        out += ["本次可访问来源中未检出符合筛选阈值且尚未报道的事件。来源失败、有限订阅窗口及未核实日期仍可能造成遗漏。", ""]
    for i, g in enumerate(groups, 1):
        r, a = g["representative"], g["analysis"]
        heading = a.get("title_zh") or r["title"]
        out += [f"## {i}. {md(heading)}", "",
                f"类别：{' / '.join(labels.get(c,c) for c in r['categories'])}；分析模式：{'模型辅助，待复核' if a['mode']=='llm' else '规则模板，待复核'}；优先分：{r['priority']}。", "",
                "| 字段 | 信息 |", "|---|---|",
                f"| 事件日期 | {md(a.get('event_date') or r.get('event_date') or '未核实')} |",
                f"| 日期依据 | {md(a.get('event_date_evidence') or r['event_date_basis'])} |",
                f"| 公告/发表日期 | {md(r.get('published_date') or '未核实')} |",
                f"| 页面修改日期 | {md(r.get('modified_date') or '未报告')} |",
                f"| 原文提及地区/来源辖区 | {md(r['jurisdiction'])} |",
                f"| 成分 | {md(' / '.join(r['molecules']) or '类别政策')} |",
                f"| 原文提及品牌 | {md(' / '.join(r['brands']) or '未明确；不按成分自动外推品牌')} |",
                f"| 阶段标识 | {md(r['stage'])} |",
                f"| 证据范围 | {md(r.get('body_status'))} |", "", "**来源记载 / 核心信息**", ""]
        for f in a["facts"]:
            out += [f"- {md(f['claim'])} [{md(f['source_id'])}]",
                    f"  - 核对摘录：{md(f['evidence'])}"]
        out += ["", "**潜在影响（推断，尚待验证）**", "",
                f"- 产品竞争力：{md(a['impacts']['competitiveness'])}",
                f"- 临床应用：{md(a['impacts']['clinical_use'])}",
                f"- 未来市场：{md(a['impacts']['future_market'])}", ""]
        if r.get("update_note"):
            out += ["更新说明：" + md(r["update_note"]), ""]
        for x in a.get("uncertainties", []):
            out.append("待核实：" + md(x))
        out += ["", "来源：", ""]
        for j, s in enumerate(g["sources"], 1):
            out.append(f"- S{j} [{md(s['source_name'])}]({s['url']})；发布日期 {s.get('published_date') or '未核实'}；{s['source_type']}。")
            if s.get("doi"):
                out.append(f"  DOI：[{'doi:' + s['doi']}](https://doi.org/{s['doi']})")
        out.append("")
    out += ["## 来源覆盖与缺口", "", "覆盖的是以下指定官方入口与文献索引，不代表全球所有监管机构或全部历史公告均已检索。", "",
            "| 来源 | 地区 | 状态 | 相关条数 |", "|---|---|---|---|"]
    for h in health:
        out.append(f"| [{md(h['name'])}]({h['url']}) | {md(h['region'])} | {md(h['status'])} | {h['accepted']} |")
    out.append("")
    for h in health:
        if h.get("error"):
            out.append(f"- {md(h['name'])}：{md(h['error'])}")
        for w in h.get("warnings", []):
            out.append(f"- {md(h['name'])}：{md(w)}")
    if review:
        out += ["", "## 未进入新闻结论的待核实记录", ""]
        for r in review:
            out.append(f"- [{md(r['title'])}]({r['url']})：{md(r['reason'])}")
    out += ["", "方法：按来源白名单采集，以持久化URL/相关正文版本、DOI及保守事件相似度去重。"
            "同试验的新随访、不同剂型、人群、地区、阶段或数值差异不强行合并。"
            "未进行人工确认的机器分组仍可能漏合并或误合并。", ""]
    return "\n".join(out)


def write_reports(base: Path, run_id: str, groups, health, review, metadata):
    base.mkdir(parents=True, exist_ok=True)
    markdown = render(groups, health, review, metadata)
    archive = base / metadata["until"]
    archive.mkdir(parents=True, exist_ok=True)
    for path in [archive / (run_id + ".md"), base / "latest.md"]:
        path.write_text(markdown, encoding="utf-8")
    payload = {"metadata": metadata, "events": export_groups(groups), "coverage": health, "review_queue": review}
    for path in [archive / (run_id + ".json"), base / "latest.json"]:
        write_json(path, payload)
    write_json(base / "coverage.json", health)
    columns = ["id", "event_date", "published_date", "title", "jurisdiction", "molecules", "brands", "stage", "source_urls", "analysis_mode", "competitiveness", "clinical_use", "future_market"]
    for path in [archive / (run_id + ".csv"), base / "latest.csv"]:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for g in groups:
                r, a = g["representative"], g["analysis"]
                values = {"id": g["id"], "event_date": a.get("event_date") or r.get("event_date"),
                          "published_date": r.get("published_date"), "title": a.get("title_zh") or r["title"],
                          "jurisdiction": r["jurisdiction"], "molecules": ";".join(r["molecules"]),
                          "brands": ";".join(r["brands"]), "stage": r["stage"],
                          "source_urls": ";".join(s["url"] for s in g["sources"]), "analysis_mode": a["mode"], **a["impacts"]}
                writer.writerow({k: safe_csv(v) for k, v in values.items()})
