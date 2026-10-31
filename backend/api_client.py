import json
import logging
import os
import time
import requests
import calendar
import streamlit as st

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# 获取当前模块的 logger
logger = logging.getLogger(__name__)

# API_CACHE_FILE = Path(__file__).with_name(f"copilot_usage_cache_{USERNAME}.json")
CACHE_TTL = timedelta(minutes=15)
"""缓存时间间隔，15分钟"""

def get_cache_file(username: str) -> Path:
    """返回缓存文件路径，按用户名区分"""
    return Path(__file__).with_name(f"copilot_usage_cache_{username}.json")


def load_cached_data(username: str):
    """从缓存文件中加载数据"""
    API_CACHE_FILE = get_cache_file(username)

    try:
        cached = json.loads(API_CACHE_FILE.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(cached["cached_at"])
        if datetime.now(timezone.utc) - cached_at >= CACHE_TTL:
            return None
        return cached["data"], cached["usage_data"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def fetch_api_data(username: str, token: str):
    """获取 API 数据并缓存"""
    try:
        API_CACHE_FILE = get_cache_file(username)

        Headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token.strip()}",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        # `quota_snapshots` 是 Copilot UI 使用的数据源。
        # logger.info("发起请求：GET https://api.github.com/copilot_internal/user")
        response = requests.get(
            "https://api.github.com/copilot_internal/user",
            headers=Headers,
            timeout=30,
        )
        if not response.ok:
            response.raise_for_status()
        data = response.json()

        # 账单接口提供按模型拆分的实际 AI Credits 消耗。
        usage_url = f"https://api.github.com/users/{username}/settings/billing/ai_credit/usage"
        # logger.info(f"发起请求：GET {usage_url}")
        usage_response = requests.get(
            usage_url,
            headers=Headers,
            params={"year": date.today().year, "month": date.today().month},
            timeout=30,
        )
        if not usage_response.ok:
            usage_response.raise_for_status()
        usage_data = usage_response.json()

        API_CACHE_FILE.write_text(
            json.dumps(
                {
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "data": data,
                    "usage_data": usage_data,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        logger.info("数据拉取成功，并已更新本地 JSON 缓存")
        return data, usage_data
    except requests.exceptions.RequestException:
        logger.exception("GitHub API 网络请求异常")
        raise
    except Exception:
        logger.exception("处理 GitHub API 数据时发生异常")
        raise


def get_copilot_data(force_refresh=False,username:str="",token:str=""):
    """获取配额和明细数据，默认优先使用 15 分钟缓存。"""
    
    cached_data = None if force_refresh else load_cached_data(username)
    if cached_data is None:
        logger.info(f"数据刷新：正在从 GitHub 获取最新数据")
        return fetch_api_data(username, token)
    else:
        logger.info("数据刷新：使用本地缓存数据")
        return cached_data


def fetch_daily_usage_backfill(
    username: str,
    year: int,
    month: int,
    token: str,
    days: list[int] | None = None,
):
    """
    回填指定月份的历史数据。
    返回格式 为 { "YYYY-MM-DD": {"total": float, "models": {model_name: float}} }
    """
    today = date.today()
    daily_results = {}
    Headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token.strip()}",
                "X-GitHub-Api-Version": "2026-03-10",
            }
    # ================= 严谨的天数判断逻辑 =================
    # 1. 获取该月准确的天数 (例如 28, 29, 30, 31)
    _ , days_in_month = calendar.monthrange(year, month)

    if (today.year == year and today.month == month):
        # 2. 如果是当前月：只回填到昨天（今天由正常流程负责）
        last_day = today.day - 1
    elif (year < today.year) or (year == today.year and month < today.month):
        # 3. 如果是过去的月份：回填该月的完整天数
        last_day = days_in_month
    else:
        # 4. 如果是未来月份：直接返回空（禁止回填未来）
        logger.error("不能回填未来的数据。")
        return {}

    requested_days = (
        list(range(1, last_day + 1))
        if days is None
        else sorted({day for day in days if 1 <= day <= last_day})
    )
    logger.info(
        "开始回填历史数据：%s 天，范围：%s",
        len(requested_days),
        ", ".join(f"{year}-{month:02d}-{day:02d}" for day in requested_days),
    )

    for day in requested_days:
        # 构建请求 URL 和参数
        url = f"https://api.github.com/users/{username}/settings/billing/ai_credit/usage"
        params = {"year": year, "month": month, "day": day}
        try:
            response = requests.get(url, headers=Headers, params=params, timeout=30)
            if not response.ok:
                logger.error(f"请求失败: {response.status_code} - {response.text}")
                continue
            day_data = response.json()
            items = day_data.get("usageItems", [])
            daily_total_usage = 0.0
            daily_model_usage = {}

            for item in items:
                if item.get("product", "").lower() not in ["copilot", "github copilot"]:
                    continue  # 只统计 Copilot 产品的使用量
                model = item.get("model") or "unknown"
                quantity = float(item.get("grossQuantity", 0))
                daily_total_usage += quantity
                daily_model_usage[model] = daily_model_usage.get(model, 0.0) + quantity

            date_str = f"{year}-{month:02d}-{day:02d}"
            daily_results[date_str] = {
                "total": daily_total_usage,
                "models": daily_model_usage,
            }

            time.sleep(0.5)  # 避免请求过快
        except Exception as e:
            logger.error(f"回填 {year}-{month:02d}-{day:02d} 数据时出错: {e}")
            continue
    logger.info(f"历史数据回填完成，共回填 {len(daily_results)} 天的数据。")

    return daily_results
                    
