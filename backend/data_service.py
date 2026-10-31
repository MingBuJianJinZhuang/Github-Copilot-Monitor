from dataclasses import dataclass
from datetime import datetime
import logging

import streamlit as st

import database
from api_client import fetch_daily_usage_backfill, get_copilot_data
from core_logic import (
    aggregate_model_usage,
    build_desktop_payload,
    calculate_quota_status,
    empty_quota_info,
)

logger = logging.getLogger(__name__)

HISTORY_CACHE_TTL = 300


@dataclass
class DashboardData:
    quota_info: dict
    models: dict
    total_gross: float
    desktop_payload: dict
    current_models_usage: dict
    update_time_str: str
    data_source: str
    error_message: str = ""


class DashboardDataUnavailable(RuntimeError):
    """当无法获取到有效的 dashboard 数据时抛出此异常。"""


@st.cache_data(ttl=HISTORY_CACHE_TTL, show_spinner=False)
def load_total_usage_history(year: int, month: int, username: str):
    return database.get_total_usage_history(year, month, username)


@st.cache_data(ttl=HISTORY_CACHE_TTL, show_spinner=False)
def load_model_usage_history(year: int, month: int, username: str):
    return database.get_model_usage_history(year, month, username)


def clear_history_cache() -> None:
    """清除历史数据缓存，确保下次获取时从数据库重新拉取。"""
    load_total_usage_history.clear()
    load_model_usage_history.clear()


def fetch_backfill_data(
    username: str,
    year: int,
    month: int,
    token: str,
    days: list[int],
):
    return fetch_daily_usage_backfill(username, year, month, token, days)


def load_dashboard_data(
    current_user: str, current_token: str, force_refresh: bool
) -> DashboardData:
    """获取实时 dashboard 数据，若失败则尝试使用离线数据。"""
    try:
        api_data, usage_data = get_copilot_data(
            force_refresh=force_refresh,
            username=current_user,
            token=current_token,
        )
        quota_info = calculate_quota_status(api_data)
        models, total_gross = aggregate_model_usage(usage_data)
        return DashboardData(
            quota_info=quota_info,
            models=models,
            total_gross=total_gross,
            desktop_payload=build_desktop_payload(quota_info, models, total_gross),
            current_models_usage={
                model: stats["gross_quantity"] for model, stats in models.items()
            },
            update_time_str=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data_source="live",
        )
    except Exception as error:
        logger.exception("获取实时 dashboard 数据失败，尝试使用离线数据。")
        latest_total_usage = database.get_latest_total_usage(current_user)
        if not latest_total_usage:
            raise DashboardDataUnavailable(str(error)) from error

        record_date, included_credits, used_credits, remaining_credits = (
            latest_total_usage
        )
        latest_models_date = database.get_latest_model_usage(
            current_user, record_date
        )
        quota_info = empty_quota_info()
        quota_info.update(
            {
                "included_credits": included_credits,
                "remaining_credits": remaining_credits,
                "used_credits": used_credits,
                "plan": "unknown",
            }
        )

        models = {}
        total_gross = sum(item[1] for item in (latest_models_date or []))
        for model_name, model_used in latest_models_date or []:
            models[model_name] = {
                "gross_quantity": model_used,
                "net_quantity": model_used,
                "gross_amount": 0.0,
                "net_amount": 0.0,
                "percentage": (
                    model_used / total_gross * 100 if total_gross > 0 else 0
                ),
            }

        return DashboardData(
            quota_info=quota_info,
            models=models,
            total_gross=total_gross,
            desktop_payload={
                "status": "offline",
                "message": "数据来源于历史缓存",
                "quota": quota_info,
                "models": models,
            },
            current_models_usage={
                model: stats["gross_quantity"] for model, stats in models.items()
            },
            update_time_str=f"历史缓存数据 (日期: {record_date})",
            data_source="offline",
            error_message=str(error),
        )
