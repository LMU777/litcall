"""中英文学术概念映射模块。

将中文研究术语扩展为对应的英文学术关键词，提升跨语言检索效果。
用户用中文提问，但论文元数据多是英文——此模块通过预置的概念映射表，
自动将中文术语附加对应的英文同义词，使检索能命中英文文献。
"""

import logging
import re

logger = logging.getLogger(__name__)

# 中英文学术概念映射：用户用中文提问，但论文元数据多是英文
_CONCEPT_MAP: dict = {
    # ── AI 技术与智能体 ──
    "智能体": "agent chatbot conversational agent virtual assistant embodied agent autonomous agent multi-agent",
    "聊天机器人": "chatbot conversational agent virtual assistant dialogue system",
    "对话式ai": "conversational ai conversational agent chatbot dialogue system nlp",
    "生成式ai": "generative ai genai chatgpt large language model llm gpt foundation model text generation image generation",
    "大语言模型": "large language model llm gpt foundation model transformer bert pretrained model",
    "自然语言处理": "natural language processing nlp text analysis sentiment analysis computational linguistics",
    "机器学习": "machine learning deep learning neural network supervised unsupervised reinforcement learning",
    "推荐系统": "recommender system recommendation algorithm personalization collaborative filtering",
    "计算机视觉": "computer vision image recognition visual analysis facial recognition",
    "人机协同": "human ai collaboration human in the loop human machine collaboration hybrid intelligence augmentation",
    "人机交互": "human computer interaction hci human ai interaction user interface ux",
    "具身认知": "embodied cognition sensory perception grounding situated cognition",
    "可解释性": "explainability explainable ai xai transparency interpretability black box",
    # ── 消费者心理与行为 ──
    "消费者信任": "consumer trust trust in ai perceived trustworthiness credibility reliability confidence",
    "消费者行为": "consumer behavior purchase intention decision making adoption acceptance willingness to pay",
    "消费者态度": "consumer attitude perception evaluation satisfaction loyalty engagement",
    "消费者心理": "consumer psychology cognition affect emotion motivation attitude persuasion",
    "个性化": "personalization personalized recommendation customization targeting segmentation tailoring",
    "隐私": "privacy data privacy information privacy surveillance data protection gdpr",
    "算法偏见": "algorithmic bias fairness discrimination ethics justice equity",
    "拟人化": "anthropomorphism humanization human-like warmth social presence",
    "用户体验": "user experience ux usability satisfaction engagement flow",
    "情感": "emotion affect sentiment mood feeling emotional response arousal valence",
    # ── 品牌与广告 ──
    "品牌管理": "brand management brand equity brand attitude brand trust brand loyalty brand personality",
    "品牌": "brand branding brand identity brand image brand positioning brand awareness",
    "广告": "advertising ad advertisement persuasion ad effectiveness ad creativity",
    "社交媒体": "social media influencer content creator platform engagement virality",
    "内容营销": "content marketing content creation storytelling user generated content",
    "口碑": "word of mouth ewom electronic word of mouth review rating online review",
    # ── 营销战略 ──
    "数字营销": "digital marketing online marketing social media marketing mobile marketing omnichannel",
    "服务营销": "service marketing customer experience service quality satisfaction loyalty",
    "顾客体验": "customer experience consumer experience service experience journey touchpoint",
    "价值共创": "value co-creation co-creation customer participation engagement",
    "客户关系": "customer relationship crm loyalty retention churn engagement",
    "定价": "pricing price promotion discount willingness to pay revenue",
    "全渠道": "omnichannel multichannel channel integration retail online offline",
    # ── 研究方法 ──
    "研究空白": "research gap future research research agenda future direction limitation opportunity",
    "研究缺口": "research gap future research research agenda underexplored overlooked",
    "文献综述": "literature review systematic review bibliometric analysis meta analysis review",
    "理论模型": "theoretical model conceptual framework theory model framework mechanism",
    "实验设计": "experiment experimental design randomized controlled trial field experiment lab experiment",
    "问卷调查": "survey questionnaire scale measurement construct psychometric",
    "质性研究": "qualitative research interview focus group thematic analysis grounded theory ethnography",
    "定量研究": "quantitative research statistical analysis regression sem structural equation modeling",
    "元分析": "meta-analysis meta analysis systematic review effect size",
    "眼动": "eye tracking eye movement visual attention gaze fixation",
    "神经科学": "neuroscience fmri eeg neuromarketing biometric physiological",
    "文本分析": "text analysis text mining content analysis natural language processing topic modeling",
    "大数据": "big data data mining predictive analytics machine learning data driven",
    # ── 理论与概念 ──
    "技术接受模型": "technology acceptance model tam utaut technology adoption is acceptance",
    "信任理论": "trust theory trustworthiness credibility benevolence integrity ability",
    "社会存在": "social presence parasocial relationship social interaction social cues",
    "自我决定": "self-determination autonomy competence relatedness intrinsic motivation",
    "认知负荷": "cognitive load information processing attention mental effort",
    "心流": "flow flow theory optimal experience immersion engagement",
    "期望确认": "expectation confirmation satisfaction continuance is continuance",
    "创新扩散": "innovation diffusion technology adoption doi diffusion of innovation",
    "信号理论": "signaling theory signal credibility quality signal information asymmetry",
    "归因理论": "attribution theory causal attribution blame responsibility",
    "调节聚焦": "regulatory focus promotion prevention regulatory fit",
    "解释水平": "construal level psychological distance abstraction concreteness",
    "抗拒理论": "reactance psychological reactance freedom threat persuasion resistance",
    # ── 伦理与社会 ──
    "伦理": "ethics ethical ai ethics responsible ai fairness accountability transparency",
    "可持续": "sustainability sustainable esg environmental social green",
    "数字鸿沟": "digital divide digital literacy digital inequality access",
    "虚假信息": "misinformation disinformation fake news deepfake deception",
    # ── 期刊/发表 ──
    "顶刊": "top journal journal of marketing journal of consumer research marketing science",
    "utd": "utd24 ft50 top tier journal management science",
}

_CONCEPT_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_CONCEPT_MAP.keys(), key=len, reverse=True)),
    re.IGNORECASE,
)


def expand_query(query: str) -> str:
    """Expand Chinese query terms with English equivalents.

    将中文查询中的概念映射为对应的英文学术词汇，提升跨语言检索效果。
    对于查询中的每个中文概念关键词，在其后附加对应的英文同义词序列，
    使 Token 匹配阶段能命中英文元数据。

    Args:
        query: 用户原始查询文本（可包含中英文混合）。

    Returns:
        扩展后的查询文本，在中文学术术语后附加了对应英文关键词。
    """
    return _CONCEPT_RE.sub(
        lambda m: f"{m.group()} {_CONCEPT_MAP.get(m.group().lower(), '')}",
        query,
    )
