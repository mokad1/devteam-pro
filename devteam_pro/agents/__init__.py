"""四角色 Agent 层：PM → Developer → Reviewer → QA。

每个 Agent 通过结构化 Pydantic 模型通信，禁止纯文本传递。
"""

from devteam_pro.agents.base import BaseAgent
from devteam_pro.agents.developer import DeveloperAgent
from devteam_pro.agents.pm import PMAgent
from devteam_pro.agents.qa import QAAgent
from devteam_pro.agents.reviewer import ReviewerAgent

__all__ = [
    "BaseAgent",
    "DeveloperAgent",
    "PMAgent",
    "QAAgent",
    "ReviewerAgent",
]
