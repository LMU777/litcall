"""LitCallOrchestrator — 论文处理协调器。

铁律 #6: Agent 是唯一入口。CLI 和 Web 只是 Agent 的两种控制界面。

模式:
- reread: 从 Zotero litcall 集合获取全部文献，重新深度阅读
- read_only: 仅阅读 待处理文献/ 中的 PDF
- full: 检索 + 阅读（需要搜索流水线模块）
- watch: 监控 待处理文献/ 新 PDF
"""

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from litcall.agent.file_lock import WorkerLock
from litcall.agent.ipc import (
    Signal,
    check_and_wait_if_paused,
    check_signal_files,
    clear_all_signals,
    write_pid,
)
from litcall.agent.run_logger import AgentRunLogger
from litcall.agent.state_machine import PaperStatus
from litcall.core.config import config
from litcall.core.paths import PDF_DIR
from litcall.pipeline.read.deepseek_reader import generate_notes
from litcall.pipeline.read.journal_if import match_impact_factor
from litcall.pipeline.read.pdf_extract import (
    extract_doi_from_pdf,
    extract_text_from_pdf,
)
from litcall.stores.base import PaperData, norm_doi
from litcall.stores.obsidian import ObsidianStore
from litcall.stores.processed_log import ProcessedLogStore
from litcall.stores.transaction import FourStoreTransaction
from litcall.stores.zotero import ZoteroStore

logger = logging.getLogger(__name__)

# ── 标签规范 ──
# 铁律: tags 使用空格分词，小写。只有 AI 技术词用大写缩写: AI, GenAI, ML, LLM, NLP

TAG_MAP = {
    # AI 技术缩写（大写）
    "人工智能": "AI", "artificial intelligence": "AI", "ai": "AI",
    "生成式ai": "GenAI", "生成式人工智能": "GenAI",
    "generative ai": "GenAI", "genai": "GenAI",
    "generative artificial intelligence": "GenAI",
    "机器学习": "ML", "machine learning": "ML",
    "大语言模型": "LLM", "大型语言模型": "LLM",
    "large language model": "LLM", "llm": "LLM",
    "自然语言处理": "NLP", "natural language processing": "NLP",
    # 常见概念（小写空格）
    "消费者行为": "consumer behavior",
    "consumer behaviour": "consumer behavior",
    "消费者信任": "consumer trust",
    "品牌信任": "brand trust",
    "品牌参与": "brand engagement",
    "品牌engagement": "brand engagement",
    "客户体验": "customer experience",
    "顾客体验": "customer experience",
    "cx": "customer experience",
    "营销策略": "marketing strategy",
    "数字营销": "digital marketing",
    "数字化转型": "digital transformation",
    "虚拟影响者": "virtual influencer",
    "虚拟网红": "virtual influencer",
    "人机协同": "human-AI collaboration",
    "人机协作": "human-AI collaboration",
    "个性化": "personalization",
    "personalisation": "personalization",
    "真实性": "authenticity",
    "ai伦理": "AI ethics", "人工智能伦理": "AI ethics",
    "隐私": "privacy",
    "决策": "decision making",
    "共创": "co-creation",
    "现场实验": "field experiment",
    "元分析": "meta-analysis",
    "旅游": "tourism",
    "服务补救": "service recovery",
    "文献计量": "bibliometrics", "文献计量学": "bibliometrics",
    "算法": "algorithms", "algorithm": "algorithms",
    "聊天机器人": "chatbot", "chatbots": "chatbot",
    "敏捷": "agility",
    "信任": "trust",
    "品牌": "brand",
    "创新": "innovation",
    "中小企业": "SME", "sme": "SME",
    "高等教育": "higher education",
    "供应链": "supply chain",
    "系统性文献综述": "SLR",
    "自动化": "automation",
    "可持续性": "sustainability",
    "区块链": "blockchain",
}


class OrchestratorMode(str, Enum):
    FULL = "full"
    READ_ONLY = "read_only"
    WATCH = "watch"
    SEARCH_ONLY = "search_only"
    REREAD = "reread"


class LitCallOrchestrator:
    """LitCall Agent 主控制器。

    协调两条流水线:
    - 检索流水线: SPIS 搜索 → 去重 → 下载 PDF
    - 阅读流水线: 提取文本 → DeepSeek 精读 → 四库事务 → 自检 → 删 PDF

    每个论文级操作前后检查信号文件（铁律 #5）。
    """

    def __init__(
        self,
        mode: OrchestratorMode = OrchestratorMode.READ_ONLY,
        target_papers: int = 0,
    ):
        self._mode = mode
        self._target_papers = target_papers
        self._run_logger: Optional[AgentRunLogger] = None
        self._worker_lock = WorkerLock()
        self._transaction = FourStoreTransaction()
        self._processed_log = ProcessedLogStore()

    @staticmethod
    def _keywords_to_tags(keywords: str) -> str:
        """将 DeepSeek 返回的关键词转为规范化标签（换行分隔）。

        铁律: tags 用空格分词，小写。只有 AI 技术词用大写缩写。
        """
        if not keywords or not keywords.strip():
            return ""
        import re
        kws = re.split(r'[,;，；]\s*', keywords)
        tags = []
        seen = set()
        for kw in kws:
            kw = kw.strip().lower()
            if not kw:
                continue
            tag = TAG_MAP.get(kw)
            if not tag:
                tag = kw.replace("-", " ").replace("_", " ")
                if len(tag) < 2 or len(tag) > 50:
                    continue
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
        return "\n".join(tags)

    # ═══════════════════════════════════════════════════════════════
    # 主循环
    # ═══════════════════════════════════════════════════════════════

    async def run(self) -> Dict:
        """启动 Agent 主循环。"""
        if not self._worker_lock.acquire():
            logger.error("无法获取 Worker 锁（已有实例在运行）")
            return {"error": "worker_already_running"}

        try:
            write_pid()
            clear_all_signals()
            self._run_logger = AgentRunLogger()

            if self._mode == OrchestratorMode.REREAD:
                stats = await self._run_reread_loop()
            elif self._mode == OrchestratorMode.READ_ONLY:
                stats = await self._run_read_loop()
            elif self._mode == OrchestratorMode.FULL:
                stats = await self._run_full_loop()
            elif self._mode == OrchestratorMode.SEARCH_ONLY:
                stats = await self._run_search_loop()
            elif self._mode == OrchestratorMode.WATCH:
                stats = await self._run_watch_loop()
            else:
                stats = {"error": f"未知模式: {self._mode}"}

            return stats
        except Exception as e:
            logger.error(f"Orchestrator 异常: {e}")
            return {"error": str(e)}
        finally:
            if self._run_logger:
                self._run_logger.log_completion()
            self._worker_lock.release()

    # ═══════════════════════════════════════════════════════════════
    # 批量重读模式（Zotero litcall → Obsidian 完整重建）
    # ═══════════════════════════════════════════════════════════════

    async def _run_reread_loop(self) -> Dict:
        """从 Zotero litcall 集合获取全部文献，重新深度阅读。

        铁律: Zotero litcall = Obsidian。以 Zotero 为单一真相来源。
        不做任何"是否需要重读"的判断——处理集合中每一篇文献。

        流程:
        1. 获取 Zotero litcall 集合全部条目
        2. 为每篇找到 PDF 附件（从 Zotero 本地 storage 拷贝）
        3. 逐篇深度阅读 → 四库原子事务
        4. 验证 Zotero litcall DOI 集合 = Obsidian DOI 集合
        """
        self._run_logger.log_phase("reread", "开始重读模式 — Zotero litcall → Obsidian 完整重建")
        stats = {
            "collection_items": 0,
            "no_pdf": 0,
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }

        zotero_store = ZoteroStore()
        obsidian_store = ObsidianStore()

        # ── Step 1: 获取 litcall 集合全部条目 ──
        logger.info("Reread Step 1: 从 Zotero litcall 集合获取全部条目...")
        collection_items = await zotero_store.list_collection_items()

        if not collection_items:
            logger.error("Zotero litcall 集合为空或无法访问")
            self._run_logger.log_phase("reread_error", "litcall 集合为空")
            return stats

        stats["collection_items"] = len(collection_items)
        logger.info(
            f"Zotero litcall 集合: {len(collection_items)} 个条目"
        )

        # 过滤：只处理 journalArticle
        articles = [
            item for item in collection_items
            if item.get("item_type") == "journalArticle"
        ]
        logger.info(
            f"  其中 journalArticle: {len(articles)} 篇"
        )
        self._run_logger.log_phase(
            "reread_scan",
            f"litcall 集合: {len(collection_items)} 条目, "
            f"{len(articles)} journalArticle"
        )

        # ── Step 2: 为每篇找 PDF ──
        to_process = []
        for item in articles:
            item_key = item["key"]
            doi = norm_doi(item["doi"])
            title = item["title"]

            logger.info(f"查找 PDF: {doi} — {title[:60]}...")
            pdf_path = await zotero_store.find_pdf_for_item(item_key)

            if not pdf_path:
                logger.warning(
                    f"  ⊘ 无 PDF 附件: {doi} — {title[:60]}"
                )
                stats["no_pdf"] += 1
                self._run_logger.log_paper(
                    "no_pdf", doi=doi, title=title,
                    error="Zotero 条目无 PDF 附件"
                )
                continue

            to_process.append({
                "doi": doi,
                "title": title,
                "pdf_path": pdf_path,
                "item_key": item_key,
            })

        logger.info(
            f"Reread Step 2 完成: {len(to_process)} 篇有 PDF, "
            f"{stats['no_pdf']} 篇无 PDF"
        )
        self._run_logger.log_phase(
            "reread_pdfs",
            f"找到 {len(to_process)} 篇有 PDF, "
            f"{stats['no_pdf']} 篇无 PDF"
        )

        if not to_process:
            logger.warning("没有可处理的论文（全部无 PDF 附件）")
            return stats

        # ── Step 3: 逐篇深度阅读 ──
        stats["total"] = len(to_process)
        for i, paper_info in enumerate(to_process):
            sig = await check_and_wait_if_paused()
            if sig == Signal.TERMINATED:
                logger.info("Reread 收到终止信号，停止")
                break

            if self._target_papers > 0 and stats["success"] >= self._target_papers:
                logger.info(f"已达到目标论文数 ({self._target_papers})，停止")
                break

            ndoi = paper_info["doi"]
            title = paper_info["title"]
            pdf_path = paper_info["pdf_path"]

            logger.info(
                f"Reread [{i+1}/{len(to_process)}] {ndoi}: {title[:60]}..."
            )
            self._run_logger.log_phase(
                "reread_paper",
                f"[{i+1}/{len(to_process)}] {ndoi} — {title[:60]}"
            )

            # 标记为 rereading（防止 _process_one_paper 的 skip 检查误跳过）
            self._processed_log.update_status(ndoi, PaperStatus.REREADING)

            # 深度阅读（与普通 read_only 模式共用 _process_one_paper）
            result = await self._process_one_paper(pdf_path)
            if result == "success":
                stats["success"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

        # ── Step 4: 验证 Zotero litcall = Obsidian ──
        logger.info("Reread Step 4: 验证 Zotero litcall = Obsidian...")
        litcall_items = await zotero_store.list_collection_items()
        from litcall.stores.base import norm_doi as _norm_doi
        zotero_dois = {_norm_doi(i.get("doi", "")) for i in litcall_items if i.get("doi")}
        obsidian_dois = obsidian_store.list_dois()

        only_zotero = zotero_dois - obsidian_dois
        only_obsidian = obsidian_dois - zotero_dois
        common = zotero_dois & obsidian_dois

        logger.info(
            f"四库比对: Zotero={len(zotero_dois)}, "
            f"Obsidian={len(obsidian_dois)}, "
            f"交集={len(common)}"
        )
        if only_zotero:
            logger.warning(
                f"Zotero 独有 ({len(only_zotero)}): "
                f"{list(only_zotero)[:5]}..."
            )
        if only_obsidian:
            logger.warning(
                f"Obsidian 独有 ({len(only_obsidian)}): "
                f"{list(only_obsidian)[:5]}..."
            )

        stats["zotero_count"] = len(zotero_dois)
        stats["obsidian_count"] = len(obsidian_dois)
        stats["common_count"] = len(common)

        self._run_logger.log_phase("reread_done", str(stats))
        logger.info(f"Reread 完成: {stats}")
        return stats

    # ═══════════════════════════════════════════════════════════════
    # 仅阅读模式
    # ═══════════════════════════════════════════════════════════════

    async def _run_read_loop(self) -> Dict:
        """仅阅读模式：处理 待处理文献/ 中的所有 PDF。"""
        self._run_logger.log_phase("read_loop", "开始阅读循环")
        stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}

        pdfs = sorted(PDF_DIR.glob("*.pdf"))
        if not pdfs:
            logger.info("待处理文献/ 中没有 PDF")
            return stats

        for pdf_path in pdfs:
            sig = await check_and_wait_if_paused()
            if sig == Signal.TERMINATED:
                logger.info("收到终止信号，停止阅读循环")
                break

            if self._target_papers > 0 and stats["success"] >= self._target_papers:
                break

            result = await self._process_one_paper(pdf_path)
            stats["total"] += 1
            if result == "success":
                stats["success"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

        self._run_logger.log_phase("read_loop_end", str(stats))
        return stats

    # ═══════════════════════════════════════════════════════════════
    # 核心流水线: 单篇 PDF → 四库入库
    # ═══════════════════════════════════════════════════════════════

    async def _process_one_paper(self, pdf_path: Path) -> str:
        """处理单篇 PDF 的完整流程。

        生命周期: downloaded → reading → storing → verifying → done

        Returns:
            "success" | "skipped" | "failed"
        """
        pdf_name = pdf_path.name
        ndoi = ""

        try:
            # Step 1: 提取 DOI
            doi = extract_doi_from_pdf(pdf_path)
            if not doi:
                logger.warning(f"无法提取 DOI: {pdf_name}")
                return "failed"

            ndoi = norm_doi(doi)
            self._run_logger.log_paper("discovered", doi=ndoi, title=pdf_name)

            # Step 2: 检查是否已处理
            existing = self._processed_log.get_paper(ndoi)
            if existing and existing.get("status") == "done":
                logger.info(f"论文已处理，跳过: {ndoi}")
                self._run_logger.log_paper("skipped", doi=ndoi, status="done")
                return "skipped"

            # Step 3: 提取全文
            text = extract_text_from_pdf(pdf_path)
            if not text or len(text) < 500:
                logger.warning(
                    f"PDF 文本过短 ({len(text)} chars): {pdf_name}"
                )
                return "failed"

            # Step 4: 状态: downloaded → reading
            self._processed_log.update_status(ndoi, PaperStatus.READING)
            self._run_logger.log_paper("reading", doi=ndoi, status="reading")

            # Step 5: DeepSeek 精读 + 反幻觉自检
            notes = await self._cancellable_deepseek(text, ndoi)
            if not notes:
                logger.error(f"DeepSeek 精读失败或被终止: {ndoi}")
                self._processed_log.update_status(
                    ndoi, PaperStatus.ERROR,
                    "DeepSeek API 精读失败或被终止"
                )
                return "failed"

            # Step 5b: Gemini Vision 图表识别 + DeepSeek 图表分析（可选）
            gemini_key = config.get("gemini_api_key", "")
            if config.get("enable_figure_analysis", False) and gemini_key:
                try:
                    from litcall.pipeline.read.gemini_vision import (
                        recognize_figures_structured,
                    )
                    from litcall.pipeline.read.figure_analysis import (
                        format_figure_data,
                        analyze_figures_with_deepseek,
                    )

                    logger.info(f"Gemini Vision 图表识别: {ndoi}")
                    figure_data = await recognize_figures_structured(
                        pdf_path, gemini_key
                    )
                    if figure_data:
                        total_figs = sum(
                            len(v) for v in figure_data.values()
                        )
                        if total_figs > 0:
                            logger.info(
                                f"Gemini 识别 {total_figs} 个图表/表格"
                            )
                            fig_summary = format_figure_data(figure_data)
                            analysis = await analyze_figures_with_deepseek(
                                text[:3000], fig_summary, notes
                            )
                            if analysis:
                                existing = notes.get(
                                    "深度理解与理论推导", ""
                                )
                                notes["深度理解与理论推导"] = (
                                    existing
                                    + "\n\n## 图表分析\n"
                                    + analysis
                                ).strip()
                                logger.info("图表分析完成")
                except Exception as e:
                    logger.warning(f"Gemini 图表识别异常: {e}")

            # Step 6: 匹配影响因子
            journal = notes.get("期刊", "")
            if_j, quartile = match_impact_factor(journal)
            notes["影响因子"] = if_j or notes.get("影响因子", "")
            notes["分区"] = quartile or notes.get("分区", "")

            # Step 7: 状态: reading → storing
            self._processed_log.update_status(ndoi, PaperStatus.STORING)
            self._run_logger.log_paper("storing", doi=ndoi, status="storing")

            # Step 8: 构建 PaperData（含 tags 规范化 + 反幻觉 QC）
            paper = PaperData(
                doi=doi,
                title=notes.get("标题", ""),
                authors=notes.get("作者", ""),
                first_author=notes.get("第一作者", ""),
                corresponding_author=notes.get("通讯作者", ""),
                year=notes.get("年份", ""),
                journal=journal,
                impact_factor=notes.get("影响因子", ""),
                quartile=notes.get("分区", ""),
                keywords=notes.get("关键词", ""),
                background=notes.get("研究背景与动机", ""),
                research_question=notes.get("研究问题", ""),
                variables=notes.get("变量汇总", ""),
                method=notes.get("研究方法", ""),
                method_details=notes.get("方法论详解", ""),
                results=notes.get("研究结果", ""),
                discussion=notes.get("讨论与结论", ""),
                innovation=notes.get("创新点", ""),
                limitations=notes.get("局限与展望", ""),
                figure_analysis=notes.get("深度理解与理论推导", ""),
                self_check_confidence=notes.get("_置信度", ""),
                self_check_flag=notes.get("_自检标记", ""),
                variable_check=json.dumps(
                    notes.get("_变量校验", []), ensure_ascii=False
                ),
                quality_issues=json.dumps(
                    notes.get("_问题汇总", []), ensure_ascii=False
                ),
                reading_method="deep_read",
                reading_date=datetime.now().strftime("%Y-%m-%d"),
                pdf_path=str(pdf_path),
                status=PaperStatus.STORING,
                tags=self._keywords_to_tags(notes.get("关键词", "")),
            )

            # Step 9: 入库前最后检查暂停/终止信号
            sig = await check_and_wait_if_paused()
            if sig == Signal.TERMINATED:
                logger.info(f"论文处理被终止（入库前）: {ndoi}")
                return "failed"

            # Step 10: 四库原子事务
            result = await self._transaction.commit(paper)
            if not result.ok:
                logger.error(
                    f"四库事务失败: {result.failed_store} — "
                    f"{result.failed_reason}"
                )
                self._run_logger.log_paper(
                    "error", doi=ndoi, status="error",
                    error=f"四库事务: {result.failed_store}",
                )
                self._processed_log.update_status(
                    ndoi, PaperStatus.ERROR,
                    f"四库事务失败: {result.failed_store}"
                )
                return "failed"

            # Step 11: 状态 storing → verifying
            self._processed_log.update_status(ndoi, PaperStatus.VERIFYING)
            self._run_logger.log_paper("verifying", doi=ndoi, status="verifying")

            # Step 12: 四库逐库验证
            verify_results = await self._transaction.verify_all(doi)
            all_verified = all(r.ok for r in verify_results.values())
            if not all_verified:
                failed_stores = [
                    n for n, r in verify_results.items() if not r.ok
                ]
                logger.error(
                    f"提交后验证失败: {failed_stores} (DOI: {ndoi})"
                )
                self._processed_log.update_status(
                    ndoi, PaperStatus.ERROR,
                    f"验证失败: {failed_stores}"
                )
                self._run_logger.log_paper(
                    "error", doi=ndoi, status="error",
                    error=f"验证失败: {failed_stores}",
                )
                return "failed"

            # Step 13: 状态 verifying → done
            self._processed_log.update_status(ndoi, PaperStatus.DONE)
            self._run_logger.log_paper("done", doi=ndoi, status="done")

            # Step 14: 删除 PDF（铁律: 四库全部验证通过后才删除）
            try:
                pdf_path.unlink()
                logger.info(f"PDF 已删除: {pdf_name}")
            except Exception as e:
                logger.warning(f"删除 PDF 失败: {e}")

            self._run_logger.log_heartbeat(f"done: {ndoi}")
            return "success"

        except Exception as e:
            logger.error(f"处理论文异常 ({pdf_name}): {e}")
            if ndoi:
                self._processed_log.update_status(
                    ndoi, PaperStatus.ERROR, str(e)
                )
            self._run_logger.log_paper(
                "error", doi=ndoi, status="error", error=str(e)
            )
            return "failed"

    # ═══════════════════════════════════════════════════════════════
    # 可中断 DeepSeek 调用
    # ═══════════════════════════════════════════════════════════════

    async def _cancellable_deepseek(self, text: str, ndoi: str):
        """运行 DeepSeek 精读，每 2 秒轮询信号文件以响应暂停/终止。

        铁律 #5: 暂停/终止必须即时响应。
        """
        task = asyncio.create_task(generate_notes(text))

        while not task.done():
            sig = check_signal_files()
            if sig == Signal.TERMINATED:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                logger.info(f"[信号] DeepSeek 被终止: {ndoi}")
                return None
            if sig == Signal.PAUSED:
                logger.info(f"[信号] DeepSeek 暂停中 ({ndoi})...")
                while check_signal_files() == Signal.PAUSED:
                    await asyncio.sleep(0.5)
                    if check_signal_files() == Signal.TERMINATED:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        logger.info(
                            f"[信号] DeepSeek 被终止（暂停中）: {ndoi}"
                        )
                        return None
                logger.info(f"[信号] DeepSeek 恢复: {ndoi}")

            done, _ = await asyncio.wait([task], timeout=2.0)
            if done:
                break

        return await task

    # ═══════════════════════════════════════════════════════════════
    # 完整模式: SPIS 检索 + 深度阅读
    # ═══════════════════════════════════════════════════════════════

    async def _run_full_loop(self) -> Dict:
        """完整模式: SPIS 检索 → 去重 → 期刊过滤 → 下载 → 深度阅读。

        流程:
        1. 从关键词游标开始，逐关键词在 SPIS 检索新论文
        2. 自动去重 (DOI + 标题) + 期刊白名单过滤 + 文献求助
        3. 有下载链接的论文 → pending_manual.json（需手动下载到 PDF_DIR）
        4. 检索完成后，对 PDF_DIR 中所有 PDF 执行深度阅读流水线
        """
        self._run_logger.log_phase("full", "完整模式 — SPIS 检索 + 深度阅读")
        logger.info("=" * 60)
        logger.info("LitCall Full Mode: SPIS 检索 + 深度阅读")
        logger.info("=" * 60)

        # ── 读取搜索配置 ──
        search_cfg = config.get("search", {})
        year_start = int(search_cfg.get("year_start", 2025))
        year_end = int(search_cfg.get("year_end", 2026))
        headless = search_cfg.get("headless", False)
        journal_filter = config.get("journal_whitelist_extra", None)
        max_pages_per_kw = search_cfg.get("max_pages_per_keyword", 10)
        global_limit = self._target_papers or search_cfg.get("global_paper_limit", 10)

        search_stats = {
            "collected": 0,
            "with_links": 0,
            "without_links": 0,
            "help_submitted": 0,
            "keywords_exhausted": False,
        }

        # ── Phase 1: SPIS 检索 ──
        try:
            from litcall.pipeline.search.spis_browser import (
                AgentSignalError,
                _scrape_new_articles_autonomous,
            )

            logger.info(
                f"SPIS 检索参数: {year_start}-{year_end}, "
                f"headless={headless}, limit={global_limit}"
            )
            self._run_logger.log_phase(
                "full_search",
                f"SPIS {year_start}-{year_end}, limit={global_limit}",
            )

            result = await _scrape_new_articles_autonomous(
                year_start=year_start,
                year_end=year_end,
                headless=headless,
                global_paper_limit=global_limit,
                max_pages_per_kw=max_pages_per_kw,
                journal_filter=journal_filter,
                run_logger=self._run_logger,
            )

            search_stats["collected"] = len(result.get("collected", []))
            search_stats["with_links"] = len(result.get("with_links", []))
            search_stats["without_links"] = len(result.get("without_links", []))
            search_stats["help_submitted"] = result.get("help_submitted", 0)
            search_stats["keywords_exhausted"] = result.get(
                "keywords_exhausted", False
            )

            logger.info(
                f"SPIS 检索完成: 收集 {search_stats['collected']} 篇 "
                f"(有链接 {search_stats['with_links']}, "
                f"无链接 {search_stats['without_links']}, "
                f"求助 {search_stats['help_submitted']})"
            )
            self._run_logger.log_phase(
                "full_search_done", str(search_stats)
            )

        except ImportError as e:
            logger.error(
                f"搜索流水线模块不可用: {e}\n"
                f"  请安装 playwright: pip install playwright && playwright install"
            )
            self._run_logger.log_phase(
                "full_search_error",
                f"模块缺失: {e}",
            )
            return {**search_stats, "error": f"搜索模块不可用: {e}"}
        except AgentSignalError:
            logger.info("SPIS 检索被用户终止")
            self._run_logger.log_phase(
                "full_search_terminated", "用户终止"
            )
            return {**search_stats, "terminated": True}
        except Exception as e:
            logger.error(f"SPIS 检索异常: {e}")
            self._run_logger.log_phase("full_search_error", str(e))
            return {**search_stats, "error": str(e)}

        # ── Phase 2: 深度阅读 PDF_DIR 中的 PDF ──
        logger.info(
            "Phase 2: 深度阅读 PDF_DIR 中的 PDF..."
        )
        read_stats = await self._run_read_loop()

        combined = {**search_stats, **read_stats}
        self._run_logger.log_phase("full_done", str(combined))
        logger.info(f"完整模式完成: {combined}")
        return combined

    # ═══════════════════════════════════════════════════════════════
    # 仅检索模式: 只搜索 SPIS，不阅读
    # ═══════════════════════════════════════════════════════════════

    async def _run_search_loop(self) -> Dict:
        """仅检索模式: 只搜索 SPIS，不触发深度阅读。

        搜索结果:
        - 有下载链接的论文 → pending_manual.json（手动下载到 PDF_DIR 后
          可用 read_only 模式处理）
        - 无下载链接的论文 → 自动提交文献求助
        - 关键词游标自动推进，重启后从下一个关键词继续
        """
        self._run_logger.log_phase(
            "search_only", "仅检索模式 — SPIS 搜索"
        )
        logger.info("=" * 60)
        logger.info("LitCall Search-Only Mode: 仅 SPIS 检索")
        logger.info("=" * 60)

        search_cfg = config.get("search", {})
        year_start = int(search_cfg.get("year_start", 2025))
        year_end = int(search_cfg.get("year_end", 2026))
        headless = search_cfg.get("headless", False)
        journal_filter = config.get("journal_whitelist_extra", None)
        max_pages_per_kw = search_cfg.get("max_pages_per_keyword", 10)
        global_limit = self._target_papers or search_cfg.get("global_paper_limit", 10)

        stats = {
            "collected": 0,
            "with_links": 0,
            "without_links": 0,
            "help_submitted": 0,
            "keywords_exhausted": False,
        }

        try:
            from litcall.pipeline.search.spis_browser import (
                AgentSignalError,
                _scrape_new_articles_autonomous,
            )

            logger.info(
                f"SPIS 检索参数: {year_start}-{year_end}, "
                f"headless={headless}, limit={global_limit}"
            )

            result = await _scrape_new_articles_autonomous(
                year_start=year_start,
                year_end=year_end,
                headless=headless,
                global_paper_limit=global_limit,
                max_pages_per_kw=max_pages_per_kw,
                journal_filter=journal_filter,
                run_logger=self._run_logger,
            )

            stats["collected"] = len(result.get("collected", []))
            stats["with_links"] = len(result.get("with_links", []))
            stats["without_links"] = len(result.get("without_links", []))
            stats["help_submitted"] = result.get("help_submitted", 0)
            stats["keywords_exhausted"] = result.get(
                "keywords_exhausted", False
            )

            logger.info(f"仅检索完成: {stats}")
            self._run_logger.log_phase("search_only_done", str(stats))

        except ImportError as e:
            logger.error(f"搜索流水线模块不可用: {e}")
            self._run_logger.log_phase(
                "search_only_error", f"模块缺失: {e}"
            )
            stats["error"] = f"搜索模块不可用: {e}"
        except AgentSignalError:
            logger.info("SPIS 检索被用户终止")
            self._run_logger.log_phase(
                "search_only_terminated", "用户终止"
            )
            stats["terminated"] = True
        except Exception as e:
            logger.error(f"SPIS 检索异常: {e}")
            self._run_logger.log_phase("search_only_error", str(e))
            stats["error"] = str(e)

        return stats

    # ═══════════════════════════════════════════════════════════════
    # Watch 模式: 持续监控
    # ═══════════════════════════════════════════════════════════════

    async def _run_watch_loop(self) -> Dict:
        """Watch 模式: 持续监控 待处理文献/ 新 PDF。"""
        self._run_logger.log_phase("watch", "开始 Watch 模式")
        logger.info("Watch 模式启动，扫描间隔 30s")

        known_pdfs = set()
        while True:
            sig = check_signal_files()
            if sig == Signal.TERMINATED:
                break
            await check_and_wait_if_paused()

            current_pdfs = set(PDF_DIR.glob("*.pdf"))
            new_pdfs = current_pdfs - known_pdfs

            for pdf_path in sorted(new_pdfs):
                sig = await check_and_wait_if_paused()
                if sig == Signal.TERMINATED:
                    break
                await self._process_one_paper(pdf_path)

            known_pdfs = current_pdfs
            await asyncio.sleep(30)

        return {"watch": "terminated"}
