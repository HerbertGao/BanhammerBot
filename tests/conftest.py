"""Pytest 配置和共享 fixtures"""

import sys
from pathlib import Path

import pytest

# 添加 src 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def temp_db_path(tmp_path):
    """临时数据库路径 fixture"""
    return str(tmp_path / "test_banhammer.db")


@pytest.fixture
def sample_user_id():
    """测试用户 ID"""
    return 123456789


@pytest.fixture
def sample_chat_id():
    """测试群组 ID"""
    return -1001234567890
