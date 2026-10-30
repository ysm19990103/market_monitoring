from __future__ import annotations

import re

from .common import clip_words


IMPACTS = {
    "approval": (
        "如果最终许可扩大了适用人群或适应证，该产品可能增加差异化竞争优势；仅有受理或审评意见时尚不能作此结论。",
        "临床应用须核对本地区最终标签、剂型、剂量和目标人群；一种品牌或剂型的获批不能外推给同成分其他产品。",
        "未来份额取决于上市时间、支付覆盖、供应与竞品证据；批准本身不能确定收入增幅。"),
    "launch": (
        "当地实际可及性可能改善产品竞争力，需核实供货范围及持续性。",
        "应区分已可处方、开始发货和广泛药房供应，并核对本地区标签。",
        "销量转化仍取决于支付、价格、患者持续治疗及竞争对手渠道。"),
    "safety": (
        "如果信号被后续审评证实并导致标签调整，可能影响风险获益定位；自发报告数量不能直接比较产品安全性。",
        "信号、统计关联和因果关系不同；没有暴露分母时不能计算发生率，临床行动应核对监管建议。",
        "市场影响需等待因果评估、绝对风险、标签与真实处方变化验证。"),
    "clinical": (
        "新增证据可能改变疗效或结局差异化；跨试验百分比不能替代随机头对头比较。",
        "需核对研究人群、对照、主要终点、效应量和置信区间、随访及estimand；事后分析仅提供探索性证据。",
        "转化为未来市场优势还需要适应证、指南、支付及可及性支持，不能把研究结果当作监管许可。"),
    "regulatory": (
        "政策可能改变准入、供应或合规成本，影响方向取决于司法辖区、适用主体和生效条款。",
        "核对规则是否为提案、正式决定或执行宽限，以及是否改变处方、配制或支付资格。",
        "竞争影响需观察执行力度、患者支付变化及供给替代，不能直接据此预测份额。"),
    "competition": (
        "价格、供应、产能或财务披露可能改变可及性及商业竞争力；自费价、标价和实际净价应分开。",
        "临床价值仍需疗效、安全性和适用人群证据，销售额不能替代临床优越性。",
        "比较份额须统一地区、期间和分母；未来走势需处方量、净价、供货和持续治疗数据验证。")}


def rules(group: dict) -> dict:
    r = group["representative"]
    primary = next((x for x in ["safety", "regulatory", "approval", "launch", "clinical", "competition"] if x in r["categories"]), "competition")
    # A paper's body can mention safety as background: favor the actual headline topic.
    if r["source_type"] == "research" and "safety" not in r["title"].lower():
        primary = "clinical"
    certainty = {"regulator": "监管机构公布的信息", "company": "公司披露；不等同于独立验证", "research": "原始研究摘要报告；需结合研究设计解读"}[r["source_type"]]
    impacts = dict(zip(["competitiveness", "clinical_use", "future_market"], IMPACTS[primary]))
    targets = "、".join(r["brands"] or r["molecules"]) or "肠促胰素药物类别"
    impacts["competitiveness"] = f"本条涉及{targets}。" + impacts["competitiveness"]
    if r["stage"] == "positive_opinion":
        impacts["clinical_use"] = "本次为审评积极意见，尚不能据此按最终批准适应证开展临床应用；需核对欧盟委员会决定及最终标签。"
    elif r["stage"] == "conference_preview":
        impacts["clinical_use"] = "本次为会议预告，应等待实际披露、完整结果和研究方法，不依据预告改变临床结论。"
    elif r["stage"] == "financial_report":
        impacts["competitiveness"] = f"本次财务披露涉及{targets}。需按相同季度和地区分解销量、净价和汇率贡献，再判断份额或价格竞争变化。"
    if re.search(r"post.hoc|事后", r["title"], re.I):
        impacts["clinical_use"] = "本条为事后分析，亚组结果具有探索性；需核对交互作用检验及预设分析方案，不能直接认定该亚组优于总体。"
    return {"mode": "rules", "title_zh": "", "facts": [{"claim": certainty, "source_id": "S1", "evidence": clip_words(r["excerpt_candidate"])}],
            "impacts": impacts,
            "uncertainties": ["以下为按事件类别生成的条件性分析，不是对未来结果的验证。"],
            "event_date": r.get("event_date"), "event_date_evidence": "", "needs_review": True}
