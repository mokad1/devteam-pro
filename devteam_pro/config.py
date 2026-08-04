"""全局配置管理，从 .env 文件和环境变量加载。

所有敏感信息（API Key、Base URL）通过环境变量注入，
不硬编码在代码中。配置类使用 Pydantic v2 进行校验。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field


# 自动定位 .env 文件：先找项目根目录，再找当前目录
_ENV_PATH = Path(__file__).parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)
else:
    load_dotenv()

ProviderKind = Literal["openai", "deepseek", "qwen"]


class Config(BaseModel):
    """全局配置，所有字段从环境变量读取，模型启动时校验。"""

    # ── LLM Provider 选择 ──────────────────────────────
    llm_provider: ProviderKind = Field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "deepseek")
    )

    # ── OpenAI ──────────────────────────────────────────
    openai_api_key: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    openai_base_url: str = Field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )

    # ── DeepSeek ────────────────────────────────────────
    deepseek_api_key: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "")
    )
    deepseek_base_url: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    )

    # ── 通义千问 (Qwen) ────────────────────────────────
    qwen_api_key: str = Field(
        default_factory=lambda: os.getenv("QWEN_API_KEY", "")
    )
    qwen_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    )

    # ── 模型参数 ────────────────────────────────────────
    default_model: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_MODEL", "")
    )
    max_retries: int = Field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "3"))
    )
    request_timeout: int = Field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "120"))
    )

    # ── Pipeline 参数 ───────────────────────────────────
    max_fix_rounds: int = Field(
        default_factory=lambda: int(os.getenv("MAX_FIX_ROUNDS", "3"))
    )
    sandbox_timeout: int = Field(
        default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT", "120"))
    )

    # ── 限流参数 ────────────────────────────────────────
    rate_limit_rpm: int = Field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_RPM", "30"))
    )

    # ── 日志级别 ────────────────────────────────────────
    log_level: str = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    # ── 数据目录 ────────────────────────────────────────
    data_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("DATA_DIR", str(Path(__file__).parent.parent / "data"))
        )
    )


# 全局单例，启动时加载一次
config = Config()


def get_config() -> Config:
    """获取全局配置单例。"""
    return config
