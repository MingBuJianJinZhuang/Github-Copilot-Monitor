from collections import defaultdict
from datetime import datetime, timezone

def calculate_quota_status(api_data: dict):
    """解析配额快照，计算剩余时间等信息"""
    quota_snapshots = api_data.get("quota_snapshots")
    if not isinstance(quota_snapshots, dict):
        raise ValueError("copilot_internal/user 响应中缺少有效的 quota_snapshots")

    premium_quota = quota_snapshots.get("premium_interactions", {})
    included_credits = premium_quota.get("entitlement", 0)  # 总额度
    remaining_credits = premium_quota.get("remaining", 0)    # 剩余额度
    reset_date = api_data.get("quota_reset_date")            # 重置日期

    now_utc = datetime.now(timezone.utc)
    reset_time_text = "未知"
    if reset_date:
        reset_datetime = datetime.fromisoformat(reset_date.replace("Z", "+00:00"))
        if reset_datetime.tzinfo is None:
            reset_datetime = reset_datetime.replace(tzinfo=timezone.utc)
        reset_time_text = reset_datetime.strftime("%Y 年 %m 月 %d 日")
        remaining_time = reset_datetime - now_utc
        if remaining_time.total_seconds() > 0:
            days_left, remainder = divmod(int(remaining_time.total_seconds()), 86400)
            hours_left, remainder = divmod(remainder, 3600)
            minutes_left = remainder // 60
            remaining_time_text = (
                f"{days_left} 天 {hours_left} 小时 {minutes_left} 分钟"
            )
        else:
            remaining_time_text = "已到期"
    else:
        remaining_time_text = "未知"

    return {
        "plan": api_data.get('copilot_plan') or api_data.get('access_type_sku', '未知'),
        "all_quotas": quota_snapshots,
        "included_credits": included_credits,
        "remaining_credits": remaining_credits,
        "reset_time_text": reset_time_text,
        "remaining_time_text": remaining_time_text,
        "current_date_str": now_utc.strftime('%Y 年 %m 月 %d 日')
    }


def aggregate_model_usage(usage_data: dict):
    models = defaultdict(
    lambda: {
        "gross_quantity": 0.0,
        "net_quantity": 0.0,
        "gross_amount": 0.0,
        "net_amount": 0.0,
    }
    )
    field_mapping = {
        "gross_quantity": "grossQuantity",
        "net_quantity": "netQuantity",
        "gross_amount": "grossAmount",
        "net_amount": "netAmount",
    }

    for item in usage_data.get("usageItems", []):
            if item.get("product", "").lower() not in {
                "copilot",
                "copilot ai credits",
            }:
                continue
    
            model = item.get("model") or "Unknown model"
            for field, response_field in field_mapping.items():
                value = item.get(response_field)
                models[model][field] += float(value or 0)

    total_gross_quantity = sum(stats["gross_quantity"] for stats in models.values())
    total_net_quantity = sum(stats["net_quantity"] for stats in models.values())
    result_models = {}
    for model, stats in models.items():
        percentage = (
            stats["gross_quantity"] / total_gross_quantity * 100
            if total_gross_quantity
            else 0
        )
        net_percentage = (
            stats["net_quantity"] / total_net_quantity * 100
            if total_net_quantity
            else 0
        )
        result_models[model] = {
            **stats,
            "percentage": percentage,
            "net_percentage": net_percentage,
        }

    return result_models , total_gross_quantity

# 建立一个稳定的、可序列化为 JSON 的响应，用于桌面客户端
def build_desktop_payload(quota_info: dict, models: dict, total_gross: float) -> dict:
    """Build a stable, JSON-serializable response for a desktop client."""
    included = quota_info["included_credits"]
    remaining = quota_info["remaining_credits"]
    used = max(included - remaining, 0)

    return {
        "schema_version": 1,
        "quota": {
            "plan": quota_info["plan"],
            "all_quotas": quota_info["all_quotas"],
            "included_credits": included,
            "remaining_credits": remaining,
            "used_credits": used,
            "used_percentage": round(used / included * 100, 2) if included else 0,
            "reset_date": quota_info["reset_time_text"],
            "remaining_time": quota_info["remaining_time_text"],
            "current_date": quota_info["current_date_str"],
        },
        "usage": {
            "total_gross_quantity": total_gross,
            "models": [
                {
                    "name": model,
                    **{
                        key: round(value, 6) if isinstance(value, float) else value
                        for key, value in stats.items()
                    },
                }
                for model, stats in sorted(
                    models.items(),
                    key=lambda item: item[1]["gross_quantity"],
                    reverse=True,
                )
            ],
        },
    }