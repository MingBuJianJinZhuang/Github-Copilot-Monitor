import logging
import streamlit as st
import hmac
import requests

# 获取当前模块的 logger
logger = logging.getLogger(__name__)

def verify_github_credentials(username: str, token: str) -> bool:
    """
    通过 GitHub API 验证 Token 是否有效，并检查其归属是否与输入的用户名一致
    """
    if not username or not token:
        return False,"请输入 GitHub 用户名和 Personal Access Token。"
        
    try:
        headers = {"Authorization": f"token {token.strip()}"}
        resp = requests.get("https://api.github.com/user", headers=headers, timeout=5)
        
        if resp.status_code == 200:
            actual_username = resp.json().get("login", "").lower()
            if actual_username == username.strip().lower():
                return True, "✅ 验证成功！"        
            else:
                
                return False, f"❌ 用户名不匹配！该 Token 实际属于 `{actual_username}`"
        elif resp.status_code == 401:
            return False, "❌ 认证失败：Token 无效、已过期或被撤销。"
        elif resp.status_code == 403:
            return False, "❌ 权限不足：该 Token 缺少 `read:user` 权限，或触发了 API 速率限制。"
        else:
            return False, f"❌ GitHub API 返回未知状态码: {resp.status_code}"
        
    except requests.exceptions.Timeout:
        logger.exception("GitHub 凭证验证超时")
        return False, "⏳ 连接 GitHub 超时，请检查网络后重试。"
    except Exception as e:
        logger.exception("GitHub 凭证验证发生异常")
        return False, f"❌ 验证过程中发生异常: {e}"

    
def is_authenticated() -> bool:
    """检查当前会话是否已认证，且必须包含完整的用户凭证"""
    is_auth = st.session_state.get("authenticated", False)
    has_user = "username" in st.session_state
    has_token = "token" in st.session_state
    # 必须三个条件同时满足才算有效登录
    return is_auth and has_user and has_token


def render_login_page():
    """渲染登录页面，要求用户输入 GitHub 用户名和 Personal Access Token"""
    st.title("👤 Github Copilot 额度监控")
    st.markdown("请使用您的 **GitHub 用户名** 和 **Personal Access Token** 登录。")
    st.info("💡 您的 Token 仅保存在当前会话内存中，不会被记录到任何服务器日志中。")

    remembered_username = st.query_params.get("remembered_username", "")
    remember_username = bool(remembered_username)

    remember_username = st.checkbox(
        "记住用户名",
        value=remember_username,
        help="只保存用户名，不会保存 Personal Access Token。",
    )

    with st.form("login_form"):
        username = st.text_input("GitHub 用户名", value=remembered_username)
        token = st.text_input("Personal Access Token", type="password", placeholder="ghp_...")
        submitted = st.form_submit_button("登录", use_container_width=True)

        if submitted:
            with st.spinner("正在验证凭证..."):
                is_valid, error_msg = verify_github_credentials(username, token)
                if is_valid:
                    normalized_username = username.strip().lower()
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = normalized_username
                    st.session_state["token"] = token.strip()
                    if remember_username:
                        st.query_params["remembered_username"] = normalized_username
                    else:
                        st.query_params.pop("remembered_username", None)
                    st.success("登录成功，正在跳转...")
                    logger.info("用户登录成功")
                    st.rerun()
                else:
                    st.error(error_msg)
                    logger.error(f"用户登录失败: {error_msg}")
    st.stop()


def logout():
    """登出并清除会话状态，包括 Token"""
    st.session_state.clear()
    logger.info("用户已登出，清除会话状态")
    st.rerun()
