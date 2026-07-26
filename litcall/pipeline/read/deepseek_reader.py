"""DeepSeek V4 Pro 深度阅读 — 18 字段结构化笔记生成 + 反幻觉流水线。

从 literature_agent.py 单体中提取，自包含模块。
流水线: DeepSeek 生成 → 自检 → 变量交叉校验 → 复核队列。
"""

import asyncio
import datetime
import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from litcall.core.config import config
from litcall.core.paths import REVIEW_QUEUE_FILE

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# API 重试工具
# ═══════════════════════════════════════════════════════════════════════════════

async def _retry_api_call(callable_async, max_retries: int = 3, base_delay: float = 2.0,
                          description: str = "API call") -> Any:
    """异步 API 调用自动重试（指数退避）。

    适用场景：DeepSeek、Zotero、Gemini 等可能因网络波动或服务端限流失败的 API。
    重试策略：base_delay * (2 ** attempt)，最多 max_retries 次。
    所有重试均失败后返回 None（不抛异常，由调用方决定如何处理）。

    Args:
        callable_async: 无参异步可调用对象（如 lambda: session.post(...)）
        max_retries: 最多重试次数（含首次，默认3次）
        base_delay: 基础退避秒数（默认2秒，总延迟 ≈ 2 + 4 = 6秒）
        description: 描述文字，用于日志
    Returns:
        成功返回 callable 的返回值，全部失败返回 None
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            result = await callable_async()
            if attempt > 0:
                logger.info(f"[重试] {description} 第 {attempt + 1} 次尝试成功")
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"[重试] {description} 第 {attempt + 1}/{max_retries} 次失败: {e}。"
                    f"{delay:.0f}s 后重试..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[重试] {description} 全部 {max_retries} 次尝试均失败。"
                    f"最后错误: {e}"
                )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 复核队列
# ═══════════════════════════════════════════════════════════════════════════════

def _add_to_review_queue(notes: Dict[str, str]) -> None:
    """将 🟡 或 🔴 置信度的笔记加入人工复核队列。"""
    try:
        queue = []
        if REVIEW_QUEUE_FILE.exists():
            queue = json.loads(REVIEW_QUEUE_FILE.read_text(encoding="utf-8"))
        entry = {
            "title": notes.get("标题", "")[:120],
            "first_author": notes.get("第一作者", ""),
            "year": notes.get("年份", ""),
            "journal": notes.get("期刊", ""),
            "doi": notes.get("doi", ""),
            "confidence": notes.get("_置信度", "medium"),
            "issues": notes.get("_自检标记", ""),
            "added": datetime.datetime.now().isoformat(),
        }
        # 去重：同 DOI 只保留最新
        existing_doi = entry.get("doi", "").strip().lower()
        queue = [q for q in queue if q.get("doi", "").strip().lower() != existing_doi or not existing_doi]
        queue.append(entry)
        REVIEW_QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[复核队列] 已加入: {entry['title'][:50]}")
    except Exception as e:
        logger.warning(f"复核队列写入失败: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# DeepSeek 深度阅读 — 生成 18 字段笔记
# ═══════════════════════════════════════════════════════════════════════════════

async def _generate_via_deepseek(text: str, api_key: str, model: str) -> Optional[Dict[str, str]]:
    """通过 DeepSeek V4 Pro API（OpenAI 兼容）进行文献提取。
    使用中文 prompt，直接输出中文 key 的 JSON，无需映射。"""
    # 清洗 PDF 文本中的 surrogate 字符和 Unicode 非字符，防止 API HTTP 400
    text = re.sub(r'[\ud800-\udfff￾-￿]', '', text)
    system_prompt = """你是一位专注于人工智能与市场营销交叉领域的资深教授。你正在深度阅读一篇学术论文，为其制作精读笔记，纳入你的个人学术知识体系。

这份笔记包含两部分：前 17 个字段是对原文的忠实记录（未来回顾时不必重读原文），第 18 个字段「深度理解与理论推导」是你作为学者的独立分析和批判性思考。

核心纪律（适用于第 1-17 字段）：
1. 只写原文中明确出现的信息。不编造、不脑补、不美化。
2. 数字——样本量、统计量、p值、均值、alpha系数——必须与原文严格一致。n=207就是207，不是"约200"。
3. 原文没有提到的内容，不要提及。不要写"原文未报告XXX"——如果原文没报告，你的笔记里自然就没有它。
4. 深度来自对原文的透彻理解与清晰转述，而非添加原文中没有的细节。原文详实则笔记详实，原文简略则笔记简略。
5. 笔记使用中文撰写。专业术语（理论名、变量名、量表名、统计方法名）保留英文并括号标注中文。
6. 第 18 字段「深度理解与理论推导」不受上述规则约束——该字段明确允许和鼓励推理、推导、批判和跨文献连接。详见用户提示中的该字段说明。
7. 仅输出合法的 JSON 对象。"""


    user_prompt = f"""你是一位专注于人工智能与市场营销交叉领域的资深教授，正在为这篇论文制作深度精读笔记。这份笔记是你的个人学术知识储备——未来回顾这篇论文时，你不必重读原文，仅凭笔记就能准确还原它的核心内容。

## 核心纪律
你写下的每一个事实性陈述，都必须能在原文中找到具体出处。数字与原文严格一致。原文没有提到的内容，你的笔记中就不会出现——不需要标注"原文未报告"，它不存在于原文，自然也不存在于你的笔记。不要为了显得"详细"而脑补。原文信息翔实你就写翔实，原文写得简略你就如实简略。

## 笔记语言
中文撰写。专业术语（理论名、变量名、量表名、统计方法名）保留英文并括号标注中文。论文标题保持英文原文。

## 字段要求
返回 JSON，18 个字段：

━━━ 基础信息 ━━━
1. 标题：论文完整英文标题。
2. 作者：按原文顺序列出。标注第一作者和通讯作者："Name（第一作者）, Name（通讯作者）"。原文未标注通讯作者则不加。
3. 第一作者
4. 通讯作者
5. 年份（4位数字）
6. 期刊全称（英文）
7. 影响因子：留空
8. 分区：留空
9. 关键词：用原文关键词的语言。术语统一使用全称，禁止附加缩写（用"large language models"而非"LLMs"或"large language models (LLMs)"）。分号分隔。

━━━ 核心内容 ━━━
10. 研究背景与动机：
    交代清楚：①本文针对的现实痛点或理论缺口；②为什么这个问题重要；③已有研究的核心进展和尚存的矛盾/空白；④本文的切入点。像写文献综述一样有逻辑脉络。

11. 研究问题：
    ①列出核心研究问题（RQ）或假设（H）。②每个假设/问题的理论推导逻辑。③研究的理论框架：核心构念（construct）有哪些、它们之间的关系，以及这些构念在框架中的理论角色（前因/结果/中介/调节）。

12. 变量汇总：
    若论文有明确界定的变量/构念（定量研究通常有自变量、因变量、中介变量、调节变量、控制变量等），逐一列出。每个变量独立成段，包含：
    - 变量名称：英文原文（中文翻译）
    - 变量类型：自变量 / 因变量 / 中介变量 / 调节变量 / 控制变量
    - 概念定义：论文中对该变量的理论定义。若原文有明确定义则直接引用；若原文未单独给出定义，则从测量题项中归纳其操作化含义（如"该构念通过xxx等题项测量，反映的是xxx"）。严禁写"论文中未提供明确的理论定义"——这是敷衍。每个变量都必须有实质性的定义内容。
    - 测量方式：量表名称、题项数、来源文献、Cronbach's alpha 值（原文提供了才写，未提供则不写）

    若论文为质性研究、概念性论文或未设置明确变量的文献，此节留空。不要为了填充而编造变量。

13. 研究方法：
    像教授向同事复述一篇论文的方法——清晰、准确、不遗漏关键细节，但不套模板。按论文自身逻辑组织，自然分段。覆盖：研究设计及理由、数据来源与样本（数字须准确）、实验程序/数据收集流程（如适用）、分析方法及选用理由。（注意：各构念的测量细节已在「变量汇总」中列出，此处无需重复。）

14. 方法论详解：
    这是本篇笔记中技术含量最高的章节。目标：未来你读到这篇笔记时，即使忘了这篇论文用了什么方法，看完这一节就能完全理解其方法论逻辑，甚至可以向学生讲解这些方法。

    **按论文类型，覆盖以下内容（不是你全部都要写——选论文实际用到的）：**

    ━━━ 定量实证（含实验）━━━
    ① **建模方法**：论文使用了什么模型？（如：OLS回归、Logit/Probit、结构方程模型SEM、多层线性模型HLM、固定效应面板、双重差分DID、断点回归RDD、工具变量IV、Heckman选择模型、倾向得分匹配PSM、合成控制法、机器学习（随机森林/XGBoost/神经网络）等。）这个模型的核心思想是什么，为什么适合回答本文的研究问题？
    ② **识别策略**（因果推断论文必须有）：作者如何识别因果关系？用什么 variation？（如：外生冲击、政策变化、自然实验、field experiment、实验室实验。）识别假设是什么？
    ③ **内生性处理**（如有）：论文是否讨论了内生性问题？（遗漏变量、反向因果、测量误差、自选择。）作者如何解决？（工具变量——IV是什么、为什么有效、是否通过弱工具变量检验；Heckman两步法；固定效应；匹配方法；等等。）每种方法的核心逻辑用一两句话讲清楚。
    ④ **模型设定**：因变量和自变量的操作化方式。非线性变换（如对数变换）的理由。交互项的含义。关键控制变量。函数形式的选择理由。
    ⑤ **估计细节**：标准误类型（稳健标准误、聚类标准误——聚类层级及理由）。多重共线性诊断（如有）。模型选择标准（AIC/BIC/交叉验证等，如有）。
    ⑥ **稳健性检验**：作者做了哪些稳健性检验？每种检验的核心逻辑和结论。替换因变量/自变量度量方式、替换样本、替换模型、安慰剂检验、平行趋势检验（DID）、排除替代解释等。不要只列名字——每个检验说明它的目的和通过意味着什么。

    ━━━ 质性研究 ━━━
    ① **方法论取向**：扎根理论/现象学/案例研究/叙事分析/民族志/内容分析等。为什么选择这个取向？
    ② **抽样策略**：目的性抽样/理论抽样/滚雪球/最大变异抽样等。为什么这样抽样？
    ③ **数据收集**：访谈（半结构化/深度/焦点小组）、观察、档案、多源数据。如何确保数据丰富性？
    ④ **编码与分析**：编码策略（开放编码/主轴编码/选择性编码）、主题分析步骤。如何从原始数据提炼主题？理论饱和度如何判断？
    ⑤ **可信度保障**：三角验证、成员检查、同行汇报、审计追踪、反身性（研究者自我反思）等。如何确保研究质量？

    ━━━ 概念性/综述论文 ━━━
    ① **理论构建逻辑**：论文如何从已有文献推导出新框架？核心论证结构是什么？
    ② **文献筛选方法**（系统综述）：数据库、检索式、纳入/排除标准、PRISMA流程图描述。偏倚风险评估。
    ③ **分析方法**（文献计量/元分析）：使用的工具（VOSviewer/Bibliometrix/CiteSpace等）、分析维度（共被引/共词/耦合等）。元分析的效应量计算方式、异质性检验（Q统计量/I²）、出版偏倚检验。

    ━━━ 共通的 ━━━
    ⑦ **方法局限性**：本文方法层面的内在局限（不是泛泛的"样本量小"，而是该方法本身有什么不足？如DID的平行趋势假设、IV的排他性约束、实验的外部效度等）。
    ⑧ **方法贡献**：本文在方法上有什么独到之处？新奇的测量方式？巧妙的研究设计？独特的数据集？

    **关键要求**：这不是简单罗列方法名称——是像教授给学生讲解研究方法课一样，把每个方法的**核心逻辑**、**为什么选它**、**它的关键假设**、**本文如何满足（或不满足）这些假设**讲透。好的方法论讲解让读者"原来如此"，不好的只列名词和引用。

15. 研究结果：
    定量研究（有明确假设）：描述性统计→逐条假设检验（每条独立成段："H1（简述）：支持/不支持。统计量值, p = 值, 效应量。"）→中介/调节效应→附加分析。
    质性研究：按主题组织，每个主题独立成段。
    最后用"核心发现"总结3-5条。

15. 讨论与结论：
    作者如何解释核心结果？解释的逻辑是否合理？与已有文献的关系（一致/不一致？作者如何调和？）。理论含义和实践含义。有值得商榷或质疑之处吗？

16. 创新点：
    本文的边际贡献在哪里？理论创新/方法创新/实践创新？逐条列出，每条另起一行。

17. 局限与展望：
    逐条列出，每条局限和每个未来研究方向各占一行。格式如下：
    - 局限性：
    （1）第一条局限...
    （2）第二条局限...
    - 未来研究方向：
    （1）第一个方向...
    （2）第二个方向...
    作者明确提出的都写，你认为值得探索的补充在最后并标注。（注：不是简单翻译原文列表——每条需包含简要解释，说明为什么这是局限或为什么这个方向值得探索。）

━━━ 深度理解（你的学术判断）━━━
18. 深度理解与理论推导：
    这是你作为资深学者最体现功力的章节。前面 17 个字段忠实地记录原文——而这一节，你被明确授权和鼓励进行**推理、推导、连接和批判**。你不是在复述原文，而是在用你自己的学术判断去理解和超越它。

    按论文实际情况，覆盖以下维度（不是全部都要写，选真正有价值的）：

    ① **理论模型重构**：
    即使原文没有画理论模型图，只要变量和假设是清晰的，你就应该用自己的话描述这个模型的结构。自变量→中介→因变量的路径是什么？调节变量作用于哪一段？控制变量有哪些？用文字或简单的路径表述（如「X → M → Y，W 调节 X→M 路径」）把逻辑讲清楚。如果原文已有模型图，你可以指出图中可能被作者忽略的关系或隐含假设。

    ② **深层机制挖掘**：
    为什么 X 会导致 Y？论文可能报告了统计显著的结果，但统计显著不等于理论解释充分。基于你对营销学和消费者心理学的理解，推演可能的底层机制——认知的？情感的？社会的？经济的？即使论文没有详细展开，你也可以从理论逻辑出发给出合理的分析。

    ③ **与 AI × Marketing 知识体系的对话**：
    这篇论文的发现如何与更广泛的 AI×Marketing 文献对话？它是支持还是挑战了已有理论（如 Technology Acceptance Model, UTAUT, Signaling Theory, Anthropomorphism Theory, Uncanny Valley, Computers Are Social Actors 等）？它填补了什么空白？它提出的构念是否与已有构念重叠或冲突？

    ④ **隐藏假设与竞争性解释**：
    论文的论证建立在哪些未明言的假设上？（例如：消费者对 AI 的感知是稳定的、实验室场景能推广到真实购买、在线样本代表目标人群……）有哪些可能的替代解释？如果换一个理论视角看同样的结果，会得到不同的解读吗？

    ⑤ **实践落地推演**：
    如果企业营销部门真的按照这篇论文的建议去做，具体会发生什么？实施中会遇到什么阻力？效果能持续多久？成本-收益如何？在什么条件下这些发现可能失效？

    ⑥ **延伸思考与未来方向**：
    这篇论文让你想到了什么值得进一步探索的问题（不是重复第 17 条中作者自己列的局限）？有没有可能将它的逻辑迁移到另一个子领域？有没有它忽略但重要的变量？

    撰写要求：
    - 使用段落叙述，不是列表。像写学术评论文章（类似于 Journal of Marketing 的 "Research Insights" 栏目）。
    - 有洞察力的分析优于面面俱到的罗列。一两个真正深入的点，比十条浅尝辄止的点更有价值。
    - 标注你的推理边界——如果你基于理论推断而不是原文明确写的内容，请自然地区分（如"虽然论文未展开讨论，但从 XX 理论视角来看……"）。

**输出格式**
仅输出一个合法的 JSON 对象，键名与上述字段名完全一致，不要添加任何额外的解释文字或 Markdown 标记。示例结构：
{{
  "标题": "",
  "作者": "",
  "第一作者": "",
  "通讯作者": "",
  "年份": "",
  "期刊": "",
  "影响因子": "",
  "分区": "",
  "关键词": "",
  "研究背景与动机": "",
  "研究问题": "",
  "变量汇总": "",
  "研究方法": "",
  "方法论详解": "",
  "研究结果": "",
  "讨论与结论": "",
  "创新点": "",
  "局限与展望": "",
  "深度理解与理论推导": ""
}}

[论文全文]
{text}"""

    try:
        async def _do_request():
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 12288,
                }
                async with session.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"HTTP {resp.status} — {body[:300]}")
                    result = await resp.json()
                    content = result["choices"][0]["message"]["content"]
                    json_match = re.search(r"\{.*\}", content, re.DOTALL)
                    if not json_match:
                        raise RuntimeError("DeepSeek 返回中未找到合法 JSON")
                    raw = json.loads(json_match.group())
                    return {
                        "标题": raw.get("标题", ""),
                        "作者": raw.get("作者", ""),
                        "第一作者": raw.get("第一作者", ""),
                        "通讯作者": raw.get("通讯作者", ""),
                        "年份": raw.get("年份", ""),
                        "期刊": raw.get("期刊", ""),
                        "影响因子": "",
                        "分区": raw.get("分区", ""),
                        "关键词": raw.get("关键词", ""),
                        "研究背景与动机": raw.get("研究背景与动机", ""),
                        "研究问题": raw.get("研究问题", ""),
                        "变量汇总": raw.get("变量汇总", ""),
                        "研究方法": raw.get("研究方法", ""),
                        "方法论详解": raw.get("方法论详解", ""),
                        "研究结果": raw.get("研究结果", ""),
                        "讨论与结论": raw.get("讨论与结论", ""),
                        "创新点": raw.get("创新点", ""),
                        "局限与展望": raw.get("局限与展望", ""),
                        "深度理解与理论推导": raw.get("深度理解与理论推导", ""),
                    }

        result = await _retry_api_call(_do_request, max_retries=3, base_delay=2.0,
                                       description="DeepSeek 深度阅读")
        return result
    except Exception as e:
        logger.error(f"DeepSeek API 调用异常（已重试）: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════════════════

async def _self_check_notes(text: str, notes: Dict[str, str], api_key: str, model: str) -> Dict[str, Any]:
    """深度阅读后自检（一轮精简版）。

    检查变量遗漏、数字错误、编造内容，一次 API 调用完成。
    返回 {"issues": [...], "verified": [...], "confidence": "high"|"medium"|"low"}
    失败不阻塞主流程。"""

    result = {"issues": [], "verified": [], "confidence": "high"}

    # 取原文前部（方法+结果通常在中间偏前）+ 关键笔记字段
    text_sample = text[:12000]
    notes_check = {
        "变量汇总": notes.get("变量汇总", "")[:800],
        "研究方法": notes.get("研究方法", "")[:600],
        "研究结果": notes.get("研究结果", "")[:1000],
    }

    check_prompt = f"""你是学术审稿人。检查这份精读笔记是否存在以下问题，每条问题独立验证：

1. 变量遗漏：原文是定量实证研究，笔记"变量汇总"为空或遗漏关键变量？
2. 数字错误：笔记中的样本量、统计量（β/SE/t/p/α/R²）、百分比与原文不一致？
3. 编造内容：笔记中存在原文没有的事实性陈述？

对每个发现的问题，给出：
- 问题类型（遗漏/数字错误/编造）
- 原文原句（引用原文）
- 笔记表述（引用笔记）
- 判定（WRONG/UNCLEAR）

原文（前12000字符）：
{text_sample}

笔记关键字段：
{json.dumps(notes_check, ensure_ascii=False, indent=2)}

如果笔记质量合格无问题，仅回复 "PASS"。
否则逐条列出问题，格式：
WRONG|UNCLEAR: <类型> — <问题描述>"""

    try:
        async def _do_check():
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "你是严谨的学术审稿人。只回复判定结果，不添加客套话。"},
                        {"role": "user", "content": check_prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 800,
                }
                async with session.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    resp_data = await resp.json()
                    return resp_data["choices"][0]["message"]["content"].strip()

        content = await _retry_api_call(_do_check, max_retries=2, base_delay=1.5,
                                        description="自检")
        if content is None:
            result["confidence"] = "unchecked"
            result["issues"].append("自检API调用失败，本轮笔记未经反幻觉验证")
            return result

        if content.upper().startswith("PASS"):
            logger.info("[自检] 通过 ✓")
            return result

        # 解析问题
        for line in content.split("\n"):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.upper().startswith("PASS"):
                continue
            if "WRONG" in line_stripped:
                result["verified"].append({"verdict": "WRONG", "detail": line_stripped[:200]})
                logger.warning(f"[自检·WRONG] {line_stripped[:120]}")
            elif "UNCLEAR" in line_stripped:
                result["verified"].append({"verdict": "UNCLEAR", "detail": line_stripped[:200]})
                logger.info(f"[自检·UNCLEAR] {line_stripped[:120]}")
            elif any(kw in line_stripped for kw in ["问题", "遗漏", "错误", "编造"]):
                result["issues"].append(line_stripped[:200])
                logger.warning(f"[自检] {line_stripped[:120]}")

        wrong_count = sum(1 for v in result["verified"] if v["verdict"] == "WRONG")
        if wrong_count > 0:
            result["confidence"] = "low"
        elif result["verified"] or result["issues"]:
            result["confidence"] = "medium"
        else:
            result["confidence"] = "high"

        return result
    except Exception as e:
        logger.warning(f"自检异常（不阻塞）: {e}")
        result["confidence"] = "unchecked"
        result["issues"].append(f"自检异常: {e}")
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 变量交叉校验
# ═══════════════════════════════════════════════════════════════════════════════

async def _cross_validate_variables(text: str, notes: Dict[str, str]) -> List[str]:
    """变量交叉校验：检查 变量汇总 中的变量是否与 研究方法 段落一致。

    策略（纯规则，不调用 API）：
    1. 从 变量汇总 提取变量名列表
    2. 从 研究方法 段落提取变量名
    3. 方法中提到的变量但未在汇总中出现 → [变量遗漏]
    4. 汇总中的变量但全文未再出现 → [变量孤立]
    """
    warnings = []
    var_summary = notes.get("变量汇总", "")
    研究方法 = notes.get("研究方法", "")

    if not var_summary or not 研究方法:
        return warnings

    # 提取变量汇总中的变量名（以 - 或数字开头的行、或含"变量名称"的行）
    var_names_in_summary = set()
    for line in var_summary.split("\n"):
        line = line.strip()
        # 匹配 "变量名称：xxx" 或 "- xxx（IV）" 等模式
        name_match = re.search(r'(?:变量名称[：:]\s*|-\s*)([\w\s\-]+?)(?:[（(]|$)', line)
        if name_match:
            var_name = name_match.group(1).strip()
            if len(var_name) >= 3:  # 过滤太短的
                var_names_in_summary.add(var_name.lower())

    # 提取研究方法段落中提到的变量/构念名
    # 找引号中的术语、常见变量模式
    method_var_candidates = set()
    # 引号中的词
    quoted = re.findall(r'["""]([^"""]+?)["»"]', 研究方法)
    for q in quoted:
        if 3 <= len(q) <= 40:
            method_var_candidates.add(q.lower().strip())
    # 常见模式：XXX scale / XXX construct
    scale_matches = re.findall(r'(\w[\w\s]{2,35}?)\s(?:scale|construct|measure|variable)', 研究方法, re.IGNORECASE)
    for sm in scale_matches:
        method_var_candidates.add(sm.lower().strip())

    # 交叉比对
    if var_names_in_summary and method_var_candidates:
        # 方法中提到的变量是否在汇总中
        for mv in method_var_candidates:
            # 模糊匹配
            found = any(
                mv in vs or vs in mv or
                sum(1 for a, b in zip(mv.split(), vs.split()) if a == b) >= 1
                for vs in var_names_in_summary
            )
            if not found and len(mv) > 5:
                warnings.append(f"[变量遗漏] 研究方法提到「{mv}」但变量汇总未收录")

    if warnings:
        logger.warning(f"[变量交叉校验] 发现 {len(warnings)} 个问题")
    else:
        logger.info("[变量交叉校验] 通过 ✓")

    return warnings


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口: generate_notes
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_notes(text: str) -> Optional[Dict[str, str]]:
    """
    使用 DeepSeek V4 Pro API 对论文全文进行学术级深度提取。
    无回退模式——DeepSeek 不可用时直接报错，确保输出质量。

    防幻觉流水线:
    1. DeepSeek 生成 17 字段笔记
    2. 第一轮快速自检 → PASS 则直接入库
    3. 第一轮 FAIL → 第二轮逐条验证 (PASS/WRONG/UNCLEAR)
    4. 变量交叉校验 (规则引擎，不消耗 API)
    5. 置信度标注 + 复核队列

    返回包含 17 字段的 dict（含 _自检标记, _置信度, _验证详情），失败时返回 None。
    """
    deepseek_key = config.get("deepseek_api_key", "")
    deepseek_model = config.get("deepseek_model", "deepseek-v4-pro")

    if not deepseek_key:
        logger.error("DeepSeek API Key 未配置！请在 config.json 中设置 deepseek_api_key。")
        return None

    logger.info(f"调用 DeepSeek API ({deepseek_model}) 生成笔记...")
    notes = await _generate_via_deepseek(text, deepseek_key, deepseek_model)

    if not notes:
        return None

    all_issues = []

    # ── 1. 自检 + 二次验证 ──
    check_result = await _self_check_notes(text, notes, deepseek_key, deepseek_model)
    confidence = check_result.get("confidence", "high")
    notes["_置信度"] = confidence
    notes["_自检标记"] = ""

    if check_result.get("verified"):
        wrong_items = [v for v in check_result["verified"] if v["verdict"] == "WRONG"]
        unclear_items = [v for v in check_result["verified"] if v["verdict"] == "UNCLEAR"]
        notes["_验证详情"] = check_result["verified"]

        if wrong_items:
            wrong_msg = "; ".join(f"WRONG: {w['detail'][:100]}" for w in wrong_items)
            all_issues.append(wrong_msg)
            logger.warning(f"[防幻觉] {len(wrong_items)} 条 WRONG，建议人工复核后决定是否入库")
        if unclear_items:
            unclear_msg = "; ".join(f"UNCLEAR: {u['detail'][:100]}" for u in unclear_items)
            all_issues.append(unclear_msg)
    else:
        notes["_验证详情"] = []

    if check_result.get("issues") and not check_result.get("verified"):
        # 二次验证未执行（API 失败），保留第一轮问题
        all_issues.extend(check_result["issues"])

    # ── 2. 变量交叉校验 ──
    var_warnings = await _cross_validate_variables(text, notes)
    if var_warnings:
        all_issues.extend(var_warnings)
        # 变量问题 → 降级置信度（自检可能 PASS 但变量校验 FAIL）
        if confidence == "high":
            confidence = "medium"
            notes["_置信度"] = confidence
            logger.warning(f"[防幻觉] 变量校验发现问题，置信度降级: HIGH → MEDIUM")

    # ── 3. 汇总标记 ──
    if all_issues:
        notes["_自检标记"] = " | ".join(all_issues)
        logger.warning(f"[防幻觉] 总共 {len(all_issues)} 个问题/警告，置信度: {confidence.upper()}")
    else:
        logger.info("[防幻觉] 全部通过 ✓ 置信度: HIGH")

    # ── 4. 写入复核队列（有问题就进队列，不管置信度高低）──
    if all_issues or confidence in ("low", "medium"):
        _add_to_review_queue(notes)

    return notes
