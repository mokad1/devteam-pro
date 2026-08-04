"""LLM Provider 抽象基类。

所有 Provider 必须实现 generate 方法。
设计思路：上层代码只依赖此抽象接口，通过工厂函数获取具体实现，
实现 Provider 的透明替换。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    """LLM Provider 抽象基类。

    所有 Provider 实现必须继承此类并实现 generate 方法。
    """

    def __init__(self, model: str, api_key: str, base_url: str, **kwargs: Any) -> None:
        """初始化 Provider。

        Args:
            model: 模型名称（如 gpt-4o, deepseek-chat, qwen-turbo）。
            api_key: API 密钥。
            base_url: API 基础地址（OpenAI-compatible endpoint）。
            **kwargs: 其他 Provider 特定参数。
        """
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.extra_kwargs = kwargs

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> str:
        """异步调用 LLM 生成文本。

        Args:
            prompt: 用户提示词。
            system_prompt: 系统提示词。
            json_mode: 是否强制 JSON 输出模式。
            temperature: 生成温度（0-2，推荐结构化任务用 0.3）。
            max_tokens: 最大生成 token 数。

        Returns:
            LLM 生成的原始文本。

        Raises:
            RuntimeError: LLM 调用失败（含重试后仍失败）。
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 名称标识。"""
        ...

    def __repr__(self) -> str:
        return f"<{self.provider_name}(model={self.model})>"
