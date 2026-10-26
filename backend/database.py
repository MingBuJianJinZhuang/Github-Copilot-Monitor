import logging
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


@contextmanager
def _connection(database_path: Path):
    conn = sqlite3.connect(database_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db_file(username: str = "") -> Path:
    """返回数据库文件路径。
    用户名作为参数保留，以便与现有调用者兼容。用户隔离通过复合键和查询谓词来强制执行，而不是通过单独的数据库文件。
    """
    return Path(__file__).with_name("copilot_usage.db")


def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})")}


def _create_tables(cursor: sqlite3.Cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS total_daily_usage (
            record_date TEXT NOT NULL,
            username TEXT NOT NULL,
            included_credits REAL,
            used_credits REAL,
            remaining_credits REAL,
            PRIMARY KEY (record_date, username)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_daily_usage (
            record_date TEXT NOT NULL,
            username TEXT NOT NULL,
            model_name TEXT NOT NULL,
            used_credits REAL,
            PRIMARY KEY (record_date, username, model_name)
        )
    """)


def _migrate_legacy_tables(cursor: sqlite3.Cursor, username: str) -> None:
    """Migrate the former date-only schema while retaining existing data."""
    total_columns = _table_columns(cursor, "total_daily_usage")
    if total_columns and "username" not in total_columns:
        cursor.execute("ALTER TABLE total_daily_usage RENAME TO total_daily_usage_legacy")
        cursor.execute("""
            CREATE TABLE total_daily_usage (
                record_date TEXT NOT NULL,
                username TEXT NOT NULL,
                included_credits REAL,
                used_credits REAL,
                remaining_credits REAL,
                PRIMARY KEY (record_date, username)
            )
        """)
        cursor.execute("""
            INSERT INTO total_daily_usage
                (record_date, username, included_credits, used_credits, remaining_credits)
            SELECT record_date, ?, included_credits, used_credits, remaining_credits
            FROM total_daily_usage_legacy
        """, (username,))
        cursor.execute("DROP TABLE total_daily_usage_legacy")

    model_columns = _table_columns(cursor, "model_daily_usage")
    if model_columns and "username" not in model_columns:
        cursor.execute("ALTER TABLE model_daily_usage RENAME TO model_daily_usage_legacy")
        cursor.execute("""
            CREATE TABLE model_daily_usage (
                record_date TEXT NOT NULL,
                username TEXT NOT NULL,
                model_name TEXT NOT NULL,
                used_credits REAL,
                PRIMARY KEY (record_date, username, model_name)
            )
        """)
        cursor.execute("""
            INSERT INTO model_daily_usage
                (record_date, username, model_name, used_credits)
            SELECT record_date, ?, model_name, used_credits
            FROM model_daily_usage_legacy
        """, (username,))
        cursor.execute("DROP TABLE model_daily_usage_legacy")


def initialize_database(username: str):
    """Initialize the shared database and migrate the former schema."""
    database_path = get_db_file(username)
    logger.info("初始化数据库")
    try:
        with _connection(database_path) as conn:
            cursor = conn.cursor()
            _migrate_legacy_tables(cursor, username)
            _create_tables(cursor)
        logger.info("数据库初始化完成")
    except sqlite3.Error as e:
        logger.error(f"初始化数据库失败: {e}")
        raise


def save_daily_usage(
    included_credits: float,
    used_credits: float,
    remaining_credits: float,
    model_usage: dict,
    username: str,
):
    """Save the current user's daily quota and model usage snapshot."""
    database_path = get_db_file(username)
    try:
        today_str = date.today().isoformat()
        with _connection(database_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO total_daily_usage
                    (record_date, username, included_credits, used_credits, remaining_credits)
                VALUES (?, ?, ?, ?, ?)
            """, (today_str, username, included_credits, used_credits, remaining_credits))

            cursor.execute(
                "DELETE FROM model_daily_usage WHERE record_date = ? AND username = ?",
                (today_str, username),
            )
            for model_name, model_used in model_usage.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO model_daily_usage
                        (record_date, username, model_name, used_credits)
                    VALUES (?, ?, ?, ?)
                """, (today_str, username, model_name, model_used))
        logger.info("数据库保存成功：总额度和模型消耗数据已更新")
    except sqlite3.Error as e:
        logger.error(f"保存当日用量到数据库失败: {e}")
        raise


def get_total_usage_history(years: int, months: int, username: str):
    """Get the current user's total usage history."""
    month_str = f"{years:04d}-{months:02d}"
    database_path = get_db_file(username)
    with _connection(database_path) as conn:
        return conn.execute("""
            SELECT record_date, used_credits
            FROM total_daily_usage
            WHERE record_date LIKE ? AND username = ?
            ORDER BY record_date ASC
        """, (f"{month_str}%", username)).fetchall()


def get_model_usage_history(years: int, months: int, username: str):
    """Get the current user's model usage history."""
    month_str = f"{years:04d}-{months:02d}"
    database_path = get_db_file(username)
    with _connection(database_path) as conn:
        return conn.execute("""
            SELECT record_date, model_name, used_credits
            FROM model_daily_usage
            WHERE record_date LIKE ? AND username = ?
            ORDER BY record_date ASC
        """, (f"{month_str}%", username)).fetchall()


def get_latest_total_usage(username: str):
    """Get the latest total usage record for the current user."""
    database_path = get_db_file(username)
    with _connection(database_path) as conn:
        return conn.execute("""
            SELECT record_date, included_credits, used_credits, remaining_credits
            FROM total_daily_usage
            WHERE username = ?
            ORDER BY record_date DESC
            LIMIT 1
        """, (username,)).fetchone()


def get_latest_model_usage(username: str, target_date: str):
    """Get model usage for the current user's specified date."""
    database_path = get_db_file(username)
    with _connection(database_path) as conn:
        return conn.execute("""
            SELECT model_name, used_credits
            FROM model_daily_usage
            WHERE record_date = ? AND username = ?
        """, (target_date, username)).fetchall()


def backfill_history(daily_results: dict, username: str):
    """Write cumulative daily backfill results for the current user."""
    database_path = get_db_file(username)
    cumulative_total = 0.0
    cumulative_models = {}

    try:
        with _connection(database_path) as conn:
            cursor = conn.cursor()
            for date_str in sorted(daily_results):
                result = daily_results[date_str]
                cumulative_total += result["total"]
                for model, quantity in result["models"].items():
                    cumulative_models[model] = cumulative_models.get(model, 0.0) + quantity

                cursor.execute("""
                    INSERT OR REPLACE INTO total_daily_usage
                        (record_date, username, included_credits, used_credits, remaining_credits)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str, username, 0, cumulative_total, 0))

                for model, cumulative_quantity in cumulative_models.items():
                    cursor.execute("""
                        INSERT OR REPLACE INTO model_daily_usage
                            (record_date, username, model_name, used_credits)
                        VALUES (?, ?, ?, ?)
                    """, (date_str, username, model, cumulative_quantity))
    except sqlite3.Error as e:
        logger.error(f"回填历史数据失败: {e}")
        raise
