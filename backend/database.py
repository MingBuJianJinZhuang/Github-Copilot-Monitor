import logging
from datetime import date
from typing import Any

import streamlit as st
from supabase import Client, create_client

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None


def _get_supabase_client() -> Client:
    """获取缓存的 Supabase 客户端。"""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    config = st.secrets

    def get_secret(name: str) -> Any:
        return config[name] if name in config else None

    supabase_config = get_secret("supabase")
    if not hasattr(supabase_config, "get"):
        supabase_config = {}

    supabase_url = (
        get_secret("SUPABASE_URL")
        or get_secret("supabase_url")
        or supabase_config.get("url")
    )
    supabase_key = (
        get_secret("SUPABASE_SERVICE_ROLE_KEY")
        or get_secret("SUPABASE_SERVICE_KEY")
        or get_secret("SUPABASE_KEY")
        or get_secret("SUPABASE_ANON_KEY")
        or get_secret("supabase_key")
        or supabase_config.get("key")
        or supabase_config.get("anon_key")
    )

    missing = []
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not supabase_key:
        missing.append("SUPABASE_KEY")
    if missing:
        raise RuntimeError(
            "Streamlit Secrets 中缺少 "
            f"{'、'.join(missing)}。请配置顶层同名键，或配置 [supabase] "
            "下的 url 和 key。"
        )

    _supabase_client = create_client(supabase_url, supabase_key)
    return _supabase_client


def _rows(response: Any) -> list[dict[str, Any]]:
    """提取 Supabase 查询结果。"""
    return response.data or []


def initialize_database(username: str):
    """检查 Supabase 连接是否可用。"""
    try:
        _get_supabase_client()
        logger.info("Supabase 数据库连接初始化完成，当前用户：%s", username)
    except Exception:
        logger.exception("Supabase 数据库连接初始化失败")
        raise


def save_daily_usage(
    included_credits: float,
    used_credits: float,
    remaining_credits: float,
    model_usage: dict,
    username: str,
):
    """保存当前用户当天的额度和模型用量快照。"""
    today_str = date.today().isoformat()
    client = _get_supabase_client()

    try:
        client.table("total_daily_usage").upsert(
            {
                "record_date": today_str,
                "username": username,
                "included_credits": included_credits,
                "used_credits": used_credits,
                "remaining_credits": remaining_credits,
            },
            on_conflict="record_date,username",
        ).execute()

        client.table("model_daily_usage").delete().eq(
            "record_date", today_str
        ).eq("username", username).execute()

        if model_usage:
            client.table("model_daily_usage").upsert(
                [
                    {
                        "record_date": today_str,
                        "username": username,
                        "model_name": model_name,
                        "used_credits": model_used,
                    }
                    for model_name, model_used in model_usage.items()
                ],
                on_conflict="record_date,username,model_name",
            ).execute()
        logger.info("Supabase 数据库保存成功：总额度和模型用量已更新")
    except Exception:
        logger.exception("保存当日用量到 Supabase 失败")
        raise


def get_total_usage_history(years: int, months: int, username: str):
    """获取当前用户的总额度历史记录。"""
    month_str = f"{years:04d}-{months:02d}"
    response = _get_supabase_client().table("total_daily_usage").select(
        "record_date,used_credits"
    ).eq("username", username).like(
        "record_date", f"{month_str}%"
    ).order("record_date").execute()
    return [
        (row["record_date"], row["used_credits"])
        for row in _rows(response)
    ]


def get_model_usage_history(years: int, months: int, username: str):
    """获取当前用户的模型用量历史记录。"""
    month_str = f"{years:04d}-{months:02d}"
    response = _get_supabase_client().table("model_daily_usage").select(
        "record_date,model_name,used_credits"
    ).eq("username", username).like(
        "record_date", f"{month_str}%"
    ).order("record_date").execute()
    return [
        (row["record_date"], row["model_name"], row["used_credits"])
        for row in _rows(response)
    ]


def get_latest_total_usage(username: str):
    """获取当前用户最新的总额度记录。"""
    response = _get_supabase_client().table("total_daily_usage").select(
        "record_date,included_credits,used_credits,remaining_credits"
    ).eq("username", username).order(
        "record_date", desc=True
    ).limit(1).execute()
    rows = _rows(response)
    if not rows:
        return None
    row = rows[0]
    return (
        row["record_date"],
        row["included_credits"],
        row["used_credits"],
        row["remaining_credits"],
    )


def get_latest_model_usage(username: str, target_date: str):
    """获取当前用户指定日期的模型用量。"""
    response = _get_supabase_client().table("model_daily_usage").select(
        "model_name,used_credits"
    ).eq("username", username).eq(
        "record_date", target_date
    ).execute()
    return [
        (row["model_name"], row["used_credits"])
        for row in _rows(response)
    ]


def backfill_history(daily_results: dict, username: str):
    """回填当前用户按日累计的历史用量。"""
    cumulative_total = 0.0
    cumulative_models: dict[str, float] = {}
    client = _get_supabase_client()

    try:
        for date_str in sorted(daily_results):
            result = daily_results[date_str]
            cumulative_total += result["total"]
            for model, quantity in result["models"].items():
                cumulative_models[model] = (
                    cumulative_models.get(model, 0.0) + quantity
                )

            client.table("total_daily_usage").upsert(
                {
                    "record_date": date_str,
                    "username": username,
                    "included_credits": 0,
                    "used_credits": cumulative_total,
                    "remaining_credits": 0,
                },
                on_conflict="record_date,username",
            ).execute()

            if cumulative_models:
                client.table("model_daily_usage").upsert(
                    [
                        {
                            "record_date": date_str,
                            "username": username,
                            "model_name": model,
                            "used_credits": cumulative_quantity,
                        }
                        for model, cumulative_quantity in cumulative_models.items()
                    ],
                    on_conflict="record_date,username,model_name",
                ).execute()
    except Exception:
        logger.exception("回填历史数据到 Supabase 失败")
        raise
