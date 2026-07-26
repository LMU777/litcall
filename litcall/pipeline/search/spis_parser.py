"""
spis_parser.py — SPIS 列表页 & 详情页解析器
从 SPIS 搜索结果列表页提取文章元数据，从详情页获取完整标题/期刊/DOI/作者。

所有解析逻辑均为同步/异步无浏览器导航操作（只读 DOM）。
浏览器导航逻辑在 spis_browser.py 中。
"""

import asyncio
import logging
import random
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from litcall.core.config import config

logger = logging.getLogger(__name__)


# ============================================================================
# 辅助判断
# ============================================================================

def _looks_like_author(text: str) -> bool:
    """检测文本是否看起来像作者名而非期刊名。

    用于策略1/2的候选过滤，避免将"AK Pradeep, A Appel"或"P Gentsch -"误判为期刊。"""
    if not text:
        return True
    # 规则1: 3+逗号分隔 → 多作者列表（如 "Smith J, Wang L, Zhang K"）
    if text.count(",") >= 2 and not any(
        w.lower() in text.lower()
        for w in ["journal", "review", "research", "marketing", "management",
                   "science", "psychology", "quarterly", "studies", "annals",
                   "letters", "report", "bulletin", "ethics"]
    ):
        return True
    # 规则2: 以 " -" 结尾 → 作者名后跟破折号被截断（如 "P Gentsch -"）
    if text.rstrip().endswith(" -"):
        return True
    # 规则3: 单作者模式 "Initial Surname" 或 "Initials Surname"
    # 匹配像 "A Mari", "P Gentsch", "MA Upadhyay" 等单人作者
    stripped = text.rstrip().rstrip("-").strip()
    if re.match(r"^[A-Z][a-z]{0,2}\s+[A-Z][a-z]+\s*$", stripped):
        return True
    # 规则4: 逗号分隔的 "Initial Surname, Initial Surname" 模式
    parts = [p.strip() for p in stripped.split(",")]
    if len(parts) >= 2 and all(
        re.match(r"^[A-Z][a-z]{0,2}\s+[A-Z][a-z]+$", p) for p in parts
    ):
        return True
    return False


# ============================================================================
# 列表页解析
# ============================================================================

def parse_meta(raw_text: str) -> Tuple[str, str]:
    """多策略解析 SPIS 元数据行，提取期刊名和年份。

    核心改进（V6）：
    - 策略0（最高优先级）：直接在文本中搜索白名单期刊名，彻底绕开 SPIS 格式变异。
    - 策略1-3（回退）：正则提取，用于不在白名单中但仍可能有价值的期刊。
    - 通过白名单匹配来规避"提取到作者名而非期刊名"的经典误识别。"""
    from litcall.pipeline.search.journal_filter import _find_whitelist_journal_in_text

    if not raw_text:
        return "", ""
    text = unicodedata.normalize('NFKC', raw_text).replace("–", " - ").replace("—", " - ")

    # 提取年份（第一个 202x-203x）
    year = ""
    for m in re.finditer(r"\b(20\d\d)\b", text):
        year = m.group(1)
        break

    # ── 策略0（新增，最高优先级）：直接在文本中搜索白名单期刊名 ──
    # SPIS 常截断期刊名，且正则容易把作者名误判为期刊名。
    # 直接在原始文本中搜索白名单，如果找到则立即返回，无需依赖格式假设。
    journal = _find_whitelist_journal_in_text(text)
    if journal:
        return journal, year

    # ── 策略1: " - Journal Name, 2024" 或 " - Journal Name 2024" ──
    journal = ""
    m = re.search(r"\s[-–—]\s(.+?),?\s*20\d\d", text)
    if m:
        candidate = m.group(1).strip().rstrip("…").rstrip(".").rstrip(",").strip()
        # 二次校验：如果提取结果看起来不像期刊名（太短/像作者名），尝试白名单匹配
        if len(candidate) >= 3:
            resolved = _find_whitelist_journal_in_text(candidate)
            if resolved:
                return resolved, year
            # 防护：排除明显是作者名的候选
            if _looks_like_author(candidate):
                pass  # 看起来像作者名，不采用
            else:
                journal = candidate

    # ── 策略2: "Journal Name, 2024" 格式（无前导破折号）──
    if not journal or len(journal) < 5:
        m = re.search(r"^(.+?),?\s*20\d\d", text.strip())
        if m:
            candidate = m.group(1).strip().rstrip("…").rstrip(".").rstrip(",").strip()
            if len(candidate) > len(journal):
                # 防护：排除明显是作者名的候选（与策略1保持一致）
                if _looks_like_author(candidate):
                    pass  # 作者名，不采用
                else:
                    resolved = _find_whitelist_journal_in_text(candidate)
                    if resolved:
                        return resolved, year
                    journal = candidate

    # ── 策略3: 从括号中提取 ──
    if not journal or len(journal) < 5:
        m = re.search(r"[\(（]([^)）]{5,80})[\)）]", text)
        if m:
            candidate = m.group(1).strip().rstrip("…").rstrip(".").rstrip(",").strip()
            if len(candidate) > len(journal):
                resolved = _find_whitelist_journal_in_text(candidate)
                if resolved:
                    return resolved, year
                journal = candidate

    # 清理：移除首尾的省略号、逗号、句号、空白
    journal = re.sub(r"^[…\.\s]+", "", journal)
    journal = re.sub(r"[,\.…\s]+$", "", journal)

    return journal, year


async def scrape_page(page) -> List[Dict[str, str]]:
    """从 SPIS 搜索结果列表页抓取所有 article 元素，返回文章元数据列表。"""
    from litcall.pipeline.search.journal_filter import (
        journal_in_whitelist,
        _find_whitelist_journal_in_text,
        _resolve_truncated_journal,
    )

    articles = []
    article_els = await page.query_selector_all("article.article")
    for art in article_els:
        title = ""
        for sel in ["div.d-t.jump", "div.allow-ai", "div.jump", "div[title]"]:
            el = await art.query_selector(sel)
            if el:
                title = (await el.get_attribute("title") or "").strip()
                if not title:
                    title = (await el.inner_text()).strip()
                if title:
                    break
        if not title:
            continue

        # ── 标题清洗 ──
        # 1. 去掉 SPIS 序号前缀（"1、", "24、", "29、" 等）
        title = re.sub(r'^\d+[、.．]\s*', '', title)
        # 2. 去掉末尾的省略号和多余空白（但保留用于检测截断）
        title_raw = title  # 保存原始版本用于截断检测
        title = title.rstrip("…。.，, \t")
        # 3. 尝试从 <a> 标签 title 属性获取更完整的标题（SPIS 显示可能截断）
        a_els = await art.query_selector_all("a")
        for a_el in a_els:
            a_title = (await a_el.get_attribute("title") or "").strip()
            a_text = (await a_el.inner_text()).strip()
            # 如果有完整标题且比当前标题更长（去序号前缀后），采用之
            for candidate in [a_title, a_text]:
                clean_candidate = re.sub(r'^\d+[、.．]\s*', '', candidate).rstrip("…。.，, \t")
                if clean_candidate and len(clean_candidate) > len(title):
                    # 候选标题应该包含原标题的核心词（避免匹配到无关文本）
                    if len(title) < 20 or title[:20] in clean_candidate:
                        title = clean_candidate
                        break

        if not title:
            continue

        # ── 增强标题清洗（V11）──
        # 4. 去除尾部作者混入模式
        #    "Title: X. Wang et al" → "Title"
        #    "Title - Author Name, Author Name" → "Title"
        title = re.sub(r'\s*[:：]\s*[A-Z][.\s]*[A-Za-z]+(?:\s+et\s+al\.?)?\s*$', '', title)
        title = re.sub(r'\s*[-–—]\s*[A-Z][a-z]+\s+[A-Z][a-z]+.*$', '', title)
        # 5. 去除括号内的作者年份引用 "(Smith 2024)" 或 "(Wang et al. 2023)"
        title = re.sub(r'\s*[\(（]\s*[A-Z][a-z]+(?:\s+et\s+al\.?)?\s*,?\s*\d{4}\s*[\)）]\s*$', '', title)
        # 6. 如果标题以省略号开头（SPIS严重截断），标记为残缺
        is_garbled = title_raw.startswith("…") or title_raw.startswith("...") or title.startswith("…")

        # 主路径：div.d-a 文本
        meta_el = await art.query_selector("div.d-a")
        meta_text = await meta_el.inner_text() if meta_el else ""
        journal, year = parse_meta(meta_text)

        # 备选路径：当解析不到期刊名时，尝试从 <a> 标签 href/title 提取
        if not journal or len(journal) < 4:
            a_els = await art.query_selector_all("a")
            for a_el in a_els:
                href = (await a_el.get_attribute("href") or "").strip()
                a_title = (await a_el.get_attribute("title") or "").strip()
                a_text = (await a_el.inner_text()).strip()
                for candidate in [a_title, a_text]:
                    if candidate and len(candidate) > 4 and not candidate.startswith("http"):
                        j2, y2 = parse_meta(candidate)
                        if j2 and len(j2) >= len(journal):
                            journal = j2
                        if y2 and not year:
                            year = y2

        # 备选路径2：从 article 全文提取
        if not journal or len(journal) < 4:
            full_text = await art.inner_text()
            # 在全文前 200 字符中寻找可能含期刊名的行
            lines = full_text.split("\n")
            for line in lines[:5]:
                j3, y3 = parse_meta(line)
                if j3 and len(j3) > len(journal):
                    journal = j3
                if y3 and not year:
                    year = y3

        doi = ""
        doi_el = await art.query_selector("a[href*='doi.org']")
        if doi_el:
            doi = (await doi_el.get_attribute("href") or "").strip()
        if not doi:
            full_text = await art.inner_text()
            m = re.search(r"(10\.\d{4,}/[^\s]+)", full_text)
            if m:
                doi = m.group(1).strip()

        # ── 期刊名白名单匹配与补全 ──
        # 如果正则提取没有得到期刊名，或提取结果不在白名单中，
        # 则搜索 article 全文来查找白名单期刊名。
        # 这能解决 SPIS 截断/格式异化导致的"作者名被误判为期刊名"问题。
        if not journal or not journal_in_whitelist(journal):
            # 从 article 全文（前 500 字符足够包含期刊元数据）搜索白名单期刊
            full_text = await art.inner_text()
            found = _find_whitelist_journal_in_text(full_text[:500])
            if found:
                logger.debug(f"全文搜索补全期刊: '{journal}' → '{found}'")
                journal = found
                # 如果还没年份，尝试从全文提取
                if not year:
                    _, year = parse_meta(full_text[:200])

        # ── 期刊白名单过滤（V12：放宽，截断刊名不再直接过滤）──
        # 策略：先尝试补全截断刊名 → 白名单匹配 → 模糊通过 → 最后才过滤
        if journal and not journal_in_whitelist(journal):
            # 尝试补全截断的期刊名
            resolved = _resolve_truncated_journal(journal)
            if resolved:
                logger.debug(f"列表页期刊补全: '{journal}' → '{resolved}'")
                journal = resolved

        if journal and not journal_in_whitelist(journal):
            # 刊名不在白名单 → 判断是否看起来像正经学术期刊（非会议/非垃圾）
            j_lower = journal.lower().strip()
            j_words = j_lower.split()
            is_likely_journal = (
                len(j_words) >= 3  # >=3 词：通常是完整期刊名
                and not any(w in j_lower for w in [
                    "conference", "proceedings", "symposium", "workshop",
                    "preprint", "archive", "arxiv", "ssrn",
                    "procedia", "ieee", "lecture notes",
                ])
                and not j_lower.startswith("advances in")  # 很多垃圾刊以这个开头
            )
            if is_likely_journal:
                # 看起来像正经期刊，放行 → 详情页补全时会获取完整刊名
                logger.info(f"⚠ [待确认] {title[:50]} | 期刊待详情页确认: {journal}")
            else:
                logger.info(f"✗ [过滤] {title[:50]} | 期刊不在白名单: {journal}")
                continue
        if not journal:
            # 诊断日志：打印原始元数据文本，定位 parse_meta 失败原因
            full_diag = await art.inner_text()
            logger.warning(f"✗ [空期刊] {title[:50]} | 无法识别期刊名，跳过")
            logger.warning(f"  >>> div.d-a 原始文本: {repr(meta_text[:300])}")
            logger.warning(f"  >>> article 全文(前300字符): {repr(full_diag[:300])}")
            continue
        if year:
            min_year = config.get("min_year", 2023)
            if int(year) < min_year:
                logger.info(f"✗ [过滤] {title[:50]} | 年份过旧: {year}")
                continue
        else:
            if journal:  # 有期刊但无年份，同样诊断
                full_diag = await art.inner_text()
                logger.warning(f"⚠ [空年份] {title[:50]} | 无法识别年份")
                logger.warning(f"  >>> div.d-a 原始文本: {repr(meta_text[:300])}")
                logger.warning(f"  >>> article 全文(前300字符): {repr(full_diag[:300])}")

        log_prefix = "⚠ [残缺]" if is_garbled else "✓ [通过]"
        logger.info(f"{log_prefix} {title[:80]} | {journal} | {year}")
        articles.append({
            "title": title,
            "journal": journal,
            "year": year,
            "doi": doi,
            "is_garbled": is_garbled,  # 标记严重截断，供后续优先补全
        })
    return articles


# ============================================================================
# 详情页解析
# ============================================================================

async def _extract_from_detail(page, result: Dict[str, str]):
    """从 SPIS 详情页提取完整元数据，原地写入 result dict。

    基于 SPIS 真实 DOM 结构（V12）：
      - 标题: a.article-title 的 title 属性（完整标题，非视觉截断）
      - 期刊: div.summary-label"来源：" → 相邻 a.jump-link 的 title
      - DOI:  div.summary-label"DOI：" → 相邻 a.jump-link 的 title/href
      - 年份: 来源行内的 <span>
    """
    from litcall.pipeline.search.journal_filter import (
        journal_in_whitelist,
        _find_whitelist_journal_in_text,
        _resolve_truncated_journal,
    )

    old_title = result.get("title", "")

    # 等待 React 渲染
    try:
        await page.wait_for_function(
            """() => {
                const root = document.getElementById('root');
                return root && root.innerText.trim().length > 50;
            }""",
            timeout=15000
        )
    except Exception:
        pass
    await asyncio.sleep(1.0)

    try:
        full_text = await page.inner_text("body")
    except Exception:
        return

    # ── 1. 提取完整标题（V12：优先用 title 属性而非 inner_text）──
    title = ""
    title_el = await page.query_selector("a.article-title")
    if title_el:
        # title 属性包含 SPIS 完整标题（inner_text 可能被视觉截断）
        attr_title = (await title_el.get_attribute("title") or "").strip()
        inner_title = (await title_el.inner_text()).strip()
        # 取两者中较长者（title 属性通常更完整）
        if attr_title and len(attr_title) > 15:
            title = attr_title
            logger.info(f"  [诊断] a.article-title[title] → {title[:120]}")
        elif inner_title and len(inner_title) > 15:
            title = inner_title
            logger.info(f"  [诊断] a.article-title[innerText] → {title[:120]}")

    # 回退：其他选择器
    if not title or len(title) < 15:
        for sel in ["h1", ".paper-title", "[class*='detailTitle']", "[class*='paperTitle']",
                     "[class*='title']", ".detail-title", "h2"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    t = (await el.get_attribute("title") or "").strip()
                    if not t or len(t) < 15:
                        t = (await el.inner_text()).strip()
                    if t and len(t) > 15:
                        title = t
                        logger.info(f"  [诊断] 回退选择器 {sel} → {t[:120]}")
                        break
            except Exception:
                continue

    # 最终回退：#root 第一行长文本
    if not title or len(title) < 15:
        try:
            root_text = await page.evaluate("() => document.getElementById('root')?.innerText || ''")
            lines = [l.strip() for l in root_text.split("\n") if len(l.strip()) > 20]
            if lines:
                title = lines[0]
                logger.info(f"  [诊断] #root首行 → {title[:120]}")
        except Exception:
            pass

    if not title or len(title) < 10:
        logger.info(f"  [诊断] 未能提取到有效标题")
        return

    # ── 标题清洗 ──
    title = re.sub(r'^\d+[、.．]\s*', '', title).strip()
    title = re.sub(r'\s*[:：\-–—]\s*[A-Z][.\s]*[A-Za-z]+(?:\s+et\s+al\.?)?\s*$', '', title)
    title = re.sub(r'\s*[-–—]\s*\d{4}\s*$', '', title)
    title = re.sub(r'\s*[:：]\s*[A-Z]\.\s*\w+(?:\s+(?:and|&)\s+[A-Z]\.\s*\w+)?\s*$', '', title)

    # ── 双语标题清洗：保留中文，剥离英文翻译 ──
    # SPIS 对中文论文常显示 "中文标题 / English Title"
    # 检测 "/ " 两侧语言，保留中文侧
    if ' / ' in title:
        parts = title.split(' / ')
        if len(parts) == 2:
            left, right = parts
            left_has_cn = bool(re.search(r'[一-鿿]', left))
            right_has_cn = bool(re.search(r'[一-鿿]', right))
            if left_has_cn and not right_has_cn:
                title = left  # "中文 / English" → 保留中文
                logger.info(f"  [标题清洗] 剥离英文翻译: {title[:80]}")
            elif right_has_cn and not left_has_cn:
                title = right  # "English / 中文" → 保留中文
                logger.info(f"  [标题清洗] 剥离英文前缀: {title[:80]}")

    if title.startswith("…") or title.startswith("..."):
        core = title.lstrip("…。.，, \t")
        if len(core) > 10:
            for line in full_text.split("\n"):
                line_clean = line.strip()
                if core[:30] in line_clean and len(line_clean) > len(title):
                    title = line_clean
                    logger.info(f"  [诊断] 省略号标题补全: {title[:120]}")
                    break

    # ── 安全校验 ──
    title_lower = title.lower()
    old_lower = old_title.lower().rstrip("…。.，, \t")

    is_truncated = (old_lower.startswith("…") or old_lower.endswith("…") or len(old_lower) < 25)
    is_partial = old_lower.startswith("…") and len(old_lower) > 10

    old_words = set(old_lower.split())
    new_words = set(title_lower.split())
    word_overlap = len(old_words & new_words) / max(len(old_words), 1) if old_words else 0

    old_words_list = old_lower.split()
    if len(old_words_list) >= 3:
        old_without_last_2 = " ".join(old_words_list[:-2])
        substr_match = old_without_last_2 in title_lower if len(old_without_last_2) >= 15 else False
    else:
        substr_match = old_lower[:20] in title_lower if len(old_lower) >= 15 else False

    is_related = substr_match or word_overlap > 0.6
    title_actually_changed = title != old_title

    if len(title) >= len(old_title) and title_actually_changed and \
       (is_truncated or is_partial or is_related or not old_title):
        result["title"] = title
        logger.info(f"  ✓ 标题补全: {title[:120]}")
    elif len(title) > len(old_title) and word_overlap > 0.4:
        result["title"] = title
        logger.info(f"  ✓ 标题补全(放宽): {title[:120]}")
    elif not title_actually_changed:
        logger.info(f"  [诊断] 标题已完整 (len={len(title)}), 无需补全")
    else:
        logger.info(f"  [诊断] 标题未替换: 新({len(title)})>旧({len(old_title)})?"
                    f"={len(title)>len(old_title)} 残缺={is_truncated} 词重叠={word_overlap*100:.0f}%")

    # ── 2. 提取期刊名（V13：label来源优先存储，白名单仅用于规范化大小写）──
    old_journal = result.get("journal", "")
    journal_found = False

    # 策略A：通过 "来源：" label 定位（SPIS 详情页 DOM 结构）
    source_journal_raw = ""  # label 提取的原始刊名
    try:
        source_link = await page.evaluate("""() => {
            const labels = document.querySelectorAll('.summary-label');
            for (const label of labels) {
                if (label.textContent.trim() === '来源：') {
                    const parent = label.closest('.item');
                    if (parent) {
                        const link = parent.querySelector('a.jump-link, a.default-text');
                        if (link) {
                            const title = link.getAttribute('title') || '';
                            if (title) return title.trim();
                            return link.textContent.trim();
                        }
                        const span = parent.querySelector('span');
                        if (span) return span.textContent.trim();
                    }
                }
            }
            return '';
        }""")
        if source_link and len(source_link) > 3:
            source_journal_raw = source_link.strip()
            # 优先在白名单中查找（获取规范大小写），找不到也保留原始文本
            j_from_source = _find_whitelist_journal_in_text(source_journal_raw)
            if j_from_source:
                result["journal"] = j_from_source
                journal_found = True
                logger.info(f"  ✓ 期刊补全(label来源): {j_from_source}")
            else:
                # 非白名单期刊也存储，label 来源是权威的
                # V14修复: 只要 label 提取到了有效刊名，就存储它。
                # 不再用 len() 比较——旧刊名可能更长但错误（被 _resolve_truncated_journal 猜错）。
                # label 提取的是 SPIS 详情页的真实刊名，优先级最高。
                result["journal"] = source_journal_raw
                journal_found = True
                logger.info(f"  ✓ 期刊补全(label来源,非白名单): {source_journal_raw}")
    except Exception as e:
        logger.debug(f"  期刊label提取异常: {e}")

    # 策略B：全文搜索白名单期刊名（仅在 label 未找到时）
    if not journal_found:
        found = _find_whitelist_journal_in_text(full_text)
        if not found:
            top_text = "\n".join(full_text.split("\n")[:30])
            found = _find_whitelist_journal_in_text(top_text)
        if found:
            if not old_journal or len(found) > len(old_journal) or not journal_in_whitelist(old_journal):
                result["journal"] = found
                journal_found = True
                logger.info(f"  ✓ 期刊补全(全文搜索): {found}")

    # 策略C：截断期刊名补全（仅当 label 和全文搜索均失败，且旧刊名明显截断）
    if not journal_found and old_journal and len(old_journal) < 30:
        partial = old_journal.strip().lower()
        if len(partial) >= 5:
            # 如果 label 提取到了原始文本但不在白名单，优先用它（而不是猜测）
            if source_journal_raw and len(source_journal_raw) > len(old_journal):
                result["journal"] = source_journal_raw
                journal_found = True
                logger.info(f"  ✓ 期刊补全(label原始): {source_journal_raw}")
            else:
                resolved = _resolve_truncated_journal(partial)
                if resolved:
                    result["journal"] = resolved
                    journal_found = True
                    logger.info(f"  ✓ 期刊补全(截断修复): {resolved}")

    # ── 3. 提取 DOI（V12：通过 "DOI：" label 定位）──
    if not result.get("doi"):
        doi_extracted = False
        try:
            doi_val = await page.evaluate("""() => {
                const labels = document.querySelectorAll('.summary-label');
                for (const label of labels) {
                    if (label.textContent.trim().startsWith('DOI')) {
                        const parent = label.closest('.item');
                        if (parent) {
                            const link = parent.querySelector('a.jump-link');
                            if (link) {
                                const title = link.getAttribute('title') || '';
                                if (title && title.includes('doi.org')) return title;
                                const href = link.getAttribute('href') || '';
                                if (href && href.includes('doi.org')) return href;
                                return link.textContent.trim();
                            }
                        }
                    }
                }
                return '';
            }""")
            if doi_val and "10." in doi_val:
                # 提取标准 DOI 格式
                m = re.search(r"(10\.\d{4,}/[^\s\"'<>；;，,]+)", doi_val)
                if m:
                    result["doi"] = m.group(1).rstrip(".,;)")
                    doi_extracted = True
                    logger.info(f"  ✓ DOI补全(label): {result['doi']}")
        except Exception as e:
            logger.debug(f"  DOI label提取异常: {e}")

        # 回退：全文正则匹配
        if not doi_extracted:
            m = re.search(r"(10\.\d{4,}/[^\s\"'<>；;，,]+)", full_text)
            if m:
                result["doi"] = m.group(1).rstrip(".,;)")
                doi_extracted = True
                logger.info(f"  ✓ DOI补全(正则): {result['doi']}")

    # ── 4. 提取年份（V12：来源行内 span）──
    if not result.get("year"):
        try:
            yr_val = await page.evaluate("""() => {
                const labels = document.querySelectorAll('.summary-label');
                for (const label of labels) {
                    if (label.textContent.trim() === '来源：') {
                        const parent = label.closest('.item');
                        if (parent) {
                            const spans = parent.querySelectorAll('span');
                            for (const span of spans) {
                                const t = span.textContent.trim();
                                if (/^20[2-9]\\d$/.test(t)) return t;
                            }
                            // 回退：匹配文本中的年份
                            const text = parent.textContent;
                            const m = text.match(/20[2-9]\\d/);
                            if (m) return m[0];
                        }
                    }
                }
                return '';
            }""")
            if yr_val and yr_val.isdigit() and 2020 <= int(yr_val) <= 2030:
                result["year"] = yr_val
                logger.info(f"  ✓ 年份补全: {yr_val}")
        except Exception:
            pass

    # ── 4. 提取年份（回退）──
    if not result.get("year"):
        for m in re.finditer(r"\b(20[2-9]\d)\b", full_text[:500]):
            yr = int(m.group(1))
            if 2020 <= yr <= 2030:
                result["year"] = str(yr)
                break

    # ── 5. 提取作者 ──
    if not result.get("authors") and not result.get("author"):
        try:
            authors = await page.evaluate("""() => {
                // 策略A：通过 "作者：" label 定位（与期刊/DOI提取一致）
                const labels = document.querySelectorAll('.summary-label');
                for (const label of labels) {
                    if (label.textContent.trim() === '作者：') {
                        const parent = label.closest('.item');
                        if (parent) {
                            // 作者可能在 a.jump-link 或 span 中
                            const links = parent.querySelectorAll('a.jump-link, a.default-text');
                            if (links.length > 0) {
                                return Array.from(links).map(l => l.textContent.trim()).join(', ');
                            }
                            const span = parent.querySelector('span');
                            if (span) return span.textContent.trim();
                            // 直接取父元素文本（去掉"作者："前缀）
                            const text = parent.textContent.trim();
                            return text.replace(/^作者：\\s*/, '');
                        }
                    }
                }
                // 策略B：查找含 "作者" 文本的任意元素
                const allEls = document.querySelectorAll('.item, .summary-item, [class*=\"author\"]');
                for (const el of allEls) {
                    const text = el.textContent.trim();
                    if (text.startsWith('作者：') || text.startsWith('作者:')) {
                        return text.replace(/^作者[：:]\\s*/, '');
                    }
                }
                return '';
            }""")
            if authors and len(authors) > 2:
                result["authors"] = authors.strip()
                result["author"] = authors.strip()  # 兼容两种 key
                logger.info(f"  ✓ 作者补全: {authors[:100]}")
        except Exception:
            pass


# ============================================================================
# 详情页下载链接检测 & 文献求助自动提交
# ============================================================================

async def _check_detail_download_url(tab) -> Optional[str]:
    """检测详情页是否有可用的下载链接。返回下载 URL 或 None。"""
    try:
        download_url = await tab.evaluate("""() => {
            // 方式1: 下载按钮中的链接
            const downloadBtn = document.querySelector('.action-button.download a');
            if (downloadBtn && downloadBtn.href) return downloadBtn.href;

            // 方式2: 下载地址卡片中的链接
            const downloadCard = document.querySelector('[id*="download-card"]');
            if (downloadCard) {
                const links = downloadCard.querySelectorAll('a.jump-link');
                for (const link of links) {
                    if (link.href && link.href.length > 20) return link.href;
                }
            }

            // 方式3: ResearchGate 等外部下载链接
            const cardContent = document.querySelector('.card-content');
            if (cardContent) {
                const links = cardContent.querySelectorAll('a');
                for (const link of links) {
                    if (link.href && (link.href.includes('researchgate') ||
                                      link.href.includes('.pdf') ||
                                      link.href.includes('download'))) {
                        return link.href;
                    }
                }
            }
            return '';
        }""")
        if download_url and len(download_url) > 10:
            return download_url.strip()
    except Exception:
        pass
    return None


async def _auto_submit_literature_help(tab, article: Dict[str, str], help_email: str) -> bool:
    """自动提交 SPIS 文献求助表单（邮箱已由系统预设，无需填写）。

    模拟真人操作节奏：慢速滚动 → 勾选条款 → 确认 → 等待。
    返回 True 表示提交成功，False 表示失败。
    """
    logger.info(f"  🔍 [文献求助] 开始自动提交: {article['title'][:60]}")

    try:
        # ── Step 1: 切换到「文献求助」tab ──
        help_tab_clicked = await tab.evaluate("""() => {
            const tabs = document.querySelectorAll('.ant-tabs-tab');
            for (const t of tabs) {
                if (t.textContent.includes('文献求助') || t.textContent.includes('help')) {
                    t.click();
                    return true;
                }
            }
            const cardTabs = document.querySelectorAll('[data-node-key="help-card"]');
            if (cardTabs.length > 0) { cardTabs[0].click(); return true; }
            return false;
        }""")
        if help_tab_clicked:
            logger.info("  ✓ 已点击「文献求助」tab")
        else:
            logger.warning("  ⚠ 未找到文献求助 tab，尝试继续...")
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # ── Step 2: 模拟真人滚动 ──
        await tab.evaluate("""() => {
            const d = 100 + Math.random() * 200;
            window.scrollBy({top: d, behavior: 'smooth'});
        }""")
        await asyncio.sleep(random.uniform(0.8, 1.5))

        # ── Step 3: 检查并填写邮箱（Playwright 逐字输入，模拟真人）──
        email_filled = False
        # 先诊断：打印页面上所有可见的 input 元素，方便定位
        try:
            diag_inputs = await tab.evaluate("""() => {
                const inputs = document.querySelectorAll('input:not([type="hidden"])');
                const result = [];
                inputs.forEach((inp, i) => {
                    if (inp.offsetParent !== null) {
                        result.push({
                            idx: i,
                            type: inp.type || 'text',
                            placeholder: inp.placeholder || '',
                            value: inp.value || '',
                            className: inp.className || '',
                            id: inp.id || '',
                            name: inp.name || '',
                            ariaLabel: inp.getAttribute('aria-label') || '',
                        });
                    }
                });
                return result;
            }""")
            if diag_inputs:
                logger.info(f"  [诊断] 页面上可见 input 共 {len(diag_inputs)} 个:")
                for inp in diag_inputs:
                    logger.info(f"    [{inp['idx']}] type={inp['type']} placeholder='{inp['placeholder']}' "
                                f"value='{inp['value'][:30]}' class='{inp['className'][:60]}' "
                                f"id='{inp['id']}' name='{inp['name']}'")
            else:
                logger.warning("  [诊断] 页面上没有可见的 input 元素")
        except Exception as e:
            logger.warning(f"  [诊断] input 诊断失败: {e}")

        # 宽泛查找邮箱输入框：遍历所有可见 input，找 type=email 或含"邮箱"/"email"属性的
        try:
            all_inputs = await tab.query_selector_all('input:not([type="hidden"])')
            for inp in all_inputs:
                try:
                    if not await inp.is_visible():
                        continue
                    inp_type = (await inp.get_attribute("type") or "").lower()
                    placeholder = (await inp.get_attribute("placeholder") or "").lower()
                    aria_label = (await inp.get_attribute("aria-label") or "").lower()
                    inp_name = (await inp.get_attribute("name") or "").lower()
                    inp_id = (await inp.get_attribute("id") or "").lower()
                    combined = f"{inp_type} {placeholder} {aria_label} {inp_name} {inp_id}"
                    current_val = (await inp.input_value()).strip()

                    # 已经预设了邮箱 → 跳过填写
                    if current_val and "@" in current_val:
                        logger.info(f"  ✓ 邮箱已预设: {current_val}")
                        email_filled = True
                        break

                    # 判断这行是否像邮箱输入框
                    is_email_field = (
                        inp_type == "email"
                        or "邮箱" in combined or "email" in combined or "mail" in combined
                        or "e-mail" in combined
                    )
                    if not is_email_field:
                        continue

                    # 已确认是邮箱字段 → 填写
                    if current_val:
                        logger.info(f"  [诊断] 邮箱字段当前值='{current_val}'（非邮箱格式），覆盖填写")

                    await inp.click()
                    await asyncio.sleep(random.uniform(0.2, 0.4))
                    await tab.keyboard.press("Control+a")
                    await asyncio.sleep(random.uniform(0.1, 0.2))
                    await tab.keyboard.type(help_email, delay=random.randint(60, 100))
                    logger.info(f"  ✓ 邮箱已逐字输入: {help_email}")
                    email_filled = True
                    break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"  [诊断] 输入框遍历异常: {e}")

        # 回退：直接定位包含"邮箱"文本的元素旁边的 input
        if not email_filled:
            try:
                fallback_filled = await tab.evaluate(f"""(email) => {{
                    // 策略1: 找包含"邮箱"文字的 label/div，再找相邻 input
                    const allEls = document.querySelectorAll('*');
                    for (const el of allEls) {{
                        if (el.children.length === 0 && el.textContent.trim() === '邮箱：') {{
                            // 向上找父容器，再找其中的 input
                            let parent = el.parentElement;
                            for (let i = 0; i < 5 && parent; i++) {{
                                const inp = parent.querySelector('input:not([type="hidden"])');
                                if (inp && inp.offsetParent !== null) {{
                                    inp.focus();
                                    inp.value = '';
                                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    // 模拟逐字输入
                                    const chars = email.split('');
                                    chars.forEach((ch, idx) => {{
                                        setTimeout(() => {{
                                            inp.value += ch;
                                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        }}, idx * 80);
                                    }});
                                    return true;
                                }}
                                parent = parent.parentElement;
                            }}
                        }}
                    }}
                    // 策略2: Ant Design Form.Item 里找
                    const formItems = document.querySelectorAll('.ant-form-item, .ant-row');
                    for (const item of formItems) {{
                        const label = item.querySelector('.ant-form-item-label label');
                        if (label && label.textContent.includes('邮箱')) {{
                            const inp = item.querySelector('input');
                            if (inp && inp.offsetParent !== null) {{
                                inp.focus();
                                inp.value = '';
                                const chars = email.split('');
                                chars.forEach((ch, idx) => {{
                                    setTimeout(() => {{
                                        inp.value += ch;
                                        inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    }}, idx * 80);
                                }});
                                return true;
                            }}
                        }}
                    }}
                    return false;
                }}""", help_email)
                if fallback_filled:
                    # setTimeout 方式不可靠，但回退策略至少尝试了
                    await asyncio.sleep(len(help_email) * 0.08 + 1.0)
                    logger.info(f"  ✓ 邮箱已填写(回退策略): {help_email}")
                    email_filled = True
            except Exception:
                pass

        if not email_filled:
            logger.warning("  ⚠ 未找到邮箱输入框，尝试继续（可能无需填写）...")
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # ── Step 4: 勾选《文献求助服务条款》──
        # 优先用 Playwright 原生点击（更真实），失败回退到 JS evaluate
        checkbox_checked = False
        try:
            cb_el = await tab.query_selector('.custom-checkbox-img:not(.checked)')
            if not cb_el:
                cb_el = await tab.query_selector('input[type="checkbox"]:not(:checked)')
            if cb_el and await cb_el.is_visible():
                await cb_el.click(delay=random.randint(100, 250))
                checkbox_checked = True
                logger.info("  ✓ 已勾选《文献求助服务条款》(原生点击)")
        except Exception:
            pass

        if not checkbox_checked:
            checkbox_checked = await tab.evaluate("""() => {
                const cbs = document.querySelectorAll('.custom-checkbox-img, input[type="checkbox"]');
                for (const cb of cbs) {
                    const p = cb.closest('.reason-checkbox') || cb.closest('label') || cb.parentElement;
                    const t = (p?.textContent || '').toLowerCase();
                    if (t.includes('条款') || t.includes('服务') || t.includes('agree') || t.includes('同意')) {
                        if (cb.classList?.contains('custom-checkbox-img') && !cb.classList.contains('checked')) { cb.click(); return true; }
                        if (cb.tagName === 'INPUT' && !cb.checked) { cb.click(); return true; }
                    }
                }
                for (const cb of cbs) {
                    if (cb.classList?.contains('custom-checkbox-img') && !cb.classList.contains('checked')) { cb.click(); return true; }
                    if (cb.tagName === 'INPUT' && !cb.checked) { cb.click(); return true; }
                }
                return false;
            }""")
        if checkbox_checked:
            logger.info("  ✓ 已勾选《文献求助服务条款》")
        else:
            logger.warning("  ⚠ 未找到服务条款复选框")
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # ── Step 5: 点击「确认」按钮（Playwright 原生优先）──
        confirm_clicked = False
        try:
            for btn_sel in ['button', '.ant-btn', '.modal-btn']:
                buttons = await tab.query_selector_all(btn_sel)
                for btn in buttons:
                    try:
                        text = (await btn.inner_text()).strip()
                        if text in ('确认', '提交', '确定') and await btn.is_visible():
                            # 先慢速移动到按钮（模拟鼠标轨迹）
                            box = await btn.bounding_box()
                            if box:
                                await tab.mouse.move(
                                    box['x'] + random.uniform(10, box['width'] - 10),
                                    box['y'] + random.uniform(5, box['height'] - 5),
                                    steps=random.randint(3, 8),
                                )
                                await asyncio.sleep(random.uniform(0.2, 0.5))
                            await btn.click(delay=random.randint(50, 150))
                            confirm_clicked = True
                            logger.info(f"  ✓ 已点击「{text}」按钮 (原生)")
                            break
                    except Exception:
                        continue
                if confirm_clicked:
                    break
        except Exception:
            pass

        if not confirm_clicked:
            confirm_clicked = await tab.evaluate("""() => {
                const btns = document.querySelectorAll('button, .ant-btn, .modal-btn');
                for (const b of btns) {
                    const t = b.textContent.trim();
                    if ((t === '确认' || t === '提交' || t === '确定') && b.offsetParent !== null) {
                        b.click(); return true;
                    }
                }
                return false;
            }""")
        if confirm_clicked:
            logger.info("  ✓ 已点击「确认」按钮")
        else:
            logger.warning("  ⚠ 未找到确认按钮")

        # ── Step 6: 等待提交完成 ──
        await asyncio.sleep(random.uniform(2.0, 3.5))

        # 检测成功提示
        success = await tab.evaluate("""() => {
            const b = document.body.innerText;
            return b.includes('成功') || b.includes('已提交') || b.includes('提交成功');
        }""")
        if success:
            logger.info(f"  ✓ [文献求助] 提交成功: {article['title'][:60]}")
        else:
            logger.info(f"  ✓ [文献求助] 已提交（等待确认）: {article['title'][:60]}")

        return True

    except Exception as e:
        logger.error(f"  ✗ [文献求助] 自动提交异常: {e}")
        return False


# ============================================================================
# 年份解析
# ============================================================================

def _parse_article_year(year_str: str, year_start: int, year_end: int) -> bool:
    """检查文章年份是否在目标范围内。"""
    if not year_str:
        return True  # 无年份信息 → 保留（后续人工判断）
    try:
        yr = int(str(year_str).strip()[:4])
        return year_start <= yr <= year_end
    except (ValueError, TypeError):
        return True  # 无法解析年份 → 保留
