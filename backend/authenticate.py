import streamlit as st
import hmac


def get_credentials():
    """直接复用现有的 GITHUB_USERNAME 和 GITHUB_TOKEN 作为登录凭证"""
    # 从 Secrets 中读取你现有的配置
    valid_user = st.secrets.get("GITHUB_USERNAME", "")
    valid_token = st.secrets.get("GITHUB_TOKEN", "")
    return valid_user, valid_token


def verify_credentials(username: str, token: str) -> bool:
    """安全比对用户输入的凭证与配置"""
    valid_user, valid_token = get_credentials()
    if not valid_user or not valid_token:
        return False
        
    # 使用 hmac.compare_digest 防止时序攻击
    user_ok = hmac.compare_digest(username.strip(), valid_user)
    token_ok = hmac.compare_digest(token.strip(), valid_token)
    return user_ok and token_ok

def is_authenticated() -> bool:
    """检查当前会话是否已认证"""
    return st.session_state.get("authenticated", False)

def render_login_page():
    """渲染登录界面，验证通过后设置会话状态并刷新页面"""
    st.title("🔐 访问认证")
    st.markdown("请使用您的 **GitHub 用户名** 和 **Personal Access Token** 登录。")

    with st.form("login_form"):
        username = st.text_input("用户名", placeholder="GitHub Username")
        token = st.text_input("访问令牌", type="password", placeholder="GitHub Token (ghp_...)")
        submitted = st.form_submit_button("登录", use_container_width=True)

        if submitted:
            if verify_credentials(username, token):
                st.session_state["authenticated"] = True
                st.session_state["username"] = username.strip()
                st.success("登录成功，正在跳转...")
                st.rerun()
            else:
                st.error("用户名或访问令牌错误，请重试。")
    st.stop()  # 未登录时阻止后续代码执行


def logout():
    """清除会话状态，退出登录"""
    st.session_state.pop("authenticated", None)
    st.session_state.pop("username", None)
    st.rerun()
    