"""具体 LLM Provider 实现：OpenAI / DeepSeek / 通义千问。

三家 Provider 均兼容 OpenAI Chat Completions API 格式，
共用一个基于 httpx 的 HTTP 调用实现，仅 base_url 和默认 model 不同。

设计思路：
- OpenAICompatibleProvider 封装通用的 OpenAI-compatible API 调用逻辑
- 三个具体 Provider 继承并设置各自的默认参数
- 通过 get_provider() 工厂函数根据配置自动选择
"""

from __future__ import annotations

from typing import Any

import httpx

from devteam_pro.config import config
from devteam_pro.llm.base import BaseProvider
from devteam_pro.llm.retry import with_retry
from devteam_pro.utils.logger import get_logger

logger = get_logger("llm.providers")


# ═══════════════════════════════════════════════════════════════
# OpenAI-compatible 通用 HTTP Provider
# ═══════════════════════════════════════════════════════════════

class OpenAICompatibleProvider(BaseProvider):
    """基于 httpx 的 OpenAI-compatible API 调用实现。

    兼容所有支持 /v1/chat/completions 端点的服务。
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        name: str = "openai",
        **kwargs: Any,
    ) -> None:
        super().__init__(model, api_key, base_url, **kwargs)
        self._name = name
        self._client: httpx.AsyncClient | None = None

    @property
    def provider_name(self) -> str:
        return self._name

    async def _get_client(self) -> httpx.AsyncClient:
        """延迟创建 httpx 客户端（线程安全）。"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=float(config.request_timeout),
                    write=30.0,
                    pool=10.0,
                ),
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> str:
        """调用 LLM 生成文本。

        思路：
        1. 构建 messages 列表
        2. 如果 json_mode=True，添加 response_format 参数（OpenAI 风格）
        3. 通过 with_retry 包装 HTTP 调用，自动处理限流和重试
        4. 从响应中提取 content 文本

        Raises:
            RuntimeError: 调用失败。
        """
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # JSON mode：优先使用 response_format，备选为 system prompt 中强调
        if json_mode:
            # DeepSeek / Qwen 部分模型可能不支持 response_format，
            # 尝试设置；不支持的服务会忽略此字段
            body["response_format"] = {"type": "json_object"}

        async def _call() -> str:
            client = await self._get_client()
            response = await client.post("/chat/completions", json=body)
            response.raise_for_status()
            data = response.json()

            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")

            if not content:
                logger.warning(
                    "Empty response from %s. Finish reason: %s",
                    self._name, choice.get("finish_reason"),
                )
                # 尝试从 tool_calls 中获取（部分模型可能以 function call 返回）
                raise RuntimeError(f"Empty response from {self._name}")

            # 记录 token 消耗
            usage = data.get("usage", {})
            logger.debug(
                "%s tokens: prompt=%d, completion=%d, total=%d",
                self._name,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
            )

            return content

        return await with_retry(
            _call,
            provider_name=self._name,
            max_retries=config.max_retries,
            rpm=config.rate_limit_rpm,
        )

    async def close(self) -> None:
        """关闭 HTTP 客户端连接。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ═══════════════════════════════════════════════════════════════
# 具体 Provider 实现
# ═══════════════════════════════════════════════════════════════

class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI Provider。

    默认模型：gpt-4o
    API 地址：https://api.openai.com/v1
    """

    def __init__(self, model: str = "", api_key: str = "", base_url: str = "") -> None:
        super().__init__(
            model=model or config.default_model or "gpt-4o",
            api_key=api_key or config.openai_api_key,
            base_url=base_url or config.openai_base_url,
            name="openai",
        )


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek Provider。

    默认模型：deepseek-chat
    API 地址：https://api.deepseek.com/v1
    """

    def __init__(self, model: str = "", api_key: str = "", base_url: str = "") -> None:
        super().__init__(
            model=model or config.default_model or "deepseek-chat",
            api_key=api_key or config.deepseek_api_key,
            base_url=base_url or config.deepseek_base_url,
            name="deepseek",
        )


class QwenProvider(OpenAICompatibleProvider):
    """通义千问 (Qwen) Provider。

    默认模型：qwen-turbo
    API 地址：https://dashscope.aliyuncs.com/compatible-mode/v1
    """

    def __init__(self, model: str = "", api_key: str = "", base_url: str = "") -> None:
        super().__init__(
            model=model or config.default_model or "qwen-turbo",
            api_key=api_key or config.qwen_api_key,
            base_url=base_url or config.qwen_base_url,
            name="qwen",
        )


# ═══════════════════════════════════════════════════════════════
# Provider 工厂函数
# ═══════════════════════════════════════════════════════════════

# Provider 类注册表
_PROVIDER_MAP: dict[str, type[OpenAICompatibleProvider]] = {
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
}


def get_provider(
    provider_name: str | None = None,
    model: str | None = None,
) -> BaseProvider:
    """工厂函数：根据配置创建 LLM Provider 实例。

    用法：
        provider = get_provider()  # 使用 .env 中的 LLM_PROVIDER
        provider = get_provider("openai", model="gpt-4o-mini")

    Args:
        provider_name: Provider 名称（openai/deepseek/qwen），默认从配置读取。
        model: 覆盖默认模型名。

    Returns:
        BaseProvider 实例。

    Raises:
        ValueError: 未知的 provider_name。
    """
    name = provider_name or config.llm_provider
    if name not in _PROVIDER_MAP:
        raise ValueError(
            f"Unknown provider '{name}'. Available: {list(_PROVIDER_MAP.keys())}"
        )

    cls = _PROVIDER_MAP[name]
    kwargs: dict[str, str] = {}
    if model:
        kwargs["model"] = model
    return cls(**kwargs)
