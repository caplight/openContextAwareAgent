"""结构化日志：统一 logger 配置，避免散落的 print。"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def _configure_root() -> None:
    root = logging.getLogger()
    if root.handlers:  # 已配置过则跳过
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """获取带统一格式的 logger。"""
    _configure_root()
    return logging.getLogger(name)
