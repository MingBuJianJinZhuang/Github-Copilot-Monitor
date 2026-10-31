import json
import sys

from logger_setup import setup_logger
from api_client import get_copilot_data
from core_logic import (
    aggregate_model_usage,
    build_desktop_payload,
    calculate_quota_status,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

setup_logger()


def main():
    # 1. 获取原始数据
    api_data, usage_data = get_copilot_data()

    # 2. 计算配额与时间信息
    quota_info = calculate_quota_status(api_data)

    # 3. Build a desktop-client-friendly JSON response.
    models, total_gross = aggregate_model_usage(usage_data)
    print(json.dumps(
        build_desktop_payload(quota_info, models, total_gross),
        ensure_ascii=False,
        indent=2,
    ))

# if __name__ == "__main__":
#     main()