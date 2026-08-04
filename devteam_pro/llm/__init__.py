"""统一模型 Provider 适配层。

抽象统一模型接口，兼容 OpenAI / DeepSeek / 通义千问。
上层业务代码通过工厂函数获取 provider，无需绑定单一模型。
"""

from devteam_pro.llm.base import BaseProvider
from devteam_pro.llm.providers import (
    DeepSeekProvider,
    OpenAIProvider,
    QwenProvider,
    get_provider,
)

__all__ = [
    "BaseProvider",
    "DeepSeekProvider",
    "OpenAIProvider",
    "QwenProvider",
    "get_provider",
]
