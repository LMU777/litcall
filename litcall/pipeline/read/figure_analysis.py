"""图表深度分析 — Gemini 结构化输出 → 格式化 → DeepSeek 结合文献深度分析。

从 literature_agent.py 提取，完全自包含，不依赖 literature_agent。
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from litcall.core.config import config

logger = logging.getLogger(__name__)


# ============================================================================
# 公共接口
# ============================================================================


def format_figure_data(figure_data: Dict[str, Any]) -> str:
    """将 Gemini 结构化图表数据格式化为文本，供 DeepSeek 分析。"""
    lines = []

    if figure_data.get("mermaid_diagrams"):
        lines.append(f"## 理论框架图 ({len(figure_data['mermaid_diagrams'])} 个)")
        for i, d in enumerate(figure_data["mermaid_diagrams"], 1):
            lines.append(f"\n### 框架图 {i}: {d.get('caption', '')}")
            if d.get("mermaid_code"):
                lines.append(f"```mermaid\n{d['mermaid_code']}\n```")
            else:
                lines.append(d.get("body", ""))

    if figure_data.get("statistical_results"):
        lines.append(f"\n## 统计结果表 ({len(figure_data['statistical_results'])} 个)")
        for i, d in enumerate(figure_data["statistical_results"], 1):
            lines.append(f"\n### 统计表 {i}: {d.get('caption', '')}")
            if d.get("paths"):
                for p in d["paths"]:
                    lines.append(f"- {p}")
            else:
                lines.append(d.get("body", ""))

    if figure_data.get("markdown_tables"):
        lines.append(f"\n## 描述性统计表 ({len(figure_data['markdown_tables'])} 个)")
        for i, d in enumerate(figure_data["markdown_tables"], 1):
            lines.append(f"\n### 表格 {i}: {d.get('caption', '')}")
            lines.append(d.get("body", ""))

    if figure_data.get("descriptions"):
        lines.append(f"\n## 数据图表描述 ({len(figure_data['descriptions'])} 个)")
        for i, d in enumerate(figure_data["descriptions"], 1):
            lines.append(f"\n### 图表 {i}: {d.get('caption', '')}")
            lines.append(d.get("body", ""))

    return "\n".join(lines)


async def analyze_figures_with_deepseek(
    paper_excerpt: str,
    figure_summary: str,
    notes: Dict[str, str],
) -> Optional[str]:
    """用 DeepSeek 对 Gemini 提取的图表做结合文献的深度分析。"""
    if not figure_summary or len(figure_summary) < 50:
        return None

    deepseek_key = config.get("deepseek_api_key", "")
    deepseek_model = config.get("deepseek_model", "deepseek-v4-pro")
    if not deepseek_key:
        return None

    title = notes.get("标题", "未知论文")
    research_q = notes.get("研究问题", notes.get("research_questions", ""))
    findings = notes.get("主要发现", notes.get("key_findings", ""))

    prompt = f"""你是一位市场营销×AI营销领域的资深研究者。请对以下论文的图表进行深度分析。

## 论文信息
- 标题: {title}
- 研究问题: {research_q[:300]}
- 主要发现: {findings[:300]}

## 论文文本摘要（前3000字）
{paper_excerpt[:3000]}

## Gemini Vision 提取的图表数据
{figure_summary[:4000]}

请做以下分析（中文，专业术语保留英文）：
1. **理论框架解读**：如果有理论模型图，解读各变量之间的关系，分析其理论逻辑
2. **关键数据发现**：从统计结果表中提取最重要的路径系数、效应量、显著性水平
3. **数据一致性检查**：图表中的数据是否与正文中的发现一致？如有矛盾请指出
4. **图表质量评价**：图表的呈现是否清晰、完整？是否有缺失的信息？
5. **研究启示**：这些图表揭示了什么重要洞见？对后续研究有何启发？

控制在 800 字以内，结构清晰。"""

    try:
        async def _do_fig_analysis():
            from openai import OpenAI
            client = OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com/v1",
                timeout=90.0,  # H2 fix: 防止永久挂起
            )
            resp = client.chat.completions.create(
                model=deepseek_model,
                messages=[
                    {"role": "system", "content": "你是一位学术研究者，擅长分析论文中的图表和数据。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
            return resp.choices[0].message.content

        result = await _retry_api_call(_do_fig_analysis, max_retries=2, base_delay=2.0,
                                       description="DeepSeek 图表分析")
        return result
    except Exception as e:
        logger.warning(f"图表分析 DeepSeek 调用失败（已重试）: {e}")
        return None


# ============================================================================
# 内部辅助函数
# ============================================================================


async def _retry_api_call(callable_async, max_retries: int = 3, base_delay: float = 2.0,
                          description: str = "API call") -> Any:
    """异步 API 调用自动重试（指数退避）。

    适用场景：DeepSeek、Zotero、Gemini 等可能因网络波动或服务端限流失败的 API。
    重试策略：base_delay * (2 ** attempt)，最多 max_retries 次。
    所有重试均失败后返回 None（不抛异常，由调用方决定如何处理）。

    Args:
        callable_async: 无参异步可调用对象（如 lambda: session.post(...)）
        max_retries: 最多重试次数（含首次，默认3次）
        base_delay: 基础退避秒数（默认2秒，总延迟 ≈ 2 + 4 = 6秒）
        description: 描述文字，用于日志
    Returns:
        成功返回 callable 的返回值，全部失败返回 None
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            result = await callable_async()
            if attempt > 0:
                logger.info(f"[重试] {description} 第 {attempt + 1} 次尝试成功")
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"[重试] {description} 第 {attempt + 1}/{max_retries} 次失败: {e}。"
                    f"{delay:.0f}s 后重试..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[重试] {description} 全部 {max_retries} 次尝试均失败。"
                    f"最后错误: {e}"
                )
    return None
