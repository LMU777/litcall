"""PaperLifecycle — 论文生命周期状态机。

铁律 #2: 四库全部成功才标记 done。
铁律 #6: 先验证再操作。

状态转换:
discovered → downloaded → reading → storing → verifying → done
                                                     → error (可重试)
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PaperStatus(str, Enum):
    """论文生命周期状态。"""
    DISCOVERED = "discovered"
    DOWNLOADED = "downloaded"
    READING = "reading"
    STORING = "storing"
    VERIFYING = "verifying"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"
    REREADING = "rereading"

    def __str__(self) -> str:
        return self.value


# 合法状态转换
VALID_TRANSITIONS: Dict[PaperStatus, set] = {
    PaperStatus.DISCOVERED: {PaperStatus.DOWNLOADED, PaperStatus.SKIPPED},
    PaperStatus.DOWNLOADED: {PaperStatus.READING, PaperStatus.ERROR},
    PaperStatus.READING: {PaperStatus.STORING, PaperStatus.ERROR},
    PaperStatus.STORING: {PaperStatus.VERIFYING, PaperStatus.ERROR},
    PaperStatus.VERIFYING: {PaperStatus.DONE, PaperStatus.ERROR},
    PaperStatus.DONE: set(),
    PaperStatus.ERROR: {PaperStatus.DOWNLOADED, PaperStatus.SKIPPED},
    PaperStatus.SKIPPED: set(),
    PaperStatus.REREADING: {PaperStatus.READING, PaperStatus.ERROR},
}


def can_transition(from_status: str, to_status: str) -> bool:
    """检查状态转换是否合法。"""
    from_s = PaperStatus(from_status) if isinstance(from_status, str) else from_status
    to_s = PaperStatus(to_status) if isinstance(to_status, str) else to_status
    return to_s in VALID_TRANSITIONS.get(from_s, set())


def transition(
    current_status: str,
    new_status: str,
    doi: str = "",
    error: str = "",
) -> Dict:
    """执行状态转换并返回更新后的记录字段。

    Raises:
        ValueError: 状态转换不合法。
    """
    if not can_transition(current_status, new_status):
        raise ValueError(
            f"非法状态转换: {current_status} → {new_status} (DOI: {doi})"
        )

    update = {
        "status": new_status,
        "updated_at": datetime.now().isoformat(),
    }

    if new_status == PaperStatus.ERROR and error:
        update["error"] = error
    elif new_status == PaperStatus.DONE:
        update["completed_at"] = datetime.now().isoformat()

    logger.info(
        f"[状态] {doi or '(无DOI)'} : {current_status} → {new_status}"
        + (f" ({error})" if error else "")
    )

    return update
