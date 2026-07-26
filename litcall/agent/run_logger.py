"""AgentRunLogger — 结构化运行日志。

铁律: Agent 路径禁止 print()，统一用 logger。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentRunLogger:
    """Agent 结构化运行日志。

    记录每次运行的阶段、论文处理、心跳和最终统计。
    """

    def __init__(self, log_dir: Optional[Path] = None):
        if log_dir is None:
            from litcall.core.paths import LOG_DIR
            log_dir = LOG_DIR
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._events: List[Dict] = []
        self._stats: Dict = {}

    def log_phase(self, phase: str, detail: str = ""):
        """记录阶段事件。"""
        event = {
            "session": self._session_id,
            "timestamp": datetime.now().isoformat(),
            "type": "phase",
            "phase": phase,
            "detail": detail,
        }
        self._events.append(event)
        logger.info(f"[{phase}] {detail}")

    def log_paper(self, event_type: str, doi: str = "", title: str = "",
                  status: str = "", error: str = ""):
        """记录论文级事件。"""
        event = {
            "session": self._session_id,
            "timestamp": datetime.now().isoformat(),
            "type": "paper",
            "event": event_type,
            "doi": doi,
            "title": title[:200] if title else "",
            "status": status,
            "error": error,
        }
        self._events.append(event)

    def log_heartbeat(self, detail: str = ""):
        """记录心跳。"""
        event = {
            "session": self._session_id,
            "timestamp": datetime.now().isoformat(),
            "type": "heartbeat",
            "detail": detail,
        }
        self._events.append(event)

    def log_completion(self):
        """写入完成日志文件。"""
        log_file = self._log_dir / f"run_{self._session_id}.json"
        try:
            log_file.write_text(
                json.dumps(self._events, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"写入运行日志失败: {e}")
