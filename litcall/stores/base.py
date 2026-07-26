"""AbstractStore — 四库统一接口 + 共享工具函数。

铁律 #7: DOI 是唯一可靠的跨库键。所有 DOI 入口必须经过 norm_doi() 规范化。
铁律 #10: Zotero 搜索 API 不索引 DOI，验证用直接 GET /items/{key}。
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ═══════════════════════════════════════════════════════════════
# DOI 规范化 — 铁律 #7
# ═══════════════════════════════════════════════════════════════

# 已知垃圾关键词白名单（见 Bug #5：不可以用宽泛正则误杀合法期刊缩写）
_DOI_GARBAGE_KEYWORDS = [
    "wiley", "logo", "society", "elsevier", "springer",
    "emerald", "taylor", "francis", "sage", "oxford",
    "cambridge", "routledge", "informa", "palgrave",
]


def norm_doi(doi: str) -> str:
    """规范化 DOI：去引号、去逗号、去垃圾后缀、统一小写。

    所有跨库操作的 DOI 入口必须经过此函数。
    """
    if not doi:
        return ""
    d = str(doi).strip().strip('"').strip("'").strip(",").lower()
    # 去垃圾关键词后缀 (仅当垃圾词出现在 DOI 中段之后)
    for g in _DOI_GARBAGE_KEYWORDS:
        idx = d.find(g)
        if idx > 20:  # 只截断 DOI 主段之后的垃圾
            d = d[:idx]
    # 去除尾部非 DOI 字符
    d = re.sub(r'[,;:\s]+$', '', d)
    return d.strip()


# ═══════════════════════════════════════════════════════════════
# 标题工具
# ═══════════════════════════════════════════════════════════════

def normalize_title(title: str) -> str:
    """标准化标题用于比对：去标点、去空格、统一小写。"""
    if not title:
        return ""
    t = str(title).lower().strip()
    t = re.sub(r'[^a-z0-9一-鿿\s]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def title_similarity(a: str, b: str) -> float:
    """标题相似度 (SequenceMatcher, 0.0-1.0)。"""
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def is_title_duplicate(a: str, b: str, threshold: float = 0.95) -> bool:
    """判断两标题是否为同一论文。

    铁律: 阈值 95%。学术论文标题几乎一模一样才叫重复。
    """
    return title_similarity(a, b) >= threshold


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class PaperData:
    """一篇论文的完整数据，用于跨库传递。

    18 字段结构化笔记 + 元数据。所有字段可选，各 Store 按需取用。
    """
    # 元数据
    doi: str = ""
    title: str = ""
    authors: str = ""
    first_author: str = ""
    corresponding_author: str = ""
    year: str = ""
    journal: str = ""
    impact_factor: str = ""
    quartile: str = ""
    keywords: str = ""

    # 18 字段笔记
    background: str = ""       # 研究背景与动机
    research_question: str = ""  # 研究问题
    variables: str = ""         # 变量汇总
    method: str = ""            # 研究方法
    method_details: str = ""    # 方法论详解
    results: str = ""           # 研究结果
    discussion: str = ""        # 讨论与结论
    innovation: str = ""        # 创新点
    limitations: str = ""       # 局限与展望
    figure_analysis: str = ""   # 图表分析

    # 处理元数据
    reading_method: str = ""
    reading_date: str = ""
    pdf_path: str = ""
    zotero_item_key: str = ""  # Zotero 条目 key（用于直接验证）

    # 生命周期状态
    status: str = "discovered"
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        """转为字典（排除 None 和空字符串）。"""
        return {k: v for k, v in self.__dict__.items() if v}

    @classmethod
    def from_dict(cls, data: Dict) -> "PaperData":
        """从字典创建。"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})

    @property
    def norm_doi(self) -> str:
        return norm_doi(self.doi)


@dataclass
class VerifyResult:
    """单库验证结果。"""
    store_name: str
    ok: bool
    detail: str = ""
    found_doi: str = ""
    found_title: str = ""


@dataclass
class TransactionResult:
    """四库原子事务结果。"""
    ok: bool
    doi: str = ""
    title: str = ""
    written_stores: List[str] = field(default_factory=list)
    failed_store: str = ""
    failed_reason: str = ""
    verified_stores: List[str] = field(default_factory=list)
    unverified_stores: List[str] = field(default_factory=list)

    @classmethod
    def success(cls, doi: str = "", title: str = "",
                written: List[str] = None, verified: List[str] = None) -> "TransactionResult":
        return cls(ok=True, doi=doi, title=title,
                   written_stores=written or [], verified_stores=verified or [])

    @classmethod
    def failed(cls, doi: str = "", title: str = "",
               store: str = "", reason: str = "",
               written: List[str] = None) -> "TransactionResult":
        return cls(ok=False, doi=doi, title=title,
                   failed_store=store, failed_reason=reason,
                   written_stores=written or [])

    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "doi": self.doi,
            "title": self.title,
            "written_stores": self.written_stores,
            "failed_store": self.failed_store,
            "failed_reason": self.failed_reason,
            "verified_stores": self.verified_stores,
            "unverified_stores": self.unverified_stores,
        }


# ═══════════════════════════════════════════════════════════════
# AbstractStore — 铁律 §6.4
# ═══════════════════════════════════════════════════════════════

class AbstractStore(ABC):
    """四库统一抽象接口。

    每个 Store 实现必须满足：
    - write: 创建/更新一条论文记录
    - verify: 确认记录真实存在于库中（不信任 write 返回值）
    - delete: 删除记录（用于回滚）
    - count: 本库论文总数
    - list_dois: 本库所有 DOI
    """

    name: str = "abstract"

    @abstractmethod
    async def write(self, paper: PaperData) -> bool:
        """写入/更新一条论文记录。返回 True 表示成功。"""
        ...

    @abstractmethod
    async def verify(self, doi: str) -> VerifyResult:
        """验证一条论文记录是否真实存在于库中。"""
        ...

    @abstractmethod
    async def delete(self, doi: str) -> bool:
        """删除一条论文记录（用于回滚）。"""
        ...

    @abstractmethod
    def count(self) -> int:
        """本库中的论文总数。"""
        ...

    @abstractmethod
    def list_dois(self) -> Set[str]:
        """本库中所有规范化 DOI 的集合。"""
        ...
