"""FourStoreTransaction — 四库原子事务。

铁律 #2: 四库全部成功写入 + 全部验证通过，才标记已处理 + 删 PDF。
        任一失败 → 全部回滚 → PDF 保留。
"""

import logging
from typing import Dict, List, Optional

from litcall.stores.base import (
    AbstractStore,
    PaperData,
    TransactionResult,
    VerifyResult,
    norm_doi,
)
from litcall.stores.excel import ExcelStore
from litcall.stores.obsidian import ObsidianStore
from litcall.stores.processed_log import ProcessedLogStore
from litcall.stores.zotero import ZoteroStore

logger = logging.getLogger(__name__)


class FourStoreTransaction:
    """四库原子事务管理器。

    写入顺序（先本地后远程，processed_log 最后）:
    1. Obsidian  — 本地最快
    2. Excel     — 本地文件
    3. Zotero    — 远程 API（最慢，最易失败）
    4. processed_log — 最后写（标记"已处理"）

    全部成功 → 逐个验证 → 返回 TransactionResult.ok
    任一失败 → 逆序回滚已写入的库 → 返回 TransactionResult.failed
    """

    WRITE_ORDER = ["obsidian", "excel", "zotero", "processed_log"]

    def __init__(
        self,
        obsidian: Optional[ObsidianStore] = None,
        excel: Optional[ExcelStore] = None,
        zotero: Optional[ZoteroStore] = None,
        processed_log: Optional[ProcessedLogStore] = None,
    ):
        self._stores: Dict[str, AbstractStore] = {
            "obsidian": obsidian or ObsidianStore(),
            "excel": excel or ExcelStore(),
            "zotero": zotero or ZoteroStore(),
            "processed_log": processed_log or ProcessedLogStore(),
        }

    @property
    def stores(self) -> Dict[str, AbstractStore]:
        return self._stores

    async def commit(self, paper: PaperData) -> TransactionResult:
        """原子提交一篇论文到四库。

        流程:
        1. 按 WRITE_ORDER 顺序写入四库
        2. 任一 write 返回 False 或抛异常 → 逆序回滚 → 返回 failed
        3. 全部 write 成功 → 逐个 verify
        4. 任一 verify 失败 → 返回 failed
        5. 全部 verify 成功 → 返回 success
        """
        ndoi = norm_doi(paper.doi)
        written: List[str] = []

        # Phase 1: 写入
        for store_name in self.WRITE_ORDER:
            store = self._stores[store_name]
            try:
                success = await store.write(paper)
                if not success:
                    await self._rollback(written, ndoi)
                    return TransactionResult.failed(
                        doi=paper.doi, title=paper.title,
                        store=store_name, reason="write() 返回 False",
                        written=written,
                    )
                written.append(store_name)
                logger.info(f"事务: {store_name} 写入成功 (DOI: {ndoi})")
            except Exception as e:
                logger.error(f"事务: {store_name} 写入异常: {e}")
                await self._rollback(written, ndoi)
                return TransactionResult.failed(
                    doi=paper.doi, title=paper.title,
                    store=store_name, reason=f"写入异常: {e}",
                    written=written,
                )

        # Phase 2: 逐个验证
        verified: List[str] = []
        unverified: List[str] = []

        for store_name in self.WRITE_ORDER:
            store = self._stores[store_name]
            try:
                result = await store.verify(paper.doi)
                if result.ok:
                    verified.append(store_name)
                else:
                    unverified.append(store_name)
                    logger.error(
                        f"事务: {store_name} 验证失败: {result.detail}"
                    )
            except Exception as e:
                unverified.append(store_name)
                logger.error(f"事务: {store_name} 验证异常: {e}")

        if unverified:
            return TransactionResult.failed(
                doi=paper.doi, title=paper.title,
                store=unverified[0],
                reason=f"验证失败: {len(unverified)} 个库未通过 "
                       f"({', '.join(unverified)})",
                written=written,
            )

        logger.info(
            f"事务: 四库原子提交成功 (DOI: {ndoi})"
        )
        return TransactionResult.success(
            doi=paper.doi, title=paper.title,
            written=written, verified=verified,
        )

    async def _rollback(self, written: List[str], doi: str) -> None:
        """逆序回滚已写入的库。"""
        for store_name in reversed(written):
            store = self._stores[store_name]
            try:
                success = await store.delete(doi)
                if success:
                    logger.info(
                        f"事务回滚: {store_name} 删除成功 (DOI: {doi})"
                    )
                else:
                    logger.error(
                        f"事务回滚: {store_name} 删除失败 (DOI: {doi})"
                    )
            except Exception as e:
                logger.error(
                    f"事务回滚: {store_name} 删除异常: {e} (DOI: {doi})"
                )

    async def verify_all(self, doi: str) -> Dict[str, VerifyResult]:
        """验证一篇论文在四库中的存在状态（不写入）。"""
        results = {}
        for name, store in self._stores.items():
            try:
                results[name] = await store.verify(doi)
            except Exception as e:
                results[name] = VerifyResult(
                    store_name=name, ok=False, detail=f"验证异常: {e}"
                )
        return results

    def count_all(self) -> Dict[str, int]:
        """获取四库各自的论文计数。"""
        return {name: store.count() for name, store in self._stores.items()}

    def list_all_dois(self) -> Dict[str, set]:
        """获取四库各自的 DOI 集合。"""
        return {name: store.list_dois() for name, store in self._stores.items()}
