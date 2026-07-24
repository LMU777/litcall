# 🦉 ATHENA — Academic Literature Agent for AI × Marketing

> **AI×Marketing 交叉领域的个人学术知识管理 Agent。自动检索、精读、入库，将每周 6–8 小时的人工文献工作压缩至 ~5 分钟。**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.60-FF4B4B?logo=streamlit)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## The Problem

AI×Marketing 交叉领域文献更新快、分散在多个付费数据库中。传统工作流：

```
打开 SPIS → 逐个关键词搜索 → 手动筛选年份/期刊 → 判断相关性
→ 下载 PDF → 阅读全文 → 手动做笔记 → 录入 Zotero → 整理 Excel...
```

每周耗时 **6–8 小时**，且容易遗漏高影响力期刊的最新论文。

## The Solution

ATHENA 将上述流程自动化，人工只需做一件事：**在 SPIS 上手动下载付费 PDF**（受限于机构付费墙）。

```
┌─────────────────────────────────────────────────────────────┐
│                     🦉 ATHENA Pipeline                       │
├──────────────┬──────────────────┬────────────────────────────┤
│   PHASE 0    │     PHASE 1      │     PHASE 2                │
│   VPN 检测   │   SPIS 文献检索   │   深度阅读 + 入库          │
│              │                  │                            │
│  自动检测    │  24 组中英关键词   │  DeepSeek V4 Pro 全文精读  │
│  湖南大学VPN │  60+ 期刊白名单    │  18 字段结构化笔记         │
│  5 分钟超时  │  年份过滤 + 去重   │  自检验证 + 图表提取       │
│              │  关键词游标续传   │  → Obsidian + Zotero       │
│              │                  │  → 知识图谱双向链接         │
├──────────────┴──────────────────┴────────────────────────────┤
│                     PHASE 3: 索引同步 + 问答就绪              │
└─────────────────────────────────────────────────────────────┘
```

## Features

### 🤖 Autonomous Agent
- **关键词游标**：24 组中英文关键词按宽→窄→中文三级迭代，每次运行收满 5 篇即停，游标跨会话持久化，断点续传
- **高级搜索**：支持自定义关键词、年份范围、期刊过滤、篇数/翻页数控制
- **运行控制**：Web 面板控制后台 Worker 进程的启动/暂停/恢复/终止（信号文件 IPC）

### 🔍 Smart Retrieval
- **三重去重**：DOI 精确匹配 + 标题模糊匹配 + Zotero 实时比对
- **双语清洗**：自动检测并剥离 SPIS 返回的中英双语标题中的英文翻译
- **期刊白名单**：60+ 顶刊覆盖（UTD24/FT50 全覆盖 + 营销+管理+心理扩展）
- **付费墙应对**：自动识别 OA 文献并下载，付费文献通过 SPIS 文献求助自动提交

### 📖 Deep Reading
- **18 字段结构化笔记**：研究背景→研究问题→变量汇总→研究方法→方法论详解→研究结果→讨论与结论→创新点→局限与展望→图表分析
- **反幻觉 Pipeline**：自检 + 变量交叉校验 + 人工复核队列
- **图表识别**：Gemini Vision API 提取 PDF 图表并嵌入笔记
- **关键纪律**：只写原文明确出现的信息，不推断不编造；数字与原文严格一致

### 🏗️ Knowledge Management
- **Obsidian 知识图谱**：双向链接 `[[概念]]`、年份/期刊分层目录、图表附件嵌入
- **Zotero 文献管理**：自动创建条目 + 上传 PDF 附件 + 同步确认
- **Excel 汇总表**：全量文献数据库，支持筛选/排序
- **教授级问答**：基于本地文献的混合检索（Token 匹配 + n-gram TF-IDF 语义），支持外部知识增强

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Browser Automation** | Playwright (persistent context) | SPIS 登录态保持 + 翻页抓取 |
| **AI / LLM** | DeepSeek V4 Pro API | 深度阅读 + 知识库问答 |
| | Gemini Vision API | PDF 图表识别 |
| **Frontend** | Streamlit | Web 控制面板 + 实时监控 |
| **Knowledge Base** | Obsidian (Markdown vault) | 文献笔记 + 知识图谱 |
| **Reference Manager** | Zotero API | 文献入库 + 去重 |
| **PDF Processing** | PyMuPDF (fitz) | 文本提取 + 图表提取 |
| **Data** | openpyxl, JSON | Excel 汇总 + 运行日志 |
| **IPC** | Signal files (.pause / .terminate) | Streamlit ↔ Worker 进程通信 |

## Project Structure

```
athena/
├── app.py                   # Streamlit Web 面板
├── literature_agent.py      # 核心引擎 (~8500 lines)
├── run_agent_worker.py      # CLI Worker 入口
├── config.example.json      # 配置模板（占位符）
├── requirements.txt         # Python 依赖
├── journal_if.json          # 影响因子库 (239 种期刊)
├── agent文献汇总.xlsx        # Excel 知识库
├── processed_log.json       # 已处理文献日志
│
├── agent抓取/               # Obsidian Vault
│   ├── _index.md            # 文献索引
│   ├── 2020/ ... 2026/      # 按年份 → 期刊分层
│   │   └── {journal}/
│   │       ├── {year}_{title}.md   # 18 字段精读笔记
│   │       └── attachments/        # PDF 图表
│   └── concepts/            # 概念节点（知识图谱）
│
├── 新论文待处理/             # PDF 暂存区
│   └── notes/               # JSON 笔记暂存
│
└── 运行日志/                 # AgentRunLogger JSON
    └── runs/                # 结构化运行日志
```

## Quick Start

### Prerequisites
- Python 3.10+
- Playwright Chromium: `python -m playwright install chromium`
- DeepSeek API Key ([platform.deepseek.com](https://platform.deepseek.com))
- Zotero API Key ([zotero.org/settings/keys](https://www.zotero.org/settings/keys))
- (Optional) Gemini API Key for figure extraction

### Setup
```bash
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json with your API keys and Zotero credentials
python -m playwright install chromium
```

### Run
```bash
# Web Panel (recommended)
streamlit run app.py

# CLI (headless, for scheduled runs)
python run_agent_worker.py --year-start 2025 --year-end 2026 --target-papers 5
```

## Key Metrics

| Metric | Value |
|--------|-------|
| Knowledge Base | 70 papers (2020–2026) |
| Journal Coverage | 60+ whitelist + 239 IF database |
| Keywords | 24 (broad / narrow / Chinese) |
| Time Saved | 6–8 hrs → ~5 min per week |
| Note Structure | 18 fields with hallucination checks |
| Lines of Code | ~11,000 (Python) |

## Design Decisions

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design rationale:

- **Why monolithic?** All functions share global state (config, logger, paths). Splitting prematurely would cause circular imports. Will split during web-ification when the framework enforces layering.
- **Why n-gram TF-IDF instead of vector DB?** At 70-paper scale, character n-grams handle cross-language retrieval (Chinese + English) with zero new dependencies. Upgrade to embeddings at 200+ papers.
- **Why file signals instead of message queue?** Single-machine, single-user scenario. Signal files are zero-dependency, transparent, and trivially debugged.
- **Why Pause waits until step-completion?** The agent checks signal files at defined checkpoints (page boundary, keyword boundary, phase boundary) to avoid leaving browser/network in an inconsistent state.

## License

MIT — see [LICENSE](LICENSE) file.

---

*Built with 🦉 and Claude Code*
