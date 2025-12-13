"""
简化的帧验证工具
专注于核心验证逻辑，减少过度防御性编程
"""
import numpy as np
from typing import Optional, Tuple
import carb

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class FrameValidator:
    """
    帧验证器 - 确保视频帧符合编码器要求
    """

    def __init__(self, width: int, height: int):
        """
        Args:
            width: 目标宽度（必须是偶数）
            height: 目标高度（必须是偶数）
        """
        # 确保尺寸为偶数
        self.width = width - (width % 2)
        self.height = height - (height % 2)

        # 错误计数
        self._error_count = 0
        self._max_error_log = 5

    def validate_and_fix(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        验证并修复帧数据

        Args:
            frame: 输入帧

        Returns:
            修复后的帧，如果无法修复则返回None
        """
        if frame is None or not isinstance(frame, np.ndarray):
            self._log_error("Invalid frame type")
            return None

        if frame.size == 0:
            self._log_error("Empty frame")
            return None

        try:
            # 1. 处理数据类型和值范围
            frame = self._fix_dtype_and_range(frame)

            # 2. 处理通道数
            frame = self._fix_channels(frame)

            # 3. 调整尺寸
            frame = self._fix_size(frame)

            # 4. 确保内存连续
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame)

            # 5. 最终验证
            if frame.shape != (self.height, self.width, 3):
                self._log_error(f"Final shape mismatch: {frame.shape}")
                return None

            if frame.dtype != np.uint8:
                self._log_error(f"Final dtype mismatch: {frame.dtype}")
                return None

            return frame

        except Exception as e:
            self._log_error(f"Frame validation failed: {e}")
            return None

    def _fix_dtype_and_range(self, frame: np.ndarray) -> np.ndarray:
        """修复数据类型和值范围"""
        if frame.dtype == np.uint8:
            return frame

        # 浮点类型
        if frame.dtype in (np.float32, np.float64):
            # 处理NaN和Inf
            if np.isnan(frame).any() or np.isinf(frame).any():
                frame = np.nan_to_num(frame, nan=0.0, posinf=1.0, neginf=0.0)

            # 检测值范围并缩放
            min_val = frame.min()
            max_val = frame.max()

            if 0.0 <= min_val and max_val <= 1.0:
                # [0, 1] 范围
                return (frame * 255).astype(np.uint8)
            elif 0.0 <= min_val and max_val <= 255.0:
                # [0, 255] 范围
                return frame.astype(np.uint8)
            else:
                # 其他范围，归一化
                if max_val > min_val:
                    frame = (frame - min_val) / (max_val - min_val) * 255
                    return frame.astype(np.uint8)
                else:
                    return np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # 其他整数类型
        return frame.astype(np.uint8)

    def _fix_channels(self, frame: np.ndarray) -> np.ndarray:
        """修复通道数"""
        if len(frame.shape) == 2:
            # 灰度图 -> RGB
            return np.stack([frame] * 3, axis=-1)

        if len(frame.shape) != 3:
            raise ValueError(f"Invalid frame dimensions: {frame.shape}")

        channels = frame.shape[2]

        if channels == 3:
            return frame
        elif channels == 4:
            # RGBA -> RGB
            return frame[:, :, :3].copy()
        elif channels == 1:
            # 单通道 -> RGB
            return np.concatenate([frame] * 3, axis=-1)
        else:
            raise ValueError(f"Invalid channel count: {channels}")

    def _fix_size(self, frame: np.ndarray) -> np.ndarray:
        """调整帧尺寸"""
        h, w = frame.shape[:2]

        if h == self.height and w == self.width:
            return frame

        if not HAS_PIL:
            raise RuntimeError("PIL is required for frame resizing")

        img = Image.fromarray(frame)
        img = img.resize((self.width, self.height), Image.BILINEAR)
        return np.array(img)

    def _log_error(self, message: str):
        """记录错误（限制次数）"""
        self._error_count += 1
        if self._error_count <= self._max_error_log:
            carb.log_error(f"[FrameValidator] {message} (#{self._error_count})")

    def generate_test_pattern(self) -> np.ndarray:
        """生成彩色条纹测试图案"""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        stripe_width = self.width // 7

        colors = [
            [255, 255, 255],  # 白色
            [255, 255, 0],    # 黄色
            [0, 255, 255],    # 青色
            [0, 255, 0],      # 绿色
            [255, 0, 255],    # 品红
            [255, 0, 0],      # 红色
            [0, 0, 255],      # 蓝色
        ]

        for i, color in enumerate(colors):
            x_start = i * stripe_width
            x_end = min((i + 1) * stripe_width, self.width)
            frame[:, x_start:x_end] = color

        return frame

    def generate_blank_frame(self, color: Tuple[int, int, int] = (0, 128, 0)) -> np.ndarray:
        """
        生成纯色帧

        Args:
            color: RGB颜色 (默认为绿色)
        """
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:, :] = color
        return frame
