"""Reviewer Agent：代码静态评审。

接收 DevOutput，输出 ReviewReport（评分 + 结构化问题清单）。
覆盖规范、逻辑、安全、性能、边界、错误处理等维度。
"""

from __future__ import annotations

from typing import Any

from devteam_pro.agents.base import BaseAgent
from devteam_pro.llm.base import BaseProvider
from devteam_pro.models.messages import AgentMessage, DevOutput, ReviewReport
from devteam_pro.utils.logger import get_logger

logger = get_logger("agents.reviewer")

REVIEWER_SYSTEM_PROMPT = """You are a Senior Code Reviewer. Your job is to perform a thorough
static code review of Python code. You must be critical and thorough — every issue you find
improves the final product quality.

## Review Dimensions
1. **Style (style)**: PEP 8 violations, inconsistent naming, poor formatting
2. **Logic (logic)**: Bugs, incorrect algorithms, off-by-one errors, wrong assumptions
3. **Security (security)**: Injection risks, hardcoded secrets, unsafe eval/exec, path traversal
4. **Performance (performance)**: Inefficient loops, missing generators, n+1 patterns, excessive memory
5. **Boundary (boundary)**: Missing null checks, edge cases not handled, input validation gaps
6. **Error Handling (error_handling)**: Bare excepts, swallowed exceptions, missing try/except
7. **Naming (naming)**: Unclear variable/function names, inconsistent conventions
8. **Architecture (architecture)**: SRP violations, circular dependencies, poor separation of concerns

## Severity Guidelines
- **critical**: Will cause runtime crash, security vulnerability, or data loss
- **major**: Logic bug, significant performance issue, or missing critical error handling
- **minor**: Style issue, unclear naming, minor improvement opportunity
- **info**: Suggestion for better practice, not a problem

## Scoring
- 90-100: Production-ready, minimal issues
- 75-89: Good quality, some minor improvements needed
- 60-74: Acceptable but needs work
- Below 60: Significant issues, should be refactored

## IMPORTANT
- Be specific: cite file paths and approximate line numbers
- Each issue must have a clear suggestion for how to fix it
- Don't flag issues you're not confident about
- Review ALL files provided
"""


class ReviewerAgent(BaseAgent[DevOutput, ReviewReport]):
    """Reviewer Agent — 代码审查。

    输入：DevOutput（开发者产出的代码）
    输出：ReviewReport（审查问题 + 评分）
    """

    role = "reviewer"
    system_prompt_template = REVIEWER_SYSTEM_PROMPT
    output_schema_cls = ReviewReport

    def __init__(self, provider: BaseProvider) -> None:
        super().__init__(provider)

    def _build_user_prompt(self, input_data: DevOutput, **extra: Any) -> str:
        """构建包含所有代码文件的审查 prompt。"""
        parts = [
            "## Code to Review\n",
            f"Project: {input_data.project_name}\n",
            f"Entry point: {input_data.entry_point}\n",
            f"Dependencies: {', '.join(input_data.dependencies)}\n\n",
            "### Files\n",
        ]

        for f in input_data.files:
            parts.append(f"**{f.path}** ({f.description})\n")
            parts.append(f"```python\n{f.content}\n```\n\n")

        parts.append(
            "\nPlease review ALL files above thoroughly. "
            "For each issue found, specify the exact file path and approximate line number. "
            "Provide an overall quality score (0-100)."
        )

        return "\n".join(parts)

    async def execute(
        self,
        input_data: DevOutput,
        task_id: str = "",
        **extra: Any,
    ) -> ReviewReport:
        """执行代码审查。"""
        return await super().execute(input_data, task_id=task_id, **extra)

    async def process_dev_output(self, dev_msg: AgentMessage) -> AgentMessage:
        """处理 Developer 输出，执行代码审查。

        Args:
            dev_msg: Developer Agent 的输出消息。

        Returns:
            包含 ReviewReport 的 AgentMessage。
        """
        dev_output = dev_msg.unwrap_as(DevOutput)
        output = await self.execute(dev_output, task_id=dev_msg.task_id)

        msg = AgentMessage(
            agent_role="reviewer",
            task_id=dev_msg.task_id,
            input_ref=f"{dev_msg.task_id}:developer",
        )
        msg.wrap_output(output)

        critical = sum(1 for i in output.issues if i.severity == "critical")
        major = sum(1 for i in output.issues if i.severity == "major")
        logger.info(
            "[%s] Reviewer completed: score=%.0f, issues=%d (critical=%d, major=%d)",
            dev_msg.task_id[:8], output.overall_score,
            len(output.issues), critical, major,
        )
        return msg
