"""QA Agent：自动生成 pytest 单元测试。

接收 DevOutput + PMOutput（了解预期行为），输出 QAOutput（测试文件 + 用例数）。
"""

from __future__ import annotations

from typing import Any

from devteam_pro.agents.base import BaseAgent
from devteam_pro.llm.base import BaseProvider
from devteam_pro.models.messages import AgentMessage, DevOutput, PMOutput, QAOutput
from devteam_pro.utils.logger import get_logger

logger = get_logger("agents.qa")

QA_SYSTEM_PROMPT = """You are a Senior QA Engineer. Your job is to write comprehensive pytest
unit tests for Python code based on the development specification and the implemented code.

## Testing Standards
- Use pytest as the testing framework
- Every test file must be placed in a "tests/" directory
- Test file naming: test_<module_name>.py
- Each test function should test ONE specific behavior
- Use descriptive test names: test_<function>_<scenario>_<expected_result>
- Include tests for:
  - Happy path (normal input → expected output)
  - Edge cases (empty input, boundary values, None)
  - Error cases (invalid input → appropriate exception)
  - Integration between modules (if applicable)
- Use fixtures for common setup
- Use parametrize for multiple input variants
- Mock external dependencies where appropriate
- Tests MUST be self-contained and runnable

## IMPORTANT
- Write COMPLETE test file content, not outlines
- Tests must be able to import the actual code (use relative imports or sys.path)
- Include __init__.py in tests/ directory
- If the project uses a src layout, adjust imports accordingly
- Each test should have a brief docstring
"""


class QAAgent(BaseAgent[DevOutput, QAOutput]):
    """QA Agent — 测试生成。

    输入：DevOutput（需要测试的代码）
    额外输入：PMOutput（了解需求预期行为）
    输出：QAOutput（测试文件 + 统计）
    """

    role = "qa"
    system_prompt_template = QA_SYSTEM_PROMPT
    output_schema_cls = QAOutput

    def __init__(self, provider: BaseProvider) -> None:
        super().__init__(provider)

    def _build_user_prompt(self, input_data: DevOutput, **extra: Any) -> str:
        """构建包含代码和需求的 QA prompt。"""
        parts = [
            "## Code to Test\n",
            f"Project: {input_data.project_name}\n",
            f"Entry point: {input_data.entry_point}\n\n",
            "### Source Files\n",
        ]

        for f in input_data.files:
            parts.append(f"**{f.path}**\n")
            parts.append(f"```python\n{f.content}\n```\n\n")

        # 如果有需求文档，提供更多上下文
        if "pm_output" in extra:
            parts.append("## Requirements Specification\n")
            parts.append(f"```json\n{extra['pm_output']}\n```\n")

        parts.append(
            "\nPlease write comprehensive pytest unit tests for ALL the source files above. "
            "Place all test files in a 'tests/' directory. "
            "Include __init__.py so tests can be discovered. "
            "Cover happy paths, edge cases, and error handling for each module."
        )

        return "\n".join(parts)

    async def execute(
        self,
        input_data: DevOutput,
        task_id: str = "",
        **extra: Any,
    ) -> QAOutput:
        """执行测试生成。"""
        return await super().execute(input_data, task_id=task_id, **extra)

    async def process_dev_output(
        self,
        dev_msg: AgentMessage,
        pm_msg: AgentMessage | None = None,
    ) -> AgentMessage:
        """处理 Developer 输出，生成测试用例。

        Args:
            dev_msg: Developer Agent 的输出消息。
            pm_msg: PM Agent 的输出消息（可选，提供需求上下文）。

        Returns:
            包含 QAOutput 的 AgentMessage。
        """
        dev_output = dev_msg.unwrap_as(DevOutput)

        extra: dict[str, Any] = {}
        if pm_msg is not None:
            extra["pm_output"] = pm_msg.content

        output = await self.execute(
            dev_output,
            task_id=dev_msg.task_id,
            **extra,
        )

        msg = AgentMessage(
            agent_role="qa",
            task_id=dev_msg.task_id,
            input_ref=f"{dev_msg.task_id}:developer",
            metadata={"pm_ref": f"{dev_msg.task_id}:pm" if pm_msg else None},
        )
        msg.wrap_output(output)
        logger.info(
            "[%s] QA completed: %d test files, %d test cases",
            dev_msg.task_id[:8], len(output.test_files), output.test_count,
        )
        return msg
