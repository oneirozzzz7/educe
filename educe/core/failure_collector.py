"""
失败采集器 — 从 session logs 中提取 parse/execute 失败样本，生成 fixture。

用途：自动积累 normalizer 回归测试集，日志反哺治理层的第一个闭环。
原则：只采集失败，不碰成功（"只补漏不增益"）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import logging

log = logging.getLogger("educe.core.failure_collector")


def collect_failures(logs_dir: Path, output_dir: Path | None = None) -> list[dict]:
    """扫描所有 session 的 events.jsonl，提取 tool_result 失败样本。

    每个样本关联上一条 llm_output trace（原始模型输出），用于回放验证。
    """
    output_dir = output_dir or Path("tests/fixtures/failures")
    output_dir.mkdir(parents=True, exist_ok=True)

    failures = []

    for session_dir in logs_dir.rglob("events.jsonl"):
        events = []
        try:
            for line in session_dir.read_text().strip().split("\n"):
                if line.strip():
                    events.append(json.loads(line))
        except Exception as e:
            log.debug("suppressed: %s", e)
            continue

        # Find trace file for this session
        trace_file = session_dir.parent / "trace.jsonl"
        traces = []
        if trace_file.exists():
            try:
                for line in trace_file.read_text().strip().split("\n"):
                    if line.strip():
                        traces.append(json.loads(line))
            except Exception as e:
                log.debug("suppressed: %s", e)

        # Build trace index: trace_id → payload
        trace_index = {t["trace_id"]: t for t in traces if "trace_id" in t}

        # Scan for failures
        last_llm_output = ""
        for evt in events:
            # Track last LLM output
            if evt.get("name") == "llm_response" and evt.get("trace_id"):
                trace = trace_index.get(evt["trace_id"])
                if trace and trace.get("kind") == "llm_output":
                    last_llm_output = str(trace.get("payload", ""))

            # Capture failures
            if evt.get("type") == "tool_call" and evt.get("status") == "error":
                action_type = evt.get("data", {}).get("action_type", "")
                failure = {
                    "event_name": evt.get("name", ""),
                    "action_type": action_type,
                    "summary": evt.get("summary", ""),
                    "llm_output": last_llm_output[:2000] if last_llm_output else "",
                    "session_dir": str(session_dir.parent),
                }

                # Generate stable hash for dedup
                content_key = f"{action_type}:{last_llm_output[:500]}"
                failure["hash"] = hashlib.md5(content_key.encode()).hexdigest()[:12]

                failures.append(failure)

    # Deduplicate by hash
    seen = set()
    unique = []
    for f in failures:
        if f["hash"] not in seen:
            seen.add(f["hash"])
            unique.append(f)

    # Write fixtures
    for f in unique:
        fixture_path = output_dir / f"{f['hash']}.json"
        fixture_path.write_text(json.dumps(f, ensure_ascii=False, indent=2))

    return unique


def replay_fixtures(fixtures_dir: Path) -> dict[str, Any]:
    """回放所有 failure fixtures，检查 parse_actions 是否仍然失败。

    返回 {total, still_failing, fixed, new_failures}
    """
    from educe.core.action_executor import parse_actions

    results = {"total": 0, "still_failing": 0, "fixed": 0, "details": []}

    for fixture_path in sorted(fixtures_dir.glob("*.json")):
        try:
            f = json.loads(fixture_path.read_text())
        except Exception as e:
            log.debug("suppressed: %s", e)
            continue

        llm_output = f.get("llm_output", "")
        if not llm_output:
            continue

        results["total"] += 1
        _, actions = parse_actions(llm_output)

        # A fixture is "fixed" if parse_actions now produces a valid action
        if actions:
            results["fixed"] += 1
            results["details"].append({"hash": f["hash"], "status": "fixed", "type": actions[0].type})
        else:
            results["still_failing"] += 1
            results["details"].append({"hash": f["hash"], "status": "still_failing", "action_type": f.get("action_type", "")})

    return results


if __name__ == "__main__":
    import sys
    logs_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".educe/logs")
    print(f"Scanning {logs_dir}...")
    failures = collect_failures(logs_dir)
    print(f"Collected {len(failures)} unique failures")

    if failures:
        print("\nReplay results:")
        results = replay_fixtures(Path("tests/fixtures/failures"))
        print(f"  Total: {results['total']}")
        print(f"  Fixed: {results['fixed']}")
        print(f"  Still failing: {results['still_failing']}")
