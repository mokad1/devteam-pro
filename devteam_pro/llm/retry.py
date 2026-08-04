"""LLM 调用的重试、限流、异常降级逻辑。

核心功能：
1. 指数退避重试（1s → 2s → 4s → 8s，最多 max_retries 次）
2. 令牌桶限流（控制每分钟请求数，防止触发 API 频率限制）
3. 异常分类降级（网络超时可重试，认证错误立即抛出）
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from devteam_pro.utils.logger import get_logger

logger = get_logger("llm.retry")

T = TypeVar("T")


class RateLimiter:
    """令牌桶算法实现的速率限制器。

    思路：桶容量 = rpm，每秒补充 rpm/60 个令牌，每次请求消耗 1 个令牌。
    若令牌不足则等待，而非立即失败，保证请求的平滑发送。
    """

    def __init__(self, rpm: int = 30) -> None:
        """初始化限流器。

        Args:
            rpm: 每分钟最大请求数。
        """
        self.rpm = rpm
        self.tokens: float = float(rpm)  # 当前令牌数
        self.max_tokens: float = float(rpm)
        self.refill_rate: float = rpm / 60.0  # 每秒补充令牌数
        self.last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """获取一个令牌，若不足则等待。"""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return

            # 计算需要等待的时间
            wait_time = (1.0 - self.tokens) / self.refill_rate
            logger.debug("Rate limit: waiting %.1fs for token", wait_time)
            await asyncio.sleep(wait_time)
            self.tokens = 0.0
            self.last_refill = time.monotonic()


# 全局限流器（按 provider 分实例）
_RATE_LIMITERS: dict[str, RateLimiter] = {}


def get_rate_limiter(provider_name: str, rpm: int = 30) -> RateLimiter:
    """获取或创建指定 provider 的限流器实例。"""
    if provider_name not in _RATE_LIMITERS:
        _RATE_LIMITERS[provider_name] = RateLimiter(rpm)
    return _RATE_LIMITERS[provider_name]


# 可重试的异常类型
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    provider_name: str = "default",
    max_retries: int = 3,
    rpm: int = 30,
) -> T:
    """带指数退避重试和限流的异步调用包装器。

    思路：
    1. 先通过令牌桶限流
    2. 执行请求
    3. 若失败且为可重试异常 → 指数退避后重试
    4. 不可重试异常（如 401 认证错误）立即抛出

    Args:
        fn: 异步可调用对象。
        provider_name: provider 名称（用于限流器隔离）。
        max_retries: 最大重试次数（不含首次）。
        rpm: 每分钟请求速率限制。

    Returns:
        函数返回值。

    Raises:
        RuntimeError: 所有重试耗尽后仍失败。
    """
    limiter = get_rate_limiter(provider_name, rpm)

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            await limiter.acquire()
            return await fn()
        except Exception as e:
            last_error = e
            status = _extract_http_status(e)

            # 认证错误不重试
            if status == 401:
                logger.error("Authentication failed (401): %s", e)
                raise

            # 非可重试客户端错误（4xx 除 429）不重试
            if status is not None and 400 <= status < 500 and status != 429:
                logger.error("Non-retryable client error (%d): %s", status, e)
                raise

            if attempt < max_retries:
                delay = 2 ** attempt  # 1s, 2s, 4s, ...
                logger.warning(
                    "Attempt %d/%d failed (%s), retrying in %ds...",
                    attempt + 1, max_retries + 1, e, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d attempts exhausted. Last error: %s",
                    max_retries + 1, e,
                )

    raise RuntimeError(
        f"LLM call failed after {max_retries + 1} attempts. "
        f"Last error: {last_error}"
    )


def _extract_http_status(exception: Exception) -> int | None:
    """从异常中提取 HTTP 状态码（兼容 httpx 和通用异常）。"""
    # httpx.HTTPStatusError
    if hasattr(exception, "response"):
        resp = getattr(exception, "response", None)
        if resp is not None and hasattr(resp, "status_code"):
            return resp.status_code
    # httpx.RequestError（网络超时等）
    if hasattr(exception, "__class__"):
        cls_name = exception.__class__.__name__
        if cls_name in ("ConnectError", "ReadError", "WriteError", "RemoteProtocolError"):
            return 503  # 模拟可重试状态码
    return None
