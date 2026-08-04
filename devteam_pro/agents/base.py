"""Agent 基类。

封装 LLM 调用、Pydantic 结构化输出解析、解析失败自动重试。
所有角色 Agent 继承此类，通过泛型指定输入/输出 Pydantic 模型类型。

设计思路：
1. 将输出 JSON Schema 注入 system prompt，要求 LLM 返回纯 JSON
2. 尝试 Pydantic model_validate_json 解析
3. 解析失败将错误信息回传给 LLM 重试（最多 3 次）
4. 支持 json_mode（response_format）和普通模式双路径
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from devteam_pro.llm.base import BaseProvider
from devteam_pro.models.messages import AgentMessage
from devteam_pro.utils.logger import get_logger

logger = get_logger("agents.base")


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT", bound=BaseModel)


def _clean_json_response(raw: str) -> str:
    """清理 LLM 返回的 JSON 字符串。

    处理常见的格式问题：
    - ```json ... ``` 代码块包裹
    - ``` ... ``` 无语言标识包裹
    - 前后空白字符
    """
    raw = raw.strip()
    # 移除 ```json ... ``` 包裹
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


class BaseAgent(Generic[InputT, OutputT]):
    """Agent 通用基类。

    泛型参数：
        InputT: 输入 Pydantic 模型类型。
        OutputT: 输出 Pydantic 模型类型。
    """

    # 子类覆盖
    role: str = "base"
    system_prompt_template: str = ""
    output_schema_cls: type[OutputT] | None = None

    def __init__(self, provider: BaseProvider) -> None:
        """初始化 Agent。

        Args:
            provider: LLM Provider 实例。
        """
        self.provider = provider
        self._parse_retries = 3  # 解析失败最大重试次数

    # ── Prompt 构建 ──────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """构建完整的 system prompt（含 JSON schema 约束）。

        思路：将 Pydantic 模型的 JSON Schema 追加到 system prompt 末尾，
        强制 LLM 按 schema 输出。这是实现结构化通信的关键。
        """
        base = self.system_prompt_template
        if self.output_schema_cls is not None:
            schema = self.output_schema_cls.model_json_schema()
            schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
            base += (
                "\n\n## Output Format\n"
                "You MUST respond with ONLY valid JSON. No markdown, no explanations, "
                "just the raw JSON object. The JSON must exactly match this schema:\n"
                f"```json\n{schema_str}\n```\n"
                "IMPORTANT: Your entire response must be parseable JSON. "
                "Do NOT wrap it in ```json code blocks. Do NOT add any text outside the JSON."
            )
        return base

    def _build_user_prompt(self, input_data: InputT, **extra: Any) -> str:
        """构建 user prompt。子类可覆盖此方法定制。

        Args:
            input_data: 上游 Agent 的结构化输出。
            **extra: 额外上下文（如修复轮次、错误信息等）。
        """
        # 默认：将输入模型序列化为格式化的 JSON 文本
        input_json = input_data.model_dump_json(indent=2)
        prompt = f"Input data:\n```json\n{input_json}\n```\n"
        for key, value in extra.items():
            prompt += f"\n{key}:\n{value}\n"
        prompt += "\nPlease produce your output as specified in the system prompt."
        return prompt

    # ── LLM 调用 + 解析 ──────────────────────────────────────

    async def execute(
        self,
        input_data: InputT,
        task_id: str = "",
        **extra: Any,
    ) -> OutputT:
        """执行 Agent 主逻辑：调用 LLM → 解析 Pydantic 输出。

        Args:
            input_data: 上游输入（Pydantic 模型）。
            task_id: 任务标识。
            **extra: 额外上下文。

        Returns:
            解析后的 Pydantic 输出模型。

        Raises:
            ValueError: 所有解析重试耗尽后仍失败。
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(input_data, **extra)

        last_parse_error: str | None = None

        for attempt in range(self._parse_retries + 1):
            try:
                raw = await self.provider.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    json_mode=True,
                    temperature=0.3,
                )
                # 清理可能残留的代码块标记
                cleaned = _clean_json_response(raw)
                parsed = self.output_schema_cls.model_validate_json(cleaned)
                logger.info(
                    "[%s] %s output parsed successfully (attempt %d/%d)",
                    task_id[:8], self.role, attempt + 1, self._parse_retries + 1,
                )
                return parsed
            except Exception as e:
                last_parse_error = str(e)
                logger.warning(
                    "[%s] %s parse attempt %d/%d failed: %s",
                    task_id[:8], self.role, attempt + 1, self._parse_retries + 1, e,
                )
                if attempt < self._parse_retries:
                    # 将解析错误回传给 LLM 修正
                    user_prompt += (
                        f"\n\n[ERROR] Your previous JSON was invalid. "
                        f"Parse error: {last_parse_error}\n"
                        f"Please fix the JSON and output ONLY valid JSON."
                    )
                    await asyncio.sleep(1)

        raise ValueError(
            f"{self.role} failed to produce valid {self.output_schema_cls.__name__} "
            f"after {self._parse_retries + 1} attempts. Last error: {last_parse_error}"
        )

    # ── 便捷方法：输入+执行+打包为 AgentMessage ──────────────

    async def process_message(
        self,
        input_msg: AgentMessage,
        **extra: Any,
    ) -> AgentMessage:
        """处理上游 AgentMessage，执行逻辑，返回包装好的 AgentMessage。

        这是流水线中的标准调用入口。

        Args:
            input_msg: 上游 Agent 消息。
            **extra: 额外上下文。

        Returns:
            包含当前 Agent 输出的 AgentMessage。
        """
        input_data = input_msg.unwrap_as(self._input_cls())
        output = await self.execute(input_data, task_id=input_msg.task_id, **extra)

        msg = AgentMessage(
            agent_role=self.role,  # type: ignore[arg-type]
            task_id=input_msg.task_id,
            input_ref=f"{input_msg.task_id}:{input_msg.agent_role}",
            metadata=extra,
        )
        msg.wrap_output(output)
        return msg

    def _input_cls(self) -> type[InputT]:
        """子类覆盖返回输入模型类型。"""
        raise NotImplementedError
