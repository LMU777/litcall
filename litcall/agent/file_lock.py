"""WorkerLock — 基于 PID 文件的进程互斥锁。

防止同一台机器上运行多个 Worker 实例。
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_DIR = Path(os.path.expanduser("~")) / ".litcall"
LOCK_FILE = LOCK_DIR / "worker.lock"


class WorkerLock:
    """PID 文件锁。"""

    def __init__(self):
        self._acquired = False

    def acquire(self) -> bool:
        """尝试获取锁。返回 True 表示获取成功。"""
        LOCK_DIR.mkdir(parents=True, exist_ok=True)

        if LOCK_FILE.exists():
            try:
                old_pid = int(LOCK_FILE.read_text().strip())
                # 检查进程是否还在运行
                try:
                    os.kill(old_pid, 0)  # 信号 0 只检查不发送
                    logger.warning(f"Worker 已在运行 (PID={old_pid})")
                    return False
                except (ProcessLookupError, OSError):
                    # 进程已退出，清理过期锁
                    logger.info(f"清理过期锁 (PID={old_pid} 已退出)")
                    LOCK_FILE.unlink(missing_ok=True)
            except (ValueError, Exception):
                LOCK_FILE.unlink(missing_ok=True)

        LOCK_FILE.write_text(str(os.getpid()))
        self._acquired = True
        logger.info(f"Worker 锁已获取 (PID={os.getpid()})")
        return True

    def release(self):
        """释放锁。"""
        if self._acquired and LOCK_FILE.exists():
            try:
                if int(LOCK_FILE.read_text().strip()) == os.getpid():
                    LOCK_FILE.unlink(missing_ok=True)
            except Exception:
                pass
        self._acquired = False
