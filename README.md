# 🦉 ATHENA — Academic Literature Agent for AI × Marketing

> **将每周 15–20 小时的文献检索、笔记整理与知识管理压缩至 2–3 小时。Agent 承担全部查找、筛选、结构化笔记和入库——你只负责结合笔记深度阅读论文本身。**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.60-FF4B4B?logo=streamlit)](https://streamlit.io)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek_V4_Pro-4B6BFB)](https://platform.deepseek.com)
[![Status](https://img.shields.io/badge/Status-Active_2_months-brightgreen)]()

---

## At a Glance

```
  VPN 检测          24 组中英关键词 × 三级迭代         DeepSeek V4 Pro 全文精读
  (5min超时/跳过)    60+ 顶刊白名单 + 年份过滤           18 字段结构化笔记
       │              四层去重 + 双语标题清洗             方法论深度讲解 + 反幻觉自检
       │              关键词游标 → 断点续传              图表识别 (Gemini Vision)
       ▼                    │                                  │
  ┌────────┐          ┌──────────┐                    ┌──────────────┐
  │ PHASE 0 │ ──────► │ PHASE 1  │ ────────────────►  │   PHASE 2    │
  │ 连通检测 │        │ SPIS 检索 │                    │ 深度阅读+入库 │
  └────────┘          └──────────┘                    └──────────────┘
                                                             │
                                            ┌────────────────┘
                                            ▼
                                    ┌──────────────┐
                                    │   PHASE 3    │
                                    │ 索引+问答就绪  │
                                    └──────────────┘
  人工操作: ~5 分钟下载 PDF        →  →  →        深度阅读: 2–3 小时
```

| Metric | | Metric | |
|--------|--|--------|--|
| 📄 知识库 | **70 papers** (2020–2026) | 🏷️ 期刊覆盖 | **60+ whitelist + 239 IF** |
| 🔑 关键词 | **24 组** (宽/窄/中文) | 📝 笔记结构 | **18 字段** + 方法论详解 |
| 🛡️ 幻觉控制 | **3 道防线** | 📊 代码规模 | **~11,300 lines** Python |

---

## Why This Isn't Just Another "AI Paper Summarizer"

ATHENA 不是通用 AI 阅读器。以下每一个设计决策都来自真实使用中踩过的坑——只用通用工具的人不会遇到这些问题：

| 如果你只用通用 AI 工具 | ATHENA 的做法 | 为什么这很重要 |
|---|---|---|
| 丢 PDF → 出总结，不知道期刊是不是水刊 | **60+ 顶刊白名单**（UTD24/FT50 全覆盖）+ 239 种期刊 IF 库，检索阶段就过滤 | 你不会浪费时间读一篇 Q4 期刊的论文 |
| "本文使用回归分析" | **方法论详解**：讲建模逻辑、识别策略、内生性处理、稳健性检验——像教授讲研究方法课 | 读完笔记你就懂了方法，不用回头翻原文 |
| 输出什么信什么 | **反幻觉 Pipeline**：Prompt 纪律 → 二次 API 自检 → `review_queue.json` 人工复核 | LLM 会编造——ATHENA 有纠错机制 |
| 每次从零开始搜 | **关键词游标**持久化到 `config.json`，跨运行断点续传，不会重复检索已覆盖的关键词 | 持续运行几周后，你系统性地覆盖了整个领域 |
| 你给一个词，它搜一次 | **24 组中英关键词 × 三级迭代**（宽泛→精确→中文），游标自动推进 | 不是"搜一次"——是"系统覆盖一个领域" |
| 中英文标题混在一起，同一篇论文出两个笔记 | **双语标题自动清洗** + DOI 跨语言去重 | 70 篇笔记没有一篇重复 |
| 黑盒运行，跑起来停不住 | **Web 面板实时控制**：启动/暂停/恢复/终止，信号文件 IPC | 你随时掌控制，不是 Agent 控制你 |
| 输出一段文本 | **Obsidian 知识图谱 + Zotero + Excel 三项自动同步**，双向链接 + 图表附件 | 笔记不是孤立的——是一个可导航的知识网络 |
| 不管付费墙 | **VPN 检测 + 自动文献求助 + 手动下载跟踪** | 现实中大部分顶刊在付费墙后面 |
| 不关心去重质量 | **四层去重**：DOI 精确 + 标题模糊 + Zotero API + Obsidian DOI 扫描 | 跨关键词、跨语言、跨年份——0 篇重复入库 |

---

## Technical Highlights

**信号文件 IPC — 跨进程运行控制**
Streamlit Web 面板通过写 `.pause` / `.terminate` 文件控制 `subprocess.Popen(DETACHED_PROCESS)` 拉起的独立 Worker。检查点设在翻页/关键词/Phase 边界——不会在浏览器操作中途杀进程。零外部依赖，透明可调试。

**关键词游标状态机**
`config.json` 中维护 `(category_index, keyword_index)` 游标，原子写入（temp file + rename）防崩溃丢进度。24 个关键词按 宽→窄→中文 三级迭代，全部穷尽后自动切为"仅检索当年新文献"模式。

**反幻觉三道防线**
(1) Prompt 纪律：只写原文明确出现的，temperature=0.1。(2) 二次 API 自检：逐字段核对变量遗漏、数字错误、编造内容。(3) 人工复核队列：自检失败的笔记进入 `review_queue.json`，Web 面板提示用户复核。

**跨语言混合检索**
Q&A 模块：中文学术术语自动扩展为英文对应词 → Token 匹配 (55% weight，标题×4/关键词×3/正文×1.5) + 字符 3-gram+4-gram TF-IDF 语义重排 (45% weight)。不需要向量数据库——70 篇规模下零新依赖。

---

## Quick Start

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥
cp config.example.json config.json
# 编辑 config.json：填入 DeepSeek API Key、Zotero 凭据、关键词等

# 3. 安装浏览器
python -m playwright install chromium

# 4. 启动
streamlit run app.py                        # Web 面板
python run_agent_worker.py --target-papers 5  # 或 CLI
```

**依赖**: Python 3.10+ · DeepSeek API Key · Zotero API Key · (可选) Gemini API Key

---

## Project Structure

```
├── app.py               Streamlit 面板 (~2700 lines)
├── literature_agent.py  核心引擎 (~8600 lines)
├── run_agent_worker.py  CLI Worker 入口
├── config.example.json  配置模板 · journal_if.json (239种期刊 IF)
│
├── agent抓取/           Obsidian Vault — 70 papers, 按 年份/期刊 分层
│   └── {year}/{journal}/{title}.md  + attachments/ + concepts/
│
├── 新论文待处理/         PDF 暂存区 · 运行日志/runs/ (结构化 JSON)
├── agent文献汇总.xlsx    Excel 全量库 · processed_log.json (已处理日志)
└── requirements.txt
```

---

## Design Decisions

| 决策 | 理由 |
|------|------|
| **单体 ~8600 行，不拆分** | 所有函数共享全局状态（config, logger, paths）。过早拆分导致循环导入。Web 化迁移时框架自然强制分层 |
| **n-gram TF-IDF，不用向量库** | 70 篇规模下字符 n-gram 天然跨语言（中英统一），零新依赖。200+ 篇时升级 embedding |
| **信号文件，不用消息队列** | 单机单用户。文件零依赖、透明、一个 `ls` 就能调试 |
| **游标在 config.json，不用数据库** | 最简单可用的持久化。原子写入防 corruption |

详见 [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Screenshots

<!-- TODO: 补充截图 -->
| Agent 控制面板 | 深度阅读笔记 | 知识图谱 |
|:---:|:---:|:---:|
| *(screenshot)* | *(screenshot)* | *(screenshot)* |

---

*独立设计开发 · 2026.05–07 · 已稳定服务个人学术研究 2 个月*
