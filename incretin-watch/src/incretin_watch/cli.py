from __future__ import annotations

import argparse
import fcntl
import json
from importlib.resources import files
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .analyze import rules
from .collect import collect
from .common import load_json, write_json
from .events import mark_emitted, stage_events
from .http import Client
from .report import write_reports


def main(argv=None):
    p = argparse.ArgumentParser(description="Primary-source incretin market intelligence")
    p.add_argument("--config", type=Path, help="configuration path; defaults to local config.json or bundled public sources")
    p.add_argument("--state", type=Path, default=Path("state/state.json"))
    p.add_argument("--output", type=Path, default=Path("reports"))
    p.add_argument("--cache", type=Path, default=Path(".cache/http"))
    p.add_argument("--lookback-days", type=int, default=None)
    p.add_argument("--as-of", type=date.fromisoformat, help="ISO date; defaults to Asia/Shanghai today")
    p.add_argument("--sources", help="comma-separated configured source IDs")
    p.add_argument("--analysis", choices=["rules"], default="rules", help="local rule-based analysis")
    p.add_argument("--strict-coverage", action="store_true", help="nonzero exit on any partial/failed source")
    p.add_argument("--check-sources", action="store_true", help="write source health only; never read or advance deduplication state")
    args = p.parse_args(argv)
    config_path = args.config or (Path("config.json") if Path("config.json").exists() else None)
    config = load_json(config_path, None) if config_path else json.loads(files("incretin_watch").joinpath("default_config.json").read_text(encoding="utf-8"))
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
    # Lock is outside committed state. GitHub also serializes the entire job.
    args.cache.mkdir(parents=True, exist_ok=True)
    with (args.cache / "run.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            p.error("another run is active in this workspace")
        state = None if args.check_sources else load_json(args.state, {"schema_version": 1, "documents": {}, "events": {}})
        client = Client(args.cache, config["allowed_domains"])
        rows, health = collect(config, client, since.isoformat(), until.isoformat(), selected)
        if args.check_sources:
            write_json(args.output / "coverage.json", health)
            write_json(args.output / "coverage-run.json", {"checked_at": now.isoformat(timespec="seconds"),
                       "since": since.isoformat(), "until": until.isoformat(), "mode": "check-sources"})
            print("Source check complete; deduplication state and reports were not advanced.", flush=True)
            if all(h["status"] == "failed" for h in health):
                return 2
            return 3 if args.strict_coverage and any(h["status"] != "ok" for h in health) else 0
        # Local diagnostics only; .cache/ is ignored by git and never included in artifacts.
        write_json(args.cache / "last-records.json", rows)
        if all(h["status"] == "failed" for h in health):
            write_json(args.output / "coverage.json", health)
            print("All sources failed; no report or deduplication state advanced.", flush=True)
            return 2
        groups, review, skipped = stage_events(rows, config, state, since.isoformat(), until.isoformat())
        # Do not acknowledge lower priority events as reported: future runs may promote them.
        groups = [g for g in groups if g["representative"]["priority"] >= config["min_priority"]]
        for g in groups:
            g["analysis"] = rules(g)
        note = "本次使用本地规则分析：核心信息保留原文摘录，三维影响为条件性模板，仍需人工复核。"
        metadata = {"generated_at": now.isoformat(timespec="seconds"), "since": since.isoformat(), "until": until.isoformat(),
                    "duplicates": skipped, "analysis_note": note,
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
