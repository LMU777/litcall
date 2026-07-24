---
title: "Implementing Artificial Intelligence Consumer Experience Tools in Supply Chains"
authors: "Ming Cheng（第一作者）, Bin Shen（通讯作者）, Hau-Ling Chan"
first_author: "Ming Cheng"
corresponding_author: "Bin Shen"
year: 2025
journal: "IEEE Transactions on Engineering Management"
impact_factor: "5.8"
zone: ""
doi: "10.1109/TEM.2024.3525412,"
keywords: "artificial intelligence; consumer experience tools; consumer privacy concerns; dual-channel; supply chain"
pdf: "C:/Users/LI-UF/Desktop/Claude/semi_autp_paper/新论文待处理/Implementing Artificial Intelligence Consumer Experience Tools in Supply Chains.pdf"
reading_mode: ""
reading_date: ""
tags: [AI, marketing, IEEE Transactions on Engineeri, consumer-experience-tools, consumer-privacy-concerns, dual-channel, supply-chain]
---

## 研究背景与动机
在电子商务中，消费者面临产品匹配不确定性（product fit uncertainty），约80%的消费者在线上购物时遇到挑战。人工智能消费者体验工具（AI-CE）可以帮助消费者在购买前评估产品匹配度，已被零售商和供应商采用。然而，AI-CE的实施可能引发消费者隐私担忧，约55%的消费者认为卖家会收集并分享数据。现有研究尚未明确在供应商同时通过批发渠道（零售商）和直销渠道销售两种水平差异化产品的入侵式供应链（encroached supply chain）中，由谁提供AI-CE是最优的。本文旨在填补这一理论空白，通过博弈论模型分析AI-CE实施策略，考虑消费者隐私敏感度、渠道竞争和比较劣势效应。

## 研究问题
研究问题（RQs）：
RQ1: 零售商和供应商实施AI-CE是否明智？
RQ2: AI-CE对消费者产品匹配的精度如何影响与AI-CE实施策略相关的利益相关者利润？
RQ3: 在什么条件下AI-CE有助于提高消费者剩余？

理论推导逻辑：
- AI-CE的实施会产生两个关键效应：渠道竞争缓解效应（channel competition mitigation effect）和比较劣势效应（comparative disadvantage effect）。
- 渠道竞争缓解效应：AI-CE帮助消费者了解产品匹配度，降低渠道替代性，使零售商或供应商能够提高价格。
- 比较劣势效应：实施AI-CE的一方因引发消费者隐私担忧而处于竞争劣势，被迫降低价格。
- 消费者隐私敏感度（k）调节这两个效应的相对强度。

理论框架：
- 核心构念：AI-CE实施策略（四种场景：NN、YN、NY、YY）、消费者隐私敏感度（k）、AI-CE精度（β）、供应商利润、零售商利润、消费者剩余。
- 构念关系：AI-CE实施策略和精度影响利润和消费者剩余，消费者隐私敏感度调节这些影响。
- 理论角色：AI-CE实施策略为决策变量（前因），消费者隐私敏感度为调节变量，AI-CE精度为外生参数，利润和消费者剩余为结果变量。

## 变量汇总
1. 变量名称：consumer sensitivity toward privacy (消费者隐私敏感度)
   - 变量类型：调节变量
   - 概念定义：消费者对隐私问题的敏感程度，用参数k表示，k > 0。
   - 测量方式：无（理论模型参数）

2. 变量名称：AI-CE precision toward product fitness (AI-CE对产品匹配的精度)
   - 变量类型：自变量（外生参数）
   - 概念定义：AI-CE帮助消费者获得关于产品匹配度的正确信号的概率，用β表示，0 < b < β < 1。零售商和供应商的精度分别记为βr和βs，且βr ≥ βs。
   - 测量方式：无（理论模型参数）

3. 变量名称：retailer profit (零售商利润)
   - 变量类型：因变量
   - 概念定义：零售商在给定AI-CE实施策略下的期望利润。
   - 测量方式：无（理论模型推导）

4. 变量名称：supplier profit (供应商利润)
   - 变量类型：因变量
   - 概念定义：供应商在给定AI-CE实施策略下的期望利润。
   - 测量方式：无（理论模型推导）

5. 变量名称：consumer surplus (消费者剩余)
   - 变量类型：因变量
   - 概念定义：消费者在给定AI-CE实施策略下的总剩余。
   - 测量方式：无（理论模型推导）

## 研究方法
本文采用博弈论模型（game-theoretical models）进行研究。研究设计基于一个入侵式供应链结构：一个供应商通过批发渠道（零售商）和直销渠道销售两种水平差异化产品（产品R和产品S）。消费者分为忠诚消费者（loyal consumers）和购物者（shoppers）。忠诚消费者只从特定卖家购买，购物者则选择净效用最高的产品，且其购买决策受AI-CE影响。AI-CE的实施精度（β）影响购物者对产品匹配度的认知，同时引发隐私担忧，隐私担忧成本为C(β) = kβ²/2。

博弈顺序：
- 第1阶段：供应商和零售商同时决定是否实施AI-CE（四种场景：NN、YN、NY、YY）。
- 第2阶段：作为Stackelberg领导者，供应商设定批发价格w和直销渠道价格ps。
- 第3阶段：作为追随者，零售商设定零售价格pr。
- 第4阶段：消费者使用AI-CE（如有）并做出购买决策。

分析方法：通过逆向归纳法（backward induction）求解每个子博弈的均衡价格和利润，然后比较四种场景下的均衡利润，确定纳什均衡（Nash equilibrium）的AI-CE实施策略。模型还进行了稳健性检验（robustness check），包括上游精度优势、正单位生产成本和任意单位不匹配成本。

## 研究结果
描述性统计：无（理论模型）。

假设检验（命题）：
- 命题1（场景NN）：供应商利润随购物者自身评估精度b增加而减少，零售商利润随b增加而增加。
- 命题2（场景YN）：当消费者隐私敏感度足够低（k ≤ k1）时，供应商利润随βs增加而减少，零售商利润随βs增加而增加；当k > k1时，供应商和零售商利润均随βs增加而增加。
- 命题3（场景NY）：当k ≤ k2时，供应商利润随βr增加而减少，零售商利润随βr增加而增加；当k3 < k时，供应商利润随βr增加而增加，零售商利润随βr增加而减少；当k2 < k ≤ k3时，供应商和零售商利润均随βr增加而减少。
- 命题4（场景YY）：供应商利润随βi（i∈{s,r}）增加而减少，零售商利润随βi增加而增加。
- 命题5：
  (i) 当竞争对手不实施AI-CE时：零售商在NY下的利润高于NN当且仅当k ≤ k4；供应商在YN下的利润高于NN当且仅当k > k5。
  (ii) 当竞争对手实施AI-CE时：零售商在YY下的利润高于YN当且仅当k ≤ k6；供应商在NY下的利润始终高于YY。
- 命题6（均衡策略）：
  (i) 当k ≤ k4时，零售商实施AI-CE，供应商不实施（NY为均衡）。
  (ii) 当k4 < k ≤ min{k5, k6}时，双方均不实施AI-CE（NN为均衡）。
  (iii) 当k > max{k5, k6}时，供应商实施AI-CE，零售商不实施（YN为均衡）。
  (iv) 双方均实施AI-CE（YY）永远不会成为均衡策略。
- 命题7（消费者剩余）：存在阈值k7，当k ≤ k7时，NY场景产生最高消费者剩余；当k7 < k时，NN场景产生最高消费者剩余。

核心发现：
1. 最优AI-CE实施策略取决于消费者隐私敏感度：低敏感度时零售商单独实施，高敏感度时供应商单独实施，中等敏感度时双方均不实施。
2. 双方均实施AI-CE永远不会成为均衡策略，因为联合实施会消除比较劣势和渠道竞争的正面效应。
3. AI-CE精度的提高可能有益或有害于供应商和零售商，取决于隐私敏感度和实施场景。
4. 当隐私敏感度低时，零售商单独实施AI-CE能提高消费者剩余；当隐私敏感度高时，任何AI-CE实施都会降低消费者剩余。

## 讨论与结论
作者将核心结果解释为AI-CE实施带来的渠道竞争缓解效应和比较劣势效应之间的权衡。当隐私敏感度低时，零售商实施AI-CE的渠道竞争缓解效应占主导，使其受益；当隐私敏感度高时，供应商实施AI-CE的比较劣势效应在批发渠道的正面影响超过在直销渠道的负面影响，使供应商受益。中等敏感度时，双方均因比较劣势效应而受损，因此都不实施。

与已有文献的关系：
- 与产品信息披露文献一致：AI-CE提供匹配信息，影响渠道竞争。
- 与消费者隐私担忧文献一致：隐私担忧产生比较劣势。
- 与入侵式供应链文献一致：信息不对称和渠道竞争影响决策。

理论含义：揭示了AI-CE实施在供应链中的战略价值，挑战了“双方都应实施AI-CE”的传统观点。

实践含义：
- 对于低隐私敏感度产品（如食品、饮料），零售商应单独实施AI-CE。
- 对于高隐私敏感度产品（如金融服务、药品），供应商应单独实施AI-CE。
- 对于中等隐私敏感度产品（如时尚产品），双方均不应实施AI-CE。
- 管理者在投资提高AI-CE精度前应仔细评估隐私敏感度和竞争对手策略。

值得商榷之处：模型假设AI-CE精度外生，且消费者对产品垂直质量同质，可能简化了现实复杂性。

## 创新点
1. 理论创新：首次在入侵式供应链中研究AI-CE实施策略，识别了渠道竞争缓解效应和比较劣势效应，揭示了消费者隐私敏感度的关键调节作用。
2. 理论创新：发现双方均实施AI-CE永远不会成为均衡策略，挑战了传统认知。
3. 理论创新：揭示了AI-CE精度提高对利润的非单调影响，取决于隐私敏感度和实施场景。
4. 实践创新：为零售商和供应商提供了基于隐私敏感度的差异化AI-CE实施指南。

## 局限与展望
- 局限性：
  (1) 模型假设消费者对产品垂直质量属性具有相同估值，未考虑消费者在产品质量上的异质性。
  (2) 模型假设AI-CE的精度是外生的，而实践中提高精度是企业的重要决策。
  (3) 模型假设供应商通过直销渠道入侵，未考虑通过第三方代理渠道（agency channel）销售的场景。

- 未来研究方向：
  (1) 未来研究可考虑消费者在产品质量上的异质性，分析AI-CE实施如何影响质量差异化产品的供应链。
  (2) 未来研究可将模型扩展为包含信息精度决策的内生模型，分析企业如何最优选择AI-CE精度。
  (3) 未来研究可探讨供应商通过第三方代理渠道入侵的场景，分析不同渠道结构下的AI-CE实施策略。

---
## 相关概念
- [[AI]]
- [[consumer experience tools]]
- [[consumer privacy concerns]]
- [[dual-channel]]
- [[supply chain]]

---
## 图表索引

![[attachments/Implementing Artificial Intell_fig1.png]]

![[attachments/Implementing Artificial Intell_fig2.png]]
