"""
DeepForge 领域知识引擎
傻瓜式操作：用户丢任何文件进来，自动消化为结构化知识

流程：任意文件 → 文本提取(file_handler) → LLM解构(概念/关系/推理链/误区) → 编译到知识图谱 → 问答时按命中注入
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

from educe.core.knowledge import LayeredCache


@dataclass
class Concept:
    name: str
    definition: str
    boundary: str = ""
    related: list[str] = field(default_factory=list)


@dataclass
class ReasoningChain:
    domain: str
    name: str
    steps: list[str] = field(default_factory=list)


@dataclass
class Pitfall:
    claim: str
    correction: str


@dataclass
class DomainKnowledge:
    domain: str
    source: str
    concepts: list[Concept] = field(default_factory=list)
    chains: list[ReasoningChain] = field(default_factory=list)
    pitfalls: list[Pitfall] = field(default_factory=list)
    raw_text: str = ""
    created_at: float = 0

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "source": self.source,
            "concepts": [{"name": c.name, "definition": c.definition, "boundary": c.boundary, "related": c.related} for c in self.concepts],
            "chains": [{"domain": c.domain, "name": c.name, "steps": c.steps} for c in self.chains],
            "pitfalls": [{"claim": p.claim, "correction": p.correction} for p in self.pitfalls],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DomainKnowledge:
        return cls(
            domain=d.get("domain", ""),
            source=d.get("source", ""),
            concepts=[Concept(**c) for c in d.get("concepts", [])],
            chains=[ReasoningChain(**c) for c in d.get("chains", [])],
            pitfalls=[Pitfall(**p) for p in d.get("pitfalls", [])],
            raw_text=d.get("raw_text", ""),
            created_at=d.get("created_at", 0),
        )


DIGEST_PROMPT = """你是知识解构专家。请分析以下文本，提取结构化知识。

## 文本内容
{text}

## 要求
从文本中提取：
1. **核心概念**（3-10个）：每个概念包含名称、定义、边界（什么不属于这个概念）
2. **推理链**（1-3个）：这个领域解决问题的典型思路步骤
3. **常见误区**（1-5个）：容易犯的错误，以及正确说法

## 输出格式（严格JSON）
```json
{{
  "domain": "这段知识属于什么领域",
  "concepts": [
    {{"name": "概念名", "definition": "一句话定义", "boundary": "什么不算这个概念", "related": ["相关概念1"]}}
  ],
  "chains": [
    {{"domain": "领域", "name": "推理链名称", "steps": ["第1步：...", "第2步：...", "第3步：..."]}}
  ],
  "pitfalls": [
    {{"claim": "错误说法", "correction": "正确说法"}}
  ]
}}
```

只输出JSON。"""


class DomainEngine:
    """领域知识引擎——消化任意文件为结构化知识"""

    def __init__(self, storage_dir: str = ".educe/domains", knowledge: LayeredCache | None = None):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.domains: dict[str, DomainKnowledge] = {}
        self.knowledge = knowledge or LayeredCache()
        self._load()

    def _load(self):
        for path in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                dk = DomainKnowledge.from_dict(data)
                self.domains[dk.domain] = dk
            except Exception:
                pass

    def _save(self, dk: DomainKnowledge):
        safe_name = dk.domain.replace("/", "_").replace(" ", "_")[:50]
        path = self.storage_dir / f"{safe_name}.json"
        path.write_text(json.dumps(dk.to_dict(), ensure_ascii=False, indent=2))

    async def digest(self, text: str, source_name: str, model_client: Any,
                     model: str, max_tokens: int = 4096) -> DomainKnowledge:
        """消化任意文本为结构化知识——核心方法"""
        truncated = text[:30000]

        prompt = DIGEST_PROMPT.format(text=truncated)
        result = await model_client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            temperature=0.1,
        )

        dk = self._parse_digest(result, source_name, text)

        domain_key = dk.domain
        if domain_key in self.domains and self.domains[domain_key].source != source_name:
            domain_key = f"{dk.domain}({source_name})"
            dk.domain = domain_key

        self.domains[domain_key] = dk
        self._save(dk)
        self._compile_to_knowledge(dk)

        return dk

    def _parse_digest(self, result: str, source: str, raw_text: str) -> DomainKnowledge:
        """解析LLM输出的JSON"""
        import re
        json_match = re.search(r'```json\s*([\s\S]*?)```', result)
        json_str = json_match.group(1) if json_match else result

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            json_match2 = re.search(r'\{[\s\S]*"domain"[\s\S]*\}', result)
            if json_match2:
                try:
                    data = json.loads(json_match2.group(0))
                except json.JSONDecodeError:
                    data = {"domain": "通用", "concepts": [], "chains": [], "pitfalls": []}
            else:
                data = {"domain": "通用", "concepts": [], "chains": [], "pitfalls": []}

        dk = DomainKnowledge(
            domain=data.get("domain", "通用"),
            source=source,
            concepts=[Concept(**c) for c in data.get("concepts", [])],
            chains=[ReasoningChain(**c) for c in data.get("chains", [])],
            pitfalls=[Pitfall(**p) for p in data.get("pitfalls", [])],
            raw_text=raw_text[:5000],
            created_at=time.time(),
        )
        return dk

    def _compile_to_knowledge(self, dk: DomainKnowledge):
        """编译结构化知识到LayeredCache"""
        for concept in dk.concepts:
            triggers = self.knowledge._tokenize(concept.name + " " + concept.definition)
            self.knowledge.add(
                f"[{dk.domain}] {concept.name}：{concept.definition}" +
                (f"（注意：{concept.boundary}）" if concept.boundary else ""),
                triggers, "domain_concept"
            )

        for chain in dk.chains:
            triggers = self.knowledge._tokenize(chain.name + " " + dk.domain)
            steps = " → ".join(chain.steps)
            self.knowledge.add(
                f"[{dk.domain}推理] {chain.name}：{steps}",
                triggers, "domain_chain"
            )

        for pitfall in dk.pitfalls:
            triggers = self.knowledge._tokenize(pitfall.claim)
            self.knowledge.add(
                f"[{dk.domain}误区] ❌{pitfall.claim} → ✅{pitfall.correction}",
                triggers, "domain_pitfall"
            )

    def match_domain(self, query: str) -> str | None:
        """检测用户问题属于哪个已有领域"""
        if not self.domains:
            return None

        query_tokens = self.knowledge._tokenize(query)
        best_domain = None
        best_score = 0

        for domain_name, dk in self.domains.items():
            score = 0
            for concept in dk.concepts:
                concept_tokens = self.knowledge._tokenize(concept.name)
                overlap = len(query_tokens & concept_tokens)
                if overlap > 0:
                    score += overlap

            if score > best_score:
                best_score = score
                best_domain = domain_name

        return best_domain if best_score >= 2 else None

    def inject_knowledge(self, query: str, domain: str | None = None) -> str:
        """按命中注入领域知识到prompt——明确匹配领域时格式化注入"""
        if domain and domain in self.domains:
            dk = self.domains[domain]
            return self._format_domain(dk, query)

        return ""

    def recall_candidates(self, query: str, max_results: int = 5) -> list[str]:
        """召回候选知识（不过滤），由上层决定是否注入"""
        return self.knowledge.recall(query, max_results=max_results)

    def _format_domain(self, dk: DomainKnowledge, query: str) -> str:
        """格式化领域知识为prompt注入段"""
        sections = [f"\n## 领域知识（{dk.domain}）"]

        if dk.concepts:
            sections.append("### 核心概念")
            for c in dk.concepts[:5]:
                s = f"- **{c.name}**：{c.definition}"
                if c.boundary:
                    s += f"（注意：{c.boundary}）"
                sections.append(s)

        query_tokens = self.knowledge._tokenize(query)
        for chain in dk.chains:
            chain_tokens = self.knowledge._tokenize(chain.name + " " + chain.domain)
            if query_tokens & chain_tokens:
                sections.append(f"### 推理方法：{chain.name}")
                for i, step in enumerate(chain.steps, 1):
                    sections.append(f"{i}. {step}")
                break

        if dk.pitfalls:
            sections.append("### 注意避免")
            for p in dk.pitfalls[:3]:
                sections.append(f"- ❌ {p.claim} → ✅ {p.correction}")

        return "\n".join(sections)

    def list_domains(self) -> list[dict]:
        """列出所有已消化的领域"""
        return [
            {
                "domain": dk.domain,
                "source": dk.source,
                "concepts": len(dk.concepts),
                "chains": len(dk.chains),
                "pitfalls": len(dk.pitfalls),
                "created_at": dk.created_at,
            }
            for dk in self.domains.values()
        ]
