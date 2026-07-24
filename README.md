# 🦉 ATHENA — Academic Literature Agent for AI × Marketing

> **面向 AI×Marketing 交叉领域的个人学术文献 Agent。将每周 25–30+ 小时的文献检索、深度精读与知识整理工作压缩至 ~5 分钟人工操作。不是通用 AI 阅读器——而是针对高影响力付费期刊深度阅读需求，从检索、方法论精读、到知识图谱入库的全流程个性化管道。**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.60-FF4B4B?logo=streamlit)](https://streamlit.io)

---

## The Problem

AI×Marketing 交叉领域的文献有三个特点，让传统工作流极其低效：

1. **分散在多个付费数据库中**。UTD24/FT50 期刊（Journal of Marketing、JCR、Marketing Science 等）大部分在付费墙后，OA 比例低。
2. **深度阅读门槛高**。一篇顶刊论文的方法论（结构方程、DID、工具变量、机器学习建模……）和理论框架，真正读懂并做出有质量的笔记，远不是"读一遍摘要"能解决的。
3. **没有现成工具能覆盖全流程**。通用 AI 阅读器只做"丢 PDF → 出总结"，不懂你的研究领域、不管期刊质量、不帮你检索、不考虑去重。

结果就是：

```
手动检索 SPIS → 人工判断期刊等级 → 手动下载 → 逐篇精读 →
逐篇做结构化笔记 → 手动录 Zotero → 手动整理 Excel → 手动做知识图谱链接
```

这不是"每周几小时"的问题——是**根本做不到持续、系统地跟踪一个交叉领域的高质量文献**。

## What ATHENA Does

ATHENA 是一套**个性化文献 Agent**——不是通用 skill，而是针对你的研究领域（AI×Marketing）深度定制的全流程管道：

```
┌──────────────────────────────────────────────────────────────┐
│                    🦉 ATHENA Pipeline                         │
├─────────────┬──────────────────┬──────────────────────────────┤
│   PHASE 0   │     PHASE 1      │        PHASE 2               │
│  VPN 检测   │   SPIS 文献检索   │     深度阅读 + 入库           │
│             │                  │                               │
│ 自动检测    │ 24 组中英关键词    │  DeepSeek V4 Pro 全文精读     │
│ 湖南大学VPN │ 按游标逐次推进     │  18 字段结构化笔记            │
│ 5分钟超时   │ 60+ 顶刊白名单     │  方法论深度讲解               │
│ 未连则跳过  │ 年份过滤 + 三重去重 │  自检反幻觉 + 图表提取        │
│             │ 每次运行收 5 篇    │  → Obsidian 知识图谱          │
│             │ 跨会话断点续传     │  → Zotero 文献库 + Excel      │
├─────────────┴──────────────────┴──────────────────────────────┤
│                   PHASE 3: 索引重建 + 教授级问答                │
└──────────────────────────────────────────────────────────────┘
```

**人工只需做一件事：在 SPIS 上下载付费 PDF（5 分钟）。其余全自动。**

---

## Why ATHENA vs. Generic AI Tools

ATHENA 不是"又一个 AI 论文总结器"。以下每个设计都来自真实使用中的痛点：

| 维度 | 通用 AI 阅读器 / Skill | ATHENA |
|------|----------------------|--------|
| **领域适配** | 通用 prompt，不懂你的领域 | 关键词库、期刊白名单、IF 库均为 AI×Marketing 定制 |
| **方法论深度** | "本文用了回归分析" | 讲解建模逻辑、识别策略、内生性处理、稳健性检验——像教授教研究方法课 |
| **幻觉控制** | 输出什么就是什么 | 自检 → 变量交叉校验 → 人工复核队列，三道防线 |
| **连续性** | 每次从头开始 | 关键词游标持久化，跨运行跨会话断点续传，不会重复检索 |
| **检索策略** | 你给一个关键词，它搜一次 | 24 组中英关键词 × 三级迭代（宽→窄→中文），系统覆盖整个领域 |
| **付费墙应对** | 不处理 | VPN 检测 + 自动文献求助 + 手动下载跟踪 |
| **运行控制** | 黑盒，跑起来停不住 | Web 面板：实时监控、暂停/恢复/终止，信号文件 IPC |
| **去重** | DOI 匹配（如有） | DOI + 标题模糊 + Zotero 实时比对 + Obsidian DOI 扫描，四层去重 |
| **双语处理** | 中英混杂 | 自动剥离中英双语标题 + 跨语言去重 + 中英混合检索 |
| **知识管理** | 输出一段文本 | Obsidian 知识图谱 + Zotero + Excel，三项自动同步 |

---

## Features

### 🤖 Personalized Agent
- **关键词游标**：24 组中英关键词（4 宽 × 10 窄 × 10 中文），每次运行收满 5 篇即停。游标写入 `config.json`，下次运行自动从上次断点继续。所有关键词穷尽后提示用户，改为仅检索当年新文献
- **高级搜索**：Web 面板支持覆盖默认参数——自定义关键词、年份范围、期刊过滤、篇数/翻页数。参数变更时弹窗询问"仅本次"还是"保存为默认"
- **运行控制**：`subprocess.Popen(DETACHED_PROCESS)` 拉起独立 Worker，通过信号文件（`.pause` / `.terminate`）实现暂停/恢复/终止。检查点设在关键词/翻页/Phase 边界，避免中断时留下不一致状态

### 🔍 Domain-Specific Retrieval
- **期刊白名单**：60+ 顶刊硬编码 + `config.json` 可扩展。覆盖营销类全部核心期刊 + UTD24/FT50 管理类 + 心理学扩展。`journal_if.json` 收录 239 种期刊影响因子
- **四层去重**：DOI 精确匹配 + 标题模糊匹配（SequenceMatcher > 80% AND Jaccard > 50%）+ Zotero 实时 API 比对 + Obsidian DOI 扫描（防止中英文关键词产生重复笔记）
- **双语标题清洗**：SPIS 返回 `中文标题 / English Title` 时，自动检测中文侧并剥离英文翻译
- **付费墙应对**：自动识别 OA 文献并通过 Unpaywall/Semantic Scholar 下载；付费文献自动在 SPIS 提交文献求助请求

### 📖 Deep Reading with Methodology Focus
- **18 字段结构化笔记**：
  ```
  基础信息 (9) → 研究背景与动机 → 研究问题 → 变量汇总 →
  研究方法 → 方法论详解 → 研究结果 → 讨论与结论 → 创新点 → 局限与展望 →
  图表分析
  ```
- **方法论详解**（区别于通用工具的核心字段）：按论文类型自动适配——
  - 定量实证：建模方法核心逻辑、识别策略、内生性处理、模型设定、估计细节、稳健性检验
  - 实验：设计逻辑、随机化、操纵检验
  - 质性研究：方法论取向、编码策略、可信度保障
  - 概念/综述：理论构建逻辑、文献筛选方法
  - 每个方法不是列名字——是讲清楚"为什么选它、核心假设是什么、本文如何满足"
- **反幻觉 Pipeline**：
  1. Prompt 纪律：只写原文明确出现的，temperature=0.1
  2. 二次自检 API 调用：检查变量遗漏、数字错误、编造内容。失败不阻塞，标记供人工复核
  3. `review_queue.json` 人工复核队列，Web 面板提示

### 🏗️ Knowledge Management
- **Obsidian 知识图谱**：按年份→期刊分层目录，双向链接 `[[概念]]` 自动生成，PDF 图表附件嵌入
- **Zotero 文献管理**：API 创建条目 + 上传 PDF 附件 + 同步确认后才标记 `processed_log`
- **Excel 汇总表**：全量文献数据库，含全部 18 字段 + PDF 路径 + 入库时间
- **教授级问答**：基于本地文献的 Token 匹配（55%）+ n-gram TF-IDF 语义重排（45%），中英跨语言检索。支持外部知识增强，回答后自动交叉验证引用准确性

---

## Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Browser Automation** | Playwright (persistent context) | SPIS 登录态跨会话保持 |
| **Deep Reading** | DeepSeek V4 Pro API | 学术理解力远超本地模型 |
| **Figure Recognition** | Gemini Vision API | PDF 图表提取（1500次/天免费） |
| **Web Panel** | Streamlit | 快速迭代，无需前后端分离 |
| **Knowledge Base** | Obsidian (Markdown vault) | 双向链接 + 图谱可视化 |
| **Reference Manager** | Zotero API v3 | 文献条目 + PDF 附件上传 |
| **PDF Processing** | PyMuPDF (fitz) | 文本提取 + 图表提取 |
| **IPC** | Signal files (.pause / .terminate) | 零依赖，透明可调试 |
| **Data** | openpyxl, JSON, aiohttp | Excel 汇总 + 运行日志 + 异步 HTTP |

---

## Project Structure

```
athena/
├── app.py                   # Streamlit Web 面板 (~2700 lines)
├── literature_agent.py      # 核心引擎 (~8600 lines)
├── run_agent_worker.py      # CLI Worker 入口
├── config.example.json      # 配置模板
├── requirements.txt         # Python 依赖
├── journal_if.json          # 影响因子库 (239 种期刊, 9 个学科)
│
├── agent抓取/               # Obsidian Vault (70 papers, 2020–2026)
│   ├── _index.md
│   ├── {year}/{journal}/{year}_{title}.md   # 18 字段笔记
│   │                └── attachments/        # PDF 图表
│   └── concepts/            # 概念节点（知识图谱）
│
├── 新论文待处理/             # PDF 暂存区
├── 运行日志/runs/            # AgentRunLogger 结构化 JSON
├── agent文献汇总.xlsx        # Excel 全量知识库
└── processed_log.json       # 已处理文献日志
```

---

## Quick Start

### Prerequisites
- Python 3.10+
- Playwright Chromium: `python -m playwright install chromium`
- DeepSeek API Key ([platform.deepseek.com](https://platform.deepseek.com))
- Zotero API Key（[zotero.org/settings/keys](https://www.zotero.org/settings/keys)，需勾选 Allow write access）
- (Optional) Gemini API Key（[aistudio.google.com](https://aistudio.google.com)，用于图表提取）

### Setup
```bash
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json：填入 API Key、Zotero 凭据、关键词等
python -m playwright install chromium
```

### Run
```bash
# Web 面板（推荐）
streamlit run app.py

# CLI（适合定时任务）
python run_agent_worker.py --year-start 2025 --year-end 2026 --target-papers 5
```

---

## Key Metrics

| Metric | Value |
|--------|-------|
| Knowledge Base | 70 papers (2020–2026, 7 个年份) |
| Journal Coverage | 60+ whitelist + 239 IF database (9 学科) |
| Keywords | 24 (4 broad / 10 narrow / 10 Chinese) |
| Note Structure | 18 fields with hallucination self-check |
| Anti-Hallucination | Prompt discipline + 2nd-pass verification + review queue |
| Lines of Code | ~11,300 (Python) |

---

## Design Decisions

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design rationale, data flow diagrams, and trade-off analysis. Key decisions:

- **Why monolithic?** All functions share global state (config, logger, paths). Splitting prematurely causes circular imports. Future web migration will naturally enforce layering.
- **Why n-gram TF-IDF instead of vector DB?** At 70-paper scale, character n-grams handle cross-language (Chinese+English) retrieval with zero new dependencies. Upgrade to embeddings at 200+ papers.
- **Why signal files instead of message queue?** Single-machine, single-user. Files are zero-dependency, transparent, and trivially debugged.
- **Why keyword cursor in config.json?** The simplest persistent state store available. Atomic write (temp file + rename) prevents corruption on crash.

---

*Built for personal academic research. Not a product — a tool that fits one researcher's workflow exactly.*
