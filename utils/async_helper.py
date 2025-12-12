"""
异步和线程安全辅助工具
改进线程安全处理
"""
import asyncio
from typing import Optional
import carb


def safe_set_event(event: asyncio.Event, logger_name: str = "AsyncHelper") -> bool:
    """
    线程安全地设置asyncio事件

    Args:
        event: asyncio.Event实例
        logger_name: 日志器名称

    Returns:
        是否成功设置
    """
    try:
        # 尝试获取当前事件循环
        loop = asyncio.get_event_loop()

        # 检查是否在正确的线程中
        if loop.is_running():
            # 在事件循环线程中，使用call_soon_threadsafe
            loop.call_soon_threadsafe(event.set)
            return True
        else:
            # 事件循环未运行，直接设置
            event.set()
            return True

    except RuntimeError as e:
        # 没有当前事件循环，可能在其他线程中
        if "no running event loop" in str(e).lower() or "no current event loop" in str(e).lower():
            # 尝试直接设置（在某些情况下可能有效）
            try:
                event.set()
                return True
            except Exception as inner_e:
                carb.log_warn(f"[{logger_name}] Failed to set event: {inner_e}")
                return False
        else:
            carb.log_warn(f"[{logger_name}] Unexpected RuntimeError: {e}")
            return False

    except Exception as e:
        carb.log_error(f"[{logger_name}] Failed to set event safely: {e}")
        return False


async def safe_wait_for(
    awaitable,
    timeout: Optional[float] = None,
    default=None,
    logger_name: str = "AsyncHelper"
):
    """
    安全地等待异步操作，带超时和默认值

    Args:
        awaitable: 要等待的协程或任务
        timeout: 超时时间（秒），None表示无限等待
        default: 超时时返回的默认值
        logger_name: 日志器名称

    Returns:
        awaitable的结果或default
    """
    try:
        if timeout is not None:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        else:
            return await awaitable
    except asyncio.TimeoutError:
        carb.log_warn(f"[{logger_name}] Operation timed out after {timeout}s")
        return default
    except Exception as e:
        carb.log_error(f"[{logger_name}] Operation failed: {e}")
        return default


class AsyncLock:
    """
    改进的异步锁，带超时和日志
    """

    def __init__(self, name: str = "Lock", timeout: float = 30.0):
        """
        Args:
            name: 锁的名称（用于日志）
            timeout: 获取锁的超时时间（秒）
        """
        self.name = name
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._acquired_time: Optional[float] = None

    async def acquire(self) -> bool:
        """
        获取锁（带超时）

        Returns:
            是否成功获取锁
        """
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.timeout)
            self._acquired_time = asyncio.get_event_loop().time()
            return True
        except asyncio.TimeoutError:
            carb.log_error(f"[{self.name}] Failed to acquire lock after {self.timeout}s")
            return False

    def release(self):
        """释放锁"""
        if self._acquired_time is not None:
            elapsed = asyncio.get_event_loop().time() - self._acquired_time
            if elapsed > 5.0:  # 如果锁持有超过5秒，记录警告
                carb.log_warn(f"[{self.name}] Lock held for {elapsed:.2f}s")
            self._acquired_time = None

        self._lock.release()

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        self.release()
