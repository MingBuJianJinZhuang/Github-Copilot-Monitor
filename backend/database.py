import logging
import sqlite3
from pathlib import Path
from datetime import date

logger = logging.getLogger(__name__)

# 数据库文件放在当前目录下


# 动态生成对应账号的数据库路径
def get_db_file(username: str) -> Path:
    # 过滤特殊字符防止路径穿越攻击
    safe_name = "".join([c for c in username if c.isalnum() or c in "-_"])
    return Path(__file__).with_name(f"copilot_usage_{safe_name}.db")

def initialize_database(username: str):
    DATABASE_PATH  = get_db_file(username)
    """初始化数据库，创建总额度表和模型消耗表"""
    logger.info("初始化数据库")
    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            
            # 1. 总额度表（按日期记录整体情况）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS total_daily_usage (
                    record_date TEXT PRIMARY KEY,
                    included_credits REAL,
                    used_credits REAL,
                    remaining_credits REAL
                )
            """)
            
            # 2. 模型消耗表（按日期+模型名称记录）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_daily_usage (
                    record_date TEXT,
                    model_name TEXT,
                    used_credits REAL,
                    PRIMARY KEY (record_date, model_name)
                )
            """)
            conn.commit()
        logger.info("数据库初始化完成")
    except sqlite3.Error as e:
        logger.error(f"初始化数据库失败: {e}")
        raise

def save_daily_usage(included_credits:float , used_credits:float , remaining_credits:float , model_usage:dict , username: str):
    """保存每日总额度和模型消耗数据"""
    DATABASE_PATH  = get_db_file(username)
    try:
        today_str = date.today().isoformat()
        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            
            # 保存总额度数据
            cursor.execute("""
                INSERT OR REPLACE INTO total_daily_usage (record_date, included_credits, used_credits, remaining_credits)
                VALUES (?, ?, ?, ?)
            """, (today_str, included_credits, used_credits, remaining_credits))
            
            # 当天数据是快照：先删除旧模型行，避免已消失的模型继续显示。
            cursor.execute(
                "DELETE FROM model_daily_usage WHERE record_date = ?",
                (today_str,),
            )
            # 保存模型消耗数据
            for model_name, model_used  in model_usage.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO model_daily_usage (record_date, model_name, used_credits)
                    VALUES (?, ?, ?)
                """, (today_str, model_name, model_used))
            
            conn.commit()
        logger.info("数据库保存成功：总额度和模型消耗数据已更新")
    except sqlite3.Error as e:
        logger.error(f"保存当日用量到数据库失败: {e}")
        raise

def get_total_usage_history(years:int , months:int , username: str):
    """获取总额度历史数据"""
    mouth_str = f"{years:04d}-{months:02d}"
    DATABASE_PATH  = get_db_file(username)
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT record_date, used_credits
            FROM total_daily_usage
            WHERE record_date LIKE ?
            ORDER BY record_date ASC
        """, (f"{mouth_str}%",))
        return cursor.fetchall()

def get_model_usage_history(years:int , months:int , username: str):
    """获取模型消耗历史数据"""
    mouth_str = f"{years:04d}-{months:02d}"
    DATABASE_PATH  = get_db_file(username)
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT record_date, model_name, used_credits
            FROM model_daily_usage
            WHERE record_date LIKE ?
            ORDER BY record_date ASC
        """, (f"{mouth_str}%",))
        return cursor.fetchall()

def get_latest_total_usage(username: str):
    """获取最新的总额度数据"""
    DATABASE_PATH  = get_db_file(username)
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        # 按日期降序获取最新一条记录
        cursor.execute("""
            SELECT record_date, included_credits, used_credits, remaining_credits
            FROM total_daily_usage
            ORDER BY record_date DESC LIMIT 1
        """)
        return cursor.fetchone()

def get_latest_model_usage(username: str, target_date:str ):
    """获取指定日期的各模型消耗数据"""
    DATABASE_PATH  = get_db_file(username)
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT model_name, used_credits
            FROM model_daily_usage
            WHERE record_date = ?
        """, (target_date,))
        return cursor.fetchall()

# 回填历史数据
def backfill_history(daily_results: dict, username: str):
    """
    将按日回填的结果写入数据库。
    daily_results 格式: { "2026-10-01": {"total": X, "models": {...}}, ... }
    """
    DATABASE_PATH  = get_db_file(username)
    cumulative_total = 0.0
    cumulative_models = {}  # {model: cumulative_qty}
    
    # 按日期排序，确保累加顺序正确
    for date_str in sorted(daily_results.keys()):
        result = daily_results[date_str]
        cumulative_total += result["total"]
        
        for model, qty in result["models"].items():
            cumulative_models[model] = cumulative_models.get(model, 0.0) + qty
        
        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            
            # 写入总额度表（存储累计已用额度）
            # 注意：included_credits 和 remaining_credits 历史值可能不准确，用近似值填充
            # 这里 included 可以用当前的总额度，remaining 用 included - cumulative_total
            cursor.execute("""
                INSERT OR REPLACE INTO total_daily_usage 
                (record_date, included_credits, used_credits, remaining_credits)
                VALUES (?, ?, ?, ?)
            """, (date_str, 0, cumulative_total, 0))  # included/remaining 回填时暂用0或近似值
            
            # 写入模型表（存储累计消耗）
            for model, cum_qty in cumulative_models.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO model_daily_usage 
                    (record_date, model_name, used_credits)
                    VALUES (?, ?, ?)
                """, (date_str, model, cum_qty))
                
            conn.commit()