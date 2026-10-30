from __future__ import annotations

import argparse
import fcntl
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .analyze import analyze
from .collect import collect
from .common import load_json, write_json
from .events import mark_emitted, stage_events
from .http import Client
from .report import write_reports


def main(argv=None):
    p = argparse.ArgumentParser(description="Primary-source incretin market intelligence")
    p.add_argument("--config", type=Path, default=Path("config.json"))
    p.add_argument("--state", type=Path, default=Path("state/state.json"))
    p.add_argument("--output", type=Path, default=Path("reports"))
    p.add_argument("--cache", type=Path, default=Path(".cache/http"))
    p.add_argument("--lookback-days", type=int, default=None)
    p.add_argument("--as-of", type=date.fromisoformat, help="ISO date; defaults to Asia/Shanghai today")
    p.add_argument("--sources", help="comma-separated configured source IDs")
    p.add_argument("--analysis", choices=["auto", "rules", "llm"], default="auto")
    p.add_argument("--strict-coverage", action="store_true", help="nonzero exit on any partial/failed source")
    args = p.parse_args(argv)
    config = load_json(args.config, None)
    if not config or config.get("config_version") != 1:
        p.error("missing or unsupported config")
    days = args.lookback_days or config["lookback_days"]
    if args.lookback_days is not None and not 1 <= args.lookback_days <= 366:
        p.error("lookback-days must be between 1 and 366")
    now = datetime.now(ZoneInfo(config["timezone"]))
    until = args.as_of or now.date()
    since = until - timedelta(days=days-1)
    selected = set(args.sources.split(",")) if args.sources else None
    if selected and selected - {s["id"] for s in config["sources"]}:
        p.error("unknown source ID")
    key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if args.analysis == "llm" and not (key and model):
        p.error("llm mode requires OPENAI_API_KEY and OPENAI_MODEL; use rules for no-key mode")
    args.state.parent.mkdir(parents=True, exist_ok=True)
    # Lock is outside committed state. GitHub also serializes the entire job.
    args.cache.mkdir(parents=True, exist_ok=True)
    with (args.cache / "run.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            p.error("another run is active in this workspace")
        state = load_json(args.state, {"schema_version": 1, "documents": {}, "events": {}})
        client = Client(args.cache, config["allowed_domains"])
        rows, health = collect(config, client, since.isoformat(), until.isoformat(), selected)
        # Local diagnostics only; .cache/ is ignored by git and never included in artifacts.
        write_json(args.cache / "last-records.json", rows)
        if all(h["status"] == "failed" for h in health):
            write_json(args.output / "coverage.json", health)
            print("All sources failed; no report or deduplication state advanced.", flush=True)
            return 2
        groups, review, skipped = stage_events(rows, config, state, since.isoformat(), until.isoformat())
        # Do not acknowledge lower priority events as reported: future runs may promote them.
        groups = [g for g in groups if g["representative"]["priority"] >= config["min_priority"]]
        warnings, used = [], 0
        for g in groups:
            mode = args.analysis if used < config["max_model_events"] else "rules"
            analysis, warning = analyze(g, mode, model, key)
            g["analysis"] = analysis
            if mode != "rules" and key and model:
                used += 1
            if warning:
                warnings.append(warning)
        note = ""
        if not (key and model) or args.analysis == "rules":
            note = "本次使用无密钥规则模式：核心信息保留原文摘录，三维影响为条件性模板；尚未启用模型逐项中文综合。"
        if warnings:
            note += f" {len(warnings)} 条模型分析失败或未通过证据检查，已标注为规则模式。"
        metadata = {"generated_at": now.isoformat(timespec="seconds"), "since": since.isoformat(), "until": until.isoformat(),
                    "duplicates": skipped, "analysis_note": note, "model_calls": used,
                    "coverage_complete": False, "scope": "configured official sources and indexed primary literature"}
        run_id = now.strftime("%H%M%S-%f")
        write_reports(args.output, run_id, groups, health, review, metadata)
        # A report must be successfully written before new records are marked emitted.
        mark_emitted(groups, state, until.isoformat())
        state["last_successful_run"] = now.isoformat(timespec="seconds")
        write_json(args.state, state)
        print(f"Wrote {len(groups)} events; {skipped} duplicates; {len(review)} pending review -> {args.output / 'latest.md'}", flush=True)
        failed = [h for h in health if h["status"] == "failed"]
        if failed:
            print("Coverage gaps: " + ", ".join(h["id"] for h in failed), flush=True)
        return 3 if args.strict_coverage and any(h["status"] != "ok" for h in health) else 0


if __name__ == "__main__":
    raise SystemExit(main())
