"""ObsidianStore — Markdown 笔记读写。

铁律 #3: Obsidian 是日常使用最多的入口。
铁律 #2: 四库全部成功才标记已处理。

笔记模板: 18 字段结构化笔记 + YAML frontmatter。
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set

from litcall.core.paths import OBSIDIAN_DIR
from litcall.stores.base import AbstractStore, PaperData, VerifyResult, norm_doi

logger = logging.getLogger(__name__)

# ── Obsidian 笔记模板 ──

OBSIDIAN_TEMPLATE = """---
title: "{title}"
author: "{authors}"
first_author: "{first_author}"
corresponding_author: "{corresponding_author}"
year: "{year}"
journal: "{journal}"
impact_factor: "{impact_factor}"
quartile: "{quartile}"
doi: "{doi}"
keywords: "{keywords}"
{tags_yaml}reading_method: "{reading_method}"
reading_date: "{reading_date}"
status: "{status}"
---

# {title}

**作者**: {authors}
**期刊**: {journal} ({year}) | IF: {impact_factor} | {quartile}
**DOI**: [{doi}](https://doi.org/{doi})

---

## 研究背景与动机

{background}

---

## 研究问题

{research_question}

---

## 变量汇总

{variables}

---

## 研究方法

{method}

---

## 方法论详解

{method_details}

---

## 研究结果

{results}

---

## 讨论与结论

{discussion}

---

## 创新点

{innovation}

---

## 局限与展望

{limitations}

---

## 图表分析

{figure_analysis}

---

## 质量控制

- **置信度**: {self_check_confidence}
- **自检标记**: {self_check_flag}

---

## 知识图谱链接

- [[_index]]
"""

# 铁律: tags 使用空格分词，小写（非缩写词），不使用连字符
#       只有 AI 技术词用大写缩写: AI, GenAI, ML, LLM, NLP


def _clean_filename(text: str, max_len: int = 80) -> str:
    """清理文件名中的非法字符。不截断期刊名（铁律: 不截断）。"""
    if not text:
        return "untitled"
    illegal = r'[<>:"/\\|?*\n\r\t]'
    cleaned = re.sub(illegal, "_", text)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._ ")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("._ ")
    return cleaned or "untitled"


class ObsidianStore(AbstractStore):
    """Obsidian Vault Markdown 笔记存储后端。"""

    name = "obsidian"

    def __init__(self, vault_dir: Optional[Path] = None):
        self._vault_dir = vault_dir or OBSIDIAN_DIR
        self._vault_dir.mkdir(parents=True, exist_ok=True)

    # ── 路径计算 ──

    def _paper_dir(self, paper: PaperData) -> Path:
        """论文所属目录: {year}/{journal}/"""
        year = paper.year or "unknown"
        journal = _clean_filename(paper.journal, max_len=80) if paper.journal else "unknown"
        return self._vault_dir / str(year) / journal

    def _paper_path(self, paper: PaperData) -> Path:
        """论文笔记路径。"""
        title_clean = _clean_filename(paper.title, max_len=120)
        return self._paper_dir(paper) / f"{paper.year}_{title_clean}.md"

    # ── Frontmatter 解析 ──

    @staticmethod
    def parse_frontmatter(md_text: str) -> Dict[str, str]:
        """从 Markdown 文本解析 YAML frontmatter。"""
        result = {}
        m = re.match(r'^---\s*\n(.*?)\n---', md_text, re.DOTALL)
        if not m:
            return result
        for line in m.group(1).split("\n"):
            kv = re.match(r'^(\w+):\s*(.*)', line)
            if kv:
                k = kv.group(1).lower()
                v = kv.group(2).strip().strip('"').strip("'")
                result[k] = v
        return result

    @staticmethod
    def extract_doi_from_note(md_text: str) -> str:
        """从 Markdown 笔记提取规范化 DOI。"""
        fm = ObsidianStore.parse_frontmatter(md_text)
        return norm_doi(fm.get("doi", ""))

    @staticmethod
    def _build_tags_yaml(tags: str) -> str:
        """将 paper.tags 转为 YAML 标签块。

        paper.tags 支持两种格式:
          - 换行分隔: "AI\\nconsumer behavior\\nbrand trust"
          - 逗号分隔: "AI, consumer behavior, brand trust"

        Returns:
            "tags:\\n  - AI\\n  - consumer behavior\\n" 或空字符串
        """
        if not tags or not tags.strip():
            return ""
        tag_list = [t.strip() for t in tags.replace(",", "\n").split("\n")]
        tag_list = [t for t in tag_list if t]
        if not tag_list:
            return ""
        return "tags:\n" + "\n".join(f"  - {t}" for t in tag_list) + "\n"

    # ── AbstractStore 接口 ──

    async def write(self, paper: PaperData, force: bool = True) -> bool:
        """写入 Obsidian 笔记。

        Args:
            paper: 论文数据。
            force: True 时覆写已有笔记（Agent 模式默认覆写）。
        """
        try:
            paper_dir = self._paper_dir(paper)
            paper_dir.mkdir(parents=True, exist_ok=True)

            filepath = self._paper_path(paper)

            if filepath.exists() and not force:
                logger.info(f"Obsidian 笔记已存在，跳过: {filepath.name}")
                return True

            # 生成 tags YAML 块
            tags_yaml = self._build_tags_yaml(paper.tags)

            content = OBSIDIAN_TEMPLATE.format(
                title=paper.title or "",
                authors=paper.authors or "",
                first_author=paper.first_author or "",
                corresponding_author=paper.corresponding_author or "",
                year=paper.year or "",
                journal=paper.journal or "",
                impact_factor=paper.impact_factor or "",
                quartile=paper.quartile or "",
                doi=paper.doi or "",
                keywords=paper.keywords or "",
                tags_yaml=tags_yaml,
                reading_method=paper.reading_method or "",
                reading_date=paper.reading_date or datetime.now().strftime("%Y-%m-%d"),
                status=paper.status or "done",
                background=paper.background or "",
                research_question=paper.research_question or "",
                variables=paper.variables or "",
                method=paper.method or "",
                method_details=paper.method_details or "",
                results=paper.results or "",
                discussion=paper.discussion or "",
                innovation=paper.innovation or "",
                limitations=paper.limitations or "",
                figure_analysis=paper.figure_analysis or "",
                self_check_confidence=paper.self_check_confidence or "",
                self_check_flag=paper.self_check_flag or "",
            )

            filepath.write_text(content, encoding="utf-8")
            logger.info(f"Obsidian 笔记已写入: {filepath.relative_to(self._vault_dir)}")
            return True
        except Exception as e:
            logger.error(f"ObsidianStore.write 失败: {e}")
            return False

    async def verify(self, doi: str) -> VerifyResult:
        """在 Obsidian vault 中搜索 DOI。"""
        try:
            ndoi = norm_doi(doi)
            for md in self._vault_dir.glob("**/*.md"):
                try:
                    text = md.read_text(encoding="utf-8")
                    if ObsidianStore.extract_doi_from_note(text) == ndoi:
                        fm = self.parse_frontmatter(text)
                        return VerifyResult(
                            store_name=self.name, ok=True,
                            found_doi=ndoi,
                            found_title=fm.get("title", ""),
                        )
                except Exception:
                    continue
            return VerifyResult(
                store_name=self.name, ok=False,
                detail=f"DOI {ndoi} 不在 Obsidian 中",
            )
        except Exception as e:
            return VerifyResult(
                store_name=self.name, ok=False,
                detail=f"验证异常: {e}",
            )

    async def delete(self, doi: str) -> bool:
        """删除 Obsidian 笔记（用于回滚）。"""
        try:
            ndoi = norm_doi(doi)
            for md in self._vault_dir.glob("**/*.md"):
                try:
                    if ObsidianStore.extract_doi_from_note(md.read_text(encoding="utf-8")) == ndoi:
                        md.unlink()
                        logger.info(f"ObsidianStore: 删除笔记 {md.name}")
                        return True
                except Exception:
                    continue
            return False  # 没找到要删除的
        except Exception as e:
            logger.error(f"ObsidianStore.delete 失败: {e}")
            return False

    def count(self) -> int:
        return len(self.list_dois())

    def list_dois(self) -> Set[str]:
        dois = set()
        for md in self._vault_dir.glob("**/*.md"):
            try:
                d = ObsidianStore.extract_doi_from_note(md.read_text(encoding="utf-8"))
                if d:
                    dois.add(d)
            except Exception:
                continue
        return dois

    # ── 扩展方法 ──

    def find_note_by_doi(self, doi: str) -> Optional[Path]:
        """按 DOI 查找笔记文件路径。"""
        ndoi = norm_doi(doi)
        for md in self._vault_dir.glob("**/*.md"):
            try:
                if ObsidianStore.extract_doi_from_note(md.read_text(encoding="utf-8")) == ndoi:
                    return md
            except Exception:
                continue
        return None
