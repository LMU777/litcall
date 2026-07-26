"""ProcessedLogStore — JSON 文件存储，追踪论文处理状态。

文件: processed_log.json
格式: [{"doi": "...", "title": "...", "status": "done", ...}, ...]

铁律 #1: 原子写入 (temp 文件 + replace)
铁律 #8: 已存在记录时填充空字段，不跳过
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from litcall.core.paths import PROCESSED_LOG
from litcall.stores.base import AbstractStore, PaperData, VerifyResult, norm_doi

logger = logging.getLogger(__name__)


class ProcessedLogStore(AbstractStore):
    """processed_log.json 存储后端。"""

    name = "processed_log"

    def __init__(self, path: Optional[Path] = None):
        self._path = path or PROCESSED_LOG
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("[]", encoding="utf-8")

    # ── 读写 ──

    def _read_all(self) -> List[Dict]:
        """读取全部记录。"""
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"{self._path} 损坏或不存在，返回空列表")
            return []

    def _write_all(self, records: List[Dict]) -> None:
        """原子写回全部记录。"""
        tmp = Path(str(self._path) + ".tmp")
        tmp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    # ── AbstractStore 接口 ──

    async def write(self, paper: PaperData) -> bool:
        """写入或更新论文记录。

        铁律 #8: 已存在 → 填充空字段，不跳过。
        """
        try:
            records = self._read_all()
            ndoi = norm_doi(paper.doi)

            # 查找是否已存在
            existing_idx = None
            for i, rec in enumerate(records):
                if norm_doi(rec.get("doi", "")) == ndoi:
                    existing_idx = i
                    break

            now = datetime.now().isoformat()
            new_record = {
                "doi": paper.doi,
                "title": paper.title,
                "file": Path(paper.pdf_path).name if paper.pdf_path else "",
                "year": paper.year,
                "journal": paper.journal,
                "status": paper.status,
                "updated_at": now,
            }

            if existing_idx is not None:
                # 填充空字段，不跳过
                old = records[existing_idx]
                for k, v in new_record.items():
                    if not old.get(k) and v:
                        old[k] = v
                old["status"] = paper.status or old.get("status", "done")
                old["updated_at"] = now
            else:
                new_record["created_at"] = now
                records.append(new_record)

            self._write_all(records)
            return True
        except Exception as e:
            logger.error(f"ProcessedLogStore.write 失败: {e}")
            return False

    async def verify(self, doi: str) -> VerifyResult:
        """验证 DOI 存在于 processed_log 中。"""
        try:
            ndoi = norm_doi(doi)
            records = self._read_all()
            for rec in records:
                if norm_doi(rec.get("doi", "")) == ndoi:
                    return VerifyResult(
                        store_name=self.name, ok=True,
                        found_doi=ndoi,
                        found_title=rec.get("title", ""),
                    )
            return VerifyResult(
                store_name=self.name, ok=False,
                detail=f"DOI {ndoi} 不在 {self.name} 中",
            )
        except Exception as e:
            return VerifyResult(
                store_name=self.name, ok=False,
                detail=f"验证异常: {e}",
            )

    async def delete(self, doi: str) -> bool:
        """删除记录（用于回滚）。"""
        try:
            ndoi = norm_doi(doi)
            records = self._read_all()
            before = len(records)
            records = [r for r in records if norm_doi(r.get("doi", "")) != ndoi]
            if len(records) < before:
                self._write_all(records)
                logger.info(f"ProcessedLogStore: 删除 {doi}")
            return True
        except Exception as e:
            logger.error(f"ProcessedLogStore.delete 失败: {e}")
            return False

    def count(self) -> int:
        return len(self._read_all())

    def list_dois(self) -> Set[str]:
        return {norm_doi(r.get("doi", "")) for r in self._read_all() if r.get("doi")}

    # ── 扩展方法 ──

    def get_paper(self, doi: str) -> Optional[Dict]:
        """获取单条记录。"""
        ndoi = norm_doi(doi)
        for rec in self._read_all():
            if norm_doi(rec.get("doi", "")) == ndoi:
                return dict(rec)
        return None

    def update_status(self, doi: str, status: str, error: str = "") -> bool:
        """更新论文生命周期状态。"""
        try:
            ndoi = norm_doi(doi)
            records = self._read_all()
            for rec in records:
                if norm_doi(rec.get("doi", "")) == ndoi:
                    rec["status"] = status
                    if error:
                        rec["error"] = error
                    rec["updated_at"] = datetime.now().isoformat()
                    self._write_all(records)
                    return True
            return False
        except Exception as e:
            logger.error(f"update_status 失败: {e}")
            return False
