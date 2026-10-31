import logging

import streamlit as st

import authenticate
import database
from dashboard import render_dashboard
from logger_setup import setup_logger


setup_logger()
logger = logging.getLogger(__name__)

# Streamlit 页面配置
st.set_page_config(page_title="Copilot 额度监控", page_icon="🤖", layout="wide")

# 设置门禁
if not authenticate.is_authenticated():
    authenticate.render_login_page()
    st.stop()

current_user = st.session_state.get("username")
current_token = st.session_state.get("token")

if not current_user or not current_token:
    st.session_state.clear()
    st.rerun()

with st.sidebar:
    st.write(f"👤 当前用户：**{current_user}**")
    if st.button("🚪 退出登录"):
        authenticate.logout()

# 初始化数据库并渲染仪表盘
database.initialize_database(current_user)
render_dashboard(current_user, current_token)
