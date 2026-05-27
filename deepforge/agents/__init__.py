from deepforge.agents.project_manager import ProjectManagerAgent
from deepforge.agents.product_manager import ProductManagerAgent
from deepforge.agents.architect import ArchitectAgent
from deepforge.agents.engineer import EngineerAgent
from deepforge.agents.reviewer import ReviewerAgent
from deepforge.agents.crowd_user import CrowdUserAgent
from deepforge.agents.memory_keeper import MemoryKeeperAgent

ALL_AGENTS = [
    ProjectManagerAgent,
    ProductManagerAgent,
    ArchitectAgent,
    EngineerAgent,
    ReviewerAgent,
    CrowdUserAgent,
    MemoryKeeperAgent,
]

__all__ = [
    "ProjectManagerAgent",
    "ProductManagerAgent",
    "ArchitectAgent",
    "EngineerAgent",
    "ReviewerAgent",
    "CrowdUserAgent",
    "MemoryKeeperAgent",
    "ALL_AGENTS",
]
