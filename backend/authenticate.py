import streamlit as st
import hmac
import requests


def verify_github_credentials(username: str, token: str) -> bool:
    """
    通过 GitHub API 验证 Token 是否有效，并检查其归属是否与输入的用户名一致
    """
    if not username or not token:
        return False
        
    try:
        headers = {"Authorization": f"token {token.strip()}"}
        resp = requests.get("https://api.github.com/user", headers=headers, timeout=10)
        
        if resp.status_code == 200:
            # 获取该 Token 实际归属的用户名
            actual_username = resp.json().get("login", "").lower()
            # 忽略大小写进行比对
            return actual_username == username.strip().lower()
        return False
    except Exception:
        return False

    
def is_authenticated() -> bool:
    """检查当前会话是否已认证"""
    return st.session_state.get("authenticated", False)

def render_login_page():
    st.title("🔐 访问认证")
    st.markdown("请使用您的 **GitHub 用户名** 和 **Personal Access Token** 登录。")
    st.info("💡 您的 Token 仅保存在当前会话内存中，不会被记录到任何服务器日志中。")

    with st.form("login_form"):
        username = st.text_input("GitHub 用户名")
        token = st.text_input("Personal Access Token", type="password", placeholder="ghp_...")
        submitted = st.form_submit_button("登录", use_container_width=True)

        if submitted:
            with st.spinner("正在验证凭证..."):
                if verify_github_credentials(username, token):
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username.strip().lower()
                    st.session_state["token"] = token.strip()
                    st.success("登录成功，正在跳转...")
                    st.rerun()
                else:
                    st.error("用户名或 Token 无效，或两者不匹配，请重试。")
    st.stop()


def logout():
    """登出并清除会话状态，包括 Token"""
    st.session_state.clear()
    st.rerun()
