"""Pydantic v2 数据模型层。

所有 Agent 间消息和任务状态必须使用此包中的模型。
"""

from devteam_pro.models.messages import (
    AgentMessage,
    AgentRole,
    CodeFile,
    DevOutput,
    Feature,
    LintIssue,
    OutputSpec,
    PMOutput,
    QAOutput,
    ReviewIssue,
    ReviewReport,
    SandboxResult,
    TechConstraints,
)
from devteam_pro.models.task import StageResult, TaskState, TaskStatus

__all__ = [
    # Messages
    "AgentMessage",
    "AgentRole",
    "CodeFile",
    "DevOutput",
    "Feature",
    "LintIssue",
    "OutputSpec",
    "PMOutput",
    "QAOutput",
    "ReviewIssue",
    "ReviewReport",
    "SandboxResult",
    "TechConstraints",
    # Task
    "StageResult",
    "TaskState",
    "TaskStatus",
]
