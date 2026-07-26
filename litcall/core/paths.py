"""路径常量 — 所有路径的单一来源。

修改 BASE_DIR 后，所有子路径自动跟随。无需在其他模块中硬编码路径。
"""

from pathlib import Path

# ── 根目录 ──
SCRIPT_DIR = Path(__file__).parent.parent.parent.absolute()
BASE_DIR = SCRIPT_DIR

# ── 数据文件 ──
CONFIG_PATH = SCRIPT_DIR / "config.json"
PROCESSED_LOG = SCRIPT_DIR / "processed_log.json"
EXCEL_PATH = BASE_DIR / "litcall文献汇总.xlsx"
JOURNAL_IF_PATH = SCRIPT_DIR / "journal_if.json"

# ── 目录 ──
PDF_DIR = BASE_DIR / "待处理文献"
NOTES_DIR = PDF_DIR / "notes"
OBSIDIAN_DIR = BASE_DIR / "litcall"
LOG_DIR = BASE_DIR / "运行日志"
RUNS_DIR = LOG_DIR / "runs"

# ── 信号文件 ──
PAUSE_FILE = LOG_DIR / ".pause"
TERMINATE_FILE = LOG_DIR / ".terminate"

# ── 锁文件 ──
WORKER_PID_FILE = LOG_DIR / "worker.pid"
EXCEL_LOCK_FILE = LOG_DIR / ".excel.lock"

# ── 复核队列 ──
REVIEW_QUEUE_FILE = LOG_DIR / "review_queue.json"

# ── 审计日志 ──
AUDIT_LOG_DIR = LOG_DIR / "audits"
