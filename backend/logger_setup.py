import logging
import sys
from pathlib import Path

def setup_logger():
    """配置全局日志：输出到控制台和 app.log 文件"""
    log_file = Path(__file__).parent / "app.log"
    
    # 日志格式：时间 - 级别 - 模块名 - 信息
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 文件处理器
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # 获取根 logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 避免重复添加 handler (Streamlit 每次热重载都会执行)
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
    return logger