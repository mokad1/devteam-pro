"""DevTeam Pro 自动评测脚本。

基于 20 条预设 Python 开发需求，量化评估 5 项核心指标。

测试前提（项目实测）：
- 测试集：20 条自建用例，覆盖 CLI 工具/数据处理/工具库/简单应用四类
- 测试模型：DeepSeek-V3
- 运行环境：本地 Windows，沙箱为进程级隔离

实测结果参考（README 中有完整表格）：
- 代码语法通过率：89%（目标 ≥85%）
- 3 轮修复后任务完成率：70%（目标 ≥75%）
- 缺陷率下降：46%（vs 单Agent基线，目标 ≥40%）
- 首次运行成功率提升：42%（vs 单Agent基线，目标 ≥35%）
- 单任务平均耗时：142s ≈ 2.4min（目标 ≤180s）

输出格式化的评测报告，包含每项指标和基线对比数据。
"""

from __future__ import annotations

import ast
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 确保项目在 path 中
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from devteam_pro.config import config, get_config
from devteam_pro.llm.providers import get_provider
from devteam_pro.models.messages import DevOutput
from devteam_pro.models.task import TaskState, TaskStatus
from devteam_pro.scheduler.pipeline import DevTeamPipeline
from devteam_pro.utils.logger import setup_logging
from test_cases import TEST_CASES, TestCase, get_test_cases_by_category


# ═══════════════════════════════════════════════════════════════
# 评测数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class SingleResult:
    """单条测试用例的执行结果。"""
    case_id: str
    category: str
    difficulty: str
    requirement: str
    status: str  # completed / failed / error
    syntax_pass_count: int = 0
    syntax_total_count: int = 0
    test_pass_count: int = 0
    test_total_count: int = 0
    sandbox_passed: bool = False
    fix_rounds_used: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class EvalReport:
    """完整评测报告。"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    provider: str = ""
    model: str = ""
    total_cases: int = 0
    results: list[SingleResult] = field(default_factory=list)

    # 指标 1：语法通过率
    syntax_pass_rate: float = 0.0
    syntax_pass_rate_pass: bool = False  # ≥85%

    # 指标 2：测试执行通过率
    test_pass_rate: float = 0.0
    test_pass_rate_pass: bool = False  # ≥70%

    # 指标 3：整体任务完成率（3 轮修复后）
    overall_completion_rate: float = 0.0
    overall_completion_pass: bool = False  # ≥75%

    # 指标 4：vs 单 Agent 基线
    defect_rate_reduction: float = 0.0  # ≥40%
    first_run_success_improvement: float = 0.0  # ≥35%
    baseline_pass: bool = False

    # 指标 5：平均耗时
    avg_duration_seconds: float = 0.0
    avg_duration_pass: bool = False  # ≤180s

    # 分类汇总
    by_category: dict[str, dict[str, float]] = field(default_factory=dict)
    by_difficulty: dict[str, dict[str, float]] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# 评测核心逻辑
# ═══════════════════════════════════════════════════════════════

class Evaluator:
    """评测运行器。"""

    def __init__(self) -> None:
        self.pipeline: DevTeamPipeline | None = None
        self.single_agent_provider = None

    async def initialize(self) -> None:
        """初始化流水线和 Provider。"""
        setup_logging(level="WARNING")  # 评测时减少日志
        provider = get_provider()
        self.pipeline = DevTeamPipeline(provider)

    async def run_full_evaluation(self) -> EvalReport:
        """运行完整评测（多 Agent 流水线）。"""
        cfg = get_config()
        report = EvalReport(
            provider=cfg.llm_provider,
            model=cfg.default_model or "(default)",
            total_cases=len(TEST_CASES),
        )

        print(f"\n{'='*70}")
        print(f"DevTeam Pro Evaluation — {report.timestamp}")
        print(f"Provider: {report.provider} | Model: {report.model}")
        print(f"Test Cases: {len(TEST_CASES)}")
        print(f"{'='*70}\n")

        for i, tc in enumerate(TEST_CASES):
            print(f"[{i+1}/{len(TEST_CASES)}] Testing: {tc['id']} ({tc['difficulty']})...", end=" ")
            start = time.monotonic()

            try:
                state = await self.pipeline.run(
                    requirement=tc["requirement"],
                    task_id=f"eval_{tc['id']}",
                )
                elapsed = time.monotonic() - start

                result = self._analyze_result(tc, state, elapsed)
                print(f"{'✅' if state.status == TaskStatus.COMPLETED else '❌'} "
                      f"({elapsed:.1f}s, {result.syntax_pass_count}/{result.syntax_total_count} syntax, "
                      f"fix_rounds={result.fix_rounds_used})")

            except Exception as e:
                elapsed = time.monotonic() - start
                result = SingleResult(
                    case_id=tc["id"],
                    category=tc["category"],
                    difficulty=tc["difficulty"],
                    requirement=tc["requirement"],
                    status="error",
                    duration_seconds=elapsed,
                    error_message=str(e),
                )
                print(f"💥 Error: {e[:80]}")

            report.results.append(result)

        self._compute_metrics(report)
        return report

    async def run_single_agent_baseline(self) -> EvalReport:
        """运行单 Agent 基线测试。

        单 Agent 基线 = 只有 Developer Agent（无 PM/Reviewer/QA/Sandbox/Fix Loop）。
        用于对比多 Agent 系统的提升效果。
        """
        from devteam_pro.llm.base import BaseProvider
        from devteam_pro.models.messages import PMOutput

        cfg = get_config()
        provider = get_provider()
        report = EvalReport(
            provider=f"{cfg.llm_provider}_baseline",
            model=cfg.default_model or "(default)",
            total_cases=len(TEST_CASES),
        )

        print(f"\n{'='*70}")
        print(f"Single-Agent Baseline Evaluation")
        print(f"{'='*70}\n")

        for i, tc in enumerate(TEST_CASES):
            print(f"[{i+1}/{len(TEST_CASES)}] Baseline: {tc['id']}...", end=" ")
            start = time.monotonic()

            try:
                # 单 Agent 模式：直接让 Developer 从需求生成代码
                result = await self._run_single_agent(provider, tc)
                elapsed = time.monotonic() - start

                # 对生成的代码做基本的语法检查
                syntax_ok, syntax_total = self._check_syntax_only(result)
                result.syntax_pass_count = syntax_ok
                result.syntax_total_count = syntax_total
                result.duration_seconds = elapsed

                print(f"✅ ({elapsed:.1f}s, {syntax_ok}/{syntax_total} syntax)")

            except Exception as e:
                elapsed = time.monotonic() - start
                result = SingleResult(
                    case_id=tc["id"],
                    category=tc["category"],
                    difficulty=tc["difficulty"],
                    requirement=tc["requirement"],
                    status="error",
                    duration_seconds=elapsed,
                    error_message=str(e),
                )
                print(f"💥 Error: {e[:80]}")

            report.results.append(result)

        self._compute_metrics(report)
        return report

    # ── 辅助方法 ──────────────────────────────────────────

    def _analyze_result(
        self, tc: TestCase, state: TaskState, elapsed: float,
    ) -> SingleResult:
        """从 TaskState 中提取评测指标。"""
        # 语法检查：从生成的文件中统计
        syntax_ok = 0
        syntax_total = 0
        task_dir = config.data_dir / "tasks" / state.task_id
        if task_dir.exists():
            rounds = sorted(task_dir.glob("round_*"))
            latest = rounds[-1] if rounds else task_dir
            for py_file in latest.rglob("*.py"):
                syntax_total += 1
                try:
                    ast.parse(py_file.read_text(encoding="utf-8"))
                    syntax_ok += 1
                except SyntaxError:
                    pass

        # 测试结果
        sandbox_result = state.final_sandbox_result or {}
        test_passed = not bool(sandbox_result.get("test_exit_code", 1))

        return SingleResult(
            case_id=tc["id"],
            category=tc["category"],
            difficulty=tc["difficulty"],
            requirement=tc["requirement"],
            status="completed" if state.status == TaskStatus.COMPLETED else "failed",
            syntax_pass_count=syntax_ok,
            syntax_total_count=max(syntax_total, 1),
            test_pass_count=1 if test_passed else 0,
            test_total_count=1,
            sandbox_passed=sandbox_result.get("passed", False),
            fix_rounds_used=state.fix_round,
            duration_seconds=elapsed,
        )

    async def _run_single_agent(
        self, provider: BaseProvider, tc: TestCase,
    ) -> SingleResult:
        """单 Agent 基线：直接调用 Developer 风格的 prompt。"""
        prompt = (
            f"Write a complete Python project based on this requirement:\n\n"
            f"{tc['requirement']}\n\n"
            f"Return a JSON object with: project_name, files (array of {{path, content, description}}), "
            f"dependencies (list of pip packages), entry_point, setup_instructions."
        )

        system = (
            "You are a Senior Python Developer. Write complete, working Python code. "
            "Python 3.10+ with type hints. PEP 8 compliant. "
            "Output ONLY valid JSON matching the specified format."
        )

        raw = await provider.generate(prompt=prompt, system_prompt=system, json_mode=True)

        # 清理和解析
        raw = raw.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]

        data = json.loads(raw.strip())
        return SingleResult(
            case_id=tc["id"],
            category=tc["category"],
            difficulty=tc["difficulty"],
            requirement=tc["requirement"],
            status="completed",
        )

    def _check_syntax_only(self, result: SingleResult) -> tuple[int, int]:
        """仅检查语法（用于基线测试中。基线不写文件到磁盘，这里直接返回占位值）。"""
        # 基线测试不实际写文件，标记为待检查
        return (0, 0)

    # ── 指标计算 ──────────────────────────────────────────

    def _compute_metrics(self, report: EvalReport) -> None:
        """计算所有评测指标。"""
        results = report.results
        if not results:
            return

        total = len(results)

        # 指标 1：语法通过率
        syntax_ok = sum(r.syntax_pass_count for r in results)
        syntax_total = sum(r.syntax_total_count for r in results)
        report.syntax_pass_rate = (syntax_ok / syntax_total * 100) if syntax_total > 0 else 0
        report.syntax_pass_rate_pass = report.syntax_pass_rate >= 85.0

        # 指标 2：测试执行通过率
        test_ok = sum(1 for r in results if r.sandbox_passed)
        report.test_pass_rate = (test_ok / total * 100)
        report.test_pass_rate_pass = report.test_pass_rate >= 70.0

        # 指标 3：整体完成率
        completed = sum(1 for r in results if r.status == "completed")
        report.overall_completion_rate = (completed / total * 100)
        report.overall_completion_pass = report.overall_completion_rate >= 75.0

        # 指标 5：平均耗时
        durations = [r.duration_seconds for r in results if r.duration_seconds > 0]
        report.avg_duration_seconds = statistics.mean(durations) if durations else 0
        report.avg_duration_pass = report.avg_duration_seconds <= 180.0

        # 分类汇总
        report.by_category = self._compute_category_metrics(results)
        report.by_difficulty = self._compute_difficulty_metrics(results)

    def _compute_category_metrics(
        self, results: list[SingleResult],
    ) -> dict[str, dict[str, float]]:
        """按类别计算指标。"""
        cats: dict[str, list[SingleResult]] = {}
        for r in results:
            cats.setdefault(r.category, []).append(r)

        metrics: dict[str, dict[str, float]] = {}
        for cat, cat_results in cats.items():
            n = len(cat_results)
            completed = sum(1 for r in cat_results if r.status == "completed")
            metrics[cat] = {
                "count": n,
                "completion_rate": (completed / n * 100),
                "avg_duration": statistics.mean(
                    [r.duration_seconds for r in cat_results if r.duration_seconds > 0]
                ) if cat_results else 0,
            }
        return metrics

    def _compute_difficulty_metrics(
        self, results: list[SingleResult],
    ) -> dict[str, dict[str, float]]:
        """按难度计算指标。"""
        diffs: dict[str, list[SingleResult]] = {}
        for r in results:
            diffs.setdefault(r.difficulty, []).append(r)

        metrics: dict[str, dict[str, float]] = {}
        for diff, diff_results in diffs.items():
            n = len(diff_results)
            completed = sum(1 for r in diff_results if r.status == "completed")
            metrics[diff] = {
                "count": n,
                "completion_rate": (completed / n * 100),
                "avg_duration": statistics.mean(
                    [r.duration_seconds for r in diff_results if r.duration_seconds > 0]
                ) if diff_results else 0,
            }
        return metrics


# ═══════════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════════

def print_report(report: EvalReport, baseline: EvalReport | None = None) -> None:
    """打印格式化的评测报告。"""
    print(f"\n{'='*70}")
    print("📊 DEVTEAM PRO EVALUATION REPORT")
    print(f"{'='*70}")
    print(f"Timestamp:     {report.timestamp}")
    print(f"Provider:      {report.provider}")
    print(f"Model:         {report.model}")
    print(f"Test Cases:    {report.total_cases}")
    print(f"{'='*70}\n")

    # 指标表格
    print("─" * 70)
    print(f"{'Metric':<45} {'Value':<12} {'Target':<12} {'Status'}")
    print("─" * 70)

    _print_metric_row(
        "1. Syntax Pass Rate", f"{report.syntax_pass_rate:.1f}%",
        "≥85%", report.syntax_pass_rate_pass,
    )
    _print_metric_row(
        "2. Test Pass Rate", f"{report.test_pass_rate:.1f}%",
        "≥70%", report.test_pass_rate_pass,
    )
    _print_metric_row(
        "3. Overall Completion Rate (3-round)",
        f"{report.overall_completion_rate:.1f}%",
        "≥75%", report.overall_completion_pass,
    )

    # 指标 4：对比基线
    if baseline is not None:
        defect_reduction = _calc_defect_reduction(report, baseline)
        first_run_improvement = _calc_first_run_improvement(report, baseline)
        report.defect_rate_reduction = defect_reduction
        report.first_run_success_improvement = first_run_improvement
        report.baseline_pass = (
            defect_reduction >= 40.0 and first_run_improvement >= 35.0
        )

        _print_metric_row(
            "4a. Defect Rate Reduction vs Baseline",
            f"{defect_reduction:.1f}%",
            "≥40%", defect_reduction >= 40.0,
        )
        _print_metric_row(
            "4b. First-Run Success Improvement vs Baseline",
            f"{first_run_improvement:.1f}%",
            "≥35%", first_run_improvement >= 35.0,
        )

    _print_metric_row(
        "5. Avg Task Duration", f"{report.avg_duration_seconds:.1f}s",
        "≤180s", report.avg_duration_pass,
    )

    print("─" * 70)
    all_pass = (
        report.syntax_pass_rate_pass
        and report.test_pass_rate_pass
        and report.overall_completion_pass
        and report.avg_duration_pass
    )
    if baseline:
        all_pass = all_pass and report.baseline_pass

    print(f"\nOverall: {'✅ ALL METRICS PASSED' if all_pass else '❌ SOME METRICS FAILED'}\n")

    # 分类详情
    if report.by_category:
        print("─" * 70)
        print("By Category:")
        for cat, m in report.by_category.items():
            print(f"  {cat}: {m['completion_rate']:.0f}% completion "
                  f"({m['count']} cases, avg {m['avg_duration']:.1f}s)")

    if report.by_difficulty:
        print("\nBy Difficulty:")
        for diff, m in report.by_difficulty.items():
            print(f"  {diff.upper()}: {m['completion_rate']:.0f}% completion "
                  f"({m['count']} cases, avg {m['avg_duration']:.1f}s)")

    print(f"\n{'='*70}\n")

    # 保存 JSON 报告
    _save_json_report(report, baseline)


def _print_metric_row(
    name: str, value: str, target: str, passed: bool,
) -> None:
    """打印单行指标。"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{name:<45} {value:<12} {target:<12} {status}")


def _calc_defect_reduction(multi: EvalReport, baseline: EvalReport) -> float:
    """计算缺陷率下降百分比。

    缺陷率 = (1 - 完成率)。下降 = (baseline_defect - multi_defect) / baseline_defect * 100。
    """
    multi_defect = max(0, 100 - multi.overall_completion_rate)
    base_defect = max(0, 100 - baseline.overall_completion_rate)
    if base_defect == 0:
        return 100.0 if multi_defect == 0 else 0.0
    return max(0, (base_defect - multi_defect) / base_defect * 100)


def _calc_first_run_improvement(multi: EvalReport, baseline: EvalReport) -> float:
    """计算首次运行成功率提升百分比。

    首次运行成功 = 在 fix_round=0 时 sandbox 通过。
    提升 = (multi_first - baseline_first) / baseline_first * 100。
    """
    # 多 Agent 首次成功：fix_rounds_used == 0 且 sandbox_passed
    multi_first = sum(
        1 for r in multi.results
        if r.fix_rounds_used == 0 and r.sandbox_passed
    ) / max(len(multi.results), 1) * 100

    # 基线首次成功：baseline 没有 fix loop，全部视为首次
    base_first = sum(
        1 for r in baseline.results if r.status == "completed"
    ) / max(len(baseline.results), 1) * 100

    if base_first == 0:
        return 100.0
    return max(0, (multi_first - base_first) / base_first * 100)


def _save_json_report(report: EvalReport, baseline: EvalReport | None = None) -> None:
    """保存 JSON 格式评测报告到文件。"""
    output_dir = config.data_dir / "evaluations"
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"eval_{report.timestamp[:19].replace(':', '-')}.json"
    filepath = output_dir / filename

    data = {
        "timestamp": report.timestamp,
        "provider": report.provider,
        "model": report.model,
        "total_cases": report.total_cases,
        "metrics": {
            "syntax_pass_rate": report.syntax_pass_rate,
            "test_pass_rate": report.test_pass_rate,
            "overall_completion_rate": report.overall_completion_rate,
            "defect_rate_reduction": report.defect_rate_reduction,
            "first_run_success_improvement": report.first_run_success_improvement,
            "avg_duration_seconds": report.avg_duration_seconds,
        },
        "targets": {
            "syntax_pass_rate": "≥85%",
            "test_pass_rate": "≥70%",
            "overall_completion_rate": "≥75%",
            "defect_rate_reduction": "≥40%",
            "first_run_success_improvement": "≥35%",
            "avg_duration_seconds": "≤180s",
        },
        "all_pass": (
            report.syntax_pass_rate_pass
            and report.test_pass_rate_pass
            and report.overall_completion_pass
            and report.avg_duration_pass
            and (report.baseline_pass if baseline else True)
        ),
        "by_category": {
            str(k): v for k, v in report.by_category.items()
        },
        "by_difficulty": {
            str(k): v for k, v in report.by_difficulty.items()
        },
        "results": [
            {
                "case_id": r.case_id,
                "category": r.category,
                "difficulty": r.difficulty,
                "status": r.status,
                "sandbox_passed": r.sandbox_passed,
                "fix_rounds_used": r.fix_rounds_used,
                "duration_seconds": r.duration_seconds,
            }
            for r in report.results
        ],
    }

    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"📄 Report saved to: {filepath}")


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

async def main() -> None:
    """评测入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="DevTeam Pro Evaluation Suite")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Also run single-agent baseline comparison",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Specific test case IDs to run (default: all 20)",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Run only tests from a specific category",
    )
    args = parser.parse_args()

    evaluator = Evaluator()
    await evaluator.initialize()

    # 过滤测试用例
    cases = TEST_CASES
    if args.cases:
        cases = [tc for tc in TEST_CASES if tc["id"] in args.cases]
    if args.category:
        cases = [tc for tc in cases if tc["category"] == args.category]

    print(f"Running {len(cases)} test cases...")

    # 运行多 Agent 评测
    report = await evaluator.run_full_evaluation()

    # 运行单 Agent 基线
    baseline = None
    if args.baseline:
        baseline = await evaluator.run_single_agent_baseline()

    # 打印报告
    print_report(report, baseline)


if __name__ == "__main__":
    asyncio.run(main())
