import streamlit as st
import hmac
import requests


def verify_github_credentials(username: str, token: str) -> bool:
    """
    通过 GitHub API 验证 Token 是否有效，并检查其归属是否与输入的用户名一致
    """
    if not username or not token:
        st.warning("⚠️ 请输入用户名和 Token")
        return False
        
    try:
        headers = {"Authorization": f"token {token.strip()}"}
        resp = requests.get("https://api.github.com/user", headers=headers, timeout=5)
        
        if resp.status_code == 200:
            actual_username = resp.json().get("login", "").lower()
            if actual_username == username.strip().lower():
                return True
            else:
                st.error(f"❌ 用户名不匹配！该 Token 实际属于 `{actual_username}`")
                return False
        elif resp.status_code == 401:
            st.error("❌ 认证失败：Token 无效、已过期或被撤销。")
            return False
        elif resp.status_code == 403:
            st.error("❌ 权限不足：该 Token 缺少 `read:user` 权限，或触发了 API 速率限制。")
            return False
        else:
            st.error(f"❌ GitHub API 返回未知状态码: {resp.status_code}")
            return False
        
    except requests.exceptions.Timeout:
        st.error("⏳ 连接 GitHub 超时，请检查网络后重试。")
        return False
    except Exception as e:
        st.error(f"❌ 发生网络异常: {e}")
        return False

    
def is_authenticated() -> bool:
    """检查当前会话是否已认证，且必须包含完整的用户凭证"""
    is_auth = st.session_state.get("authenticated", False)
    has_user = "username" in st.session_state
    has_token = "token" in st.session_state
    # 必须三个条件同时满足才算有效登录
    return is_auth and has_user and has_token

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
