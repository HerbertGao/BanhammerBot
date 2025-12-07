"""测试速率限制器"""

import time

import pytest

from utils.rate_limiter import RateLimiter


class TestRateLimiter:
    """测试速率限制器"""

    @pytest.fixture
    def limiter(self):
        """创建速率限制器实例"""
        return RateLimiter()

    @pytest.mark.asyncio
    async def test_single_call_not_limited(self, limiter):
        """测试单次调用不被限制"""
        result = await limiter.is_rate_limited(
            user_id=123, action="test_action", max_calls=5, window_seconds=60
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_within_limit_not_blocked(self, limiter):
        """测试在限制范围内不被阻止"""
        user_id = 123
        action = "test_action"

        # 连续调用4次（限制是5次）
        for _ in range(4):
            result = await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=60)
            assert result is False

    @pytest.mark.asyncio
    async def test_exceed_limit_blocked(self, limiter):
        """测试超过限制被阻止"""
        user_id = 123
        action = "test_action"

        # 前5次应该通过
        for i in range(5):
            result = await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=60)
            assert result is False, f"第 {i+1} 次调用应该通过"

        # 第6次应该被阻止
        result = await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=60)
        assert result is True, "第 6 次调用应该被阻止"

    @pytest.mark.asyncio
    async def test_different_users_independent(self, limiter):
        """测试不同用户的限制是独立的"""
        action = "test_action"

        # 用户1使用5次
        for _ in range(5):
            await limiter.is_rate_limited(
                user_id=111, action=action, max_calls=5, window_seconds=60
            )

        # 用户1应该被限制
        result1 = await limiter.is_rate_limited(
            user_id=111, action=action, max_calls=5, window_seconds=60
        )
        assert result1 is True

        # 用户2应该不受影响
        result2 = await limiter.is_rate_limited(
            user_id=222, action=action, max_calls=5, window_seconds=60
        )
        assert result2 is False

    @pytest.mark.asyncio
    async def test_different_actions_independent(self, limiter):
        """测试不同操作的限制是独立的"""
        user_id = 123

        # action1 使用5次
        for _ in range(5):
            await limiter.is_rate_limited(user_id, "action1", max_calls=5, window_seconds=60)

        # action1 应该被限制
        result1 = await limiter.is_rate_limited(user_id, "action1", max_calls=5, window_seconds=60)
        assert result1 is True

        # action2 应该不受影响
        result2 = await limiter.is_rate_limited(user_id, "action2", max_calls=5, window_seconds=60)
        assert result2 is False

    @pytest.mark.asyncio
    async def test_window_expiration(self, limiter):
        """测试时间窗口过期后限制解除"""
        user_id = 123
        action = "test_action"
        window = 1  # 1秒窗口

        # 使用5次达到限制
        for _ in range(5):
            await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=window)

        # 应该被限制
        assert (
            await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=window)
            is True
        )

        # 等待窗口过期
        time.sleep(window + 0.1)

        # 应该可以再次调用
        result = await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=window)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_remaining_time_when_limited(self, limiter):
        """测试获取剩余时间（被限制时）"""
        user_id = 123
        action = "test_action"
        window = 60

        # 使用5次达到限制
        for _ in range(5):
            await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=window)

        # 获取剩余时间
        remaining = await limiter.get_remaining_time(user_id, action, window)

        # 应该接近窗口大小
        assert remaining > 0
        assert remaining <= window

    @pytest.mark.asyncio
    async def test_get_remaining_time_when_not_limited(self, limiter):
        """测试获取剩余时间（未被限制时）"""
        remaining = await limiter.get_remaining_time(
            user_id=123, action="test_action", window_seconds=60
        )
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_reset_specific_action(self, limiter):
        """测试重置特定操作"""
        user_id = 123
        action = "test_action"

        # 使用5次达到限制
        for _ in range(5):
            await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=60)

        # 应该被限制
        assert (
            await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=60) is True
        )

        # 重置
        await limiter.reset(user_id, action)

        # 应该可以再次调用
        result = await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=60)
        assert result is False

    @pytest.mark.asyncio
    async def test_reset_all_actions(self, limiter):
        """测试重置所有操作"""
        user_id = 123

        # action1 和 action2 都使用5次
        for action in ["action1", "action2"]:
            for _ in range(5):
                await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=60)

        # 两个操作都应该被限制
        assert (
            await limiter.is_rate_limited(user_id, "action1", max_calls=5, window_seconds=60)
            is True
        )
        assert (
            await limiter.is_rate_limited(user_id, "action2", max_calls=5, window_seconds=60)
            is True
        )

        # 重置所有操作
        await limiter.reset(user_id)

        # 两个操作都应该可以再次调用
        assert (
            await limiter.is_rate_limited(user_id, "action1", max_calls=5, window_seconds=60)
            is False
        )
        assert (
            await limiter.is_rate_limited(user_id, "action2", max_calls=5, window_seconds=60)
            is False
        )

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, limiter):
        """测试清理过期记录"""
        user_id = 123
        action = "test_action"
        short_window = 1

        # 添加一些记录
        await limiter.is_rate_limited(user_id, action, max_calls=5, window_seconds=short_window)

        # 等待过期
        time.sleep(short_window + 0.1)

        # 清理
        await limiter.cleanup_expired(window_seconds=short_window)

        # 记录应该被清理，可以再次调用
        result = await limiter.is_rate_limited(
            user_id, action, max_calls=5, window_seconds=short_window
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_concurrent_requests_same_user(self, limiter):
        """测试同一用户的并发请求"""
        user_id = 123
        action = "test_action"
        max_calls = 3

        # 模拟并发请求
        results = []
        for _ in range(5):
            result = await limiter.is_rate_limited(
                user_id, action, max_calls=max_calls, window_seconds=60
            )
            results.append(result)

        # 前3次应该通过，后2次应该被阻止
        assert results == [False, False, False, True, True]

    @pytest.mark.asyncio
    async def test_zero_max_calls(self, limiter):
        """测试max_calls=0的情况"""
        # 任何调用都应该被阻止
        result = await limiter.is_rate_limited(
            user_id=123, action="test_action", max_calls=0, window_seconds=60
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_very_short_window(self, limiter):
        """测试非常短的时间窗口"""
        user_id = 123
        action = "test_action"
        short_window = 0.5

        # 使用2次
        await limiter.is_rate_limited(user_id, action, max_calls=2, window_seconds=short_window)
        await limiter.is_rate_limited(user_id, action, max_calls=2, window_seconds=short_window)

        # 应该被限制
        assert (
            await limiter.is_rate_limited(user_id, action, max_calls=2, window_seconds=short_window)
            is True
        )

        # 等待窗口过期
        time.sleep(short_window + 0.1)

        # 应该可以再次调用
        assert (
            await limiter.is_rate_limited(user_id, action, max_calls=2, window_seconds=short_window)
            is False
        )
