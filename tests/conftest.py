"""pytest 全局 fixture。"""

from __future__ import annotations

import pytest

from enterprise_kb.config import get_settings


@pytest.fixture(autouse=True)
def _reset_settings():
    """每个测试前后清空配置缓存，确保环境变量改动生效。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
