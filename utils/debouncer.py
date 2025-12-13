"""
防抖工具
改进的防抖逻辑，提供更好的用户反馈
"""
import time
from typing import Dict, Callable, Optional, Any
import asyncio


class Debouncer:
    """
    防抖器 - 防止命令在短时间内重复执行
    提供用户反馈机制
    """

    def __init__(self, window: float = 0.5):
        """
        Args:
            window: 防抖时间窗口（秒）
        """
        self.window = window
        self._last_call_times: Dict[str, float] = {}
        self._call_counts: Dict[str, int] = {}

    def should_execute(self, key: str) -> tuple[bool, Optional[str]]:
        """
        判断是否应该执行命令

        Args:
            key: 命令的唯一标识

        Returns:
            (should_execute, message)
            - should_execute: 是否应该执行
            - message: 如果被防抖，返回说明信息；否则为None
        """
        current_time = time.time()

        if key not in self._last_call_times:
            # 首次调用
            self._last_call_times[key] = current_time
            self._call_counts[key] = 1
            return True, None

        elapsed = current_time - self._last_call_times[key]

        if elapsed < self.window:
            # 在防抖窗口内，拒绝执行
            self._call_counts[key] = self._call_counts.get(key, 0) + 1
            remaining = self.window - elapsed
            message = f"命令 '{key}' 被防抖过滤 (距离上次 {elapsed:.2f}秒，需等待 {remaining:.2f}秒，已过滤 {self._call_counts[key]} 次)"
            return False, message

        # 超过防抖窗口，允许执行
        self._last_call_times[key] = current_time
        self._call_counts[key] = 1
        return True, None

    def reset(self, key: Optional[str] = None):
        """
        重置防抖状态

        Args:
            key: 要重置的命令标识，如果为None则重置所有
        """
        if key is None:
            self._last_call_times.clear()
            self._call_counts.clear()
        else:
            self._last_call_times.pop(key, None)
            self._call_counts.pop(key, None)


class AsyncDebouncer:
    """
    异步防抖器 - 支持异步回调
    当命令被防抖时，可以发送通知给客户端
    """

    def __init__(
        self,
        window: float = 0.5,
        on_debounced: Optional[Callable[[str, str], Any]] = None
    ):
        """
        Args:
            window: 防抖时间窗口（秒）
            on_debounced: 当命令被防抖时的回调函数 (key, message) -> None
        """
        self.debouncer = Debouncer(window)
        self.on_debounced = on_debounced

    async def execute_with_debounce(
        self,
        key: str,
        func: Callable,
        *args,
        **kwargs
    ) -> Optional[Any]:
        """
        带防抖的执行函数

        Args:
            key: 命令标识
            func: 要执行的函数
            *args, **kwargs: 传递给函数的参数

        Returns:
            函数的返回值，如果被防抖则返回None
        """
        should_execute, message = self.debouncer.should_execute(key)

        if not should_execute:
            # 被防抖，触发回调
            if self.on_debounced:
                if asyncio.iscoroutinefunction(self.on_debounced):
                    await self.on_debounced(key, message)
                else:
                    self.on_debounced(key, message)
            return None

        # 执行函数
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)

    def reset(self, key: Optional[str] = None):
        """重置防抖状态"""
        self.debouncer.reset(key)
