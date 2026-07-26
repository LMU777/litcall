"""
LitCall v3.0 — AI × Marketing 学术文献智能助手
统一 Web 面板入口: streamlit run litcall/ui/app.py

铁律 #6: Agent 是唯一入口。Web 面板只是 Agent 的一种控制界面。
"""
import streamlit as st
import asyncio
import json
import re
import sys
import time
import threading
import base64
from pathlib import Path
from datetime import datetime
from collections import Counter
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

# ── litcall core ──
from litcall.core.config import config, load_config, save_config
from litcall.core.paths import (
    BASE_DIR, PDF_DIR, CONFIG_PATH, PROCESSED_LOG, EXCEL_PATH, OBSIDIAN_DIR,
)

# ── litcall services ──
from litcall.services.qa import (
    _qa_paper_index, _qa_top_n, _qa_use_external, _QA_NOTES_DIR,
    _build_paper_index, _retrieve_papers, _score_and_rank, _semantic_scores,
    _build_qa_messages, _chat_via_deepseek, _verify_answer_claims,
    _parse_year_filter, _tokenize, _char_ngrams, _build_semantic_index,
    _save_qa_history, _save_qa_chat, _print_qa_help,
    _list_qa_sessions, _save_qa_session, _load_qa_session, _delete_qa_session,
    _generate_session_name,
    agent_plan, agent_execute_plan, agent_synthesize,
    build_paper_index,
)
from litcall.services.concept_map import _CONCEPT_MAP, expand_query
from litcall.services.briefing import generate_daily_briefing

# ── litcall pipeline ──
from litcall.pipeline.read.pdf_extract import extract_doi_from_pdf
from litcall.pipeline.read.journal_if import _load_journal_if_map, _journal_if_map, match_impact_factor
from litcall.pipeline.read.anti_hallucination import (
    _add_to_review_queue, _get_review_queue, _remove_from_review_queue,
    _retry_fix_notes, _retry_api_call, _self_check_notes, _cross_validate_variables,
)
from litcall.pipeline.search.keyword_cursor import (
    _read_keyword_cursor, _write_keyword_cursor, _get_next_keyword,
    _advance_keyword_cursor, print_keywords,
)
from litcall.pipeline.search.journal_filter import _get_effective_whitelist, journal_in_whitelist
from litcall.pipeline.search.spis_browser import (
    fetch_zotero_existing_dois, load_processed_log,
)
from litcall.pipeline.search.dedup import normalize_title, is_title_duplicate

# ── litcall agent ──
from litcall.agent.run_logger import AgentRunLogger
from litcall.agent.orchestrator import LitCallOrchestrator, OrchestratorMode

# ── litcall stores ──
from litcall.stores.zotero import ZoteroStore
from litcall.stores.obsidian import ObsidianStore

st.set_page_config(
    page_title="LitCall · 学术智能体",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* Global */
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&display=swap');
.stApp { font-family: system-ui, -apple-system, sans-serif; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #fafafa;
    border-right: 1px solid #eee;
}

/* ── Brand ── */
.sidebar-brand { padding: 0.25rem 0 0.5rem 0; }
.sidebar-brand .brand-name {
    font-family: 'Playfair Display', Georgia, 'Times New Roman', serif;
    font-size: 1.65rem;
    font-weight: 700;
    color: #1a1a2e;
    letter-spacing: -0.02em;
    line-height: 1.15;
}
.sidebar-brand .brand-accent {
    display: inline-block;
    width: 28px;
    height: 2.5px;
    background: #c8956c;
    margin: 0.4rem 0 0.55rem 0;
    border-radius: 1px;
}
.sidebar-brand .brand-tagline {
    font-size: 0.92rem;
    font-weight: 500;
    color: #4a4a5a;
    letter-spacing: 0.01em;
    margin-bottom: 0.15rem;
}
.sidebar-brand .brand-sub {
    font-size: 0.7rem;
    font-weight: 400;
    color: #999;
    letter-spacing: 0.02em;
}

/* Metric — compact */
[data-testid="stSidebar"] .stMetric [data-testid="stMetricValue"] {
    font-weight: 500; font-size: 0.95rem;
}
[data-testid="stSidebar"] .stMetric [data-testid="stMetricLabel"] {
    font-size: 0.75rem; font-weight: 400; color: #888;
}

/* Buttons */
.stButton > button {
    border-radius: 4px !important;
    border: 1px solid #ddd !important;
    background: #fff !important;
    color: #333 !important;
    font-weight: 400 !important;
}
.stButton > button:hover { border-color: #999 !important; }

/* Expander */
[data-testid="stExpander"] {
    border: none !important;
    border-bottom: 1px solid #f0f0f0 !important;
    border-radius: 0 !important;
}

/* Metric card */
[data-testid="stMetric"] {
    background: transparent;
    border: none;
    padding: 0.5rem;
}

/* Tabs */
[data-testid="stTabs"] [aria-selected="true"] { font-weight: 500; }

/* Chat */
[data-testid="stChatMessage"] {
    border-radius: 6px;
    padding: 0.75rem 1rem;
}

/* Hide default sidebar h2 */
[data-testid="stSidebar"] h2 { display: none; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# Session State
# ═══════════════════════════════════════════════════════════════
DEFAULTS = {
    "qa_index_built": False,
    "qa_chat_history": [],
    "qa_last_papers": [],
    "qa_last_scores": [],
    "qa_last_concepts": {},
    "qa_last_retrieval_detail": {},
    "qa_use_external": True,
    "qa_top_n": 8,
    "qa_year_from": None,
    "qa_year_to": None,
    "qa_session_id": None,
    "qa_session_name": "新会话",
    "qa_agent_mode": False,
    "reading_results": None,
    "reading_cancel": False,
    "scraping": False,
    "scraping_log": [],
}
for key, val in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════
def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        return asyncio.run(coro)
    except RuntimeError:
        return asyncio.run(coro)


@st.cache_data(ttl=120)
def _get_paper_index():
    """缓存知识库索引，2分钟自动刷新。_build_paper_index 自带内存缓存，不会重复读盘。"""
    build_paper_index()
    return len(_qa_paper_index), _qa_paper_index


@st.cache_data(ttl=300)
def _parse_frontmatter_md(md_text: str) -> dict:
    """从 Markdown 解析 YAML frontmatter。"""
    result = {}
    m = re.match(r'^---\s*\n(.*?)\n---', md_text, re.DOTALL)
    if not m:
        return result
    for line in m.group(1).split("\n"):
        kv = re.match(r'^(\w+):\s*(.*)', line)
        if kv:
            result[kv.group(1).lower()] = kv.group(2).strip().strip('"').strip("'")
    return result


def _load_dashboard_data():
    """从 Obsidian vault 加载完整 17 字段数据用于仪表盘。

    以 processed_log 为权威数据源过滤：只返回 processed_log 中已确认入库的论文。
    数据来源优先级: Obsidian vault (litcall/) → notes/ JSON (回退)
    """
    papers = []
    seen_dois = set()

    # 加载 processed_log DOI 集合作为权威过滤依据
    valid_dois: set = set()
    try:
        log_dois, _ = load_processed_log()
        valid_dois = log_dois  # 已是 lowercase set
    except Exception:
        valid_dois = set()

    # 优先从 Obsidian vault 加载（litcall/ 目录）
    obsidian_dir = OBSIDIAN_DIR
    if obsidian_dir.exists():
        for md in sorted(obsidian_dir.glob("**/*.md")):
            try:
                text = md.read_text(encoding="utf-8")
                fm = _parse_frontmatter_md(text)
                doi = (fm.get("doi") or "").strip().strip('"').strip("'").strip(",").lower()
                if not doi:
                    continue
                if valid_dois and doi not in valid_dois:
                    continue
                if doi in seen_dois:
                    continue
                seen_dois.add(doi)
                # 将 frontmatter 转为旧格式兼容的 paper dict
                papers.append({
                    "标题": fm.get("title", md.stem),
                    "doi": fm.get("doi", ""),
                    "作者": fm.get("author", ""),
                    "第一作者": fm.get("first_author", ""),
                    "通讯作者": fm.get("corresponding_author", ""),
                    "年份": fm.get("year", ""),
                    "期刊": fm.get("journal", ""),
                    "影响因子": fm.get("impact_factor", ""),
                    "分区": fm.get("quartile", ""),
                    "关键词": fm.get("keywords", ""),
                    "研究背景与动机": fm.get("background", ""),
                    "研究问题": fm.get("research_question", ""),
                    "变量汇总": fm.get("variables", ""),
                    "研究方法": fm.get("method", ""),
                    "方法论详解": fm.get("method_details", ""),
                    "研究结果": fm.get("results", ""),
                    "讨论与结论": fm.get("discussion", ""),
                    "创新点": fm.get("innovation", ""),
                    "局限与展望": fm.get("limitations", ""),
                    "图表分析": fm.get("figure_analysis", ""),
                })
            except Exception:
                continue

    # 回退: 从 notes/ JSON 补录 Obsidian 中缺失的
    notes_dir = PDF_DIR / "notes"
    if notes_dir.exists():
        for f in sorted(notes_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                doi = (data.get("doi") or "").strip().lower()
                if not doi or doi in seen_dois:
                    continue
                if not data.get("标题"):
                    continue
                if valid_dois and doi not in valid_dois:
                    continue
                seen_dois.add(doi)
                papers.append(data)
            except Exception:
                pass

    return papers


def _load_config():
    """读取配置文件（使用 litcall 模块缓存）。"""
    return load_config()


def _save_config(cfg: dict):
    """保存配置到文件（同时刷新 litcall 模块缓存）。"""
    from litcall.core.config import save_config as _lit_save
    _lit_save(cfg)


def _console_safe(text: str) -> str:
    return re.sub(r'[\ud800-\udfff￾-￿]', '', text)


# ═══════════════════════════════════════════════════════════════
# 侧边栏
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
<div class="sidebar-brand">
    <div class="brand-name">LitCall</div>
    <div class="brand-accent"></div>
    <div class="brand-tagline">今天你看文献了吗？</div>

</div>
""", unsafe_allow_html=True)

    _idx_count, _ = _get_paper_index()  # 触发索引构建
    full_data = _load_dashboard_data()
    st.metric("知识库", f"{len(full_data)} 篇 / {len(set(p.get('期刊','') for p in full_data if p.get('期刊')))} 刊")

    cfg = _load_config()


    # ── Agent 运行状态指示灯 ──
    try:
        runs_dir = Path(BASE_DIR) / "运行日志" / "runs"
    except Exception:
        runs_dir = SCRIPT_DIR / "运行日志" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_files = sorted(runs_dir.glob("*.json"))
    except Exception:
        run_files = []
    active_runs = []
    zombie_runs = []
    if run_files:
        try:
            for rf in run_files:
                try:
                    data = json.loads(rf.read_text(encoding="utf-8"))
                    if data.get("status") == "running":
                        # 心跳检测：90秒无心跳 → Worker 已崩溃（僵尸会话）
                        if AgentRunLogger.is_heartbeat_stale(data, max_age_seconds=300):
                            zombie_runs.append((rf, data))
                        else:
                            active_runs.append(data)
                except Exception:
                    pass
        except Exception:
            pass

    # ── 自动清理僵尸会话 ──
    for rf, zdata in zombie_runs:
        try:
            zdata["status"] = "crashed"
            zdata["_crashed_reason"] = "Worker heartbeat lost (likely crash or kill)"
            zdata["ended_at"] = datetime.now().isoformat()
            tmp = Path(str(rf) + ".tmp")
            tmp.write_text(json.dumps(zdata, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(rf)
        except Exception:
            pass

    if active_runs:
        with st.expander(f"🔵 Agent 运行中 ({len(active_runs)} 个会话)", expanded=True):
            for i, run in enumerate(active_runs):
                run_id = run.get("run_id", "?")[:12]
                started = run.get("started_at", "?")[:16]
                p1_s = run.get("phase1", {}).get("status", "?")
                p2_s = run.get("phase2", {}).get("status", "?")
                p3_s = run.get("phase3", {}).get("status", "?")
                paused = run.get("_paused", False)
                status_text = "⏸ 已暂停" if paused else f"P1:{p1_s} P2:{p2_s} P3:{p3_s}"
                st.caption(f"**{run_id}** — {started} — {status_text}")
                c1, c2 = st.columns([3, 1])
                with c1:
                    if st.button(f"⏹ 终止此会话", key=f"sidebar_term_{i}", use_container_width=True):
                        (SCRIPT_DIR / "运行日志" / ".terminate").touch()
                        (SCRIPT_DIR / "运行日志" / ".pause").unlink(missing_ok=True)
                        st.toast("终止信号已发送，刷新页面后生效")
                        st.rerun()
                with c2:
                    if st.button(f"🧹 清除", key=f"sidebar_clear_{i}", use_container_width=True):
                        # 标记为 terminated 并保存
                        run["status"] = "terminated"
                        run["_terminated_by"] = "user_from_sidebar"
                        run["_terminated_at"] = datetime.now().isoformat()
                        rf_path = runs_dir / f"{run.get('run_id', 'unknown')}.json"
                        with open(rf_path, "w", encoding="utf-8") as f:
                            json.dump(run, f, ensure_ascii=False, indent=2)
                        (SCRIPT_DIR / "运行日志" / ".terminate").touch()
                        (SCRIPT_DIR / "运行日志" / ".pause").unlink(missing_ok=True)
                        st.toast(f"已标记为终止，刷新页面")
                        st.rerun()

    if zombie_runs:
        with st.expander(f"💀 崩溃会话 ({len(zombie_runs)} 个)", expanded=False):
            for _, zdata in zombie_runs:
                st.caption(f"💀 **{zdata.get('run_id', '?')[:12]}** — 已自动标记为 crashed")
    elif run_files:
        last_run = run_files[-1]
        try:
            data = json.loads(last_run.read_text(encoding="utf-8"))
            status_icon = {"completed": "✅", "failed": "❌", "running": "🔄"}.get(data.get("status", ""), "")
            last_time = data.get("started_at", last_run.stem)[:16]
            st.caption(f"{status_icon} 上次运行: {last_time}")
        except Exception:
            pass

    st.divider()

    # 会话
    sessions = _list_qa_sessions()
    current_name = st.session_state.qa_session_name or "新会话"
    if st.button(f"{current_name[:20]}", use_container_width=True):
        st.session_state._show_session_panel = not st.session_state.get("_show_session_panel", False)

    if st.session_state.get("_show_session_panel", False):
        if st.button("➕ 新建", use_container_width=True):
            if st.session_state.qa_chat_history:
                sid = st.session_state.qa_session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
                _save_qa_session(sid, st.session_state.qa_session_name, st.session_state.qa_chat_history)
            st.session_state.qa_chat_history = []
            st.session_state.qa_session_id = None
            st.session_state.qa_session_name = "新会话"
            st.session_state._show_session_panel = False
            st.rerun()
        if sessions:
            for s in sessions[:6]:
                is_current = s["id"] == st.session_state.qa_session_id
                prefix = "▸ " if is_current else "  "
                col_l, col_d = st.columns([5, 1])
                with col_l:
                    if st.button(f"{prefix}{s['name'][:25]} ({s['message_count']})", key=f"l_{s['id']}", use_container_width=True):
                        if st.session_state.qa_chat_history:
                            csid = st.session_state.qa_session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
                            _save_qa_session(csid, st.session_state.qa_session_name, st.session_state.qa_chat_history)
                        msgs = _load_qa_session(s["id"])
                        if msgs:
                            st.session_state.qa_chat_history = msgs
                            st.session_state.qa_session_id = s["id"]
                            st.session_state.qa_session_name = s["name"]
                            st.session_state._show_session_panel = False
                            st.rerun()
                with col_d:
                    if st.button("✕", key=f"d_{s['id']}"):
                        _delete_qa_session(s["id"])
                        if s["id"] == st.session_state.qa_session_id:
                            st.session_state.qa_chat_history = []
                            st.session_state.qa_session_id = None
                            st.session_state.qa_session_name = "新会话"
                        st.rerun()

    st.divider()
    page = st.radio(
        "导航",
        ["知识库问答", "文献笔记", "Agent", "知识库仪表盘", "管理"],
        label_visibility="collapsed",
    )


# ═══════════════════════════════════════════════════════════════
#  知识库问答
# ═══════════════════════════════════════════════════════════════

if page == "知识库问答":
    session_label = st.session_state.qa_session_name or "新会话"
    st.header(f"知识库问答 — {session_label}")

    # 初始化索引
    if not st.session_state.qa_index_built:
        with st.spinner("正在构建知识库索引..."):
            _get_paper_index()
            st.session_state.qa_index_built = True

    # ── 自动加载最近一次检索简报 ──
    daily_dir = OBSIDIAN_DIR / "Daily"
    latest_briefing = None
    if daily_dir.exists():
        briefing_files = sorted(daily_dir.glob("*.md"), reverse=True)
        if briefing_files:
            latest_file = briefing_files[0]
            try:
                content = latest_file.read_text(encoding="utf-8")
                # 解析 YAML frontmatter
                fm = {}
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        for line in parts[1].strip().split("\n"):
                            kv = line.split(":", 1)
                            if len(kv) == 2:
                                fm[kv[0].strip()] = kv[1].strip()
                latest_briefing = {
                    "path": str(latest_file),
                    "date": fm.get("date", latest_file.stem[:10]),
                    "total": fm.get("total_collected", "?"),
                    "with_links": fm.get("with_download_links", "?"),
                    "help": fm.get("literature_help_submitted", "?"),
                    "content": content,
                }
            except Exception:
                pass

    # ── 设置栏 ──
    col0, col1, col2, col3, col4, col5 = st.columns([0.7, 0.7, 0.7, 0.6, 0.6, 1.2])
    with col0:
        agent_on = st.toggle("Agent 模式", st.session_state.qa_agent_mode,
                            help="开启后，系统会自主规划并分步执行复杂任务（如文献综述、理论对比）。关闭则为普通问答。")
        if agent_on != st.session_state.qa_agent_mode:
            st.session_state.qa_agent_mode = agent_on
    with col1:
        n = st.number_input("检索篇数", 3, 15, st.session_state.qa_top_n, step=1)
        if n != st.session_state.qa_top_n:
            st.session_state.qa_top_n = n
            _qa_top_n = n
    with col2:
        ext = st.toggle("外部知识", st.session_state.qa_use_external)
        if ext != st.session_state.qa_use_external:
            st.session_state.qa_use_external = ext
            _qa_use_external = ext
    with col3:
        yf = st.number_input("年份起", 1990, 2030, st.session_state.qa_year_from or 2020, step=1, format="%d")
        st.session_state.qa_year_from = yf if yf != 2020 or st.session_state.qa_year_from else None
    with col4:
        yt = st.number_input("年份止", 1990, 2030, st.session_state.qa_year_to or 2026, step=1, format="%d")
        st.session_state.qa_year_to = yt if yt != 2026 or st.session_state.qa_year_from else None
    with col5:
        col_papers, col_save = st.columns(2)
        with col_papers:
            if st.button("检索详情", use_container_width=True, help="显示上次检索的文献及评分"):
                st.session_state._show_retrieval = not st.session_state.get("_show_retrieval", False)
        with col_save:
            if st.button("保存到 Obsidian", use_container_width=True, help="保存当前对话到 Obsidian QA笔记"):
                if st.session_state.qa_chat_history:
                    _QA_NOTES_DIR.mkdir(parents=True, exist_ok=True)
                    now = datetime.now()
                    filename = f"QA_{now.strftime('%Y%m%d_%H%M%S')}.md"
                    filepath = _QA_NOTES_DIR / filename
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(f"---\ndate: {now.isoformat()}\nquestion: {st.session_state.qa_chat_history[0]['content'][:80] if st.session_state.qa_chat_history else ''}\n---\n\n")
                        for msg in st.session_state.qa_chat_history:
                            role_label = "**Q**" if msg["role"] == "user" else "**A**"
                            f.write(f"{role_label}: {msg['content']}\n\n")
                    st.toast(f"已保存: {filename}", icon="✅")
                else:
                    st.toast("没有对话内容", icon="⚠️")

    # ── 检索简报卡片 ──
    if latest_briefing:
        with st.expander(
            f"上次检索简报 — {latest_briefing['date']}  "
            f"(新文献 {latest_briefing['total']} 篇 | 下载 {latest_briefing['with_links']} | 求助 {latest_briefing['help']})",
            expanded=False
        ):
            st.caption("AI 会自动将此简报作为上下文参考。点击展开查看完整内容。")
            # 只显示正文(跳过 YAML frontmatter)
            body = latest_briefing["content"].split("---", 2)[-1] if latest_briefing["content"].count("---") >= 2 else latest_briefing["content"]
            st.markdown(body[:4000] + ("\n\n...(过长截断)" if len(body) > 4000 else ""))
    elif daily_dir.exists() and not briefing_files:
        st.info("还没有检索简报。在 Agent 页面执行一次自主检索后，简报会自动推送到这里。")

    # ── 渲染历史 ──
    for msg in st.session_state.qa_chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 处理自动追问
    if question := (st.session_state.pop("_auto_question", None) or st.chat_input("输入你的学术问题...")):
        # 重置上下文追问标记
        st.session_state._contextual_suggestions_generated = False
        st.session_state.suggestions_pool = []

        with st.chat_message("user"):
            st.markdown(question)

        # ── 自动注入最近检索简报作为上下文 ──
        _briefing_ctx = ""
        if latest_briefing:
            briefing_body = latest_briefing["content"].split("---", 2)[-1] if latest_briefing["content"].count("---") >= 2 else latest_briefing["content"]
            _briefing_ctx = (
                f"\n\n[系统上下文：最近一次文献检索简报 ({latest_briefing['date']})]\n"
                f"共收集 {latest_briefing['total']} 篇新文献，"
                f"其中 {latest_briefing['with_links']} 篇有下载链接等待下载，"
                f"{latest_briefing['help']} 篇已通过文献求助提交。"
                f"以下是简报内容摘要，供你参考：\n{briefing_body[:2000]}"
            )
            question_augmented = question + _briefing_ctx
        else:
            question_augmented = question

        # ═══════════════════════════════════════════════════
        #  Agent 模式：规划 → 执行 → 综合
        #  如果计划为空 → 自动回退到助手模式
        # ═══════════════════════════════════════════════════
        use_agent = st.session_state.qa_agent_mode
        answer = None
        plan = None
        step_results = []

        if use_agent:
            # 1. 规划
            with st.spinner("Agent 正在规划..."):
                plan = _run_async(agent_plan(question_augmented, st.session_state.qa_chat_history))

            if plan is None:
                st.warning("规划失败，回退到普通问答模式。")
                use_agent = False
            elif len(plan) == 0:
                st.info("Agent 判断为简单问题，使用快速问答。")
                use_agent = False  # 回退到助手模式
            else:
                # 展示计划
                plan_text = "\n".join(
                    f"{i+1}. **{s['tool']}** — {s.get('reason', '')}"
                    for i, s in enumerate(plan)
                )
                with st.status(f"执行计划 ({len(plan)} 步)") as status_container:
                    st.markdown(plan_text)

                    # 2. 逐步执行
                    def _progress(i, total, tool, args, reason, state):
                        emoji = {"running": "⏳", "done": "✅", "error": "❌"}.get(state, "⏳")
                        arg_preview = ", ".join(f"{k}={str(v)[:40]}" for k, v in (args or {}).items())
                        if state == "done":
                            st.success(f"{emoji} **{tool}** — {reason}")
                        elif state == "error":
                            st.error(f"{emoji} **{tool}** — {reason}")
                        else:
                            st.markdown(f"{emoji} **{tool}** — {reason}  `({arg_preview})`")

                    step_results = _run_async(agent_execute_plan(plan, _progress))

                    # 3. 综合
                    if step_results:
                        st.markdown("---")
                        with st.spinner("🧠 综合所有步骤结果..."):
                            answer = _run_async(agent_synthesize(question_augmented, plan, step_results))
                        if answer:
                            status_container.update(label="✅ Agent 执行完成", state="complete")
                        else:
                            status_container.update(label="⚠️ 综合失败", state="error")

            # Agent 没产出答案时的兜底
            if use_agent and not answer:
                if step_results:
                    # 有步骤结果但综合失败，直接用步骤结果拼凑
                    parts = []
                    for s in step_results:
                        if s.get("ok") and s.get("result"):
                            parts.append(f"**{s['tool']}**: {json.dumps(s['result'], ensure_ascii=False)[:500]}")
                    answer = "\n\n".join(parts) if parts else "Agent 执行完成，但无法综合结果。"

        # ═══════════════════════════════════════════════════
        #  助手模式（或 Agent 回退）
        # ═══════════════════════════════════════════════════
        if not use_agent:
            # 年份过滤（拼接到 query 中）
            yf = st.session_state.qa_year_from
            yt = st.session_state.qa_year_to
            if yf is not None or yt is not None:
                yf_val = yf or 1990
                yt_val = yt or 2030
                question_aug = f"{yf_val}-{yt_val}年 {question_augmented}"
            else:
                question_aug = question_augmented

            # 概念扩展
            concept_matches = {}
            for cn_term, en_terms in _CONCEPT_MAP.items():
                if cn_term in question:
                    concept_matches[cn_term] = en_terms
            st.session_state.qa_last_concepts = concept_matches

            # 检索
            _qa_top_n = st.session_state.qa_top_n
            _qa_use_external = st.session_state.qa_use_external
            relevant = _retrieve_papers(question_aug)
            st.session_state.qa_last_papers = relevant

            # 打分
            retrieval_detail = {"concepts": concept_matches, "query": question_aug, "year_filter": (yf, yt)}
            scores_display = []
            if relevant:
                scored = _score_and_rank(question_aug, relevant)
                indices = [_qa_paper_index.index(p) for p in relevant if p in _qa_paper_index]
                sem_scores = _semantic_scores(question_aug, indices) if indices else [0]*len(relevant)
                for i in range(len(relevant)):
                    ts = scored[i][1] if i < len(scored) else 0
                    ss = sem_scores[i] if i < len(sem_scores) else 0
                    scores_display.append((ts, ss))
                st.session_state.qa_last_scores = scores_display
            retrieval_detail["token_scores"] = [f"{s[0]:.3f}" for s in scores_display]
            retrieval_detail["semantic_scores"] = [f"{s[1]:.3f}" for s in scores_display]
            retrieval_detail["paper_count"] = len(relevant)
            years_in_result = [str(p.get("year","?")) for p in relevant if p.get("year")]
            retrieval_detail["year_distribution"] = dict(Counter(years_in_result))
            st.session_state.qa_last_retrieval_detail = retrieval_detail

            # 检索透明度面板
            if st.session_state.get("_show_retrieval", False) and relevant:
                with st.expander(f"检索流水线: 匹配 {len(relevant)} 篇文献", expanded=False):
                    if concept_matches:
                        st.caption("**Step 1: 概念扩展** (中文学术术语 → 英文搜索词)")
                        for cn, en in concept_matches.items():
                            st.markdown(f"- `{cn}` → `{en[:100]}`")
                    else:
                        st.caption("**Step 1: 概念扩展** — 无匹配")
                    st.caption(f"**Step 2: Token 匹配** (中文bigram + 英文word, 加权: 标题×4 / 关键词×3 / 正文×1.5)")
                    st.caption(f"**Step 3: 语义重排** (3-gram+4-gram TF-IDF, 55%token + 45%语义)")
                    years = retrieval_detail.get("year_distribution", {})
                    if years:
                        st.caption(f"**Step 4: 年份过滤** → {len(years)} 个年份")
                        st.bar_chart({k: years[k] for k in sorted(years)}, horizontal=True)
                    st.caption(f"**最终排名** (Blended Score):")
                    for i, p in enumerate(relevant, 1):
                        ts, ss = scores_display[i-1] if i-1 < len(scores_display) else (0, 0)
                        blended = 0.55*ts + 0.45*ss
                        st.markdown(
                            f"`[{i}]` {p.get('first_author','?')} ({p.get('year','?')}) — "
                            f"Token:{ts:.3f} + 语义:{ss:.3f} = **{blended:.3f}** — "
                            f"*{p.get('title','')[:50]}*"
                        )
                        st.progress(min(blended, 1.0))
            elif not relevant:
                st.info("未找到直接匹配的本地文献。请尝试更宽泛的关键词或调整年份范围。")

            # 调用 DeepSeek
            if not st.session_state.qa_use_external and not relevant:
                answer = "本地文献无匹配，且外部知识已关闭。请尝试换个问题或开启外部知识。"
            else:
                with st.spinner("DeepSeek V4 Pro 思考中..."):
                    messages = _build_qa_messages(question, relevant, st.session_state.qa_chat_history)
                    answer = _run_async(_chat_via_deepseek(messages))
                    if not answer:
                        answer = "DeepSeek API 调用失败，请检查网络和 API Key。"

        # ═══════════════════════════════════════════════════
        #  通用：展示答案 + 验证 + 追问 + 保存
        # ═══════════════════════════════════════════════════
        with st.chat_message("assistant"):
            st.markdown(_console_safe(answer))

        # 引用验证（仅助手模式有 relevant 信息）
        if not st.session_state.qa_agent_mode and relevant and answer:
            warnings = _verify_answer_claims(answer, relevant, _qa_paper_index)
            if warnings:
                with st.expander("⚠️ 引用验证提醒"):
                    for w in warnings:
                        st.markdown(f"- {w}")

        # 动态智能追问（基于回答内容生成）
        if answer and len(answer) > 50:
            with st.expander("继续探讨", expanded=True):
                # 深度追问：用回答内容生成上下文化的追问
                if "suggestions_ready" not in st.session_state:
                    st.session_state.suggestions_ready = False
                if "suggestions_pool" not in st.session_state:
                    st.session_state.suggestions_pool = []

                if not st.session_state.suggestions_pool:
                    # 先显示通用追问（无 API 延迟）
                    generic_suggestions = [
                        "这些观点之间有什么共识和分歧？",
                        "有哪些实证证据支持这些理论？",
                        "你能推荐几篇这个方向的关键文献吗？",
                    ]
                    st.session_state.suggestions_pool = generic_suggestions
                    st.session_state.suggestions_ready = True

                cols = st.columns(min(3, len(st.session_state.suggestions_pool)))
                for i, sug in enumerate(st.session_state.suggestions_pool[:3]):
                    if cols[i].button(sug, key=f"sug_{i}_{hash(question)%100000}", use_container_width=True):
                        st.session_state._auto_question = sug
                        st.rerun()

                # 异步生成上下文化追问（下次回答后显示）
                if not st.session_state.get("_contextual_suggestions_generated", False):
                    st.session_state._contextual_suggestions_generated = True
                    try:
                        ctx_prompt = f"""Based on this academic Q&A exchange, generate 3 natural follow-up questions a PhD student might ask next. The questions should be specific to the content, not generic. Keep each under 30 words. Output one per line, no numbering.

Question: {question[:200]}
Answer summary: {answer[:500]}

Follow-up questions:"""
                        ctx_msgs = [
                            {"role": "system", "content": "You generate contextual academic follow-up questions. Output 3 lines, no numbering."},
                            {"role": "user", "content": ctx_prompt},
                        ]
                        ctx_answer = _run_async(_chat_via_deepseek(ctx_msgs))
                        if ctx_answer:
                            ctx_sugs = [l.strip("-•123456789. ") for l in ctx_answer.strip().split("\n") if l.strip() and len(l.strip()) > 10]
                            if len(ctx_sugs) >= 2:
                                st.session_state.suggestions_pool = ctx_sugs[:3]
                    except Exception:
                        pass  # 上下文追问失败用通用追问兜底

        # 保存历史（多会话架构）
        st.session_state.qa_chat_history.append({"role": "user", "content": question})
        st.session_state.qa_chat_history.append({"role": "assistant", "content": answer})
        if len(st.session_state.qa_chat_history) > 30:
            st.session_state.qa_chat_history = st.session_state.qa_chat_history[-30:]

        # 自动保存到当前会话
        sid = st.session_state.qa_session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        if not st.session_state.qa_session_id:
            st.session_state.qa_session_id = sid
            st.session_state.qa_session_name = _generate_session_name(st.session_state.qa_chat_history)
        _save_qa_session(sid, st.session_state.qa_session_name, st.session_state.qa_chat_history)
        st.rerun()


# ═══════════════════════════════════════════════════════════════
#  深度阅读 + 入库
# ═══════════════════════════════════════════════════════════════


elif page == "文献笔记":
    st.header("文献笔记")

    full_data = _load_dashboard_data()
    if not full_data:
        st.info("知识库为空。请先在「深度阅读 + 入库」页面处理 PDF。")
    else:
        # ── 搜索栏 ──
        st.markdown("##### 检索")
        col_search, col_year, col_sort = st.columns([3, 1, 1])
        with col_search:
            search_query = st.text_input(
                "搜索标题、关键词、作者、期刊、摘要...",
                placeholder="输入任意关键词...",
                label_visibility="collapsed",
            )
        with col_year:
            year_options = ["全部年份"] + sorted(set(
                str(p.get("年份", "")) for p in full_data
                if p.get("年份") and str(p.get("年份")).isdigit()
            ), reverse=True)
            year_filter = st.selectbox("年份", year_options, label_visibility="collapsed")
        with col_sort:
            sort_by = st.selectbox(
                "排序",
                ["年份 ↓", "影响因子 ↓", "标题 A-Z", "最近添加"],
                label_visibility="collapsed",
            )

        # ── 过滤 ──
        filtered = []
        q = search_query.strip().lower() if search_query else ""
        for p in full_data:
            # 年份过滤
            if year_filter != "全部年份":
                if str(p.get("年份", "")) != year_filter:
                    continue
            # 文本搜索
            if q:
                searchable = " ".join([
                    str(p.get("标题", "")),
                    str(p.get("关键词", "")),
                    str(p.get("作者", "")),
                    str(p.get("第一作者", "")),
                    str(p.get("通讯作者", "")),
                    str(p.get("期刊", "")),
                    str(p.get("摘要", "")),
                    str(p.get("研究背景与动机", "")),
                    str(p.get("研究问题", "")),
                    str(p.get("研究结论", "")),
                ]).lower()
                if q not in searchable:
                    continue
            filtered.append(p)

        # ── 排序 ──
        if sort_by == "影响因子 ↓":
            def _if_val(p):
                try: return float(p.get("影响因子", 0))
                except: return 0.0
            filtered.sort(key=_if_val, reverse=True)
        elif sort_by == "标题 A-Z":
            filtered.sort(key=lambda p: p.get("标题", ""))
        elif sort_by == "最近添加":
            filtered.sort(key=lambda p: p.get("处理时间", p.get("阅读时间", "")), reverse=True)
        else:  # 年份 ↓
            def _yr_val(p):
                try: return int(p.get("年份", 0))
                except: return 0
            filtered.sort(key=_yr_val, reverse=True)

        # ── 结果概览 ──
        st.caption(f"共 {len(filtered)} 篇" + (f"（知识库 {len(full_data)} 篇）" if q or year_filter != "全部年份" else ""))

        if not filtered:
            st.info("没有匹配的文献，请调整搜索条件。")
        else:
            # ── 论文列表 ──
            for i, paper in enumerate(filtered):
                title = paper.get("标题", "无标题")[:150]
                authors = paper.get("作者", paper.get("第一作者", ""))
                journal = paper.get("期刊", "")
                year = paper.get("年份", "")
                if_val = paper.get("影响因子", "")
                keywords = paper.get("关键词", "")
                doi = paper.get("doi", "")

                # 卡片头
                meta_badges = []
                if year: meta_badges.append(str(year))
                if journal: meta_badges.append(f"*{journal}*")
                if if_val: meta_badges.append(f"IF {if_val}")

                with st.expander(f"**{title}**  —  {' · '.join(meta_badges)}"):
                    # ── 元信息 ──
                    col_a, col_b = st.columns([2, 1])
                    with col_a:
                        if authors:
                            st.caption(f"**作者**: {authors}")
                        if doi:
                            st.caption(f"DOI: `{doi}`")
                    with col_b:
                        if keywords:
                            kw_list = [k.strip() for k in keywords.replace(";", ",").split(",") if k.strip()]
                            if kw_list:
                                st.caption(" ".join(f"`{k}`" for k in kw_list[:10]))

                    st.divider()

                    # ── 核心摘要 ──
                    abstract = paper.get("摘要", "")
                    if abstract and len(abstract) > 20:
                        st.markdown("**摘要**")
                        st.markdown(abstract[:500] + ("..." if len(abstract) > 500 else ""))

                    conclusion = paper.get("研究结论", "")
                    if conclusion and len(conclusion) > 20:
                        st.markdown("**研究结论**")
                        st.success(conclusion[:500] + ("..." if len(conclusion) > 500 else ""))

                    # ── 结构化字段 ──
                    col1, col2 = st.columns(2)
                    with col1:
                        bg = paper.get("研究背景与动机", "")
                        if bg and len(bg) > 20:
                            with st.expander("研究背景与动机", expanded=False):
                                st.markdown(bg[:800])

                        rq = paper.get("研究问题", "")
                        if rq and len(rq) > 10:
                            with st.expander("研究问题与假设", expanded=False):
                                st.markdown(rq[:800])

                        variables = paper.get("变量汇总", "")
                        if variables and len(variables) > 10:
                            with st.expander("变量汇总", expanded=False):
                                st.markdown(variables[:800])

                        method = paper.get("研究方法", "")
                        if method and len(method) > 10:
                            with st.expander("研究方法", expanded=False):
                                st.markdown(method[:800])

                    with col2:
                        findings = paper.get("研究发现", "")
                        if findings and len(findings) > 10:
                            with st.expander("研究发现", expanded=False):
                                st.markdown(findings[:800])

                        contribution = paper.get("理论贡献", "")
                        if contribution and len(contribution) > 10:
                            with st.expander("理论贡献", expanded=False):
                                st.markdown(contribution[:800])

                        gaps = paper.get("研究局限与展望", "")
                        if gaps and len(gaps) > 10:
                            with st.expander("研究局限与展望", expanded=False):
                                st.markdown(gaps[:800])

                        fig_analysis = paper.get("图表分析", "")
                        if fig_analysis and len(fig_analysis) > 10 and _load_config().get("enable_figure_analysis", False):
                            with st.expander("图表分析", expanded=False):
                                st.markdown(fig_analysis[:1000])

                    # ── 亮点 ──
                    highlights = paper.get("亮点", "")
                    if highlights and len(highlights) > 10:
                        with st.expander("文章亮点", expanded=False):
                            st.markdown(highlights[:800])

                    # ── 底部元数据 ──
                    reading_mode = paper.get("阅读方式", "")
                    reading_date = paper.get("阅读时间", paper.get("处理时间", ""))
                    if reading_mode or reading_date:
                        st.caption(f"阅读方式: {reading_mode or '—'} | 处理时间: {reading_date or '—'}")


# ═══════════════════════════════════════════════════════════════
elif page == "Agent":
    st.header("Agent")

    # ── Agent 启动函数 ──
    def _do_launch_agent(yr_s, yr_e, tgt_papers, mx_pages, jrnl_filter, jrnl_free, kw_override):
        """启动 Agent 子进程。"""
        import subprocess as _sp
        import os as _os
        worker_script = SCRIPT_DIR / "run_agent_worker.py"
        log_dir = SCRIPT_DIR / "运行日志"
        log_dir.mkdir(parents=True, exist_ok=True)

        # ── PID 锁：防止同时启动多个 Worker ──
        pid_file = log_dir / "worker.pid"
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                # 检查该 PID 是否仍在运行
                import ctypes
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, old_pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    st.error(f"⚠ Agent 已在运行中（PID {old_pid}）。请等待当前任务完成，或先终止它。")
                    return
            except Exception:
                pass  # PID 无效，可以继续
            # 清理僵尸 PID 文件
            try:
                pid_file.unlink()
            except Exception:
                pass

        cmd = [
            sys.executable, str(worker_script),
            "--year-start", str(yr_s),
            "--year-end", str(yr_e),
            "--target-papers", str(tgt_papers),
            "--max-pages", str(mx_pages),
        ]
        if kw_override.strip():
            cmd.extend(["--keyword-override", kw_override.strip()])

        # 合并期刊过滤
        all_journals = list(jrnl_filter or [])
        if jrnl_free.strip():
            all_journals.extend([j.strip() for j in jrnl_free.split(",") if j.strip()])
        if all_journals:
            cmd.extend(["--journal-filter", ",".join(all_journals)])

        try:
            proc = _sp.Popen(
                cmd, cwd=str(SCRIPT_DIR),
                stdout=open(log_dir / "worker_stdout.log", "a", encoding="utf-8"),
                stderr=open(log_dir / "worker_stderr.log", "a", encoding="utf-8"),
                env={**_os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=0x00000008 if sys.platform == "win32" else 0,
            )
            # 写入 PID 文件
            pid_file.write_text(str(proc.pid))
            st.success("Agent Worker 已启动（独立进程，关闭网页不中断）")
            st.toast("Agent 已启动")
        except Exception as e:
            st.error(f"Worker 启动失败: {e}")

    # ── 信号文件辅助函数 ──
    def _create_signal(filename: str):
        (SCRIPT_DIR / "运行日志" / filename).touch()

    def _remove_signal(filename: str):
        p = SCRIPT_DIR / "运行日志" / filename
        if p.exists():
            p.unlink()

    def _signal_exists(filename: str) -> bool:
        return (SCRIPT_DIR / "运行日志" / filename).exists()

    # ── 运行日志目录 ──
    runs_dir = SCRIPT_DIR / "运行日志" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # ── 检测活跃运行（含心跳检查，过滤僵尸会话）──
    active_run = None
    run_files = sorted(runs_dir.glob("*.json"), reverse=True)
    for rf in run_files:
        try:
            d = json.loads(rf.read_text(encoding="utf-8"))
            if d.get("status") == "running":
                # 心跳检测：90秒无心跳 → Worker 已崩溃
                if AgentRunLogger.is_heartbeat_stale(d, max_age_seconds=300):
                    # 自动标记为 crashed
                    d["status"] = "crashed"
                    d["_crashed_reason"] = "Worker heartbeat lost"
                    d["ended_at"] = datetime.now().isoformat()
                    tmp = Path(str(rf) + ".tmp")
                    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp.replace(rf)
                    continue
                active_run = d
                break
        except Exception:
            pass

    tab1, tab2 = st.tabs(["运行", "运行历史"])

    # ═══════════════════════════════════════════════════════════
    # Tab 1: 运行
    # ═══════════════════════════════════════════════════════════
    with tab1:
        # ── VPN 提醒 ──
        with st.expander("VPN 提醒", expanded=True):
            st.warning(
                "**请先连接 湖南大学 VPN**\n\n"
                "SPIS 基于学校 IP 白名单认证，不连 VPN 将无法检索。\n"
                "Agent 启动后会检测 VPN 状态，最多等待 5 分钟。"
                "超时则跳过检索，仅执行深度阅读 + 入库。"
            )

        # ── 关键词游标状态 ──
        cursor = _load_config().get("_keyword_cursor", {})
        if cursor:
            next_kw, scope, ci, ki = _get_next_keyword(cursor)
            if next_kw:
                cat_names = ["Broad", "Narrow", "Chinese"]
                cat_name = cat_names[ci] if ci < 3 else f"Cat{ci}"
                st.info(
                    f"📍 **关键词游标**: `{next_kw}` "
                    f"({cat_name} #{ki + 1}，第 {ci + 1}/3 组)"
                )
            else:
                st.success(
                    "✅ **所有关键词已遍历完毕！**\n\n"
                    "可点击下方「🔄 重置游标」从第一个关键词重新开始，"
                    "或使用高级搜索指定新关键词。"
                )
        else:
            st.caption("📍 关键词游标: 从头开始")

        # ── 高级搜索面板 ──
        defaults = _load_config().get("advanced_search_defaults", {})
        with st.expander("高级搜索", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                custom_kw = st.text_input(
                    "自定义关键词（留空=使用游标关键词）",
                    placeholder='e.g. \"generative AI\" AND \"advertising\"',
                    key="_agent_custom_kw",
                )
                yr_start = st.number_input(
                    "起始年份", 1990, 2030,
                    value=defaults.get("year_start", 2025),
                    key="_agent_yr_start",
                )
                yr_end = st.number_input(
                    "截止年份", 1990, 2030,
                    value=defaults.get("year_end", 2026),
                    key="_agent_yr_end",
                )
            with col2:
                target_papers = st.number_input(
                    "本次收集论文数", 1, 50,
                    value=defaults.get("target_papers", 5),
                    help="本次运行总共收集多少篇论文（跨关键词总计）",
                    key="_agent_target_papers",
                )
                max_pages = st.number_input(
                    "每关键词最大翻页数", 1, 100,
                    value=defaults.get("max_pages_per_keyword", 10),
                    key="_agent_max_pages",
                )

            # 期刊过滤
            whitelist_journals = list(_get_effective_whitelist()) if callable(_get_effective_whitelist) else []
            default_jf = defaults.get("journal_filter", [])
            journal_filter = st.multiselect(
                "期刊过滤（多选，留空=使用默认白名单）",
                options=sorted(whitelist_journals),
                default=[j for j in default_jf if j in whitelist_journals],
                help="仅搜索这些期刊的论文",
                key="_agent_journal_filter",
            )
            journal_free = st.text_input(
                "或其他期刊名（逗号分隔）",
                placeholder="Journal of Sustainable Marketing",
                key="_agent_journal_free",
            )

            # 操作按钮行
            col_adv1, col_adv2 = st.columns(2)
            with col_adv1:
                if st.button("重置关键词游标", use_container_width=True,
                            help="从第一个关键词重新开始"):
                    _write_keyword_cursor(0, 0)
                    st.toast("游标已重置")
                    st.rerun()
            with col_adv2:
                if st.button("保存为默认", use_container_width=True,
                            help="将当前高级搜索参数保存为默认配置"):
                    cfg_to_save = _load_config()
                    cfg_to_save["advanced_search_defaults"] = {
                        "year_start": yr_start,
                        "year_end": yr_end,
                        "target_papers": target_papers,
                        "max_pages_per_keyword": max_pages,
                        "journal_filter": journal_filter,
                    }
                    _save_config(cfg_to_save)
                    st.toast("已保存默认配置")
                    st.rerun()

        # ── 启动按钮组 ──
        st.divider()
        launch_cols = st.columns([2, 1, 1, 1])
        with launch_cols[0]:
            launch_disabled = active_run is not None
            launch_label = "启动 Agent" if not launch_disabled else "Agent 运行中..."
            if st.button(launch_label, type="primary", disabled=launch_disabled,
                         use_container_width=True, key="_agent_launch"):
                # 检查是否修改了高级搜索
                cfg_current = _load_config()
                current_defaults = cfg_current.get("advanced_search_defaults", {})
                panel_differs = (
                    yr_start != current_defaults.get("year_start", 2025) or
                    yr_end != current_defaults.get("year_end", 2026) or
                    target_papers != current_defaults.get("target_papers", 5) or
                    max_pages != current_defaults.get("max_pages_per_keyword", 10) or
                    bool(journal_filter) != bool(current_defaults.get("journal_filter", [])) or
                    bool(custom_kw.strip())
                )
                if panel_differs:
                    st.session_state._confirm_launch = True
                    st.session_state._launch_params = {
                        "yr_start": yr_start, "yr_end": yr_end,
                        "target_papers": target_papers, "max_pages": max_pages,
                        "journal_filter": journal_filter,
                        "journal_free": journal_free,
                        "custom_kw": custom_kw,
                    }
                    st.rerun()
                else:
                    _do_launch_agent(yr_start, yr_end, target_papers, max_pages,
                                    journal_filter, journal_free, custom_kw)

        # ── 确认对话框（参数与默认不同时弹出）──
        if st.session_state.get("_confirm_launch"):
            lp = st.session_state._confirm_launch_params = st.session_state.get("_launch_params", {})
            st.warning("⚠️ 高级搜索参数与默认配置不同，请选择：")
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                if st.button("仅本次使用", use_container_width=True, key="_confirm_once"):
                    _do_launch_agent(
                        lp.get("yr_start", 2025), lp.get("yr_end", 2026),
                        lp.get("target_papers", 5), lp.get("max_pages", 10),
                        lp.get("journal_filter", []), lp.get("journal_free", ""),
                        lp.get("custom_kw", ""),
                    )
                    st.session_state._confirm_launch = False
                    st.rerun()
            with cc2:
                if st.button("保存并启动", use_container_width=True, key="_confirm_save"):
                    cfg_to_save = _load_config()
                    cfg_to_save["advanced_search_defaults"] = {
                        "year_start": lp.get("yr_start", 2025),
                        "year_end": lp.get("yr_end", 2026),
                        "target_papers": lp.get("target_papers", 5),
                        "max_pages_per_keyword": lp.get("max_pages", 10),
                        "journal_filter": lp.get("journal_filter", []),
                    }
                    _save_config(cfg_to_save)
                    _do_launch_agent(
                        lp.get("yr_start", 2025), lp.get("yr_end", 2026),
                        lp.get("target_papers", 5), lp.get("max_pages", 10),
                        lp.get("journal_filter", []), lp.get("journal_free", ""),
                        lp.get("custom_kw", ""),
                    )
                    st.session_state._confirm_launch = False
                    st.rerun()
            with cc3:
                if st.button("取消", use_container_width=True, key="_confirm_cancel"):
                    st.session_state._confirm_launch = False
                    st.rerun()

        # ── 控制按钮 ──
        with launch_cols[1]:
            if st.button("⏸ 暂停", disabled=active_run is None, use_container_width=True,
                        help="当前步骤完成后暂停", key="_agent_pause"):
                _create_signal(".pause")
                st.toast("暂停信号已发送")
                st.rerun()
        with launch_cols[2]:
            paused = _signal_exists(".pause")
            if st.button("▶ 继续", disabled=not paused, use_container_width=True,
                        key="_agent_resume"):
                _remove_signal(".pause")
                st.toast("继续信号已发送")
                st.rerun()
        with launch_cols[3]:
            if st.button("⏹ 终止", disabled=active_run is None, use_container_width=True,
                        help="终止 Agent 运行", key="_agent_term"):
                _create_signal(".terminate")
                _remove_signal(".pause")
                st.toast("终止信号已发送")
                st.rerun()

        # ── 实时监控 ──
        if active_run:
            st.divider()
            st.warning("Agent 正在运行中 — 实时监控（每 3 秒自动刷新）")

            # Phase 状态
            p1_status = active_run.get("phase1", {}).get("status", "pending")
            p2_status = active_run.get("phase2", {}).get("status", "pending")
            p3_status = active_run.get("phase3", {}).get("status", "pending")
            is_paused = active_run.get("_paused", False)

            if is_paused:
                st.info("⏸ Agent 已暂停")

            pc1, pc2, pc3 = st.columns(3)
            for col, label, status in [
                (pc1, "Phase 1: 检索", p1_status),
                (pc2, "Phase 2: 深度阅读", p2_status),
                (pc3, "Phase 3: 索引同步", p3_status),
            ]:
                with col:
                    icon = {"completed": "✅", "running": "⏳", "failed": "❌",
                            "pending": "⬜", "skipped": "⏭"}.get(status, "⬜")
                    st.caption(f"{icon} {label}")
                    if status == "running":
                        st.progress(0.5)

            # Phase 1 metrics
            p1 = active_run.get("phase1", {})
            if p1.get("status") not in ("pending",):
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("检索到", f"{p1.get('papers_total', 0)} 篇")
                mc2.metric("有下载链接", f"{p1.get('papers_with_links', 0)} 篇")
                mc3.metric("已文献求助", f"{p1.get('help_submitted', 0)} 篇")

            # Phase 2 metrics
            p2 = active_run.get("phase2", {})
            if p2.get("status") not in ("pending",):
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("已入库", f"{p2.get('papers_processed', 0)} 篇")
                mc2.metric("失败", f"{p2.get('papers_failed', 0)} 篇")
                mc3.metric("跳过", f"{p2.get('papers_skipped', 0)} 篇")

                # 当前处理的论文
                current = p2.get("_currently_processing")
                if current:
                    st.caption(f"正在处理: **{current.get('title', '?')[:80]}**")

                # 已完成的论文摘要
                for pap in p2.get("papers", []):
                    if pap.get("status") == "success":
                        with st.expander(f"✅ {pap.get('title', '?')[:80]}", expanded=False):
                            st.caption(f"*{pap.get('journal', '?')}* ({pap.get('year', '?')})")
                            if pap.get("core_summary"):
                                st.info(pap["core_summary"][:300])
                    elif pap.get("status") == "failed":
                        st.caption(f"❌ {pap.get('title', pap.get('file', '?'))[:80]} — {pap.get('failure_reason', '?')}")

            # Phase 3
            p3 = active_run.get("phase3", {})
            if p3.get("status") == "completed":
                st.success(f"Phase 3 完成 — 索引 {p3.get('index_size', '?')} 篇")

            # 关键词游标进度
            kc = active_run.get("keyword_cursor")
            if kc:
                st.caption(
                    f"📍 当前关键词: `{kc.get('current_keyword', '?')}` | "
                    f"已收: {kc.get('papers_collected_this_keyword', 0)} 篇"
                )

            time.sleep(3)
            st.rerun()

        # ── 空状态：无运行中 ──
        if not active_run:
            st.divider()
            st.caption("点击「启动 Agent」开始全自动检索 + 深度阅读 + 入库。关闭网页不影响运行。")

    # ═══════════════════════════════════════════════════════════
    # Tab 2: 运行历史
    # ═══════════════════════════════════════════════════════════
    with tab2:
        if not run_files:
            st.info("还没有运行记录。点击「启动 Agent」运行完成后会自动生成。")
        else:
            # ── 概览卡片 ──
            total_runs = len(run_files)
            completed_runs = 0
            total_retrieved = 0
            total_processed = 0
            for rf in run_files:
                try:
                    d = json.loads(rf.read_text(encoding="utf-8"))
                    if d.get("status") == "completed":
                        completed_runs += 1
                    total_retrieved += d.get("phase1", {}).get("papers_total", 0)
                    total_processed += d.get("phase2", {}).get("papers_processed", 0)
                except Exception:
                    pass

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("总运行次数", total_runs)
            c2.metric("✅ 成功", completed_runs)
            c3.metric("累计检索", f"{total_retrieved} 篇")
            c4.metric("累计入库", f"{total_processed} 篇")

            st.divider()
            st.subheader("运行历史")

            for rf in run_files:
                try:
                    run = json.loads(rf.read_text(encoding="utf-8"))
                except Exception:
                    continue

                run_id = run.get("run_id", rf.stem)
                started = run.get("started_at", "")[:16]
                status = run.get("status", "?")
                status_icon_ = {"completed": "✅", "failed": "❌", "running": "🔄",
                               "terminated": "⏹"}.get(status, "❓")
                p1_total = run.get("phase1", {}).get("papers_total", 0)
                p1_status = run.get("phase1", {}).get("status", "?")
                p1_links = run.get("phase1", {}).get("papers_with_links", 0)
                p2_ok = run.get("phase2", {}).get("papers_processed", 0)
                p2_fail = run.get("phase2", {}).get("papers_failed", 0)
                vpn_info = run.get("vpn", {})
                kw_exhausted = run.get("keywords_exhausted", False)

                duration = ""
                if run.get("ended_at") and run.get("started_at"):
                    try:
                        from dateutil.parser import parse as dt_parse
                        delta = dt_parse(run["ended_at"]) - dt_parse(run["started_at"])
                        mins = int(delta.total_seconds() // 60)
                        secs = int(delta.total_seconds() % 60)
                        duration = f" · ⏱ {mins}分{secs}秒" if mins > 0 else f" · ⏱ {secs}秒"
                    except Exception:
                        pass

                # VPN tag
                vpn_tag = ""
                if vpn_info:
                    if vpn_info.get("skipped"):
                        vpn_tag = " · VPN未连"
                    elif vpn_info.get("connected"):
                        vpn_tag = f" · VPN已连({vpn_info.get('waited_seconds', 0):.0f}s)"

                # Phase 1 label
                if p1_status == "skipped":
                    p1_label = "检索跳过"
                else:
                    p1_label = f"{p1_total}篇检索"

                if kw_exhausted:
                    vpn_tag += " · 关键词遍历完毕"

                expander_label = (
                    f"{status_icon_} **{started}** — "
                    f"{p1_label} | {p2_ok}篇入库"
                    f"{' | ' + str(p2_fail) + '失败' if p2_fail else ''}"
                    f"{vpn_tag}{duration}"
                )
                with st.expander(expander_label):
                    tab_r1, tab_r2, tab_r3, tab_r4 = st.tabs([
                        "检索清单", "深度阅读", "简报", "配置"
                    ])

                    with tab_r1:
                        p1_status_ = run.get("phase1", {}).get("status", "")
                        p1_papers = run.get("phase1", {}).get("papers", [])
                        if p1_status_ == "skipped":
                            reason = run.get("phase1", {}).get("reason", "VPN 未连接")
                            st.warning(f"⏭ **Phase 1 已跳过**：{reason}")
                        elif p1_papers:
                            st.caption(
                                f"共 {p1_total} 篇：{p1_links} 篇有下载链接 "
                                f"| {run.get('phase1', {}).get('papers_without_links', 0)} 篇已文献求助"
                            )
                            for p in p1_papers:
                                icon = "有链接" if p.get("has_download_link") else "已求助"
                                st.markdown(f"{icon} **{p.get('title', '?')[:120]}**")
                                meta = []
                                if p.get("journal"):
                                    meta.append(f"*{p['journal']}*")
                                if p.get("year"):
                                    meta.append(str(p["year"]))
                                if p.get("keyword"):
                                    meta.append(f"`{p['keyword']}`")
                                st.caption(" | ".join(meta))

                    with tab_r2:
                        p2_papers = run.get("phase2", {}).get("papers", [])
                        if p2_papers:
                            for p in p2_papers:
                                if p.get("status") == "success":
                                    st.markdown(f"✅ **{p.get('title', '?')[:100]}**")
                                    st.caption(f"*{p.get('journal', '?')}* ({p.get('year', '?')})")
                                    if p.get("core_summary"):
                                        st.info(p["core_summary"][:250])
                                else:
                                    st.markdown(f"❌ {p.get('title', p.get('file', '?'))[:100]}")
                                    st.caption(f"原因：{p.get('failure_reason', '?')}")
                        else:
                            st.caption("无深度阅读记录")

                    with tab_r3:
                        briefing_path = run.get("briefing_path", "")
                        if briefing_path:
                            bp = Path(briefing_path)
                            if bp.exists():
                                st.markdown(bp.read_text(encoding="utf-8")[:5000])
                            else:
                                st.caption(f"简报文件不存在: {briefing_path}")
                        else:
                            st.caption("无简报")

                    with tab_r4:
                        cfg = run.get("config", {})
                        st.json({
                            "年份": f"{cfg.get('year_start', '?')}-{cfg.get('year_end', '?')}",
                            "关键词数": cfg.get("keywords_count", 0),
                            "关键词": cfg.get("keywords", [])[:10],
                            "运行ID": run_id,
                            "状态": status,
                        })
                        if kw_exhausted:
                            st.success("本次运行中所有关键词遍历完毕")

elif page == "知识库仪表盘":
    st.header("知识库仪表盘")

    idx_count, idx = _get_paper_index()
    full_data = _load_dashboard_data()  # 完整 17 字段数据
    total_papers = len(full_data) if full_data else idx_count  # 优先用 JSON 数据，与侧边栏统一
    if total_papers == 0:
        st.info("知识库为空。请先阅读文献。")
    else:
        # ── 总览卡片 ──
        years_list = [int(p.get("年份", 0)) for p in full_data if p.get("年份") and str(p.get("年份")).isdigit()]
        if_vals = [float(p.get("影响因子", 0)) for p in full_data if p.get("影响因子") and str(p.get("影响因子", "")).replace(".","").isdigit()]
        journals = set(p.get("期刊", "") for p in full_data if p.get("期刊") and p.get("期刊") != "原文未提及")

        # 阅读方式统计
        deep_count = sum(1 for p in full_data if p.get("变量汇总") and len(p.get("变量汇总", "")) > 50)
        conceptual_count = sum(1 for p in full_data if not p.get("变量汇总") or len(p.get("变量汇总", "")) < 20)

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("总文献数", total_papers)
        col2.metric("年份跨度", f"{min(years_list)}-{max(years_list)}" if years_list else "N/A")
        col3.metric("平均IF", f"{sum(if_vals)/len(if_vals):.1f}" if if_vals else "N/A")
        col4.metric("期刊数", len(journals))
        col5.metric("实证研究", f"{deep_count}篇 ({100*deep_count//max(total_papers,1)}%)")

        st.divider()

        # ── Tabs ──
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "年份/IF/期刊", "理论概念图", "变量网络",
            "🏷 主题关键词", "🔭 研究空白"
        ])

        # ── Tab 1: 年份/IF/期刊 ──
        with tab1:
            import pandas as pd
            sub_a, sub_b, sub_c = st.columns(3)
            with sub_a:
                st.caption("**年份分布**")
                if years_list:
                    year_counts = Counter(years_list)
                    st.bar_chart({str(y): year_counts[y] for y in sorted(year_counts)})
            with sub_b:
                st.caption("**IF 分布**")
                if if_vals:
                    if_bins = [0, 2, 4, 6, 8, 10, 15, 20, 50, 100]
                    if_labels = ["0-2", "2-4", "4-6", "6-8", "8-10", "10-15", "15-20", "20-50", "50+"]
                    if_binned = pd.cut(if_vals, bins=if_bins, labels=if_labels).value_counts().sort_index()
                    if_df = pd.DataFrame({
                        "篇数": list(if_binned.values)
                    }, index=pd.Index(list(if_binned.index), name="IF区间"))
                    st.dataframe(if_df, use_container_width=True, height=250)
            with sub_c:
                st.caption("**期刊分布**")
                journal_counts = Counter(p.get("期刊", "?") for p in full_data if p.get("期刊"))
                if journal_counts:
                    top = journal_counts.most_common(15)
                    j_df = pd.DataFrame({
                        "篇数": [c for j, c in top]
                    }, index=pd.Index([j for j, c in top], name="期刊"))
                    st.dataframe(j_df, use_container_width=True, height=400)

        # ── Tab 2: 理论概念图 ──
        with tab2:
            st.caption("从研究问题 & 讨论结论中提取的理论框架")

            # ═══════ 理论百科全书 ═══════
            THEORY_ENCYCLOPEDIA = {
                "TAM": {
                    "name": "Technology Acceptance Model (TAM) · 技术接受模型",
                    "definition": "解释用户如何接受和使用新技术的理论框架。核心观点：感知有用性(PU)和感知易用性(PEOU)是影响技术接受的两个关键信念，它们影响使用态度→行为意向→实际使用。",
                    "origin": "Davis (1989), MIS Quarterly. 基于 TRA (理性行为理论) 发展而来。",
                    "constructs": "感知有用性, 感知易用性, 使用态度, 行为意向, 实际使用",
                    "ai_marketing": "广泛用于解释消费者对AI推荐系统、聊天机器人、智能音箱等AI营销工具的接受行为。常扩展信任、隐私、拟人化等变量。",
                },
                "UTAUT": {
                    "name": "Unified Theory of Acceptance and Use of Technology (UTAUT) · 技术接受与使用统一理论",
                    "definition": "整合8种技术接受理论的元框架。核心变量：绩效期望(PE)、努力期望(EE)、社会影响(SI)、便利条件(FC)，以及年龄/性别/经验/自愿性四个调节变量。",
                    "origin": "Venkatesh et al. (2003), MIS Quarterly.",
                    "constructs": "绩效期望, 努力期望, 社会影响, 便利条件, 行为意向, 使用行为",
                    "ai_marketing": "AI营销中常用于解释用户对AI工具的采纳意愿，尤其是GPT/LLM工具的接受研究中。",
                },
                "S-O-R": {
                    "name": "Stimulus-Organism-Response (S-O-R) · 刺激-机体-反应模型",
                    "definition": "环境刺激(S)通过个体内部状态(O)的中介作用引发行为反应(R)。修正自行为主义S-R模型，强调认知/情感的中介过程。",
                    "origin": "Mehrabian & Russell (1974), An Approach to Environmental Psychology.",
                    "constructs": "刺激(Stimulus), 机体状态(Organism: 认知/情感), 反应(Response: 趋近/回避)",
                    "ai_marketing": "广泛应用于AI交互场景：AI特征(拟人化、个性化)为S → 消费者信任/临场感为O → 购买/采纳行为为R。",
                },
                "ELM": {
                    "name": "Elaboration Likelihood Model (ELM) · 精细加工可能性模型",
                    "definition": "说服的二元路径模型：中心路径(仔细思考论据质量)和边缘路径(依赖表面线索如来源吸引力)。动机和能力的水平决定走哪条路径。",
                    "origin": "Petty & Cacioppo (1986), Communication and Persuasion.",
                    "constructs": "中心路径, 边缘路径, 论据质量, 来源可信度, 卷入度, 认知需求",
                    "ai_marketing": "解释消费者如何加工AI生成内容：AI来源可能触发不同路径。低卷入时AI标签作为边缘线索，高卷入时内容质量走中心路径。",
                },
                "Trust Transfer": {
                    "name": "Trust Transfer Theory · 信任转移理论",
                    "definition": "个体对某一实体的信任可以转移到另一相关联实体。信任转移通过认知关联或社会关系链发生。",
                    "origin": "Stewart (2003), Journal of Management Information Systems.",
                    "constructs": "来源信任, 目标信任, 关联强度, 转移路径",
                    "ai_marketing": "消费者对品牌/平台的信任转移到AI代理(如推荐系统、AI客服)。对平台的高信任可以溢出到其AI功能。",
                },
                "Signaling": {
                    "name": "Signaling Theory · 信号理论",
                    "definition": "在信息不对称情境下，信息优势方(发送者)通过可观察的信号向信息劣势方(接收者)传递不可观察的质量信息。有效信号需满足：可观察性+成本(高成本信号不会被低质量者模仿)。",
                    "origin": "Spence (1973), Quarterly Journal of Economics. 从劳动市场信号模型发展而来。",
                    "constructs": "信号发送者, 信号接收者, 信号本身, 信号成本, 信号可观察性, 信息不对称",
                    "ai_marketing": "AI标签作为质量信号：展示'AI驱动'可能作为技术先进性信号。品牌投资AI可视为对消费者的质量承诺信号。",
                },
                "Attribution": {
                    "name": "Attribution Theory · 归因理论",
                    "definition": "个体如何解释事件原因。内部归因(归因于自身)vs外部归因(归因于环境/他人)。归因维度：因果源、稳定性、可控性。",
                    "origin": "Heider (1958); Weiner (1986), Psychological Review.",
                    "constructs": "归因源(内部/外部), 稳定性, 可控性, 责任判断",
                    "ai_marketing": "消费者如何归因AI行为：AI犯错归咎于谁(品牌/AI/自己)？AI推荐成功归因于算法能力还是运气？影响后续信任和使用。",
                },
                "Social Presence": {
                    "name": "Social Presence Theory · 社会临场感理论",
                    "definition": "在媒介化交互中感知到他人(或社会实体)存在的程度。高社会临场感使交互更'温暖'、更社会性。",
                    "origin": "Short, Williams & Christie (1976), The Social Psychology of Telecommunications.",
                    "constructs": "社会临场感, 媒介丰富度, 亲密感, 即时感, 心理距离",
                    "ai_marketing": "核心概念：AI聊天机器人/虚拟助手的'人性化'程度影响消费者信任和参与。拟人化设计提升社会临场感。",
                },
                "Anthropomorphism": {
                    "name": "Anthropomorphism Theory · 拟人化理论",
                    "definition": "人类倾向于将非人类实体赋予人类特征(外貌、情感、意图)。拟人化满足社会连接需求和控制感需求。",
                    "origin": "Epley, Waytz & Cacioppo (2007), Psychological Review.",
                    "constructs": "人类外貌, 人类情感, 人类意图, 拟人化程度, 感知相似性",
                    "ai_marketing": "AI营销中的核心变量：拟人化AI代理(虚拟网红、数字人)vs 非拟人化AI。过度拟人化可能触发恐怖谷效应。",
                },
                "Uncanny Valley": {
                    "name": "Uncanny Valley · 恐怖谷理论",
                    "definition": "当人造实体(机器人/AI/虚拟形象)与人类相似度达到较高但非完美的程度时，会引发人类的厌恶和不适感。",
                    "origin": "Mori (1970), Energy.",
                    "constructs": "类人度, 亲和感, 恐怖谷低谷, 诡异感(Eeriness)",
                    "ai_marketing": "AI虚拟形象设计的关键约束：太像人反而降低消费者好感。虚拟网红、数字人营销需注意避开恐怖谷区域。",
                },
                "Mind Perception": {
                    "name": "Mind Perception Theory · 心智感知理论",
                    "definition": "个体感知他人(或非人类实体)拥有心理能力(思维、情感、意图)的程度。两大维度：agency(能动性/思考能力)和experience(体验性/感受能力)。",
                    "origin": "Gray, Gray & Wegner (2007), Science.",
                    "constructs": "能动性(Agency), 体验性(Experience), 道德判断, 责任归属",
                    "ai_marketing": "消费者感知AI'有心智'的程度影响信任和道德判断。感知AI有情感能力 → 更强的关系建立动机。",
                },
                "Privacy Calculus": {
                    "name": "Privacy Calculus Theory · 隐私计算理论",
                    "definition": "个体在披露个人信息时进行风险-收益权衡。当感知收益>感知风险时倾向于信息披露。",
                    "origin": "Culnan & Armstrong (1999), Organization Science. 基于社会交换理论。",
                    "constructs": "感知隐私风险, 感知收益, 信息披露意愿, 隐私关注, 信任",
                    "ai_marketing": "AI个性化依赖用户数据 → 消费者权衡个性化收益 vs 隐私风险。AI透明度和用户控制权降低感知风险。",
                },
                "CASA": {
                    "name": "Computers as Social Actors (CASA) · 计算机作为社会行动者",
                    "definition": "人们无意识地将社会规则和期望应用于计算机(和AI)。即使知道对方不是人类，仍会礼貌回应、形成团队认同、被'人格'影响。",
                    "origin": "Reeves & Nass (1996), The Media Equation.",
                    "constructs": "社会脚本, 礼貌, 互惠, 刻板印象应用, 无意识社会反应",
                    "ai_marketing": "消费者与AI交互时自动应用社交规范(礼貌、互惠)。AI的'人格'设计(友好/专业/幽默)影响消费者行为。",
                },
                "U&G": {
                    "name": "Uses and Gratifications Theory (U&G) · 使用与满足理论",
                    "definition": "受众主动选择媒介来满足特定需求。核心问题不是'媒介对人们做了什么'而是'人们用媒介做了什么'。",
                    "origin": "Katz, Blumler & Gurevitch (1973).",
                    "constructs": "认知需求, 情感需求, 社交需求, 身份需求, 娱乐需求, 满足感",
                    "ai_marketing": "消费者使用AI工具(聊天机器人、AI搜索)的动机分析：效率(认知)、陪伴(情感)、社交展示(身份)。",
                },
                "Self-Determination": {
                    "name": "Self-Determination Theory (SDT) · 自我决定理论",
                    "definition": "人类动机由三种基本心理需求驱动：自主性(autonomy)、胜任感(competence)、关系感(relatedness)。需求满足产生内在动机。",
                    "origin": "Deci & Ryan (1985), Intrinsic Motivation and Self-Determination.",
                    "constructs": "自主性, 胜任感, 关系感, 内在动机, 外在动机, 动机内化",
                    "ai_marketing": "AI工具使用中：AI辅助增强胜任感、AI自由度影响自主性。AI推荐可能支持或削弱消费者的自主决策感。",
                },
                "Construal Level": {
                    "name": "Construal Level Theory (CLT) · 解释水平理论",
                    "definition": "心理距离(时间/空间/社会/概率)影响思维的抽象程度。远距离→高解释水平(抽象/核心/目标)。近距离→低解释水平(具体/细节/手段)。",
                    "origin": "Trope & Liberman (2010), Psychological Review.",
                    "constructs": "心理距离, 解释水平(高/低), 抽象vs具体, 目标vs手段, 可行性vs合意性",
                    "ai_marketing": "AI推荐的时间框架：'立即购买'vs'未来规划' → 不同解释水平影响决策。AI生成内容的抽象程度影响说服力。",
                },
                "Cognitive Load": {
                    "name": "Cognitive Load Theory · 认知负荷理论",
                    "definition": "人类工作记忆容量有限。学习/决策时的认知负荷分三种：内在(任务本身)、外在(信息呈现方式)、相关(图式建构)。",
                    "origin": "Sweller (1988), Cognitive Science.",
                    "constructs": "内在认知负荷, 外在认知负荷, 相关认知负荷, 工作记忆容量",
                    "ai_marketing": "AI推荐系统降低消费者信息处理负荷。但过多AI选项可能增加认知负荷。AI摘要vs全文 → 降低外在负荷。",
                },
                "Cognitive Dissonance": {
                    "name": "Cognitive Dissonance Theory · 认知失调理论",
                    "definition": "当个体持有不一致的认知(信念/态度/行为)时产生心理不适，驱使其减少失调(改变态度、改变行为、增加新认知)。",
                    "origin": "Festinger (1957), A Theory of Cognitive Dissonance.",
                    "constructs": "认知不一致, 失调程度, 失调减少策略, 自由选择, 努力正当化",
                    "ai_marketing": "消费者使用AI后体验不一致(期望vs实际表现) → 失调 → 调整态度或更换服务。AI说服过程中可能引发失调。",
                },
                "ECT": {
                    "name": "Expectation-Confirmation Theory (ECT) · 期望确认理论",
                    "definition": "满意度 = f(期望, 感知绩效, 确认/不确认)。满意度决定持续使用意愿。广泛应用于IS持续使用研究。",
                    "origin": "Oliver (1980); Bhattacherjee (2001), MIS Quarterly (IS Continuance Model).",
                    "constructs": "期望, 感知绩效, 确认(Confirmation), 满意度, 持续使用意愿",
                    "ai_marketing": "AI产品的持续使用：首次使用后是否'确认'期望 → 满意度 → 继续使用或流失。ChatGPT/Claude等LLM工具的持续使用研究。",
                },
                "Source Credibility": {
                    "name": "Source Credibility Theory · 来源可信度理论",
                    "definition": "信息说服力受来源可信度影响。可信度由专业性(expertise)和可信赖性(trustworthiness)组成。",
                    "origin": "Hovland, Janis & Kelley (1953), Communication and Persuasion.",
                    "constructs": "专业性, 可信赖性, 吸引力, 来源相似性, 信息采纳",
                    "ai_marketing": "AI作为信息来源的可信度：消费者认为AI专业(数据处理能力)但可能缺乏可信赖性(无情感/道德判断)。AI vs 人类专家的来源效应。",
                },
                "Persuasion Knowledge": {
                    "name": "Persuasion Knowledge Model (PKM) · 说服知识模型",
                    "definition": "消费者拥有关于说服尝试的知识和信念。当说服知识被激活，消费者会使用应对策略(怀疑、反驳、回避)。",
                    "origin": "Friestad & Wright (1994), Journal of Consumer Research.",
                    "constructs": "说服知识, 说服代理, 说服目标, 应对策略, 说服意图感知",
                    "ai_marketing": "消费者知道AI在'推销' → 激活说服知识 → 抵制AI推荐。AI说服的隐蔽性vs透明度。AI比人类销售人员更少激活说服知识。",
                },
                "Innovation Diffusion": {
                    "name": "Diffusion of Innovations (DOI) · 创新扩散理论",
                    "definition": "创新通过社会系统成员在时间中通过特定渠道传播。五类采纳者：创新者→早期采纳者→早期大众→晚期大众→落后者。",
                    "origin": "Rogers (1962/2003), Diffusion of Innovations.",
                    "constructs": "相对优势, 兼容性, 复杂性, 可试用性, 可观察性, 采纳者类别",
                    "ai_marketing": "AI营销工具(如AIGC、推荐引擎)的扩散路径。不同细分市场对AI创新的采纳速度和障碍不同。",
                },
                "Institutional": {
                    "name": "Institutional Theory · 制度理论",
                    "definition": "组织行为受制度环境(规则、规范、文化-认知)塑造，不完全是理性效率选择。三种同构压力：强制性、模仿性、规范性。",
                    "origin": "DiMaggio & Powell (1983), American Sociological Review.",
                    "constructs": "制度压力, 同构(isomorphism), 合法性, 理所当然性",
                    "ai_marketing": "企业采纳AI营销的制度压力：竞争对手都在用(模仿)、行业协会推动(规范)、政府数字化政策(强制)。",
                },
                "Agency": {
                    "name": "Agency Theory · 代理理论",
                    "definition": "委托-代理关系中因信息不对称和目标不一致产生代理问题。解决机制：监控、激励契约、信号。",
                    "origin": "Jensen & Meckling (1976), Journal of Financial Economics.",
                    "constructs": "委托人, 代理人, 信息不对称, 道德风险, 逆向选择, 激励对齐",
                    "ai_marketing": "消费者(委托人)委托AI代理决策 → 目标可能不一致：AI优化点击率 vs 消费者需要最佳匹配。算法透明度作为监控机制。",
                },
                "Stakeholder": {
                    "name": "Stakeholder Theory · 利益相关者理论",
                    "definition": "企业应对所有利益相关者(不限于股东)负责：消费者、员工、供应商、社区、环境。长期价值创造需要平衡多方利益。",
                    "origin": "Freeman (1984), Strategic Management: A Stakeholder Approach.",
                    "constructs": "利益相关者识别, 利益相关者重要性, 价值分配, 伦理责任",
                    "ai_marketing": "AI营销的伦理边界：AI个性化对消费者有利，但数据收集可能侵犯隐私。AI内容生成影响内容创作者(替代vs增强)。",
                },
                "RBV": {
                    "name": "Resource-Based View (RBV) · 资源基础观",
                    "definition": "企业的可持续竞争优势源于其拥有的独特资源和能力。VRIN标准：有价值、稀缺、不可模仿、不可替代。",
                    "origin": "Barney (1991), Journal of Management.",
                    "constructs": "VRIN资源, 动态能力, 竞争优势, 资源异质性, 路径依赖",
                    "ai_marketing": "AI能力作为企业战略资源：AI数据资产、算法能力、AI人才是否符合VRIN标准？AI营销能力的竞争优势持续性。",
                },
                "SDL": {
                    "name": "Service-Dominant Logic (SDL) · 服务主导逻辑",
                    "definition": "所有经济交换本质上是服务交换。价值不是'嵌入'产品中，而是在使用中由消费者和提供者共创。",
                    "origin": "Vargo & Lusch (2004), Journal of Marketing.",
                    "constructs": "服务交换, 价值共创, 操作性资源, 消费者角色, 生态系统",
                    "ai_marketing": "AI赋能价值共创：AI作为操作性资源(知识/技能)协助消费者创造个性化价值。消费者通过AI交互积极参与价值共创。",
                },
                "Means-End Chain": {
                    "name": "Means-End Chain Theory · 手段-目的链理论",
                    "definition": "消费者将产品属性(means)与个人价值(ends)联结的认知结构。属性→功能性结果→心理社会结果→终极价值。",
                    "origin": "Gutman (1982), Journal of Marketing.",
                    "constructs": "属性, 功能性结果, 心理社会结果, 终极价值, 认知层级",
                    "ai_marketing": "AI功能属性(个性化程度)→结果(找到更好产品)→价值(自我表达、幸福感)。用于理解AI服务如何创造消费者价值。",
                },
                "Prospect": {
                    "name": "Prospect Theory · 前景理论",
                    "definition": "人们在不确定下做决策时，对损失比对收益更敏感(损失厌恶)。决策取决于相对于参照点的变化(而非绝对结果)。",
                    "origin": "Kahneman & Tversky (1979), Econometrica.",
                    "constructs": "损失厌恶, 参照依赖, 确定性效应, 框架效应, S型价值函数",
                    "ai_marketing": "AI推荐中的框架效应：'不买就错过'vs'买了享受'。AI定价中的参照点设定。AI个性化折扣中的损失框架。",
                },
                "Regulatory Focus": {
                    "name": "Regulatory Focus Theory · 调节聚焦理论",
                    "definition": "个体追求目标时有两大动机系统：促进聚焦(追求理想、收益、成长)和预防聚焦(履行责任、避免损失、安全)。",
                    "origin": "Higgins (1997), American Psychologist.",
                    "constructs": "促进聚焦, 预防聚焦, 调节匹配, 收益vs损失框架",
                    "ai_marketing": "AI推荐需匹配消费者调节聚焦：促进聚焦→突出产品增益和创新；预防聚焦→突出产品安全和可靠性。AI个性化调节匹配。",
                },
                "Appraisal": {
                    "name": "Appraisal Theory of Emotion · 情绪评价理论",
                    "definition": "情绪不是由事件本身直接引发，而是由个体对事件的认知评价(意义、原因、后果)产生。不同评价维度产生不同情绪。",
                    "origin": "Lazarus (1991); Smith & Ellsworth (1985).",
                    "constructs": "认知评价维度, 愉悦度, 确定性, 可控性, 责任, 预期努力",
                    "ai_marketing": "消费者对AI交互的情绪反应取决于如何'评价'AI行为：AI错误可控→愤怒；AI成功但不可控→惊喜。AI设计管理消费者评价。",
                },
                "Social Exchange": {
                    "name": "Social Exchange Theory · 社会交换理论",
                    "definition": "社会关系中的行为基于成本-收益交换。关系持续的条件：收益>成本，且替代方案不超过当前收益。",
                    "origin": "Homans (1958); Blau (1964); Thibaut & Kelley (1959).",
                    "constructs": "成本, 收益, 比较水平, 替代方案比较, 互惠规范, 信任",
                    "ai_marketing": "消费者-AI持续互动视为社会交换：AI提供个性化、便利收益 → 消费者投入数据、注意力成本。互惠驱动关系持续。",
                },
                "Commitment-Trust": {
                    "name": "Commitment-Trust Theory · 承诺-信任理论",
                    "definition": "关系营销的核心中介变量是关系承诺和信任。共享价值观、沟通、机会主义行为是前因，默许、合作、离开倾向是后果。",
                    "origin": "Morgan & Hunt (1994), Journal of Marketing.",
                    "constructs": "信任, 关系承诺, 共享价值观, 沟通, 机会主义, 合作, 默许",
                    "ai_marketing": "消费者-AI品牌关系：AI的持续可靠表现建立信任→承诺→长期忠诚。AI'背叛'(错误推荐)可能损害信任。",
                },
                "Dual-Process": {
                    "name": "Dual-Process Theories · 双加工理论",
                    "definition": "人类信息处理存在两种模式：系统1(快速/自动/启发式/情感)和系统2(慢速/受控/分析/理性)。决策是两系统交互的结果。",
                    "origin": "Evans & Stanovich (2013), Perspectives on Psychological Science.",
                    "constructs": "系统1(直觉), 系统2(分析), 认知资源, 启发式, 默认干预",
                    "ai_marketing": "AI消费决策中的双加工：低卷入场景→AI推荐触发系统1(自动接受)；高卷入场景→系统2审视AI逻辑。AI决策辅助设计考虑双系统。",
                },
                "Social Identity": {
                    "name": "Social Identity Theory · 社会认同理论",
                    "definition": "个体自我概念部分来源于所属社会群体。通过社会分类→社会认同→社会比较→积极独特性。内群偏爱和外群歧视。",
                    "origin": "Tajfel & Turner (1979).",
                    "constructs": "社会分类, 社会认同, 内群/外群, 内群偏爱, 自我概念",
                    "ai_marketing": "AI品牌社区中的社会认同：'AI原住民'作为身份标签。AI个性化帮助消费者表达特定社会身份。",
                },
                # ── 第二批：补充所有检测到的理论 ──
                "TRA": {
                    "name": "Theory of Reasoned Action (TRA) · 理性行为理论",
                    "definition": "行为意向是实际行为的最直接预测变量，而行为意向由态度和主观规范共同决定。态度反映对行为的评价，主观规范反映感知到的社会压力。",
                    "origin": "Fishbein & Ajzen (1975), Belief, Attitude, Intention and Behavior.",
                    "constructs": "行为态度, 主观规范, 行为意向, 实际行为",
                    "ai_marketing": "TAM的基础理论。在AI营销中用于解释消费者对AI服务的采纳意向如何受个人态度和社会影响。",
                },
                "TPB": {
                    "name": "Theory of Planned Behavior (TPB) · 计划行为理论",
                    "definition": "TRA的扩展，增加了感知行为控制(PBC)变量。当人们认为自己拥有更多资源和机会、预期障碍更少时，PBC更强，行为意向更高。",
                    "origin": "Ajzen (1991), Organizational Behavior and Human Decision Processes.",
                    "constructs": "态度, 主观规范, 感知行为控制, 行为意向, 实际行为",
                    "ai_marketing": "解释消费者使用AI工具的意愿：即使态度积极，若觉得AI太难用(PBC低)，也不会尝试。",
                },
                "TTF": {
                    "name": "Task-Technology Fit (TTF) · 任务技术匹配理论",
                    "definition": "技术只有在其功能与用户任务需求相匹配时才会被使用并产生绩效。匹配度取决于任务特征和技术特征的对应关系。",
                    "origin": "Goodhue & Thompson (1995), MIS Quarterly.",
                    "constructs": "任务特征, 技术特征, 任务技术匹配, 使用行为, 绩效影响",
                    "ai_marketing": "AI工具的设计是否匹配营销任务需求：如AI写文案 vs 传统方式，匹配度高则采用率高。",
                },
                "IS Success": {
                    "name": "IS Success Model (D&M Model) · 信息系统成功模型",
                    "definition": "信息系统的成功由六个维度构成：系统质量、信息质量、服务质量、使用/使用意向、用户满意度、净收益。维度间存在相互影响。",
                    "origin": "DeLone & McLean (2003), Journal of Management Information Systems.",
                    "constructs": "系统质量, 信息质量, 服务质量, 使用意向, 用户满意度, 净收益",
                    "ai_marketing": "评估AI营销系统(推荐引擎、聊天机器人)成功的框架：系统质量→AI响应速度/稳定性；信息质量→推荐准确性。",
                },
                "Flow": {
                    "name": "Flow Theory · 心流理论",
                    "definition": "个体完全沉浸于某项活动时的最优体验状态：注意力高度集中、自我意识消失、时间感扭曲、活动本身具有奖励性。技能与挑战的平衡是进入心流的关键条件。",
                    "origin": "Csikszentmihalyi (1990), Flow: The Psychology of Optimal Experience.",
                    "constructs": "技能-挑战平衡, 注意力集中, 控制感, 时间扭曲, 内在愉悦, 临场感",
                    "ai_marketing": "消费者与AI聊天机器人的沉浸式交互 → 心流体验 → 更高的满意度、购买意愿和品牌忠诚。AI个性化增强心流。",
                },
                "Goal-Setting": {
                    "name": "Goal-Setting Theory · 目标设定理论",
                    "definition": "具体且有挑战性的目标比模糊或容易的目标更能激发绩效。目标通过引导注意力、调动努力、增强坚持性和促进策略发展来影响行为。",
                    "origin": "Locke & Latham (1990), A Theory of Goal Setting and Task Performance.",
                    "constructs": "目标具体性, 目标难度, 目标承诺, 反馈, 自我效能, 任务策略",
                    "ai_marketing": "AI目标设定工具如何影响消费者行为：AI帮助设定具体理财/健身目标 → 更高达成率。目标框架与AI推荐匹配。",
                },
                "PMT": {
                    "name": "Protection Motivation Theory (PMT) · 保护动机理论",
                    "definition": "恐惧诉求通过两大评估过程引发保护动机：威胁评估(严重性+易感性)和应对评估(反应效能+自我效能)。当威胁高且应对可行时，保护动机最强。",
                    "origin": "Rogers (1975); Maddux & Rogers (1983).",
                    "constructs": "感知严重性, 感知易感性, 反应效能, 自我效能, 恐惧, 保护动机",
                    "ai_marketing": "AI安全/隐私提示中的恐惧诉求：展示AI数据泄露风险(威胁)→推荐防护措施(应对)→用户采纳AI安全功能。",
                },
                "PPM": {
                    "name": "Push-Pull-Mooring (PPM) · 推-拉-锚定模型",
                    "definition": "从人口迁移理论引入消费者行为：推动因素(对现状不满)→推出原行为；拉动因素(替代方案吸引)→拉向新行为；锚定因素(个人/情境约束)→阻碍或促进转换。",
                    "origin": "Bogue (1969); Moon (1995); Bansal et al. (2005).",
                    "constructs": "推动因素, 拉动因素, 锚定因素, 转换意愿, 转换成本, 习惯",
                    "ai_marketing": "消费者从传统服务切换到AI服务的决策：不满人工服务(推)+AI便利性(拉)+技术焦虑(锚定)。",
                },
                "Inoculation": {
                    "name": "Inoculation Theory · 接种理论",
                    "definition": "预先暴露于弱化的反面论点可以增强对后续强说服攻击的抵抗力，类似于医学疫苗。过程包括：威胁(意识到态度脆弱)→反驳(主动构建对抗论点)。",
                    "origin": "McGuire (1964); Compton (2013).",
                    "constructs": "威胁感知, 反驳, 接种处理, 态度抵抗力, 前测-后测",
                    "ai_marketing": "消费者抵御AI错误推荐的能力：了解AI推荐机制(接种)→更批判性评估AI建议，减少盲从。",
                },
                "Narrative Transportation": {
                    "name": "Narrative Transportation · 叙事传输理论",
                    "definition": "当读者/观众沉浸在故事中时会被「传输」到叙事世界，这暂时剥离现实世界的信念和态度，使故事中的隐含价值观更容易被接受。",
                    "origin": "Green & Brock (2000), Journal of Personality and Social Psychology.",
                    "constructs": "叙事传输, 情感参与, 认知参与, 心像, 态度改变, 信念采纳",
                    "ai_marketing": "AI生成品牌故事/广告叙事：AI能否创作'传输'消费者到品牌世界的故事？AI叙事 vs 人类叙事的传输效果比较。",
                },
                "Agenda-Setting": {
                    "name": "Agenda-Setting Theory · 议程设置理论",
                    "definition": "媒体不仅告诉人们'怎么想'，更通过报道频率和显著性告诉人们'想什么'。第一层：议题重要性转移；第二层：属性显著性转移。",
                    "origin": "McCombs & Shaw (1972), Public Opinion Quarterly.",
                    "constructs": "议题显著性, 属性显著性, 媒体报道量, 公众议程, 政策议程",
                    "ai_marketing": "AI推荐算法如何设置消费者'议程'：推荐系统优先展示哪些产品/品牌 → 塑造消费者关注和偏好结构。",
                },
                "Framing": {
                    "name": "Framing Theory · 框架理论",
                    "definition": "同一信息的不同呈现方式(框架)会显著影响人们的判断和决策。增益框架(强调收益)和损失框架(强调损失)即使客观上等价也会产生不同选择。",
                    "origin": "Goffman (1974); Tversky & Kahneman (1981), Science.",
                    "constructs": "增益框架, 损失框架, 等效性框架, 强调性框架, 框架效应",
                    "ai_marketing": "AI生成内容的框架策略：AI推荐用'省50元'还是'不亏50元'？AI可自动检测消费者偏好框架并动态调整个性化信息框架。",
                },
                "Two-Step Flow": {
                    "name": "Two-Step Flow of Communication · 两级传播理论",
                    "definition": "大众媒体信息首先到达意见领袖(第一步)，然后由意见领袖通过人际渠道传递给追随者(第二步)。意见领袖在信息过滤和解读中起关键作用。",
                    "origin": "Lazarsfeld, Berelson & Gaudet (1944), The People's Choice.",
                    "constructs": "意见领袖, 追随者, 媒体曝光, 人际影响, 信息过滤",
                    "ai_marketing": "AI网红/KOL营销：AI虚拟意见领袖 vs 人类KOL的信息传播路径。AI算法识别和激活意见领袖。",
                },
                "Cultivation": {
                    "name": "Cultivation Theory · 涵化理论",
                    "definition": "长期接触媒体内容会逐渐'涵化'受众对现实的认知，使其更接近媒体呈现的世界而非真实世界。效果在重度观看者中更显著。",
                    "origin": "Gerbner & Gross (1976), Journal of Communication.",
                    "constructs": "媒体曝光量, 第一阶信念(事实性), 第二阶信念(态度/价值观), 主流化, 共鸣",
                    "ai_marketing": "长期接触AI生成内容是否'涵化'消费者对品牌/产品的认知？算法过滤气泡可能系统性偏斜消费者世界观。",
                },
                "Dynamic Capabilities": {
                    "name": "Dynamic Capabilities · 动态能力理论",
                    "definition": "企业整合、构建和重新配置内外资源以应对快速变化环境的能力。区别于普通能力(运营能力)，动态能力是关于'改变能力的能力'。",
                    "origin": "Teece, Pisano & Shuen (1997), Strategic Management Journal.",
                    "constructs": "感知(Sensing), 抓住(Seizing), 转型(Transforming), 资源重组, 路径依赖",
                    "ai_marketing": "AI营销能力作为动态能力：感知消费者变化(大数据)→抓住机会(实时个性化)→转型组织(AI驱动决策)。竞争优势的来源。",
                },
                "Contingency": {
                    "name": "Contingency Theory · 权变理论",
                    "definition": "不存在普适的最佳管理/组织方式，最优选择取决于(取决于/权变于)情境因素如环境不确定性、技术特征、组织规模。",
                    "origin": "Lawrence & Lorsch (1967); Fiedler (1964).",
                    "constructs": "环境不确定性, 技术特征, 组织规模, 战略匹配, 权变因素",
                    "ai_marketing": "AI营销策略的效果取决于情境：产品类型(搜索品vs体验品)、消费者特征(技术素养)、文化背景(个人主义vs集体主义)。",
                },
                "Transaction Cost": {
                    "name": "Transaction Cost Economics (TCE) · 交易成本经济学",
                    "definition": "经济交换存在交易成本(搜索、谈判、监督、执行)。组织或市场的选择取决于哪种治理结构最小化交易成本。核心维度：资产专用性、不确定性、交易频率。",
                    "origin": "Williamson (1975), Markets and Hierarchies.",
                    "constructs": "交易成本, 资产专用性, 不确定性, 交易频率, 有限理性, 机会主义",
                    "ai_marketing": "AI如何降低消费者交易成本：AI搜索降低信息搜索成本、AI推荐降低评估成本、智能合约降低执行成本。",
                },
                "Absorptive Capacity": {
                    "name": "Absorptive Capacity · 吸收能力理论",
                    "definition": "企业识别、消化和应用外部新知识的能力。吸收能力是累积性的——先前的相关知识越多，吸收新知识的能力越强。分为潜在吸收能力(获取+消化)和实现吸收能力(转化+应用)。",
                    "origin": "Cohen & Levinthal (1990), Administrative Science Quarterly.",
                    "constructs": "知识获取, 知识消化, 知识转化, 知识应用, 先前知识基础",
                    "ai_marketing": "企业吸收AI技术知识的能力决定AI营销应用深度。高吸收能力企业更快将AI研究转化为营销实践。",
                },
                "Organizational Learning": {
                    "name": "Organizational Learning Theory · 组织学习理论",
                    "definition": "组织通过编码经验→形成常规→检测和纠正错误来学习。单环学习(在现有框架内修正)vs双环学习(质疑和改变框架本身)。",
                    "origin": "Argyris & Schön (1978), Organizational Learning.",
                    "constructs": "单环学习, 双环学习, 心智模型, 组织记忆, 知识共享, 学习型组织",
                    "ai_marketing": "营销组织如何从AI系统学习：AI分析的消费者洞察→组织学习→营销策略调整。双环学习：AI不仅优化现有策略，还能揭示策略假设本身的问题。",
                },
                "Institutional Trust": {
                    "name": "Institutional Trust · 制度信任",
                    "definition": "个体对制度、组织或系统整体(而非特定个人)的信任，基于制度保障(法律、规则、流程)而非人际互动。在线上环境中尤为重要。",
                    "origin": "Zucker (1986); McKnight et al. (2002), Information Systems Research.",
                    "constructs": "制度保障, 结构保证, 情境正常, 信任倾向, 初始信任",
                    "ai_marketing": "消费者对AI系统的制度信任：AI治理框架、数据保护法规、平台声誉作为制度信任基础。弥补AI缺乏人际信任(面孔/情感)的不足。",
                },
                "Perceived Risk": {
                    "name": "Perceived Risk Theory · 感知风险理论",
                    "definition": "消费者决策中感知到的不确定性和负面结果的可能。六类风险：财务、性能、身体、心理、社会、时间。高风险感知抑制购买行为。",
                    "origin": "Bauer (1960); Cunningham (1967); Jacoby & Kaplan (1972).",
                    "constructs": "财务风险, 性能风险, 社会风险, 心理风险, 时间风险, 总体感知风险",
                    "ai_marketing": "AI推荐降低还是增加感知风险？一方面AI精准匹配降低性能风险，另一方面AI'黑箱'增加不确定性。可信AI降低感知风险。",
                },
                "Perceived Value": {
                    "name": "Perceived Value Theory · 感知价值理论",
                    "definition": "消费者对产品/服务的总体效用评价基于'得到什么'(收益)和'付出什么'(成本)的比较。多维概念：功能价值、情感价值、社会价值、认知价值、条件价值。",
                    "origin": "Zeithaml (1988); Sheth, Newman & Gross (1991), Journal of Business Research.",
                    "constructs": "功能价值, 情感价值, 社会价值, 认知价值, 条件价值, 感知成本",
                    "ai_marketing": "AI个性化如何增加消费者感知价值：精准推荐(功能价值)、个性化体验(情感价值)、'早期使用者'标签(社会价值)。",
                },
                "Consumption Value": {
                    "name": "Theory of Consumption Values · 消费价值理论",
                    "definition": "消费者选择受五种消费价值驱动：功能价值、社会价值、情感价值、认知价值(满足好奇心/新奇感)和条件价值(特定情境下的价值)。选择是多重价值的函数。",
                    "origin": "Sheth, Newman & Gross (1991), Journal of Business Research.",
                    "constructs": "功能价值, 社会价值, 情感价值, 认知价值, 条件价值",
                    "ai_marketing": "AI产品/服务为消费者创造的五种价值：新奇的AI体验(认知价值)；AI个性化(功能价值)；使用AI工具的社会形象(社会价值)。",
                },
                "Self-Congruity": {
                    "name": "Self-Congruity Theory · 自我一致性理论",
                    "definition": "消费者偏好和自我概念(实际自我或理想自我)一致的品牌和产品。自我-品牌一致性越高，品牌态度和购买意愿越强。",
                    "origin": "Sirgy (1982), Journal of Business Research.",
                    "constructs": "实际自我, 理想自我, 品牌形象, 自我-品牌一致性, 品牌偏好",
                    "ai_marketing": "AI基于消费者画像推荐与自我概念匹配的产品。但AI对'自我'的推断是否准确？错误推断导致自我不一致→反感。",
                },
                "Brand Attachment": {
                    "name": "Brand Attachment Theory · 品牌依恋理论",
                    "definition": "消费者与品牌之间的情感联结，类似于人际依恋。强品牌依恋的特征：品牌-自我联结、自动唤起、品牌激情。",
                    "origin": "Park, MacInnis & Priester (2006); Thomson, MacInnis & Park (2005).",
                    "constructs": "品牌-自我联结, 品牌激情, 依恋强度, 分离痛苦, 自动唤起",
                    "ai_marketing": "AI交互(如AI客服、AI陪伴)是否促进消费者-品牌依恋形成？AI'人格'作为品牌人格的延伸→情感联结。",
                },
                "Brand Relationship": {
                    "name": "Brand Relationship Theory · 品牌关系理论",
                    "definition": "消费者与品牌之间存在类人际关系的多维联结。品牌关系质量(BRQ)包括：爱/激情、自我联结、承诺、亲密、品牌伙伴质量。",
                    "origin": "Fournier (1998), Journal of Consumer Research.",
                    "constructs": "品牌关系质量, 爱/激情, 自我联结, 相互依赖, 承诺, 亲密",
                    "ai_marketing": "AI作为品牌关系的服务界面：消费者通过AI交互建立品牌关系的路径有何不同？AI人格作为'品牌代言人'影响关系形成。",
                },
                "Customer Engagement": {
                    "name": "Customer Engagement · 顾客参与理论",
                    "definition": "顾客在与品牌/企业的互动中产生的超越购买的认知、情感和行为投入。维度包括：认知参与(注意力)、情感参与(热情/兴趣)、行为参与(主动互动/共创)。",
                    "origin": "Brodie et al. (2011), Journal of Service Research.",
                    "constructs": "认知参与, 情感参与, 行为参与, 互动性, 价值共创",
                    "ai_marketing": "AI互动工具(如AI聊天、个性化内容)作为提高顾客参与的手段。AI交互的便利性和个性化增强行为参与，但需要平衡'人性温度'。",
                },
                "Relationship Marketing": {
                    "name": "Relationship Marketing Theory · 关系营销理论",
                    "definition": "营销的核心从离散交易转向建立、维护和发展长期客户关系。关系质量(信任+满意+承诺)是关系持续的关键中介。",
                    "origin": "Berry (1983); Morgan & Hunt (1994), Journal of Marketing.",
                    "constructs": "信任, 承诺, 满意度, 关系质量, 关系收益, 关系终止成本",
                    "ai_marketing": "AI在营销关系管理中的角色：CRM的AI增强→预测流失→主动干预。但AI管理的关系是否缺少'人性温度'？",
                },
                "Co-Creation": {
                    "name": "Co-Creation Theory · 价值共创理论",
                    "definition": "消费者不是被动的价值接受者，而是价值的主动共创者。通过与企业的互动，消费者整合自己的资源和企业的资源共同创造独特的体验价值。",
                    "origin": "Prahalad & Ramaswamy (2004), Journal of Interactive Marketing.",
                    "constructs": "对话, 获取, 风险评估, 透明度, 消费者资源, 企业资源",
                    "ai_marketing": "AI赋能价值共创的最前沿：AI生成工具(AIGC)让消费者参与产品设计、广告创意。消费者+AI共创品牌内容。",
                },
                "Service Quality": {
                    "name": "Service Quality (SERVQUAL) · 服务质量模型",
                    "definition": "服务质量是消费者对服务的期望与实际感知之间的差距。五个维度：可靠性、响应性、保证性、移情性、有形性。",
                    "origin": "Parasuraman, Zeithaml & Berry (1988), Journal of Retailing.",
                    "constructs": "可靠性, 响应性, 保证性, 移情性, 有形性, 服务差距",
                    "ai_marketing": "AI服务质量评估：AI客服的可靠性(回答准确率)、响应性(回复速度)、移情性(AI能否理解和回应情感)。",
                },
                "Customer Satisfaction": {
                    "name": "Customer Satisfaction Theory · 顾客满意度理论",
                    "definition": "满意度是消费者对产品/服务体验的整体评价，取决于感知绩效与比较标准(期望/需求/公平)之间的差距。满意度是忠诚、口碑和重复购买的核心预测变量。",
                    "origin": "Oliver (1980/1997), Satisfaction: A Behavioral Perspective.",
                    "constructs": "期望, 感知绩效, 不一致(Disconfirmation), 满意度, 结果, 归因",
                    "ai_marketing": "AI个性化是否提高满意度？匹配准确→正向不一致→高满意度。但AI的'过度精准'可能让消费者感到被操控。",
                },
                "KBV": {
                    "name": "Knowledge-Based View (KBV) · 知识基础观",
                    "definition": "RBV的延伸：知识是企业最重要的战略资源。企业存在的原因是其比市场更有效地整合和创造知识。竞争优势源于知识创造、存储和转移的能力。",
                    "origin": "Grant (1996), Strategic Management Journal.",
                    "constructs": "知识创造, 知识整合, 知识转移, 隐性知识, 显性知识",
                    "ai_marketing": "AI作为知识整合器：AI系统整合分散的消费者知识(数据→洞察→知识)。AI营销的知识管理功能。",
                },
                "Information Processing": {
                    "name": "Information Processing Theory · 信息加工理论",
                    "definition": "人类认知系统通过编码→存储→提取来加工信息。信息加工受注意力和工作记忆容量的限制。消费者决策本质上是信息加工过程。",
                    "origin": "Miller (1956); Newell & Simon (1972).",
                    "constructs": "信息编码, 信息存储, 信息提取, 注意力, 工作记忆, 认知容量",
                    "ai_marketing": "AI如何改变消费者信息加工：AI摘要降低信息加工负荷；AI推荐替代消费者决策中的信息搜索和评估阶段。",
                },
                "HSM": {
                    "name": "Heuristic-Systematic Model (HSM) · 启发式-系统式加工模型",
                    "definition": "信息加工的两种模式：系统式加工(仔细分析内容)和启发式加工(依赖简单规则/线索)。与ELM类似但有区别：两种加工可以同时发生(共现假设)。",
                    "origin": "Chaiken (1980), Journal of Personality and Social Psychology.",
                    "constructs": "系统式加工, 启发式加工, 最小充分原则, 加工动机, 共现",
                    "ai_marketing": "消费者对AI推荐的加工模式：高卷入→系统式(仔细评估AI逻辑)；低卷入→启发式(AI=准确)。AI标签本身作为启发式线索。",
                },
                "Sensemaking": {
                    "name": "Sensemaking Theory · 意义建构理论",
                    "definition": "当面对模糊、混乱或意外情境时，个体/组织通过回顾性解释来理解和建构'发生了什么'。意义建构是一个持续的、社会性的、基于身份的过程。",
                    "origin": "Weick (1995), Sensemaking in Organizations.",
                    "constructs": "身份建构, 回顾性, 制定(Enactment), 社会性, 持续性, 合理性",
                    "ai_marketing": "消费者如何'理解'AI的行为和推荐：当AI做出意外推荐时→消费者进行意义建构→'这个AI了解我吗？'还是'这个AI在操纵我？'",
                },
                "Moral Foundations": {
                    "name": "Moral Foundations Theory · 道德基础理论",
                    "definition": "人类道德判断基于五个(后扩展为六)先天道德基础：关怀/伤害、公平/欺骗、忠诚/背叛、权威/颠覆、神圣/堕落、自由/压迫。不同文化/意识形态对这些基础的权重不同。",
                    "origin": "Haidt & Joseph (2004); Graham et al. (2013), Advances in Experimental Social Psychology.",
                    "constructs": "关怀, 公平, 忠诚, 权威, 神圣, 自由",
                    "ai_marketing": "消费者对AI营销的道德判断涉及多个道德基础：AI偏见(公平)、AI利用弱势群体(关怀)、AI违反社会规范(权威)。",
                },
                "Deontology": {
                    "name": "Deontology · 义务论伦理学",
                    "definition": "行为的道德正确性取决于行为本身是否符合道德规则或义务，而非其后果。某些行为(如欺骗、利用)本质上错误，即使可能产生好结果。",
                    "origin": "Kant (1785), Groundwork of the Metaphysics of Morals.",
                    "constructs": "道德义务, 绝对命令, 人性目的, 尊重, 权利, 尊严",
                    "ai_marketing": "AI营销的伦理边界：使用AI操纵消费者即使效果好也是错的(义务论视角)。消费者数据虽然可获取但不应被利用。",
                },
                "Utilitarianism": {
                    "name": "Utilitarianism · 功利主义伦理学",
                    "definition": "行为的道德正确性取决于其后果——'为最大多数人创造最大幸福'。与义务论相对：后果论方法认为目的可以正当化手段。",
                    "origin": "Bentham (1789); Mill (1863).",
                    "constructs": "效用最大化, 成本-收益计算, 幸福/痛苦, 所有人计算, 结果主义",
                    "ai_marketing": "AI营销的功利主义论证：AI个性化同时使消费者(找到好产品)和企业(提高效率)受益→整体效用最大化。但可能忽视少数群体。",
                },
                "Ethical Decision-Making": {
                    "name": "Ethical Decision-Making Theory · 伦理决策理论",
                    "definition": "个体/组织在面对伦理困境时的决策过程受多层面因素影响：道德强度(问题的伦理特征)、个体因素(道德发展阶段)、组织因素(伦理文化/氛围)。",
                    "origin": "Rest (1986); Jones (1991), Academy of Management Review.",
                    "constructs": "道德意识, 道德判断, 道德意图, 道德行为, 道德强度, 组织氛围",
                    "ai_marketing": "营销经理面对AI伦理困境(如使用暗模式/操控性个性化)时的决策过程。组织AI伦理指南如何影响决策。",
                },
                "Mental Accounting": {
                    "name": "Mental Accounting · 心理账户理论",
                    "definition": "消费者在心理上编码、分类和评估财务活动的方式，违反经济学的可替代性原则。不同来源/用途的钱被放入不同的'心理账户'，消费决策受账户框架影响。",
                    "origin": "Thaler (1985/1999), Journal of Behavioral Decision Making.",
                    "constructs": "心理账户, 交易效用, 沉没成本效应, 支付脱钩, 预算框架",
                    "ai_marketing": "AI个性化定价与心理账户：AI预测消费者对价格在不同'账户'中的感知（日常开支vs享乐消费），动态调整个性化折扣策略。",
                },
                "Affect-as-Information": {
                    "name": "Affect-as-Information Theory · 情感即信息理论",
                    "definition": "人们在判断和决策中将自己的情绪/情感状态作为信息来源。积极情绪信号'环境良好'→启发式加工；消极情绪信号'有问题'→系统式加工。",
                    "origin": "Schwarz & Clore (1983); Schwarz (2012).",
                    "constructs": "情绪信息, 情绪归因, 启发式加工, 系统式加工, 判断",
                    "ai_marketing": "AI交互中的情感设计：积极的AI交互体验→消费者直接用情感作为'这个AI很好'的判断信息。AI识别用户情绪并调整交互策略。",
                },
                "Warranty": {
                    "name": "Warranty Theory · 担保理论",
                    "definition": "在信息不对称市场中，卖方通过提供担保(退货、保修)来信号化产品质量。有效的担保需要足够成本，使低质量卖方无法模仿。",
                    "origin": "Spence (1977); Grossman (1981).",
                    "constructs": "担保成本, 信号可信度, 质量信号, 逆向选择, 道德风险",
                    "ai_marketing": "AI产品/服务的'担保'作为质量信号：AI工具的试用期、退款保证、算法透明度承诺作为消费者信心的担保机制。",
                },
                "Media Richness": {
                    "name": "Media Richness Theory · 媒介丰富度理论",
                    "definition": "不同媒介的信息承载能力(丰富度)不同，取决于四个标准：即时反馈、多线索(语言/表情/语调)、语言多样性、个人聚焦。丰富度高的媒介适合模糊任务；精简媒介适合清晰任务。",
                    "origin": "Daft & Lengel (1986), Management Science.",
                    "constructs": "媒介丰富度, 反馈速度, 线索多样性, 语言多样性, 任务模糊性, 媒介匹配",
                    "ai_marketing": "AI聊天机器人(文本)vs 虚拟人(视频/表情/声音)的媒介丰富度：高丰富度AI适合复杂服务(理财咨询)，低丰富度AI适合简单服务(订单查询)。",
                },
                "Media Equation": {
                    "name": "Media Equation · 媒体方程",
                    "definition": "人们对计算机、电视和其他媒体的反应本质上与其对真实人/地方的反应相同——'媒体=真实生活'。这种反应是无意识和自动的。",
                    "origin": "Reeves & Nass (1996), The Media Equation.",
                    "constructs": "礼貌, 人际距离, 人格, 情感, 社会角色, 社会规则",
                    "ai_marketing": "CASA的延伸：消费者对AI的反应与人际反应相同。AI的设计应遵循社会规则——礼貌的AI更受欢迎，'粗鲁'的AI会引发负面评价。",
                },
                "Modality-Agency": {
                    "name": "Modality-Agency Theory · 模态-代理理论",
                    "definition": "在数字界面中，用户可以感知到两个不同的交互对象：界面本身(模态)和界面背后的设计者/组织(代理)。不同的感知对象影响信任和归因。",
                    "origin": "Sundar (2008); Sundar & Nass (2000).",
                    "constructs": "界面模态, 代理感知, 设计者归因, 信任对象, 人机交互",
                    "ai_marketing": "消费者感知AI聊天机器人的两个层次：对话界面(可用性/反应速度)→模态感知；背后的品牌/企业(意图/诚信)→代理感知。不良体验归因于谁？",
                },
                "Social Capital": {
                    "name": "Social Capital Theory · 社会资本理论",
                    "definition": "嵌入在社会网络中的实际和潜在资源总和。三个维度：结构维度(网络联系)、关系维度(信任/规范)、认知维度(共享语言/愿景)。",
                    "origin": "Bourdieu (1986); Nahapiet & Ghoshal (1998), Academy of Management Review.",
                    "constructs": "结构维度(网络), 关系维度(信任/规范), 认知维度(共享理解), 网络闭合",
                    "ai_marketing": "AI品牌社区中的社会资本：AI推荐连接相似消费者→构建网络(结构)；AI促进互动信任(关系)；AI创造共享品牌语言(认知)。",
                },
                "Social Cognitive": {
                    "name": "Social Cognitive Theory · 社会认知理论",
                    "definition": "人类行为由个人因素、行为和环境三者交互决定(三元交互因果)。核心概念：观察学习(建模)、自我效能、自我调节。",
                    "origin": "Bandura (1986), Social Foundations of Thought and Action.",
                    "constructs": "三元交互因果, 观察学习, 自我效能, 自我调节, 结果期望",
                    "ai_marketing": "消费者的AI使用行为：观察到他人使用AI获得好处→自我效能提升→自己尝试使用AI。AI作为'角色模型'的观察学习效应。",
                },
                "Social Comparison": {
                    "name": "Social Comparison Theory · 社会比较理论",
                    "definition": "个体通过与他人比较来评估自己的能力和观点。上行比较(与更优者比)可能激励或导致自卑；下行比较(与更差者比)可能增强自尊但减少改进动力。",
                    "origin": "Festinger (1954); Wills (1981).",
                    "constructs": "上行比较, 下行比较, 自我评价, 自我增强, 同化, 对比",
                    "ai_marketing": "AI个性化推荐中的社会比较：'同类用户买了这个'→上行或下行比较框架。AI排行榜/徽章作为社会比较的激励机制。",
                },
                "Social Impact": {
                    "name": "Social Impact Theory · 社会影响理论",
                    "definition": "社会影响(他人对个体态度/行为的影响)是力量(来源强度)×即时性(时空接近度)×数量(来源数量)的函数。影响遵循心理社会法则：边际递减。",
                    "origin": "Latane (1981), American Psychologist.",
                    "constructs": "影响力, 来源强度, 即时性, 来源数量, 心理社会法则",
                    "ai_marketing": "AI评分/评论系统的社会影响：评论数量(来源数量)、评论者权威(来源强度)、即时推送(即时性)。AI生成的'其他人也买了'的社会影响效应。",
                },
                "Parasocial": {
                    "name": "Parasocial Relationship Theory · 准社会关系理论",
                    "definition": "受众与媒体人物(主持人、角色、网红)形成的一种单向的、但情感真实的关系。该互动具有'类社会性'，受众感知到亲密和友谊。",
                    "origin": "Horton & Wohl (1956), Psychiatry.",
                    "constructs": "准社会互动, 准社会关系, 亲密感, 类友谊, 受众依恋",
                    "ai_marketing": "AI虚拟网红/VTuber的准社会关系：粉丝与AI角色形成真实情感联结。AI比人类网红更可控、从不疲惫→更强的持续互动。",
                },
                "Equity": {
                    "name": "Equity Theory · 公平理论",
                    "definition": "个体评估交换关系公平性通过比较自己的投入-产出比与他人的投入-产出比。不公平感产生紧张，驱动行为以恢复公平(改变投入/产出/比较对象/离开关系)。",
                    "origin": "Adams (1965), Advances in Experimental Social Psychology.",
                    "constructs": "投入(Input), 产出(Outcome), 比较他人, 公平/不公平, 恢复行为",
                    "ai_marketing": "AI定价/推荐的公平感知：AI向不同消费者展示不同价格→与比较他人的不公平感。AI需要感知的公平(不仅是实际公平)才能维持消费者关系。",
                },
                "Reactance": {
                    "name": "Psychological Reactance Theory · 心理阻抗理论",
                    "definition": "当个体感知到自由被威胁或剥夺时产生的动机状态，驱使其恢复被威胁的自由。表现为：抵抗说服、做被禁止的行为、贬低被推荐选项。",
                    "origin": "Brehm (1966), A Theory of Psychological Reactance.",
                    "constructs": "自由威胁, 阻抗唤起, 自由恢复, 抵抗, 回旋镖效应",
                    "ai_marketing": "AI过度个性化引发阻抗：'这个AI太了解我了'→隐私威胁→感知自由被剥夺→抵制AI推荐。AI推荐需要'自由度感知'(给消费者选择感)。",
                },
                "Social Contagion": {
                    "name": "Social Contagion Theory · 社会传染理论",
                    "definition": "行为、态度、情绪在社会网络中像传染病一样传播。传播依赖暴露于'感染者'(已采纳者)和网络结构特征(聚类、弱连接)。",
                    "origin": "Levy & Nail (1993); Burt (1987).",
                    "constructs": "传染暴露, 采纳阈值, 网络结构, 弱连接, 聚类, 级联",
                    "ai_marketing": "AI营销传播的病毒性：AI生成的内容是否更容易在网络中传染？AI识别意见领袖和传染路径→精准'播种'营销信息。",
                },
            }

            # ═══ 扩展理论模式 (70+ patterns) ═══
            theory_patterns = [
                # ── 技术接受类 ──
                (r'\bTAM\b|Technology Acceptance Model|技术接受模型', "TAM"),
                (r'\bUTAUT\b|Unified Theory of Acceptance', "UTAUT"),
                (r'\bTRA\b|Theory of Reasoned Action|理性行为理论', "TRA"),
                (r'\bTPB\b|Theory of Planned Behavior|计划行为理论', "TPB"),
                (r'\bIDT\b|Innovation Diffusion Theory|\bDOI\b|创新扩散', "Innovation Diffusion"),
                (r'\bTTF\b|Task[-\s]Technology Fit|任务技术匹配', "TTF"),
                (r'\bIS Success|D[&]M.*Model|信息系统成功模型', "IS Success"),
                # ── 心理与决策类 ──
                (r'S-O-R|Stimulus[-\s]Organism[-\s]Response|刺激[-\s]机体[-\s]反应', "S-O-R"),
                (r'Elaboration Likelihood|\bELM\b|精细加工可能性|详尽可能', "ELM"),
                (r'Dual[-\s]Process|双加工|双系统', "Dual-Process"),
                (r'Cognitive Dissonance|认知失调', "Cognitive Dissonance"),
                (r'Cognitive Load|认知负荷', "Cognitive Load"),
                (r'Construal Level|\bCLT\b|解释水平', "Construal Level"),
                (r'Regulatory Focus|调节聚焦|促进聚焦|预防聚焦', "Regulatory Focus"),
                (r'Prospect Theory|前景理论|损失厌恶', "Prospect"),
                (r'Mental Accounting|心理账户', "Mental Accounting"),
                (r'Appraisal Theory|情绪评价|认知评价理论', "Appraisal"),
                (r'Affect[-\s]as[-\s]Information|情感即信息', "Affect-as-Information"),
                # ── 信任与隐私类 ──
                (r'Trust Transfer|信任转移', "Trust Transfer"),
                (r'Privacy Calculus|隐私计算', "Privacy Calculus"),
                (r'Commitment[-\s]Trust|承诺[-\s]信任', "Commitment-Trust"),
                (r'Source Credibility|来源可信度', "Source Credibility"),
                (r'Signaling Theory|Signalling|信号理论', "Signaling"),
                (r'Warranty Theory|担保理论', "Warranty"),
                # ── AI/人机交互类 ──
                (r'Anthropomorphism|拟人化(?!沟通)', "Anthropomorphism"),
                (r'Uncanny Valley|恐怖谷', "Uncanny Valley"),
                (r'Mind Perception|心智感知', "Mind Perception"),
                (r'CASA|Computers as Social Actors|计算机作为社会行动者|媒体方程', "CASA"),
                (r'Social Presence|社会临场感|社会存在感', "Social Presence"),
                (r'Media Richness|媒介丰富度', "Media Richness"),
                (r'Media Equation|媒体方程', "Media Equation"),
                (r'Modality[-\s]Agency|模态代理', "Modality-Agency"),
                # ── 社会与关系类 ──
                (r'Social Exchange(?! Theory.*Social)|社会交换(?!理论)', "Social Exchange"),
                (r'Social Identity(?! Theory)|社会认同(?!理论)', "Social Identity"),
                (r'Social Capital|社会资本', "Social Capital"),
                (r'Social Cognitive|社会认知(?:理论)?', "Social Cognitive"),
                (r'Social Comparison|社会比较', "Social Comparison"),
                (r'Social Impact|社会影响(?:理论)?', "Social Impact"),
                (r'Parasocial[-\s]Relationship|准社会关系|准社会交往', "Parasocial"),
                (r'Attribution Theory|归因理论', "Attribution"),
                (r'Equity Theory|公平理论|Adams.*理论', "Equity"),
                (r'Reactance Theory|Psychological Reactance|心理阻抗|逆反心理', "Reactance"),
                (r'Social Contagion|社会传染|行为传染|信息级联', "Social Contagion"),
                # ── 动机与使用类 ──
                (r'Uses? and Gratification|\bU&G\b|使用与满足', "U&G"),
                (r'Self[-\s]Determination|\bSDT\b|自我决定', "Self-Determination"),
                (r'Expectation[-\s]Confirmation|\bECT\b|\bECM\b|期望确认|期望不一致', "ECT"),
                (r'Flow Theory|心流理论|沉浸理论', "Flow"),
                (r'Goal[-\s]Setting|目标设定', "Goal-Setting"),
                (r'Protection Motivation|\bPMT\b|保护动机', "PMT"),
                (r'Push[-\s]Pull[-\s]Mooring|\bPPM\b|推拉锚定', "PPM"),
                # ── 说服与沟通类 ──
                (r'Persuasion Knowledge|\bPKM\b|说服知识', "Persuasion Knowledge"),
                (r'Inoculation Theory|接种理论', "Inoculation"),
                (r'Narrative[-\s]Transportation|Transportation Theory|叙事传输|叙事沉浸', "Narrative Transportation"),
                (r'Agenda[-\s]Setting|议程设置', "Agenda-Setting"),
                (r'Framing Theory|框架理论|信息框架', "Framing"),
                (r'Two[-\s]Step Flow|两级传播', "Two-Step Flow"),
                (r'Cultivation Theory|涵化理论', "Cultivation"),
                # ── 战略与管理类 ──
                (r'Resource[-\s]Based View|\bRBV\b|资源基础观|资源基础理论', "RBV"),
                (r'Dynamic Capabilit(?:y|ies)|动态能力', "Dynamic Capabilities"),
                (r'Service[-\s]Dominant Logic|\bSDL\b|服务主导逻辑', "SDL"),
                (r'Stakeholder Theory|利益相关者', "Stakeholder"),
                (r'Agency Theory|代理理论|委托代理', "Agency"),
                (r'Institutional Theory|制度理论|制度同构|新制度主义', "Institutional"),
                (r'Contingency Theory|权变理论', "Contingency"),
                (r'Transaction Cost|\bTCE\b|交易成本', "Transaction Cost"),
                (r'Absorptive Capacity|吸收能力', "Absorptive Capacity"),
                (r'Organizational Learning|组织学习', "Organizational Learning"),
                (r'Institutional Trust|制度信任', "Institutional Trust"),
                # ── 消费行为类 ──
                (r'Means[-\s]End Chain|手段[-\s]目的链', "Means-End Chain"),
                (r'Perceived Risk|感知风险(?:理论)?', "Perceived Risk"),
                (r'Perceived Value|感知价值(?:理论)?', "Perceived Value"),
                (r'Theory of Consumption Value|消费价值理论', "Consumption Value"),
                (r'Self[-\s]Congruity|自我一致性|自我-品牌一致', "Self-Congruity"),
                (r'Brand Attachment|品牌依恋', "Brand Attachment"),
                (r'Brand Relationship|品牌关系', "Brand Relationship"),
                (r'Customer Engagement|顾客参与|顾客契合', "Customer Engagement"),
                (r'Relationship Marketing|关系营销', "Relationship Marketing"),
                (r'Co[-\s]Creation|价值共创(?!理论)', "Co-Creation"),
                (r'Service Quality|SERVQUAL|服务质量', "Service Quality"),
                (r'Customer Satisfaction|顾客满意(?!度)', "Customer Satisfaction"),
                # ── 知识/学习类 ──
                (r'Knowledge[-\s]Based View|\bKBV\b|知识基础观', "KBV"),
                (r'Information Processing|信息处理(?:理论)?', "Information Processing"),
                (r'Heuristic[-\s]Systematic|\bHSM\b|启发式[-\s]系统式', "HSM"),
                (r'Sense[-\s]Making|Sensemaking|意义建构', "Sensemaking"),
                # ── 伦理/道德类 ──
                (r'Moral Foundation|道德基础', "Moral Foundations"),
                (r'Deontology|Deontological|义务论', "Deontology"),
                (r'Utilitarian|功利主义', "Utilitarianism"),
                (r'Ethical Decision[-\s]Making|伦理决策', "Ethical Decision-Making"),
            ]

            theory_counts = Counter()
            theory_papers = {}
            matched_theories = set()

            for p in full_data:
                # 搜索范围：研究问题 + 假设 + 讨论结论
                text = " ".join([
                    p.get("研究问题", ""),
                    p.get("研究假设", ""),
                    p.get("讨论与结论", ""),
                ]).lower()

                matched_in_paper = set()
                for pattern, canonical in theory_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    if matches:
                        if canonical not in matched_in_paper:
                            matched_in_paper.add(canonical)
                            theory_counts[canonical] += 1
                            if canonical not in theory_papers:
                                theory_papers[canonical] = []
                            theory_papers[canonical].append(p.get("标题", "?"))
                matched_theories |= matched_in_paper

            if theory_counts:
                top_theories = theory_counts.most_common(25)

                col_theory_chart, col_theory_info = st.columns([1, 1])

                with col_theory_chart:
                    st.caption(f"**理论分布 Top {len(top_theories)}**（共检出 {len(theory_counts)} 个理论框架）")
                    st.bar_chart({t[:30]: c for t, c in top_theories})

                    with st.expander("理论-论文关联"):
                        for theory, count in top_theories:
                            papers = theory_papers.get(theory, [])
                            st.markdown(f"**{theory}** ({count}篇)")
                            for pt in papers[:5]:
                                st.caption(f"  • {pt}")
                            if len(papers) > 5:
                                st.caption(f"  ... 还有 {len(papers)-5} 篇")

                with col_theory_info:
                    st.caption("**理论详解**")
                    selected_theory = st.selectbox(
                        "选择理论",
                        [""] + [t for t, c in top_theories],
                        format_func=lambda x: "— 选择一个理论 —" if x == "" else f"{x} ({theory_counts[x]}篇)",
                        key="theory_detail"
                    )

                    if selected_theory:
                        # ── 精简版预览（即时显示）──
                        if selected_theory in THEORY_ENCYCLOPEDIA:
                            entry = THEORY_ENCYCLOPEDIA[selected_theory]
                            st.markdown(f"### {entry['name']}")
                            st.markdown(f"**定义**  \n{entry['definition']}")
                            st.markdown(f"**学术来源**  \n{entry['origin']}")
                            st.markdown(f"**核心构念**  \n{entry['constructs']}")
                            st.markdown(f"**AI × 营销应用**  \n{entry['ai_marketing']}")
                        else:
                            st.markdown(f"### {selected_theory}")
                            st.info("精简版尚未编入。")

                        st.divider()

                        # ── DeepSeek 教授级深度解读 ──
                        if st.button("🎓 教授级深度解读", type="primary",
                                     help="让 DeepSeek V4 Pro 以资深教授身份，深度剖析该理论的学术溯源、核心命题、演变争议、AI营销应用及推荐阅读",
                                     key=f"deep_theory_{selected_theory}"):
                            with st.spinner(f"DeepSeek 正在深度解读 {selected_theory}..."):
                                # 收集该理论相关的本地论文摘要做上下文
                                related_papers = theory_papers.get(selected_theory, [])[:5]
                                local_context = ""
                                if related_papers:
                                    local_context = "\n\n该理论在你知识库中出现于以下论文：\n" + "\n".join(f"- {t}" for t in related_papers)

                                deep_prompt = f"""请对「{selected_theory}」理论进行一次深度学术剖析。按以下结构展开，中文，专业术语保留英文：

## 1. 学术溯源
- 谁、哪年、哪本期刊/著作首次提出？要解决什么问题？当时的主流替代理论？
- 理论经历的重要修正和扩展（关键学者+年份）

## 2. 核心构念与命题
- 逐一拆解核心构念的含义和操作化方式
- 构念间逻辑关系（文字描述概念框架）
- 核心命题（命题1: ...；命题2: ...）
- 边界条件：什么条件下适用/不适用

## 3. 学术演变与争议
- 重要修正版本
- 主要批评
- 竞争性或互补性理论

## 4. AI × 营销中的应用
- 主要解释什么现象
- 典型研究设计（实验/问卷/二手数据）
- 重要实证发现
- 可进一步拓展或检验的角度

## 5. 推荐阅读
- 5-7篇关键文献（APA格式），含原创、修正、AI营销应用各1-2篇
{local_context}

深入、严谨，触及理论深层逻辑和未解决问题。不要角色扮演，直接输出分析内容。"""

                                msgs = [
                                    {"role": "system", "content": "你在市场营销×AI营销交叉领域有深厚的学术积累。回答风格：学术严谨、有洞察力、具体。中文，专业术语保留英文。不扮演任何角色，直接输出内容。"},
                                    {"role": "user", "content": deep_prompt},
                                ]
                                try:
                                    result = _run_async(_chat_via_deepseek(msgs))
                                    if result:
                                        st.markdown(result)
                                    else:
                                        st.warning("API 返回空，请重试。")
                                except Exception as e:
                                    st.error(f"DeepSeek 调用失败: {e}")
                    else:
                        st.info("👈 从下拉菜单中选择一个理论，查看精简版定义后可点击「教授级深度解读」获取DeepSeek生成的详尽学术分析。")

            else:
                st.info("未识别到理论框架。可能论文以中文为主或使用了非标准理论名。")

        # ── Tab 3: 变量网络 ──
        with tab3:
            try:
                import networkx as nx
                from pyvis.network import Network

                G = nx.DiGraph()
                var_freq = Counter()
                var_papers = {}  # 记录每个变量出现在哪些论文

                for p in full_data:
                    var_text = p.get("变量汇总", "")
                    if not var_text or len(var_text) < 20:
                        continue
                    # 按变量名称分割为独立变量块
                    blocks = re.split(r'\n(?=变量名称[：:])', var_text)
                    variables = {}
                    for block in blocks:
                        name_match = re.search(r'变量名称[：:]\s*([^\n]{2,60})', block)
                        if not name_match:
                            continue
                        var_name = name_match.group(1).strip()[:40]
                        # 去括号内英文，保留更简洁的中文名
                        var_name_clean = re.sub(r'[（(][^)）]*[)）]', '', var_name).strip()
                        if len(var_name_clean) >= 2:
                            var_name = var_name_clean
                        var_freq[var_name] += 1
                        # 记录来源论文
                        author_year = f"{p.get('第一作者','?')} {p.get('年份','?')}"
                        if var_name not in var_papers:
                            var_papers[var_name] = []
                        var_papers[var_name].append(author_year)

                        # 类型检测
                        type_match = re.search(r'变量类型[：:]\s*([^\n]{2,20})', block)
                        type_str = type_match.group(1).strip() if type_match else ""
                        if any(t in type_str for t in ["自变量", "IV", "independent"]):
                            vtype = "IV"
                        elif any(t in type_str for t in ["因变量", "DV", "dependent"]):
                            vtype = "DV"
                        elif any(t in type_str for t in ["中介", "mediator"]):
                            vtype = "mediator"
                        elif any(t in type_str for t in ["调节", "moderator"]):
                            vtype = "moderator"
                        else:
                            vtype = "other"
                        variables[var_name] = vtype
                        G.add_node(var_name, type=vtype, weight=var_freq[var_name])

                    # 论文内变量连接：IV → DV, IV → mediator → DV, moderator → DV
                    ivs = [v for v, t in variables.items() if t == "IV"]
                    dvs = [v for v, t in variables.items() if t == "DV"]
                    meds = [v for v, t in variables.items() if t == "mediator"]
                    mods = [v for v, t in variables.items() if t == "moderator"]
                    for iv in ivs:
                        for dv in dvs:
                            if meds:
                                for med in meds:
                                    G.add_edge(iv, med)
                                    G.add_edge(med, dv)
                            else:
                                G.add_edge(iv, dv)
                            for mod in mods:
                                G.add_edge(mod, dv)

                if G.number_of_nodes() > 0:
                    col_graph, col_stats = st.columns([3, 1])

                    with col_graph:
                        # pyvis 交互式力导向图
                        net = Network(height="620px", width="100%",
                                      directed=True, notebook=False, bgcolor="#fafafa")

                        net.set_options(f"""{{
                          "physics": {{
                            "forceAtlas2Based": {{
                              "gravitationalConstant": -120,
                              "centralGravity": 0.01,
                              "springLength": 250,
                              "springConstant": 0.02,
                              "damping": 0.35,
                              "avoidOverlap": 0.5
                            }},
                            "minVelocity": 0.75,
                            "maxVelocity": 30,
                            "solver": "forceAtlas2Based",
                            "stabilization": {{"iterations": 250, "fit": true}}
                          }},
                          "interaction": {{
                            "hover": true,
                            "tooltipDelay": 100,
                            "zoomView": true,
                            "dragView": true,
                            "navigationButtons": true
                          }},
                          "nodes": {{
                            "font": {{"size": 13, "face": "Microsoft YaHei, Noto Sans SC, sans-serif"}},
                            "borderWidth": 2,
                            "borderWidthSelected": 3
                          }},
                          "edges": {{
                            "color": {{"color": "#bbb", "highlight": "#666"}},
                            "smooth": {{"type": "continuous"}},
                            "arrows": {{"to": {{"enabled": true, "scaleFactor": 0.6}}}}
                          }}
                        }}""")

                        colors = {"IV": "#4CAF50", "DV": "#2196F3", "mediator": "#FF9800",
                                  "moderator": "#E91E63", "other": "#9E9E9E"}
                        type_labels = {"IV": "自变量", "DV": "因变量", "mediator": "中介变量",
                                       "moderator": "调节变量", "other": "其他"}

                        for node in G.nodes():
                            ntype = G.nodes[node].get("type", "other")
                            w = G.nodes[node].get("weight", 1)
                            size = 18 + min(w, 15) * 4
                            papers = var_papers.get(node, [])
                            paper_list = "<br>".join(papers[:5])
                            if len(papers) > 5:
                                paper_list += f"<br>...等{len(papers)}篇"
                            net.add_node(
                                node,
                                label=node,
                                color={"background": colors.get(ntype, "#999"),
                                       "border": "#333", "highlight": {"background": colors.get(ntype, "#999")}},
                                size=size,
                                title=f"<b>{node}</b><br>类型: {type_labels.get(ntype, ntype)}<br>频次: {w}<br><br>来源:<br>{paper_list}"
                            )

                        for u, v in G.edges():
                            net.add_edge(u, v, color="#ccc", width=1)

                        # 渲染为 HTML 并嵌入
                        import tempfile, os
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
                        net.save_graph(tmp.name)
                        tmp.close()
                        with open(tmp.name, "r", encoding="utf-8") as fh:
                            html = fh.read()
                        os.unlink(tmp.name)
                        st.components.v1.html(html, height=640, scrolling=False)
                        st.caption("拖拽节点 · 滚轮缩放 · 悬停看详情 · 底部按钮平移")

                    with col_stats:
                        st.caption(f"**{G.number_of_nodes()} 个变量 · {G.number_of_edges()} 条边**")
                        st.divider()
                        # 按类型分列展示
                        for vt, label, emoji in [
                            ("IV", "自变量", "🟢"), ("DV", "因变量", "🔵"),
                            ("mediator", "中介", "🟠"), ("moderator", "调节", "🔴")
                        ]:
                            vars_of_type = [(v, var_freq[v]) for v, t in
                                            {n: G.nodes[n].get("type", "") for n in G.nodes()}.items()
                                            if t == vt]
                            if vars_of_type:
                                st.caption(f"{emoji} **{label}** ({len(vars_of_type)}个)")
                                for v, c in sorted(vars_of_type, key=lambda x: -x[1])[:8]:
                                    st.markdown(f"`{c}×` {v[:35]}")
                else:
                    st.info("变量汇总字段中未提取到足够的变量关系。可从「文献阅读」Tab 重新精读论文以生成变量数据。")
            except ImportError as e:
                st.info(f"缺少依赖: {e}。运行: pip install networkx pyvis")

        # ── Tab 4: 主题关键词 ──
        with tab4:
            st.caption("基于论文关键词的主题分布")
            all_keywords = []
            for p in full_data:
                kw = p.get("关键词", "")
                if kw:
                    # 分号或逗号分隔
                    for k in re.split(r'[;,；，]', kw):
                        k = k.strip().lower()
                        if k and len(k) > 2:
                            all_keywords.append(k)

            if all_keywords:
                kw_counts = Counter(all_keywords)
                top_kw = kw_counts.most_common(30)
                col_kw_chart, col_kw_list = st.columns([2, 1])
                with col_kw_chart:
                    st.bar_chart({k[:30]: c for k, c in top_kw[:20]})
                with col_kw_list:
                    st.caption("**Top 30 关键词**")
                    for kw, cnt in top_kw:
                        st.markdown(f"`{cnt}×` {kw[:50]}")
            else:
                st.info("关键词数据不足。")

        # ── Tab 5: 研究空白 ──
        with tab5:
            st.caption("提取「未来研究方向」条目 → DeepSeek 综合为可操作的研究方向")

            # ── 提取：分离"局限性"与"未来研究方向" ──
            future_items = []  # 只取未来研究方向
            for p in full_data:
                lim = p.get("局限与展望", "")
                if not lim:
                    continue
                # 找到"未来研究方向"段落
                future_section = ""
                f_marker = re.search(r'(?:未来研究|未来方向|研究展望|Future\s+Research|Future\s+Direction)', lim, re.IGNORECASE)
                l_marker = re.search(r'(?:局限性[：:]|局限[：:]|Limitation)', lim, re.IGNORECASE)
                if f_marker:
                    start = f_marker.start()
                    end = l_marker.start() if (l_marker and l_marker.start() > start) else len(lim)
                    future_section = lim[start:end]
                else:
                    # 无明确标记，用关键词分行
                    for line in lim.split("\n"):
                        if re.search(r'(?:未来|建议|应[该当]|值得|有待|进一步|还需|尚需|可[以从]|值得|需要.*研究)', line):
                            future_section += line + "\n"
                if not future_section:
                    continue
                # 提取编号条目
                items = re.findall(r'(?:^|\n)\s*(?:[(（]?\d+[)）.．、]\s*|[-•]\s+)([^\n]{15,180})', future_section)
                if not items:
                    for s in re.split(r'[。\n]', future_section):
                        s = s.strip()
                        if len(s) >= 12 and not re.match(r'^(?:未来|局限|研究|伦理)', s):
                            items.append(s[:150])
                for item in items:
                    item = item.strip()
                    # 过滤明显的局限性表述
                    if item and len(item) >= 12 and not re.match(r'^(?:缺乏|不足|仅|只|限于|没有|无法|难以|本文)', item):
                        future_items.append({
                            "text": item,
                            "author": p.get("第一作者", "?"),
                            "year": p.get("年份", "?"),
                        })

            if not future_items:
                st.info("未提取到未来研究方向条目。")
            else:
                st.caption(f"从 {len(full_data)} 篇文献提取 {len(future_items)} 条未来研究方向")

                # ── DeepSeek 综合 ──
                if st.button("🧠 综合研究方向", type="primary", help="用 DeepSeek V4 Pro 将数百条方向综合为教授级的、可操作的研究方向"):
                    with st.spinner("DeepSeek V4 Pro 综合中... (约30秒)"):
                        # 取代表性样本（去重 + 多样化）
                        seen = set()
                        sample = []
                        for f in future_items:
                            key = f["text"][:40]
                            if key not in seen:
                                seen.add(key)
                                sample.append(f)
                                if len(sample) >= 100:
                                    break

                        sample_text = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(sample))
                        synthesis_prompt = f"""你是一位市场营销×AI营销领域的资深教授。你的博士生整理了知识库中{len(full_data)}篇文献的未来研究方向，共{len(future_items)}条。

以下是其中{len(sample)}条代表性条目：
{sample_text}

请你做以下工作：
1. **忽略**那些明显只是某篇特定论文的局限或元注释（如"建议补充更多数据库"、"本文仅为概念性论文需实证检验"、方法论建议如"采用混合方法"）。这些不是研究方向。
2. **聚焦**那些具体的、可操作的研究问题——即博士生可以据此设计一项研究的方向。
3. 将这些方向综合为 **8-12 个具体的研究方向**，每个方向：
   - 一个清晰的标题（≤20字）
   - 2-3句话说明为什么这个方向值得做、可以从哪些角度切入
   - 语言：中文，像一个教授在指导博士生做选题

输出格式：
## 1. 方向标题
为什么值得做 + 研究建议 (2-3句话)

## 2. 方向标题
..."""

                        try:
                            msgs = [
                                {"role": "system", "content": "你是一位市场营销×AI营销领域的资深教授，正在指导博士生选题。你的回答像一个真正的教授——有洞察力、实用、具体。中文。"},
                                {"role": "user", "content": synthesis_prompt},
                            ]
                            result = _run_async(_chat_via_deepseek(msgs))
                            if result:
                                st.markdown(result)
                            else:
                                st.warning("API 返回空，请重试。")
                        except Exception as e:
                            st.error(f"综合失败: {e}")

                # ── 原始条目（可折叠）──
                with st.expander(f"原始条目 ({len(future_items)} 条)"):
                    for i, f in enumerate(future_items[:50]):
                        st.caption(f"`{f['author']} {f['year']}` {f['text'][:150]}")



# ═══════════════════════════════════════════════════════════════
#  管理
# ═══════════════════════════════════════════════════════════════

elif page == "管理":
    st.header("管理")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["清理 PDF", "待复核", "🔄 批量重读", "关键词管理", "系统状态"])

    # ── Tab 1: 清理 PDF ──
    with tab1:
        st.subheader("清理已处理的 PDF")
        pdf_files = sorted(PDF_DIR.glob("*.pdf")) if PDF_DIR.exists() else []
        if not pdf_files:
            st.info("没有 PDF 文件。")
        else:
            # 加载 processed_log
            processed_dois = set()
            if PROCESSED_LOG.exists():
                with open(PROCESSED_LOG, "r", encoding="utf-8") as f:
                    for rec in json.load(f):
                        doi = rec.get("doi", "").strip().lower()
                        if doi:
                            processed_dois.add(doi)

            cleanable = []
            for pdf in pdf_files:
                doi = extract_doi_from_pdf(pdf)
                if doi and doi.strip().lower() in processed_dois:
                    cleanable.append((pdf, doi))

            if cleanable:
                st.warning(f"共 {len(cleanable)} 个 PDF 可清理（已在 processed_log 中）")
                total_size = sum(p[0].stat().st_size for p in cleanable)
                st.caption(f"可释放空间: {total_size / 1024 / 1024:.1f} MB")
                for pdf, doi in cleanable:
                    st.markdown(f"- `{pdf.name}` (DOI: {doi[:40]}...)")

                if st.button(f"确认删除 {len(cleanable)} 个文件", type="primary"):
                    deleted = 0
                    for pdf, _ in cleanable:
                        try:
                            pdf.unlink()
                            deleted += 1
                        except Exception as e:
                            st.error(f"删除失败: {pdf.name} — {e}")
                    st.success(f"已删除 {deleted} 个文件")
                    st.rerun()
            else:
                st.info("没有可清理的 PDF（所有 PDF 均未在 processed_log.json 中记录）。")

    # ── Tab 2: 待复核队列 ──
    with tab2:
        st.subheader("待人工复核")
        st.caption("防幻觉流水线自动标记的 🟡/🔴 笔记，集中在此处复核。")

        queue = _get_review_queue()
        if not queue:
            st.success("复核队列为空，所有笔记均为高置信。")
        else:
            # 统计
            low_count = sum(1 for q in queue if q.get("confidence") == "low")
            med_count = sum(1 for q in queue if q.get("confidence") == "medium")
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("🔴 低置信 (需复核)", low_count)
            col_b.metric("🟡 中置信 (建议复核)", med_count)
            col_c.metric("总计", len(queue))

            st.divider()
            for i, item in enumerate(queue):
                conf = item.get("confidence", "medium")
                has_fail = item.get("issues", "").upper().startswith("FAIL")
                if conf == "low" or has_fail:
                    emoji = "🔴"
                elif conf == "medium":
                    emoji = "🟡"
                else:
                    emoji = "🟢"
                with st.expander(f"{emoji} [{conf.upper()}] {item.get('title', '?')[:120]}", expanded=(conf == "low")):
                    c1, c2, c3 = st.columns(3)
                    c1.caption(f"**作者**: {item.get('first_author', '?')}")
                    c2.caption(f"**年份**: {item.get('year', '?')}")
                    c3.caption(f"**期刊**: {item.get('journal', '?')[:30]}")
                    if item.get("doi"):
                        st.code(item["doi"], language=None)
                    if item.get("issues"):
                        st.warning(f"**问题**: {item['issues'][:500]}")
                    if item.get("added"):
                        st.caption(f"加入时间: {item['added']}")

                    col_done, col_retry, col_skip = st.columns(3)
                    with col_done:
                        if st.button(f"✅ 已复核，移出队列", key=f"review_done_{i}"):
                            if item.get("doi"):
                                _remove_from_review_queue(item["doi"])
                                st.toast("已移出复核队列", icon="✅")
                                st.rerun()
                    with col_retry:
                        if st.button(f"🔄 重新阅读修复", key=f"review_retry_{i}",
                                     help="用现有笔记+问题描述让DeepSeek针对性修复"):
                            with st.spinner(f"正在修复 {item.get('title','')[:40]}..."):
                                fixed = _run_async(_retry_fix_notes(
                                    item.get("doi", ""), item.get("issues", "")
                                ))
                            if fixed:
                                st.toast("修复成功！已移出复核队列", icon="✅")
                                st.rerun()
                            else:
                                st.toast("修复失败，仍保留在队列中", icon="❌")
                    with col_skip:
                        if st.button(f"⏭ 跳过（保留在队列）", key=f"review_skip_{i}"):
                            st.toast("已跳过", icon="⏭")

    # ── Tab 3: 批量重读 ──
    with tab3:
        st.subheader("批量重读（Prompt 升级时使用）")
        st.caption("从 Zotero 集合读取已入库文献，用最新 Prompt 重新深度阅读并覆写笔记。")

        # 预览 Zotero 文献
        cfg = _load_config()
        zotero_cfg = cfg.get("zotero", {})
        if zotero_cfg.get("api_key"):
            if st.button("获取 Zotero 文献列表"):
                with st.spinner("从 Zotero 获取..."):
                    try:
                        coll_key = _run_async(ZoteroStore()._get_collection_key())
                        if coll_key:
                            dois, titles = _run_async(fetch_zotero_existing_dois())
                            st.info(f"Zotero 集合中共 {len(dois)} 篇文献")
                    except Exception as e:
                        st.error(f"获取失败: {e}")

            st.divider()
            # 提示：使用新版 LitCallOrchestrator (reread 模式)
            st.info("💡 推荐使用 CLI 批量重读: `python -m litcall.ui.worker --mode reread`")
            if st.button("开始批量重读（CLI 新版）", type="primary"):
                with st.spinner("批量重读中...（可能需要较长时间）"):
                    try:
                        from litcall.agent.orchestrator import (
                            LitCallOrchestrator, OrchestratorMode,
                        )
                        orch = LitCallOrchestrator(
                            mode=OrchestratorMode.REREAD,
                        )
                        result = _run_async(orch.run())
                        st.success(f"批量重读完成: {result}")
                        # 重建索引
                        with st.spinner("重建知识库索引..."):
                            _get_paper_index.clear()
                            build_paper_index()
                        st.success("知识库索引已更新")
                    except Exception as e:
                        st.error(f"批量重读异常: {e}")
        else:
            st.warning("Zotero 未配置，无法使用批量重读。")

    # ── Tab 4: 关键词管理 ──
    with tab4:
        st.subheader("关键词管理")
        cfg = _load_config()
        keywords_cfg = cfg.get("keywords", {"broad": [], "narrow": []})

        col_b, col_n = st.columns(2)
        with col_b:
            st.markdown("**Broad 关键词**")
            new_broad = st.text_area("每行一个", value="\n".join(keywords_cfg.get("broad", [])), height=150, key="broad_kw_edit")
        with col_n:
            st.markdown("**Narrow 关键词**")
            new_narrow = st.text_area("每行一个", value="\n".join(keywords_cfg.get("narrow", [])), height=150, key="narrow_kw_edit")

        if st.button("保存关键词", type="primary"):
            cfg["keywords"] = {
                "broad": [k.strip() for k in new_broad.split("\n") if k.strip()],
                "narrow": [k.strip() for k in new_narrow.split("\n") if k.strip()],
            }
            _save_config(cfg)
            st.success("关键词已保存")
            st.rerun()

    # ── Tab 5: 系统状态 ──
    with tab5:
        st.subheader("系统状态")
        cfg = _load_config()

        # ── 图表分析开关 ──
        fig_enabled = cfg.get("enable_figure_analysis", False)
        col_fig, col_fig2 = st.columns([1, 2])
        with col_fig:
            new_fig = st.toggle("图表分析", fig_enabled,
                                help="开启后，深度阅读时将调用 Gemini Vision 识别图表 + DeepSeek 分析。"
                                     "需要配置 gemini_api_key。默认关闭，找到合适的图表分析模型后再开启。")
            if new_fig != fig_enabled:
                cfg["enable_figure_analysis"] = new_fig
                _save_config(cfg)
                st.rerun()
        with col_fig2:
            if fig_enabled:
                gemini_ok = bool(cfg.get("gemini_api_key", ""))
                if gemini_ok:
                    st.success("已启用 — Gemini API 已配置，深度阅读时将自动分析图表")
                else:
                    st.warning("已启用但 Gemini API Key 未配置 — 图表分析不会实际运行")
            else:
                st.caption("已关闭 — 深度阅读时跳过图表分析")

        st.divider()
        st.json({
            "知识库索引": f"{_get_paper_index()[0]} 篇",
            "processed_log.json": f"{PROCESSED_LOG.exists()} ({len(json.loads(PROCESSED_LOG.read_text(encoding='utf-8')) if PROCESSED_LOG.exists() else [])} 条)",
            "Excel": f"{EXCEL_PATH.exists()}",
            "Obsidian Vault": f"{OBSIDIAN_DIR.exists()}",
            "待处理文献": f"{PDF_DIR.exists()} ({len(list(PDF_DIR.glob('*.pdf'))) if PDF_DIR.exists() else 0} 个 PDF)",
            "DeepSeek API": bool(cfg.get("deepseek_api_key", "")),
            "Gemini Vision": bool(cfg.get("gemini_api_key", "")),
            "图表分析": "已启用" if fig_enabled else "已关闭",
            "Zotero": bool(cfg.get("zotero", {}).get("api_key", "")),
            "影响因子库": f"{len(_journal_if_map)} 条",
            "关键词": f"{len(cfg.get('keywords', {}).get('broad', []))} broad + {len(cfg.get('keywords', {}).get('narrow', []))} narrow",
        })
