"""批量重读管理组件。

功能:
- 预览 Zotero litcall 集合文献列表
- 启动批量重读（Zotero → Obsidian 完整重建）
- 显示进度和结果

铁律: Zotero litcall 集合是唯一真相来源，不碰用户其他文献。
Agent 是唯一入口，所有操作通过 LitCallOrchestrator 执行。
"""

import asyncio
import streamlit as st
from typing import Dict, List, Optional


def _run_async(coro):
    """在 Streamlit 同步环境中运行异步协程。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        return asyncio.run(coro)
    except RuntimeError:
        return asyncio.run(coro)


def render_reread_tab():
    """渲染批量重读 Tab。

    流程:
    1. 获取 Zotero litcall 集合条目预览
    2. 用户确认后启动重读
    3. 显示完成统计 + Zotero vs Obsidian 比对
    """
    st.subheader("🔄 批量重读（Zotero → Obsidian 完整重建）")
    st.caption(
        "以 Zotero litcall 集合为唯一真相来源，重新深度阅读全部文献，"
        "用最新 18 字段模板覆写 Obsidian 笔记。"
    )

    # ── Step 1: 预览 Zotero litcall 集合 ──
    st.markdown("### 1. Zotero litcall 集合预览")

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("📋 获取 Zotero 文献列表", use_container_width=True):
            with st.spinner("正在从 Zotero litcall 集合获取..."):
                try:
                    from litcall.stores.zotero import ZoteroStore
                    zs = ZoteroStore()
                    items = _run_async(zs.list_collection_items())

                    if items:
                        st.session_state["reread_items"] = items
                        st.session_state["reread_count"] = len(items)
                    else:
                        st.warning("Zotero litcall 集合为空或无法访问")
                except Exception as e:
                    st.error(f"获取失败: {e}")

    with col2:
        count = st.session_state.get("reread_count", 0)
        if count > 0:
            st.success(f"✅ Zotero litcall 集合共 **{count}** 篇文献")
        else:
            st.info("点击左侧按钮获取文献列表")

    # 展示文献列表
    items = st.session_state.get("reread_items", [])
    if items:
        with st.expander(f"查看全部 {len(items)} 篇文献", expanded=False):
            for idx, item in enumerate(items, 1):
                title = item.get("title", "?")[:80]
                doi = item.get("doi", "?")
                st.write(f"{idx}. {title}  `{doi}`")

    st.divider()

    # ── Step 2: 启动重读 ──
    st.markdown("### 2. 启动批量重读")

    if not items:
        st.warning("请先获取 Zotero litcall 集合文献列表")
        return

    target = st.number_input(
        "目标论文数（0 = 全部）",
        min_value=0,
        max_value=len(items),
        value=0,
        step=1,
        help="设置限制用于测试，0 表示处理全部",
    )

    if st.button("🚀 开始批量重读", type="primary", use_container_width=True):
        from litcall.agent.orchestrator import (
            LitCallOrchestrator, OrchestratorMode,
        )

        orch = LitCallOrchestrator(
            mode=OrchestratorMode.REREAD,
            target_papers=target if target > 0 else 0,
        )

        progress_bar = st.progress(0, text="正在重读...")
        status_text = st.empty()

        try:
            with st.spinner(f"批量重读中...（共 {len(items)} 篇，目标 {target or '不限'} 篇）"):
                result = _run_async(orch.run())

            # 显示结果
            progress_bar.progress(100)

            success = result.get("success", 0)
            failed = result.get("failed", 0)
            no_pdf = result.get("no_pdf", 0)
            total = result.get("total", 0)
            zotero_count = result.get("zotero_count", 0)
            obsidian_count = result.get("obsidian_count", 0)

            st.success(f"### ✅ 批量重读完成")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("总处理", total)
            col2.metric("成功", success)
            col3.metric("失败", failed)
            col4.metric("无 PDF", no_pdf)

            st.divider()
            st.markdown("### 四库比对")
            col1, col2, col3 = st.columns(3)
            col1.metric("Zotero", zotero_count)
            col2.metric("Obsidian", obsidian_count)
            col3.metric(
                "一致",
                "✅" if zotero_count == obsidian_count
                else f"❌ 差 {abs(zotero_count - obsidian_count)}"
            )

            if zotero_count != obsidian_count:
                st.warning(
                    f"Zotero 和 Obsidian 数量不一致！"
                    f"请运行 `cross_library_audit()` 排查。"
                )

        except Exception as e:
            progress_bar.progress(0)
            st.error(f"批量重读异常: {e}")
            import traceback
            st.code(traceback.format_exc())

    st.divider()

    # ── Step 3: CLI 快速入口 ──
    st.markdown("### 3. CLI 方式")
    st.code(
        f"python -m litcall.ui.worker --mode reread"
        + (f" --target {target}" if target > 0 else ""),
        language="bash",
    )
    st.caption("推荐：长时间重读使用 CLI，Web 面板用于预览和监控。")
