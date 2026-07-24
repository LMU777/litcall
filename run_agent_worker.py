#!/usr/bin/env python3
"""
🦉 ATHENA Agent Worker — 独立子进程执行器

由 Streamlit 通过 subprocess.Popen 拉起，独立于 Web 进程运行。
浏览器关闭不影响执行。进度通过 AgentRunLogger JSON 文件汇报。

用法:
    python run_agent_worker.py --year-start 2025 --year-end 2026 [--headless]
    python run_agent_worker.py --target-papers 5 --max-pages 10 --keyword-override "\"AI\" AND \"marketing\""
"""

import asyncio
import sys
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from literature_agent import full_autonomous_session, logger, AgentSignalError


async def main():
    parser = argparse.ArgumentParser(description="ATHENA Agent Worker")
    parser.add_argument("--year-start", type=int, default=2025)
    parser.add_argument("--year-end", type=int, default=2026)
    parser.add_argument("--headless", action="store_true", default=False,
                        help="无头模式运行浏览器（需先手动登录 SPIS 保存 cookies）")
    parser.add_argument("--target-papers", type=int, default=5,
                        help="本次运行总共收集多少篇论文（跨关键词总计，默认5）")
    parser.add_argument("--max-pages", type=int, default=10,
                        help="每个关键词最多翻多少页（默认10）")
    parser.add_argument("--journal-filter", type=str, default="",
                        help="逗号分隔的期刊名过滤（留空=使用白名单）")
    parser.add_argument("--keyword-override", type=str, default="",
                        help="自定义搜索关键词（覆盖关键词游标，仅本次有效）")
    args = parser.parse_args()

    # 解析 journal filter
    journal_filter = None
    if args.journal_filter.strip():
        journal_filter = [j.strip() for j in args.journal_filter.split(",") if j.strip()]

    keyword_override = args.keyword_override.strip() or None

    logger.info("=" * 60)
    logger.info(f"🦉 ATHENA Agent Worker 启动 (独立进程)")
    logger.info(f"   年份: {args.year_start}-{args.year_end}")
    logger.info(f"   无头: {args.headless}")
    logger.info(f"   总篇数: {args.target_papers}")
    logger.info(f"   最大翻页: {args.max_pages}")
    if journal_filter:
        logger.info(f"   期刊过滤: {journal_filter}")
    if keyword_override:
        logger.info(f"   自定义关键词: {keyword_override}")
    logger.info("=" * 60)

    try:
        result = await full_autonomous_session(
            year_start=args.year_start,
            year_end=args.year_end,
            headless=args.headless,
            global_paper_limit=args.target_papers,
            max_pages_per_kw=args.max_pages,
            journal_filter=journal_filter,
            keyword_override=keyword_override,
        )
        summary = result.get("combined_summary", {})
        logger.info("=" * 60)
        logger.info(f"✅ Agent Worker 完成")
        logger.info(f"   Phase 1: {summary.get('new_papers_found', 0)} 篇新文献")
        logger.info(f"   Phase 2: {summary.get('papers_processed', 0)} 篇入库")
        logger.info(f"   Phase 3: 索引已刷新")
        logger.info(f"   运行日志: {result.get('run_id', '?')}")
        logger.info("=" * 60)
        return 0
    except AgentSignalError:
        logger.info("=" * 60)
        logger.info("⏹ Agent Worker 已被用户终止")
        logger.info("=" * 60)
        return 0
    except Exception as e:
        logger.error(f"Agent Worker 异常: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
