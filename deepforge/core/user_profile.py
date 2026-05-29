"""
DeepForge UserProfile
从使用行为中隐式构建用户画像——用户完全无感知。

画像影响激发策略：
- 程序员用户 → 技术回答更深入，给代码示例
- 学生用户 → 解释更通俗，给学习建议
- 高频用户 → 回答更简洁（已熟悉框架风格）
- 新用户 → 回答更详细，带引导
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from collections import Counter


PROFILE_DIR = Path(".deepforge/profiles")


class UserProfile:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._domains: list = []
        self._question_lengths: list = []
        self._signals: list = []
        self._turn_count = 0
        self._code_requests = 0
        self._text_requests = 0
        self._start_time = time.time()

    @property
    def primary_domains(self) -> list:
        if not self._domains:
            return []
        counter = Counter(self._domains)
        return [d for d, _ in counter.most_common(3)]

    @property
    def expertise_level(self) -> str:
        avg_len = sum(self._question_lengths) / max(len(self._question_lengths), 1)
        if avg_len > 50:
            return "advanced"
        elif avg_len > 20:
            return "intermediate"
        return "beginner"

    @property
    def response_preference(self) -> str:
        if not self._question_lengths:
            return "detailed"
        avg = sum(self._question_lengths) / len(self._question_lengths)
        if avg < 15:
            return "concise"
        return "detailed"

    @property
    def is_builder(self) -> bool:
        total = self._code_requests + self._text_requests
        return total > 0 and self._code_requests / total > 0.4

    @property
    def is_new_user(self) -> bool:
        return self._turn_count < 5

    def record_turn(self, question: str, domain: str, is_code: bool,
                    signal: str = "neutral"):
        self._turn_count += 1
        self._domains.append(domain)
        self._question_lengths.append(len(question))
        self._signals.append(signal)
        if is_code:
            self._code_requests += 1
        else:
            self._text_requests += 1

    def get_activation_hint(self) -> str:
        hints = []

        if self.is_new_user:
            hints.append("用户是新用户，回答详细一些，适当引导")
        elif self._turn_count > 20:
            hints.append("用户是高频用户，回答可以更简洁精炼")

        if self.is_builder:
            hints.append("用户偏好做工具/代码，技术相关回答可以更深入")

        if self.expertise_level == "advanced":
            hints.append("用户提问较专业，可以使用专业术语")
        elif self.expertise_level == "beginner":
            hints.append("用户提问较简短，解释尽量通俗易懂")

        if not hints:
            return ""
        return "\n[用户画像]\n" + "\n".join("- " + h for h in hints)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "turn_count": self._turn_count,
            "primary_domains": self.primary_domains,
            "expertise_level": self.expertise_level,
            "response_preference": self.response_preference,
            "is_builder": self.is_builder,
            "code_requests": self._code_requests,
            "text_requests": self._text_requests,
        }


class UserProfileManager:
    def __init__(self):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[str, UserProfile] = {}

    def get_or_create(self, session_id: str) -> UserProfile:
        if session_id not in self._profiles:
            self._profiles[session_id] = UserProfile(session_id)
        return self._profiles[session_id]

    def save(self, session_id: str):
        profile = self._profiles.get(session_id)
        if profile and profile._turn_count >= 3:
            path = PROFILE_DIR / "{}.json".format(session_id[:16])
            path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
