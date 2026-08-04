"""代码静态检查：flake8 + pylint 集成。

思路：
- flake8：快速风格/逻辑检查（PEP 8, pyflakes, mccabe）
- pylint：深度静态分析（代码质量、设计问题）
- 两者结果合并为统一的 LintIssue 列表
- 如果工具未安装则跳过并记录警告（不阻塞流程）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from devteam_pro.models.messages import LintIssue
from devteam_pro.utils.logger import get_logger

logger = get_logger("sandbox.linter")


class LinterRunner:
    """静态代码检查运行器。

    在指定项目目录上运行 flake8 和 pylint，收集所有问题。
    """

    def __init__(self, project_dir: Path) -> None:
        """初始化。

        Args:
            project_dir: 项目根目录（包含 Python 文件）。
        """
        self.project_dir = project_dir
        self._flake8_available: bool | None = None
        self._pylint_available: bool | None = None

    # ── 工具可用性检查 ──────────────────────────────────────

    @property
    def flake8_available(self) -> bool:
        """检查 flake8 是否可调用。"""
        if self._flake8_available is None:
            try:
                subprocess.run(
                    [sys.executable, "-m", "flake8", "--version"],
                    capture_output=True, timeout=10,
                    check=False,
                )
                self._flake8_available = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._flake8_available = False
                logger.warning("flake8 not available, skipping flake8 checks")
        return self._flake8_available

    @property
    def pylint_available(self) -> bool:
        """检查 pylint 是否可调用。"""
        if self._pylint_available is None:
            try:
                subprocess.run(
                    [sys.executable, "-m", "pylint", "--version"],
                    capture_output=True, timeout=10,
                    check=False,
                )
                self._pylint_available = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._pylint_available = False
                logger.warning("pylint not available, skipping pylint checks")
        return self._pylint_available

    # ── 运行检查 ────────────────────────────────────────────

    async def run_all(self) -> list[LintIssue]:
        """运行所有可用的 Lint 检查并汇总结果。

        Returns:
            LintIssue 列表（按文件+行号排序）。
        """
        issues: list[LintIssue] = []

        flake8_issues = await self._run_flake8()
        issues.extend(flake8_issues)

        pylint_issues = await self._run_pylint()
        issues.extend(pylint_issues)

        # 按文件和行号排序
        issues.sort(key=lambda x: (x.file, x.line))
        return issues

    async def _run_flake8(self) -> list[LintIssue]:
        """运行 flake8 检查。"""
        if not self.flake8_available:
            return []

        try:
            # --max-line-length=120 避免过度严格的换行检查
            result = subprocess.run(
                [
                    sys.executable, "-m", "flake8",
                    "--max-line-length=120",
                    "--max-complexity=15",
                    str(self.project_dir),
                ],
                capture_output=True, text=True, timeout=60,
                check=False,
            )

            issues: list[LintIssue] = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # flake8 输出格式: path:line:col: CODE message
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    file_path = parts[0]
                    try:
                        line_no = int(parts[1])
                    except ValueError:
                        line_no = 0
                    code_msg = parts[3].strip()
                    code_parts = code_msg.split(" ", 1)
                    code = code_parts[0] if code_parts else ""
                    message = code_parts[1] if len(code_parts) > 1 else code_msg

                    issues.append(LintIssue(
                        tool="flake8",
                        file=file_path,
                        line=line_no,
                        message=message,
                        code=code,
                    ))

            logger.info("flake8 found %d issues in %s", len(issues), self.project_dir.name)
            return issues
        except subprocess.TimeoutExpired:
            logger.warning("flake8 timed out on %s", self.project_dir.name)
            return []
        except Exception as e:
            logger.error("flake8 error on %s: %s", self.project_dir.name, e)
            return []

    async def _run_pylint(self) -> list[LintIssue]:
        """运行 pylint 检查。"""
        if not self.pylint_available:
            return []

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pylint",
                    "--output-format=text",
                    "--disable=C0114,C0115,C0116",  # 不强制模块/类/函数 docstring
                    str(self.project_dir),
                ],
                capture_output=True, text=True, timeout=90,
                check=False,
            )

            issues: list[LintIssue] = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # pylint 输出格式: path:line:col: CODE: message
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    file_path = parts[0]
                    try:
                        line_no = int(parts[1])
                    except ValueError:
                        line_no = 0
                    code_msg = parts[3].strip()
                    code_parts = code_msg.split(":", 1)
                    code = code_parts[0].strip() if code_parts else ""
                    message = code_parts[1].strip() if len(code_parts) > 1 else code_msg

                    issues.append(LintIssue(
                        tool="pylint",
                        file=file_path,
                        line=line_no,
                        message=message,
                        code=code,
                    ))

            logger.info("pylint found %d issues in %s", len(issues), self.project_dir.name)
            return issues
        except subprocess.TimeoutExpired:
            logger.warning("pylint timed out on %s", self.project_dir.name)
            return []
        except Exception as e:
            logger.error("pylint error on %s: %s", self.project_dir.name, e)
            return []
