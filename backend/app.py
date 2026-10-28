from datetime import datetime
import logging
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go  # 👈 新增：用于画平滑面积图

import authenticate
from logger_setup import setup_logger
import database
from api_client import fetch_daily_usage_backfill, get_copilot_data
from core_logic import (
    aggregate_model_usage,
    build_desktop_payload,
    calculate_quota_status,
)

# 设置全局日志
setup_logger()
logger = logging.getLogger(__name__)

# 设置页面宽屏模式
st.set_page_config(page_title="Copilot 额度监控", page_icon="🤖", layout="wide")
# ================= 访问认证门禁 =================
if not authenticate.is_authenticated():
    authenticate.render_login_page()
    st.stop()  # 确保未登录时直接停止

# 获取当前用户信息 (使用安全的 get 方法)
current_user = st.session_state.get("username")
current_token = st.session_state.get("token")

# 再次兜底检查，防止因为某些意外情况穿透
if not current_user or not current_token:
    st.session_state.clear()
    st.rerun()

# 侧边栏退出
with st.sidebar:
    st.write(f"👤 当前用户：**{current_user}**")
    if st.button("🚪 退出登录"):
        authenticate.logout()

# 初始化数据库
database.initialize_database(current_user)

# ================= 状态变量初始化 =================
data_source = "live"  # 默认数据源为 "live"（实时数据） "offline"（离线缓存数据）
error_message = ""
update_time_str = "未知" 

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
}

/* 确保所有图表和表格占满容器宽度，不溢出 */
.stPlotlyChart, .stDataFrame, .stTable {
    width: 100% !important;
    max-width: 100vw;
}

</style>
""", unsafe_allow_html=True)
st.title("🤖 GitHub Copilot 额度监控")

# ================= 历史查询缓存 =================
# Streamlit 每次交互都会 rerun 整个脚本；这里把“按月历史查询”缓存 5 分钟，
# 避免每次点击控件都重新打 Supabase。回填/落库成功后会显式 clear。
HISTORY_CACHE_TTL = 300


@st.cache_data(ttl=HISTORY_CACHE_TTL, show_spinner=False)
def load_total_usage_history(year: int, month: int, username: str):
    return database.get_total_usage_history(year, month, username)


@st.cache_data(ttl=HISTORY_CACHE_TTL, show_spinner=False)
def load_model_usage_history(year: int, month: int, username: str):
    return database.get_model_usage_history(year, month, username)


def clear_history_cache():
    """历史数据写入后（落库/回填）清掉缓存，让图表读到最新数据。"""
    load_total_usage_history.clear()
    load_model_usage_history.clear()


# ================= 操作按钮区 =================
# 在获取数据之前
col1, col_refresh , col_backfill= st.columns([6, 2, 2])
with col_refresh:
    force_refresh = st.button("🔄 刷新数据", use_container_width=True)

# 回填历史数据按钮：只记录“意图”，具体执行放到下方独立流程
with col_backfill:
    do_backfill = st.button("📥 回填本月历史数据", use_container_width=True)

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
    else:
        with st.spinner("正在回填历史数据，大约需要 30 秒..."):
            try:
                backfill_data = fetch_daily_usage_backfill(
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
                logger.exception("回填历史数据失败。")
                st.session_state[backfill_result_key] = {
                    "status": "empty",
                    "message": "回填历史数据时发生错误，请稍后重试。",
                }
    # 回填结束，统一 rerun：让结果提示与刷新后的图表在同一次干净渲染中出现
    st.rerun()

# ================= 数据获取 =================
# 获取数据；手动刷新时明确绕过 15 分钟缓存。
with st.spinner("正在获取最新数据..."):
    try:
        api_data, usage_data = get_copilot_data(force_refresh=force_refresh, username=current_user, token=current_token)
        quota_info = calculate_quota_status(api_data)
        models, total_gross = aggregate_model_usage(usage_data)
        desktop_payload = build_desktop_payload(quota_info, models, total_gross)
        current_models_usage = {model: stats["gross_quantity"] for model, stats in models.items()}
        update_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.exception("页面渲染时发生严重错误，已降级为离线模式。")
        data_source = "offline"
        error_message = str(e)

        # 如果无法获取实时数据，则尝试从数据库中获取最近的历史数据
        latest_total_usage = database.get_latest_total_usage(current_user)

        if not latest_total_usage:
            st.error(f"网络请求失败，且本地无任何历史缓存数据可用。\n错误信息：{error_message}")
            st.stop()
        logger.info("最近的历史缓存数据已成功加载，页面将使用离线模式显示。")

        # 如果有历史数据，则使用最近的一条记录
        record_date, included_credits, used_credits, remaining_credits = latest_total_usage
        update_time_str = f"历史缓存数据 (日期: {record_date})"
        latest_models_date = database.get_latest_model_usage(current_user, record_date)

        # 伪造一个基本的 quota_info 字典，确保后续代码可以正常运行
        quota_info = {
            "account_status": "未知账户类型",
            "included_credits": included_credits,
            "remaining_credits": remaining_credits,
            "used_credits": used_credits,
            "plan": "unknown",
            "remaining_time_text": "未知",
            "reset_time_text": "未知"
        }

        models = {}
        total_gross = sum(m[1] for m in latest_models_date) if latest_models_date else 0
        for m_name, m_used in (latest_models_date or []):
            models[m_name] = {
                "gross_quantity": m_used,
                "net_quantity": m_used,
                "gross_amount": 0.0,
                "net_amount": 0.0,
                "percentage": (m_used / total_gross * 100) if total_gross > 0 else 0
            }
            
        # 伪造 desktop_payload
        desktop_payload = {
            "status": "offline", 
            "message": "数据来源于历史缓存", 
                        "quota": quota_info,
            "models": models
        }
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
        "模型名称": [item["模型名称"] for item in table_data],
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
            
            # 使用 Plotly 平滑面积图
            fig_total = go.Figure()
            fig_total.add_trace(go.Scatter(
                x=df_total["日期"], y=df_total["已用额度(Total)"],
                mode='lines+markers',
                line=dict(color='#4A90E2', width=3, shape='spline'),
                fill='tozeroy', fillcolor='rgba(74, 144, 226, 0.1)',
                marker=dict(size=6)
            ))
            fig_total.update_layout(
                margin=dict(l=10, r=10, t=10, b=10), height=350,
                xaxis=dict(tickangle=-45, showgrid=False),
                yaxis=dict(showgrid=True, gridcolor='#f0f2f6'),
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig_total, use_container_width=True)
        else:
            logger.info("当前月份暂无整体消耗历史数据，跳过整体趋势图渲染。")

    with col_model:
        st.markdown("**各模型消耗趋势**")
        model_usage_history = load_model_usage_history(now.year, now.month, current_user)
        if model_usage_history:
            df_model = pd.DataFrame(model_usage_history, columns=["日期", "模型名称", "已用额度(Model)"])
            df_model_pivot = df_model.pivot(index="日期", columns="模型名称", values="已用额度(Model)").fillna(0).sort_index()
            st.line_chart(df_model_pivot, use_container_width=True)
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
        st.plotly_chart(fig_bar, use_container_width=True)

        # 渲染表格
        html_table = df.to_html(index=False, classes='custom-table', border=0)
        css = """
        <style>
        .custom-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        .custom-table th { background-color: #f8f9fa; color: #333; font-weight: bold; padding: 10px; text-align: center !important; border-bottom: 2px solid #ddd; border-top: 1px solid #ddd; }
        .custom-table td { padding: 10px; text-align: center !important; border-bottom: 1px solid #ddd; }
        .custom-table tr:hover { background-color: #f5f5f5; }
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
        st.markdown(html_table, unsafe_allow_html=True)

# --- Tab 3: 环形图 ---
with tab3:
    if not models:
        st.info("当前月份暂无消耗记录。")
    else:
        # 为了让图表不至于太宽，可以放在一个居中的列里
        st.markdown("**各模型消耗占比**")
        col_pie_left, col_pie_center, col_pie_right = st.columns([1, 2, 1])
        
        with col_pie_center:
            fig_pie = px.pie(
                pie_chart_data, values='消耗占比', names='模型名称', hole=0.6,
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_pie.update_traces(textinfo='percent', textposition='inside', hoverinfo='label+value')
            fig_pie.update_layout(
                margin=dict(t=20, b=20, l=20, r=20), height=400, showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    # streamlit run backend/app.py