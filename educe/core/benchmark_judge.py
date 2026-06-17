"""
Benchmark Judge — 调用 Claude Opus 对 L3/主观维度评分

设计原则（Opus 4.8 讨论确认）：
- 结构化 JSON 输出（非自由文本）
- 给 anchor rubric（5/3/1 具体锚点）
- 盲评：不透露模型品牌
- 评产出只给最终文件；评决策必须给 trace
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import httpx


@dataclass
class JudgeScore:
    case_id: str
    dimension: str  # "completion"|"process"|"decision"|"output"
    score: float  # 0-5
    reason: str = ""
    model: str = ""  # which model produced the output (hidden from judge)


RUBRICS = {
    "completion": {
        "name": "完成度",
        "anchors": {
            5: "验收标准 100% 达成，结果准确无误",
            3: "主要目标达成但有小缺陷（格式瑕疵、细节遗漏）",
            1: "仅有雏形或方向正确但未实质完成",
            0: "完全未完成或方向错误",
        },
    },
    "process": {
        "name": "过程效率",
        "anchors": {
            5: "直达目标，无冗余操作，轮次最少",
            3: "有 1-2 次无效探索但最终完成",
            1: "大量重复/回退/无效操作，效率极低",
            0: "完全卡住未推进",
        },
    },
    "decision": {
        "name": "决策质量",
        "anchors": {
            5: "该问则问、该做则做，决策点判断精准",
            3: "大部分决策正确，有 1 处可改进",
            1: "重大误判（该 clarify 时直接动手，或不该问时反复追问）",
            0: "完全不恰当的决策（如对模糊指令盲目执行删除操作）",
        },
    },
    "output": {
        "name": "产出质量",
        "anchors": {
            5: "产出专业、结构清晰、代码规范/文档精炼",
            3: "产出可用但风格/结构有改进空间",
            1: "产出粗糙、有明显错误或不符合要求",
            0: "无有效产出",
        },
    },
}


def build_judge_prompt(
    case_id: str,
    instruction: str,
    dimension: str,
    output_text: str,
    trace_summary: str | None = None,
) -> str:
    """构建 judge 评分 prompt"""
    rubric = RUBRICS[dimension]
    anchors_text = "\n".join(f"  {score}分: {desc}" for score, desc in rubric["anchors"].items())

    prompt = f"""你是一个严格的 AI Agent 评分专家。请根据以下标准对 Agent 的表现打分。

## 任务
用户指令: "{instruction}"

## 评分维度: {rubric["name"]}
评分标准（0-5分）:
{anchors_text}

## Agent 产出
{output_text[:3000]}
"""

    if trace_summary and dimension in ("process", "decision"):
        prompt += f"""
## Agent 执行过程
{trace_summary[:2000]}
"""

    prompt += """
## 要求
- 只输出 JSON，格式: {"score": <0-5整数>, "reason": "<一句话理由>"}
- 评分要严格，不要给人情分
- 只看客观表现，不考虑模型品牌或能力预期
"""
    return prompt


async def judge_case(
    case_id: str,
    instruction: str,
    dimensions: list[str],
    output_text: str,
    trace_summary: str | None = None,
    api_key: str = "",
    base_url: str = "http://api.example.com/anthropic",
    model: str = "Claude-Opus-4.8",
) -> list[JudgeScore]:
    """对单个 case 的多个维度评分"""
    scores = []

    for dim in dimensions:
        prompt = build_judge_prompt(case_id, instruction, dim, output_text, trace_summary)

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{base_url}/v1/messages",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": model,
                        "max_tokens": 200,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                data = resp.json()

                if "content" in data:
                    text = data["content"][0]["text"].strip()
                    # Parse JSON from response
                    text = text.strip("`").strip()
                    if text.startswith("json"):
                        text = text[4:].strip()
                    parsed = json.loads(text)
                    scores.append(JudgeScore(
                        case_id=case_id,
                        dimension=dim,
                        score=float(parsed.get("score", 0)),
                        reason=parsed.get("reason", ""),
                    ))
                else:
                    error = data.get("error", {}).get("message", "unknown error")
                    scores.append(JudgeScore(
                        case_id=case_id, dimension=dim, score=-1,
                        reason=f"API error: {error}",
                    ))
        except Exception as e:
            scores.append(JudgeScore(
                case_id=case_id, dimension=dim, score=-1,
                reason=f"Exception: {str(e)[:100]}",
            ))

    return scores


def extract_output_for_judge(result: dict) -> str:
    """从 benchmark result 中提取 judge 需要看的产出文本"""
    import pathlib
    parts = []
    workspace = result.get("workspace", "")

    # Priority 1: Read actual files from workspace (build 产出)
    if workspace:
        ws_path = pathlib.Path(workspace)
        if ws_path.exists():
            for f in sorted(ws_path.rglob("*")):
                if f.is_file() and f.suffix in (".html", ".py", ".js", ".css", ".json", ".txt", ".md", ".csv"):
                    try:
                        content = f.read_text(errors="ignore")[:3000]
                        if content.strip():
                            parts.append(f"=== {f.name} ===\n{content}")
                    except Exception:
                        pass
                if len(parts) >= 5:
                    break

    # Priority 2: trace for full LLM output (if no workspace files)
    if not parts and workspace:
        log_dir = pathlib.Path(workspace).parent / "logs"
        for trace_file in log_dir.rglob("trace.jsonl"):
            try:
                for line in trace_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    if t.get("kind") == "llm_output":
                        payload = str(t.get("payload", ""))
                        if payload and len(payload) > 20:
                            parts.append(payload)
            except Exception:
                pass

    # Fallback: reply_preview
    if not parts:
        for evt in result.get("events", []):
            if evt.get("name") == "model_output":
                preview = evt.get("data", {}).get("reply_preview", "")
                if preview:
                    parts.append(preview)
    return "\n---\n".join(parts)[:6000] if parts else "(无产出)"


def extract_trace_for_judge(result: dict) -> str:
    """从 benchmark result 中提取过程摘要（给 process/decision 维度看）"""
    lines = []
    for evt in result.get("events", []):
        name = evt.get("name", "")
        if name in ("turn_start", "actions_parsed", "tool_result", "nudge_triggered",
                    "clarify_pause", "continuation", "safety_net", "turn_end"):
            lines.append(f"[{name}] {evt.get('summary', '')[:80]}")
    return "\n".join(lines) if lines else "(无过程记录)"
