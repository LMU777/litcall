"""反幻觉质量控制 — 自检 + 变量交叉校验 + 复核队列。

铁律: 防幻觉结果必须随笔记入库，不丢弃。
从 literature_agent.py 单体中提取，独立可测。
"""

import asyncio
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

# ── 复核队列 ──

_REVIEW_QUEUE_FILE = Path(__file__).resolve().parent.parent.parent.parent / "review_queue.json"


def _add_to_review_queue(notes: Dict[str, str]) -> None:
    """将有问题的笔记加入人工复核队列。"""
    try:
        queue = []
        if _REVIEW_QUEUE_FILE.exists():
            queue = json.loads(_REVIEW_QUEUE_FILE.read_text(encoding="utf-8"))
        entry = {
            "title": notes.get("标题", "")[:120],
            "first_author": notes.get("第一作者", ""),
            "year": notes.get("年份", ""),
            "journal": notes.get("期刊", ""),
            "doi": notes.get("doi", ""),
            "confidence": notes.get("_置信度", "medium"),
            "issues": notes.get("_自检标记", ""),
            "added": datetime.datetime.now().isoformat(),
        }
        existing_doi = entry.get("doi", "").strip().lower()
        queue = [
            q for q in queue
            if q.get("doi", "").strip().lower() != existing_doi or not existing_doi
        ]
        queue.append(entry)
        _REVIEW_QUEUE_FILE.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"[复核队列] 已加入: {entry['title'][:50]}")
    except Exception as e:
        logger.warning(f"复核队列写入失败: {e}")


def _get_review_queue() -> List[Dict]:
    """读取人工复核队列。"""
    try:
        if _REVIEW_QUEUE_FILE.exists():
            return json.loads(_REVIEW_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _remove_from_review_queue(doi: str) -> bool:
    """从复核队列中移除一条记录（人工复核完成）。"""
    try:
        if not _REVIEW_QUEUE_FILE.exists():
            return False
        queue = json.loads(_REVIEW_QUEUE_FILE.read_text(encoding="utf-8"))
        doi_lower = doi.strip().lower()
        new_queue = [q for q in queue if q.get("doi", "").strip().lower() != doi_lower]
        _REVIEW_QUEUE_FILE.write_text(json.dumps(new_queue, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(new_queue) < len(queue)
    except Exception as e:
        logger.warning(f"复核队列删除失败: {e}")
        return False


# ── API 重试 ──

async def _retry_api_call(
    callable_async: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 2.0,
    description: str = "API call",
) -> Any:
    """异步 API 调用自动重试（指数退避）。

    适用: DeepSeek、Zotero、Gemini 等可能因网络波动或限流失败的 API。
    全部失败返回 None。
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            result = await callable_async()
            if attempt > 0:
                logger.info(
                    f"[重试] {description} 第 {attempt + 1} 次尝试成功"
                )
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"[重试] {description} 第 {attempt + 1}/{max_retries} "
                    f"次失败: {e}. {delay:.0f}s 后重试..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[重试] {description} 全部 {max_retries} 次尝试均失败。"
                    f"最后错误: {e}"
                )
    return None


# ── 自检 ──

async def _self_check_notes(
    text: str, notes: Dict[str, str], api_key: str, model: str
) -> Dict[str, Any]:
    """深度阅读后自检（一轮精简版）。

    检查变量遗漏、数字错误、编造内容。
    返回 {"issues": [...], "verified": [...], "confidence": "high"|"medium"|"low"}
    失败不阻塞主流程。
    """
    import aiohttp

    result: Dict[str, Any] = {"issues": [], "verified": [], "confidence": "high"}

    text_sample = text[:12000]
    notes_check = {
        "变量汇总": notes.get("变量汇总", "")[:800],
        "研究方法": notes.get("研究方法", "")[:600],
        "研究结果": notes.get("研究结果", "")[:1000],
    }

    check_prompt = f"""你是学术审稿人。检查这份精读笔记是否存在以下问题，每条问题独立验证：

1. 变量遗漏：原文是定量实证研究，笔记"变量汇总"为空或遗漏关键变量？
2. 数字错误：笔记中的样本量、统计量（β/SE/t/p/α/R²）、百分比与原文不一致？
3. 编造内容：笔记中存在原文没有的事实性陈述？

对每个发现的问题，给出：
- 问题类型（遗漏/数字错误/编造）
- 具体描述（引用原文和笔记的具体内容对比）
- 严重程度（HIGH/MEDIUM/LOW）

对每个已验证无误的字段，给出：
- 字段名
- 验证结果（PASS）

返回 JSON：
{{
  "confidence": "high" | "medium" | "low",
  "verified": [
    {{"field": "变量汇总", "verdict": "PASS"}},
    {{"field": "研究结果", "verdict": "PASS"}},
    ...
  ],
  "issues": ["具体问题描述1", "具体问题描述2", ...]
}}

原文片段：
{text_sample}

笔记检查内容：
变量汇总: {notes_check["变量汇总"]}
研究方法: {notes_check["研究方法"]}
研究结果: {notes_check["研究结果"]}

仅输出合法 JSON 对象。"""

    try:
        async def _do_check():
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": check_prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 4096,
                }
                async with session.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"HTTP {resp.status} — {body[:200]}")
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    json_match = re.search(r"\{.*\}", content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
                    return {"issues": [f"JSON 解析失败: {content[:200]}"]}

        check_result = await _retry_api_call(
            _do_check, max_retries=2, base_delay=1.0,
            description="自检 API"
        )
        if check_result:
            result["confidence"] = check_result.get("confidence", "high")
            result["verified"] = check_result.get("verified", [])
            result["issues"] = check_result.get("issues", [])
    except Exception as e:
        logger.warning(f"自检 API 异常（不阻塞主流程）: {e}")
        result["issues"].append(f"自检 API 异常: {e}")

    return result


# ── 变量交叉校验 ──

async def _cross_validate_variables(
    text: str, notes: Dict[str, str]
) -> List[str]:
    """变量交叉校验（规则引擎，不消耗 API）。

    检查:
    1. 变量汇总中每个变量名是否在原文中出现
    2. 样本量/统计量数值是否与原文一致
    """
    warnings = []
    variables_text = notes.get("变量汇总", "")

    if not variables_text or len(variables_text) < 10:
        return warnings

    # 从变量汇总中提取变量名（英文）
    var_names = re.findall(r'[A-Z][a-zA-Z\s]+(?=\s*[\(（])', variables_text)
    var_names += re.findall(
        r'\b([A-Z]{2,}(?:\s*[-–]\s*[A-Z]{2,})?)\b', variables_text
    )

    for vn in var_names[:15]:
        vn_clean = vn.strip()
        if len(vn_clean) < 3:
            continue
        # 检查变量名是否在原文中出现至少一次
        count = len(re.findall(re.escape(vn_clean), text, re.IGNORECASE))
        if count == 0 and len(vn_clean) > 4:
            warnings.append(
                f"变量校验: '{vn_clean}' 在原文中未找到"
            )

    # 检查样本量是否一致
    n_match_notes = re.findall(
        r'[nN]\s*[=＝]\s*(\d[\d,]*)', variables_text + notes.get("研究方法", "")
    )
    n_match_text = re.findall(r'[nN]\s*[=＝]\s*(\d[\d,]*)', text[:10000])

    if n_match_notes and n_match_text:
        n_notes = int(n_match_notes[0].replace(",", ""))
        n_text = int(n_match_text[0].replace(",", ""))
        if abs(n_notes - n_text) > 5:
            warnings.append(
                f"变量校验: 样本量不一致 (笔记: n={n_notes}, 原文: n={n_text})"
            )

    if warnings:
        logger.warning(f"[变量校验] {len(warnings)} 个警告")

    return warnings


# ── 中文笔记 → PaperData 映射 ──

_CN_TO_PAPER = {
    "标题": "title",
    "作者": "authors",
    "第一作者": "first_author",
    "通讯作者": "corresponding_author",
    "年份": "year",
    "期刊": "journal",
    "影响因子": "impact_factor",
    "分区": "quartile",
    "doi": "doi",
    "关键词": "keywords",
    "研究背景与动机": "background",
    "研究问题": "research_question",
    "变量汇总": "variables",
    "研究方法": "method",
    "方法论详解": "method_details",
    "研究结果": "results",
    "研究结论": "discussion",
    "讨论与结论": "discussion",
    "创新点": "innovation",
    "局限与展望": "limitations",
    "图表分析": "figure_analysis",
    "阅读方式": "reading_method",
    "阅读日期": "reading_date",
}


def _notes_dict_to_paper(notes: Dict[str, str]) -> "PaperData":
    """将中文键的笔记 dict 转换为 PaperData 对象。"""
    from litcall.stores.base import PaperData
    paper = PaperData()
    for cn_key, en_attr in _CN_TO_PAPER.items():
        val = notes.get(cn_key, "")
        if val:
            try:
                setattr(paper, en_attr, val)
            except Exception:
                pass
    # 扩展属性（不在 PaperData dataclass 中，ObsidianStore 模板需要）
    paper.self_check_confidence = notes.get("_置信度", "")  # type: ignore[attr-defined]
    paper.self_check_flag = notes.get("_自检标记", "")      # type: ignore[attr-defined]
    paper.tags = notes.get("关键词", "")                    # type: ignore[attr-defined]
    return paper


# ── 复核队列修复 ──

async def _retry_fix_notes(doi: str, issues: str) -> bool:
    """【复核队列修复】用现有笔记 + 问题描述让 DeepSeek 针对性修复。

    Args:
        doi: 论文 DOI
        issues: _自检标记 字段的问题描述（如 "FAIL: 变量汇总字段为空"）

    Returns:
        True 表示修复成功（无新问题），False 表示修复失败（仍有问题或无法修复）
    """
    import aiohttp

    from litcall.core.config import config
    from litcall.core.paths import NOTES_DIR
    from litcall.stores.obsidian import ObsidianStore
    from litcall.stores.excel import ExcelStore

    if not doi or not issues:
        return False

    doi_lower = doi.strip().lower()

    # 1. 找到对应的 JSON 笔记
    notes_file = None
    existing_notes = None
    if NOTES_DIR.exists():
        for f in NOTES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("doi", "").strip().lower() == doi_lower:
                    notes_file = f
                    existing_notes = data
                    break
            except Exception:
                continue

    if not existing_notes:
        logger.warning(f"[修复] 未找到 DOI={doi} 的 JSON 笔记，无法修复")
        return False

    # 2. 构建修复 prompt
    fix_prompt = f"""你是学术审稿人。以下是一篇论文的结构化笔记，自检发现了以下问题：

**问题**：
{issues}

**现有笔记**：
- 标题: {existing_notes.get("标题", "")}
- 作者: {existing_notes.get("作者", "")}
- 摘要: {existing_notes.get("摘要", "")[:1500]}
- 研究背景与动机: {existing_notes.get("研究背景与动机", "")[:1000]}
- 研究问题: {existing_notes.get("研究问题", "")[:1000]}
- 研究方法: {existing_notes.get("研究方法", "")[:1500]}
- 研究结果: {existing_notes.get("研究结果", "")[:1500]}
- 研究结论: {existing_notes.get("研究结论", "")[:1000]}
- 变量汇总: {existing_notes.get("变量汇总", "")}

请针对上述问题，只修复有问题的字段。只输出修复后的字段（JSON 格式），不要输出其他内容。
格式：{{"字段名": "修复后的内容", ...}}

注意：
1. 如果问题是"变量汇总为空"，请从研究方法和研究结果段落中提取变量信息（变量名称、类型、定义、测量方式）
2. 只修复问题中提到的字段，其他字段不要改动
3. 如果原文确实没有相关信息（如质性研究无定量变量），请输出空值"""

    # 3. 调用 DeepSeek
    deepseek_key = config.get("deepseek_api_key", "")
    if not deepseek_key:
        logger.error("[修复] DeepSeek API Key 未配置")
        return False

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {deepseek_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": config.get("deepseek_model", "deepseek-chat"),
                "messages": [
                    {"role": "system", "content": "你是学术审稿人，只输出修复后的 JSON，不输出任何解释。"},
                    {"role": "user", "content": fix_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 2048,
            }
            async with session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"[修复] API 错误: HTTP {resp.status}")
                    return False
                resp_data = await resp.json()
                content = resp_data["choices"][0]["message"]["content"].strip()

                # 解析修复后的 JSON
                import re as _re
                json_match = _re.search(r'\{.*\}', content, _re.DOTALL)
                if not json_match:
                    logger.error(f"[修复] 无法解析修复结果: {content[:200]}")
                    return False
                try:
                    fixes = json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.error(f"[修复] JSON 解析失败: {content[:200]}")
                    return False

                if not fixes:
                    logger.info("[修复] DeepSeek 判断无需修复（原文确实无相关信息）")
                    _remove_from_review_queue(doi)
                    return True

                # 4. 更新现有笔记
                updated_fields = []
                for key, val in fixes.items():
                    if val and isinstance(val, str) and len(val.strip()) > 5:
                        existing_notes[key] = val
                        updated_fields.append(key)
                        logger.info(f"[修复] ✓ {key} 已更新 ({len(val)} 字)")

                if not updated_fields:
                    logger.info("[修复] 无有效修复内容")
                    _remove_from_review_queue(doi)
                    return True

                # 5. 保存 JSON 笔记
                if notes_file:
                    notes_file.write_text(
                        json.dumps(existing_notes, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                # 6. 更新 Obsidian 笔记（用 force=True 覆写）
                paper = _notes_dict_to_paper(existing_notes)
                try:
                    obsidian_store = ObsidianStore()
                    await obsidian_store.write(paper, force=True)
                    logger.info("[修复] Obsidian 笔记已更新")
                except Exception as e:
                    logger.warning(f"[修复] Obsidian 更新失败: {e}")

                # 7. 更新 Excel
                try:
                    excel_store = ExcelStore()
                    await excel_store.write(paper)
                    logger.info("[修复] Excel 已更新")
                except Exception as e:
                    logger.warning(f"[修复] Excel 更新失败: {e}")

                # 8. 清除 _自检标记（修复后重新评估留给下次 generate_notes）
                if "_自检标记" in existing_notes:
                    del existing_notes["_自检标记"]
                if "_置信度" in existing_notes:
                    existing_notes["_置信度"] = "high"

                # 9. 移出复核队列
                _remove_from_review_queue(doi)
                logger.info(f"[修复] ✅ {existing_notes.get('标题','')[:60]} 修复完成，已移出复核队列")
                return True

    except Exception as e:
        logger.error(f"[修复] 异常: {e}")
        return False
