"""期刊白名单过滤模块 — 扩展版期刊白名单（100+ 种管理/心理类顶刊）。

支持：
- 硬编码白名单 + config.json 扩展
- 前缀索引加速匹配
- 截断期刊名智能补全
- 多策略回退匹配（精确 → 前缀 → 子串 → 尾缀）

从 literature_agent.py 提取，供检索管线各阶段复用。
"""

import logging
from typing import Dict, List, Optional

from litcall.core.config import config

logger = logging.getLogger(__name__)

# ============================================================================
# 扩展版期刊白名单（硬编码，60+ 种）
# 可通过 config.json 中 "journal_whitelist_extra" 字段追加自定义期刊
# ============================================================================
WHITELIST = [
    # ── 营销类核心 ──
    "Journal of Marketing",
    "Journal of Marketing Research",
    "Marketing Science",
    "Journal of Consumer Research",
    "Journal of the Academy of Marketing Science",
    "Journal of Consumer Psychology",
    # 营销类扩展（高影响力）
    "Journal of Business Research",
    "Journal of Retailing",
    "Industrial Marketing Management",
    "Journal of Service Research",
    "Journal of Advertising",
    "Psychology & Marketing",
    "European Journal of Marketing",
    "International Journal of Research in Marketing",
    "Journal of Interactive Marketing",
    "Journal of Research in Interactive Marketing",
    "Journal of Public Policy & Marketing",
    "Journal of International Marketing",
    "International Journal of Market Research",
    "Marketing Letters",
    "Quantitative Marketing and Economics",
    "Journal of Advertising Research",
    "International Journal of Advertising",
    "Journal of Brand Management",
    "Journal of Product & Brand Management",
    "Journal of Services Marketing",
    "Journal of Marketing Management",
    "Journal of Macromarketing",
    "Consumption Markets & Culture",
    "Journal of the Association for Consumer Research",
    "Journal of Consumer Behaviour",
    "Journal of Consumer Affairs",
    "Journal of Retailing and Consumer Services",
    # ── 管理类 (UTD24/FT50 全覆盖) ──
    "Academy of Management Journal",
    "Academy of Management Review",
    "Academy of Management Perspectives",
    "Academy of Management Annals",
    "Administrative Science Quarterly",
    "Organization Science",
    "Strategic Management Journal",
    "Management Science",
    "Journal of Management",
    "Journal of Management Studies",
    "Journal of International Business Studies",
    "Journal of Operations Management",
    "Production and Operations Management",
    "Information Systems Research",
    "MIS Quarterly",
    # 管理类扩展
    "Harvard Business Review",
    "MIT Sloan Management Review",
    "California Management Review",
    "Journal of World Business",
    "Global Strategy Journal",
    "Long Range Planning",
    "Research Policy",
    "Technovation",
    "Journal of Product Innovation Management",
    "Decision Sciences",
    "Manufacturing & Service Operations Management",
    "Omega",
    "European Journal of Operational Research",
    "Management and Organization Review",
    "Asia Pacific Journal of Management",
    "Journal of Supply Chain Management",
    # ── 工商管理/创业/伦理 ──
    "Journal of Business Ethics",
    "Business Ethics Quarterly",
    "Business & Society",
    "Entrepreneurship Theory and Practice",
    "Journal of Business Venturing",
    "Human Relations",
    "Journal of Organizational Behavior",
    "Leadership Quarterly",
    "Organizational Research Methods",
    # ── 应用心理学 / 消费者行为 ──
    "Journal of Applied Psychology",
    "Personnel Psychology",
    "Organizational Behavior and Human Decision Processes",
    "Journal of Personality and Social Psychology",
    "Psychological Science",
    "Journal of Experimental Psychology: General",
    "Journal of Experimental Psychology: Applied",
    "Journal of Experimental Social Psychology",
    "Personality and Social Psychology Bulletin",
    "Psychological Review",
    "Annual Review of Psychology",
    "Cognition",
    "Emotion",
    "Judgment and Decision Making",
    "Journal of Behavioral Decision Making",
    "Social Psychological and Personality Science",
    "Journal of Economic Psychology",
    "Appetite",
    "Food Quality and Preference",
    # ── 信息系统 / 技术 ──
    "Journal of the Association for Information Systems",
    "European Journal of Information Systems",
    "Information & Management",
    "Decision Support Systems",
    "Journal of Information Technology",
    "Journal of Management Information Systems",
    "Information Systems Journal",
    # ── 人机交互 / 计算机交叉（AI+营销高频发表阵地）──
    "Computers in Human Behavior",
    "Business Horizons",
    # ── 知识管理 / 信息管理 ──
    "Journal of Knowledge Management",
    "International Journal of Information Management",
    "Journal of Information Science",
    "Information Processing & Management",
    "Knowledge Management Research & Practice",
    # ── 旅游/酒店（AI+营销/服务高频发表阵地）──
    "Tourism Management",
    "Annals of Tourism Research",
    "Journal of Travel Research",
    "International Journal of Hospitality Management",
    "International Journal of Contemporary Hospitality Management",
    "Journal of Hospitality Marketing & Management",
    # ── 服务质量/运营（Emerald 等）──
    "International Journal of Quality and Service Sciences",
    "Journal of Service Theory and Practice",
    "Managing Service Quality",
    "International Journal of Quality & Reliability Management",
    "The TQM Journal",
    "Benchmarking",
    # ── 营销扩展（补充）──
    "Journal of Strategic Marketing",
    "Journal of Marketing Communications",
    "Marketing Theory",
    "Journal of Fashion Marketing and Management",
    "International Marketing Review",
    "Journal of Business & Industrial Marketing",
    "Journal of Consumer Marketing",
    "Journal of Personal Selling & Sales Management",
    "International Review of Retail Distribution and Consumer Research",
    # ── 管理扩展 ──
    "British Journal of Management",
    "International Journal of Management Reviews",
    "Scandinavian Journal of Management",
    "Technological Forecasting and Social Change",
    "Journal of Cleaner Production",
    "Business Strategy and the Environment",
    "Corporate Social Responsibility and Environmental Management",
    # ── 创新/科技管理 ──
    "Journal of Innovation & Knowledge",
    "IEEE Transactions on Engineering Management",
    "R&D Management",
    "Journal of Engineering and Technology Management",
    # ── 信息系统扩展 ──
    "Journal of Strategic Information Systems",
    "Information and Organization",
    "Journal of Database Management",
    "Information Systems Frontiers",
    # ── 社科/综合（⚠️ 全学科巨型期刊，可能收录非营销/AI论文，建议人工复核）──
    "PLOS ONE",
    "Scientific Reports",
    "Heliyon",
    "SAGE Open",
]


# ============================================================================
# 合并白名单：硬编码 + config.json 扩展
# ============================================================================
def _get_effective_whitelist() -> List[str]:
    """合并硬编码白名单与 config.json 中的 journal_whitelist_extra"""
    extra = config.get("journal_whitelist_extra", [])
    if extra:
        logger.info(f"加载自定义期刊 {len(extra)} 种: {extra}")
    seen = set(w.lower() for w in WHITELIST)
    merged = list(WHITELIST)
    for jn in extra:
        if jn.lower() not in seen:
            merged.append(jn)
            seen.add(jn.lower())
    return merged


# 构建开头词索引：{"journal of": ["Journal of Marketing", "Journal of Consumer Research", ...]}
def _build_prefix_index(whitelist: List[str]) -> Dict[str, List[str]]:
    idx: Dict[str, List[str]] = {}
    for w in whitelist:
        words = w.lower().split()
        for n in range(2, min(len(words) + 1, 6)):
            prefix = " ".join(words[:n])
            idx.setdefault(prefix, []).append(w)
    return idx


_EFFECTIVE_WHITELIST = _get_effective_whitelist()
_PREFIX_INDEX = _build_prefix_index(_EFFECTIVE_WHITELIST)


def _find_whitelist_journal_in_text(text: str) -> Optional[str]:
    """在任意文本中搜索白名单期刊名，返回匹配到的完整期刊名（最长匹配优先）。

    用于解决 SPIS 截断/异形格式导致的期刊名提取失败。
    直接搜索文本中是否包含白名单期刊名，不依赖任何格式假设。
    返回白名单中的原始大小写期刊名，或 None。"""
    if not text:
        return None
    text_lower = text.lower()
    best_match: Optional[str] = None
    best_len = 0
    for w in _EFFECTIVE_WHITELIST:
        wl = w.lower()
        if wl in text_lower:
            if len(wl) > best_len:
                best_match = w
                best_len = len(wl)
    return best_match


def _resolve_truncated_journal(partial: str) -> Optional[str]:
    """尝试从截断的期刊名片段补全为完整白名单期刊名。

    V14 改进：后缀匹配必须唯一 — 只有当 partial 唯一匹配到一个白名单期刊时才返回。
    避免 "International Journal of" → 误匹配 "International Journal of Contemporary Hospitality Management"。
    """
    if not partial or len(partial) < 5:
        return None
    partial_lower = partial.lower().strip()

    # 策略1：白名单期刊名以 partial 结尾（partial 是后半截）
    # V14: 必须唯一匹配
    suffix_matches = []
    for w in _EFFECTIVE_WHITELIST:
        wl = w.lower()
        if wl.endswith(partial_lower) and len(wl) > len(partial_lower):
            suffix_matches.append(w)
    if len(suffix_matches) == 1:
        logger.debug(f"截断期刊补全(后缀匹配,唯一): '{partial}' → '{suffix_matches[0]}'")
        return suffix_matches[0]
    elif len(suffix_matches) > 1:
        logger.debug(f"截断期刊补全(后缀匹配,歧义): '{partial}' 匹配 {len(suffix_matches)} 个，不猜测")

    # 策略2：取 partial 最后 2-3 个实词搜索
    words = partial_lower.split()
    for n in [3, 2]:
        if len(words) >= n:
            suffix = " ".join(words[-n:])
            if len(suffix) >= 8:
                word_matches = []
                for w in _EFFECTIVE_WHITELIST:
                    wl = w.lower()
                    if suffix in wl and len(wl) > len(partial_lower):
                        word_matches.append(w)
                if len(word_matches) == 1:
                    logger.debug(f"截断期刊补全(尾词搜索,唯一): '{partial}' → '{word_matches[0]}'")
                    return word_matches[0]
                elif len(word_matches) > 1:
                    logger.debug(f"截断期刊补全(尾词搜索,歧义): '{partial}' 匹配 {len(word_matches)} 个")

    return None


def journal_in_whitelist(journal: str) -> bool:
    """增强匹配：首词前缀 → 前缀索引 → 逐级回退 → 子串双向包含 → 尾缀匹配

    V7 改进：新增策略0.5，专门处理 SPIS 截断导致的单/双词期刊名前缀
    （如 "California" → "California Management Review"）。"""
    if not journal:
        return False
    # 去除 SPIS 截断标记（前后 "…" / "..." 及空白）
    j = journal.lower().strip().strip("….").strip().rstrip(",")

    # 策略0: 精确匹配（快速路径）
    for w in _EFFECTIVE_WHITELIST:
        if w.lower() == j:
            return True

    # ── 策略0.5（V14改进）：首词前缀匹配 ──
    # 专门处理 SPIS 单/双词截断场景。
    # V14 严格条件：
    #   1. j 是 wl 的前缀，且 j≥5字符
    #   2. 长度比≥35%（排除太短的通用前缀如 "International Journal of"）
    #   3. 排除通用开头词：只匹配有独特性的前缀
    #   4. 该前缀在所有白名单期刊中只匹配唯一一本（避免歧义）
    # "california"(10) / "california management review"(28) = 35.7% → 通过 ✓
    # "psychology"(10) / "psychology & marketing"(22) = 45.5% → 通过 ✓
    # "international journal of"(24) → 多个匹配，歧义过大 → 拒绝 ✓
    # "the"(3) → len<5 拒绝 ✓
    if len(j) >= 5:
        # 统计有多少白名单期刊以 j 开头
        matches = []
        for w in _EFFECTIVE_WHITELIST:
            wl = w.lower()
            if wl.startswith(j) and len(j) / len(wl) >= 0.35:
                matches.append(w)
        # 只有当 j 唯一匹配一个白名单期刊时才通过
        # 这避免了 "International Journal of" 匹配到错误的期刊
        if len(matches) == 1:
            w = matches[0]
            wl = w.lower()
            logger.debug(f"首词前缀匹配(V14): '{journal}' → '{w}' ({len(j)/len(wl)*100:.0f}%)")
            return True
        elif len(matches) > 1:
            logger.debug(f"首词前缀歧义(V14): '{journal}' 匹配 {len(matches)} 个期刊，拒绝猜测。"
                        f"候选项: {matches[:5]}")

    # 策略1: 前缀索引精确匹配（处理截断，如 "Journal of Consumer" → "Journal of Consumer Research"）
    candidates = _PREFIX_INDEX.get(j)
    if candidates:
        for c in candidates:
            c_lower = c.lower()
            if c_lower.startswith(j):
                logger.debug(f"前缀匹配: '{journal}' → '{c}'")
                return True
            if j.startswith(c_lower):
                logger.debug(f"前缀匹配: '{journal}' → '{c}'")
                return True

    # 策略2: 检查 j 本身的逐级前缀（被截断时 j 可能不在索引中但 j[:n] 在）
    j_words = j.split()
    for n in range(len(j_words) - 1, 1, -1):
        partial = " ".join(j_words[:n])
        if partial in _PREFIX_INDEX:
            for c in _PREFIX_INDEX[partial]:
                c_lower = c.lower()
                if c_lower.startswith(partial) and j in c_lower:
                    logger.debug(f"部分前缀匹配: '{journal}' → '{c}'")
                    return True

    # 策略3: 子串双向包含（兜底），V7 门槛降至 30%
    for w in _EFFECTIVE_WHITELIST:
        wl = w.lower()
        if wl in j:
            return True
        if j in wl:
            if len(j) / len(wl) >= 0.30:
                return True
        prefix = " ".join(wl.split()[:4])
        if len(prefix) >= 15 and prefix in j:
            return True

    # 策略4（V7新增）：尾缀匹配 — 白名单刊名以 j 结尾
    # 例: "Management Review" → "California Management Review"
    for w in _EFFECTIVE_WHITELIST:
        wl = w.lower()
        if wl.endswith(j) and len(j) >= 10 and len(j) / len(wl) >= 0.30:
            logger.debug(f"尾缀匹配(V7): '{journal}' → '{w}'")
            return True

    return False
