"""DevTeam 流水线编排器：PM → Developer → Reviewer → QA → Sandbox → Auto-Fix Loop。

核心流程：
1. PM 解析需求
2. Developer 生成代码
3. Reviewer 代码审查
4. QA 生成测试
5. Sandbox 执行 + Lint
6. 若失败 → 错误信息回传 Developer → 重新生成（最多 3 轮）
7. 每轮都经过 Reviewer + QA + Sandbox 全流程

设计思路：
- 所有 Agent 间消息使用 Pydantic 结构化数据（AgentMessage）
- 任务状态持久化到 JSON 文件（支持中断恢复）
- 人工介入通过设置 human_intervention_message 实现
- 异步流水线，每个阶段记录耗时和中间结果
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from devteam_pro.agents.developer import DeveloperAgent
from devteam_pro.agents.pm import PMAgent
from devteam_pro.agents.qa import QAAgent
from devteam_pro.agents.reviewer import ReviewerAgent
from devteam_pro.config import config
from devteam_pro.llm.base import BaseProvider
from devteam_pro.models.messages import (
    AgentMessage,
    DevOutput,
    PMOutput,
    QAOutput,
    ReviewReport,
    SandboxResult,
)
from devteam_pro.models.task import StageResult, TaskState, TaskStatus
from devteam_pro.sandbox.executor import SandboxExecutor
from devteam_pro.utils.logger import get_logger, log_event

logger = get_logger("scheduler.pipeline")


class DevTeamPipeline:
    """DevTeam Pro 主流水线。

    协调四个 Agent + Sandbox 完成从需求到可运行代码的全流程。
    内建自动修复闭环（最多 3 轮）。
    """

    def __init__(self, provider: BaseProvider) -> None:
        """初始化流水线。

        Args:
            provider: LLM Provider 实例（共享给所有 Agent）。
        """
        self.provider = provider
        self.pm = PMAgent(provider)
        self.developer = DeveloperAgent(provider)
        self.reviewer = ReviewerAgent(provider)
        self.qa = QAAgent(provider)
        self.sandbox = SandboxExecutor()

        # 任务输出目录
        self.output_dir = config.data_dir / "tasks"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── 主入口 ──────────────────────────────────────────────

    async def run(
        self,
        requirement: str,
        task_id: str | None = None,
        human_callback: Any = None,
    ) -> TaskState:
        """执行完整流水线。

        Args:
            requirement: 自然语言需求描述。
            task_id: 任务 ID（可选，自动生成 UUID）。
            human_callback: 人工介入回调（可选）。
                           签名为 async (TaskState) -> str | None
                           返回修正说明字符串。

        Returns:
            TaskState：完整的任务执行状态。
        """
        task_id = task_id or uuid.uuid4().hex[:12]
        state = TaskState(
            task_id=task_id,
            requirement=requirement,
            max_fix_rounds=config.max_fix_rounds,
            started_at=datetime.now(),
        )
        logger.info("=" * 60)
        logger.info("[%s] Pipeline started: %s", task_id[:8], requirement[:80])

        try:
            # ── Stage 1: PM ─────────────────────────────
            pm_msg = await self._run_pm(requirement, task_id, state)

            # ── Stage 2: Developer (首次生成) ───────────
            dev_msg = await self._run_developer(pm_msg, state, fix_round=0)

            # ── Stage 3: Reviewer ───────────────────────
            review_msg = await self._run_reviewer(dev_msg, state)

            # ── Stage 4: QA ────────────────────────────
            qa_msg = await self._run_qa(dev_msg, pm_msg, state)

            # ── Stage 5: Sandbox ────────────────────────
            sandbox_result = await self._run_sandbox(dev_msg, qa_msg, task_id, state)

            # ── Stage 6: Auto-Fix Loop ──────────────────
            fix_round = 0
            while (
                not sandbox_result.passed
                and fix_round < config.max_fix_rounds
            ):
                fix_round += 1
                logger.info(
                    "[%s] Auto-fix round %d/%d starting...",
                    task_id[:8], fix_round, config.max_fix_rounds,
                )
                state.status = TaskStatus.FIXING
                state.fix_round = fix_round

                # 人工介入检查点
                if human_callback:
                    correction = await human_callback(state)
                    if correction:
                        state.human_intervention_message = correction
                        logger.info("[%s] Human intervention: %s", task_id[:8], correction)

                # Developer 修复
                fix_context = self._build_fix_context(
                    dev_msg, review_msg, sandbox_result, fix_round,
                )
                if state.human_intervention_message:
                    fix_context["human_correction"] = state.human_intervention_message

                dev_msg = await self._run_developer(pm_msg, state, fix_round=fix_round, fix_context=fix_context)

                # 重新审查
                review_msg = await self._run_reviewer(dev_msg, state, fix_round=fix_round)

                # 重新生成测试
                qa_msg = await self._run_qa(dev_msg, pm_msg, state, fix_round=fix_round)

                # 重新沙箱执行
                sandbox_result = await self._run_sandbox(dev_msg, qa_msg, task_id, state, fix_round=fix_round)

            # ── 完成 ────────────────────────────────────
            if sandbox_result.passed:
                state.status = TaskStatus.COMPLETED
                logger.info("[%s] Pipeline COMPLETED successfully!", task_id[:8])
            else:
                state.status = TaskStatus.FAILED
                logger.warning(
                    "[%s] Pipeline FAILED after %d fix rounds",
                    task_id[:8], fix_round,
                )

        except Exception as e:
            state.status = TaskStatus.FAILED
            state.stages.append(StageResult(
                stage="pipeline",
                status="error",
                error=str(e),
            ))
            logger.error("[%s] Pipeline error: %s", task_id[:8], e)

        finally:
            state.finished_at = datetime.now()
            state.final_sandbox_result = (
                sandbox_result.model_dump(mode="json") if 'sandbox_result' in dir() else None
            )
            self._persist_state(state)

        return state

    # ── 各阶段执行 ──────────────────────────────────────────

    async def _run_pm(
        self, requirement: str, task_id: str, state: TaskState,
    ) -> AgentMessage:
        """执行 PM 阶段。"""
        state.status = TaskStatus.PM_RUNNING
        started = datetime.now()

        pm_msg = await self.pm.process_requirement(requirement, task_id)

        state.status = TaskStatus.PM_DONE
        state.stages.append(StageResult(
            stage="pm",
            status="done",
            output_message=pm_msg.content,
            started_at=started,
            finished_at=datetime.now(),
        ))
        log_event(task_id, "agent_output", "pm", pm_msg.content)
        return pm_msg

    async def _run_developer(
        self,
        pm_msg: AgentMessage,
        state: TaskState,
        fix_round: int = 0,
        fix_context: dict[str, Any] | None = None,
    ) -> AgentMessage:
        """执行 Developer 阶段。"""
        state.status = TaskStatus.DEV_RUNNING
        started = datetime.now()

        dev_msg = await self.developer.process_pm_output(pm_msg, fix_context)

        state.status = TaskStatus.DEV_DONE
        state.stages.append(StageResult(
            stage=f"dev_r{fix_round}",
            status="done",
            output_message=dev_msg.content,
            started_at=started,
            finished_at=datetime.now(),
        ))
        log_event(state.task_id, "agent_output", "developer", dev_msg.content)

        # 保存生成的代码到磁盘
        self._save_code_to_disk(dev_msg, state.task_id, fix_round)
        return dev_msg

    async def _run_reviewer(
        self, dev_msg: AgentMessage, state: TaskState, fix_round: int = 0,
    ) -> AgentMessage:
        """执行 Reviewer 阶段。"""
        state.status = TaskStatus.REVIEW_RUNNING
        started = datetime.now()

        review_msg = await self.reviewer.process_dev_output(dev_msg)

        state.status = TaskStatus.REVIEW_DONE
        state.stages.append(StageResult(
            stage=f"review_r{fix_round}",
            status="done",
            output_message=review_msg.content,
            started_at=started,
            finished_at=datetime.now(),
        ))
        log_event(state.task_id, "agent_output", "reviewer", review_msg.content)
        return review_msg

    async def _run_qa(
        self,
        dev_msg: AgentMessage,
        pm_msg: AgentMessage,
        state: TaskState,
        fix_round: int = 0,
    ) -> AgentMessage:
        """执行 QA 阶段。"""
        state.status = TaskStatus.QA_RUNNING
        started = datetime.now()

        qa_msg = await self.qa.process_dev_output(dev_msg, pm_msg)

        state.status = TaskStatus.QA_DONE
        state.stages.append(StageResult(
            stage=f"qa_r{fix_round}",
            status="done",
            output_message=qa_msg.content,
            started_at=started,
            finished_at=datetime.now(),
        ))
        log_event(state.task_id, "agent_output", "qa", qa_msg.content)
        return qa_msg

    async def _run_sandbox(
        self,
        dev_msg: AgentMessage,
        qa_msg: AgentMessage,
        task_id: str,
        state: TaskState,
        fix_round: int = 0,
    ) -> SandboxResult:
        """执行沙箱阶段。"""
        state.status = TaskStatus.SANDBOX_RUNNING
        started = datetime.now()

        dev_output = dev_msg.unwrap_as(DevOutput)
        qa_output = qa_msg.unwrap_as(QAOutput)
        result = await self.sandbox.execute(dev_output, qa_output, task_id)

        state.status = TaskStatus.SANDBOX_DONE
        state.stages.append(StageResult(
            stage=f"sandbox_r{fix_round}",
            status="done" if result.passed else "failed",
            output_message=result.model_dump(mode="json"),  # type: ignore[arg-type]
            started_at=started,
            finished_at=datetime.now(),
            error=result.error_summary,
        ))
        log_event(task_id, "sandbox_result", "sandbox", result.model_dump(mode="json"))
        return result

    # ── 修复上下文构建 ──────────────────────────────────────

    def _build_fix_context(
        self,
        dev_msg: AgentMessage,
        review_msg: AgentMessage,
        sandbox_result: SandboxResult,
        fix_round: int,
    ) -> dict[str, Any]:
        """构建传给 Developer 的修复上下文。

        思路：汇总所有失败信息（Lint、测试失败、运行错误、审查问题），
        以结构化方式传递给 Developer，让其精确理解需要修复什么。
        """
        dev_output = dev_msg.unwrap_as(DevOutput)

        # 提取前一轮代码
        previous_code_parts: list[str] = []
        for f in dev_output.files:
            previous_code_parts.append(f"# {f.path}\n{f.content}")

        # 构建错误摘要
        error_parts: list[str] = []

        if sandbox_result.error_summary:
            error_parts.append(sandbox_result.error_summary)

        if sandbox_result.lint_issues:
            lint_summary = "\n".join(
                f"- [{i.tool}] {i.file}:{i.line}: {i.message}"
                for i in sandbox_result.lint_issues[:20]  # 限制数量避免 token 爆
            )
            error_parts.append(f"Lint Issues:\n{lint_summary}")

        if sandbox_result.test_stderr:
            error_parts.append(f"Test Errors:\n{sandbox_result.test_stderr[:1000]}")

        if sandbox_result.test_stdout and sandbox_result.test_exit_code != 0:
            error_parts.append(f"Test Output:\n{sandbox_result.test_stdout[:1000]}")

        # 审查问题
        try:
            review = review_msg.unwrap_as(ReviewReport)
            critical_issues = [i for i in review.issues if i.severity in ("critical", "major")]
            if critical_issues:
                review_summary = "\n".join(
                    f"- [{i.severity}][{i.category}] {i.file}: {i.description} → {i.suggestion}"
                    for i in critical_issues[:10]
                )
                error_parts.append(f"Critical Review Issues:\n{review_summary}")
        except Exception:
            pass

        return {
            "fix_round": fix_round,
            "previous_code": "\n".join(previous_code_parts[:5]),
            "error_summary": "\n\n".join(error_parts),
            "review_issues": "\n".join(error_parts[-1:]) if error_parts else "",
        }

    # ── 持久化 ──────────────────────────────────────────────

    def _save_code_to_disk(
        self, dev_msg: AgentMessage, task_id: str, fix_round: int,
    ) -> None:
        """将生成的代码保存到磁盘（供人工检查和 Streamlit 展示）。"""
        dev_output = dev_msg.unwrap_as(DevOutput)
        task_dir = self.output_dir / task_id / f"round_{fix_round}"
        task_dir.mkdir(parents=True, exist_ok=True)

        for f in dev_output.files:
            file_path = task_dir / f.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f.content, encoding="utf-8")

        logger.debug("[%s] Saved %d files to %s", task_id[:8], len(dev_output.files), task_dir)

    def _persist_state(self, state: TaskState) -> None:
        """持久化任务状态到 JSON 文件。"""
        try:
            state_dir = self.output_dir / state.task_id
            state_dir.mkdir(parents=True, exist_ok=True)
            state_path = state_dir / "state.json"
            state_path.write_text(
                state.model_dump_json(indent=2),
                encoding="utf-8",
            )
            log_event(state.task_id, "state_persisted", "scheduler", state.model_dump(mode="json"))
        except Exception as e:
            logger.error("[%s] Failed to persist state: %s", state.task_id[:8], e)

    @staticmethod
    def load_state(task_id: str) -> TaskState | None:
        """从磁盘加载任务状态。

        Args:
            task_id: 任务 ID。

        Returns:
            TaskState 或 None（文件不存在时）。
        """
        state_path = config.data_dir / "tasks" / task_id / "state.json"
        if not state_path.exists():
            return None
        return TaskState.model_validate_json(state_path.read_text(encoding="utf-8"))
