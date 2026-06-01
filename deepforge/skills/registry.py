from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Skill(BaseModel):
    name: str
    description: str
    version: str = "1.0.0"
    author: str = "system"
    tags: list[str] = Field(default_factory=list)
    prompt_template: str = ""
    tools: list[str] = Field(default_factory=list)
    pipeline: list[str] = Field(default_factory=list)
    usage_count: int = 0
    success_rate: float = 0.0
    source: str = "builtin"  # builtin, user, community


class SkillRegistry:
    def __init__(self, skill_dir: str = ".deepforge/skills", community_dir: str = ".deepforge/community_skills"):
        self.skill_dir = Path(skill_dir)
        self.community_dir = Path(community_dir)
        self._skills: dict[str, Skill] = {}
        self._load_builtins()
        self._load_from_dir(self.skill_dir, "user")
        self._load_from_dir(self.community_dir, "community")

    def _load_builtins(self) -> None:
        builtins = [
            Skill(
                name="create_web_app",
                description="从零创建一个Web应用，包含前后端",
                tags=["web", "fullstack", "create"],
                pipeline=["project_manager", "product_manager", "architect", "engineer", "reviewer", "crowd_user"],
                prompt_template="用户想要创建一个Web应用：{description}",
            ),
            Skill(
                name="create_cli_tool",
                description="创建一个命令行工具",
                tags=["cli", "tool", "create"],
                pipeline=["project_manager", "architect", "engineer", "reviewer"],
                prompt_template="用户想要创建一个CLI工具：{description}",
            ),
            Skill(
                name="create_chrome_extension",
                description="创建一个Chrome浏览器扩展",
                tags=["chrome", "extension", "browser", "create"],
                pipeline=["project_manager", "product_manager", "architect", "engineer", "reviewer", "crowd_user"],
                prompt_template="用户想要创建一个Chrome扩展：{description}",
            ),
            Skill(
                name="fix_bug",
                description="分析并修复代码中的bug",
                tags=["debug", "fix", "bug"],
                pipeline=["project_manager", "engineer", "reviewer"],
                prompt_template="用户遇到了一个bug需要修复：{description}",
            ),
            Skill(
                name="code_review",
                description="对代码进行全面审查",
                tags=["review", "quality"],
                pipeline=["reviewer"],
                prompt_template="请审查以下代码：{description}",
            ),
        ]
        for skill in builtins:
            self._skills[skill.name] = skill

    def _load_from_dir(self, directory: Path, source: str) -> None:
        if not directory.exists():
            return
        # JSON格式skill
        for path in directory.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                skill = Skill.model_validate(data)
                skill.source = source
                self._skills[skill.name] = skill
            except Exception:
                pass
        # Markdown格式skill（Claude Code风格：目录/skill.md）
        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "skill.md"
            if not skill_md.exists():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                meta, body = self._parse_skill_md(content)
                if meta.get("name"):
                    skill = Skill(
                        name=meta["name"],
                        description=meta.get("description", ""),
                        tags=meta.get("tags", []),
                        prompt_template=body,
                        source=source,
                    )
                    self._skills[skill.name] = skill
            except Exception:
                pass

    def _parse_skill_md(self, content: str) -> tuple:
        """解析markdown skill的frontmatter和正文"""
        import re
        match = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
        if not match:
            return {}, content
        frontmatter = match.group(1)
        body = match.group(2).strip()
        meta = {}
        for line in frontmatter.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, body

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def search(self, query: str) -> list[Skill]:
        query_lower = query.lower()
        results = []
        for skill in self._skills.values():
            score = 0
            if query_lower in skill.name.lower():
                score += 3
            if query_lower in skill.description.lower():
                score += 2
            if any(query_lower in tag for tag in skill.tags):
                score += 1
            if score > 0:
                results.append((score, skill))
        results.sort(key=lambda x: (-x[0], -x[1].usage_count))
        return [s for _, s in results]

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def save_skill(self, skill: Skill, directory: Path | None = None) -> None:
        directory = directory or self.skill_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{skill.name}.json"
        with open(path, "w") as f:
            json.dump(skill.model_dump(), f, ensure_ascii=False, indent=2)
        self._skills[skill.name] = skill
