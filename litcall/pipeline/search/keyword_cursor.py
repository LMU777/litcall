"""关键词游标模块 — 渐进式关键词检索游标管理。

游标状态持久化在 config.json 的 _keyword_cursor 字段中，
支持宽/窄/中三类关键词的依次遍历，每次检索推进游标，
确保重启后不会重复已检索过的关键词。

同时包含 async_request / safe_http_request 工具函数，
供 Zotero API 调用时使用。

从 literature_agent.py 提取，供检索管线各阶段复用。
"""

import asyncio
import json
import logging
from typing import Tuple, Optional

import requests

from litcall.core.config import config, load_config, save_config
from litcall.core.paths import CONFIG_PATH

logger = logging.getLogger(__name__)


# ============================================================================
# 关键词游标
# ============================================================================

def _get_category_index(scope: str, flat_index: int) -> tuple:
    """将 scope 标签 + 扁平索引转换为 (category_index, keyword_index_within_category)。"""
    if scope == "宽":
        return (0, flat_index)
    elif scope == "窄":
        return (1, flat_index - len(config.get("keywords", {}).get("broad", [])))
    elif scope == "中":
        broad_len = len(config.get("keywords", {}).get("broad", []))
        narrow_len = len(config.get("keywords", {}).get("narrow", []))
        return (2, flat_index - broad_len - narrow_len)
    return (0, flat_index)


def _read_keyword_cursor() -> dict:
    """从 config.json 读取关键词游标。"""
    return config.get("_keyword_cursor", {"category_index": 0, "keyword_index": 0})


def _write_keyword_cursor(category_index: int, keyword_index: int):
    """原子写入关键词游标到 config.json（通过 save_config 保证原子性）。"""
    from datetime import datetime
    cfg = load_config()
    cfg["_keyword_cursor"] = {
        "category_index": category_index,
        "keyword_index": keyword_index,
        "last_updated": datetime.now().isoformat(),
    }
    try:
        save_config(cfg)
    except Exception as e:
        logger.error(f"写入关键词游标失败（游标位置将丢失，下次运行可能重复检索）: {e}")


def _get_next_keyword(cursor: dict) -> tuple:
    """从游标位置获取下一个关键词。

    Returns:
        (keyword_str, scope_tag, category_index, keyword_index)
        全部穷尽时返回 (None, None, -1, -1)
    """
    categories = [
        ("宽", config.get("keywords", {}).get("broad", [])),
        ("窄", config.get("keywords", {}).get("narrow", [])),
        ("中", config.get("keywords", {}).get("chinese", [])),
    ]

    ci = cursor.get("category_index", 0)
    ki = cursor.get("keyword_index", 0)

    while ci < len(categories):
        scope, kw_list = categories[ci]
        if ki < len(kw_list):
            return (kw_list[ki], scope, ci, ki)
        ci += 1
        ki = 0

    return (None, None, -1, -1)


def _advance_keyword_cursor(cursor: dict):
    """推进游标到下一个关键词（写回 config.json）。"""
    ci = cursor.get("category_index", 0)
    ki = cursor.get("keyword_index", 0)

    categories = [
        config.get("keywords", {}).get("broad", []),
        config.get("keywords", {}).get("narrow", []),
        config.get("keywords", {}).get("chinese", []),
    ]

    ki += 1
    while ci < len(categories) and ki >= len(categories[ci]):
        ci += 1
        ki = 0

    _write_keyword_cursor(ci, ki)
    return {"category_index": ci, "keyword_index": ki}


# ============================================================================
# Step 1: 打印关键词
# ============================================================================

def print_keywords():
    """打印全部关键词矩阵，返回扁平列表 [(keyword, scope), ...]"""
    keywords = config.get("keywords", {})
    broad = keywords.get("broad", [])
    narrow = keywords.get("narrow", [])
    chinese = keywords.get("chinese", [])
    all_kw = [(kw, "宽") for kw in broad] + [(kw, "窄") for kw in narrow] + [(kw, "中") for kw in chinese]
    print("\n===== 关键词矩阵 =====")
    for idx, (kw, scope) in enumerate(all_kw, 1):
        print(f"[{idx}] ({scope}) {kw}")
    print("========================\n")
    return all_kw


# ============================================================================
# HTTP 请求工具（Zotero API / 通用）
# ============================================================================

def safe_http_request(method: str, url: str, **kwargs) -> requests.Response:
    """安全的 HTTP 请求封装，处理 SSL 错误、连接超时等常见异常。"""
    kwargs.setdefault("timeout", 30)
    try:
        return requests.request(method, url, **kwargs)
    except requests.exceptions.SSLError:
        kwargs["verify"] = False
        return requests.request(method, url, **kwargs)
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"无法连接到 {url}: {e}") from e
    except requests.exceptions.Timeout as e:
        raise TimeoutError(f"请求超时 {url}: {e}") from e


async def async_request(method: str, url: str, **kwargs) -> requests.Response:
    """异步包装 safe_http_request，在线程池中执行。"""
    return await asyncio.to_thread(safe_http_request, method, url, **kwargs)
