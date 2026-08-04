"""PM Agent：自然语言需求 → 结构化开发文档。

接收原始需求文本，输出 PMOutput（功能清单、技术约束、验收标准）。
"""

from __future__ import annotations

from typing import Any

from devteam_pro.agents.base import BaseAgent
from devteam_pro.llm.base import BaseProvider
from devteam_pro.models.messages import AgentMessage, PMOutput
from devteam_pro.utils.logger import get_logger

logger = get_logger("agents.pm")

PM_SYSTEM_PROMPT = """You are a Senior Product Manager for a Python software development team.
Your job is to analyze user requirements and produce a detailed, structured development document.

## Responsibilities
1. Parse the user's natural language requirement and extract all features
2. Define clear technical constraints (Python 3.10+, package restrictions, file count limits)
3. Specify the expected output format
4. Define acceptance criteria to verify the final product

## Guidelines
- Be concrete and specific — avoid vague language like "good performance"
- Prioritize features: high=core functionality, medium=important enhancements, low=nice-to-have
- For technical constraints, consider: Python version, forbidden/required packages, max files
- Output format should specify: project type, whether tests/README/requirements are needed
- Acceptance criteria should be testable statements

## Example
For "Create a CLI password generator":
- Features: random password generation, length config, character set options, clipboard support
- Tech constraints: Python 3.10+, no external API calls needed, use stdlib secrets module
- Acceptance: run `python password_gen.py --length 16` produces 16-char password
"""


class PMAgent(BaseAgent[Any, PMOutput]):
    """PM Agent — 需求分析。

    输入：原始需求字符串（非 Pydantic 模型）
    输出：PMOutput（结构化开发文档）
    """

    role = "pm"
    system_prompt_template = PM_SYSTEM_PROMPT
    output_schema_cls = PMOutput

    def __init__(self, provider: BaseProvider) -> None:
        super().__init__(provider)

    def _build_user_prompt(self, input_data: str, **extra: Any) -> str:
        """PM 的输入是纯文本需求，非 Pydantic 模型。"""
        return (
            f"## User Requirement\n\n{input_data}\n\n"
            "Please analyze the above requirement and produce a structured "
            "development document following the specified JSON schema."
        )

    async def execute(
        self,
        input_data: str,
        task_id: str = "",
        **extra: Any,
    ) -> PMOutput:
        """执行 PM 分析（重载以接受字符串输入）。"""
        return await super().execute(input_data, task_id=task_id, **extra)

    async def process_requirement(
        self,
        requirement: str,
        task_id: str = "",
    ) -> AgentMessage:
        """PM 专用入口：处理原始需求字符串。

        Args:
            requirement: 用户自然语言需求。
            task_id: 任务标识。

        Returns:
            包含 PMOutput 的 AgentMessage。
        """
        output = await self.execute(requirement, task_id=task_id)

        msg = AgentMessage(
            agent_role="pm",
            task_id=task_id,
        )
        msg.wrap_output(output)
        logger.info("[%s] PM completed: %d features defined", task_id[:8], len(output.features))
        return msg
