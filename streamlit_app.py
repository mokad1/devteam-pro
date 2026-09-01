"""DevTeam Pro — Streamlit 可视化调试面板。

功能：
- 需求输入 + Provider 配置
- 流水线实时状态展示（4 阶段 + 修复轮次）
- 每个 Agent 的输入/输出 JSON 折叠查看
- 沙箱执行日志（Lint、测试、运行结果）
- 最终代码文件预览 + 下载
- 任务历史选择 + 重放
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

# 确保项目根目录在 path 中
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from devteam_pro.config import config, get_config
from devteam_pro.llm.providers import get_provider
from devteam_pro.models.task import TaskState, TaskStatus
from devteam_pro.scheduler.pipeline import DevTeamPipeline
from devteam_pro.utils.logger import setup_logging

# ── 页面配置 ────────────────────────────────────────────────

st.set_page_config(
    page_title="DevTeam Pro",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🛠️ DevTeam Pro — 多Agent代码开发协同系统")
st.caption("PM → Developer → Reviewer → QA → Sandbox → Auto-Fix")

# ── 初始化 ──────────────────────────────────────────────────

setup_logging()


@st.cache_resource
def get_pipeline() -> DevTeamPipeline | None:
    """获取流水线实例（缓存避免重复创建）。"""
    try:
        provider = get_provider()
        return DevTeamPipeline(provider)
    except Exception as e:
        st.error(f"Failed to initialize pipeline: {e}")
        return None


# ── 侧边栏 ──────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Configuration")

    cfg = get_config()
    st.metric("Provider", cfg.llm_provider.upper())
    st.metric("Model", cfg.default_model or "(default)")
    st.metric("Max Fix Rounds", cfg.max_fix_rounds)
    st.metric("Sandbox Timeout", f"{cfg.sandbox_timeout}s")

    st.divider()

    st.header("📝 New Task")
    requirement = st.text_area(
        "Requirement (Natural Language)",
        height=150,
        placeholder="e.g., Create a CLI tool that generates random secure passwords with configurable length and character sets...",
    )

    col1, col2 = st.columns(2)
    with col1:
        run_btn = st.button("▶️ Run Pipeline", type="primary", use_container_width=True)
    with col2:
        stop_btn = st.button("⏹️ Stop", use_container_width=True)

    st.divider()

    st.header("📂 Task History")
    tasks_dir = config.data_dir / "tasks"
    if tasks_dir.exists():
        task_ids = sorted(
            [d.name for d in tasks_dir.iterdir() if d.is_dir()],
            reverse=True,
        )
        selected_task = st.selectbox(
            "Select task to replay",
            ["(none)"] + task_ids,
        )
    else:
        selected_task = "(none)"

    if selected_task != "(none)":
        if st.button("🔄 Replay Task", use_container_width=True):
            st.session_state["replay_task_id"] = selected_task

# ── 主区域 ──────────────────────────────────────────────────

pipeline = get_pipeline()

# Session state 用于跟踪运行状态
if "running" not in st.session_state:
    st.session_state["running"] = False
if "current_state" not in st.session_state:
    st.session_state["current_state"] = None
if "run_log" not in st.session_state:
    st.session_state["run_log"] = []


async def run_pipeline_async(req: str) -> TaskState:
    """异步执行流水线。"""
    pl = get_pipeline()
    if pl is None:
        raise RuntimeError("Pipeline not initialized")
    return await pl.run(req)


def run_pipeline_sync(req: str) -> None:
    """同步包装器，更新 session state。"""
    st.session_state["running"] = True
    st.session_state["run_log"] = []

    try:
        state = asyncio.run(run_pipeline_async(req))
        st.session_state["current_state"] = state
        st.session_state["run_log"].append({
            "task_id": state.task_id,
            "status": state.status.value,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        st.session_state["run_log"].append({
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        })
    finally:
        st.session_state["running"] = False


# ── 执行按钮逻辑 ────────────────────────────────────────────

if run_btn and requirement.strip():
    with st.spinner("Running pipeline..."):
        run_pipeline_sync(requirement.strip())
    st.rerun()

# ── 辅助渲染函数 ────────────────────────────────────────────

def _show_pipeline_status(state: TaskState) -> None:
    """渲染流水线状态进度条。"""
    st.header("📊 Pipeline Status")

    stages = [
        ("PM", state.status in _status_after("pm_done")),
        ("Developer", state.status in _status_after("dev_done")),
        ("Reviewer", state.status in _status_after("review_done")),
        ("QA", state.status in _status_after("qa_done")),
        ("Sandbox", state.status in _status_after("sandbox_done")),
    ]

    cols = st.columns(len(stages))
    for i, (name, done) in enumerate(stages):
        with cols[i]:
            icon = "✅" if done else ("🔄" if i == _active_stage_index(state) else "⏳")
            st.markdown(f"### {icon}\n**{name}**")

    # 修复轮次
    if state.fix_round > 0:
        st.info(f"🔄 Auto-fix rounds: **{state.fix_round}/{state.max_fix_rounds}**")

    # 时间统计
    if state.total_duration_seconds:
        st.caption(
            f"Total: {state.total_duration_seconds:.1f}s | "
            f"Started: {state.started_at} | "
            f"Status: **{state.status.value.upper()}**"
        )


def _status_after(threshold: str) -> set[TaskStatus]:
    """返回大于等于指定状态的所有状态集合。"""
    statuses = list(TaskStatus)
    idx = statuses.index(TaskStatus(threshold))
    return set(statuses[idx:] + [TaskStatus.COMPLETED, TaskStatus.FAILED])


def _active_stage_index(state: TaskState) -> int:
    """获取当前活跃的阶段索引。"""
    stage_order = ["pm", "dev", "review", "qa", "sandbox"]
    for i, s in enumerate(stage_order):
        if s in state.status.value:
            return i
    return -1


def _show_agent_outputs(state: TaskState) -> None:
    """渲染各 Agent 的输出（可折叠 JSON）。"""
    st.header("🤖 Agent Outputs")

    for stage in state.stages:
        if stage.output_message is None:
            continue

        agent_name = stage.stage.split("_")[0].upper()
        status_icon = "✅" if stage.status == "done" else "❌"

        with st.expander(f"{status_icon} **{agent_name}** ({stage.stage}) — {_format_time(stage)}"):
            # 显示耗时
            if stage.started_at and stage.finished_at:
                duration = (stage.finished_at - stage.started_at).total_seconds()
                st.caption(f"Duration: {duration:.1f}s")

            if stage.error:
                st.error(stage.error)

            # JSON 格式化展示
            try:
                formatted = json.dumps(stage.output_message, indent=2, ensure_ascii=False)
                st.json(formatted, expanded=False)
            except Exception:
                st.code(str(stage.output_message))


def _show_sandbox_results(state: TaskState) -> None:
    """渲染沙箱执行结果。"""
    sandbox_stages = [s for s in state.stages if s.stage.startswith("sandbox")]
    if not sandbox_stages:
        return

    st.header("🧪 Sandbox Execution")

    for s in sandbox_stages:
        if s.output_message is None:
            continue

        result = s.output_message
        passed = result.get("passed", False)
        icon = "✅" if passed else "❌"

        with st.expander(f"{icon} Sandbox ({s.stage}) — exit_code={result.get('exit_code', '?')}"):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Exit Code", result.get("exit_code", "?"))
            with col2:
                st.metric("Test Exit Code", result.get("test_exit_code", "N/A"))
            with col3:
                st.metric("Time", f"{result.get('execution_time_seconds', 0):.1f}s")

            # Lint issues
            lint_issues = result.get("lint_issues", [])
            if lint_issues:
                st.subheader(f"📏 Lint Issues ({len(lint_issues)})")
                for issue in lint_issues[:20]:
                    st.text(
                        f"[{issue.get('tool', '?')}] {issue.get('file', '?')}:"
                        f"{issue.get('line', '?')}: {issue.get('message', '?')}"
                    )

            # stdout/stderr
            if result.get("stdout"):
                with st.expander("📤 stdout"):
                    st.code(result["stdout"])
            if result.get("stderr"):
                with st.expander("📤 stderr"):
                    st.code(result["stderr"])
            if result.get("test_stdout"):
                with st.expander("🧪 Test Output"):
                    st.code(result["test_stdout"])
            if result.get("test_stderr"):
                with st.expander("🧪 Test Errors"):
                    st.code(result["test_stderr"])

            # Error summary
            if result.get("error_summary"):
                st.error(result["error_summary"])


def _show_generated_code(state: TaskState) -> None:
    """渲染最终生成的代码文件。"""
    st.header("📁 Generated Code")

    task_dir = config.data_dir / "tasks" / state.task_id
    if not task_dir.exists():
        st.caption("No code files found on disk.")
        return

    # 找到最后一轮的代码
    rounds = sorted(task_dir.glob("round_*"), reverse=True)
    if not rounds:
        st.caption("No code rounds found.")
        return

    latest_round = rounds[0]
    py_files = list(latest_round.rglob("*.py"))

    if not py_files:
        st.caption("No Python files generated.")
        return

    st.caption(f"Round: {latest_round.name} — {len(py_files)} files")

    for f in sorted(py_files):
        relative_path = f.relative_to(latest_round)
        with st.expander(f"📄 {relative_path}"):
            try:
                content = f.read_text(encoding="utf-8")
                st.code(content, language="python")
                st.download_button(
                    f"Download {relative_path}",
                    content,
                    file_name=str(relative_path),
                )
            except Exception as e:
                st.error(f"Failed to read: {e}")


def _show_replay(task_id: str) -> None:
    """展示历史任务重放。"""
    st.header(f"🔄 Replay: {task_id}")

    state = DevTeamPipeline.load_state(task_id)
    if state is None:
        st.warning(f"Task state not found for {task_id}")
        return

    _show_pipeline_status(state)
    _show_agent_outputs(state)
    _show_sandbox_results(state)
    _show_generated_code(state)


def _format_time(stage: Any) -> str:
    """格式化阶段时间。"""
    if stage.started_at and stage.finished_at:
        dur = (stage.finished_at - stage.started_at).total_seconds()
        return f"{dur:.1f}s"
    return ""


# ── 状态展示（必须在所有辅助函数定义之后调用，否则 NameError） ──

state: TaskState | None = st.session_state.get("current_state")

if state is not None:
    _show_pipeline_status(state)
    _show_agent_outputs(state)
    _show_sandbox_results(state)
    _show_generated_code(state)
elif selected_task != "(none)" and "replay_task_id" in st.session_state:
    _show_replay(st.session_state["replay_task_id"])


# ── Footer ──────────────────────────────────────────────────

st.divider()
st.caption(
    "DevTeam Pro • Multi-Agent Code Development System • "
    "PM → Developer → Reviewer → QA → Sandbox → Auto-Fix"
)
