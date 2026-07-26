"""CLI Worker 入口 — LitCall Agent 的命令行启动器。

用法:
    python -m litcall.ui.worker --mode reread
    python -m litcall.ui.worker --mode read_only
    python -m litcall.ui.worker --mode full --target 5
    python -m litcall.ui.worker --mode watch
"""

import argparse
import asyncio
import logging
import sys

from litcall.agent.orchestrator import (
    LitCallOrchestrator,
    OrchestratorMode,
)
from litcall.core import encoding  # noqa: F401 — UTF-8 安全网
from litcall.core.logging import setup_logging

logger = logging.getLogger("litcall.worker")


def parse_args():
    parser = argparse.ArgumentParser(
        description="LitCall v3.0 — AI × Marketing 学术文献智能助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m litcall.ui.worker --mode reread                 # 批量重读（Zotero → Obsidian 完整重建）
  python -m litcall.ui.worker --mode reread --target 2      # 先跑 2 篇验证
  python -m litcall.ui.worker --mode read_only              # 仅处理已有 PDF
  python -m litcall.ui.worker --mode watch                  # Watch 模式
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["full", "read_only", "watch", "search_only", "reread"],
        default="reread",
        help="运行模式 (default: reread)",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=0,
        dest="target_papers",
        help="目标论文数，0=不限 (default: 0)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    setup_logging(console=True)

    mode_map = {
        "full": OrchestratorMode.FULL,
        "read_only": OrchestratorMode.READ_ONLY,
        "watch": OrchestratorMode.WATCH,
        "search_only": OrchestratorMode.SEARCH_ONLY,
        "reread": OrchestratorMode.REREAD,
    }

    orchestrator = LitCallOrchestrator(
        mode=mode_map[args.mode],
        target_papers=args.target_papers,
    )

    logger.info(
        f"LitCall v3.0 启动 (mode={args.mode}, "
        f"target={args.target_papers or 'unlimited'})"
    )

    try:
        result = await orchestrator.run()
        logger.info(f"运行完成: {result}")
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"运行异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
