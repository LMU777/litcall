"""标题去重模块 — 字符级 + 词级双重防线。

从 literature_agent.py 提取，供检索管线各阶段复用。
"""

import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """标准化标题：去标点、小写、压缩空白。"""
    if not title:
        return ""
    title = re.sub(r"[^\w\s]", "", title).lower().strip()
    return re.sub(r"\s+", " ", title)


def _word_set(title: str) -> set:
    """返回标题的小写词集合（过滤 <3 字符的噪声词如 'a', 'in', 'of' 等保留）。"""
    return set(w for w in title.lower().split() if len(w) >= 1)


def word_jaccard(a: str, b: str) -> float:
    """词级 Jaccard 相似度。两个标题共享的独特词比例。"""
    wa = _word_set(normalize_title(a))
    wb = _word_set(normalize_title(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def title_similarity(a: str, b: str) -> float:
    """字符级相似度（SequenceMatcher）。保留用于向后兼容。"""
    import difflib
    return difflib.SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def is_title_duplicate(a: str, b: str) -> Tuple[bool, float, float]:
    """综合判断两个标题是否为同一篇文献。

    使用双重防线：
    1. 字符级相似度 (SequenceMatcher) — 检测截断/OCR 变体
    2. 词级 Jaccard — 防止共享长短语的不同论文被误杀

    返回 (is_dup, char_sim, word_jac)。
    判定规则：字符级 > 0.80 且 词级 > 0.50 才视为重复。
    """
    char_sim = title_similarity(a, b)
    word_jac = word_jaccard(a, b)
    # 两个条件必须同时满足：
    # - 字符级高：标题文本确实相似
    # - 词级高：排除仅共享通用前缀的不同论文
    is_dup = char_sim > 0.80 and word_jac > 0.50
    return is_dup, char_sim, word_jac
