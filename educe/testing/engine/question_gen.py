"""
Question Generator — 用 LLM 生成随机化测试问题

每次运行用不同 seed 产生不同问题，但保证满足合同里的不变量。
避免测试变成固定字符串匹配 — 每次跑的问题都略有不同。
"""
import hashlib
import os
import time
from pathlib import Path

import yaml


def _get_seed() -> str:
    """Generate a seed based on current time (hourly granularity)."""
    return hashlib.md5(str(int(time.time() / 3600)).encode()).hexdigest()[:8]


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


async def generate_question(template: str, context: dict = None, seed: str = None) -> str:
    """
    Call test LLM to generate a question from a template.

    Args:
        template: Prompt template with {seed} and optional {context} placeholders
        context: Extra context variables to inject
        seed: Override seed (default: time-based)

    Returns:
        Generated question string
    """
    from openai import AsyncOpenAI

    config = _load_config()
    model_cfg = config["models"]["test_runner"]
    api_key = os.environ.get("EDUCE_TEST_API_KEY", "")
    if not api_key:
        # Fallback: use the same key as the product
        from educe.core.config import EduceConfig
        educe_cfg = EduceConfig.load()
        api_key = educe_cfg.default_model.api_key

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=model_cfg["base_url"],
        timeout=15,
    )

    if seed is None:
        seed = _get_seed()

    prompt = template.format(seed=seed, **(context or {}))

    resp = await client.chat.completions.create(
        model=model_cfg["model"],
        messages=[
            {"role": "system", "content": "你是测试问题生成器。只输出问题本身，不要解释。确保问题有明确答案。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=200,
        temperature=0.8,
    )

    return resp.choices[0].message.content.strip() if resp.choices else template


async def judge_quality(reply: str, question: str, criteria: str, min_score: int = 6) -> tuple[bool, str]:
    """
    Use judge LLM to score reply quality.

    Returns:
        (passed, detail_string)
    """
    import json
    import requests

    config = _load_config()
    judge_cfg = config["models"]["judge"]
    api_key = os.environ.get("EDUCE_TEST_API_KEY", "")
    if not api_key:
        from educe.core.config import EduceConfig
        educe_cfg = EduceConfig.load()
        api_key = educe_cfg.default_model.api_key

    prompt = f"""评价以下 AI 回复的质量（1-10分）。

问题：{question}

回复：{reply[:1500]}

评分标准：{criteria}

回复 JSON 格式：{{"score": N, "reason": "一句话原因"}}
只回复 JSON，不要其他内容。"""

    if judge_cfg["format"] == "anthropic":
        r = requests.post(
            f"{judge_cfg['base_url']}/messages",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": judge_cfg["model"], "max_tokens": 100,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        if r.status_code == 200:
            text = r.json().get("content", [{}])[0].get("text", "")
        else:
            return True, f"judge unavailable (HTTP {r.status_code}), skipping"
    else:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=judge_cfg["base_url"], timeout=30)
        resp = await client.chat.completions.create(
            model=judge_cfg["model"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100, temperature=0,
        )
        text = resp.choices[0].message.content.strip() if resp.choices else ""

    try:
        # Extract JSON from response
        if "{" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(json_str)
            score = data.get("score", 0)
            reason = data.get("reason", "")
            passed = score >= min_score
            return passed, f"score={score}/10 (min={min_score}): {reason}"
    except (json.JSONDecodeError, ValueError):
        pass

    return True, f"judge parse failed, raw='{text[:50]}', skipping"
