"""litcall.core — 基础设施层
零外部依赖。提供配置、路径、编码、日志。
"""

from litcall.core.config import config, load_config, save_config
from litcall.core.paths import (
    SCRIPT_DIR, BASE_DIR, PDF_DIR, NOTES_DIR, EXCEL_PATH,
    OBSIDIAN_DIR, CONFIG_PATH, PROCESSED_LOG, RUNS_DIR, LOG_DIR,
)
from litcall.core.logging import get_logger, setup_logging

__all__ = [
    "config", "load_config", "save_config",
    "SCRIPT_DIR", "BASE_DIR", "PDF_DIR", "NOTES_DIR", "EXCEL_PATH",
    "OBSIDIAN_DIR", "CONFIG_PATH", "PROCESSED_LOG", "RUNS_DIR", "LOG_DIR",
    "get_logger", "setup_logging",
]
