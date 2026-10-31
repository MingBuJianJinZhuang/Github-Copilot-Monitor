import logging
import sys
from pathlib import Path

_HANDLER_MARKER = "_copilot_monitor_handler"


def setup_logger() -> logging.Logger:
    """配置全局日志：输出到控制台和 app.log 文件"""
    log_file = Path(__file__).parent / "app.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                same_file = Path(handler.baseFilename).resolve() == log_file.resolve()
            except OSError:
                same_file = False
            if same_file:
                setattr(handler, _HANDLER_MARKER, "file")
        elif isinstance(handler, logging.StreamHandler):
            setattr(handler, _HANDLER_MARKER, "console")

    managed_handlers = {}
    for handler in list(root_logger.handlers):
        marker = getattr(handler, _HANDLER_MARKER, None)
        if not marker:
            continue
        if marker in managed_handlers:
            root_logger.removeHandler(handler)
            handler.close()
        else:
            managed_handlers[marker] = handler

    if "file" not in managed_handlers:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        setattr(file_handler, _HANDLER_MARKER, "file")
        root_logger.addHandler(file_handler)

    if "console" not in managed_handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        setattr(console_handler, _HANDLER_MARKER, "console")
        root_logger.addHandler(console_handler)

    return root_logger