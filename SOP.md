# LitCall — 学术文本深度阅读与知识管理智能体 · 运维手册 (SOP)

> ⚠️ **已过时** — 本文档对应 2026-07-23 版本（5400 行，旧菜单 [1]-[5]）。
> 当前代码 ~8500 行，已合并为统一的 🤖 Agent 页面 + 关键词游标架构。
> 设计决策章节（Section 8）和排障指南（Section 10）仍有参考价值，其余待重写。
>
> 版本: 2026-07-23 | 代码行数: ~5400 | 知识库规模: 43篇 (2020-2026, 30种期刊)

---

## 1. 系统概述

LitCall (Literature Calling) 是一个面向**人工智能营销**交叉领域的个人学术知识管理 agent。核心能力：

- **文献检索**: Playwright 自动化 SPIS (Google Scholar) 渐进式关键词搜索
- **深度阅读**: DeepSeek V4 Pro API 对 PDF 全文进行 17 字段结构化精读
- **知识库管理**: Obsidian vault (图谱+反向链接) + Excel 汇总表 + Zotero 文献管理
- **教授级问答**: 基于本地文献 + DeepSeek 外部知识的学术 AI 导师

**身份设定**: 市场营销 × AI 营销领域资深教授，辅导博士生。

---

## 2. 文件结构

```
semi_autp_paper/
├── literature_agent.py          # 主程序 (~5200行)
├── config.json                  # API密钥、关键词、Zotero配置
├── config.example.json          # 配置模板
├── journal_if.json              # 期刊影响因子库 (102条)
├── processed_log.json           # 已处理文献日志 (DOI+标题)
├── qa_history.json              # Q&A对话历史持久化
├── agent文献汇总.xlsx            # 知识库Excel汇总
├── SOP.md                       # 本文档
│
├── agent抓取/                    # Obsidian Vault
│   ├── _index.md                # 文献索引
│   ├── {year}/                   # 按年份组织
│   │   └── {journal}/            # 按期刊组织
│   │       ├── {year}_{title}.md # 论文精读笔记
│   │       └── attachments/      # PDF图表提取
│   └── QA笔记/                   # Q&A对话保存
│
├── 新论文待处理/                  # PDF暂存区
│   ├── *.pdf                     # 待处理PDF
│   ├── pending_manual.json       # 待人工下载清单
│   └── notes/                    # JSON笔记暂存
│
└── 运行日志/                      # 运行日志
    └── Claude_Semi_auto_paper_log.txt
```

---

## 3. 环境依赖

### Python 包
```
aiohttp, requests          # HTTP/API 调用
openpyxl                   # Excel 读写
fitz (PyMuPDF)             # PDF 文本提取 + 图表提取
playwright                 # 浏览器自动化 (SPIS检索)
numpy                      # 语义检索向量计算
```

### 外部服务
| 服务 | 用途 | 配置位置 |
|------|------|----------|
| DeepSeek API | 深度阅读 + Q&A | `config.json` → `deepseek_api_key` |
| Zotero API | 文献管理入库/去重 | `config.json` → `zotero` |
| Unpaywall API | 公开OA PDF下载 | 自动 (无需key) |
| Semantic Scholar API | PDF下载回退 | 自动 (无需key) |
| OpenAlex API | 影响因子回退查询 | 自动 (无需key) |

### 配置文件结构 (`config.json`)
```json
{
  "deepseek_api_key": "sk-...",
  "deepseek_model": "deepseek-chat",
  "zotero": {
    "user_id": "数字ID",
    "api_key": "...",
    "collection_name": "agent抓取"
  },
  "keywords": [["关键词", "broad/narrow"], ...],
  "journal_whitelist_extra": [],
  "min_year": 2020,
  "confirm_zotero_sync": true,
  "unpaywall_email": "your@email.com"
}
```

---

## 4. 菜单系统

```
╔══════════════════════════════════════════════════╗
║     LitCall 学术文本深度阅读与知识管理智能体          ║
╠══════════════════════════════════════════════════╣
║  [1] 检索新文献         SPIS → 待处理清单          ║
║  [2] 深度阅读 + 入库     PDF → DeepSeek → Obsidian ║
║                          + Excel + Zotero (主力)   ║
║  [3] 清理已处理的 PDF                             ║
║  [4] 批量重读           Zotero集合 → 覆写笔记       ║
║                          (Prompt升级时使用)         ║
║  [5] 知识库问答          教授级学术AI导师            ║
║  [0] 退出                                        ║
╠══════════════════════════════════════════════════╣
║  键盘控制 (检索/补全过程中):                       ║
║    P = 暂停    G = 继续    E = 终止               ║
╚══════════════════════════════════════════════════╝
```

### 4.1 [1] 检索新文献 (`scrape_only_flow`)

**流程**: 遍历关键词 → SPIS 搜索 → 翻页抓取 → 去重 → 达到10篇后提示用户选择

**用户交互**:
- 检索过程中: P暂停/G继续/E终止
- 达到10篇后: G继续搜同一关键词下一页 / E停止本关键词
- 关键词完成后: G继续下一个关键词 / E终止检索
- 浏览器在提示期间保持打开，用户可手动下载有链接的PDF

**输出**: `新论文待处理/pending_manual.json` (待人工下载清单)

### 4.2 [2] 深度阅读 + 入库（主力工作流）

**流程**: 扫描 `新论文待处理/*.pdf` → PDF文本提取 → DeepSeek 17字段精读 → 自检 → Obsidian笔记 + Excel → 询问是否Zotero入库

**自检环节** (新增): DeepSeek 生成笔记后，自动发起轻量二次 API 调用，检查：
- 变量汇总是否遗漏（定量实证论文该有但为空？）
- 关键数字是否与原文一致（样本量、统计量、百分比）
- 是否存在原文中没有的事实性陈述
- 自检失败不阻塞主流程，在日志和笔记中标记，供人工复核

**前置条件**: PDF已放入 `新论文待处理/` 文件夹

### 4.3 [3] 清理已处理的 PDF (`cleanup_processed_pdfs`)

**流程**: 扫描 `新论文待处理/*.pdf` → 提取DOI → 对比 `processed_log.json` → 确认后删除

### 4.4 [4] 批量重读 (`re_read_from_zotero_flow`)

**用途**: Prompt升级后批量重读已入库文献，覆写Obsidian笔记、按DOI更新Excel。日常不用。

**流程**: Zotero集合 → 获取所有条目 → 找到PDF附件 → DeepSeek重读 → 自检 → force覆写Obsidian → 更新Excel → 更新processed_log

### 4.5 [5] 知识库问答 (`flow_qa`)

**核心能力**: 基于本地Obsidian文献 + DeepSeek外部知识的教授级学术问答

**检索机制**: Token匹配(55%) + 字符n-gram TF-IDF语义(45%) 混合打分

**特殊命令**:
| 命令 | 功能 |
|------|------|
| `/exit` | 返回主菜单 |
| `/save` | 保存当前对话到 `agent抓取/QA笔记/` |
| `/clear` | 清空对话历史 |
| `/papers` | 重新显示上一轮匹配的本地文献 |
| `/n N` | 设置检索数量 (默认8, 范围3-15) |
| `/external` | 切换外部知识开关 |
| `/help` | 显示帮助 |

**对话持久化**: 自动保存到 `qa_history.json`，下次进入自动恢复

---

## 5. 去重体系

### 抓取阶段 (三重去重)

```
数据源合并:
  Zotero API (实时) + processed_log.json (历史) + Excel (全量)
  → global_doi_set + global_title_set

每篇新文献:
  1. DOI 精确匹配 (doi.lower() in global_doi_set)
  2. 标题模糊匹配 (SequenceMatcher > 80% AND Jaccard > 50%)
```

### 处理阶段

- PDF预处理: DOI匹配 processed_log + Excel 去重
- Excel追加: DOI匹配去重
- Obsidian写入: 文件存在检查 (force模式可覆写)

### 注意

- **Obsidian不参与抓取去重** — 它只存笔记，不作为去重数据源
- Zotero 是去重的主要防线

---

## 6. 深度阅读 Prompt 设计

### 身份: AI + Marketing 教授做个人学术精读笔记

### 17字段结构

| # | 字段 | 说明 |
|---|------|------|
| 1-9 | 基础信息 | 标题/作者/年份/期刊/IF/分区/关键词 |
| 10 | 研究背景与动机 | 现实痛点→理论缺口→已有研究→本文切入点 |
| 11 | 研究问题 | RQ/H + 理论推导 + 理论框架/构念关系 |
| 12 | 变量汇总 | 每个变量: 名称/类型(IV/DV/中介/调节/控制)/概念定义/测量方式。质性/概念论文留空 |
| 13 | 研究方法 | 研究设计/样本/程序/分析方法 (测量细节已在[12]) |
| 14 | 研究结果 | 逐条假设检验 + 核心发现 |
| 15 | 讨论与结论 | 结果解释 + 理论/实践含义 + 批判性评述 |
| 16 | 创新点 | 理论/方法/实践创新，逐条列出 |
| 17 | 局限与展望 | 逐条列出，每条含解释 |

### 核心纪律
1. 只写原文明确出现的信息，不推断、不补充、不美化
2. 数字与原文严格一致 (n=207 就是 207，不是"约200")
3. 原文没提到的内容，笔记里自然就没有
4. 深度来自透彻理解与清晰转述，非脑补细节
5. 中文撰写，专业术语保留英文+中文括号标注
6. 术语统一使用全称，禁止附加缩写

---

## 7. Q&A 模块设计

### 检索流程

```
用户问题
  ├─ 年份过滤: 正则提取 "2025-2026年" / "近3年"
  ├─ 概念扩展: 100+ 中→英学术术语映射
  ├─ Token 匹配: 中文bigram + 英文word, 加权打分(标题×4/关键词×3/正文×1.5/期刊×1)
  ├─ 语义重排: 字符3-gram+4-gram TF-IDF-L2, 余弦相似度, 55%token+45%语义
  ├─ 智能回退: 年份放宽 → 全库检索 → 最新文献兜底
  └─ 年份分布打印
```

### System Prompt 设计

- **角色**: 市场营销×AI营销领域执教多年的资深教授
- **对话对象**: 博士生
- **知识来源**: [本地文献] 优先 + [外部知识] 补充，始终标注来源
- **按问题类型自适应**: 文献查找/文献综述/理论讨论/方法比较/研究空白/开放讨论
- **诚实谦逊**: 不确定处标注"这一点我并非完全确定"

### 引用验证

每次回答后自动扫描 (作者, 年份) 引用模式，与本地索引交叉比对：
- `[本地未检索]`: 文献在库但未被检索匹配到
- `[年份不匹配]`: 作者存在但年份不符

---

## 8. 关键设计决策

### 8.1 为什么是单体脚本而非模块拆分？

当前 ~5200 行的单体脚本是**有意为之**：
- 所有函数共享同一组全局状态 (config, logger, paths, keyboard_state)
- 隐式依赖网密集：拆分必然导致循环导入和 NameError
- 单用户、本地运行、一人维护 — 单体脚本反而最易调试
- **等到Web化时自然分层** — Web框架强制你分层，那时拆不会出错

### 8.2 为什么全局变量不改成类封装？

- 终端单用户场景不存在多标签冲突
- Web化时 FastAPI/Chainlit 的 session 机制自然隔离状态
- 过早抽象是万恶之源

### 8.3 为什么 Q&A 检索不直接用向量数据库？

- 当前 43 篇文献规模下，token匹配+概念映射+n-gram TF-IDF已足够精准
- 避免引入 ChromaDB/Milvus 等重量级依赖
- 字符 n-gram 天然跨语言 (中文/英文统一处理)，零新依赖 (仅需numpy)
- 文献量增长到 200+ 篇时可考虑升级为 embedding 方案

### 8.4 为什么深度阅读不用本地模型？

- DeepSeek V4 Pro 的学术理解力远超任何可本地部署的模型
- 深度阅读的质量直接影响整个知识库的可信度
- API 成本可控 (每篇约 0.01-0.03 USD)
- Ollama 配置保留作为未来回退选项

### 8.5 为什么变量汇总独立成章？

- 变量是定量研究的骨架 — 写综述、设计研究、做元分析时都要查
- 之前变量信息散落在"研究问题"和"研究方法"两处，查阅不便
- 质性/概念论文留空 — 不为填充而编造

---

## 9. 编码注意事项

### Windows GBK 控制台

Windows 终端使用 GBK 编码，以下字符会崩溃：
- Emoji (📚🤖✅❌…)
- Unicode 非字符 (￾-￿)
- Lone surrogate (\uD800-\uDFFF)

**规则**: 所有 `print()` 调用使用 ASCII 安全标记：`[OK]`, `[ERROR]`, `[QA]`, `[检索]`, `[v]`

**清洗函数**:
- `_console_safe()`: 用于打印从文件系统读取的路径 (文件名可能含异常字符)
- `_safe_print()`: 用于打印 DeepSeek 回答 (可能含特殊Unicode)
- `_sanitize_excel_text()`: 用于 Excel 写入 (XML 1.0 非法字符)
- `re.sub(r'[\ud800-\udfff￾-￿]', '', text)`: 用于 API 调用前的文本清洗

### DeepSeek API

- 端点: `https://api.deepseek.com/v1/chat/completions`
- 模型: `deepseek-chat`
- 阅读模式: temperature=0.1, max_tokens=8192 (控制输出长度)
- Q&A模式: temperature=0.5, max_tokens=4096
- 输入文本必须先清洗 surrogate 字符，否则 HTTP 400

---

## 10. 常见问题排查

### Q: DeepSeek API HTTP 400
**原因**: 输入文本含 surrogate 字符或 Unicode 非字符
**检查**: `_generate_via_deepseek` 入口已加清洗；`_chat_via_deepseek` 对 messages 逐条清洗

### Q: Excel 保存报错 "NULL bytes or control characters"
**原因**: `_sanitize_excel_text` 未覆盖 surrogate 字符
**修复**: 已更新正则包含 `\ud800-\udfff￾-￿`

### Q: 检索结果年份不对
**原因**: 年份过滤失败或回退触发
**检查**: 看日志中的 `[检索]` 行，会打印匹配年份分布和回退原因

### Q: Zotero 入库后 Obsidian 笔记未生成
**原因**: 用户跳过了 Zotero 同步确认 (Phase 2/3)
**修复**: 使用 `[7] 重新深度阅读` 补生成，或 `[4] 阅读+入库` 一键完成

### Q: 变量汇总为空
**原因**: 该论文是综述/质性/概念论文，无明确变量
**验证**: 查看 JSON 笔记中的 `变量汇总` 字段；定量论文正常应该有内容

### Q: Q&A 回答引用了本地文献但未检索到
**原因**: 引用验证功能会标注 `[本地未检索]` — 该文献在库中但本轮检索未匹配到
**建议**: 检查文献的 search_text 是否包含查询关键词；必要时用 `/n 15` 增加检索数量

---

## 11. 扩展指南

### 添加新关键词
编辑 `config.json` → `keywords`:
```json
["新关键词", "broad"]   // broad: 宽泛匹配 / narrow: 精确匹配
```

### 扩充概念映射
编辑 `literature_agent.py` → `_CONCEPT_MAP` (~第4443行):
```python
"中文概念": "english academic term1 term2 term3",
```

### 添加期刊到白名单
编辑 `config.json` → `journal_whitelist_extra`:
```json
"journal_whitelist_extra": ["New Journal Name", "Another Journal"]
```

### 补充影响因子
编辑 `journal_if.json`，按分类添加期刊名→IF映射：
```json
"Marketing": {
  "Journal of Marketing": 9.0,
  ...
}
```

### 升级阅读 Prompt
在 `_generate_via_deepseek()` 中修改 `user_prompt` 的字段要求和 JSON 示例。
同步更新：
1. `return` 字典的取值 key
2. `NOTE_FIELDS` (Excel 列)
3. `write_obsidian_note()` 的 body 模板
4. `_parse_obsidian_note()` 的 `SECTION_NAMES`

### Web化路线
```
Phase 1: Chainlit Chat UI + SQLite历史 (2-3天)
Phase 2: 向量检索 + 流式输出 (3-5天)
Phase 3: 文献检索/处理面板 (1-2周)
Phase 4: FastAPI + React 全栈 (可选, 2-4周)
```
