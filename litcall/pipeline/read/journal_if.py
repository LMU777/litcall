"""期刊影响因子 / 分区匹配。

从 journal_if.json 加载期刊→IF 映射表，支持精确匹配和模糊匹配。

journal_if.json 结构：
{
    "_comment": "...",
    "营销类核心": {"Journal of Marketing": 12.3, ...},
    "管理类": {"Academy of Management Journal": 10.5, ...},
    ...
}
顶层 key 为类别名（以 "_" 开头的为注释/元数据），值为 {期刊名: IF} 嵌套 dict。
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# journal_if.json 路径 → 项目根目录
_JOURNAL_IF_PATH = Path(__file__).resolve().parent.parent.parent.parent / "journal_if.json"

# 模块级缓存
_journal_if_map: Dict[str, float] = {}
_loaded = False


def _load_journal_if_map() -> Dict[str, float]:
    """加载 journal_if.json，构建 期刊名→IF 的扁平映射表。

    遍历所有类别（跳过以 "_" 开头的注释 key），
    从每个类别的嵌套 dict 中提取 期刊名→IF 键值对。
    """
    global _journal_if_map, _loaded
    if _loaded:
        return _journal_if_map
    _loaded = True

    if not _JOURNAL_IF_PATH.exists():
        logger.warning(f"影响因子配置文件不存在: {_JOURNAL_IF_PATH}")
        return {}

    try:
        with open(_JOURNAL_IF_PATH, "r", encoding="utf-8") as f:
            if_data = json.load(f)
        for category, journals in if_data.items():
            if category.startswith("_"):
                continue
            if isinstance(journals, dict):
                for jn, if_val in journals.items():
                    if isinstance(if_val, (int, float)) and if_val > 0:
                        _journal_if_map[jn.lower().strip()] = float(if_val)
        logger.info(f"已加载 {len(_journal_if_map)} 条期刊影响因子")
    except Exception as e:
        logger.warning(f"加载影响因子配置失败: {e}")
    return _journal_if_map


def match_impact_factor(journal: str) -> Tuple[str, str]:
    """根据期刊名匹配影响因子和分区。

    当前 journal_if.json 不含分区信息，quartile 留空。
    后续可对接 OpenAlex API 或 JCR 数据源补充分区。

    Args:
        journal: 期刊名称。

    Returns:
        (impact_factor, quartile) — quartile 当前始终为空字符串。
    """
    if not journal or not journal.strip():
        return "", ""

    if_map = _load_journal_if_map()
    j_key = journal.lower().strip().rstrip(".").rstrip(",")

    # 1) 精确匹配
    if j_key in if_map:
        return str(if_map[j_key]), ""

    # 2) 模糊匹配（子串包含）
    for jn, if_val in if_map.items():
        if j_key in jn or jn in j_key:
            logger.info(f"影响因子模糊匹配: '{journal}' ≈ '{jn}' → IF={if_val}")
            return str(if_val), ""

    logger.info(f"期刊 '{journal}' 未在本地 IF 库中")
    return "", ""


def get_impact_factor(journal: str) -> str:
    """便捷方法：只返回 IF 值字符串。"""
    if_val, _ = match_impact_factor(journal)
    return if_val
