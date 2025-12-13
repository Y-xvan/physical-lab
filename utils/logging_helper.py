"""
改进的日志系统
解决原代码中"只记录一次"导致的问题隐藏
使用智能日志抑制：记录错误次数和首次/最后一次时间
"""
import time
import logging
from typing import Dict, Tuple
from collections import defaultdict
import carb


class SmartLogger:
    """
    智能日志记录器
    - 追踪每种错误的发生次数
    - 在指定时间间隔内抑制重复日志
    - 定期输出统计信息
    """

    def __init__(self, name: str, suppress_interval: float = 10.0):
        """
        Args:
            name: 日志器名称
            suppress_interval: 重复日志抑制间隔（秒）
        """
        self.name = name
        self.suppress_interval = suppress_interval

        # 错误追踪：{error_key: (count, first_time, last_time, last_log_time)}
        self._error_tracking: Dict[str, Tuple[int, float, float, float]] = {}

        # 统计信息输出间隔
        self._stats_interval = 60.0  # 每60秒输出一次统计
        self._last_stats_time = time.time()

    def _get_error_key(self, message: str, level: str) -> str:
        """生成错误的唯一标识"""
        # 使用消息的前100个字符作为key，避免参数变化导致的key不同
        return f"{level}:{message[:100]}"

    def _should_log(self, error_key: str) -> bool:
        """判断是否应该记录日志"""
        current_time = time.time()

        if error_key not in self._error_tracking:
            # 首次出现，记录
            self._error_tracking[error_key] = (1, current_time, current_time, current_time)
            return True

        count, first_time, last_time, last_log_time = self._error_tracking[error_key]

        # 更新计数和最后出现时间
        self._error_tracking[error_key] = (
            count + 1,
            first_time,
            current_time,
            last_log_time
        )

        # 如果距离上次记录超过抑制间隔，则记录
        if current_time - last_log_time >= self.suppress_interval:
            # 更新最后记录时间
            count, first_time, last_time, _ = self._error_tracking[error_key]
            self._error_tracking[error_key] = (count, first_time, last_time, current_time)
            return True

        return False

    def _log_with_carb(self, level: str, message: str):
        """使用carb记录日志"""
        if level == "info":
            carb.log_info(message)
        elif level == "warn":
            carb.log_warn(message)
        elif level == "error":
            carb.log_error(message)
        else:
            carb.log_info(message)

    def info(self, message: str, suppress: bool = False):
        """记录INFO级别日志"""
        if suppress:
            error_key = self._get_error_key(message, "INFO")
            if not self._should_log(error_key):
                return

            count, first_time, last_time, _ = self._error_tracking[error_key]
            if count > 1:
                message = f"{message} (出现 {count} 次)"

        self._log_with_carb("info", f"[{self.name}] {message}")

    def warn(self, message: str, suppress: bool = True):
        """记录WARN级别日志"""
        if suppress:
            error_key = self._get_error_key(message, "WARN")
            if not self._should_log(error_key):
                return

            count, first_time, last_time, _ = self._error_tracking[error_key]
            if count > 1:
                message = f"{message} (出现 {count} 次)"

        self._log_with_carb("warn", f"[{self.name}] {message}")

    def error(self, message: str, suppress: bool = True, exc_info: bool = False):
        """记录ERROR级别日志"""
        if suppress:
            error_key = self._get_error_key(message, "ERROR")
            if not self._should_log(error_key):
                return

            count, first_time, last_time, _ = self._error_tracking[error_key]
            if count > 1:
                message = f"{message} (出现 {count} 次，首次: {time.strftime('%H:%M:%S', time.localtime(first_time))})"

        self._log_with_carb("error", f"[{self.name}] {message}")

        # 如果需要异常信息
        if exc_info:
            import traceback
            carb.log_error(traceback.format_exc())

    def print_stats(self):
        """输出错误统计信息"""
        current_time = time.time()

        if current_time - self._last_stats_time < self._stats_interval:
            return

        if not self._error_tracking:
            return

        self._last_stats_time = current_time

        carb.log_info("=" * 60)
        carb.log_info(f"[{self.name}] 错误统计报告")
        carb.log_info("=" * 60)

        # 按出现次数排序
        sorted_errors = sorted(
            self._error_tracking.items(),
            key=lambda x: x[1][0],
            reverse=True
        )

        for error_key, (count, first_time, last_time, _) in sorted_errors[:10]:
            level, msg = error_key.split(":", 1)
            duration = last_time - first_time
            carb.log_info(
                f"  [{level}] {msg[:80]}... "
                f"(次数: {count}, 持续: {duration:.1f}秒)"
            )

        carb.log_info("=" * 60)

    def reset_stats(self):
        """重置统计信息"""
        self._error_tracking.clear()


# 创建全局日志实例
video_logger = SmartLogger("VideoTrack", suppress_interval=10.0)
camera_logger = SmartLogger("Camera", suppress_interval=10.0)
server_logger = SmartLogger("Server", suppress_interval=10.0)
simulation_logger = SmartLogger("Simulation", suppress_interval=10.0)
