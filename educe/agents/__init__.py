"""
DeepForge Agent Registry
3-Agent架构：Builder + Tester + Planner
旧Agent文件保留但不再注册到主pipeline
"""
from educe.agents.builder import BuilderAgent
from educe.agents.tester import TesterAgent
from educe.agents.planner import PlannerAgent

# 核心3-Agent
ALL_AGENTS = [
    BuilderAgent,
    TesterAgent,
    PlannerAgent,
]

__all__ = [
    "BuilderAgent",
    "TesterAgent",
    "PlannerAgent",
    "ALL_AGENTS",
]
