"""Windows UTF-8 安全网。

铁律 #9: Agent 代码路径禁止 print()，用 logger.info()。
但仍有旧代码或第三方库可能 print。此模块确保 stdout/stderr
始终使用 UTF-8 编码，避免 emoji 导致 GBK 编码崩溃。

This module is imported by core/__init__.py so encoding safety
is established before any other module runs.
"""

import io
import sys


def _ensure_utf8_encoding():
    """幂等包装 stdout/stderr 为 UTF-8 TextIOWrapper。"""
    if sys.platform != "win32":
        return

    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr)
        is_utf8 = (
            hasattr(stream, "encoding")
            and stream.encoding
            and stream.encoding.lower() in ("utf-8", "utf8")
        )
        if not is_utf8 and hasattr(stream, "buffer"):
            try:
                setattr(sys, attr, io.TextIOWrapper(
                    stream.buffer, encoding="utf-8", errors="replace"
                ))
            except Exception:
                pass  # 幂等：已经包装过则跳过


_ensure_utf8_encoding()
