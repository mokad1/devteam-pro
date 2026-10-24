"""结构化日志工具。

提供统一的日志记录接口，支持：
- 控制台 + 文件双输出
- 自动包含 task_id 上下文
- JSON 格式文件日志（便于 Streamlit 读取展示）
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from devteam_pro.config import config

_LOG_DIR = config.data_dir / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 事件日志文件（JSON Lines 格式，Streamlit 直接读取展示）
_EVENT_LOG_PATH = _LOG_DIR / "events.jsonl"


class _StructuredFormatter(logging.Formatter):
    """控制台格式：带 task_id 高亮。"""

    def format(self, record: logging.LogRecord) -> str:
        task_id = getattr(record, "task_id", "-")
        base = super().format(record)
        return f"[{task_id[:8]:>8}] {base}"


class _TaskIdFilter(logging.Filter):
    """确保每条日志记录都有 task_id 属性。

    文件 handler 的格式串里有 %(task_id)s，但绝大多数日志调用没有传
    extra={"task_id": ...}，缺少该属性会让 logging 抛 KeyError，进而
    把整条流水线带崩。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "task_id"):
            record.task_id = "-"
        return True


def setup_logging(level: str = "INFO") -> None:
    """初始化全局日志配置。

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）。
    """
    root = logging.getLogger("devteam_pro")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        _StructuredFormatter("%(asctime)s [%(levelname)-7s] %(name)s: %(message)s")
    )
    console.addFilter(_TaskIdFilter())
    root.addHandler(console)

    # 文件 handler
    file_handler = logging.FileHandler(_LOG_DIR / "devteam.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s [%(task_id)s]: %(message)s"
        )
    )
    file_handler.addFilter(_TaskIdFilter())
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """获取带模块名的 logger。"""
    return logging.getLogger(f"devteam_pro.{name}")


# ── 事件日志（供 Streamlit 可视化）────────────────────────────

def log_event(
    task_id: str,
    event_type: str,
    agent_role: str,
    data: dict[str, Any],
) -> None:
    """将结构化事件写入 JSON Lines 文件。

    Streamlit 前端持续读取此文件展示流水线进度。

    Args:
        task_id: 任务 ID。
        event_type: 事件类型（agent_input, agent_output, sandbox_log, error 等）。
        agent_role: 触发事件的 Agent 角色。
        data: 事件载荷（Pydantic 模型需先 dump）。
    """
    event = {
        "task_id": task_id,
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "agent_role": agent_role,
        "data": data,
    }
    with open(_EVENT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
