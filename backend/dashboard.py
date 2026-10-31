from datetime import datetime
import logging

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import database
from data_service import (
    DashboardDataUnavailable,
    clear_history_cache,
    fetch_backfill_data,
    load_dashboard_data,
    load_model_usage_history,
    load_total_usage_history,
)

logger = logging.getLogger(__name__)

def render_dashboard(current_user: str, current_token: str) -> None:
    # ================= 移动端适配 CSS =================
    # 修复了移动端顶部工具栏遮挡标题的问题

    # 修复移动端水平溢出与标题过大问题
    st.markdown("""
    <style>
    /* 全局防横向溢出 */
    [data-testid="stAppViewContainer"] {
        overflow-x: hidden;
    }

    /* 卡片化容器 (新增：给所有内容块加圆角、白底和微阴影) */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #ffffff;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.03);
        border: 1px solid #f0f2f6;
    }

    /* 优化原生标题边距 */
    h2, h3 {
        margin-top: 0.5rem !important;
        margin-bottom: 1rem !important;
    }

    /* 移动端适配 (屏幕宽度 < 768px) */
    @media (max-width: 768px) {
        .stMainBlockContainer {
            padding-top: 4.5rem !important; 
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-bottom: 1rem !important;
        }
        h1 {
            font-size: 1.4rem !important;
            line-height: 1.3 !important;
            margin-top: 0 !important; 
            margin-bottom: 1rem !important;
            word-break: break-word;
        }
        h2 { font-size: 1.1rem !important; }
        h3 { font-size: 1rem !important; }

        /* 趋势图在手机上纵向排列，避免两个图表被压缩。 */
        [data-testid="stTabs"] [data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
            gap: 1rem !important;
        }
    }

    /* 确保所有图表和表格占满容器宽度，不溢出 */
    .stPlotlyChart, .stDataFrame, .stTable {
        width: 100% !important;
        max-width: 100vw;
    }

    </style>
    """, unsafe_allow_html=True)
    st.title("🤖 GitHub Copilot 额度监控")


    # ================= 操作按钮区 =================
    # 在获取数据之前
    col1, col_refresh , col_backfill= st.columns([6, 2, 2])
    with col_refresh:
        force_refresh = st.button("🔄 刷新数据", width="stretch")

    # 回填历史数据按钮：只记录“意图”，具体执行放到下方独立流程
    with col_backfill:
        do_backfill = st.button("📥 回填本月历史数据", width="stretch")

    # ================= 回填历史数据（独立流程） =================
    # 通过 session_state 传递回填结果，回填完成后统一 rerun 一次，
    # 避免与下方“正在获取最新数据”的 spinner 交叉，也不再 sleep 硬等。
    backfill_result_key = "backfill_result"

    # 1) 展示上一次回填的结果，展示后立即清空，避免重复弹出
    if backfill_result_key in st.session_state:
        result = st.session_state.pop(backfill_result_key)
        if result["status"] == "success":
            st.success(result["message"])
        elif result["status"] == "skipped":
            st.toast(result["message"], icon="⚠️")
        else:
            st.warning(result["message"])

    # 2) 用户点击回填，执行回填
    if do_backfill:
        now = datetime.now()
        # 走缓存，避免每次点击都查库
        existing_history = load_total_usage_history(now.year, now.month, current_user)
        if existing_history:
            first_record_date = existing_history[0][0]
            st.session_state[backfill_result_key] = {
                "status": "skipped",
                "message": (
                    f"当前用户本月已有历史数据（最早记录：{first_record_date}），"
                    "为避免覆盖现有数据，本次未执行回填。"
                ),
            }
            logger.info("回填历史数据被跳过：本月已有历史数据，避免覆盖。")
        else:
            with st.spinner("正在回填历史数据，大约需要 30 秒..."):
                try:
                    backfill_data = fetch_backfill_data(
                        current_user, now.year, now.month, current_token
                    )
                    if backfill_data:
                        database.backfill_history(backfill_data, current_user)
                        # 回填后清缓存，确保 rerun 时图表读到新数据
                        clear_history_cache()
                        st.session_state[backfill_result_key] = {
                            "status": "success",
                            "message": f"✅ 成功回填 {len(backfill_data)} 天的历史数据！",
                        }
                    else:
                        st.session_state[backfill_result_key] = {
                            "status": "empty",
                            "message": "暂无数据或回填失败。",
                        }
                except Exception:
                    logger.exception("回填历史数据发生异常。")
                    st.session_state[backfill_result_key] = {
                        "status": "empty",
                        "message": "回填历史数据时发生错误，请稍后重试。",
                    }
        # 回填结束，统一 rerun：让结果提示与刷新后的图表在同一次干净渲染中出现
        st.rerun()

    # ================= 数据获取 =================
    # 获取数据；手动刷新时明确绕过 15 分钟缓存。
    data_source = "live"
    error_message = ""
    with st.spinner("正在获取最新数据..."):
        try:
            dashboard_data = load_dashboard_data(
                current_user, current_token, force_refresh
            )
            quota_info = dashboard_data.quota_info
            models = dashboard_data.models
            total_gross = dashboard_data.total_gross
            desktop_payload = dashboard_data.desktop_payload
            current_models_usage = dashboard_data.current_models_usage
            update_time_str = dashboard_data.update_time_str
            data_source = dashboard_data.data_source
            error_message = dashboard_data.error_message
        except DashboardDataUnavailable as error:
            st.error(
                "网络请求失败，且本地无任何历史缓存数据可用。\n"
                f"错误信息：{error}"
            )
            logger.error(f"数据获取失败，且无历史缓存可用：{error}")
            st.stop()
        else:
            # 防重复落库：Streamlit 每次交互都会 rerun，这里用 session_state 记录
            # “本次快照是否已经写过”，同一天内相同数据的重复渲染不再重复打 Supabase。
            snapshot_key = f"snapshot_saved_{current_user}"
            snapshot_id = f"{update_time_str}|{quota_info['included_credits']}"
            if st.session_state.get(snapshot_key) == snapshot_id:
                logger.info("同一份数据快照本会话已保存过，跳过重复写入。")
            else:
                try:
                    database.save_daily_usage(
                        included_credits=quota_info['included_credits'],
                        used_credits=quota_info['included_credits'] - quota_info['remaining_credits'],
                        remaining_credits=quota_info['remaining_credits'],
                        model_usage=current_models_usage,
                        username=current_user,
                    )
                    st.session_state[snapshot_key] = snapshot_id
                    # 新快照写入后，历史缓存已过期，清掉以让趋势图读到今天的数据
                    clear_history_cache()
                    logger.info("实时数据已成功保存到数据库。")
                except Exception as e:
                    logger.exception("实时数据已获取，但保存到数据库失败。")
                    st.toast(f"实时数据已获取，但数据库保存失败：{e}", icon="⚠️")

    # ================= 顶部状态与指标提示 =================
    if data_source == "offline":
        st.error(f"🚨 **网络连接失败，当前显示的是历史缓存数据！**\n\n*更新时间: {update_time_str}* \n\n*错误信息: {error_message}*")
    else:
        st.success(f"✅ **数据已实时更新** (更新时间: {update_time_str})")

    # 顶部关键指标展示（使用列布局）
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label="当前订阅计划",
            value=quota_info['plan'].upper()
        )
    with col2:
        st.metric(
            label="订阅类型",
            value=quota_info.get("account_status", "未知账户类型")
        )
    with col3:
        st.metric(
            label="剩余额度/总额度",
            value=f"{quota_info['remaining_credits']}/{quota_info['included_credits']}"
        )

    # 进度条展示
    st.subheader("额度使用情况")
    used_credits = quota_info['included_credits'] - quota_info['remaining_credits']
    progress = used_credits / quota_info['included_credits'] if quota_info['included_credits'] > 0 else 0

    # 根据使用率改变颜色
    if progress < 0.7:
        st.progress(progress, text=f"已使用 {used_credits} / {quota_info['included_credits']} Credits")
    elif progress < 0.9:
        st.progress(progress, text=f"⚠️ 已使用 {used_credits} / {quota_info['included_credits']} Credits，请注意")
    else:
        st.progress(progress, text=f"🚨 已使用 {used_credits} / {quota_info['included_credits']} Credits，即将超额！")

    st.info(f"距离额度重置还剩：**{quota_info['remaining_time_text']}** (重置日期: {quota_info['reset_time_text']})")

    st.divider()

    # ================= 图表与明细展示 =================
    # st.subheader("📈 额度消耗趋势")
    now = datetime.now()

    # 预处理表格和饼图的数据（提取到 tabs 外面，避免重复计算）
    if not models:
        logger.info("当前月份暂无消耗记录，跳过图表和表格渲染。")
    else:
        table_data = []
        for model_name, stats in models.items():
            table_data.append({
                "模型名称": model_name,
                "消耗数量 (Gross)": round(stats["gross_quantity"], 2),
                "消耗占比": f"{stats['percentage']:.2f}%",
                "产生费用 ($)": round(stats["gross_amount"], 4)
            })
        table_data = sorted(table_data, key=lambda x: x["消耗数量 (Gross)"], reverse=True)
        df = pd.DataFrame(table_data)

        pie_chart_data = pd.DataFrame({
            "模型名称": [
                item["模型名称"]
                if len(item["模型名称"]) <= 32
                else f"{item['模型名称'][:29]}..."
                for item in table_data
            ],
            "完整模型名称": [item["模型名称"] for item in table_data],
            "消耗占比": [float(item["消耗占比"].strip('%')) for item in table_data]
        })

    # 使用 Tabs 折叠杂乱的图表 (新增：让界面更干净)
    tab1, tab2, tab3 = st.tabs(["📈 消耗趋势图", "📊 模型明细表", "🍩 消耗占比图"])

    # --- Tab 1: 趋势图 ---
    with tab1:
        if not models:
            st.info("当前月份暂无消耗记录。")
        col_total, col_model = st.columns(2)
        
        with col_total:
            total_usage_history = load_total_usage_history(now.year, now.month, current_user)
            if total_usage_history:
                df_total = pd.DataFrame(total_usage_history, columns=["日期", "已用额度(Total)"])
                df_total["日期"] = pd.to_datetime(df_total["日期"])
                
                # 手动生成每 2 天的日期刻度列表
                if not df_total.empty:
                    tickvals = pd.date_range(
                        start=df_total["日期"].min(), 
                        end=df_total["日期"].max(), 
                        freq='2D'
                    ).tolist()
                else:
                    tickvals = []

                # ================= 修改这里：改回折线图 =================
                fig_total = go.Figure()
                fig_total.add_trace(go.Scatter(
                    x=df_total["日期"], y=df_total["已用额度(Total)"],
                    mode='lines+markers',
                    # 去掉了 shape='spline'，变为直线
                    line=dict(color='#4A90E2', width=3), 
                    # 去掉了 fill='tozeroy' 和 fillcolor，不再填充面积
                    marker=dict(size=6)
                ))
                # ========================================================
                
                fig_total.update_layout(
                    # 因为日期竖直显示，需要把底部边距 b 调大，防止日期文字被切掉
                    margin=dict(l=10, r=10, t=10, b=80), 
                    height=380,
                    xaxis=dict(
                        type="date",
                        tickformat="%Y-%m-%d",
                        tickvals=tickvals,
                        tickangle=-90,
                        showgrid=False,
                        tickfont=dict(size=11)
                    ),
                    yaxis=dict(showgrid=True, gridcolor='#f0f2f6'),
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig_total, width="stretch")
            else:
                logger.info("当前月份暂无整体消耗历史数据，跳过整体趋势图渲染。")

        with col_model:
            st.markdown("**各模型消耗趋势**")
            model_usage_history = load_model_usage_history(now.year, now.month, current_user)
            if model_usage_history:
                df_model = pd.DataFrame(model_usage_history, columns=["日期", "模型名称", "已用额度(Model)"])
                df_model_pivot = df_model.pivot(index="日期", columns="模型名称", values="已用额度(Model)").fillna(0).sort_index()
                st.line_chart(df_model_pivot, width="stretch")
            else:
                logger.info("当前月份暂无模型消耗历史数据，跳过模型趋势图渲染。")

    # --- Tab 2: 表格与柱状图 ---
    with tab2:
        if not models:
            st.info("当前月份暂无消耗记录。")
        else:
            # 绘制横向柱状图
            st.markdown("**各模型消耗数量 (Gross)**")
            df_chart = df.sort_values(by="消耗数量 (Gross)", ascending=True)
            fig_bar = px.bar(
                df_chart, x="消耗数量 (Gross)", y="模型名称", orientation='h',
                text="消耗数量 (Gross)", color="模型名称",
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_bar.update_layout(
                showlegend=False, margin=dict(l=0, r=0, t=10, b=0), height=280,
                xaxis=dict(showgrid=True, gridcolor='#f0f2f6'), yaxis=dict(title="")
            )
            fig_bar.update_traces(texttemplate='%{text:.2f}', textposition='outside')
            st.plotly_chart(fig_bar, width="stretch")

            # 渲染表格
            html_table = df.to_html(index=False, classes='custom-table', border=0)
            css = """
            <style>
            .custom-table { width: 100%; max-width: 100%; table-layout: fixed; border-collapse: collapse; margin-top: 10px; }
            .custom-table th { background-color: #f8f9fa; color: #333; font-weight: bold; padding: 10px; text-align: center !important; border-bottom: 2px solid #ddd; border-top: 1px solid #ddd; }
            .custom-table td { padding: 10px; text-align: center !important; border-bottom: 1px solid #ddd; }
            .custom-table th:first-child, .custom-table td:first-child { width: 40%; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
            .custom-table tr:hover,
            .custom-table tr:active,
            .custom-table tr:focus-within {
                background-color: #173b63 !important;
            }
            .custom-table tr:hover td,
            .custom-table tr:active td,
            .custom-table tr:focus-within td {
                color: inherit !important;
            }
            .custom-table ::selection { background-color: #173b63; color: inherit; }
            </style>
            """
            st.markdown(css, unsafe_allow_html=True)
            st.markdown(html_table, unsafe_allow_html=True)

    # --- Tab 3: 环形图 ---
    with tab3:
        if not models:
            st.info("当前月份暂无消耗记录。")
        else:
            st.markdown("**各模型消耗占比**")
            fig_pie = px.pie(
                pie_chart_data, values='消耗占比', names='模型名称', hole=0.6,
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_pie.update_traces(
                customdata=pie_chart_data[["完整模型名称"]],
                hovertemplate="%{customdata[0]}<br>消耗占比：%{value:.2f}%<extra></extra>",
                textinfo='percent',
                textposition='inside',
                hoverinfo='label+value',
            )
            fig_pie.update_layout(
                margin=dict(t=20, b=120, l=20, r=20),
                height=500,
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.18,
                    xanchor="center",
                    x=0.5,
                ),
            )
            st.plotly_chart(fig_pie, width="stretch")

        # streamlit run backend/app.py
