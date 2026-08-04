"""Agent 间通信的 Pydantic v2 结构化消息模型。

所有 Agent 间消息传递必须使用这些模型，禁止纯文本聊天传递上下文。
每个模型严格定义字段类型和约束，确保数据传递的类型安全。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field

_T = TypeVar("_T", bound=BaseModel)


# ═══════════════════════════════════════════════════════════════
# 基础类型
# ═══════════════════════════════════════════════════════════════

class Feature(BaseModel):
    """PM 输出的功能条目。"""
    name: str = Field(..., description="功能名称")
    description: str = Field(..., description="功能详细描述")
    priority: Literal["high", "medium", "low"] = Field(
        default="medium", description="优先级"
    )


class TechConstraints(BaseModel):
    """技术约束。"""
    language: str = Field(default="Python", description="编程语言")
    min_version: str = Field(default="3.10", description="最低版本要求")
    forbidden_packages: list[str] = Field(
        default_factory=list, description="禁用包列表"
    )
    required_packages: list[str] = Field(
        default_factory=list, description="必须使用的包"
    )
    max_file_count: int = Field(default=10, description="最大文件数")
    other: str = Field(default="", description="其他约束说明")


class OutputSpec(BaseModel):
    """输出规范。"""
    format: str = Field(default="Python package", description="输出格式")
    include_tests: bool = Field(default=True, description="是否包含测试")
    include_readme: bool = Field(default=True, description="是否包含 README")
    include_requirements: bool = Field(default=True, description="是否包含依赖文件")
    other: str = Field(default="", description="其他规范说明")


class CodeFile(BaseModel):
    """单个代码文件。"""
    path: str = Field(..., description="文件相对路径")
    content: str = Field(..., description="文件完整内容")
    description: str = Field(default="", description="文件说明")


# ═══════════════════════════════════════════════════════════════
# PM Agent 输出
# ═══════════════════════════════════════════════════════════════

class PMOutput(BaseModel):
    """PM Agent 产出：结构化开发需求文档。"""
    requirement_summary: str = Field(..., description="需求概述")
    features: list[Feature] = Field(..., description="功能清单")
    tech_constraints: TechConstraints = Field(
        default_factory=TechConstraints, description="技术约束"
    )
    output_spec: OutputSpec = Field(
        default_factory=OutputSpec, description="输出规范"
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list, description="验收标准"
    )


# ═══════════════════════════════════════════════════════════════
# Developer Agent 输出
# ═══════════════════════════════════════════════════════════════

class DevOutput(BaseModel):
    """Developer Agent 产出：完整项目代码。"""
    project_name: str = Field(..., description="项目名称")
    files: list[CodeFile] = Field(..., description="代码文件列表")
    dependencies: list[str] = Field(..., description="pip 依赖清单")
    entry_point: str = Field(..., description="入口文件路径")
    setup_instructions: str = Field(default="", description="运行说明")
    fix_round: int = Field(default=0, description="当前修复轮次（0=首次生成）")


# ═══════════════════════════════════════════════════════════════
# Reviewer Agent 输出
# ═══════════════════════════════════════════════════════════════

class ReviewIssue(BaseModel):
    """单个代码审查问题。"""
    severity: Literal["critical", "major", "minor", "info"] = Field(
        ..., description="严重级别"
    )
    file: str = Field(..., description="问题所在文件")
    line: int | None = Field(default=None, description="问题所在行号")
    category: Literal[
        "style", "logic", "security", "performance",
        "boundary", "error_handling", "naming", "architecture",
    ] = Field(..., description="问题分类")
    description: str = Field(..., description="问题描述")
    suggestion: str = Field(default="", description="修复建议")


class ReviewReport(BaseModel):
    """Reviewer Agent 产出：完整代码审查报告。"""
    overall_score: float = Field(..., ge=0, le=100, description="综合评分 0-100")
    issues: list[ReviewIssue] = Field(
        default_factory=list, description="问题清单"
    )
    summary: str = Field(default="", description="审查总结")


# ═══════════════════════════════════════════════════════════════
# QA Agent 输出
# ═══════════════════════════════════════════════════════════════

class QAOutput(BaseModel):
    """QA Agent 产出：测试用例集。"""
    test_files: list[CodeFile] = Field(..., description="测试文件列表")
    test_count: int = Field(..., description="测试用例总数")
    coverage_estimate: float = Field(
        default=0.0, ge=0, le=100, description="预估覆盖率"
    )


# ═══════════════════════════════════════════════════════════════
# 沙箱执行结果
# ═══════════════════════════════════════════════════════════════

class LintIssue(BaseModel):
    """单个 Lint 问题。"""
    tool: Literal["flake8", "pylint"] = Field(..., description="Lint 工具名")
    file: str = Field(..., description="文件路径")
    line: int = Field(default=0, description="行号")
    message: str = Field(..., description="问题描述")
    code: str = Field(default="", description="规则编号")


class SandboxResult(BaseModel):
    """沙箱执行完整结果。"""
    exit_code: int = Field(default=-1, description="程序退出码")
    stdout: str = Field(default="", description="标准输出")
    stderr: str = Field(default="", description="标准错误")
    lint_issues: list[LintIssue] = Field(
        default_factory=list, description="Lint 问题列表"
    )
    test_exit_code: int | None = Field(
        default=None, description="pytest 退出码"
    )
    test_stdout: str = Field(default="", description="pytest 标准输出")
    test_stderr: str = Field(default="", description="pytest 标准错误")
    passed: bool = Field(default=False, description="全部测试是否通过")
    error_summary: str | None = Field(
        default=None, description="错误摘要（供 Developer 修复用）"
    )
    execution_time_seconds: float = Field(
        default=0.0, description="执行耗时（秒）"
    )
    venv_path: str = Field(default="", description="使用的虚拟环境路径")


# ═══════════════════════════════════════════════════════════════
# Agent 消息信封
# ═══════════════════════════════════════════════════════════════

AgentRole = Literal["pm", "developer", "reviewer", "qa", "sandbox", "human"]


class AgentMessage(BaseModel):
    """Agent 间通信的标准化消息信封。

    所有 Agent 间通信必须使用此信封包装，content 字段为具体载荷（Pydantic 模型序列化后的 dict）。
    """
    agent_role: AgentRole = Field(..., description="发送方角色")
    task_id: str = Field(..., description="任务唯一标识")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="消息时间戳"
    )
    input_ref: str | None = Field(
        default=None, description="引用上游消息的 task_id + role 标识"
    )
    content: dict[str, Any] = Field(
        default_factory=dict, description="具体载荷（结构化字典）"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外元数据（如修复轮次）"
    )

    def wrap_output(self, output: BaseModel) -> None:
        """将 Pydantic 输出模型序列化存入 content 字段。

        思路：使用 model_dump(mode='json') 保证 datetime 等复杂类型正确序列化。
        """
        self.content = output.model_dump(mode="json")

    def unwrap_as(self, model_cls: type[_T]) -> _T:
        """从 content 字段反序列化为指定 Pydantic 模型。"""
        return model_cls.model_validate(self.content)
