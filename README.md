# 🦉 ATHENA — Academic Literature Agent for AI × Marketing

> **将每周 15–20 小时的文献检索、笔记整理与知识管理压缩至 2–3 小时。Agent 承担全部查找、筛选、结构化笔记和入库——你只负责结合笔记深度阅读论文本身。**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.60-FF4B4B?logo=streamlit)](https://streamlit.io)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek_V4_Pro-4B6BFB)](https://platform.deepseek.com)

---

## At a Glance

```
  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
  │     PHASE 0      │     │     PHASE 1      │     │     PHASE 2      │     │     PHASE 3      │
  │     VPN 检测      │ ──► │    SPIS 检索      │ ──► │   深度阅读+入库   │ ──► │   索引+问答就绪   │
  ├──────────────────┤     ├──────────────────┤     ├──────────────────┤     ├──────────────────┤
  │ • 5分钟超时       │     │ • 24组中英关键词   │     │ • DeepSeek 全文   │     │ • 重建论文索引    │
  │ • 未连自动跳过    │     │ • 60+顶刊白名单    │     │ • 18字段结构化    │     │ • 知识图谱同步    │
  │ • 识别登录页状态  │     │ • 四层去重         │     │ • 方法论详解       │     │ • 问答系统就绪    │
  │                  │     │ • 双语标题清洗     │     │ • 反幻觉自检       │     │                  │
  │                  │     │ • 游标断点续传     │     │ • Gemini 图表     │     │                  │
  └──────────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘
```

| 知识库 | 检索能力 | 质量控制 |
|:---:|:---:|:---:|
| 📄 **70** papers (2020–2026) | 🔑 **24** 组关键词 (宽/窄/中文) | 🛡️ **3** 道反幻觉防线 |
| 🏷️ **60+** 顶刊白名单 + 239 IF 库 | 📝 **18** 字段结构化笔记 | 📊 ~11,300 lines Python |

人工操作：~5 分钟下载 PDF → Agent 处理全部 → 你花 2–3 小时结合笔记深度阅读

---

## Why This Isn't Just Another "AI Paper Summarizer"

以下每个功能都来自真实使用中踩过的坑——只用通用工具的人不会遇到这些问题：

| 通用 AI 工具 | ATHENA | 为什么重要 |
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

**异步并发 + 子进程隔离**
`asyncio` + `aiohttp` 驱动并发 HTTP（DeepSeek API、Zotero API、Unpaywall 并行调用）。Agent Worker 通过 `subprocess.Popen(DETACHED_PROCESS)` 独立于 Streamlit 进程运行——关闭浏览器不影响执行。进度通过结构化 JSON 日志文件增量写出，Web 面板 3 秒轮询实现实时监控。

**Playwright 持久化上下文**
`launch_persistent_context` 将 SPIS 登录 Cookie 保存到本地目录，跨会话维持认证状态。VPN 检测复用同一套登录页标记识别逻辑（账号登录/手机号登录/微信扫码/当前IP），四标记中至少两个匹配即判定已登录。

**结构化运行日志**
`AgentRunLogger` 为每次运行生成独立 JSON 文件（`运行日志/runs/{run_id}.json`），三阶段（检索/阅读/同步）状态实时增量写入。Streamlit 运行历史页直接解析 JSON 渲染——不需要数据库。

**跨语言混合检索**
中文学术术语自动扩展为英文对应词（100+ 映射表）→ Token 匹配 (55% weight，标题×4/关键词×3/正文×1.5) + 字符 3-gram+4-gram TF-IDF 语义重排 (45%)。70 篇规模下零新依赖，不需要向量数据库。

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

## Screenshots

> 截图待补充——Agent 控制面板、深度阅读笔记示例、Obsidian 知识图谱。

<!--
![Agent 控制面板](docs/screenshots/agent-panel.png)
![深度阅读笔记](docs/screenshots/note-sample.png)
![知识图谱](docs/screenshots/knowledge-graph.png)
-->

---

*独立设计开发 · 2026.06 完成 · 已稳定服务个人学术研究 1 个月*
