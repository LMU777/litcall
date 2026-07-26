"""LitCall 每日检索简报生成。

从自主检索结果生成 Obsidian 兼容的 Markdown 简报文件。
"""

import logging
from pathlib import Path

from litcall.core.paths import OBSIDIAN_DIR

logger = logging.getLogger(__name__)

DAILY_DIR = OBSIDIAN_DIR / "Daily"
DAILY_DIR.mkdir(parents=True, exist_ok=True)


def generate_daily_briefing(result: dict, session_start: str = "") -> str:
    """生成自主检索每日简报，保存为 Obsidian 兼容的 .md 文件。

    Args:
        result: _scrape_new_articles_autonomous 的返回值
        session_start: 检索开始时间（ISO格式字符串）

    Returns:
        简报文件路径
    """
    from datetime import datetime

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    collected = result.get("collected", [])
    by_keyword = result.get("by_keyword", {})
    with_links = result.get("with_links", [])
    without_links = result.get("without_links", [])
    help_submitted = result.get("help_submitted", 0)

    # ── 构建简报内容 ──
    lines = [
        "---",
        f"date: {date_str}",
        f"time: {time_str}",
        f"weekday: {weekday}",
        f"type: 文献检索简报",
        f"total_collected: {len(collected)}",
        f"with_download_links: {len(with_links)}",
        f"literature_help_submitted: {help_submitted}",
        "keywords_used:",
    ]
    for kw in by_keyword:
        lines.append(f'  - "{kw}"')

    lines.extend([
        "---",
        "",
        f"# 📖 LitCall 自主检索简报 — {date_str} {weekday} {time_str}",
        "",
        "## 📊 概览",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 检索关键词 | {len(by_keyword)} 个 (4 broad + 10 narrow) |",
        f"| 收集新文献 | **{len(collected)}** 篇 |",
        f"| 有下载链接 🔗 | {len(with_links)} 篇 → 待手动下载 |",
        f"| 已提交文献求助 📭 | {help_submitted} 篇 → 等待邮件送达 |",
        "| 年份筛选 | 2025-2026 |",
        "",
    ])

    # ── 按关键词分组 ──
    if by_keyword:
        lines.append("## 📋 按关键词分布")
        lines.append("")
        total_from_kw = 0
        for kw, papers in by_keyword.items():
            count = len(papers)
            total_from_kw += count
            has_link = sum(1 for p in papers if p.get("download_url"))
            no_link = count - has_link
            lines.append(f"### {kw}")
            lines.append(f"- 共 {count} 篇（🔗有下载: {has_link} | 📭已求助: {no_link}）")
            lines.append("")
            for j, art in enumerate(papers, 1):
                link_icon = "🔗" if art.get("download_url") else "📭"
                title = art.get("title", "?")[:120]
                journal = art.get("journal", "?")
                year = art.get("year", "?")
                doi = art.get("doi", "")
                doi_link = f" [DOI](https://doi.org/{doi})" if doi else ""
                lines.append(f"{j}. {link_icon} **{title}**")
                lines.append(f"   - *{journal}* ({year}){doi_link}")
            lines.append("")

    # ── 待手动下载 (有链接) ──
    if with_links:
        lines.append("## 🔗 待手动下载")
        lines.append("")
        lines.append("以下论文在 SPIS 上有下载链接，请在浏览器中手动下载 PDF：")
        lines.append("")
        lines.append("> **操作提示**：下一次检索会自动复用浏览器登录态（cookies 已保存），")
        lines.append("> 打开 SPIS 后逐个搜索论文标题即可找到下载入口。")
        lines.append("")
        for j, art in enumerate(with_links, 1):
            title = art.get("title", "?")[:150]
            journal = art.get("journal", "?")
            year = art.get("year", "?")
            dl = art.get("download_url", "")[:80]
            lines.append(f"{j}. **{title}**")
            lines.append(f"   - *{journal}* ({year})")
            if dl:
                lines.append(f"   - 下载页: [{dl[:60]}...]({dl})")
            lines.append("")
        # 汇总到 pending_manual.json 的提示
        lines.append(f"> 📁 以上 {len(with_links)} 篇已保存至 `待处理文献/pending_manual.json`")
        lines.append("")

    # ── 已提交文献求助 (无链接) ──
    if without_links:
        lines.append("## 📭 已自动提交文献求助")
        lines.append("")
        lines.append("以下论文在 SPIS 上无下载链接，已自动通过「文献求助」提交至 **18922596828@163.com**：")
        lines.append("")
        lines.append("> ⏳ 文献求助通常需要 1-3 个工作日处理，请留意邮箱。")
        lines.append("")
        for j, art in enumerate(without_links, 1):
            title = art.get("title", "?")[:150]
            journal = art.get("journal", "?")
            year = art.get("year", "?")
            status = "✅ 已提交" if art.get("help_submitted") else "⚠ 提交失败"
            lines.append(f"{j}. {status} — **{title}**")
            lines.append(f"   - *{journal}* ({year})")
            lines.append("")

    # ── 下一步操作 ──
    lines.extend([
        "## 📌 下一步操作",
        "",
        "### 对于有下载链接的论文：",
        f"1. 打开 SPIS (https://spis.hnlat.com)，搜索论文标题",
        "2. 进入详情页，点击下载按钮下载 PDF",
        f"3. 将下载的 PDF 放入 `待处理文献/` 文件夹",
        f"4. 在 LitCall 中选择「深度阅读」进行自动处理",
        "",
        "### 对于已提交文献求助的论文：",
        "1. 等待 1-3 个工作日，检查 18922596828@163.com 邮箱",
        "2. 收到 PDF 后放入 `待处理文献/` 文件夹",
        "3. 在 LitCall 中处理",
        "",
        "---",
        f"*本简报由 LitCall Agent 自动生成 · {date_str} {time_str}*",
    ])

    content = "\n".join(lines)

    # ── 保存文件 ──
    filename = f"{date_str}-检索简报.md"
    filepath = DAILY_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"[Agent] 每日简报已保存: {filepath}")
    return str(filepath)
