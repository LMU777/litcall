---
title: "AI–Human Hybrids for Marketing Research: Leveraging Large Language Models (LLMs) as Collaborators"
authors: "Neeraj Arora（第一作者）, Ishita Chakraborty, Yohei Nishimura"
first_author: "Neeraj Arora"
corresponding_author: ""
year: 2025
journal: "Journal of Marketing"
impact_factor: "9.0"
zone: ""
doi: "10.1177/00222429241276529"
keywords: "generative AI; natural language processing; qualitative research; surveys; consumer insights; unstructured data; RAG; in-context learning"
pdf: "C:/Users/LI-UF/Zotero/storage/CMZTGHER/Arora 等 - 2025 - AI–Human Hybrids for Marketing Research Leveraging Large Language Models (LLMs) as Collaborators.pdf"
reading_mode: ""
reading_date: ""
tags: [AI, marketing, Journal of Marketing, generative-AI, natural-language-processing, qualitative-research, surveys, consumer-insights]
---

## 研究背景与动机
营销研究行业在2023年价值843亿美元，生成式AI（GenAI）和大语言模型（LLMs）的快速发展有望对其产生变革性影响。然而，现有关于LLMs在营销研究中价值的学术研究尚处于初期且零散，早期证据表明LLMs虽有潜力增强人类判断，但也存在不足。因此，需要系统评估LLMs在代表性营销研究任务上的表现，并开始制定指导方针。本文基于一个框架（Table 1），旨在填补这一空白，系统研究LLMs在营销研究过程中各阶段（研究设计、样本选择、数据收集、数据分析）可能增加的价值，重点关注AI-人类混合方法在定性和定量研究中的效率和有效性提升。

## 研究问题
本文的核心前提是：人类-LLM混合方法可以在营销研究过程中带来效率和有效性的提升。具体研究问题围绕LLMs在定性和定量研究的各个阶段（数据生成和数据分析）中的作用。

理论框架：
- 核心构念：AI-人类混合（AI-human hybrid）、LLM作为协作者（collaborator）、合成受访者（synthetic respondents）、数据生成（data generation）、数据分析（data analysis）。
- 关系：LLM可以作为研究过程中的助手，在数据生成和分析阶段辅助人类。人类监督是必要的，因为LLM可能出错、有偏见或产生幻觉。
- 理论角色：LLM是辅助工具，人类是最终决策者和监督者。

具体假设/问题：
- 定性研究（Study 1）：评估AI-人类混合在数据生成和数据分析方面与纯人类过程的匹配程度。
- 定量研究（Study 2）：评估合成受访者相对于人类受访者的表现，并测试通过few-shot learning和RAG融入上下文是否能改善合成数据质量。

## 变量汇总


## 研究方法
本文采用实证研究方法，与一家财富500强食品公司合作，使用GPT-4复制了该公司在2019年进行的两项研究（一项定性，一项定量），将原始人类研究作为“地面真相”来评估LLM生成数据的质量。

**定性研究（Study 1：Friendsgiving）**：
- 研究设计：复制2019年关于Friendsgiving的定性研究（虚拟深度访谈）。原始研究为期5天，本文仅关注第1天。
- 数据生成：测试了四种LLM-人类混合模型（Table 5）：
  - LLM hybrid 1（合成受访者）：使用原始讨论指南、受访者画像和探针，但用LLM生成合成受访者。
  - LLM hybrid 2（招募条件）：让LLM建议受访者群体并生成合成画像。
  - LLM hybrid 3（主持条件）：LLM既作为合成受访者，又通过实时评分（清晰度、相关性、深度、洞察力）和阈值（80分）提供探针来主持访谈。
  - LLM hybrid 4（主持和招募条件）：结合LLM hybrid 2和3。
- 评估标准：数据质量（可读性指标SMOG、Gunning fog、Flesch-Kincaid；信息密度和连贯性）、与人类数据的相似性（BERT句子嵌入的余弦相似度）、研究目标（通过Prolific上的250名参与者评估清晰度、相关性、深度和洞察力）、研究结果（由专家定性分析师评估主题和摘要）。
- 数据分析：10名人类分析师（至少5年经验）和LLM对5个问题的回答进行主题分析（识别关键句子、聚类主题、撰写摘要）。5名专家评委（超过10年经验）比较四种条件（人类生成-人类分析、人类生成-LLM分析、LLM生成-人类分析、LLM生成-LLM分析）的摘要。

**定量研究（Study 2：冷藏狗粮）**：
- 研究设计：复制2019年关于冷藏狗粮概念的调查（n=605）。
- 数据生成：使用GPT-4通过API生成合成数据，温度设置为1。为605名合成受访者创建与原始样本特征完全匹配的画像。
- 评估：比较合成数据与人类数据在概念评估（购买可能性、喜欢度、独特性）、态度测量（7个属性）和消费频率上的均值、方差和分布。
- 上下文融入：测试了两种方法：
  - Few-shot learning（LLM2）：在系统角色中包含先前问题的答案。
  - RAG（LLM3）：结合few-shot learning和来自公司之前定性研究（16名受访者）的转录数据。
- 评估指标：偏差（均值绝对差）、异质性（标准差绝对差）、内部一致性（成对相关性的绝对差）。

## 研究结果
**定性研究（Study 1）**：
- 数据质量：LLM生成的数据可读性较低（需要至少12年正规教育，而人类数据五年级水平即可），但信息密度和连贯性更高（LLM hybrid 3最佳）。
- 与人类数据相似性：LLM hybrid 3生成的数据在语义上与人类数据最接近。
- 研究目标（Prolific研究，n=250，992次评估）：
  - 清晰度和相关性：LLM与人类无显著差异。
  - 深度：LLM生成的答案得分增加0.680（p < .05）。
  - 洞察力：LLM生成的答案得分增加0.498（p < .05）。
- 数据分析：
  - 关键句子识别：人类平均标记35句，LLM平均19句，但余弦相似度平均为0.78。
  - 主题恢复：人类生成-LLM分析条件恢复96%的主题，并发现23%的新主题；LLM生成-人类分析恢复86%，新主题14%；LLM生成-LLM分析恢复77%，新主题14%。
  - 专家评估：5名评委中，3名选择人类生成-LLM分析摘要为最佳，2名选择LLM生成-人类分析摘要为最佳。无人选择纯人类或纯LLM条件。

**定量研究（Study 2）**：
- 零样本（LLM1）：LLM能正确把握答案方向（均值方向一致），但方差较小，相关性恢复较差。
- 上下文融入（LLM2和LLM3）：
  - 偏差：LLM1为0.66（SE=0.02），LLM2为0.67（0.04），LLM3为0.69（0.04），无显著改善。
  - 异质性：LLM1为0.41（0.06），LLM2为0.29（0.03），LLM3为0.28（0.03），LLM2和LLM3显著优于LLM1（p < .05）。
  - 内部一致性：LLM1为0.40（0.02），LLM2为0.27（0.02），LLM3为0.11（0.02），LLM2和LLM3显著优于LLM1（p < .05），且LLM3优于LLM2（p < .05）。

**核心发现**：
1. AI-人类混合在定性研究中能生成比纯人类数据更深入、更具洞察力的数据。
2. LLM在定性数据分析中能匹配人类专家，并发现新主题。
3. 人类-LLM混合在定性数据分析中优于纯人类或纯LLM方法。
4. 在定量研究中，零样本LLM能把握答案方向，但异质性和内部一致性不足。
5. Few-shot learning和RAG能显著改善合成数据的异质性和内部一致性。

## 讨论与结论
作者认为，AI-人类混合方法能在营销研究过程中带来显著的效率和有效性提升。在定性方面，LLM可以协助数据生成和分析，生成的数据在深度和洞察力上有时优于人类数据，且LLM作为分析师表现良好。在定量方面，LLM能把握答案方向，但通过融入上下文（few-shot learning和RAG）可以改善异质性和可靠性。作者强调，LLM和人类具有互补技能，混合方法优于单一方法。

理论含义：本文为LLMs在营销研究中的应用提供了系统性的实证证据，填补了现有文献的空白。实践含义：为从业者提供了将LLMs整合到定性和定量营销研究中的路线图（Figure 4和Figure 11），强调LLM作为协作者的角色，可以降低成本、提高效率，特别是在难以接触的受访者群体（如医生、高管）中。

值得商榷之处：研究结果基于单一公司、两个特定情境（Friendsgiving和冷藏狗粮），外部有效性有限。作者也承认这一点。

## 创新点
1. 聚焦AI-人类混合方法，系统研究LLM作为协作者在营销研究中的作用，并实证发现LLM和人类带来独特、互补的见解。
2. 同时研究定性和定量营销研究，填补了现有文献在定性领域（非结构化数据）的空白。
3. 在结构化数据领域，展示了融入上下文（few-shot learning和RAG）对于生成合成受访者的价值。
4. 提供了将LLMs整合到定性和定量营销研究中的实践路线图。

## 局限与展望
- 局限性：
（1）LLMs在训练数据中存在性别、种族和文化偏见，可能输出有偏见或错误的信息，需要人类监督。
（2）实证测试的结果不具有普遍性，应被视为主要观点的例证，需要在广泛情境中进行重复验证。
- 未来研究方向：
（1）使用强化学习（reinforcement learning）与人类反馈来促进LLM与价值观（如有用性和无害性）的对齐，减少有害内容。
（2）通过政策干预和精选数据来缓解基础模型中的数据偏见。
（3）利用微调（fine-tuning）通过迁移学习解决伦理问题，例如训练LLM遵守法律要求以消除现有偏见。
（4）在多种情境下进行重复验证，以成功采用LLM作为营销研究中的协作者/助手。

---
## 相关概念
- [[generative AI]]
- [[natural language processing]]
- [[qualitative research]]
- [[surveys]]
- [[consumer insights]]
- [[unstructured data]]
- [[RAG]]
- [[in-context learning]]

---
## 图表索引

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig52.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig53.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig54.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig55.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig56.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig57.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig58.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig59.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig60.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig61.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig62.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig63.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig64.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig65.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig66.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig67.png]]

![[attachments/Arora 等 - 2025 - AI_Human Hybr_fig68.png]]
