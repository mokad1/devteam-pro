"""沙箱执行器：subprocess 隔离运行生成的代码。

核心功能：
1. 在临时目录创建隔离执行环境
2. 自动创建 venv 并安装依赖
3. 运行 pytest 测试套件
4. 运行入口脚本验证语法
5. 收集所有输出（stdout/stderr/exit code）
6. 生成结构化 SandboxResult 供修复闭环使用

设计思路：
- 使用 tempfile.TemporaryDirectory 确保执行后自动清理
- 超时机制防止死循环/阻塞的代码
- 所有异常被捕获并转化为 SandboxResult（不会让流水线崩溃）
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from devteam_pro.config import config
from devteam_pro.models.messages import CodeFile, DevOutput, LintIssue, QAOutput, SandboxResult
from devteam_pro.sandbox.linter import LinterRunner
from devteam_pro.utils.logger import get_logger

logger = get_logger("sandbox.executor")


class SandboxExecutor:
    """沙箱代码执行器。

    在隔离的临时目录中执行生成的代码，包括：
    - 创建虚拟环境
    - 安装依赖
    - 运行 Lint 检查
    - 运行 pytest 测试
    - 运行入口脚本验证
    """

    def __init__(self, timeout: int | None = None) -> None:
        """初始化执行器。

        Args:
            timeout: 执行超时（秒），默认从配置读取。
        """
        self.timeout = timeout or config.sandbox_timeout

    # ── 主入口 ──────────────────────────────────────────────

    async def execute(
        self,
        dev_output: DevOutput,
        qa_output: QAOutput | None = None,
        task_id: str = "",
    ) -> SandboxResult:
        """在沙箱中执行完整的代码 + 测试。

        Args:
            dev_output: Developer 生成的代码。
            qa_output: QA 生成的测试用例（可选）。
            task_id: 任务标识。

        Returns:
            SandboxResult：包含所有执行结果。
        """
        start_time = time.monotonic()

        # 创建临时工作目录
        with tempfile.TemporaryDirectory(prefix=f"devteam_{task_id[:8]}_") as tmp_dir:
            work_dir = Path(tmp_dir)
            project_dir = work_dir / dev_output.project_name
            project_dir.mkdir(parents=True, exist_ok=True)

            logger.info("[%s] Sandbox created at %s", task_id[:8], project_dir)

            try:
                # 1. 写入代码文件
                self._write_files(project_dir, dev_output.files)
                if qa_output:
                    self._write_files(project_dir, qa_output.test_files)

                # 2. 创建 venv 并安装依赖
                venv_path = await self._setup_venv(project_dir, dev_output, task_id)

                # 3. 运行 Lint 检查
                linter = LinterRunner(project_dir)
                lint_issues = await linter.run_all()

                # 4. 运行语法检查（ast.parse，不需要 venv）
                syntax_ok, syntax_error = self._check_syntax(project_dir, dev_output)

                # 5. 运行入口脚本
                run_exit, run_stdout, run_stderr = await self._run_entry_point(
                    project_dir, dev_output, venv_path, task_id,
                )

                # 6. 运行 pytest（如果有测试）
                test_exit = None
                test_stdout = ""
                test_stderr = ""
                if qa_output and qa_output.test_files:
                    test_exit, test_stdout, test_stderr = await self._run_tests(
                        project_dir, venv_path, task_id,
                    )

                # 7. 汇总结果
                all_passed = (
                    syntax_ok
                    and run_exit == 0
                    and (test_exit is None or test_exit == 0)
                )

                error_parts: list[str] = []
                if not syntax_ok:
                    error_parts.append(f"Syntax Error: {syntax_error}")
                if run_exit != 0:
                    error_parts.append(f"Run Error (exit={run_exit}): {run_stderr[:500]}")
                if test_exit is not None and test_exit != 0:
                    error_parts.append(f"Test Failures:\n{test_stderr[:1000]}")
                critical_lints = [i for i in lint_issues if i.code.startswith("E") or i.code.startswith("F")]
                if critical_lints:
                    error_parts.append(f"Critical Lint Issues: {len(critical_lints)}")

                elapsed = time.monotonic() - start_time
                result = SandboxResult(
                    exit_code=run_exit,
                    stdout=run_stdout[:2000],
                    stderr=run_stderr[:2000],
                    lint_issues=lint_issues,
                    test_exit_code=test_exit,
                    test_stdout=test_stdout[:2000],
                    test_stderr=test_stderr[:2000],
                    passed=all_passed,
                    error_summary="\n".join(error_parts) if error_parts else None,
                    execution_time_seconds=round(elapsed, 2),
                    venv_path=str(venv_path),
                )

                logger.info(
                    "[%s] Sandbox result: passed=%s, lint_issues=%d, time=%.1fs",
                    task_id[:8], all_passed, len(lint_issues), elapsed,
                )
                return result

            except Exception as e:
                elapsed = time.monotonic() - start_time
                logger.error("[%s] Sandbox setup failed: %s", task_id[:8], e)
                return SandboxResult(
                    exit_code=-1,
                    stderr=str(e),
                    passed=False,
                    error_summary=f"Sandbox setup error: {e}",
                    execution_time_seconds=round(elapsed, 2),
                )

    # ── 文件写入 ─────────────────────────────────────────────

    def _write_files(self, project_dir: Path, files: list[CodeFile]) -> None:
        """将 CodeFile 列表写入磁盘。

        Args:
            project_dir: 项目根目录。
            files: 要写入的文件列表。
        """
        for f in files:
            file_path = project_dir / f.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f.content, encoding="utf-8")
            logger.debug("Wrote %s (%d chars)", f.path, len(f.content))

    # ── Venv 设置 ───────────────────────────────────────────

    async def _setup_venv(
        self,
        project_dir: Path,
        dev_output: DevOutput,
        task_id: str,
    ) -> Path:
        """创建虚拟环境并安装依赖。

        Args:
            project_dir: 项目目录。
            dev_output: 开发者输出（含依赖列表）。
            task_id: 任务标识。

        Returns:
            venv 的根路径。

        思路：使用 subprocess 调用系统 Python 创建 venv，然后 pip install。
        如果依赖安装失败，记录警告但不阻塞后续步骤。
        """
        venv_path = project_dir / ".venv"

        # 创建 venv
        logger.info("[%s] Creating venv at %s", task_id[:8], venv_path)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                capture_output=True, text=True, timeout=60,
                check=False,
            )
            if result.returncode != 0:
                logger.warning("[%s] venv creation warning: %s", task_id[:8], result.stderr)
        except subprocess.TimeoutExpired:
            logger.error("[%s] venv creation timed out", task_id[:8])
            return venv_path

        # 确定 pip 路径
        pip_path = (
            venv_path / "Scripts" / "pip.exe" if sys.platform == "win32"
            else venv_path / "bin" / "pip"
        )

        # 安装依赖
        all_deps = list(dev_output.dependencies) + ["pytest"]
        if all_deps:
            logger.info("[%s] Installing deps: %s", task_id[:8], all_deps)
            try:
                result = subprocess.run(
                    [str(pip_path), "install", "--quiet", "--disable-pip-version-check"]
                    + all_deps,
                    capture_output=True, text=True,
                    timeout=120,
                    check=False,
                )
                if result.returncode != 0:
                    logger.warning(
                        "[%s] pip install partially failed: %s",
                        task_id[:8], result.stderr[:300],
                    )
            except subprocess.TimeoutExpired:
                logger.error("[%s] pip install timed out", task_id[:8])

        return venv_path

    # ── 语法检查 ────────────────────────────────────────────

    def _check_syntax(
        self, project_dir: Path, dev_output: DevOutput,
    ) -> tuple[bool, str]:
        """使用 ast.parse 检查所有 Python 文件的语法。

        Args:
            project_dir: 项目目录。
            dev_output: 开发者输出。

        Returns:
            (syntax_ok, error_message) 元组。

        思路：ast.parse 是 Python 内置模块，不依赖第三方工具。
        """
        import ast

        for f in dev_output.files:
            if not f.path.endswith(".py"):
                continue
            file_path = project_dir / f.path
            if not file_path.exists():
                continue
            try:
                source = file_path.read_text(encoding="utf-8")
                ast.parse(source, filename=f.path)
            except SyntaxError as e:
                return False, f"{f.path}:{e.lineno}: {e.msg}"
        return True, ""

    # ── 运行入口 ────────────────────────────────────────────

    async def _run_entry_point(
        self,
        project_dir: Path,
        dev_output: DevOutput,
        venv_path: Path,
        task_id: str,
    ) -> tuple[int, str, str]:
        """运行项目的入口脚本。

        Returns:
            (exit_code, stdout, stderr) 元组。
        """
        python_path = (
            venv_path / "Scripts" / "python.exe" if sys.platform == "win32"
            else venv_path / "bin" / "python"
        )
        entry = project_dir / dev_output.entry_point

        if not entry.exists():
            return -1, "", f"Entry point not found: {dev_output.entry_point}"

        logger.info("[%s] Running entry: %s", task_id[:8], dev_output.entry_point)
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [str(python_path), str(entry)],
                capture_output=True, text=True,
                timeout=self.timeout,
                cwd=str(project_dir),
                check=False,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Entry point timed out after {self.timeout}s"
        except Exception as e:
            return -1, "", str(e)

    # ── 运行测试 ────────────────────────────────────────────

    async def _run_tests(
        self,
        project_dir: Path,
        venv_path: Path,
        task_id: str,
    ) -> tuple[int, str, str]:
        """运行 pytest 测试套件。

        Returns:
            (exit_code, stdout, stderr) 元组。
        """
        pytest_path = (
            venv_path / "Scripts" / "pytest.exe" if sys.platform == "win32"
            else venv_path / "bin" / "pytest"
        )

        logger.info("[%s] Running pytest...", task_id[:8])
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    str(pytest_path),
                    "-v",
                    "--tb=short",
                    str(project_dir),
                ],
                capture_output=True, text=True,
                timeout=self.timeout,
                cwd=str(project_dir),
                check=False,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Tests timed out after {self.timeout}s"
        except Exception as e:
            return -1, "", str(e)
