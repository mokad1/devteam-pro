"""20 条 Python 开发需求测试集。

用于 evaluate.py 自动评测脚本，覆盖以下类别：
- CLI 工具类 (5)
- 数据处理/转换类 (5)
- 工具函数库类 (5)
- 简单应用类 (5)
"""

from __future__ import annotations

from typing import TypedDict


class TestCase(TypedDict):
    """单个测试用例定义。"""
    id: str
    category: str
    requirement: str
    difficulty: str  # easy / medium / hard
    min_files_expected: int
    key_features: list[str]


TEST_CASES: list[TestCase] = [
    # ═══════════════ CLI 工具类 (5) ═══════════════
    {
        "id": "cli_01",
        "category": "CLI Tool",
        "requirement": (
            "Create a CLI password generator tool. It should support --length for password length "
            "(default 16), --no-symbols to exclude special characters, --count for generating "
            "multiple passwords at once. Use only Python stdlib (secrets and string modules). "
            "The script should be runnable as: python password_gen.py --length 20 --count 5"
        ),
        "difficulty": "easy",
        "min_files_expected": 1,
        "key_features": ["random generation", "argparse CLI", "secrets module"],
    },
    {
        "id": "cli_02",
        "category": "CLI Tool",
        "requirement": (
            "Create a file/directory size analyzer CLI tool. Given a directory path, it should "
            "recursively calculate the total size, list the top 10 largest files, and display "
            "a summary with human-readable sizes (KB/MB/GB). Support --depth flag to limit "
            "recursion depth. Use pathlib and argparse."
        ),
        "difficulty": "easy",
        "min_files_expected": 1,
        "key_features": ["recursive directory walk", "human-readable sizes", "argparse"],
    },
    {
        "id": "cli_03",
        "category": "CLI Tool",
        "requirement": (
            "Build a JSON-to-CSV converter CLI. Accept a JSON file path (array of flat objects) "
            "and output a CSV file. Support --delimiter (default comma), --output to specify "
            "output path. Handle nested objects by flattening with dot notation keys. "
            "Use argparse and csv modules from stdlib."
        ),
        "difficulty": "medium",
        "min_files_expected": 1,
        "key_features": ["JSON parsing", "CSV writing", "nested flattening", "argparse"],
    },
    {
        "id": "cli_04",
        "category": "CLI Tool",
        "requirement": (
            "Create a simple HTTP server with file listing. It should serve static files from "
            "a given directory, show directory listings as HTML, and support --port and --bind "
            "flags. Use only Python stdlib (http.server). Add basic logging of requests with "
            "timestamp, IP, method, path, and status code."
        ),
        "difficulty": "medium",
        "min_files_expected": 1,
        "key_features": ["HTTP server", "directory listing", "logging", "argparse"],
    },
    {
        "id": "cli_05",
        "category": "CLI Tool",
        "requirement": (
            "Build a markdown table of contents generator. Read a markdown file, extract all "
            "headings (#, ##, ###), generate a nested table of contents with anchor links, "
            "and insert it at the top of the file or print to stdout. Support --indent-spaces "
            "and --max-level flags. Handle duplicate heading names by appending numbers."
        ),
        "difficulty": "medium",
        "min_files_expected": 1,
        "key_features": ["regex parsing", "nested TOC", "anchor generation", "argparse"],
    },

    # ═══════════════ 数据处理/转换类 (5) ═══════════════
    {
        "id": "data_01",
        "category": "Data Processing",
        "requirement": (
            "Write a function library that takes a list of datetime strings in various formats "
            "and normalizes them to ISO 8601 format. Support formats: 'YYYY-MM-DD', "
            "'MM/DD/YYYY', 'DD-MM-YYYY', 'YYYYMMDD', and 'Mon DD, YYYY'. Return a list of "
            "normalized strings and a list of errors for unparseable inputs. Include type hints."
        ),
        "difficulty": "easy",
        "min_files_expected": 1,
        "key_features": ["date parsing", "multiple formats", "error handling", "type hints"],
    },
    {
        "id": "data_02",
        "category": "Data Processing",
        "requirement": (
            "Create a CSV data cleaner module. It should: remove duplicate rows, trim whitespace "
            "from all string fields, fill empty values with a specified default, remove rows "
            "where a specified column is empty, and normalize column names to snake_case. "
            "All functions should work with csv.DictReader/DictWriter compatible data."
        ),
        "difficulty": "easy",
        "min_files_expected": 1,
        "key_features": ["CSV cleaning", "dedup", "normalization", "type hints"],
    },
    {
        "id": "data_03",
        "category": "Data Processing",
        "requirement": (
            "Implement a text log parser that extracts structured data from Apache/Nginx style "
            "access logs. Parse each line into a dataclass with: ip, timestamp, method, path, "
            "status_code, size, user_agent. Support both Common Log Format and Combined Log "
            "Format. Return summary statistics: top 10 IPs, status code distribution, "
            "total bytes transferred."
        ),
        "difficulty": "medium",
        "min_files_expected": 2,
        "key_features": ["regex parsing", "dataclass", "statistics", "log formats"],
    },
    {
        "id": "data_04",
        "category": "Data Processing",
        "requirement": (
            "Write a Python module that merges multiple sorted CSV files (sorted by a key column) "
            "into a single sorted output file, similar to an external merge sort. The files may "
            "be too large to fit in memory, so use streaming/iterator approach. Support "
            "--key-column and --reverse flags. Handle CSV files with and without headers."
        ),
        "difficulty": "hard",
        "min_files_expected": 2,
        "key_features": ["streaming merge", "heap merge", "CSV handling", "memory efficient"],
    },
    {
        "id": "data_05",
        "category": "Data Processing",
        "requirement": (
            "Create a simple data validation framework. Define validation rules as Python "
            "dataclasses (e.g., Required, MinLength, MaxLength, Regex, Range, IsEmail). "
            "Given a list of field definitions with rules, validate a list of dict records "
            "and return a structured error report. The report should list each record's "
            "validation errors by field. Must be extensible — users can add custom rules."
        ),
        "difficulty": "hard",
        "min_files_expected": 2,
        "key_features": ["validation framework", "dataclass", "extensible rules", "error reporting"],
    },

    # ═══════════════ 工具函数库类 (5) ═══════════════
    {
        "id": "util_01",
        "category": "Utility Library",
        "requirement": (
            "Create a retry decorator utility. It should support: max_retries, backoff_factor "
            "(exponential backoff), retryable_exceptions (tuple of exception types to catch), "
            "and on_retry callback. Use functools.wraps to preserve function metadata. "
            "Write as a standalone module with type hints and docstrings."
        ),
        "difficulty": "easy",
        "min_files_expected": 1,
        "key_features": ["decorator", "retry logic", "exponential backoff", "functools.wraps"],
    },
    {
        "id": "util_02",
        "category": "Utility Library",
        "requirement": (
            "Implement a thread-safe in-memory cache with TTL (time-to-live) support. "
            "It should have: get(key), set(key, value, ttl_seconds), delete(key), clear(), "
            "and a cleanup() method to remove expired entries. Use threading.Lock for thread "
            "safety. Support max_size with LRU eviction. Include __contains__ for 'in' operator."
        ),
        "difficulty": "medium",
        "min_files_expected": 1,
        "key_features": ["thread-safe", "TTL cache", "LRU eviction", "locking"],
    },
    {
        "id": "util_03",
        "category": "Utility Library",
        "requirement": (
            "Build a simple async task queue/worker system using asyncio. It should have: "
            "enqueue(task_id, coroutine), a worker pool of N concurrent workers, task status "
            "tracking (pending/running/done/failed), and result retrieval. Use asyncio.Queue "
            "internally. Support graceful shutdown with timeout. Write as a reusable module."
        ),
        "difficulty": "hard",
        "min_files_expected": 1,
        "key_features": ["asyncio", "task queue", "worker pool", "graceful shutdown"],
    },
    {
        "id": "util_04",
        "category": "Utility Library",
        "requirement": (
            "Create a configuration loader that reads from multiple sources with priority: "
            "environment variables > YAML config file > TOML config file > default values. "
            "Support nested configuration paths with dot notation (e.g., 'database.host'). "
            "Use Pydantic for validation. Include a function to dump current config as YAML."
        ),
        "difficulty": "medium",
        "min_files_expected": 1,
        "key_features": ["multi-source config", "env vars", "YAML/TOML", "Pydantic validation"],
    },
    {
        "id": "util_05",
        "category": "Utility Library",
        "requirement": (
            "Write a file watcher module that monitors a directory for changes (create, modify, "
            "delete) and calls registered callbacks. Use polling with a configurable interval. "
            "Support file pattern filtering (glob). Track file hashes to detect actual content "
            "changes (not just timestamp changes). Include start/stop methods and a context "
            "manager interface (__enter__/__exit__)."
        ),
        "difficulty": "hard",
        "min_files_expected": 1,
        "key_features": ["file watching", "polling", "hash comparison", "callback pattern"],
    },

    # ═══════════════ 简单应用类 (5) ═══════════════
    {
        "id": "app_01",
        "category": "Simple App",
        "requirement": (
            "Build a simple personal todo list manager. Features: add task with priority "
            "(high/medium/low) and due date, list tasks sorted by priority then due date, "
            "mark tasks as done, delete tasks. Store data in a JSON file. "
            "Provide both a CLI interface (argparse subcommands: add, list, done, delete) "
            "and importable Python functions. Tasks should have unique IDs (UUID)."
        ),
        "difficulty": "medium",
        "min_files_expected": 2,
        "key_features": ["CLI subcommands", "JSON storage", "UUID", "sorting"],
    },
    {
        "id": "app_02",
        "category": "Simple App",
        "requirement": (
            "Create a URL shortener service. It should generate short codes (6 chars, "
            "alphanumeric), map them to long URLs, support redirect resolution, and track "
            "click counts. Store data in a JSON file. Provide a CLI: shorten <url>, "
            "expand <code>, stats <code>, list. Use base64 encoding for code generation. "
            "Validate URLs before shortening."
        ),
        "difficulty": "medium",
        "min_files_expected": 2,
        "key_features": ["URL validation", "short code generation", "click tracking", "CLI"],
    },
    {
        "id": "app_03",
        "category": "Simple App",
        "requirement": (
            "Implement a simple key-value store with section support (like Windows INI or "
            "config files). Features: get(section, key, default), set(section, key, value), "
            "delete(section, key), list_sections(), list_keys(section). Persist to a text "
            "file with [section] headers. Support comments (# and ;). Handle duplicate "
            "sections/keys gracefully. Thread-safe reads with a read-write lock."
        ),
        "difficulty": "medium",
        "min_files_expected": 1,
        "key_features": ["INI parsing", "section support", "thread safety", "persistence"],
    },
    {
        "id": "app_04",
        "category": "Simple App",
        "requirement": (
            "Build a simple expense tracker. Features: add expense (amount, category, date, "
            "description), list expenses with filtering by category and date range, show "
            "summary (total by category, total by month). Export to CSV. Store in JSON. "
            "CLI with subcommands: add, list, summary, export. Validate inputs "
            "(amount must be positive, categories from a predefined list)."
        ),
        "difficulty": "medium",
        "min_files_expected": 2,
        "key_features": ["expense tracking", "filtering", "CSV export", "input validation"],
    },
    {
        "id": "app_05",
        "category": "Simple App",
        "requirement": (
            "Create a simple chat message formatter that takes raw chat logs and formats them "
            "for display. Support multiple input formats (IRC style, Slack export JSON, "
            "plain text with timestamps). Output as formatted HTML or plain text with "
            "configurable templates. Support --format (html/text) and --template flags. "
            "Extract statistics: messages per user, most active hours, top words."
        ),
        "difficulty": "hard",
        "min_files_expected": 2,
        "key_features": ["multi-format parsing", "HTML output", "statistics", "argparse"],
    },
]


def get_test_cases() -> list[TestCase]:
    """获取所有测试用例。"""
    return TEST_CASES


def get_test_cases_by_category() -> dict[str, list[TestCase]]:
    """按类别分组获取测试用例。"""
    categories: dict[str, list[TestCase]] = {}
    for tc in TEST_CASES:
        categories.setdefault(tc["category"], []).append(tc)
    return categories


def get_test_case_by_id(case_id: str) -> TestCase | None:
    """根据 ID 获取单个测试用例。"""
    for tc in TEST_CASES:
        if tc["id"] == case_id:
            return tc
    return None
