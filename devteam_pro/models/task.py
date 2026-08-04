"""任务状态追踪模型。

记录流水线执行过程中的完整状态，支持：
- 任务状态持久化（JSON 序列化）
- 人工介入中断修正
- 自动修复循环计数
- 每阶段耗时统计
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """任务执行状态枚举。"""
    PENDING = "pending"            # 等待执行
    PM_RUNNING = "pm_running"      # PM 执行中
    PM_DONE = "pm_done"            # PM 完成
    DEV_RUNNING = "dev_running"    # Developer 执行中
    DEV_DONE = "dev_done"          # Developer 完成
    REVIEW_RUNNING = "review_running"
    REVIEW_DONE = "review_done"
    QA_RUNNING = "qa_running"
    QA_DONE = "qa_done"
    SANDBOX_RUNNING = "sandbox_running"
    SANDBOX_DONE = "sandbox_done"
    FIXING = "fixing"              # 自动修复中
    COMPLETED = "completed"        # 全部完成（成功）
    FAILED = "failed"              # 最终失败（3轮修复后仍失败）
    PAUSED = "paused"              # 人工暂停
    CANCELLED = "cancelled"        # 已取消


class StageResult(BaseModel):
    """单个阶段的执行结果快照。"""
    stage: str = Field(..., description="阶段名（pm/dev/review/qa/sandbox）")
    status: str = Field(..., description="阶段状态")
    input_message: dict[str, Any] | None = Field(
        default=None, description="阶段输入消息（序列化后）"
    )
    output_message: dict[str, Any] | None = Field(
        default=None, description="阶段输出消息（序列化后）"
    )
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    error: str | None = Field(default=None, description="错误信息")


class TaskState(BaseModel):
    """一个完整任务的运行状态。

    支持 JSON 序列化持久化，便于：
    - 前端轮询状态
    - 中断后恢复
    - 评测统计
    """
    task_id: str = Field(..., description="任务唯一标识")
    requirement: str = Field(..., description="原始需求文本")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="当前状态")
    fix_round: int = Field(default=0, description="当前修复轮次（0=首次）")
    max_fix_rounds: int = Field(default=3, description="最大修复轮次")
    stages: list[StageResult] = Field(
        default_factory=list, description="各阶段执行结果"
    )
    started_at: datetime | None = Field(default=None, description="任务开始时间")
    finished_at: datetime | None = Field(default=None, description="任务结束时间")
    human_intervention_message: str | None = Field(
        default=None, description="人工介入修正说明"
    )
    final_output_dir: str | None = Field(
        default=None, description="最终产出的目录路径"
    )
    final_sandbox_result: dict[str, Any] | None = Field(
        default=None, description="最终沙箱结果（序列化）"
    )

    @property
    def is_terminal(self) -> bool:
        """是否处于终态（不会再继续执行）。"""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    @property
    def total_duration_seconds(self) -> float | None:
        """从开始到结束的总耗时（秒）。"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    @property
    def error_summary(self) -> str | None:
        """汇总所有阶段的错误信息。"""
        errors = [s.error for s in self.stages if s.error]
        return "\n".join(errors) if errors else None
