"""ZoteroStore — Zotero Web API 文献库管理。

铁律 #10: Zotero 搜索 API 不索引 DOI。验证用直接 GET /items/{key}。
铁律 #11: 只传 DOI + PDF，让 Zotero 通过 Crossref/PubMed 自行获取元数据。
铁律: 批量重读只查 litcall 集合，严禁动用户其他文献。
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set

import aiohttp

from litcall.core.config import config
from litcall.stores.base import AbstractStore, PaperData, VerifyResult, norm_doi

logger = logging.getLogger(__name__)

ZOTERO_API_BASE = "https://api.zotero.org"


class ZoteroStore(AbstractStore):
    """Zotero Web API 存储后端。"""

    name = "zotero"

    def __init__(self, user_id: str = "", api_key: str = "",
                 collection_name: str = "litcall"):
        self._user_id = user_id or str(config.get("zotero", {}).get("user_id", ""))
        self._api_key = api_key or str(config.get("zotero", {}).get("api_key", ""))
        self._collection_name = collection_name or str(
            config.get("zotero", {}).get("collection_name", "litcall")
        )
        self._collection_key: Optional[str] = None

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Zotero-API-Key": self._api_key,
                "Content-Type": "application/json"}

    # ═══════════════════════════════════════════════════════════════
    # Collection 管理
    # ═══════════════════════════════════════════════════════════════

    async def _get_collection_key(self) -> Optional[str]:
        """获取或创建 litcall collection key。

        铁律: 同名 collection 存在时选条目最多的。
        """
        if self._collection_key:
            return self._collection_key

        async with aiohttp.ClientSession() as session:
            url = f"{ZOTERO_API_BASE}/users/{self._user_id}/collections"
            async with session.get(url, headers=self._headers) as resp:
                if resp.status != 200:
                    logger.error(f"获取 collections 失败: {resp.status}")
                    return None
                collections = await resp.json()

            matches = [c for c in collections
                       if c.get("data", {}).get("name") == self._collection_name]

            if not matches:
                create_url = f"{ZOTERO_API_BASE}/users/{self._user_id}/collections"
                body = json.dumps({"name": self._collection_name})
                async with session.post(create_url, headers=self._headers,
                                        data=body) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        key = data.get("key", "")
                        logger.info(
                            f"Zotero: 创建 collection "
                            f"'{self._collection_name}' ({key})"
                        )
                        self._collection_key = key
                        return key
                    logger.error(f"创建 collection 失败: {resp.status}")
                    return None

            if len(matches) > 1:
                best = matches[0]
                best_count = matches[0].get("data", {}).get("items", 0)
                for m in matches[1:]:
                    count = m.get("data", {}).get("items", 0)
                    if count > best_count:
                        best = m
                        best_count = count
                self._collection_key = best["key"]
                logger.info(
                    f"Zotero: 选择 collection '{self._collection_name}' "
                    f"({len(matches)} 同名, 选 {best_count} 条目的)"
                )
            else:
                self._collection_key = matches[0]["key"]

            return self._collection_key

    # ═══════════════════════════════════════════════════════════════
    # Collection 条目查询 — litcall 专属
    # ═══════════════════════════════════════════════════════════════

    async def list_collection_items(self) -> List[Dict]:
        """获取 litcall 集合中所有条目的基本信息。

        铁律: 只查 litcall 集合，不碰用户其他文献。
        使用 /collections/{ckey}/items 端点，分页获取全部条目。

        Returns:
            [{"key": "ABC123", "doi": "10.xxx", "title": "...",
              "item_type": "journalArticle", "year": "2024"}, ...]
        """
        ckey = await self._get_collection_key()
        if not ckey:
            logger.error("Zotero: 无法获取 litcall collection key")
            return []

        all_items = []
        start = 0
        limit = 100

        async with aiohttp.ClientSession() as session:
            while True:
                url = (
                    f"{ZOTERO_API_BASE}/users/{self._user_id}"
                    f"/collections/{ckey}/items"
                    f"?limit={limit}&start={start}"
                )
                async with session.get(url, headers=self._headers) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Zotero: 获取 collection items 失败 "
                            f"(status={resp.status}, start={start})"
                        )
                        break
                    batch = await resp.json()
                    if not batch:
                        break
                    all_items.extend(batch)
                    if len(batch) < limit:
                        break
                start += limit

        result = []
        for item in all_items:
            data = item.get("data", {})
            item_type = data.get("itemType", "")
            doi = data.get("DOI", "").strip()
            title = data.get("title", "")
            year = data.get("date", "")[:4] if data.get("date") else ""

            if not doi:
                continue

            result.append({
                "key": item.get("key", ""),
                "doi": doi,
                "title": title,
                "item_type": item_type,
                "year": year,
            })

        logger.info(
            f"Zotero: litcall 集合共 {len(result)} 个条目 "
            f"(总获取 {len(all_items)} 个)"
        )
        return result

    # ═══════════════════════════════════════════════════════════════
    # PDF 获取 — 按 item key（litcall 专属）
    # ═══════════════════════════════════════════════════════════════

    def _get_local_storage_base(self) -> Optional[Path]:
        """获取 Zotero 本地存储根目录。"""
        base = config.get("zotero", {}).get("storage_path", "")
        if base:
            p = Path(base)
            if p.exists():
                return p

        home = Path(os.path.expanduser("~"))
        candidates = [
            home / "Zotero" / "storage",
            home / "zotero" / "storage",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    async def find_pdf_for_item(
        self, item_key: str, output_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """给定 Zotero item key，找到其 PDF 附件并拷贝到 output_dir。

        不按 DOI 全局搜索 —— 直接按 item_key 查 children，
        确保只处理 litcall 集合内的文献。

        流程:
        1. GET /items/{key}/children → 找 contentType=="application/pdf"
        2. 优先从本地 Zotero storage 拷贝
        3. 备选从父条目 storage 目录找 .pdf
        4. 兜底 API 下载

        Returns:
            拷贝后的 PDF 路径，失败返回 None。
        """
        from litcall.core.paths import PDF_DIR

        output_dir = output_dir or PDF_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: 查找 PDF attachment
                children_url = (
                    f"{ZOTERO_API_BASE}/users/{self._user_id}"
                    f"/items/{item_key}/children"
                )
                async with session.get(
                    children_url, headers=self._headers
                ) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Zotero: 获取 children 失败 "
                            f"(key={item_key}, status={resp.status})"
                        )
                        return None
                    children = await resp.json()

                pdf_attachment = None
                for child in children:
                    cdata = child.get("data", {})
                    if cdata.get("contentType") == "application/pdf":
                        pdf_attachment = child
                        break

                storage_base = self._get_local_storage_base()

                # Step 2: 从本地 Zotero storage 拷贝（按 attach_key）
                if pdf_attachment:
                    attach_key = pdf_attachment["key"]
                    attach_filename = pdf_attachment.get("data", {}).get(
                        "filename", f"{item_key}.pdf"
                    )
                    output_path = output_dir / attach_filename

                    if storage_base:
                        local_dir = storage_base / attach_key
                        if local_dir.exists():
                            for f in local_dir.iterdir():
                                if f.suffix.lower() == ".pdf":
                                    shutil.copy2(f, output_path)
                                    logger.info(
                                        f"Zotero: 从本地 storage 拷贝 PDF "
                                        f"({output_path.stat().st_size} bytes): "
                                        f"{output_path.name}"
                                    )
                                    return output_path

                # Step 3: 从父条目 storage 目录找（无 attachment 或本地无文件）
                if storage_base:
                    parent_dir = storage_base / item_key
                    if parent_dir.exists():
                        for f in parent_dir.iterdir():
                            if f.suffix.lower() == ".pdf":
                                output_path = output_dir / f.name
                                shutil.copy2(f, output_path)
                                logger.info(
                                    f"Zotero: 从父条目 storage 拷贝 PDF "
                                    f"({output_path.stat().st_size} bytes): "
                                    f"{output_path.name}"
                                )
                                return output_path

                # Step 4: API 下载
                if pdf_attachment:
                    attach_key = pdf_attachment["key"]
                    logger.info(
                        f"Zotero: 本地无 PDF，尝试 API 下载 "
                        f"(item={item_key}, attach={attach_key})"
                    )
                    download_url = (
                        f"{ZOTERO_API_BASE}/users/{self._user_id}"
                        f"/items/{attach_key}/file"
                    )
                    async with session.get(
                        download_url, headers=self._headers
                    ) as resp:
                        if resp.status != 200:
                            logger.error(
                                f"Zotero: PDF API 下载失败: {resp.status}"
                            )
                            return None
                        pdf_data = await resp.read()
                        output_path = output_dir / attach_filename
                        output_path.write_bytes(pdf_data)
                        logger.info(
                            f"Zotero: PDF API 下载成功 "
                            f"({len(pdf_data)} bytes): {output_path.name}"
                        )
                        return output_path

                logger.warning(
                    f"Zotero: item {item_key} 无 PDF 附件且本地无缓存"
                )
                return None

        except Exception as e:
            logger.error(f"ZoteroStore.find_pdf_for_item 失败: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # AbstractStore 接口
    # ═══════════════════════════════════════════════════════════════

    async def write(self, paper: PaperData) -> bool:
        """创建 Zotero 条目 + 上传 PDF 附件。

        铁律 #11: 只传 DOI + PDF。元数据由 Zotero 通过 Crossref 自行获取。
        DOI 已存在时跳过创建（防止重复条目）。
        """
        try:
            ckey = await self._get_collection_key()
            if not ckey:
                logger.error("Zotero: 无法获取 collection key")
                return False

            async with aiohttp.ClientSession() as session:
                # Step 0: 全局去重 — 故意查全库（非 litcall 限定）
                # 避免在 Zotero 中创建重复条目；已存在则仅加入 litcall 集合
                ndoi = norm_doi(paper.doi)
                items = await self._list_recent_articles(session)
                for item in items:
                    if norm_doi(item.get("data", {}).get("DOI", "")) == ndoi:
                        existing_key = item["key"]
                        existing_cols = item.get("data", {}).get("collections", [])
                        if ckey not in existing_cols:
                            coll_url = (
                                f"{ZOTERO_API_BASE}/users/{self._user_id}"
                                f"/items/{existing_key}"
                            )
                            coll_data = json.dumps({
                                "collections": existing_cols + [ckey]
                            })
                            async with session.patch(
                                coll_url, headers=self._headers, data=coll_data
                            ) as resp:
                                if resp.status in (200, 204):
                                    logger.info(
                                        f"Zotero: DOI 已存在 {existing_key}，"
                                        f"已加入 collection"
                                    )
                        paper.zotero_item_key = existing_key
                        logger.info(
                            f"Zotero: DOI {paper.doi} 已存在 "
                            f"({existing_key})，跳过创建"
                        )
                        return True

                # Step 1: 创建条目（只传 DOI）
                item_url = f"{ZOTERO_API_BASE}/users/{self._user_id}/items"
                item_data = json.dumps([{
                    "itemType": "journalArticle",
                    "DOI": paper.doi,
                    "collections": [ckey],
                }])
                async with session.post(
                    item_url, headers=self._headers, data=item_data
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"Zotero 创建条目失败: {resp.status}")
                        return False
                    result = await resp.json()
                    item_key = result.get("success", {}).get("0", "")
                    if not item_key:
                        logger.error("Zotero 创建条目未返回 key")
                        return False

                paper.zotero_item_key = item_key
                logger.info(f"Zotero: 创建条目 {item_key} (DOI: {paper.doi})")

                # Step 2: 上传 PDF 附件
                if paper.pdf_path and Path(paper.pdf_path).exists():
                    if not await self._upload_file(
                        session, item_key, Path(paper.pdf_path), ckey
                    ):
                        logger.warning(
                            f"Zotero PDF 上传失败: {paper.pdf_path}"
                        )

                await asyncio.sleep(3)
                return True
        except Exception as e:
            logger.error(f"ZoteroStore.write 失败: {e}")
            return False

    async def verify(self, doi: str) -> VerifyResult:
        """验证 DOI 是否在 litcall 集合中（铁律: 只查 litcall 集合）。"""
        if not doi:
            return VerifyResult(
                store_name=self.name, ok=False, detail="DOI 为空"
            )

        ndoi = norm_doi(doi)
        try:
            async with aiohttp.ClientSession() as session:
                items = await self._list_collection_articles(session)
                for item in items:
                    item_doi = norm_doi(
                        item.get("data", {}).get("DOI", "")
                    )
                    if item_doi == ndoi:
                        return VerifyResult(
                            store_name=self.name, ok=True,
                            found_doi=ndoi,
                            found_title=item.get("data", {}).get("title", ""),
                        )
                return VerifyResult(
                    store_name=self.name, ok=False,
                    detail=f"DOI {ndoi} 不在 Zotero 中",
                )
        except Exception as e:
            return VerifyResult(
                store_name=self.name, ok=False,
                detail=f"验证异常: {e}",
            )

    async def delete(self, doi: str) -> bool:
        """删除 Zotero litcall 集合中的条目（铁律: 只动 litcall 集合）。"""
        ndoi = norm_doi(doi)
        try:
            async with aiohttp.ClientSession() as session:
                items = await self._list_collection_articles(session)
                for item in items:
                    if norm_doi(item.get("data", {}).get("DOI", "")) == ndoi:
                        ikey = item["key"]
                        version = item["version"]
                        headers = {
                            **self._headers,
                            "If-Unmodified-Since-Version": str(version),
                        }
                        url = (
                            f"{ZOTERO_API_BASE}/users/{self._user_id}"
                            f"/items/{ikey}"
                        )
                        async with session.delete(
                            url, headers=headers
                        ) as resp:
                            if resp.status == 204:
                                logger.info(f"ZoteroStore: 删除条目 {ikey}")
                                return True
                            logger.warning(
                                f"Zotero DELETE 失败: {resp.status}"
                            )
                        break
                return False
        except Exception as e:
            logger.error(f"ZoteroStore.delete 失败: {e}")
            return False

    def count(self) -> int:
        return len(self.list_dois())

    def list_dois(self) -> Set[str]:
        try:
            return asyncio.get_event_loop().run_until_complete(
                self._list_dois_async()
            )
        except RuntimeError:
            return asyncio.run(self._list_dois_async())

    async def _list_dois_async(self) -> Set[str]:
        """列出 litcall 集合中的所有 DOI（铁律: 只查 litcall 集合）。"""
        try:
            items = await self.list_collection_items()
            return {norm_doi(i.get("doi", "")) for i in items if i.get("doi")}
        except Exception:
            return set()

    # ═══════════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════════

    async def _list_collection_articles(
        self, session: aiohttp.ClientSession
    ) -> List[Dict]:
        """列出 litcall 集合中的所有 Zotero 条目（复用已有 session）。

        铁律: 只查 litcall 集合，不动用户其他文献。
        用于 verify/delete 等需要遍历条目的场景。
        """
        items = []
        ckey = await self._get_collection_key()
        if not ckey:
            return items
        start = 0
        limit = 100
        while True:
            url = (
                f"{ZOTERO_API_BASE}/users/{self._user_id}"
                f"/collections/{ckey}/items"
                f"?limit={limit}&start={start}"
            )
            async with session.get(url, headers=self._headers) as resp:
                if resp.status != 200:
                    break
                batch = await resp.json()
                if not batch:
                    break
                items.extend(batch)
                if len(batch) < limit:
                    break
            start += limit
        return items

    async def _list_recent_articles(
        self, session: aiohttp.ClientSession, limit: int = 2000
    ) -> List[Dict]:
        """列出全部 journalArticle 条目（不限 collection）。

        注意: 仅 write() 的全局去重使用此方法。
        其他场景（verify, delete, list_dois, count）一律用 litcall 限定方法。
        """
        items = []
        start = 0
        while start < limit:
            batch_size = min(100, limit - start)
            url = (
                f"{ZOTERO_API_BASE}/users/{self._user_id}/items"
                f"?itemType=journalArticle&limit={batch_size}&start={start}"
                f"&sort=dateAdded&direction=desc"
            )
            async with session.get(url, headers=self._headers) as resp:
                if resp.status != 200:
                    break
                batch = await resp.json()
                if not batch:
                    break
                items.extend(batch)
                if len(batch) < batch_size:
                    break
            start += batch_size
        return items

    async def _upload_file(
        self, session: aiohttp.ClientSession,
        parent_key: str, pdf_path: Path, collection_key: str,
    ) -> bool:
        """上传 PDF 文件到 Zotero 附件（四步流程）。

        1. 创建 attachment 子条目
        2. 请求上传授权
        3. POST 文件到 Zotero 存储
        4. 注册上传完成
        """
        try:
            file_size = pdf_path.stat().st_size
            file_mtime = int(pdf_path.stat().st_mtime * 1000)
            file_md5 = hashlib.md5(pdf_path.read_bytes()).hexdigest()

            # Step 1: 创建 attachment 子条目
            attach_url = (
                f"{ZOTERO_API_BASE}/users/{self._user_id}"
                f"/items/{parent_key}/children"
            )
            attach_data = json.dumps([{
                "itemType": "attachment",
                "parentItem": parent_key,
                "title": pdf_path.name,
                "contentType": "application/pdf",
                "filename": pdf_path.name,
            }])
            async with session.post(
                attach_url, headers=self._headers, data=attach_data
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Zotero: 创建附件失败: {resp.status}")
                    return False
                result = await resp.json()
                attach_key = result.get("success", {}).get("0", "")
                if not attach_key:
                    logger.error("Zotero: 创建附件未返回 key")
                    return False

            # Step 2: 请求上传授权
            auth_url = (
                f"{ZOTERO_API_BASE}/users/{self._user_id}"
                f"/items/{attach_key}/file"
            )
            auth_headers = {
                **self._headers,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            auth_body = (
                f"md5={file_md5}"
                f"&filename={pdf_path.name}"
                f"&filesize={file_size}"
                f"&mtime={file_mtime}"
            )
            async with session.post(
                auth_url, headers=auth_headers, data=auth_body
            ) as resp:
                if resp.status not in (200, 201):
                    logger.error(f"Zotero: 上传授权失败: {resp.status}")
                    return False
                auth = await resp.json()

            upload_url = auth.get("url")
            upload_params = auth.get("params", {})
            upload_token = auth.get("upload", auth.get("uploadToken", ""))

            if upload_url:
                # Step 3: 上传文件到存储后端
                with open(pdf_path, "rb") as f:
                    form_data = aiohttp.FormData()
                    for key, val in upload_params.items():
                        form_data.add_field(key, val)
                    form_data.add_field(
                        "file", f, filename=pdf_path.name,
                        content_type="application/pdf"
                    )
                    async with session.post(upload_url, data=form_data) as resp:
                        if resp.status not in (200, 201, 204):
                            logger.error(
                                f"Zotero: 文件上传失败: {resp.status}"
                            )
                            return False

            # Step 4: 注册上传完成
            if upload_token:
                register_url = (
                    f"{ZOTERO_API_BASE}/users/{self._user_id}"
                    f"/items/{attach_key}/file"
                )
                register_headers = {
                    **self._headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                register_body = f"upload={upload_token}"
                async with session.post(
                    register_url, headers=register_headers, data=register_body
                ) as resp:
                    if resp.status not in (200, 204):
                        logger.warning(
                            f"Zotero: 上传注册失败: {resp.status}"
                        )

            logger.info(
                f"Zotero: PDF uploaded ({file_size} bytes): {pdf_path.name}"
            )
            return True

        except Exception as e:
            logger.error(f"Zotero _upload_file: {e}")
            return False
