# ATHENA — Architecture & Design

> Key design decisions, data flow, and trade-offs behind the ATHENA literature agent.

---

## Data Flow

```
 VPN检测 (Phase 0)
      │
      ▼
 SPIS 检索 (Phase 1)
   ├─ 24 组关键词迭代
   ├─ 关键词游标 → 断点续传
   ├─ 翻页 → 年份过滤 → 期刊白名单
   ├─ 三重去重 (DOI + 标题 + Zotero)
   └─ 满 5 篇 / 关键词穷尽 → 停止
      │
      ▼
 深度阅读 (Phase 2)
   ├─ 扫描 新论文待处理/*.pdf
   ├─ PyMuPDF 提取全文 + 图表
   ├─ DeepSeek V4 Pro → 13 字段结构化笔记
   ├─ 自检 (幻觉检测 + 变量交叉校验)
   ├─ Gemini Vision → 图表描述
   ├─ Obsidian 笔记 + 知识图谱链接
   ├─ Zotero API 创建条目 + 上传 PDF
   └─ Excel 追加行
      │
      ▼
 索引同步 (Phase 3)
   ├─ 重建论文搜索索引
   ├─ 刷新 Streamlit 仪表盘数据
   └─ 生成运行简报
```

---

## IPC: Signal File Mechanism

Streamlit (Web) and Worker (subprocess) communicate via files:

```
Streamlit UI              Worker 进程
    │                        │
    ├─ 写 .pause  ──────────►├─ _check_signal_files() 检测
    │                        ├─ 阻塞轮询 (1s interval)
    │                        │
    ├─ 删 .pause ───────────►├─ 轮询发现 .pause 消失
    │                        └─ 继续执行
    │
    ├─ 写 .terminate ───────►├─ _check_signal_files() 检测
    │                        └─ raise AgentSignalError → 优雅退出
```

**Design trade-off**: Checkpoints at page/keyword/phase boundaries (not mid-operation). This prevents leaving the browser or network connection in an inconsistent state, at the cost of ~1 page of latency between "Pause clicked" and "Pause effective".

---

## Keyword Cursor State Machine

```
┌──────────┐   next_kw()   ┌──────────┐   next_kw()   ┌──────────┐
│  BROAD   │──────────────►│  NARROW  │──────────────►│ CHINESE  │
│  4 kws   │               │  10 kws  │               │  10 kws  │
└──────────┘               └──────────┘               └──────────┘
                                                           │
                                              全部穷尽 ─────┘
                                                           │
                                                           ▼
                                              通知用户 + 重置为仅检索当年
```

- Each keyword completion → atomic write cursor to `config.json` (temp file + rename)
- Crash-safe: cursor is always at or before the last completed keyword
- `keyword_override` bypasses cursor entirely (one-shot manual search)

---

## Deduplication Pipeline

```
新论文
  │
  ├─ Layer 1: DOI exact match (lowercase)
  │   data sources: Zotero API + processed_log.json + Excel
  │
  ├─ Layer 2: Title fuzzy match
  │   SequenceMatcher > 80% AND Jaccard > 50%
  │
  └─ Layer 3: Obsidian DOI scan (_find_obsidian_note_by_doi)
      prevents cross-language keyword duplicates
```

**Why Obsidian is not in Layer 1**: Obsidian sync can have stale/broken entries. Using it as primary dedup would propagate errors. Zotero is the authoritative source.

---

## Deep Reading Anti-Hallucination

```
┌─────────────────────────────────────────────────────┐
│  1. Prompt Discipline                               │
│     "只写原文明确出现的信息，不推断不编造"             │
│     "数字与原文严格一致 (n=207 就是 207)"              │
│     temperature=0.1, max_tokens=8192                │
├─────────────────────────────────────────────────────┤
│  2. Self-Check (lightweight 2nd API call)           │
│     - 变量汇总是否遗漏？(定量实证论文该有但为空？)      │
│     - 关键数字是否与原文一致？                         │
│     - 是否存在原文中没有的事实性陈述？                  │
│     - 失败不阻塞主流程，标记供人工复核                  │
├─────────────────────────────────────────────────────┤
│  3. Manual Review Queue (review_queue.json)         │
│     自检失败 → 加入人工复核队列 → UI 提示             │
└─────────────────────────────────────────────────────┘
```

---

## Bilingual Title Cleaning

SPIS returns titles with both Chinese and English (e.g., `"人工智能对消费者行为的影响研究 / The Impact of AI on Consumer Behavior"`). The cleaning logic:

```python
left, right = title.split(' / ')
if has_chinese(left) and not has_chinese(right):
    title = left   # Keep Chinese side
elif has_chinese(right) and not has_chinese(left):
    title = right  # Keep English side (unusual but handled)
```

Applied at three points: SPIS extraction, Obsidian note writing, and Zotero upload.

---

## Cross-Language Retrieval (Q&A)

```
用户问题 (中文)
    │
    ├─ 概念扩展: 100+ 中→英学术术语映射
    │   "人工智能信任" → "AI trust, artificial intelligence confidence..."
    │
    ├─ Token 匹配 (55% weight)
    │   ├─ 中文 bigram tokenization
    │   ├─ 英文 word tokenization
    │   └─ Weighted scoring: title×4 / keywords×3 / body×1.5 / journal×1
    │
    └─ Semantic Rerank (45% weight)
        ├─ Character 3-gram + 4-gram TF-IDF
        ├─ Cosine similarity (L2 normalized)
        └─ Language-agnostic (Chinese + English unified)
```

**Why not embeddings?** At 70 papers, character n-gram TF-IDF provides sufficient cross-language matching with zero additional dependencies. At 200+ papers, upgrade to embedding-based retrieval.

---

## Why Monolithic?

`literature_agent.py` is ~8500 lines in a single file. This is deliberate for the current stage:

| Factor | Monolith (current) | Modules (future) |
|--------|-------------------|-------------------|
| Shared state | All functions access config, logger, paths directly | Need dependency injection or singleton |
| Debugging | Single stack trace, no import issues | Cross-module traceback navigation |
| Circular imports | None | High risk with dense implicit dependency web |
| Web migration | N/A — Streamlit is already modularized in `app.py` | Future FastAPI/Chainlit migration will naturally force layering |

**The right time to split**: when migrating to a web framework that enforces separation (FastAPI routers, Chainlit hooks). The framework provides the layering structure, avoiding premature abstraction.

---

## External Services

| Service | API | Rate Limit | Cost |
|---------|-----|-----------|------|
| DeepSeek | chat/completions | 60 RPM | ~$0.01–0.03 per paper |
| Zotero | Web API v3 | None documented | Free |
| Gemini Vision | generateContent | 1500/day free | Free (within quota) |
| Unpaywall | /api/v1 | None (public) | Free |
| Semantic Scholar | /api/v1/paper | 100/5min | Free |
| OpenAlex | /works | None (public) | Free |

---

## Security Model

```
config.json (local, gitignored)  →  real API keys
config.example.json (committed)  →  placeholder values
.gitignore                       →  excludes config.json, logs, .claude/
```

All API keys are read from `config.json` at module load. No keys are hardcoded in source. The `.gitignore` is configured before the first commit — real credentials are never in Git history.
