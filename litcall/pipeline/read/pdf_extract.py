"""PDF 文本/DOI 提取。

铁律 #4: 全文深度阅读，不截断。
从 literature_agent.py 单体中提取，独立可测。
"""

import logging
import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def _clean_doi(raw: str) -> str:
    """清洗 DOI 字符串：移除尾部非法标点、Unicode 替换符等。"""
    cleaned = raw.replace('�', '').replace('￾', '')
    cleaned = ''.join(c for c in cleaned if c.isprintable())
    while cleaned and cleaned[-1] in ',;:!?)]}\'"':
        cleaned = cleaned[:-1]
    cleaned = cleaned.rstrip('.')
    return cleaned


def extract_doi_from_pdf(pdf_path: Path) -> Optional[str]:
    """从 PDF 提取 DOI。先搜前 3 页，缺则搜全文 + 文件名。清洗尾部脏字符。

    三策略:
    1. 前 3 页正则搜索 (DOI 通常在首页)
    2. 全文正则搜索 (部分 PDF 的 DOI 在页脚或末尾)
    3. 文件名推断 (SPIS 下载的 PDF 有时 DOI 在文件名中)
    """
    try:
        doc = fitz.open(pdf_path)
        found = None
        # 策略 1: 前 3 页
        for i in range(min(3, len(doc))):
            text = doc[i].get_text()
            m = re.search(r"(10\.\d{4,}/[^\s]+)", text)
            if m:
                found = _clean_doi(m.group(1).strip())
                break
        # 策略 2: 全文
        if not found:
            for i in range(len(doc)):
                text = doc[i].get_text()
                m = re.search(r"(10\.\d{4,}/[^\s]+)", text)
                if m:
                    found = _clean_doi(m.group(1).strip())
                    break
        doc.close()
        # 策略 3: 文件名
        if not found:
            name_match = re.search(
                r"(10[._]\d{4,}[._/][^\s]+)", pdf_path.name
            )
            if name_match:
                found = _clean_doi(name_match.group(1).replace('_', '/'))
        if found:
            return found
    except Exception as e:
        logger.debug(f"DOI 提取异常 ({pdf_path.name}): {e}")
    return None


def extract_text_from_pdf(pdf_path: Path) -> str:
    """从 PDF 提取全文文本。使用 PyMuPDF (fitz)。

    铁律 #4: 全文提取，不截断。确保 PDF 句柄始终关闭。
    """
    doc = None
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        logger.error(f"提取 PDF 文本失败: {e}")
        return ""
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
