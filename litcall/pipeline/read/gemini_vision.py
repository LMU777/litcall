"""Gemini Vision — 分层识图（结构化输出）。

三层 Prompt 策略：
- 理论框架图 → Mermaid flowchart（可在 Obsidian 渲染）
- 数据表格 → Markdown table（保留全部数字）
- 统计结果图 → 结构化列表（路径 → β → SE → p）

从 literature_agent.py 提取，完全自包含，不依赖 literature_agent。
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict

from litcall.core.config import config

logger = logging.getLogger(__name__)


# ============================================================================
# 公共接口
# ============================================================================


async def recognize_figures_structured(pdf_path: Path, gemini_api_key: str) -> Dict[str, Any]:
    """用 Gemini Vision 对 PDF 进行分层识图，输出结构化数据。

    三层 Prompt 策略：
    - 理论框架图 → Mermaid flowchart（可在 Obsidian 渲染）
    - 数据表格 → Markdown table（保留全部数字）
    - 统计结果图 → 结构化列表（路径 → β → SE → p）

    返回 {"mermaid_diagrams": [...], "markdown_tables": [...], "statistical_results": [...], "descriptions": [...]}
    失败返回空 dict。
    """
    result = {
        "mermaid_diagrams": [],
        "markdown_tables": [],
        "statistical_results": [],
        "descriptions": [],
    }

    try:
        from google import genai
        import fitz as fitz_module
    except ImportError:
        logger.warning("Gemini Vision 需要: pip install google-genai PyMuPDF")
        return result

    if not gemini_api_key:
        logger.warning("Gemini API Key 未配置，跳过识图")
        return result

    doc = None
    try:
        client = genai.Client(api_key=gemini_api_key)
        doc = fitz_module.open(pdf_path)
    except Exception as e:
        logger.warning(f"Gemini 初始化失败: {e}")
        return result

    try:
        # ── 智能预扫描：文本检测 Figure/Table 标题 ──
        # 遍历全部页面，不设上限——用户需要每篇论文的所有图表都被识别
        # 图表标题正则（中英文）
        FIGURE_CAPTION_RE = re.compile(
            r'(?:Figure|Fig\.?|Table|FIGURE|FIG\.?|TABLE)\s*[A-Z]?\d+'  # Fig. 1, Figure S1, Table A2
            r'|图\s*\d+|表\s*\d+'                                          # 中文图表
            r'|(?:Figure|Fig\.?|Table)\s*[IVX]+',                          # 罗马数字 Table IV
            re.IGNORECASE,
        )

        candidate_pages = []
        for page_num in range(len(doc)):
            try:
                text = doc[page_num].get_text()
                if FIGURE_CAPTION_RE.search(text):
                    candidate_pages.append(page_num)
            except Exception:
                continue

        # 退而：如果没检测到标题但 PDF 有图片，扫图片最多的页（最多10页）
        if not candidate_pages:
            MAX_FALLBACK = 10
            image_counts = []
            for page_num in range(len(doc)):
                try:
                    imgs = doc[page_num].get_images(full=True)
                    if imgs:
                        image_counts.append((page_num, len(imgs)))
                except Exception:
                    continue
            image_counts.sort(key=lambda x: -x[1])
            candidate_pages = [p for p, _ in image_counts[:MAX_FALLBACK]]

        # 再退：扫第 1-6 页（论文核心图表通常在这里）
        if not candidate_pages:
            candidate_pages = [p for p in range(0, min(6, len(doc)))]

        logger.info(f"  Gemini 图表检测: {len(candidate_pages)}页有图表 → {[p+1 for p in candidate_pages]}")

        # 精简 Prompt（减少 token 加快响应）
        system_prompt = """Extract figures/tables from this academic paper page.
TYPE: framework_diagram | statistical_table | descriptive_table | data_chart | other
CAPTION: [caption]
CONTENT:
[framework: Mermaid flowchart with --> for path, -.-> for moderation, ==> for mediation]
[statistical table: PATH: IV→DV, β=x, SE=x, p=x]
[descriptive table: Markdown table]
[chart: Chinese description]
If none: reply NONE."""

        pages_processed = 0
        consecutive_timeouts = 0
        MAX_TIMEOUTS = 2  # 连续超时即放弃本论文的 Gemini 识别（网络不通）

        for page_num in candidate_pages:
            # ── 信号检查：每页处理前允许暂停/终止 ──
            await asyncio.sleep(0)  # yield event loop

            # 连续超时 → Gemini API 不可达，跳过剩余页面
            if consecutive_timeouts >= MAX_TIMEOUTS:
                logger.warning(f"  Gemini 连续 {MAX_TIMEOUTS} 次超时，跳过本论文图表识别（网络可能不通）")
                break

            logger.info(f"  Gemini 第{page_num+1}页...")
            try:
                page = doc[page_num]
                pix = page.get_pixmap(dpi=200)  # 200 DPI 确保图表小字清晰可读
                img_data = pix.tobytes("png")

                # Gemini API 同步调用 → 用 asyncio.to_thread 避免阻塞事件循环
                # 设 30s 超时（国内网络到 Google API 通常较慢但不应超过 30s）
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=config.get("gemini_model", "gemini-2.5-flash"),
                        contents=[{
                            "parts": [
                                {"text": system_prompt},
                                {"inline_data": {"mime_type": "image/png", "data": img_data}},
                            ]
                        }],
                    ),
                    timeout=30,
                )

                text = resp.text.strip() if resp.text else ""
                consecutive_timeouts = 0  # 重置连续超时计数

                if not text or "NONE" in text.upper()[:10]:
                    logger.info(f"  第{page_num+1}页: 无图表")
                    continue

                pages_processed += 1
                _parse_gemini_structured_output(text, page_num + 1, result)
                logger.info(f"  第{page_num+1}页: ✓ 有图表")

                if page_num != candidate_pages[-1]:
                    await asyncio.sleep(1)

            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                logger.warning(f"Gemini 第{page_num+1}页超时 ({consecutive_timeouts}/{MAX_TIMEOUTS}) — API 无响应，可能网络不通")
            except Exception as e:
                consecutive_timeouts = 0  # 非超时错误，重置
                import traceback as _tb
                _err_detail = _tb.format_exc()[-300:]
                logger.warning(f"Gemini 第{page_num+1}页异常: {type(e).__name__}: {e}")
                logger.debug(f"Gemini 详细: {_err_detail}")
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    await asyncio.sleep(15)
                continue

        logger.info(f"  ✓ Gemini 完成: {pages_processed}页有图表, {sum(len(v) for v in result.values())} 个图表/表格")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

    return result


# ============================================================================
# 内部辅助函数
# ============================================================================


def _parse_gemini_structured_output(text: str, page_num: int, result: Dict[str, Any]) -> None:
    """解析 Gemini 返回的结构化文本，按类型归类到 result dict 中。"""
    # 按 ## TYPE: 分割段落
    sections = re.split(r'##\s*TYPE:', text)
    for section in sections:
        if not section.strip():
            continue

        section = section.strip()
        type_match = re.match(r'\s*(framework_diagram|statistical_table|descriptive_table|data_chart|other)', section)
        fig_type = type_match.group(1) if type_match else "other"
        content = section[type_match.end():].strip() if type_match else section

        # 提取 CAPTION
        caption_match = re.search(r'##\s*CAPTION:\s*(.+?)(?:\n|$)', content)
        caption = caption_match.group(1).strip()[:200] if caption_match else ""

        # 提取 CONTENT
        content_match = re.search(r'##\s*CONTENT:\s*\n?(.*)', content, re.DOTALL)
        body = content_match.group(1).strip()[:3000] if content_match else content[:2000]

        entry = {
            "page": page_num,
            "caption": caption,
            "body": body,
        }

        # 按类型归类
        if fig_type == "framework_diagram":
            # 提取 mermaid 代码块（如果有）
            mermaid_match = re.search(r'```mermaid\s*\n(.*?)```', body, re.DOTALL)
            if mermaid_match:
                entry["mermaid_code"] = mermaid_match.group(1).strip()
            result["mermaid_diagrams"].append(entry)
        elif fig_type == "statistical_table":
            # 解析路径系数行
            paths = re.findall(r'PATH:\s*(.+?)(?:\n|$)', body)
            if paths:
                entry["paths"] = [p.strip() for p in paths]
            result["statistical_results"].append(entry)
        elif fig_type == "descriptive_table":
            # 检查是否有 Markdown 表格
            if "|" in body:
                entry["has_markdown_table"] = True
            result["markdown_tables"].append(entry)
        elif fig_type == "data_chart":
            result["descriptions"].append(entry)
        else:
            result["descriptions"].append(entry)
