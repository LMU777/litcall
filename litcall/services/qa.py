"""litcall.services.qa — Knowledge-base Q&A with DeepSeek-powered academic AI tutor.

选项 [8]：知识库问答 — 教授级学术AI导师。

Self-contained module. NO imports from literature_agent.py.

Components:
  - Paper index builder (parses Obsidian markdown notes)
  - Semantic search (char n-gram TF-IDF + token overlap)
  - DeepSeek chat (LLM-powered academic Q&A)
  - Verification (cross-checks LLM claims against local index)
"""

import asyncio
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
import numpy as np

from litcall.core.config import config
from litcall.core.paths import BASE_DIR, OBSIDIAN_DIR
from litcall.services.concept_map import expand_query

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Module-level state
# ═══════════════════════════════════════════════════════════════

_qa_paper_index: list = []          # 内存论文索引，首次进入时构建
_qa_chat_history: list = []         # 对话历史 [{"role": "user"|"assistant", "content": ...}]
_qa_last_papers: list = []          # 上一轮检索到的论文
_qa_use_external: bool = True       # 是否允许使用外部知识
_qa_top_n: int = 8                  # 检索论文数量

# ── 英文停用词 ──
_QA_STOPWORDS: frozenset = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "some", "its",
    "with", "that", "this", "from", "they", "will", "would", "there", "their",
    "which", "were", "when", "what", "who", "how", "where", "into", "more",
    "than", "also", "about", "over", "after", "each", "other", "only", "most",
    "may", "such", "these", "them", "then", "should", "could",
})

# Q&A 笔记保存目录
_QA_NOTES_DIR = OBSIDIAN_DIR / "QA笔记"
# Q&A 对话历史持久化文件
_QA_HISTORY_FILE = OBSIDIAN_DIR.parent / "qa_history.json"

# ── 语义检索状态 ──
_semantic_vocab: dict = {}          # n-gram → column index
_semantic_vectors: "np.ndarray | None" = None  # (n_papers, n_vocab) TF-IDF 矩阵
_semantic_idf: "np.ndarray | None" = None      # (n_vocab,) IDF 权重


# ═══════════════════════════════════════════════════════════════
#  Tokenizer & char n-grams
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  Semantic index (char n-gram TF-IDF)
# ═══════════════════════════════════════════════════════════════

def _build_semantic_index(papers: list[dict]):
    """构建字符 3-gram + 4-gram TF-IDF-L2 矩阵，用于语义相似度计算。"""
    global _semantic_vocab, _semantic_vectors, _semantic_idf
    from collections import Counter

    # 收集所有论文的 n-gram 集合
    all_ngrams: list[set[str]] = []
    for p in papers:
        text = p.get("search_text", "")
        ngrams = set(_char_ngrams(text, n=3) + _char_ngrams(text, n=4))
        all_ngrams.append(ngrams)

    # 文档频率 → 词汇表（只保留出现在 ≥2 篇文献中的 n-gram，控制噪音）
    df = Counter()
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
        logger.warning("[QA] 语义索引词汇为空，回退到纯 token 检索。")
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

    logger.info(f"[QA] 语义索引：{n_vocab} 个 n-gram 特征, {n_papers} 篇文献")


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


# ═══════════════════════════════════════════════════════════════
#  Obsidian note parser & paper index builder
# ═══════════════════════════════════════════════════════════════

def _parse_obsidian_note(filepath: Path) -> Optional[dict]:
    """解析单篇 Obsidian 笔记：提取 YAML frontmatter + 7个章节正文。"""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    # --- 提取 YAML frontmatter（第一个 --- ... --- 块）---
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not fm_match:
        return None  # 无 frontmatter 的不是论文笔记
    fm_text = fm_match.group(1)
    body_text = content[fm_match.end():]

    # 简易 YAML 解析（flat key: value，无嵌套）
    paper: dict = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\w+):\s*(.*)", line)
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        # 去掉首尾引号
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        # tags 字段特殊处理：列表 → 分号分隔字符串
        if key == "tags" and val.startswith("["):
            items = re.findall(r"[\w-]+", val)
            val = "; ".join(items)
        paper[key] = val

    title = paper.get("title", "")
    if not title or title == "Untitled":
        return None  # 不是有效论文笔记

    # --- 提取章节正文 ---
    SECTION_NAMES = [
        "研究背景与动机", "研究问题", "变量汇总", "研究方法",
        "方法论详解", "研究结果", "讨论与结论", "创新点", "局限与展望",
    ]
    sections: dict = {}       # 截断版，用于检索打分
    sections_full: dict = {}  # 完整版，发送给 DeepSeek
    for sec_name in SECTION_NAMES:
        # 匹配 "## 研究背景与动机" 之类的 header
        pattern = rf"^##\s+{re.escape(sec_name)}\s*\n(.*?)(?=^##\s|\Z)"
        m = re.search(pattern, body_text, re.DOTALL | re.MULTILINE)
        if m:
            text = m.group(1).strip()
            sections_full[sec_name] = text  # 保留完整原文
            # 检索用截断版：控制内存占用，800 字符对 token 匹配已足够
            if len(text) > 800:
                text = text[:800] + "…"
            sections[sec_name] = text
        else:
            sections[sec_name] = ""
            sections_full[sec_name] = ""

    # --- 构建 search_text（用于检索打分）---
    search_parts = [title]
    kw = paper.get("keywords", "")
    if kw:
        search_parts.append(kw.replace(";", " ").replace("，", " "))
    jn = paper.get("journal", "")
    if jn:
        search_parts.append(jn)
    # 章节标题（帮助匹配中文查询）
    search_parts.append(" ".join(SECTION_NAMES))
    for sn in SECTION_NAMES:
        if sections.get(sn):
            search_parts.append(sections[sn])  # 截断版用于检索（本地匹配，不占API token）
    search_text = " ".join(search_parts)

    # --- 构建 full_body（用于发送给 DeepSeek 的上下文）---
    # 使用完整章节正文，确保教授级问答能获取论文全部细节
    body_parts = []
    for sn in SECTION_NAMES:
        if sections_full.get(sn):
            body_parts.append(f"## {sn}\n{sections_full[sn]}")
    full_body = "\n\n".join(body_parts)

    relpath = filepath.relative_to(OBSIDIAN_DIR)
    return {
        "path": str(filepath),
        "relpath": str(relpath).replace("\\", "/"),
        "title": title,
        "authors": paper.get("authors", ""),
        "first_author": paper.get("first_author", ""),
        "year": paper.get("year", ""),
        "journal": paper.get("journal", ""),
        "impact_factor": paper.get("impact_factor", ""),
        "keywords": paper.get("keywords", ""),
        "tags": paper.get("tags", ""),
        "doi": paper.get("doi", ""),
        "sections": sections,
        "full_body": full_body,
        "search_text": search_text,
    }


def _build_paper_index(force_rebuild: bool = False) -> list[dict]:
    """遍历 Obsidian vault，构建内存论文索引。首次构建后缓存。"""
    global _qa_paper_index
    if _qa_paper_index and not force_rebuild:
        return _qa_paper_index

    papers: list[dict] = []
    md_files = list(OBSIDIAN_DIR.glob("**/*.md"))
    for fp in md_files:
        # 跳过非论文文件
        if fp.name == "_index.md":
            continue
        if "concepts" in fp.parts:
            continue
        if ".obsidian" in fp.parts:
            continue
        paper = _parse_obsidian_note(fp)
        if paper:
            papers.append(paper)

    # 按年份降序 + 影响因子降序排列
    def _sort_key(p: dict) -> tuple:
        try:
            yr = int(p.get("year", "0"))
        except (ValueError, TypeError):
            yr = 0
        try:
            if_val = float(p.get("impact_factor", "0"))
        except (ValueError, TypeError):
            if_val = 0.0
        return (-yr, -if_val)

    papers.sort(key=_sort_key)
    _qa_paper_index = papers
    logger.info(f"[QA] 论文索引构建完成：{len(papers)} 篇")

    # 同步构建语义索引（字符 n-gram TF-IDF）
    _build_semantic_index(papers)

    return papers


# ═══════════════════════════════════════════════════════════════
#  Retrieval: query scoring & year filter
# ═══════════════════════════════════════════════════════════════

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
    try:
        return int(str(val).strip()[:4])
    except (ValueError, TypeError):
        return 0


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
    scored = [(p, _score_paper(query, p)) for p in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _retrieve_papers(query: str) -> list[dict]:
    """检索最相关的 N 篇本地文献。Token 匹配 + 语义相似度混合打分，支持年份过滤和智能回退。"""
    global _qa_paper_index, _qa_top_n
    if not _qa_paper_index:
        _build_paper_index()

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
                cand_indices.append(_qa_paper_index.index(p))
            except ValueError:
                cand_indices.append(0)
        sem_scores = _semantic_scores(query, cand_indices)
        # 归一化 + 混合
        t_max = max(s for _, s in token_scored) if token_scored else 1.0
        s_max = float(np.max(sem_scores)) if len(sem_scores) > 0 and np.max(sem_scores) > 0 else 1.0
        blended = []
        for i, (paper, ts) in enumerate(token_scored):
            tn = ts / t_max if t_max > 0 else 0
            sn = sem_scores[i] / s_max if s_max > 0 else 0
            blended.append((paper, 0.55 * tn + 0.45 * sn))
        blended.sort(key=lambda x: x[1], reverse=True)
        return [p for p, s in blended[:n] if s > 0.03]

    # 年份过滤
    y_min, y_max = _parse_year_filter(query)
    candidates = _qa_paper_index
    year_note = ""
    if y_min is not None:
        filtered = [p for p in candidates
                    if _try_parse_year(p.get("year", "")) and
                    y_min <= _try_parse_year(p.get("year", "")) <= y_max]
        if filtered:
            candidates = filtered
            year_note = f" {y_min}-{y_max}"
        else:
            print(f"  [检索] 年份 {y_min}-{y_max} 无匹配，已放宽年份限制。")

    # 第一轮：混合检索
    results = _blended_topn(candidates, _qa_top_n)

    # 智能回退：如果结果太少（<3条），去掉年份过滤重试
    if len(results) < 3 and y_min is not None:
        results = _blended_topn(_qa_paper_index, _qa_top_n)
        if results:
            print(f"  [检索] 精确匹配较少，已扩大检索范围。")

    # 最终回退：如果仍无结果，返回最新的高影响力论文
    if not results:
        results = _qa_paper_index[:_qa_top_n]
        print(f"  [检索] 未找到直接匹配，返回最新文献供参考。")

    # 打印年份分布
    years = set()
    for p in results:
        y = p.get("year", "")
        if y:
            years.add(str(y))
    print(f"  [检索] 匹配 {len(results)} 篇{year_note}（年份: {', '.join(sorted(years))}）")

    return results


# ═══════════════════════════════════════════════════════════════
#  Answer verification
# ═══════════════════════════════════════════════════════════════

def _verify_answer_claims(answer: str, retrieved_papers: list[dict],
                          all_papers: list[dict]) -> list[str]:
    """验证 DeepSeek 回答中对本地文献的引用是否准确。

    扫描回答中的 (作者, 年份) 模式，与本地文献索引交叉比对。
    返回验证警告列表，用于提醒用户存疑的引用。
    """
    warnings: list[str] = []

    # 提取 (Author, Year) 引用模式
    # 英文: "De Bock (2026)", "Gelbrich et al. (2026)", "Zhang & Li (2025)", "Smith and Jones (2023)"
    cite_pattern = re.compile(
        r'([A-Z][a-zà-ü]+(?:\s[A-Z][a-zà-ü]+)?'     # 单/双词姓氏 (De Bock, Van Dijk)
        r'(?:\s(?:and|&)\s[A-Z][a-zà-ü]+(?:\s[A-Z][a-zà-ü]+)?)?'  # 可选第二作者
        r'(?:\set\s+al\.?)?)'                         # 可选 et al.（之后不跟名字）
        r'\s*[\(（](\d{4})[\)）]',
    )
    # 中文: "张三（2025）", "李四等（2024）"
    cn_cite_pattern = re.compile(
        r'([一-鿿]{2,4}(?:等)?)\s*[\(（](\d{4})[\)）]',
    )

    # 构建本地索引查找表: {lastname_firstname: {year: paper}}
    local_index: dict[str, dict[str, dict]] = {}
    for p in all_papers:
        authors = p.get("authors", "")
        year = str(p.get("year", ""))
        if not authors or not year:
            continue
        # 取第一作者姓氏
        first_author = authors.split(",")[0].split(";")[0].strip()
        lastname = first_author.split()[-1] if first_author else ""
        key = lastname.lower()
        if key not in local_index:
            local_index[key] = {}
        if year not in local_index[key]:
            local_index[key][year] = p

    retrieved_keys: set[tuple[str, str]] = set()
    for p in retrieved_papers:
        authors = p.get("authors", "")
        year = str(p.get("year", ""))
        first_author = authors.split(",")[0].split(";")[0].strip()
        lastname = first_author.split()[-1] if first_author else ""
        retrieved_keys.add((lastname.lower(), year))

    # 检查英文引用
    for m in cite_pattern.finditer(answer):
        name = m.group(1)
        year = m.group(2)
        lastname = name.split()[-1].split()[-1].lower()  # handles "et al."
        full_ref = f"{name} ({year})"

        if (lastname, year) in retrieved_keys:
            continue  # 已检索到，可直接对照原文核实
        if lastname in local_index and year in local_index[lastname]:
            # 存在于本地库但未被检索到
            warnings.append(
                f"[本地未检索] {full_ref} — 该文献在本地库中但未被本次检索匹配到，"
                f"建议核实引用内容: {local_index[lastname][year]['title'][:60]}"
            )
        elif lastname in local_index:
            # 作者存在但年份不同
            avail_years = sorted(local_index[lastname].keys())
            warnings.append(
                f"[年份不匹配] {full_ref} — 本地库中 {name} 的文献年份为 {', '.join(avail_years)}，"
                f"未找到 {year} 年的记录。可能来自外部知识。"
            )

    return warnings


# ═══════════════════════════════════════════════════════════════
#  DeepSeek chat
# ═══════════════════════════════════════════════════════════════

def _build_qa_messages(question: str, context_papers: list[dict],
                       chat_history: list[dict]) -> list[dict]:
    """构建发送给 DeepSeek 的完整 messages 数组。"""

    system_prompt = """你是一位在市场营销与人工智能营销交叉领域执教多年的资深教授。你的学生（一位博士生）会向你请教各种学术问题——从找文献、写综述，到理论讨论、方法选择、研究设计。你认真对待每一个问题，因为你知道这关系到学生的学术成长。

## 你的学术素养
- 理论功底深厚：能追溯概念的学术源头，比较不同学派的核心观点与争议
- 方法严谨：能评价研究设计的优劣，指出因果推断的局限，建议更合适的方法
- 深入浅出：能把复杂的概念、模型、方法拆解开来逐步讲解，让学生真正理解
- 视野开阔：既能深入一个具体问题，也能跳出该问题看到更广阔的学术图景和研究机会
- 诚实谦逊：不确定的地方明确标注"这一点我并非完全确定"，不假装全知

## 你的知识来源
1. [本地文献] —— 用户已精读并整理的论文笔记，是你回答的首要根据地
2. [外部知识] —— 你自己的学术积累（经典理论、经典文献、方法知识、学科共识）

## 根据问题类型调整回答方式

当学生请你**查找/推荐文献**时：
- 先列出本地文献库中匹配的论文，简要说明每篇与问题的关联
- 再推荐值得检索的外部文献（标注"建议检索"），包括作者、大致方向、推荐理由
- 说明检索策略：可以搜哪些关键词、关注哪些期刊

当学生请你**写文献综述**时：
- 按理论脉络或研究主题组织，而非逐篇罗列
- 指出不同研究的共识、分歧、演化趋势
- 最后给出总结性评述：这个领域整体走到了哪里，还缺什么

当学生与你**讨论理论或概念**时：
- 从经典定义讲到前沿发展，追溯概念的学术演化
- 讲清核心假设、实证支持、适用边界
- 联系学生已有的本地文献：哪些论文支持了这个理论，哪些提出了挑战
- 用具体例子帮助理解抽象概念

当学生请你**比较方法或评价研究设计**时：
- 说清每种方法的逻辑、假设、优劣、适用场景
- 如果本地文献中有使用这些方法的论文，引用它们作为案例
- 给出具体建议：在学生的研究情境下，哪种方法更合适，为什么

当学生请你**找研究空白**时：
- 基于本地文献的逻辑链条，指出哪些问题已被充分研究、哪些还缺
- 区分"没人做过所以是空白"和"有人尝试过但没解决所以是机会"
- 建议可行的研究切入点和理论视角

当学生与你**开放式学术讨论**时：
- 展现批判性思维，可以提出与主流观点不同的看法
- 引用证据支持你的论点，区分"学界共识"、"少数派观点"和"我个人认为"
- 鼓励学生思考：这背后更深层的问题是什么？

## 回答规则
1. 始终标注信息来源：[本地文献] / [外部知识]
2. 不确定的内容标注"待验证"或"我对此并非完全确定"
3. 推荐外部文献时注明"建议检索"——你的学生需要知道哪些是已验证的、哪些是需要自己去核实的
4. 中文回答，专业术语保留英文"""

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # 最近 6 轮对话历史（12 条消息）
    if chat_history:
        messages.extend(chat_history[-12:])

    # 构建本地文献上下文
    if context_papers:
        context_blocks: list[str] = []
        for i, p in enumerate(context_papers, 1):
            block = f"""### [{i}] {p['title']}
**作者**: {p.get('authors', 'N/A')}
**期刊**: {p.get('journal', 'N/A')} ({p.get('year', 'N/A')}) | IF={p.get('impact_factor', 'N/A')}
**关键词**: {p.get('keywords', 'N/A')}

{p.get('full_body', '')}"""
            context_blocks.append(block)
        context_text = "\n\n---\n\n".join(context_blocks)

        user_message = f"""以下是你本地文献库中与学生问题相关的论文深度阅读笔记：

{context_text}

---
**学生的问题**: {question}

请根据问题类型，以教授的身份回答。如果本地文献足以回答，以本地文献为主、外部知识为辅。如果本地文献不足以完全回答，请调用你的知识储备进行补充，明确标注每部分信息的来源。"""
    else:
        user_message = f"""**学生的问题**: {question}

本地文献库中未找到与该问题直接相关的论文。请基于你的学术知识储备回答，标注为[外部知识]。如果合适，建议学生检索哪些方向的文献、使用哪些关键词、关注哪些期刊。"""

    messages.append({"role": "user", "content": user_message})
    return messages


async def _chat_via_deepseek(messages: list[dict]) -> Optional[str]:
    """通用 DeepSeek 对话函数。复用现有 API 调用模式。"""
    deepseek_key = config.get("deepseek_api_key", "")
    deepseek_model = config.get("deepseek_model", "deepseek-v4-pro")
    if not deepseek_key:
        logger.error("[QA] DeepSeek API Key 未配置！")
        return None

    # 清洗消息中的 surrogate 字符（部分旧笔记可能有编码残留）
    def _clean_text(s: str) -> str:
        if not s:
            return ""
        # 移除孤立 surrogate 字符 (U+D800-U+DFFF)
        return re.sub(r'[\ud800-\udfff]', '', s)

    clean_messages = []
    for m in messages:
        clean_messages.append({
            "role": m["role"],
            "content": _clean_text(m.get("content", "")),
        })

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {deepseek_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": deepseek_model,
                "messages": clean_messages,
                "temperature": 0.5,
                "max_tokens": 4096,
            }
            async with session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"[QA] DeepSeek API 错误: HTTP {resp.status} - {error_text[:200]}")
                    return None
                result = await resp.json()
                return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"[QA] DeepSeek API 调用异常: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  Q&A history persistence
# ═══════════════════════════════════════════════════════════════

def _save_qa_history() -> None:
    """静默保存对话历史到 JSON 文件，用于跨会话恢复。"""
    try:
        with open(_QA_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(_qa_chat_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"QA 历史保存失败: {e}")


def _save_qa_chat(chat_history: list[dict]):
    """保存当前 Q&A 对话到 Obsidian QA笔记目录。"""
    if not chat_history:
        print("  [QA] 没有对话内容可保存。")
        return

    _QA_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"QA_{timestamp}.md"
    filepath = _QA_NOTES_DIR / filename

    # 提取首个问题作为摘要
    first_q = ""
    for msg in chat_history:
        if msg["role"] == "user":
            first_q = msg["content"][:80]
            break

    # 收集引用文献的 wikilinks
    ref_wikilinks: list[str] = []
    if _qa_last_papers:
        for p in _qa_last_papers:
            relpath = p.get("relpath", "")
            if relpath:
                ref_wikilinks.append(f"  - [[{relpath.replace('.md', '')}|{p['title'][:60]}]]")

    # 构建内容
    lines = [
        "---",
        f"date: {now.strftime('%Y-%m-%d %H:%M')}",
        f"question_summary: \"{first_q}\"",
        "tags: [QA笔记]",
        "---",
        "",
        "# 知识库问答记录",
        "",
    ]

    for msg in chat_history:
        if msg["role"] == "user":
            lines.append(f"## 🤔 问题\n\n{msg['content']}\n")
        elif msg["role"] == "assistant":
            lines.append(f"## 🤖 回答\n\n{msg['content']}\n")

    if ref_wikilinks:
        lines.append("## 引用的本地文献\n")
        lines.extend(ref_wikilinks)
        lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  [QA] 对话已保存到: {filepath}")
    logger.info(f"[QA] 对话已保存: {filepath}")


def _print_qa_help():
    """打印 Q&A 模式帮助。"""
    state = "开启" if _qa_use_external else "关闭"
    print(f"""
╔══════════════════════════════════════════════════════╗
║  知识库问答 — 教授级学术AI导师                        ║
╠══════════════════════════════════════════════════════╣
║  直接输入问题即可获得基于本地文献+外部知识的深度回答    ║
║                                                      ║
║  特殊命令:                                            ║
║    /exit      — 返回主菜单                            ║
║    /save      — 保存当前对话到 Obsidian QA笔记         ║
║    /clear     — 清空对话历史                          ║
║    /papers    — 重新显示上一轮检索到的本地文献          ║
║    /n <数字>  — 设置检索文献数量 (默认8, 范围3-15)     ║
║    /external  — 切换是否允许外部知识 (当前: {state})   ║
║    /help      — 显示此帮助                            ║
║                                                      ║
║  信息来源标注:                                        ║
║    [本地]本地文献 = 来自你的 Obsidian 论文笔记          ║
║    [外部]外部知识 = 来自 DeepSeek 的学术知识储备       ║
╚══════════════════════════════════════════════════════╝
""")


# ═══════════════════════════════════════════════════════════════
#  Interactive Q&A loop (flow_qa)
# ═══════════════════════════════════════════════════════════════

async def flow_qa():
    """选项 [8]：知识库问答 — 教授级学术AI导师。"""
    global _qa_paper_index, _qa_chat_history, _qa_last_papers
    global _qa_use_external, _qa_top_n

    # 构建索引
    if not _qa_paper_index:
        print("\n[QA] 正在构建知识库索引...")
        _build_paper_index()
        print(f"[OK] 已索引 {len(_qa_paper_index)} 篇文献笔记\n")

    # 尝试恢复上次对话历史
    _qa_chat_history = []
    if _QA_HISTORY_FILE.exists():
        try:
            with open(_QA_HISTORY_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    _qa_chat_history = loaded
                    rounds = len(_qa_chat_history) // 2
                    if rounds > 0:
                        print(f"\n[v] 已恢复上次对话 ({rounds} 轮)。输入 /clear 清空历史。")
        except Exception:
            pass

    print("=" * 60)
    print("  知识库问答 — 教授级学术AI导师")
    print(f"  本地文献: {len(_qa_paper_index)} 篇 | 外部知识: {'开启' if _qa_use_external else '关闭'}")
    print("=" * 60)
    print("  直接输入问题进行提问。输入 /help 查看帮助。")
    print("=" * 60)

    while True:
        # 读取用户输入
        try:
            question = input("\n[Q] > ").strip()
        except (EOFError, KeyboardInterrupt):
            _save_qa_history()
            print("\n已退出问答模式。")
            break

        if not question:
            continue

        # ── 特殊命令处理 ──
        if question.startswith("/"):
            cmd = question.split()[0].lower()
            if cmd in ("/exit", "/quit"):
                _save_qa_history()
                print("已退出问答模式。")
                break
            elif cmd == "/help":
                _print_qa_help()
                continue
            elif cmd == "/clear":
                _qa_chat_history = []
                _qa_last_papers = []
                _save_qa_history()
                print("[v] 对话历史已清空。")
                continue
            elif cmd == "/papers":
                if _qa_last_papers:
                    print(f"\n上一轮检索到的本地文献 ({len(_qa_last_papers)} 篇):")
                    for i, p in enumerate(_qa_last_papers, 1):
                        print(f"  [{i}] {p['title'][:70]}")
                        print(f"      {p.get('first_author', '?')} ({p.get('year', '?')}) | "
                              f"{p.get('journal', '?')[:40]} | IF={p.get('impact_factor', '?')}")
                else:
                    print("尚无检索记录。")
                continue
            elif cmd == "/external":
                _qa_use_external = not _qa_use_external
                state = "开启" if _qa_use_external else "关闭"
                print(f"[v] 外部知识已{state}。")
                if not _qa_use_external:
                    print("  (将仅基于本地文献回答，不足时诚实告知)")
                continue
            elif cmd == "/save":
                _save_qa_chat(_qa_chat_history)
                continue
            elif cmd == "/n":
                parts = question.split()
                if len(parts) >= 2:
                    try:
                        n = int(parts[1])
                        if 3 <= n <= 15:
                            _qa_top_n = n
                            print(f"[v] 检索数量已设置为 {n} 篇。")
                        else:
                            print("检索数量范围: 3-15")
                    except ValueError:
                        print("用法: /n <数字>，如 /n 10")
                else:
                    print("用法: /n <数字>，如 /n 10")
                continue
            else:
                print(f"未知命令: {cmd}。输入 /help 查看可用命令。")
                continue

        # ── 检索本地文献 ──
        relevant = _retrieve_papers(question)
        _qa_last_papers = relevant

        if relevant:
            print(f"\n[检索] 匹配到 {len(relevant)} 篇本地文献:")
            for i, p in enumerate(relevant, 1):
                print(f"  [{i}] {p['title'][:70]}")
                print(f"      {p.get('first_author', '?')} ({p.get('year', '?')}) | "
                      f"{p.get('journal', '?')[:40]}")
        else:
            print("\n[检索] 本地文献中未找到直接匹配的论文。")
            if _qa_use_external:
                print("   将以外部知识回答，建议后续补充相关文献。")

        # ── 构建 messages 并调用 DeepSeek ──
        if not _qa_use_external and not relevant:
            print("\n[DeepSeek] 本地文献无匹配，且外部知识已关闭。请尝试换个问题或开启外部知识 (/external)。")
            continue

        print("\n[DeepSeek] 正在调用 DeepSeek V4 Pro 生成回答...")
        messages = _build_qa_messages(question, relevant, _qa_chat_history)
        answer = await _chat_via_deepseek(messages)

        if not answer:
            print("\n[ERROR] DeepSeek API 调用失败，请检查网络和 API Key 配置。可重试。")
            continue

        # ── 显示回答 ──
        # 清洗 GBK 无法编码的字符（上下标、emoji 等）
        def _safe_print(text: str) -> None:
            try:
                print(text)
            except UnicodeEncodeError:
                # 逐字符打印，跳过无法编码的
                for ch in text:
                    try:
                        print(ch, end="")
                    except UnicodeEncodeError:
                        print("?", end="")
                print()

        print("\n" + "─" * 50)
        _safe_print(answer)
        print("─" * 50)

        # ── 引用验证：检查回答中对本地文献的归因是否准确 ──
        if relevant:
            warnings = _verify_answer_claims(answer, relevant, _qa_paper_index)
            if warnings:
                print("\n[验证] 以下引用需要注意：")
                for w in warnings:
                    print(f"  {w}")

        # ── 更新对话历史 ──
        _qa_chat_history.append({"role": "user", "content": question})
        _qa_chat_history.append({"role": "assistant", "content": answer})

        # 限制历史长度（最近 10 轮 = 20 条）
        if len(_qa_chat_history) > 20:
            _qa_chat_history = _qa_chat_history[-20:]
        _save_qa_history()


# ═══════════════════════════════════════════════════════════════
#  Public API — programmatic usage
# ═══════════════════════════════════════════════════════════════

async def chat_with_deepseek(messages: list) -> Optional[str]:
    """Send messages to DeepSeek and get response.

    Args:
        messages: List of {"role": "user"|"assistant"|"system", "content": "..."}

    Returns:
        Model response text, or None on failure.
    """
    return await _chat_via_deepseek(messages)


def build_paper_index(force_rebuild: bool = False) -> list:
    """Build in-memory paper index from Obsidian vault.

    Parses all Obsidian markdown notes, extracts YAML frontmatter and
    section content, and caches the result for subsequent queries.

    Args:
        force_rebuild: If True, rebuild even if already cached.

    Returns:
        List of paper dicts with keys: title, authors, year, journal,
        impact_factor, keywords, sections, full_body, search_text, etc.
    """
    return _build_paper_index(force_rebuild=force_rebuild)


async def answer_question(question: str,
                          paper_index: Optional[list] = None,
                          chat_history: Optional[list] = None) -> dict:
    """Answer a research question using the knowledge base.

    Orchestrates the full Q&A pipeline:
    1. Retrieve relevant papers from the local index
    2. Build prompt messages with paper context + chat history
    3. Call DeepSeek for professor-level academic answer
    4. Verify answer claims against the local index

    Args:
        question: Research question text (Chinese or English).
        paper_index: Optional pre-built paper index. If None, builds one.
        chat_history: Optional conversation history for multi-turn context.

    Returns:
        dict with keys:
            answer (str): DeepSeek's response.
            papers (list): Retrieved paper dicts.
            warnings (list): Reference verification warnings.
            error (str|None): Error message if the API call failed.
    """
    global _qa_paper_index, _qa_chat_history

    # Use provided index or build one
    if paper_index is not None:
        _qa_paper_index = paper_index
    if not _qa_paper_index:
        _build_paper_index()

    # Set up chat history
    _qa_chat_history = chat_history or []

    # ── Retrieve relevant papers ──
    relevant = _retrieve_papers(question)

    # ── Call DeepSeek ──
    messages = _build_qa_messages(question, relevant, _qa_chat_history)
    answer = await _chat_via_deepseek(messages)

    if answer is None:
        return {
            "answer": "",
            "papers": relevant,
            "warnings": [],
            "error": "DeepSeek API call failed. Check API key and network.",
        }

    # ── Verify claims ──
    warnings = _verify_answer_claims(answer, relevant, _qa_paper_index)

    # ── Update history (if using module-level state) ──
    _qa_chat_history.append({"role": "user", "content": question})
    _qa_chat_history.append({"role": "assistant", "content": answer})
    if len(_qa_chat_history) > 20:
        _qa_chat_history = _qa_chat_history[-20:]

    return {
        "answer": answer,
        "papers": relevant,
        "warnings": warnings,
        "error": None,
    }


# ═══════════════════════════════════════════════════════════════
#  QA Session Management
# ═══════════════════════════════════════════════════════════════

_QA_SESSIONS_DIR = BASE_DIR / "qa_sessions"
_QA_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _list_qa_sessions() -> List[Dict]:
    """列出所有已保存的 QA 会话（按修改时间倒序）。"""
    sessions = []
    try:
        for f in sorted(_QA_SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "id": f.stem,
                "name": data.get("name", f.stem[:30]),
                "created": data.get("created", ""),
                "updated": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "message_count": len(data.get("messages", [])),
                "first_question": data.get("first_question", ""),
            })
    except Exception:
        pass
    return sessions


def _save_qa_session(session_id: str, name: str, messages: List[Dict]) -> None:
    """保存一个 QA 会话到独立文件。"""
    try:
        now = datetime.datetime.now().isoformat()
        session_file = _QA_SESSIONS_DIR / f"{session_id}.json"
        first_q = ""
        for m in messages:
            if m.get("role") == "user":
                first_q = m.get("content", "")[:80]
                break
        created = now
        if session_file.exists():
            try:
                existing = json.loads(session_file.read_text(encoding="utf-8"))
                created = existing.get("created", now)
            except Exception:
                pass
        data = {
            "name": name,
            "created": created,
            "updated": now,
            "first_question": first_q,
            "messages": messages,
        }
        session_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"保存会话失败: {e}")


def _load_qa_session(session_id: str) -> Optional[List[Dict]]:
    """加载指定会话的消息列表。"""
    try:
        path = _QA_SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("messages", [])
    except Exception:
        pass
    return None


def _delete_qa_session(session_id: str) -> bool:
    """删除指定会话。"""
    try:
        path = _QA_SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
    except Exception:
        pass
    return False


def _generate_session_name(messages: List[Dict]) -> str:
    """根据对话内容自动生成会话名称。"""
    for m in messages:
        if m.get("role") == "user":
            q = m["content"].strip()
            # 截取第一个有意义的问题作为名称
            q_clean = re.sub(r'\d{4}-\d{4}年\s*', '', q)  # 去年份前缀
            return q_clean[:60] + ("..." if len(q_clean) > 60 else "")
    return f"会话 {datetime.datetime.now().strftime('%m-%d %H:%M')}"


# ═══════════════════════════════════════════════════════════════
#  Paper field helper for sections-based paper index
# ═══════════════════════════════════════════════════════════════

# Map English field names to Chinese section keys in the paper dict
_QA_FIELD_TO_SECTION: dict[str, str] = {
    "abstract": "研究背景与动机",
    "research_questions": "研究问题",
    "theories": "研究背景与动机",
    "variables": "变量汇总",
    "methods": "研究方法",
    "key_findings": "研究结果",
    "discussion": "讨论与结论",
    "limitations": "局限与展望",
    "future_directions": "局限与展望",
}


def _qa_paper_field(paper: dict, field: str) -> str:
    """Get a field from a paper dict, trying flat YAML key first, then sections mapping.

    The paper index in qa.py stores section content under ``sections`` dict
    with Chinese keys.  This helper allows the agent tool functions to use
    conventional English field names while transparently falling back to
    the sections-based storage.
    """
    # Try flat key first (from YAML frontmatter)
    val = paper.get(field, "")
    if val:
        return val
    # Fall back to sections mapping
    section_key = _QA_FIELD_TO_SECTION.get(field)
    if section_key:
        return paper.get("sections", {}).get(section_key, "")
    return ""


# ═══════════════════════════════════════════════════════════════
#  Agent Planner / Tools
# ═══════════════════════════════════════════════════════════════

AGENT_TOOLS = {
    "search_papers": {
        "description": "检索本地文献库。参数：query(搜索查询), n(返回篇数,默认8)。返回论文列表（标题、作者、年份、期刊、摘要）。",
        "function": "_tool_search_papers",
    },
    "read_paper": {
        "description": "深度阅读一篇论文的完整笔记。参数：title(论文标题，模糊匹配)。返回完整笔记（18个字段）。",
        "function": "_tool_read_paper",
    },
    "find_theories": {
        "description": "从本地文献库中找出与某个主题相关的理论框架。参数：topic(研究主题)。返回理论列表及来源论文。",
        "function": "_tool_find_theories",
    },
    "find_gaps": {
        "description": "从本地文献的未来研究方向中提取与某个主题相关的研究空白。参数：topic(研究主题)。返回研究方向列表。",
        "function": "_tool_find_gaps",
    },
    "extract_methods": {
        "description": "提取文献中使用的分析方法。参数：papers(论文标题列表，最多5篇)。返回每篇论文的方法摘要。",
        "function": "_tool_extract_methods",
    },
    "search_all_papers": {
        "description": "【全面检索】检索本地文献库中与query相关的ALL论文（不限制返回数量）。适用于理论梳理、文献综述、研究空白分析等需要穷尽所有相关文献的任务。参数：query(搜索查询)。返回所有匹配论文的完整列表。",
        "function": "_tool_search_all_papers",
    },
    "search_external": {
        "description": "调用AI的外部知识回答本地文献未覆盖的问题。参数：question(需要外部知识回答的问题)。返回基于AI知识的回答。",
        "function": "_tool_search_external",
    },
}

AGENT_PLANNER_SYSTEM = """你是一个学术研究任务的规划器。用户会给你一个研究目标，你需要把它拆解为可执行的步骤序列。

你可以使用的工具只有以下这些（不要编造其他工具）：
{tool_descriptions}

可用数据：本地文献库论文，每篇有完整的结构化笔记（标题、作者、理论、变量、方法、结果、未来研究方向等）。使用 search_all_papers 可获取全部相关论文。

请输出一个 JSON 数组，每个元素是一个步骤：
[
  {{"tool": "search_papers", "args": {{"query": "...", "n": 8}}, "reason": "为什么需要这步"}},
  {{"tool": "read_paper", "args": {{"title": "..."}}, "reason": "..."}},
  ...
]

## 工具选择指南（重要！）
- 快速查找、了解概况 → search_papers（返回 top-N，默认8篇）
- 理论梳理、文献综述、研究空白分析 → search_all_papers（返回所有相关论文，不截断）
- 查找某个主题的理论框架 → find_theories（已在全库搜索，无需配合 search_all_papers）
- 查找未来研究方向 → find_gaps（已在全库搜索，无需配合 search_all_papers）
- 深度阅读单篇论文 → read_paper
- 提取研究方法 → extract_methods
- 本地文献无法覆盖时补充 → search_external

## 规则
1. 简单的事实性问题、概念解释、一两句话能回答的问题 → 输出空数组 []（走快速问答模式）
2. 只有需要多篇文献综合、跨步骤推理、需要"找→读→分析→写"链路的问题才需要规划
3. 第一步通常是 search_papers 或 search_all_papers 或 find_theories，最后不要加"write/summarize"步骤（系统会自动综合）
4. 步骤 2-5 个，不要过度拆分
5. search_external 只在本地文献明确无法覆盖时使用，不要作为首选
6. 当用户明确要求"所有""全部""穷尽""全面"检索时，必须使用 search_all_papers 而非 search_papers

只输出 JSON 数组，不要输出任何其他文字。"""


def _agent_get_tool_descriptions() -> str:
    return "\n".join(f"- {name}: {info['description']}" for name, info in AGENT_TOOLS.items())


# ═══ Tool Implementations ═══

def _tool_search_papers(query: str, n: int = 8) -> list[dict]:
    """检索本地文献库。"""
    global _qa_top_n
    old_n = _qa_top_n
    _qa_top_n = n
    try:
        papers = _retrieve_papers(query)
        return [
            {
                "title": p.get("title", "?")[:150],
                "first_author": p.get("first_author", "?"),
                "year": p.get("year", "?"),
                "journal": p.get("journal", "?")[:50],
                "keywords": p.get("keywords", "")[:80],
                "abstract_snippet": _qa_paper_field(p, "abstract")[:200],
            }
            for p in papers
        ]
    finally:
        _qa_top_n = old_n


def _tool_search_all_papers(query: str) -> list[dict]:
    """【全面检索】检索本地文献库中所有相关论文，不限制返回数量。

    适用于理论梳理、文献综述、研究空白分析等需要穷尽所有相关文献的任务。
    与 search_papers 的区别：search_papers 返回 top-N（默认8篇），本工具返回全部匹配论文。
    """
    global _qa_top_n, _qa_paper_index
    if not _qa_paper_index:
        _build_paper_index()

    old_n = _qa_top_n
    _qa_top_n = len(_qa_paper_index)  # 返回全部
    try:
        papers = _retrieve_papers(query)
        return [
            {
                "title": p.get("title", "?")[:200],
                "first_author": p.get("first_author", "?"),
                "year": p.get("year", "?"),
                "journal": p.get("journal", "?")[:80],
                "keywords": p.get("keywords", "")[:120],
                "abstract_snippet": _qa_paper_field(p, "abstract")[:300],
                "theories": _qa_paper_field(p, "theories")[:200],
                "future_directions": _qa_paper_field(p, "future_directions")[:200],
            }
            for p in papers
        ]
    finally:
        _qa_top_n = old_n


def _tool_read_paper(title: str) -> Optional[dict]:
    """深度阅读一篇论文的完整笔记。"""
    global _qa_paper_index
    if not _qa_paper_index:
        _build_paper_index()

    # 模糊匹配标题
    best = None
    best_score = 0
    title_lower = title.lower().strip()
    for p in _qa_paper_index:
        p_title = p.get("title", "").lower()
        # Token overlap
        query_tokens = set(title_lower.split())
        title_tokens = set(p_title.split())
        overlap = len(query_tokens & title_tokens)
        if overlap > best_score:
            best_score = overlap
            best = p
        # 子串匹配加分
        if title_lower[:30] in p_title or p_title[:30] in title_lower:
            best_score = max(best_score, len(title_lower) // 4)

    if best and best_score >= 2:
        return {
            "title": best.get("title", "?")[:200],
            "first_author": best.get("first_author", "?"),
            "year": best.get("year", "?"),
            "journal": best.get("journal", "?"),
            "research_questions": _qa_paper_field(best, "research_questions")[:300],
            "theories": _qa_paper_field(best, "theories")[:200],
            "variables": _qa_paper_field(best, "variables")[:200],
            "methods": _qa_paper_field(best, "methods")[:300],
            "key_findings": _qa_paper_field(best, "key_findings")[:400],
            "limitations": _qa_paper_field(best, "limitations")[:200],
            "future_directions": _qa_paper_field(best, "future_directions")[:200],
        }
    return None


def _tool_find_theories(topic: str) -> list[dict]:
    """从本地文献中找出与某个主题相关的理论框架。遍历全库所有论文，不限制返回数量。"""
    global _qa_paper_index
    if not _qa_paper_index:
        _build_paper_index()

    results = []
    topic_lower = topic.lower()
    for p in _qa_paper_index:
        text = " ".join([
            p.get("title", ""), _qa_paper_field(p, "abstract"),
            _qa_paper_field(p, "research_questions"), _qa_paper_field(p, "discussion"),
        ]).lower()
        if topic_lower in text or any(tok in text for tok in topic_lower.split() if len(tok) > 2):
            theories = _qa_paper_field(p, "theories")
            if theories and len(theories) > 5:
                results.append({
                    "paper": f"{p.get('first_author','?')} ({p.get('year','?')})",
                    "title": p.get("title", "?")[:120],
                    "theories": theories[:300],
                })
    # 按年份降序排列，返回全部结果
    results.sort(key=lambda r: r["paper"], reverse=True)
    return results  # 不再截断，返回全部


def _tool_find_gaps(topic: str) -> list[dict]:
    """从本地文献的未来研究方向中提取与某个主题相关的研究空白。遍历全库，不限制返回数量。"""
    global _qa_paper_index
    if not _qa_paper_index:
        _build_paper_index()

    results = []
    topic_lower = topic.lower()
    for p in _qa_paper_index:
        gaps = _qa_paper_field(p, "future_directions")
        if gaps and len(gaps) > 20:
            if topic_lower in gaps.lower() or any(tok in gaps.lower() for tok in topic_lower.split() if len(tok) > 2):
                results.append({
                    "paper": f"{p.get('first_author','?')} ({p.get('year','?')})",
                    "gaps": gaps[:300],
                })
    results.sort(key=lambda r: r["paper"], reverse=True)
    return results  # 不再截断，返回全部


def _tool_extract_methods(papers: list[str]) -> list[dict]:
    """提取指定论文的研究方法。"""
    global _qa_paper_index
    if not _qa_paper_index:
        _build_paper_index()

    results = []
    for query_title in papers[:5]:
        best = _tool_read_paper(query_title)
        if best:
            results.append({
                "paper": f"{best['first_author']} ({best['year']})",
                "title": best["title"][:120],
                "methods": best.get("methods", "未找到方法信息")[:300],
            })
    return results


async def _tool_search_external(question: str) -> Optional[str]:
    """调用 AI 的外部知识。"""
    msgs = [
        {"role": "system", "content": "你在市场营销×AI营销交叉领域有深厚的学术积累。基于你的知识回答问题。中文，专业术语保留英文。如果不知道就诚实说不知道。"},
        {"role": "user", "content": question},
    ]
    return await _chat_via_deepseek(msgs)


# ═══ Agent Core: Plan → Execute → Synthesize ═══

async def agent_plan(goal: str, chat_history: list[dict]) -> Optional[list[dict]]:
    """用 DeepSeek 将用户目标拆解为可执行的工具调用序列。"""
    tool_descriptions = _agent_get_tool_descriptions()
    system_prompt = AGENT_PLANNER_SYSTEM.format(tool_descriptions=tool_descriptions)

    # 包含最近对话上下文
    context = ""
    if chat_history:
        recent = chat_history[-6:]
        context = "\n最近对话：\n" + "\n".join(
            f"{'用户' if m['role']=='user' else '系统'}: {m['content'][:200]}"
            for m in recent
        )

    user_prompt = f"研究目标：{goal}{context}\n\n请输出执行计划（JSON数组）："

    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = await _chat_via_deepseek(msgs)
        if not raw:
            return None
        # 提取 JSON 数组
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not json_match:
            return None
        plan = json.loads(json_match.group())
        if not isinstance(plan, list):
            return None
        # 验证每个步骤的 tool 是否合法
        valid_plan = []
        for step in plan:
            if isinstance(step, dict) and step.get("tool") in AGENT_TOOLS:
                valid_plan.append(step)
        return valid_plan if valid_plan else None
    except Exception as e:
        logger.warning(f"[Agent] 规划失败: {e}")
        return None


def _execute_tool_sync(tool_name: str, args: dict) -> dict:
    """同步执行单个工具调用，返回结构化结果。"""
    tool_info = AGENT_TOOLS.get(tool_name)
    if not tool_info:
        return {"error": f"未知工具: {tool_name}"}

    try:
        func = globals().get(tool_info["function"])
        if not func:
            return {"error": f"工具未实现: {tool_info['function']}"}

        if tool_name == "search_external":
            # 异步工具需要特殊处理
            return {"error": "search_external 需异步调用，请使用 async 版本"}
        else:
            result = func(**args)
            return {"tool": tool_name, "args": args, "result": result, "ok": True}
    except Exception as e:
        return {"tool": tool_name, "args": args, "error": str(e), "ok": False}


async def agent_execute_plan(plan: list[dict], progress_callback=None) -> list[dict]:
    """执行规划好的工具调用序列。"""
    results = []
    for i, step in enumerate(plan):
        tool_name = step["tool"]
        args = step.get("args", {})
        reason = step.get("reason", "")

        if progress_callback:
            progress_callback(i, len(plan), tool_name, args, reason, "running")

        if tool_name == "search_external":
            # 异步执行
            try:
                answer = await _tool_search_external(args.get("question", ""))
                result = {"tool": tool_name, "args": args, "result": answer, "ok": True}
            except Exception as e:
                result = {"tool": tool_name, "args": args, "error": str(e), "ok": False}
        else:
            # 同步工具在 executor 中运行（避免阻塞）
            import concurrent.futures
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = await loop.run_in_executor(
                    pool, _execute_tool_sync, tool_name, args
                )

        if progress_callback:
            status = "done" if result.get("ok") else "error"
            progress_callback(i, len(plan), tool_name, args, reason, status)

        results.append(result)
    return results


async def agent_synthesize(goal: str, plan: list[dict], step_results: list[dict]) -> Optional[str]:
    """将所有步骤的结果综合为最终回答。"""
    # 构建步骤结果摘要
    summary_parts = []
    for i, (step, result) in enumerate(zip(plan, step_results)):
        tool = step["tool"]
        reason = step.get("reason", "")
        if result.get("ok") and result.get("result"):
            r = result["result"]
            if isinstance(r, list):
                summary_parts.append(f"步骤{i+1} [{tool}] ({reason}): 返回了 {len(r)} 条结果\n" +
                    "\n".join(f"  - {json.dumps(item, ensure_ascii=False)[:300]}" for item in r[:5]))
            elif isinstance(r, dict):
                summary_parts.append(f"步骤{i+1} [{tool}] ({reason}):\n  {json.dumps(r, ensure_ascii=False)[:800]}")
            elif isinstance(r, str):
                summary_parts.append(f"步骤{i+1} [{tool}] ({reason}):\n  {r[:800]}")
        elif result.get("error"):
            summary_parts.append(f"步骤{i+1} [{tool}] ({reason}): ❌ {result['error']}")
        else:
            summary_parts.append(f"步骤{i+1} [{tool}] ({reason}): 无结果")

    steps_summary = "\n\n".join(summary_parts)

    synth_prompt = f"""你是一位在市场营销×AI营销交叉领域有深厚学术积累的研究者。请根据以下分步骤检索到的信息，综合回答用户的研究目标。

研究目标：{goal}

执行步骤与结果：
{steps_summary}

请提供一份结构清晰、学术严谨的综合回答：
- 如果是文献综述类：按主题组织，指出共识与分歧，最后给出整体评述
- 如果是理论分析类：讲清概念、核心假设、实证证据、适用边界
- 如果是方法比较类：比较优劣和适用场景
- 如果步骤结果不足以全面回答，诚实说明并提供进一步建议
- 标注信息来源：本地文献用📄，外部知识用🌐
- 中文回答，专业术语保留英文"""

    msgs = [
        {"role": "system", "content": "你是一位学术研究者，综合检索结果给出严谨的回答。中文，专业术语保留英文。"},
        {"role": "user", "content": synth_prompt},
    ]
    return await _chat_via_deepseek(msgs)
