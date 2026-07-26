"""本地文献检索模块。

提供基于 Token 匹配 + 字符 n-gram 语义相似度的混合检索能力。
支持中英文混合查询、概念扩展、年份过滤和智能回退。

典型用法:
    from litcall.services.retrieval import build_semantic_index, retrieve_papers

    # 一次性构建语义索引
    build_semantic_index(paper_index)

    # 多次检索
    results = retrieve_papers("消费者信任和人工智能", paper_index, top_n=8)
"""

import datetime
import logging
import re
from collections import Counter

import numpy as np

from litcall.services.concept_map import expand_query

logger = logging.getLogger(__name__)

# ── 英文停用词 ──
_QA_STOPWORDS: frozenset = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "some", "its",
    "with", "that", "this", "from", "they", "will", "would", "there", "their",
    "which", "were", "when", "what", "who", "how", "where", "into", "more",
    "than", "also", "about", "over", "after", "each", "other", "only", "most",
    "may", "such", "these", "them", "then", "should", "could",
})

# ── 语义检索全局状态 ──
# 字符 n-gram TF-IDF 矩阵，用于捕捉同义词/近义词/跨语言模式
_semantic_vocab: dict = {}          # n-gram → column index
_semantic_vectors: "np.ndarray | None" = None  # (n_papers, n_vocab) TF-IDF 矩阵
_semantic_idf: "np.ndarray | None" = None      # (n_vocab,) IDF 权重


# ============================================================================
# 分词与 n-gram 提取
# ============================================================================

def _tokenize(text: str) -> list[str]:
    """中英混合分词：英文单词 + 中文字符二元组。"""
    tokens: list[str] = []
    if not text:
        return tokens
    text_lower = text.lower()
    # 英文单词 (≥2字母)
    for m in re.finditer(r"[a-z]{2,}", text_lower):
        word = m.group()
        if word not in _QA_STOPWORDS:
            tokens.append(word)
    # 中文字符二元组 (bigram 比 unigram 更精确)
    chinese = re.findall(r"[一-鿿]", text)
    for i in range(len(chinese) - 1):
        tokens.append(chinese[i] + chinese[i + 1])
    return tokens


def _char_ngrams(text: str, n: int = 3) -> list[str]:
    """字符 n-gram 提取。中英文统一处理，捕捉子词和跨词模式。"""
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    if len(text) < n:
        return [text] if text.strip() else []
    return [text[i:i + n] for i in range(len(text) - n + 1)]


# ============================================================================
# 语义索引
# ============================================================================

def build_semantic_index(papers: list[dict]) -> None:
    """构建字符 3-gram + 4-gram TF-IDF-L2 矩阵，用于语义相似度计算。

    应在调用 retrieve_papers 之前执行一次。
    构建后，模块级全局 _semantic_vectors 可供后续检索复用。

    Args:
        papers: 论文索引列表，每项需包含 "search_text" 字段。
    """
    global _semantic_vocab, _semantic_vectors, _semantic_idf

    # 收集所有论文的 n-gram 集合
    all_ngrams: list[set[str]] = []
    for p in papers:
        text = p.get("search_text", "")
        ngrams = set(_char_ngrams(text, n=3) + _char_ngrams(text, n=4))
        all_ngrams.append(ngrams)

    # 文档频率 → 词汇表（只保留出现在 ≥2 篇文献中的 n-gram，控制噪音）
    df: Counter = Counter()
    for ngrams in all_ngrams:
        for ng in ngrams:
            df[ng] += 1
    vocab_items = [(ng, cnt) for ng, cnt in df.items() if cnt >= 2]
    vocab_items.sort(key=lambda x: -x[1])
    vocab_items = vocab_items[:8000]  # 上限 8000 特征

    _semantic_vocab = {ng: i for i, (ng, _) in enumerate(vocab_items)}
    n_papers = len(papers)
    n_vocab = len(_semantic_vocab)

    if n_vocab == 0:
        logger.warning("[检索] 语义索引词汇为空，回退到纯 token 检索。")
        _semantic_vectors = None
        _semantic_idf = None
        return

    # TF 矩阵
    tf_matrix = np.zeros((n_papers, n_vocab), dtype=np.float32)
    for i, ngrams in enumerate(all_ngrams):
        for ng in ngrams:
            if ng in _semantic_vocab:
                tf_matrix[i, _semantic_vocab[ng]] += 1

    # IDF
    df_counts = np.sum(tf_matrix > 0, axis=0).astype(np.float32)
    _semantic_idf = np.log((n_papers + 1) / (df_counts + 1)) + 1.0

    # TF-IDF + L2 归一化
    _semantic_vectors = tf_matrix * _semantic_idf
    norms = np.linalg.norm(_semantic_vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    _semantic_vectors = _semantic_vectors / norms

    logger.info(f"[检索] 语义索引：{n_vocab} 个 n-gram 特征, {n_papers} 篇文献")


def _semantic_scores(query: str, paper_indices: list[int]) -> np.ndarray:
    """计算查询与指定论文的语义余弦相似度。返回 (len(paper_indices),) 的分数数组。"""
    if _semantic_vectors is None or not _semantic_vocab:
        return np.zeros(len(paper_indices))

    query_ngrams = set(_char_ngrams(query, n=3) + _char_ngrams(query, n=4))
    q_vec = np.zeros(len(_semantic_vocab), dtype=np.float32)
    for ng in query_ngrams:
        if ng in _semantic_vocab:
            q_vec[_semantic_vocab[ng]] += 1

    q_vec = q_vec * _semantic_idf
    q_norm = np.linalg.norm(q_vec)
    if q_norm > 0:
        q_vec = q_vec / q_norm

    return np.dot(_semantic_vectors[paper_indices], q_vec)


# ============================================================================
# 年份过滤
# ============================================================================

def _parse_year_filter(query: str) -> tuple[int | None, int | None]:
    """从查询中提取年份过滤条件。支持：2025-2026年、2025年到2026年、近两年等。"""
    # "2025年到2026年" / "2025-2026年" / "2025年至2026年"
    m = re.search(r"(\d{4})\s*[年\-至到]\s*(?:20)?(\d{2,4})\s*年?", query)
    if m:
        y1 = int(m.group(1))
        y2 = int(m.group(2))
        if y2 < 100:
            y2 = 2000 + y2
        return (min(y1, y2), max(y1, y2))
    # "2025年" (单年)
    m = re.search(r"(?<!\d)(\d{4})\s*年", query)
    if m:
        y = int(m.group(1))
        return (y, y)
    # "近N年" / "最近N年"
    m = re.search(r"[近最]近?\s*(\d+)\s*年", query)
    if m:
        n = int(m.group(1))
        current_year = datetime.datetime.now().year
        return (current_year - n + 1, current_year)
    return (None, None)


def _try_parse_year(val: str) -> int:
    """尝试从字符串中解析年份，失败返回 0。"""
    try:
        return int(str(val).strip()[:4])
    except (ValueError, TypeError):
        return 0


# ============================================================================
# 打分与排序
# ============================================================================

def _score_paper(query: str, paper: dict) -> float:
    """加权 token overlap 打分。查询会先做概念扩展。"""
    expanded_query = expand_query(query)
    query_tokens = _tokenize(expanded_query)
    if not query_tokens:
        return 0.0

    def _overlap(target_text: str) -> float:
        target_tokens = _tokenize(target_text)
        if not target_tokens:
            return 0.0
        q_set = set(query_tokens)
        t_set = set(target_tokens)
        inter = q_set & t_set
        return len(inter) / len(q_set)  # 查询 token 的覆盖率

    score = (
        _overlap(paper.get("title", "")) * 4.0 +
        _overlap(paper.get("keywords", "")) * 3.0 +
        _overlap(paper.get("search_text", "")) * 1.5 +
        _overlap(paper.get("journal", "")) * 1.0
    )

    # 高影响因子期刊微幅加成
    try:
        if_val = float(paper.get("impact_factor", "0"))
        if if_val >= 8.0:
            score *= 1.05
    except (ValueError, TypeError):
        pass

    return score


def _score_and_rank(query: str, candidates: list[dict]) -> list[tuple[dict, float]]:
    """对候选论文执行加权 token overlap 打分并降序排列。"""
    scored = [(p, _score_paper(query, p)) for p in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ============================================================================
# 主检索入口
# ============================================================================

def retrieve_papers(
    query: str,
    paper_index: list[dict],
    top_n: int = 8,
) -> list[dict]:
    """检索最相关的 N 篇本地文献。

    Token 匹配 + 语义相似度混合打分，支持年份过滤和智能回退。
    调用前需先执行 build_semantic_index(paper_index) 构建语义索引。

    Args:
        query: 用户查询（中英混合，支持年份限定如 "2025年"）。
        paper_index: 论文元数据列表，每项需包含 title / keywords /
                     search_text / journal / year / impact_factor 字段。
        top_n: 返回的最大文献数。

    Returns:
        按混合得分降序排列的论文列表，最多 top_n 篇。
    """
    if not paper_index:
        return []

    def _blended_topn(cands: list[dict], n: int) -> list[dict]:
        """Token + 语义混合打分，取 top-N。"""
        if not cands:
            return []
        # Token 分数
        token_scored = _score_and_rank(query, cands)
        # 语义分数 — 查找候选在完整索引中的位置
        cand_indices = []
        for p, _ in token_scored:
            try:
                cand_indices.append(paper_index.index(p))
            except ValueError:
                cand_indices.append(0)
        sem_scores = _semantic_scores(query, cand_indices)
        # 归一化 + 混合
        t_max = max(s for _, s in token_scored) if token_scored else 1.0
        s_max_val = float(np.max(sem_scores)) if len(sem_scores) > 0 and np.max(sem_scores) > 0 else 1.0
        blended = []
        for i, (paper, ts) in enumerate(token_scored):
            tn = ts / t_max if t_max > 0 else 0
            sn = sem_scores[i] / s_max_val if s_max_val > 0 else 0
            blended.append((paper, 0.55 * tn + 0.45 * sn))
        blended.sort(key=lambda x: x[1], reverse=True)
        return [p for p, s in blended[:n] if s > 0.03]

    # 年份过滤
    y_min, y_max = _parse_year_filter(query)
    candidates = paper_index
    year_note = ""
    if y_min is not None:
        filtered = [p for p in candidates
                    if _try_parse_year(p.get("year", "")) and
                    y_min <= _try_parse_year(p.get("year", "")) <= y_max]
        if filtered:
            candidates = filtered
            year_note = f" {y_min}-{y_max}"
        else:
            logger.info(f"[检索] 年份 {y_min}-{y_max} 无匹配，已放宽年份限制。")

    # 第一轮：混合检索
    results = _blended_topn(candidates, top_n)

    # 智能回退：如果结果太少（<3条），去掉年份过滤重试
    if len(results) < 3 and y_min is not None:
        results = _blended_topn(paper_index, top_n)
        if results:
            logger.info("[检索] 精确匹配较少，已扩大检索范围。")

    # 最终回退：如果仍无结果，返回最新的高影响力论文
    if not results:
        results = paper_index[:top_n]
        logger.info("[检索] 未找到直接匹配，返回最新文献供参考。")

    # 打印年份分布
    years: set[str] = set()
    for p in results:
        y = p.get("year", "")
        if y:
            years.add(str(y))
    logger.info(
        f"[检索] 匹配 {len(results)} 篇{year_note}"
        + (f"（年份: {', '.join(sorted(years))}）" if years else "")
    )

    return results
