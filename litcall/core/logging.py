"""日志配置 — 始终写 UTF-8 文件，不受控制台编码影响。

铁律 #9: 所有 Agent 代码路径用 logger.info()，不用 print()。
logger 始终写文件，Worker 崩溃不会丢日志。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from litcall.core.paths import LOG_DIR

# 确保日志目录存在
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── 默认日志文件 ──
DEFAULT_LOG_FILE = LOG_DIR / "litcall.log"

# ── 日志格式 ──
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── 模块级 logger 缓存 ──
_loggers: dict = {}


def setup_logging(
    log_file: Optional[Path] = None,
    level: int = logging.INFO,
    console: bool = False,
) -> None:
    """配置根 logger。

    Args:
        log_file: 日志文件路径。默认 LOG_DIR/litcall.log。
        level: 日志级别。
        console: 是否同时输出到控制台（仅 CLI 模式，Agent 模式应为 False）。
    """
    if log_file is None:
        log_file = DEFAULT_LOG_FILE

    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler 避免重复
    root.handlers.clear()

    # 文件 handler — 始终 UTF-8
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(file_handler)

    # 控制台 handler — 仅在 CLI 模式启用
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root.addHandler(console_handler)

    root.info(f"LitCall logging initialized: {log_file}")


def get_logger(name: str = "litcall") -> logging.Logger:
    """获取命名 logger。

    用法:
        from litcall.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("处理论文...")
    """
    if name not in _loggers:
        logger = logging.getLogger(name)
        _loggers[name] = logger
    return _loggers[name]


# 模块加载时自动初始化基本日志
if not logging.getLogger().handlers:
    setup_logging()
