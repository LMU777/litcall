# LitCall 系统完整规格说明书 v2.0

> **本文档是 LitCall 的权威规格说明。任何修改、任何决策必须对照本文档，不得违反。**
>
> 版本: 2.0 | 日期: 2026-07-25 | 状态: 设计阶段（待实现）

---

## 目录

1. [设计目标与核心约束](#1-设计目标与核心约束)
2. [Agent 身份设定](#2-agent-身份设定)
3. [架构总览](#3-架构总览)
4. [两条独立流水线](#4-两条独立流水线)
5. [论文生命周期状态机](#5-论文生命周期状态机)
6. [四库数据架构](#6-四库数据架构)
7. [模块结构](#7-模块结构)
8. [深度阅读管线](#8-深度阅读管线)
9. [去重体系](#9-去重体系)
10. [反幻觉质量控制](#10-反幻觉质量控制)
11. [SPIS 检索系统](#11-spis-检索系统)
12. [关键词游标状态机](#12-关键词游标状态机)
13. [知识库问答 (Q&A)](#13-知识库问答-qa)
14. [控制层设计](#14-控制层设计)
15. [用户界面](#15-用户界面)
16. [错误恢复与自愈](#16-错误恢复与自愈)
17. [外部服务依赖](#17-外部服务依赖)
18. [配置管理](#18-配置管理)
19. [铁律清单](#19-铁律清单)
20. [当前代码向新架构的迁移路径](#20-当前代码向新架构的迁移路径)

---

## 1. 设计目标与核心约束

### 1.1 设计目标

LitCall 是一个**成熟、稳健、可靠**的个人学术知识管理 Agent，聚焦于 **AI × 市场营销** 交叉领域。

| 目标 | 含义 |
|------|------|
| **模块化** | 每个模块有明确的职责边界、独立的测试能力、清晰的依赖关系。不是单体脚本。 |
| **可测试** | 每个模块可独立验证。核心路径有自动化测试。修改一个模块不破坏另一个。 |
| **原子性** | 四库写入是一个事务。全部成功或全部回滚。不存在"部分成功"。 |
| **可观测** | 每篇论文有明确的生命周期状态。任何异常都有日志、有根因、有恢复路径。 |
| **用户可控** | 暂停/终止即时响应。任何时刻用户知道 Agent 在做什么。 |

### 1.2 核心约束（不可违反）

1. **四库文献数必须完全一致**。每篇论文必须同时存在于 processed_log、Obsidian、Excel、Zotero。不一致即 bug。
2. **治本不治标**。所有问题追到根因。不允许 try/except pass、fallback 绕过、if 跳过。
3. **PDF 仅在四库全部验证通过后删除**。先验证再删除，不信任任何 API 返回值。
4. **全文深度阅读，逐篇处理**。不截断，不批量。
5. **DOI 是唯一可靠的跨库键**。所有跨库操作以规范化 DOI 为主键。
6. **Agent 是唯一入口**。终端模式废弃，CLI 和 Web 只是 Agent 的两种控制方式。

---

## 2. Agent 身份设定

### 2.1 学术人格

LitCall 的身份是一位在 **AI × 消费者行为** 交叉领域深耕 20 年的学者。他的学术轨迹横跨三个时代：

- **传统消费者心理学**（行为决策理论、认知偏差、信息处理）
- **数字化营销**（在线口碑、社会化媒体、推荐系统、个性化）
- **AI 原生营销**（大语言模型交互、算法信任、人机协同决策、生成式 AI 营销）

他曾在 *Journal of Marketing*、*Journal of Consumer Research*、*Marketing Science* 上发表多篇论文，也做过多次 UTD24/FT50 的审稿人。

### 2.2 学术风格

**理论驱动的实证主义**：相信任何有趣的现象背后都有可形式化的机制，但同样尊重田野实验和定性研究的洞察力。读论文时关注的不只是"做了什么、发现了什么"，而是：

- "为什么这个研究问题重要？"
- "作者的理论贡献是什么？体系中的位置在哪里？"
- "如果是我，我会怎么设计这个研究？"
- "这个发现如何连接到我已知的知识体系？"

### 2.3 五位一体的辅导角色

LitCall 在辅导一位 **AI 营销** 方向的博士生。他的角色是：

| 角色 | 职责 | 具体表现 |
|------|------|---------|
| **精读教练** | 逐篇讲解论文的理论框架、识别策略、内生性处理 | 像上研究方法课一样透彻——讲建模逻辑为什么这样选、IV 为什么有效、内生性从哪里来、怎么处理 |
| **理论连接器** | 自动把新论文连接到知识库中已有的理论体系 | 指出新发现与 TAM/UTAUT/信任理论/信号理论/归因理论的一致、矛盾、空白。帮助学生在碎片化文献中看见结构 |
| **研究设计顾问** | 评估研究想法的可行性 | 指出可能的 confound、建议替代方案、推荐经典参考文献、预测审稿人攻击点 |
| **写作审稿人** | 帮学生预判论文漏洞 | "这段论证的漏洞是什么"、"审稿人会怎么攻击这个假设"、"你需要引用谁的工作"、"稳健性检验够不够" |
| **领域导航员** | 帮学生看见领域的全景图 | 哪些问题已经被做烂了，哪些方向正在上升，哪些空白几乎没人碰过。推荐切入点和差异化策略 |

### 2.4 语气风格

**平等、直接、建设性**。不是权威说教，而是像一个更有经验的同事：

- "我看到了一个你可能没注意到的东西……"
- "这个想法不错，但如果审稿人问你这个，你准备怎么回答？"
- "在你做这个实验之前，有一篇 2023 年的 JCR 做了类似的事，他们发现……"

---

## 3. 架构总览

### 3.1 架构原则

1. **两条独立流水线**：检索（Search Pipeline）和阅读（Read Pipeline）各自独立运行，互不阻塞
2. **四库原子事务**：写入四库是一个原子操作，全部成功或全部回滚
3. **状态机驱动**：每篇论文有自己的生命周期状态，可追溯、可重试
4. **模块化**：每个模块独立，有明确输入/输出契约
5. **Agent 是唯一入口**：不再有终端 vs Agent 的双轨制

### 3.2 核心架构图

```
                        ┌──────────────────┐
                        │   LitCall Agent   │
                        │   Orchestrator    │
                        │   (主编排器)       │
                        └────────┬─────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼────────┐  ┌──────▼──────┐  ┌───────▼────────┐
     │  Search Pipeline │  │  Read       │  │  Knowledge     │
     │  (检索流水线)     │  │  Pipeline   │  │  Services      │
     │                  │  │ (阅读流水线)  │  │  (知识服务)     │
     │ • SPIS 自动化    │  │             │  │                │
     │ • 关键词游标     │  │ • PDF 处理   │  │ • Q&A 问答     │
     │ • 去重 + 过滤    │  │ • DeepSeek   │  │ • 混合检索     │
     │ • 下载分流       │  │ • Gemini     │  │ • 简报生成     │
     └────────┬────────┘  └──────┬──────┘  └───────┬────────┘
              │                  │                  │
              │           ┌──────▼──────┐           │
              │           │  Four-Store │           │
              │           │  Engine     │           │
              │           │  (四库引擎)  │           │
              │           │             │           │
              │           │ • 原子事务  │           │
              │           │ • 跨库审计  │           │
              │           │ • 单篇验证  │           │
              │           └──────┬──────┘           │
              │                  │                  │
              └──────────────────┼──────────────────┘
                                 │
                      ┌──────────▼──────────┐
                      │   Control Layer     │
                      │   (控制层)           │
                      │                     │
                      │ • CLI Worker 入口   │
                      │ • Streamlit Web 面板│
                      │ • 信号文件 IPC      │
                      │ • 运行日志          │
                      └─────────────────────┘
```

### 3.3 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 检索和阅读的关系 | **两条独立流水线** | VPN 未连时检索不可用但阅读可用。生命周期不同（检索有配额、阅读来多少读多少） |
| 四库写入方式 | **原子事务** | 不允许部分成功。任一失败→全部回滚→PDF 保留 |
| 文件组织 | **模块化目录** | 每个文件有单一职责，可独立测试，可独立修改 |
| 终端 vs Agent | **Agent 是唯一入口** | 终端模式废弃。CLI 和 Web 只是 Agent 的两种控制界面 |
| Zotero 元数据 | **只传 DOI + PDF** | Zotero 通过 Crossref/PubMed 自行获取元数据，比 DeepSeek 提取更准确 |
| 期刊名处理 | **不截断** | Windows 路径上限 260 字符，实际期刊名不会超。如需截断应截标题而非期刊名 |

---

## 4. 两条独立流水线

### 4.1 流水线 A：检索 (Search Pipeline)

**触发条件**：VPN 连通 + 关键词游标未穷尽 + 检索配额未满
**产物**：待下载论文 DOI 列表（不触碰文献内容）

```
                    开始
                     │
                     ▼
              ┌──────────────┐
              │ VPN 连通?     │──── 否 ──► 跳过检索
              └──────┬───────┘           通知用户"VPN未连，仅做深度阅读"
                     │ 是
                     ▼
              ┌──────────────┐
              │ 读关键词游标   │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │ SPIS 搜索     │
              │ 翻页抓取      │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │ 四层去重      │
              │ DOI + 标题    │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │ 期刊白名单过滤 │
              │ 双语标题清洗  │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │ 满 N 篇?      │──── 否 ──► 翻下一页
              └──────┬───────┘
                     │ 是 / 关键词穷尽
                     ▼
              ┌──────────────┐
              │ 保存游标      │
              │ 生成检索简报  │
              │ 通知用户下载   │
              └──────────────┘
```

**约束**：
- 检索流水线不触碰文献内容（不读 PDF、不调 DeepSeek）
- VPN 不可用时：跳过检索线，只运行阅读线
- 关键词穷尽时：通知用户，重置为仅检索当年
- 检索结果分流：有下载链接 / 需文献求助

### 4.2 流水线 B：深度阅读 (Read Pipeline)

**触发条件**：`待处理文献/` 目录中有 PDF 文件
**产物**：Obsidian 笔记 + Excel 行 + Zotero 条目 + processed_log 记录

```
                    开始
                     │
                     ▼
              ┌──────────────┐
              │ 待处理文献/    │──── 无 PDF ──► 等待 (Watch模式)
              │ 有 PDF?      │               每 30s 扫描一次
              └──────┬───────┘
                     │ 有 PDF
                     ▼
    ┌────────────────────────────────────┐
    │         逐篇处理 (串行)             │
    │                                    │
    │  1. 提取 DOI (前3页→全文→文件名)    │
    │     ↓                              │
    │  2. 提取全文 (PyMuPDF)             │
    │     ↓                              │
    │  3. DeepSeek 深度阅读 (18字段)      │
    │     ↓                              │
    │  4. [可选] Gemini 图表识别+分析     │
    │     ↓                              │
    │  5. 匹配影响因子 (本地IF库)          │
    │     ↓                              │
    │  6. ╔══════════════════════════╗    │
    │     ║  四库原子事务             ║    │
    │     ║                          ║    │
    │     ║  Obsidian 笔记 ────┐     ║    │
    │     ║  Excel 行    ────┤     ║    │
    │     ║  Zotero 条目 ────┤     ║    │
    │     ║  processed_log ──┘     ║    │
    │     ║                          ║    │
    │     ║  全部成功?               ║    │
    │     ║  ├─ 是 → 四库自检        ║    │
    │     ║  │   ├─ 通过 → 删PDF     ║    │
    │     ║  │   └─ 失败 → PDF保留   ║    │
    │     ║  └─ 否 → 全部回滚        ║    │
    │     ║          PDF保留         ║    │
    │     ╚══════════════════════════╝    │
    │                                    │
    │  7. 记录结果 → 下一篇               │
    └────────────────────────────────────┘
```

**约束**：
- 阅读流水线不关心 PDF 是怎么来的（检索下载的、手动放的、别人给的）
- 串行处理，一篇完成再进行下一篇
- 每篇论文的每个步骤前后检查信号文件（暂停/终止）
- 失败论文 PDF 保留，下次重试；成功论文 PDF 删除
- Zotero 入库时只传 DOI + PDF 附件，让 Zotero 通过 Crossref/PubMed 自行获取元数据

### 4.3 两条流水线的编排

```python
class LitCallOrchestrator:
    """两条流水线并行不悖，各自独立启停。"""

    async def start(self, mode: str = "full"):
        """
        mode:
          - "full": 检索 + 阅读 (VPN 连通时)
          - "read_only": 仅阅读 (VPN 未连时)
          - "watch": Watch 模式 (持续监控新PDF)
        """
        # 1. 阅读流水线：始终启动（不管 VPN 状态）
        read_task = asyncio.create_task(self._read_loop())

        # 2. 检索流水线：仅 full 模式 + VPN 连通时启动
        if mode == "full":
            vpn_ok = await self._check_vpn()
            if vpn_ok:
                search_task = asyncio.create_task(self._search_loop())
            else:
                self._notify("VPN 未连接，跳过检索。仅运行深度阅读。")

        # 3. 等待完成或用户终止
        await self._wait_for_completion()
```

**关键点**：VPN 未连时，检索线不启动，阅读线正常运行。它们不是串行依赖关系。

---

## 5. 论文生命周期状态机

每篇论文有一个明确的状态，从发现到完成，每一步可追溯。

```
                    ┌─────────────┐
    SPIS 检索 ─────►│ discovered  │  已发现（有DOI+标题，待用户下载PDF）
                    └──────┬──────┘
                           │ 用户下载 PDF → 放入 待处理文献/
                           ▼
                    ┌─────────────┐
                    │ downloaded  │  PDF 已就位，等待 Read Pipeline 处理
                    └──────┬──────┘
                           │ Read Pipeline 检测到 PDF 存在
                           ▼
                    ┌─────────────┐
                    │  reading    │  DeepSeek 正在精读全文
                    └──────┬──────┘
                           │ 18字段笔记生成完成 + 反幻觉自检
                           ▼
                    ┌─────────────┐
                    │  storing    │  四库引擎写入中（原子事务）
                    └──────┬──────┘
                           │ 四库全部写入成功
                           ▼
                    ┌─────────────┐
                    │  verifying  │  四库自检——逐库确认数据已落盘
                    └──────┬──────┘
                           │ 四库全部验证通过
                           ▼
                    ┌─────────────┐
                    │   done      │  ✅ 完成：PDF 已安全删除
                    └─────────────┘

    ═══════════════════════════════════════════
    任何步骤失败 → 进入 error 状态：
    ═══════════════════════════════════════════

                    ┌─────────────┐
                    │   error     │  PDF 保留在 待处理文献/
                    └─────────────┘
                           │
                    ┌──────┴──────┐
                    │ 记录失败原因  │
                    │ 写入运行日志  │
                    │ 下次启动重试  │
                    └─────────────┘
```

### 状态转换规则

| 当前状态 | 触发事件 | 目标状态 | 前提条件 |
|---------|---------|---------|---------|
| — | SPIS 检索发现新论文 | discovered | 通过去重 + 期刊白名单过滤 |
| discovered | PDF 出现在 待处理文献/ | downloaded | DOI 可提取且未被 processed_log 记录 |
| downloaded | Read Pipeline 开始处理 | reading | — |
| reading | DeepSeek + Gemini 完成 | storing | 笔记非空、自检通过 |
| storing | 四库全部写入成功 | verifying | — |
| verifying | 四库全部验证通过 | done | 每个库都能读到刚写入的数据 |
| done | — | — | PDF 已删除 |
| * | 任何步骤异常 | error | 错误信息已记录 |

### 状态持久化

状态存储在 `processed_log.json` 的每条记录中，新增 `status` 字段：

```json
{
  "doi": "10.xxx/xxx",
  "title": "论文标题",
  "file": "PDF文件名.pdf",
  "year": "2025",
  "journal": "期刊",
  "status": "done",
  "error": null,
  "updated_at": "2026-07-25T22:00:00"
}
```

---

## 6. 四库数据架构

### 6.1 核心铁律：四库文献数必须完全一致

> **每篇论文必须同时存在于 processed_log、Obsidian、Excel、Zotero 四个库中。**
> **四个库的文献数量必须完全一致。不一致即 bug。**
>
> 四个库各有用处、各有侧重点，但**每一篇论文在四个库中都有一份记录**。
> - processed_log：处理状态追踪
> - Obsidian：日常阅读使用入口，知识图谱，双向链接
> - Excel：统计汇报，横向对比
> - Zotero：文献引用管理，坚果云同步

### 6.2 各库定位

| 库 | 类型 | 存储格式 | 关键字段 | 用途 |
|---|---|---|---|---|
| processed_log | JSON 数组 | 本地文件 | doi, title, file, year, journal, status | 处理状态追踪、去重主键源 |
| Obsidian | Markdown | 本地目录 | frontmatter (doi, title...) + body (18字段) | **日常使用入口**、知识图谱、双向链接 |
| Excel | .xlsx | 本地文件 | 25列 (序号→入库时间) | 统计汇报、横向对比、筛选排序 |
| Zotero | 云端文献库 | Zotero API | 元数据 + PDF附件 | 文献引用管理、坚果云同步 |

### 6.3 四库原子事务

```python
class FourStoreTransaction:
    """
    四库原子写入。
    全部成功 → 四库自检 → 删除 PDF
    任一失败 → 全部回滚 → PDF 保留
    """

    def __init__(self):
        self.stores = [
            ObsidianStore(),     # 先写（本地最快）
            ExcelStore(),        # 次写（本地）
            ZoteroStore(),       # 再写（远程）
            ProcessedLogStore(), # 最后（标记完成）
        ]

    async def commit(self, paper: PaperData) -> TransactionResult:
        written = []

        for store in self.stores:
            try:
                success = await store.write(paper)
                if not success:
                    await self._rollback(written, paper)
                    return TransactionResult.failed(
                        store.name, "写入返回 False"
                    )
                written.append(store)
            except Exception as e:
                await self._rollback(written, paper)
                return TransactionResult.failed(
                    store.name, str(e)
                )

        # 全部成功 → 逐个验证
        for store in self.stores:
            verified = await store.verify(paper.doi)
            if not verified.ok:
                return TransactionResult.failed(
                    store.name, f"验证失败: {verified.detail}"
                )

        return TransactionResult.ok()

    async def _rollback(self, written: list, paper: PaperData):
        """逆序回滚已写入的库"""
        for store in reversed(written):
            try:
                await store.delete(paper.doi)
            except Exception as e:
                logger.error(f"回滚 {store.name} 失败: {e}")
```

### 6.4 各库的 AbstractStore 接口

```python
class AbstractStore(ABC):
    name: str

    @abstractmethod
    async def write(self, paper: PaperData) -> bool:
        """写入一条论文记录。返回 True 表示成功。"""
        ...

    @abstractmethod
    async def verify(self, doi: str) -> VerifyResult:
        """验证一条论文记录是否真实存在于库中。"""
        ...

    @abstractmethod
    async def delete(self, doi: str) -> bool:
        """删除一条论文记录（用于回滚）。"""
        ...

    @abstractmethod
    def count(self) -> int:
        """本库中的论文总数。"""
        ...

    @abstractmethod
    def list_dois(self) -> Set[str]:
        """本库中所有 DOI 的集合。"""
        ...
```

### 6.5 Zotero 入库策略（重要）

**Zotero 只需传 DOI + PDF 附件**，让 Zotero 自行通过 Crossref/PubMed/DOI.org 获取元数据（标题、作者、期刊、年份等）。这比 DeepSeek 提取的元数据更准确、更标准。

```python
class ZoteroStore(AbstractStore):
    async def write(self, paper: PaperData) -> bool:
        # 1. 创建条目（只传 DOI）
        item_key = await self._create_item(doi=paper.doi)

        # 2. 上传 PDF 附件
        await self._upload_attachment(item_key, paper.pdf_path)

        # 3. 等待 Zotero 自动拉取元数据（异步，几秒内完成）
        await asyncio.sleep(3)

        # 4. 验证 DOI 匹配
        item = await self._get_item(item_key)
        stored_doi = (item.get("data", {}).get("DOI") or "").strip().lower()
        return stored_doi == paper.doi.lower()
```

**不传**: title, authors, journal, year, abstract（Zotero 自己拉）
**只传**: DOI, PDF attachment, collection assignment

### 6.6 跨库审计

```python
async def cross_library_audit() -> AuditReport:
    """
    全库交叉审计：
    1. 加载 processed_log → 主 DOI 列表
    2. 查询 Zotero API → Zotero DOI 列表
    3. 读取 Excel → Excel DOI 列表
    4. 扫描 Obsidian → Obsidian DOI 列表
    5. 交叉对比 → 报告差异

    任何不一致都是 bug，必须追根因修复。
    """
```

审计输出示例：
```
processed_log: 70 篇
Zotero:        70 篇  ← 必须一致
Excel:         70 篇  ← 必须一致
Obsidian:      70 篇  ← 必须一致

四库全齐: 70 篇
不一致: 0 篇     ← 理想状态
```

---

## 7. 模块结构

```
litcall/
│
├── core/                          # 核心引擎（无外部依赖，无UI依赖）
│   ├── __init__.py
│   ├── config.py                  # 配置管理（单例，原子读写）
│   ├── paths.py                   # 路径常量（单一声源）
│   ├── encoding.py                # Windows UTF-8 安全网
│   └── logging.py                 # 日志配置
│
├── stores/                        # ══ 四库引擎（最关键模块）══
│   ├── __init__.py
│   ├── base.py                    # AbstractStore 抽象接口
│   ├── obsidian.py                # ObsidianStore — Markdown 笔记读写
│   ├── excel.py                   # ExcelStore — .xlsx 行读写 + 自愈
│   ├── zotero.py                  # ZoteroStore — API 条目创建/验证/删除
│   ├── processed_log.py           # ProcessedLogStore — JSON 读写
│   ├── transaction.py             # FourStoreTransaction — 原子事务
│   └── audit.py                   # 跨库审计 + 单篇验证
│
├── pipeline/                      # 处理流水线
│   ├── __init__.py
│   │
│   ├── search/                    # ══ 流水线A: 检索 ══
│   │   ├── __init__.py
│   │   ├── spis_browser.py        # Playwright SPIS 浏览器自动化
│   │   ├── spis_parser.py         # SPIS 页面解析（DOI/标题/作者/链接提取）
│   │   ├── keyword_cursor.py      # 关键词游标状态机
│   │   ├── dedup.py               # 检索阶段去重（DOI精确 + 标题≥95%）
│   │   └── journal_filter.py      # 期刊白名单过滤 + 双语标题清洗
│   │
│   └── read/                      # ══ 流水线B: 深度阅读 ══
│       ├── __init__.py
│       ├── pdf_extract.py          # PDF 文本提取 + DOI 提取 + 图表提取
│       ├── deepseek_reader.py     # DeepSeek 精读调用 (18字段 + 自检)
│       ├── gemini_vision.py       # Gemini Vision 图表识别
│       ├── figure_analysis.py     # DeepSeek 图表结合论文分析
│       ├── journal_if.py          # 影响因子匹配 (102条 IF 库)
│       └── anti_hallucination.py  # 反幻觉自检 + review_queue 管理
│
├── services/                      # 知识服务
│   ├── __init__.py
│   ├── qa.py                      # 教授级 Q&A 对话
│   ├── retrieval.py               # 混合检索 (token 55% + 语义 45%)
│   ├── concept_map.py             # 100+ 中→英学术术语映射
│   └── briefing.py                # 检索简报生成
│
├── agent/                         # Agent 控制层
│   ├── __init__.py
│   ├── orchestrator.py            # 主编排器（两条流水线协调）
│   ├── state_machine.py           # 论文生命周期状态机
│   ├── run_logger.py              # 结构化运行日志 (AgentRunLogger)
│   ├── ipc.py                     # 信号文件 IPC (暂停/终止)
│   ├── file_lock.py               # 文件级锁 (PID锁, Excel锁)
│   └── watchdog.py                # Watch 模式 (文件夹监控)
│
├── ui/                            # 用户界面（Agent 的两种控制方式）
│   ├── __init__.py
│   ├── app.py                     # Streamlit Web 面板入口
│   ├── worker.py                  # CLI Worker 入口
│   └── components/                # Streamlit UI 组件
│       ├── brand.py               # 品牌 + Logo
│       ├── sidebar.py             # 侧边栏（状态灯 + 导航）
│       ├── agent_panel.py         # Agent 运行控制面板
│       ├── run_history.py         # 运行历史
│       ├── qa_chat.py             # Q&A 对话界面
│       ├── qa_agent.py            # Q&A Agent 模式
│       ├── notes_browser.py       # 文献笔记浏览/搜索
│       ├── dashboard.py           # 知识库仪表盘（统计图表）
│       ├── dashboard_theory.py    # 理论探索
│       ├── dashboard_vars.py      # 变量网络
│       ├── dashboard_future.py    # 未来方向
│       ├── dashboard_search.py    # 文献筛选器
│       ├── management_clean.py    # 清理 PDF
│       ├── management_review.py   # 待复核队列
│       ├── management_reread.py   # 批量重读
│       ├── management_keywords.py # 关键词管理
│       ├── management_status.py   # 系统状态
│       └── data_loader.py         # 数据加载 + 缓存
│
├── tests/                         # 测试（每个模块对应一个测试文件）
│   ├── __init__.py
│   ├── test_stores/
│   │   ├── test_obsidian.py
│   │   ├── test_excel.py
│   │   ├── test_zotero.py
│   │   ├── test_processed_log.py
│   │   └── test_transaction.py
│   ├── test_pipeline/
│   │   ├── test_pdf_extract.py
│   │   ├── test_deepseek_reader.py
│   │   ├── test_dedup.py
│   │   └── test_keyword_cursor.py
│   └── test_services/
│       ├── test_qa.py
│       └── test_retrieval.py
│
├── 待处理文献/                    # PDF 暂存区
├── litcall/                       # Obsidian Vault
├── 运行日志/                      # 日志 + 运行记录
├── config.json                    # 配置文件
├── journal_if.json                # 期刊 IF 库
├── litcall文献汇总.xlsx           # Excel 知识库
├── processed_log.json             # 处理日志
├── requirements.txt
└── SYSTEM_SPEC.md                 # 本文档（权威规格说明）
```

### 模块依赖规则

```
core          ← 零外部依赖，可被所有模块引用
stores        ← 依赖 core，不依赖 pipeline/services/agent/ui
pipeline      ← 依赖 core + stores
services      ← 依赖 core + stores
agent         ← 依赖 core + stores + pipeline + services
ui            ← 依赖 agent（通过 orchestrator 接口）
tests         ← 依赖所有模块

规则：
- 禁止反向依赖（如 stores 引用 pipeline）
- 禁止循环依赖
- 每个模块的 __init__.py 只暴露公共接口
```

---

## 8. 深度阅读管线

### 8.1 18 字段结构化笔记

| # | 字段 | 类型 | 说明 |
|---|------|------|------|
| 1 | 标题 | str | 论文完整标题（原文语言） |
| 2 | 作者 | str | 全部作者，按原文顺序 |
| 3 | 第一作者 | str | — |
| 4 | 通讯作者 | str | — |
| 5 | 年份 | str | 出版年份 |
| 6 | 期刊 | str | 期刊全称 |
| 7 | 影响因子 | str | 本地 IF 库匹配，格式 "9.0 (Q1)" |
| 8 | 分区 | str | JCR Q1-Q4 |
| 9 | doi | str | 从 PDF 提取，经 norm_doi 规范化 |
| 10 | 关键词 | str | 论文关键词 |
| 11 | 研究背景与动机 | str | 现实痛点 → 理论缺口 → 已有研究 → 本文切入点 |
| 12 | 研究问题 | str | RQ/H + 理论推导 + 理论框架/构念关系 |
| 13 | 变量汇总 | str | 每个变量: 名称/类型(IV/DV/中介/调节/控制)/概念定义/测量方式。质性/概念论文留空 |
| 14 | 研究方法 | str | 研究设计/样本/程序/分析方法 |
| 15 | 方法论详解 | str | 建模逻辑、计量方法、识别策略等技术细节深度讲解 |
| 16 | 研究结果 | str | 逐条假设检验 + 核心发现 |
| 17 | 讨论与结论 | str | 结果解释 + 理论/实践含义 + 批判性评述 |
| 18 | 创新点 | str | 理论/方法/实践创新，逐条列出 |
| 19 | 局限与展望 | str | 逐条列出，每条含解释 |
| 20 | 图表分析 | str | Gemini Vision + DeepSeek 图表智能分析（可选） |

### 8.2 DeepSeek API 调用

```
端点:        https://api.deepseek.com/v1/chat/completions
模型:        deepseek-chat (DeepSeek V4 Pro)
上下文窗口:  128K token ← 输入上限（论文全文 15K-30K token 完全在窗口内）
max_tokens:  8192 ← 输出上限（18字段结构化笔记的回复长度，≈中文 6000-8000 字）
temperature: 0.1 (低随机性，确保一致输出)
```

**重要澄清**：8192 是**输出**的最大 token 数，不是输入限制。DeepSeek 的输入上下文窗口是 128K token，一篇 PDF 全文 15K-30K token 完全在输入窗口内。

### 8.3 System Prompt 纪律

```
- 只写原文明确出现的信息，不推断、不补充、不美化
- 数字与原文严格一致 (n=207 就是 207，不是"约200")
- 原文没提到的内容，笔记里自然就没有
- 深度来自透彻理解与清晰转述，非脑补细节
- 中文撰写，专业术语保留英文+中文括号标注
- 术语统一使用全称，禁止附加缩写（如 "Technology Acceptance Model (TAM)" — 禁止，只用全称）
```

### 8.4 PDF 文本提取

```python
def extract_text_from_pdf(pdf_path: Path) -> Optional[str]:
    """
    PyMuPDF (fitz) 逐页提取全文。
    使用 with 语句确保文档句柄关闭。
    失败返回 None。
    """
    try:
        with fitz.open(pdf_path) as doc:
            pages = []
            for page in doc:
                pages.append(page.get_text())
        return "\n".join(pages)
    except Exception as e:
        logger.error(f"PDF 文本提取失败: {pdf_path.name} — {e}")
        return None
```

### 8.5 DOI 提取三策略

```python
def extract_doi_from_pdf(pdf_path: Path) -> Optional[str]:
    """
    策略 1: 前 3 页搜索 DOI 模式 (10.xxx/xxx)
    策略 2: 全文搜索 DOI 模式
    策略 3: 文件名提取 (下划线/连字符分割)
    全部结果经 norm_doi() 规范化。
    """
```

### 8.6 Gemini 图表识别（可选）

```
启用条件: config.json → enable_figure_analysis = true + gemini_api_key 存在
流程:
  1. PyMuPDF 提取 PDF 中的图片/表格 → PNG
  2. Gemini Vision API 识别图表内容 (标题、类型、关键数据)
  3. DeepSeek 对图表做结合论文的分析
```

---

## 9. 去重体系

### 9.1 检索阶段去重（Search Pipeline）

```
Layer 1: DOI 精确匹配 (norm_doi 规范化后 lowercase 对比)
   数据源: Zotero API (collection 列表) + processed_log.json + Excel DOI 列
   这是主防线。DOI 经过 norm_doi() 统一格式后精确匹配。

Layer 2: 标题高阈值模糊匹配 (SequenceMatcher ≥ 95%)
   数据源: 同上
   仅在 DOI 缺失时作为辅助防线。
   学术论文标题几乎都是一模一样才叫重复，95% 以下视为不同论文。

Layer 3: 同一批次内去重
   当前检索轮次内 DOI/标题 比对

Layer 4: Obsidian DOI 扫描
   防止跨语言、跨关键词的漏网之鱼
```

### 9.2 为什么标题阈值是 95% 而不是 80%？

- 两篇不同的学术论文标题不会 80% 相似
- 80% 太容易误匹配（如 "The Impact of AI on Consumer Trust" vs "The Impact of AI on Consumer Behavior" — 85% 相似但是完全不同的论文）
- DOI 精确匹配是第一道防线；标题匹配只在 DOI 缺失时做辅助
- 95% 只会在标点/大小写/空格差异时匹配，这才叫重复

### 9.3 处理阶段去重（Read Pipeline）

```
预处理去重:
  - DOI 匹配 processed_log → 跳过（已完成）
  - 文件名匹配 processed_log → 跳过（防 DOI 提取失败导致的重复）

Excel 去重:
  - DOI 匹配 → 填充已有行的空字段（不是跳过！）
  - 这修复了"跳过已存在但不完整"的裂行 bug

Zotero 去重:
  - 列出最近条目比对 DOI（不是搜索 API！）
  - Zotero 搜索 API 不索引 DOI 字段

Obsidian 去重:
  - 文件存在检查
  - Agent 模式下始终 force=True（覆写）
```

---

## 10. 反幻觉质量控制

### 10.1 三道防线

```
┌─────────────────────────────────────────────┐
│ 防 线 1: Prompt 纪律                         │
│ • "只写原文明确出现的信息，不推断不编造"       │
│ • "数字与原文严格一致"                        │
│ • temperature=0.1 (低随机性)                  │
├─────────────────────────────────────────────┤
│ 防 线 2: 二次 API 自检                       │
│ • 变量汇总是否遗漏？(定量实证论文该有但为空？)  │
│ • 关键数字是否与原文一致？                     │
│ • 是否存在原文中没有的事实性陈述？              │
│ • 轻量调用，失败不阻塞主流程                   │
├─────────────────────────────────────────────┤
│ 防 线 3: review_queue.json 人工复核队列       │
│ • 自检失败 → 加入复核队列                      │
│ • Web 管理面板「待复核」tab 查看               │
│ • 支持 DeepSeek 针对性修复                    │
└─────────────────────────────────────────────┘
```

### 10.2 变量交叉校验

定量实证论文 → 变量汇总不应为空 → 检查 RQ/方法是否暗示了变量 → 发现遗漏自动补充

---

## 11. SPIS 检索系统

### 11.1 浏览器自动化

```
工具:     Playwright (Chromium)
登录态:   persistent context (Cookie 持久化)
SPIS URL: https://spis.hnlat.com
```

### 11.2 检索流程

```
1. 读关键词游标 → 获取当前关键词
2. 打开 SPIS → 输入关键词 → 搜索
3. 设置年份过滤 (2020-2026)
4. 翻页抓取:
   - 提取: title, authors, year, journal, doi, download_url
   - 去重 (四层)
   - 期刊白名单过滤 (60+ UTD24/FT50 顶刊)
   - 双语标题清洗
5. 满 N 篇 / 关键词穷尽 → 停止
6. 保存游标 → 生成简报 → 通知用户
```

### 11.3 期刊白名单

```
UTD24: Journal of Marketing, Journal of Consumer Research, Marketing Science,
       Management Science, Journal of Marketing Research...
FT50:  (UTD24 超集)
用户自定义: config.json → journal_whitelist_extra
```

### 11.4 双语标题清洗

```
SPIS 返回: "人工智能对消费者行为的影响研究 / The Impact of AI on Consumer Behavior"
规则: 左半有中文 + 右半无中文 → 保留左半中文
     右半有中文 + 左半无中文 → 保留右半
```

---

## 12. 关键词游标状态机

### 12.1 三级迭代

```
┌──────────┐               ┌──────────┐               ┌──────────┐
│  BROAD   │──────────────►│  NARROW  │──────────────►│ CHINESE  │
│  宽泛匹配 │  逐关键词推进  │  精确匹配 │  逐关键词推进  │  中文搜索 │
└──────────┘               └──────────┘               └──────────┘
                                                             │
                                                全部穷尽 ─────┘
                                                             │
                                                             ▼
                                                通知用户 + 重置为仅检索当年
```

### 12.2 游标存储

```json
// config.json → _keyword_cursor
{
  "category_index": 0,
  "keyword_index": 3,
  "completed_keywords": ["关键词1", "关键词2"]
}
```

### 12.3 设计约束

- 每个关键词完成后**原子写回** config.json (temp + rename)
- 崩溃安全：游标始终在最后一个**已完成**的关键词位置
- keyword_override：一次性自定义关键词，忽略游标，不持久化

---

## 13. 知识库问答 (Q&A)

### 13.1 混合检索架构

```
用户问题 (中文)
    │
    ├─ 年份过滤: 正则提取年份范围
    │
    ├─ 概念扩展: 100+ 中→英学术术语映射
    │   "人工智能信任" → "AI trust, artificial intelligence confidence..."
    │
    ├─ Token 匹配 (55% weight)
    │   ├─ 中文 bigram tokenization
    │   ├─ 英文 word tokenization
    │   └─ 加权打分: title×4 / keywords×3 / body×1.5 / journal×1
    │
    ├─ 语义重排 (45% weight)
    │   ├─ 字符 3-gram + 4-gram TF-IDF
    │   ├─ Cosine similarity (L2 normalized)
    │   └─ 语言无关 (中英文统一)
    │
    └─ 智能回退: 年份放宽 → 全库检索 → 最新文献兜底
```

### 13.2 Q&A 命令

| 命令 | 功能 |
|------|------|
| `/exit` | 退出 Q&A |
| `/save` | 保存对话到 `litcall/QA笔记/` |
| `/clear` | 清空对话历史 |
| `/papers` | 重新显示上一轮匹配的本地文献 |
| `/n N` | 设置检索数量 (默认8, 范围3-15) |
| `/external` | 切换外部知识开关 |
| `/help` | 显示帮助 |

---

## 14. 控制层设计

### 14.1 主编排器 (Orchestrator)

```python
class LitCallOrchestrator:
    """
    Agent 主编排器。
    协调两条独立流水线 + 四库引擎 + 信号控制。
    """

    async def start(self, mode: str):
        """
        mode:
          - "full": 检索 + 阅读 (VPN 连通时)
          - "read_only": 仅阅读 (VPN 未连时 / 用户选择)
        """
        ...

    async def pause(self):
        """暂停：完成当前论文后停止"""
        ...

    async def resume(self):
        """恢复：继续处理"""
        ...

    async def terminate(self):
        """终止：立即停止"""
        ...

    def status(self) -> AgentStatus:
        """返回当前运行状态"""
        ...
```

### 14.2 信号文件 IPC

```
运行日志/.pause       — 存在 = 暂停请求
运行日志/.terminate   — 存在 = 终止请求

检查点: 每篇论文的每个步骤前后
暂停行为: 完成当前论文 → 阻塞轮询 (1s) → 等待 .pause 删除
终止行为: raise AgentSignalError → 优雅退出
```

### 14.3 结构化运行日志

每次 Agent 运行生成一个 JSON 文件到 `运行日志/runs/{run_id}.json`，包含：

- 运行配置 (年份、关键词、篇数限制)
- Phase 进展 + 心跳时间戳
- 每篇论文的处理状态 + 核心摘要
- 错误诊断信息

心跳检测：300s 无心跳 → 标记 crashed → UI 允许新启动
**心跳阈值只能在一处定义**（AgentRunLogger 默认值），所有调用方不传参。

---

## 15. 用户界面

### 15.1 Agent 是唯一入口

- **CLI** (`ui/worker.py`)：命令行界面，用于本地调试、cron 定时任务
- **Web** (`ui/app.py`)：Streamlit 面板，用于日常监控和交互

两者调用同一个 `LitCallOrchestrator`，共享所有逻辑。**不再有终端 vs Agent 的双轨制。**

### 15.2 Streamlit Web 面板 (5 页面)

```
sidebar:
  ├── 品牌标识
  ├── 四库计数 (实时)
  ├── Agent 状态灯 (🟢空闲 / 🔵运行中 / 🔴崩溃)
  └── 页面导航

[1] 知识库问答 — chat 对话 + Agent 模式
[2] 文献笔记   — 浏览/搜索/排序
[3] Agent      — 启动/控制/运行历史/实时进度
[4] 知识库仪表盘 — 统计图表/理论探索/变量网络/未来方向
[5] 管理       — 清理/复核/重读/关键词/系统状态
```

### 15.3 CLI Worker 入口

```bash
python -m litcall.ui.worker --mode full --year-start 2025 --year-end 2026 --target-papers 5
python -m litcall.ui.worker --mode read_only  # 仅深度阅读（无需VPN）
python -m litcall.ui.worker --mode watch       # Watch 模式
```

---

## 16. 错误恢复与自愈

### 16.1 Excel 自愈

```
Excel 损坏 → _validate_excel() 确认 → 备份损坏文件
→ _rebuild_excel_from_obsidian() (从 Obsidian frontmatter 重建完整数据)
→ 最终回退: 空白 Excel (仅表头)
→ ⚠ 绝不从 processed_log 创建 DOI-only 骨架行
```

### 16.2 Worker 自愈

```
Worker 崩溃 → 指数退避重试 (5s→10s→20s, 最多3次)
→ 自动清理 Chrome 残留进程
→ 3次全失败 → 人工介入提示

PID 锁: worker.pid → 检测已有 Worker → 防止同时启动多个
心跳超时 (300s): UI 检测 → 标记 crashed → 允许新启动
```

### 16.3 核心保护规则

| 规则 | 工具 |
|------|------|
| 不信任 API 返回值 | 四库自检 (verify_paper_in_all_stores) |
| 删除前验证 | PDF 只在四库自检全通过后删除 |
| 原子写入 | temp 文件 + replace (用于 config, processed_log, Excel, run_log) |
| 不掉异常 | 所有 try/except 必须至少 log (绝不允许 `except: pass`) |
| 文件锁 | Excel 写入锁 + Worker PID 锁 |
| 崩溃恢复 | Worker 指数退避重试 + Chrome 进程清理 |

---

## 17. 外部服务依赖

| 服务 | 用途 | 限制 | 成本 |
|------|------|------|------|
| DeepSeek API | 深度阅读 + Q&A + 自检 | 60 RPM | ~$0.01-0.03/篇 |
| Zotero API | 文献入库/验证 (DOI+PDF) | 未公开 | 免费 |
| Gemini Vision | 图表识别 (可选) | 1500/天免费 | 免费 |
| Playwright | SPIS 浏览器自动化 | — | 免费 |
| Unpaywall | 公开 OA PDF 下载 | 未公开 | 免费 |
| Semantic Scholar | PDF 下载回退 | 100/5min | 免费 |
| OpenAlex | 影响因子回退 | 未公开 | 免费 |

---

## 18. 配置管理

### 18.1 config.json 结构

```json
{
  "deepseek_api_key": "sk-...",
  "deepseek_model": "deepseek-chat",
  "gemini_api_key": "...",
  "enable_figure_analysis": false,
  "zotero": {
    "user_id": "数字ID",
    "api_key": "...",
    "collection_name": "litcall"
  },
  "keywords": {
    "broad": [["AI marketing", "broad"], ...],
    "narrow": [["consumer AI trust", "narrow"], ...],
    "chinese": [["人工智能营销", "chinese"], ...]
  },
  "journal_whitelist_extra": [],
  "min_year": 2020,
  "unpaywall_email": "your@email.com",
  "_keyword_cursor": {
    "category_index": 0,
    "keyword_index": 0,
    "completed_keywords": []
  }
}
```

### 18.2 安全

```
config.json → .gitignore (真实 API key，绝不提交)
config.example.json → 已提交 (placeholder，供新用户参考)
```

---

## 19. 铁律清单

**任何修改、任何决策不得违反以下任何一条。违反后果写在这里，不要说"这次是例外"。**

| # | 铁律 | 详细说明 | 违反后果 |
|---|------|---------|---------|
| 1 | **治本不治标** | 看到异常 → 追根因 → 修复根因 → 验证不再复发。不允许 try/except pass 吞错误、加 fallback 绕过、加 if 跳过 | 同一 bug 反复出现，信用归零 |
| 2 | **四库全部成功** | Obsidian + Excel + Zotero 全部成功写入 + 全部验证通过，才标记已处理 + 删 PDF。任一失败 → 全部回滚 → PDF 保留 | 静默丢数据 |
| 3 | **四库数量一致** | 四个库的文献数必须完全一致。不一致即 bug。每次运行后做跨库审计 | 数据混乱，无法信任任何库 |
| 4 | **全文深度阅读，逐篇处理** | 不截断，不批量。DeepSeek 128K 上下文足够 | 阅读质量下降，笔记空洞 |
| 5 | **暂停/终止即时响应** | 每个论文级操作前后检查信号文件。暂停 = 完成当前论文后停止。终止 = 立即停止 | 用户失控 |
| 6 | **先验证再操作** | 任何数据变更前交叉校验四库状态。删除前验证。去重前验证 | 盲目操作，数据灾难 |
| 7 | **DOI 唯一键** | 所有跨库操作以 norm_doi(doi) 为主键。DOI 规范化：去引号、逗号、垃圾后缀、统一小写 | 去重全部失效，重复堆积 |
| 8 | **跳过 = 检查完整性** | 已存在的记录 → 填充空字段，不是跳过。这修复了 Excel 裂行的根因 | 半空骨架行堆积 |
| 9 | **Agent 路径禁止 print()** | Windows GBK 控制台无法编码 emoji → UnicodeEncodeError → Worker 静默崩溃。用 logger.info() 代替。logger 始终写 UTF-8 文件 | Worker 反复崩溃，用户看到"0篇/crashed" |
| 10 | **Zotero 搜索 API 不索引 DOI** | `GET /items?q={doi}` 永远返回 0 结果（ES 把 DOI 中的 . / 当词边界分割）。代码中所有对 Zotero 搜索 API 的 DOI 搜索必须替换为：列出最近条目比对 DOI 或直接 GET /items/{item_key} | 去重失败、自检全部误报、重复条目堆积 |
| 11 | **Zotero 只传 DOI + PDF** | 创建条目时只传 DOI 和 PDF 附件。让 Zotero 通过 Crossref/PubMed 自行拉取元数据。比 DeepSeek 提取的更准确 | 冗余代码 + 数据不一致 |
| 12 | **不重复犯错** | 修复后必须有对应的验证机制（grep 代码中所有同类问题点，确保全部修复）。记录到本文档附录 | 同一个 bug 复发（本次会话出现 3 次） |

---

## 20. 当前代码向新架构的迁移路径

### 20.1 当前状态

```
literature_agent.py  (~9700 行单体)
  ├── 终端菜单 main()                    → 废弃，融入 Agent
  ├── 终端阅读 deep_read_only_flow()     → 搬入 pipeline/read/
  ├── 终端入库 入库_only_flow()           → 搬入 stores/zotero.py
  ├── Agent 会话 full_autonomous_session() → 拆入 agent/orchestrator.py
  ├── SPIS 检索 (~2000 行)               → 搬入 pipeline/search/
  ├── Q&A (~1000 行)                     → 搬入 services/
  └── 工具函数/常量                       → 搬入 core/

app.py (~2800 行)
  ├── 5 个页面 + 侧边栏                   → 拆入 ui/components/
  └── 数据加载/缓存                       → ui/components/data_loader.py

run_agent_worker.py (~140 行)            → ui/worker.py
```

### 20.2 迁移原则

1. **先建目录，再搬代码**：新目录结构先就位，逐个模块迁移
2. **先写接口，再实现**：每个模块先定义 `__init__.py` 的公共接口
3. **搬一个，测一个**：迁移一个模块 → 写测试 → 验证通过 → 再搬下一个
4. **旧代码保留**：迁移期间旧代码不删，新架构并行验证
5. **四库引擎优先**：`stores/` 是最核心的模块，第一个迁移
6. **终端不保留**：迁移完成后，终端入口删除，Agent 是唯一入口

### 20.3 迁移顺序

```
Phase 1: 基础设施
  - core/config.py, core/paths.py, core/encoding.py, core/logging.py
  - stores/base.py (AbstractStore 接口)

Phase 2: 四库引擎（最关键）
  - stores/processed_log.py
  - stores/obsidian.py
  - stores/excel.py
  - stores/zotero.py
  - stores/transaction.py (原子事务)
  - stores/audit.py (跨库审计)

Phase 3: 阅读流水线
  - pipeline/read/pdf_extract.py
  - pipeline/read/deepseek_reader.py
  - pipeline/read/gemini_vision.py
  - pipeline/read/anti_hallucination.py
  - pipeline/read/journal_if.py

Phase 4: 检索流水线
  - pipeline/search/spis_browser.py
  - pipeline/search/keyword_cursor.py
  - pipeline/search/dedup.py
  - pipeline/search/journal_filter.py

Phase 5: 控制层
  - agent/orchestrator.py
  - agent/state_machine.py
  - agent/run_logger.py
  - agent/ipc.py
  - agent/watchdog.py

Phase 6: 知识服务
  - services/qa.py
  - services/retrieval.py
  - services/concept_map.py
  - services/briefing.py

Phase 7: UI
  - ui/worker.py (CLI)
  - ui/app.py + components (Web)

Phase 8: 测试
  - 每个模块的单元测试
  - 集成测试（完整处理一篇 PDF 的端到端链路）
```

### 20.4 数据文件（不受迁移影响）

以下文件是数据，不是代码，迁移过程中保持不变：
- `config.json`, `journal_if.json`
- `processed_log.json`
- `litcall文献汇总.xlsx`
- `litcall/` (Obsidian Vault)
- `待处理文献/`
- `运行日志/`

---

## 附录 A: 22 个已知 Bug 状态总览

| # | 严重度 | 名称 | 根因 | 状态 | 在新架构中如何根本解决 |
|---|--------|------|------|------|----------------------|
| 1 | 🔴 | 30 篇 PDF 丢失 | 信任 API 返回值，不验证 | ✅ | 四库原子事务 + 自检后才删 PDF |
| 2 | 🔴 | Zotero 双 collection | Agent 崩溃重试创建同名 | ✅ | collection 按条目数 tiebreak |
| 3 | 🔴 | DOI 字段大小写 | `d.get('doi')` 但 API 返回 `data.DOI` | ✅ | ZoteroStore 统一用 `d.get('DOI') or d.get('doi')` |
| 4 | 🔴 | Excel 裂行 | "跳过已存在 DOI" → 数据不完整 | ✅ | 填充空字段，不跳过 |
| 5 | 🔴 | DOI 格式污染 | 尾部逗号、垃圾字符未清洗 | ✅ | norm_doi() 所有入口 |
| 6 | 🔴 | norm_doi 过于激进 | 正则 `[A-Z]{3,}` 误杀合法期刊缩写 | ✅ | 改为已知垃圾关键词白名单 |
| 7 | 🟡 | Obsidian 截断重复目录 | 30 字符截断太短 | ✅ | 不再截断期刊名 |
| 8 | 🟡 | untitled 目录 | 空期刊名 → "untitled" | ⚠️ | 写入前检查 + 从其他来源填充期刊名 |
| 9 | 🟡 | frontmatter DOI 引号 | 正则不 strip 引号 | ✅ | 解析时统一 strip |
| 10 | 🟡 | 交叉校验缺失 | 第一版去重脚本不看跨库差异 | ✅ | cross_library_audit 在每次运行后自动执行 |
| 11 | 🔴 | GBK 编码崩溃 | Windows GBK 无法编码 emoji → print() 崩溃 | ✅ | 模块级 UTF-8 安全网 + Agent 路径禁止 print() |
| 12 | 🔴 | 多 Worker 重叠 | 无 PID 锁 + 心跳阈值太短 | ✅ | PID 文件锁 + 300s 心跳统一阈值 |
| 13 | 🔴 | Excel BadZipFile | 多进程并发写入无锁 | ✅ | Excel 文件锁 + 自愈机制 |
| 14 | 🟡 | PDF 删除失败 → 重复处理 | 文件被占用 + 去重只查 DOI | ✅ | 删除重试(3次) + DOI+文件名双键去重 |
| 15 | 🟡 | Zotero 双 collection | 见 #2 | ✅ | 见 #2 |
| 16 | 🔴 | GBK 崩溃复发 | 只修了 worker.py 没修 literature_agent.py | ✅ | 模块级安全网 + 全局禁止 Agent 路径 print() |
| 17 | 🔴 | 心跳阈值不一致 | AgentRunLogger 300s 但 app.py 硬编码 90s | ✅ | 单一默认值源，所有调用方不传参 |
| 18 | 🔴 | Zotero 搜索不索引 DOI | ES 把 DOI 的 ./ 当词边界 | ✅ | 验证用直接 GET /items/{key}，去重用列表比对 |
| 19 | 🟡 | log_phase2 未调用 | 方法写了但没接线 | ✅ | 在 Orchestrator 中显式调用 |
| 20 | 🟡 | cross_library_audit Auth Header | 用了 Bearer 不是 Zotero-API-Key | ✅ | ZoteroStore 统一认证 |
| 21 | 🔴 | Streamlit 随 session 挂 | Popen 是 session 子进程 | ✅ | DETACHED_PROCESS 脱离进程树 |
| 22 | 🔴 | _ensure_excel_valid 破坏 Excel | 从 processed_log 恢复 → DOI-only 骨架行 | ✅ | 从 Obsidian 恢复（有完整配对数据），processed_log 不用于恢复 |

---

## 附录 B: 代码搜索速查

```bash
# 异常静默吞噬（每个都是潜在的数据丢失点）
grep -n "except.*:" **/*.py | grep -A1 "pass\|continue"

# 数据删除操作（必须审核每个调用点）
grep -rn "\.unlink()\|os\.remove\|shutil\.rmtree" **/*.py

# Zotero 搜索 API（铁律 #10 违规）
grep -n "users.*items.*q=" **/*.py

# print() 在 Agent 路径中（铁律 #9 违规）
grep -n "^[^#]*print(" litcall/pipeline/**/*.py litcall/agent/**/*.py

# Zotero API 认证错误（铁律 #10）
grep -n "Authorization: Bearer" **/*.py

# DOI 字段只查小写（Bug #3）
grep -n "\.get('doi')" **/*.py | grep -v "\.get('DOI')\|\.get('doi') or"
```

---

*本文档是 LitCall 的权威规格说明。当代码与文档冲突时，以此文档为准。*
*任何对本文档的修改必须经过用户确认。*
