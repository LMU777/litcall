"""IPC 信号文件机制 — 暂停/终止/心跳。

铁律 #5: 暂停/终止必须即时响应。每篇论文每个步骤前后检查信号文件。
"""

import logging
import os
import time
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 信号文件路径
SIGNAL_DIR = Path(os.path.expanduser("~")) / ".litcall"
PAUSE_FILE = SIGNAL_DIR / ".pause"
TERMINATE_FILE = SIGNAL_DIR / ".terminate"


class Signal(Enum):
    NONE = "none"
    PAUSED = "paused"
    TERMINATED = "terminated"


def _ensure_signal_dir():
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)


def check_signal_files() -> Signal:
    """检查信号文件。终止优先于暂停。"""
    if TERMINATE_FILE.exists():
        return Signal.TERMINATED
    if PAUSE_FILE.exists():
        return Signal.PAUSED
    return Signal.NONE


async def check_and_wait_if_paused() -> Signal:
    """检查信号，如果是暂停则阻塞等待恢复或终止。"""
    import asyncio
    sig = check_signal_files()
    if sig == Signal.PAUSED:
        logger.info("[信号] 暂停中...")
        while check_signal_files() == Signal.PAUSED:
            await asyncio.sleep(0.5)
            if check_signal_files() == Signal.TERMINATED:
                return Signal.TERMINATED
        logger.info("[信号] 恢复运行")
        return Signal.NONE
    return sig


def clear_all_signals():
    """清除所有信号文件（新 session 开始前调用）。"""
    _ensure_signal_dir()
    for f in [PAUSE_FILE, TERMINATE_FILE]:
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass


def write_pid():
    """写入 PID 文件（用于外部监控）。"""
    _ensure_signal_dir()
    pid_file = SIGNAL_DIR / "worker.pid"
    pid_file.write_text(str(os.getpid()))
