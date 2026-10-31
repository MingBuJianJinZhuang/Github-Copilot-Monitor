from collections import defaultdict
from datetime import datetime, timezone
import logging

# 获取当前模块的 logger
logger = logging.getLogger(__name__)


def empty_quota_info() -> dict:
    """Return a quota payload with the complete set of expected fields."""
    now_utc = datetime.now(timezone.utc)
    return {
        "plan": "未知",
        "account_status": "未知账户类型",
        "all_quotas": {},
        "included_credits": 0,
        "remaining_credits": 0,
        "used_credits": 0,
        "reset_time_text": "未知",
        "remaining_time_text": "未知",
        "current_date_str": now_utc.strftime("%Y 年 %m 月 %d 日"),
    }


def calculate_quota_status(api_data: dict):
    """解析配额快照，计算剩余时间等信息"""
    quota_snapshots = api_data.get("quota_snapshots")
    access_type_sku = api_data.get("access_type_sku") # 获取访问类型 SKU
    plan = api_data.get("copilot_plan") or ""
    account_status = get_account_status_desc(plan, access_type_sku)
    is_free_account = account_status in {
        "Copilot 免费版",
        "开源作者专属 Pro",
        }
    quota_name = "quota_snapshots"

    if is_free_account:
        limited_user_quotas = api_data.get("limited_user_quotas")
        if limited_user_quotas:
            quota_snapshots = limited_user_quotas
            quota_name = "limited_user_quotas"
        else:
            logger.warning(
                "免费账户响应中缺少有效的 limited_user_quotas，"
                "改用 quota_snapshots 兼容计算额度"
            )
    quota = _get_quota_record(quota_snapshots, quota_name)
    included_credits = _get_quota_value(quota, "entitlement", "quota_limit", "limit")
    remaining_credits = _get_quota_value(quota, "remaining", "quota_remaining")
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

    logger.info("配额信息解析完成")

    plan = api_data.get("copilot_plan") or ""
    account_status = get_account_status_desc(plan, access_type_sku)

    return {
        **empty_quota_info(),
        "plan": plan or "未知",
        "account_status": account_status,
        "all_quotas": quota_snapshots,
        "included_credits": included_credits,
        "remaining_credits": remaining_credits,
        "used_credits": max(included_credits - remaining_credits, 0),
        "reset_time_text": reset_time_text,
        "remaining_time_text": remaining_time_text,
        "current_date_str": now_utc.strftime("%Y 年 %m 月 %d 日"),
    }


def _get_quota_record(quota_data: object, quota_name: str) -> dict:
    """从不同账户类型的额度响应中提取额度记录。"""
    if not isinstance(quota_data, dict):
        raise ValueError(f"copilot_internal/user 响应中缺少有效的 {quota_name}")

    if any(key in quota_data for key in ("entitlement", "quota_limit", "limit")):
        return quota_data

    for key in ("premium_interactions", "chat", "completions"):
        record = quota_data.get(key)
        if isinstance(record, dict):
            return record

    raise ValueError(f"{quota_name} 中缺少可识别的额度记录")


def _get_quota_value(quota: dict, *keys: str) -> float:
    """读取额度字段并统一转换为数值。"""
    for key in keys:
        value = quota.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"额度字段 {key} 不是有效数字") from error
    raise ValueError(f"额度记录中缺少字段：{'、'.join(keys)}")


def aggregate_model_usage(usage_data: dict):
    """聚合模型使用量，计算每个模型的总使用量和占比"""
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

    logger.info("模型使用量聚合完成")

    return result_models , total_gross_quantity


def get_account_status_desc(plan: str, sku: str) -> str:
    """根据 plan 和 sku 返回账户类型描述"""
    plan = plan.lower() if plan else ""
    sku = sku.lower() if sku else ""

    if sku == "free_limited_copilot":
        return "Copilot 免费版"
    if sku == "free_engaged_oss_quota":
        return "开源作者专属 Pro"
    if sku == "free_educational_quota":
        return "Copilot 学生版"
    if sku == "plus_monthly_subscriber_quota":
        return "Copilot Plus 订阅版"
    # if plan == "individual":
    #     return "Copilot 个人版 (Pro/Pro+/Max/学生)"
    if plan == "business":
        return "Copilot 商业版"
    if plan == "enterprise":
        return "Copilot 企业版"
    return "未知账户类型"


def build_desktop_payload(quota_info: dict, models: dict, total_gross: float) -> dict:
    """建立一个稳定的、可序列化为 JSON 的响应，用于桌面客户端"""
    included = quota_info["included_credits"]
    remaining = quota_info["remaining_credits"]
    used = max(included - remaining, 0)

    logger.info("桌面客户端响应数据构建完成")
    return {
        "schema_version": 1,
        "quota": {
            "plan": quota_info["plan"],
            "account_status": quota_info["account_status"],
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