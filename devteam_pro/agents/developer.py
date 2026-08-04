"""Developer Agent：结构化开发文档 → 完整项目代码。

接收 PMOutput，输出 DevOutput（代码文件 + 依赖 + 入口说明）。
支持修复模式：接收错误信息后修正代码。
"""

from __future__ import annotations

from typing import Any

from devteam_pro.agents.base import BaseAgent
from devteam_pro.llm.base import BaseProvider
from devteam_pro.models.messages import AgentMessage, DevOutput, PMOutput
from devteam_pro.utils.logger import get_logger

logger = get_logger("agents.developer")

DEV_SYSTEM_PROMPT = """You are a Senior Python Developer. Your job is to implement complete,
well-structured Python code based on a structured development document from the PM.

## Coding Standards
- Python 3.10+ with complete type annotations
- PEP 8 compliant formatting
- Use pathlib, dataclasses, and modern Python features
- Each file should have a clear single responsibility
- Include docstrings for all public functions and classes
- Handle edge cases and errors properly
- DO NOT use heavy frameworks unless explicitly required
- Prefer stdlib over external dependencies when possible

## Output Requirements
- Provide the COMPLETE content of each file (not partial snippets)
- List ALL pip dependencies needed
- Specify the entry point file (e.g., "main.py" or "src/cli.py")
- Include setup/run instructions
- If tests exist, place them in a "tests/" directory with "__init__.py"

## File Path Convention
- Use forward slashes for paths (e.g., "src/utils.py", "tests/test_main.py")
- Keep the structure flat for small projects, nested for larger ones
- Always include a main entry point
"""


class DeveloperAgent(BaseAgent[PMOutput, DevOutput]):
    """Developer Agent — 代码生成。

    输入：PMOutput（结构化需求文档）
    输出：DevOutput（完整代码项目）
    支持 fix_context 参数进行修复模式。
    """

    role = "developer"
    system_prompt_template = DEV_SYSTEM_PROMPT
    output_schema_cls = DevOutput

    def __init__(self, provider: BaseProvider) -> None:
        super().__init__(provider)

    def _build_user_prompt(self, input_data: PMOutput, **extra: Any) -> str:
        """构建 Developer prompt，可能包含修复上下文。"""
        pm_json = input_data.model_dump_json(indent=2)

        parts = [
            "## Development Specification\n",
            f"```json\n{pm_json}\n```\n",
        ]

        # 修复模式：前一版本代码 + 错误信息
        if extra.get("fix_mode"):
            parts.append("## FIX MODE — Improve Previous Implementation\n")
            if "previous_code" in extra:
                parts.append("### Previous Code\n")
                parts.append(f"```\n{extra['previous_code']}\n```\n")
            if "error_summary" in extra:
                parts.append("### Errors to Fix\n")
                parts.append(f"{extra['error_summary']}\n")
            if "review_issues" in extra:
                parts.append("### Review Issues to Address\n")
                parts.append(f"{extra['review_issues']}\n")
            parts.append(
                "\nIMPORTANT: Fix ALL errors listed above. "
                "Make the minimal necessary changes. Keep working code intact.\n"
            )
        else:
            parts.append(
                "Please implement the complete project based on the specification above. "
                "Generate ALL necessary files with their full content.\n"
            )

        return "\n".join(parts)

    async def execute(
        self,
        input_data: PMOutput,
        task_id: str = "",
        **extra: Any,
    ) -> DevOutput:
        """执行代码生成。"""
        return await super().execute(input_data, task_id=task_id, **extra)

    async def process_pm_output(
        self,
        pm_msg: AgentMessage,
        fix_context: dict[str, Any] | None = None,
    ) -> AgentMessage:
        """处理 PM 输出，生成代码。

        Args:
            pm_msg: PM Agent 的输出消息。
            fix_context: 修复上下文（错误摘要、前一版代码等）。

        Returns:
            包含 DevOutput 的 AgentMessage。
        """
        pm_output = pm_msg.unwrap_as(PMOutput)
        fix_round = fix_context.get("fix_round", 0) if fix_context else 0

        extra: dict[str, Any] = {}
        if fix_context:
            extra["fix_mode"] = True
            extra.update(fix_context)

        output = await self.execute(pm_output, task_id=pm_msg.task_id, **extra)

        output.fix_round = fix_round
        msg = AgentMessage(
            agent_role="developer",
            task_id=pm_msg.task_id,
            input_ref=f"{pm_msg.task_id}:pm",
            metadata={"fix_round": fix_round},
        )
        msg.wrap_output(output)
        logger.info(
            "[%s] Developer completed (fix_round=%d): %d files, %d deps",
            pm_msg.task_id[:8], fix_round, len(output.files), len(output.dependencies),
        )
        return msg
