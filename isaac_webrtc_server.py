"""
Isaac Sim WebRTC Server
使用aiortc实现高性能H.264视频流传输

优势：
1. H.264硬件编码 - GPU加速
2. 极低延迟 (50-150ms)
3. 自适应码率
4. 高压缩比 (比JPEG小10倍+)
"""

import carb
import omni.ext
import omni.kit.viewport.utility as vp_util
import omni.usd
import omni.timeline
from pxr import Gf, UsdGeom
import asyncio
import json
import math
import time
import numpy as np
from typing import Optional, Dict, Any, Set
import logging
import fractions
import os

# WebRTC相关
try:
    from aiohttp import web
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    from aiortc.contrib.media import MediaBlackhole
    from av import VideoFrame
    HAS_WEBRTC = True
except ImportError:
    HAS_WEBRTC = False
    carb.log_error("❌ WebRTC not available. Install: pip install aiortc aiohttp")

# PIL用于图像处理
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    carb.log_warn("❌ PIL not available - please install: pip install Pillow")

# Replicator用于帧捕获
try:
    import omni.replicator.core as rep
    HAS_REPLICATOR = True
except ImportError:
    HAS_REPLICATOR = False
    carb.log_warn("❌ Replicator not available")

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc")

# ============================================================
# 路径配置 - 适配远程主机部署
# ============================================================
# 脚本所在目录（isaac_webrtc_server.py的目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Camera配置脚本目录（与本脚本同目录下的camera文件夹）
CAMERA_SCRIPT_DIR = os.path.join(SCRIPT_DIR, "camera")

# USD场景文件路径（可通过环境变量PHY_USD_PATH覆盖）
# 默认值：假设在某个标准位置，或者通过环境变量指定
DEFAULT_USD_PATH = os.getenv("PHY_USD_PATH", "/home/zhiren/Isaaclab_Assets/Experiment/exp.usd")
# 如果希望使用相对路径，可以取消下面这行的注释：
# DEFAULT_USD_PATH = os.getenv("PHY_USD_PATH", os.path.join(SCRIPT_DIR, "assets", "exp.usd"))


class CaptureDelegate:
    """
    捕获代理类 - 实现 Capture 接口供 schedule_capture 使用
    """
    def __init__(self, video_track):
        self.video_track = video_track

    def capture(self, all_aovs, frame_info, texture, result_handle):
        """
        捕获回调 - 当帧渲染完成时被调用

        Args:
            all_aovs: 所有 AOV (Arbitrary Output Variables)
            frame_info: 帧信息
            texture: Hydra 纹理对象
            result_handle: 结果句柄
        """
        try:
            # 方法1: 从 all_aovs 获取 LDR 颜色纹理
            if 'LdrColor' in all_aovs:
                aov_data = all_aovs['LdrColor']
                if 'texture' in aov_data:
                    texture_info = aov_data['texture']

                    # 获取分辨率
                    resolution = texture_info.get('resolution')
                    if resolution:
                        width, height = resolution.x, resolution.y
                    else:
                        width, height = frame_info.get('resolution', (1280, 720))

                    # 获取 RpResource
                    rp_resource = texture_info.get('rp_resource')
                    if rp_resource:
                        # 从 GPU 资源读取数据
                        data = self._read_rp_resource(rp_resource, width, height)
                        if data is not None:
                            self.video_track.latest_frame = data
                            # 在主线程安全地设置事件
                            try:
                                loop = asyncio.get_event_loop()
                                loop.call_soon_threadsafe(self.video_track.capture_event.set)
                            except:
                                self.video_track.capture_event.set()
                            return

            # 方法2: 直接从 texture 对象获取
            if texture is not None:
                try:
                    # 获取分辨率
                    if hasattr(texture, 'get_height') and hasattr(texture, 'get_width'):
                        height = texture.get_height()
                        width = texture.get_width()
                    else:
                        width, height = frame_info.get('resolution', (1280, 720))

                    # 尝试获取 drawable resource
                    if hasattr(texture, 'get_drawable_ldr_resource'):
                        resource = texture.get_drawable_ldr_resource()
                        if resource:
                            data = self._read_rp_resource(resource, width, height)
                            if data is not None:
                                self.video_track.latest_frame = data
                                try:
                                    loop = asyncio.get_event_loop()
                                    loop.call_soon_threadsafe(self.video_track.capture_event.set)
                                except:
                                    self.video_track.capture_event.set()
                                return

                    # 备用：尝试 get_drawable_resource
                    if hasattr(texture, 'get_drawable_resource'):
                        resource = texture.get_drawable_resource()
                        if resource:
                            data = self._read_rp_resource(resource, width, height)
                            if data is not None:
                                self.video_track.latest_frame = data
                                try:
                                    loop = asyncio.get_event_loop()
                                    loop.call_soon_threadsafe(self.video_track.capture_event.set)
                                except:
                                    self.video_track.capture_event.set()
                                return

                except Exception as e:
                    if not hasattr(self, '_texture_read_error_logged'):
                        carb.log_warn(f"Texture read method failed: {e}")
                        self._texture_read_error_logged = True

        except Exception as e:
            if not hasattr(self, '_capture_error_logged'):
                carb.log_error(f"Capture delegate error: {e}")
                import traceback
                carb.log_error(traceback.format_exc())
                self._capture_error_logged = True

    def _read_rp_resource(self, resource, width: int, height: int) -> Optional[np.ndarray]:
        """
        从 RpResource 读取图像数据

        Args:
            resource: RpResource 对象
            width: 图像宽度
            height: 图像高度

        Returns:
            RGB numpy 数组 (height, width, 3) 或 None
        """
        try:
            import ctypes

            # 方法1: 尝试 map/unmap 模式
            if hasattr(resource, 'map'):
                mapped = resource.map()
                if mapped:
                    try:
                        # 读取 RGBA 数据
                        buffer_size = width * height * 4

                        # 从映射的内存创建数组
                        if hasattr(mapped, 'get_data'):
                            data_ptr = mapped.get_data()
                        elif hasattr(mapped, 'data'):
                            data_ptr = mapped.data
                        else:
                            data_ptr = int(mapped)

                        BufferType = ctypes.c_uint8 * buffer_size
                        buffer_array = np.frombuffer(
                            BufferType.from_address(data_ptr),
                            dtype=np.uint8
                        )

                        # 重塑为 RGBA 图像
                        img_rgba = buffer_array.reshape((height, width, 4))

                        # 转换为 RGB (去掉 alpha 通道)
                        img_rgb = img_rgba[:, :, :3].copy()

                        return img_rgb

                    finally:
                        # 取消映射
                        if hasattr(resource, 'unmap'):
                            resource.unmap()

            # 方法2: 尝试直接 get_data
            if hasattr(resource, 'get_data'):
                data = resource.get_data()
                if data:
                    buffer_size = width * height * 4
                    buffer_array = np.frombuffer(data, dtype=np.uint8, count=buffer_size)
                    img_rgba = buffer_array.reshape((height, width, 4))
                    return img_rgba[:, :, :3].copy()

            # 方法3: 尝试直接访问 data 属性
            if hasattr(resource, 'data'):
                data_ptr = resource.data
                if data_ptr:
                    buffer_size = width * height * 4
                    BufferType = ctypes.c_uint8 * buffer_size
                    buffer_array = np.frombuffer(
                        BufferType.from_address(data_ptr),
                        dtype=np.uint8
                    )
                    img_rgba = buffer_array.reshape((height, width, 4))
                    return img_rgba[:, :, :3].copy()

            return None

        except Exception as e:
            if not hasattr(self, '_read_resource_error_logged'):
                carb.log_error(f"RpResource read error: {e}")
                import traceback
                carb.log_error(traceback.format_exc())
                self._read_resource_error_logged = True
            return None


class IsaacSimVideoTrack(VideoStreamTrack):
    """
    Isaac Sim视频轨道 - 从Isaac Sim捕获帧并编码为视频流
    """

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30):
        super().__init__()
        # 🔑 强制尺寸为偶数（VPX/H264编码器要求）
        self.width = width - (width % 2)
        self.height = height - (height % 2)
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.last_frame_time = 0
        self.frame_count = 0

        # 用于存储捕获的帧
        self.latest_frame = None
        self.capture_event = asyncio.Event()

        # 创建捕获代理（旧方法，保留以防需要）
        self.capture_delegate = CaptureDelegate(self)

        # 使用 Replicator 进行帧捕获（新方法）
        self.use_replicator = HAS_REPLICATOR
        self.render_product = None
        self.rgb_annotator = None

        # 错误计数器
        self._frame_error_count = 0
        self._max_error_log = 5

        if self.use_replicator:
            try:
                # 获取当前相机
                viewport = vp_util.get_active_viewport()
                camera_path = viewport.get_active_camera()

                # 创建 render product（使用偶数尺寸）
                self.render_product = rep.create.render_product(camera_path, (self.width, self.height))

                # 创建 RGB annotator
                self.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
                self.rgb_annotator.attach([self.render_product])

                carb.log_info(f"📹 Video track initialized with Replicator: {self.width}x{self.height}@{fps}fps")
            except Exception as e:
                carb.log_error(f"❌ Replicator init failed: {e}")
                self.use_replicator = False
                carb.log_info(f"📹 Video track initialized (fallback): {self.width}x{self.height}@{fps}fps")
        else:
            carb.log_info(f"📹 Video track initialized: {self.width}x{self.height}@{fps}fps")

    async def recv(self):
        """
        接收下一帧 - aiortc会自动调用此方法
        修复版本：严格验证帧数据，确保符合VPX编码器要求
        """
        # 控制帧率
        current_time = time.time()
        elapsed = current_time - self.last_frame_time

        if elapsed < self.frame_interval:
            await asyncio.sleep(self.frame_interval - elapsed)

        self.last_frame_time = time.time()
        self.frame_count += 1

        # 从Isaac Sim捕获帧 (异步)
        frame_array = await self._capture_isaac_frame_async()

        if frame_array is None:
            frame_array = self._generate_test_pattern()

        # ========== 严格验证和修复帧数据 ==========
        try:
            frame_array = self._validate_and_fix_frame(frame_array)

            # 调试：打印第一帧的详细信息
            if not hasattr(self, '_first_frame_logged'):
                carb.log_info(f"📊 First frame details:")
                carb.log_info(f"   Shape: {frame_array.shape}")
                carb.log_info(f"   Dtype: {frame_array.dtype}")
                carb.log_info(f"   Min: {frame_array.min()}, Max: {frame_array.max()}, Mean: {frame_array.mean():.2f}")
                carb.log_info(f"   Contiguous: {frame_array.flags['C_CONTIGUOUS']}")
                carb.log_info(f"   Memory size: {frame_array.nbytes} bytes")
                self._first_frame_logged = True

            # 转换为 VideoFrame
            frame = VideoFrame.from_ndarray(frame_array, format="rgb24")
            frame.pts = self.frame_count
            frame.time_base = fractions.Fraction(1, self.fps)

            return frame

        except Exception as e:
            self._frame_error_count += 1

            if self._frame_error_count <= self._max_error_log:
                carb.log_error(f"VideoFrame creation failed ({self._frame_error_count}): {e}")
                import traceback
                carb.log_error(traceback.format_exc())

            # 返回安全的测试图案
            test_frame = self._generate_safe_frame()
            frame = VideoFrame.from_ndarray(test_frame, format="rgb24")
            frame.pts = self.frame_count
            frame.time_base = fractions.Fraction(1, self.fps)
            return frame

    def _validate_and_fix_frame(self, frame_array: np.ndarray) -> np.ndarray:
        """
        验证并修复帧数据，确保符合VPX编码器要求
        
        要求：
        1. 数据类型必须是 uint8
        2. 形状必须是 (height, width, 3)
        3. 宽高必须是偶数
        4. 数据必须连续存储
        5. 不能包含 NaN 或 Inf
        """
        # 1. 确保是 numpy 数组
        if not isinstance(frame_array, np.ndarray):
            carb.log_warn(f"Frame is not ndarray: {type(frame_array)}")
            return self._generate_safe_frame()

        # 2. 检查并处理空数组
        if frame_array.size == 0:
            carb.log_warn("Frame is empty")
            return self._generate_safe_frame()

        # 3. 处理数据类型
        if frame_array.dtype != np.uint8:
            if frame_array.dtype in (np.float32, np.float64):
                # 处理 NaN 和 Inf
                if np.isnan(frame_array).any() or np.isinf(frame_array).any():
                    carb.log_warn("Frame contains NaN or Inf values, replacing with zeros")
                    frame_array = np.nan_to_num(frame_array, nan=0.0, posinf=1.0, neginf=0.0)
                
                # 检查值范围并缩放
                min_val = frame_array.min()
                max_val = frame_array.max()
                
                if max_val <= 1.0 and min_val >= 0.0:
                    # 0-1 范围，需要缩放到 0-255
                    frame_array = (frame_array * 255).clip(0, 255).astype(np.uint8)
                elif max_val <= 255.0 and min_val >= 0.0:
                    # 已经是 0-255 范围
                    frame_array = frame_array.clip(0, 255).astype(np.uint8)
                else:
                    # 其他范围，归一化后缩放
                    if max_val != min_val:
                        frame_array = ((frame_array - min_val) / (max_val - min_val) * 255).astype(np.uint8)
                    else:
                        frame_array = np.zeros_like(frame_array, dtype=np.uint8)
            elif frame_array.dtype in (np.uint16, np.int32, np.int64):
                # 高位整数类型，缩放到 0-255
                min_val = frame_array.min()
                max_val = frame_array.max()
                if max_val != min_val:
                    frame_array = ((frame_array - min_val) / (max_val - min_val) * 255).astype(np.uint8)
                else:
                    frame_array = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            else:
                frame_array = frame_array.astype(np.uint8)

        # 4. 处理通道数
        if len(frame_array.shape) == 2:
            # 灰度图转RGB
            frame_array = np.stack([frame_array] * 3, axis=-1)
        elif len(frame_array.shape) == 3:
            if frame_array.shape[2] == 4:
                # RGBA 转 RGB
                frame_array = frame_array[:, :, :3].copy()
            elif frame_array.shape[2] == 1:
                # 单通道转RGB
                frame_array = np.concatenate([frame_array] * 3, axis=-1)
            elif frame_array.shape[2] != 3:
                carb.log_warn(f"Invalid channel count: {frame_array.shape[2]}")
                return self._generate_safe_frame()
        else:
            carb.log_warn(f"Invalid frame dimensions: {frame_array.shape}")
            return self._generate_safe_frame()

        # 5. 🔑 强制尺寸为偶数（VPX 编码器要求）
        h, w = frame_array.shape[:2]
        target_h = self.height
        target_w = self.width

        if h != target_h or w != target_w:
            try:
                from PIL import Image
                img = Image.fromarray(frame_array)
                img = img.resize((target_w, target_h), Image.BILINEAR)
                frame_array = np.array(img)
            except Exception as e:
                carb.log_warn(f"Frame resize failed: {e}")
                return self._generate_safe_frame()

        # 6. 确保内存连续
        if not frame_array.flags['C_CONTIGUOUS']:
            frame_array = np.ascontiguousarray(frame_array)

        # 7. 最终形状验证
        if frame_array.shape != (target_h, target_w, 3):
            carb.log_error(f"Final shape mismatch: {frame_array.shape}, expected ({target_h}, {target_w}, 3)")
            return self._generate_safe_frame()

        # 8. 最终数据类型验证
        if frame_array.dtype != np.uint8:
            frame_array = frame_array.astype(np.uint8)

        return frame_array

    def _generate_safe_frame(self) -> np.ndarray:
        """
        生成安全的备用帧（绿色背景，便于识别错误）
        确保尺寸为偶数，数据类型为 uint8
        """
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:, :, 1] = 128  # 绿色背景
        return frame

    def _generate_test_pattern(self) -> np.ndarray:
        """
        生成测试图案（彩色条纹）
        确保尺寸为偶数，数据类型为 uint8
        """
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

    def _on_capture_complete(self, buffer, buffer_size, width, height, format):
        """
        捕获完成的回调函数
        """
        try:
            if buffer is None or buffer_size == 0:
                carb.log_warn("Captured buffer is empty")
                return

            # 将buffer转换为numpy数组
            # buffer 通常是 RGBA 格式
            import ctypes
            BufferType = ctypes.c_uint8 * buffer_size
            buffer_array = np.frombuffer(
                BufferType.from_address(buffer),
                dtype=np.uint8
            )

            # 重塑为图像
            if format == 4:  # RGBA
                img = buffer_array.reshape((height, width, 4))
                # 转换为RGB
                self.latest_frame = img[:, :, :3].copy()
            else:
                img = buffer_array.reshape((height, width, 3))
                self.latest_frame = img.copy()

            # 通知等待的recv()方法
            self.capture_event.set()

        except Exception as e:
            carb.log_error(f"Capture callback error: {e}")

    async def _capture_isaac_frame_async(self) -> Optional[np.ndarray]:
        """
        从Isaac Sim视口捕获帧 - 使用 Replicator API
        """
        try:
            if self.use_replicator and self.rgb_annotator:
                # 使用 Replicator 方法（推荐）
                try:
                    # 等待一帧渲染完成
                    await rep.orchestrator.step_async()

                    # 获取 RGB 数据
                    data = self.rgb_annotator.get_data()

                    if data is not None and isinstance(data, np.ndarray):
                        # 验证数据有效性
                        if data.size == 0:
                            carb.log_warn("Replicator returned empty data")
                            return None

                        # 转换 RGBA 到 RGB (如果需要)
                        if len(data.shape) == 3 and data.shape[2] == 4:
                            rgb_data = data[:, :, :3]
                        elif len(data.shape) == 3 and data.shape[2] == 3:
                            rgb_data = data
                        else:
                            carb.log_warn(f"Unexpected data shape: {data.shape}")
                            return None

                        # 处理不同的数据类型
                        if rgb_data.dtype == np.float32 or rgb_data.dtype == np.float64:
                            # 检查 NaN 和 Inf
                            if np.isnan(rgb_data).any() or np.isinf(rgb_data).any():
                                carb.log_warn("Replicator data contains NaN/Inf")
                                rgb_data = np.nan_to_num(rgb_data, nan=0.0, posinf=1.0, neginf=0.0)
                            
                            # Replicator 返回的是 float32 [0, 1] 范围，需要缩放到 [0, 255]
                            frame = (rgb_data * 255).clip(0, 255).astype(np.uint8)
                        else:
                            # 如果已经是整数类型，直接转换
                            frame = rgb_data.astype(np.uint8)

                        # 记录成功（只在第一次）
                        if not hasattr(self, '_capture_success_logged'):
                            carb.log_info("✅ Replicator capture working!")
                            self._capture_success_logged = True

                        return self._resize_frame(frame)

                except Exception as e:
                    if not hasattr(self, '_replicator_error_logged'):
                        carb.log_error(f"Replicator capture error: {e}")
                        import traceback
                        carb.log_error(traceback.format_exc())
                        self._replicator_error_logged = True
                    # 回退到旧方法
                    self.use_replicator = False

            # 回退方法：使用 schedule_capture
            viewport = vp_util.get_active_viewport()
            if not viewport:
                return None

            # 使用 schedule_capture 和正确的 Capture delegate
            self.capture_event.clear()
            viewport.schedule_capture(self.capture_delegate)

            # 等待捕获完成
            try:
                await asyncio.wait_for(self.capture_event.wait(), timeout=0.2)
                if self.latest_frame is not None:
                    return self._resize_frame(self.latest_frame)
            except asyncio.TimeoutError:
                # 超时，返回黑帧
                if not hasattr(self, '_timeout_warning_count'):
                    self._timeout_warning_count = 0
                self._timeout_warning_count += 1

                # 只在前几次记录警告
                if self._timeout_warning_count <= 3:
                    carb.log_warn(f"Frame capture timeout (count: {self._timeout_warning_count})")

                return None

        except Exception as e:
            if not hasattr(self, '_capture_error_logged'):
                carb.log_error(f"Frame capture error: {e}")
                import traceback
                carb.log_error(traceback.format_exc())
                self._capture_error_logged = True
            return None

    def _resize_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        调整帧大小到目标分辨率（确保偶数尺寸）
        """
        # 确保输入是 uint8 格式
        if frame.dtype != np.uint8:
            if frame.dtype == np.float32 or frame.dtype == np.float64:
                frame = (frame * 255).clip(0, 255).astype(np.uint8)
            else:
                frame = frame.astype(np.uint8)

        # 检查是否需要 resize
        if frame.shape[0] != self.height or frame.shape[1] != self.width:
            try:
                from PIL import Image
                img = Image.fromarray(frame)
                img = img.resize((self.width, self.height), Image.BILINEAR)
                return np.array(img)
            except Exception as e:
                carb.log_warn(f"Resize failed: {e}")
                return self._generate_safe_frame()
        
        return frame


class CameraController:
    """相机控制器 - 与原来的相同"""

    def __init__(self):
        self.camera_distance = 10.0
        self.camera_azimuth = 45.0
        self.camera_elevation = 30.0
        self.camera_target = Gf.Vec3d(0, 0, 0)
        self.orbit_speed = 0.3
        self.pan_speed = 0.01
        self.zoom_speed = 0.1
        self.use_custom_camera = False  # 标志位：是否使用自定义相机（锁定相机）

    def orbit(self, delta_x: float, delta_y: float):
        self.camera_azimuth += delta_x * self.orbit_speed
        self.camera_elevation = max(-89, min(89, self.camera_elevation + delta_y * self.orbit_speed))
        self.camera_azimuth = self.camera_azimuth % 360
        self._update_camera()

    def pan(self, delta_x: float, delta_y: float):
        azimuth_rad = math.radians(self.camera_azimuth)
        right = Gf.Vec3d(-math.sin(azimuth_rad), math.cos(azimuth_rad), 0)
        up = Gf.Vec3d(0, 0, 1)
        self.camera_target += right * delta_x * self.pan_speed
        self.camera_target += up * delta_y * self.pan_speed
        self._update_camera()

    def zoom(self, delta: float):
        self.camera_distance = max(1.0, self.camera_distance + delta * self.zoom_speed)
        self._update_camera()

    def reset(self):
        self.camera_distance = 10.0
        self.camera_azimuth = 45.0
        self.camera_elevation = 30.0
        self.camera_target = Gf.Vec3d(0, 0, 0)
        self._update_camera()

    def _update_camera(self):
        # 如果使用自定义相机，不更新（防止覆盖用户设置）
        if self.use_custom_camera:
            return

        try:
            viewport_api = vp_util.get_active_viewport()
            if not viewport_api:
                return

            camera_path = viewport_api.get_active_camera()
            if not camera_path:
                return

            azimuth_rad = math.radians(self.camera_azimuth)
            elevation_rad = math.radians(self.camera_elevation)

            x = self.camera_distance * math.cos(elevation_rad) * math.cos(azimuth_rad)
            y = self.camera_distance * math.cos(elevation_rad) * math.sin(azimuth_rad)
            z = self.camera_distance * math.sin(elevation_rad)

            camera_pos = self.camera_target + Gf.Vec3d(x, y, z)

            stage = omni.usd.get_context().get_stage()
            if not stage:
                return

            camera_prim = stage.GetPrimAtPath(camera_path)
            if not camera_prim:
                return

            xformable = UsdGeom.Xformable(camera_prim)

            # 获取或创建 translate 操作（避免重复添加）
            translate_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeTranslate]
            if translate_ops:
                translate_op = translate_ops[0]
            else:
                translate_op = xformable.AddTranslateOp()
            translate_op.Set(camera_pos)

            # 获取或创建 rotation 操作（避免重复添加）
            rotation_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ]
            if rotation_ops:
                rotation_op = rotation_ops[0]
            else:
                rotation_op = xformable.AddRotateXYZOp()

            view_dir = (self.camera_target - camera_pos).GetNormalized()
            pitch = math.degrees(math.asin(-view_dir[2]))
            yaw = math.degrees(math.atan2(view_dir[1], view_dir[0]))
            rotation_op.Set(Gf.Vec3f(pitch, 0, yaw - 90))

        except Exception as e:
            carb.log_error(f"Camera update error: {e}")


class WebRTCServer:
    """WebRTC服务器 - 处理peer连接和信令"""

    def __init__(self, host: str = "0.0.0.0", http_port: int = 8080, ws_port: int = 30000):
        self.host = host
        self.http_port = http_port
        self.ws_port = ws_port
        self.app = None
        self.runner = None
        self.site = None

        # peer连接管理
        self.pcs: Set[RTCPeerConnection] = set()
        self.camera_controller = CameraController()

        # 视频轨道
        self.video_track = None

        # WebSocket 连接管理
        self.ws_clients: Set[web.WebSocketResponse] = set()

        # 仿真控制状态
        self.simulation_control_enabled = False  # 是否允许仿真运行
        self.auto_stop_enabled = True  # 是否自动阻止仿真运行
        self._monitor_task = None  # 监控任务
        self._reset_lock = asyncio.Lock()  # Reset锁，防止并发reset
        self._last_stop_check = 0  # 上次检查时间
        self._last_state_broadcast = 0  # 上次状态广播时间
        self._last_telemetry_broadcast = 0  # 上次遥测数据广播时间
        self._last_start_time = 0  # 上次start时间，用于防抖
        self._last_stop_time = 0  # 上次stop时间，用于防抖

        # 实验状态
        self.current_experiment_id = None  # 当前加载的实验ID

        # 实验1参数 (角动量守恒)
        self.exp1_disk_mass = 1.0  # disk质量 (kg)
        self.exp1_ring_mass = 1.0  # ring质量 (kg)
        self.exp1_disk_radius = 0.5  # disk半径 (m)
        self.exp1_ring_radius = 0.5  # ring半径 (m)
        self.exp1_disk_initial_velocity = 0.0  # disk初始角速度 (rad/s)

    async def _init_replicator_async(self, track, max_retries=3):
        """
        异步初始化 Replicator - 带重试和等待
        """
        import omni.replicator.core as rep
        import omni.kit.viewport.utility as vp_util

        retry_delay = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"🔄 尝试初始化 Replicator ({attempt}/{max_retries})...")

                # 等待 Isaac Sim 稳定
                await asyncio.sleep(retry_delay)

                # 获取视口和相机
                viewport = vp_util.get_active_viewport()
                if not viewport:
                    logger.warning("❌ 无法获取视口")
                    if attempt < max_retries:
                        continue
                    return False

                camera_path = viewport.get_active_camera()
                if not camera_path:
                    logger.warning("❌ 无法获取相机路径")
                    if attempt < max_retries:
                        continue
                    return False

                logger.info(f"✅ 相机路径: {camera_path}")

                # 清理旧资源
                if hasattr(track, 'render_product') and track.render_product:
                    try:
                        rep.destroy.render_product(track.render_product)
                    except:
                        pass

                # 创建 render product（使用偶数尺寸）
                track.render_product = rep.create.render_product(
                    camera_path,
                    (track.width, track.height)
                )

                # 创建 RGB annotator
                track.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
                track.rgb_annotator.attach([track.render_product])

                # 启用 Replicator
                track.use_replicator = True

                # 测试帧捕获
                await rep.orchestrator.step_async()
                data = track.rgb_annotator.get_data()

                if data is not None:
                    logger.info(f"✅ Replicator 初始化成功！帧: {data.shape}")
                    return True
                else:
                    logger.warning("⚠️ 帧捕获返回 None")
                    if attempt < max_retries:
                        continue
                    return False

            except Exception as e:
                logger.error(f"❌ Replicator 初始化失败: {e}")
                if attempt < max_retries:
                    continue
                return False

        return False

    async def offer(self, request):
        """处理WebRTC offer"""
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        # 创建peer connection
        pc = RTCPeerConnection()
        self.pcs.add(pc)

        logger.info(f"Created peer connection for {request.remote}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"Connection state: {pc.connectionState}")
            if pc.connectionState == "failed" or pc.connectionState == "closed":
                await self.close_peer_connection(pc)

        # 创建视频轨道（如果还没有）
        if self.video_track is None:
            self.video_track = IsaacSimVideoTrack(
                width=1280,
                height=720,
                fps=30
            )

            # 如果 Replicator 未启用，异步修复
            if not self.video_track.use_replicator:
                logger.info("⚠️ Replicator 未启用，开始异步修复...")
                success = await self._init_replicator_async(self.video_track)
                if success:
                    logger.info("✅ Replicator 已自动修复！")
                else:
                    logger.warning("⚠️ Replicator 自动修复失败，视频可能无法正常工作")

        # 添加视频轨道
        pc.addTrack(self.video_track)

        # 处理offer并创建answer
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            })
        )

    async def camera_control(self, request):
        """处理相机控制请求"""
        params = await request.json()
        action = params.get("action")

        try:
            if action == "orbit":
                self.camera_controller.orbit(
                    params.get("deltaX", 0),
                    params.get("deltaY", 0)
                )
            elif action == "pan":
                self.camera_controller.pan(
                    params.get("deltaX", 0),
                    params.get("deltaY", 0)
                )
            elif action == "zoom":
                self.camera_controller.zoom(params.get("delta", 0))
            elif action == "reset":
                self.camera_controller.reset()

            return web.Response(
                content_type="application/json",
                text=json.dumps({"status": "ok"})
            )
        except Exception as e:
            logger.error(f"Camera control error: {e}")
            return web.Response(
                content_type="application/json",
                text=json.dumps({"status": "error", "message": str(e)}),
                status=500
            )

    async def load_usd(self, request):
        """加载USD场景 - 统一加载 exp.usd，根据实验ID加载相机"""
        params = await request.json()
        experiment_id = params.get("experiment_id")  # 例如: "1", "2", "3"

        # 统一的场景文件路径（使用全局配置）
        usd_path = DEFAULT_USD_PATH

        try:
            success = omni.usd.get_context().open_stage(usd_path)

            if success:
                # 禁止仿真运行（激活监控器）
                self.simulation_control_enabled = False
                logger.info(f"📂 加载场景: {usd_path} (实验{experiment_id}) - 监控器已激活")

                # 确保停止仿真（立即停止）
                timeline = omni.timeline.get_timeline_interface()
                timeline.stop()

                # 等待场景稳定后再次确保停止（防止自动播放）
                await asyncio.sleep(0.5)
                timeline.stop()

                # 再等待一段时间，多次检查
                for i in range(3):
                    await asyncio.sleep(0.3)
                    if timeline.is_playing():
                        timeline.stop()
                        logger.info(f"⏹️ 第{i+1}次检测到自动播放，已强制停止")

                logger.info(f"✅ 场景加载完成，仿真已停止")

                # 诊断场景中的刚体对象
                self.diagnose_scene_rigid_bodies()

                # 根据实验ID设置相机参数
                if experiment_id:
                    await self._setup_camera_for_experiment(experiment_id)
                else:
                    logger.warning("⚠️ 未提供 experiment_id，使用默认相机设置")

                stage = omni.usd.get_context().get_stage()
                prim_count = len(list(stage.Traverse())) if stage else 0

                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "experiment_id": experiment_id,
                        "usd_path": usd_path,
                        "prim_count": prim_count
                    })
                )
            else:
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "error",
                        "message": f"Failed to load: {usd_path}"
                    }),
                    status=500
                )
        except Exception as e:
            logger.error(f"USD load error: {e}")
            return web.Response(
                content_type="application/json",
                text=json.dumps({"status": "error", "message": str(e)}),
                status=500
            )

    async def diagnose_video(self, request):
        """诊断视频捕获状态 - 新增接口"""
        try:
            diagnosis = {
                "status": "ok",
                "timestamp": time.time(),
                "video_track_exists": self.video_track is not None,
            }

            if self.video_track:
                track = self.video_track
                diagnosis.update({
                    "resolution": f"{track.width}x{track.height}",
                    "fps": track.fps,
                    "frame_count": track.frame_count,
                    "use_replicator": track.use_replicator,
                    "render_product": str(track.render_product) if hasattr(track, 'render_product') else None,
                    "rgb_annotator": str(track.rgb_annotator) if hasattr(track, 'rgb_annotator') else None,
                })

                # 检查视口和相机
                try:
                    viewport = vp_util.get_active_viewport()
                    diagnosis["viewport_exists"] = viewport is not None
                    if viewport:
                        camera_path = viewport.get_active_camera()
                        diagnosis["camera_path"] = str(camera_path) if camera_path else None
                except Exception as e:
                    diagnosis["viewport_error"] = str(e)

                # 检查场景
                try:
                    stage = omni.usd.get_context().get_stage()
                    diagnosis["stage_exists"] = stage is not None
                    if stage:
                        diagnosis["prim_count"] = len(list(stage.Traverse()))
                except Exception as e:
                    diagnosis["stage_error"] = str(e)

                # 尝试捕获一帧测试
                try:
                    test_frame = await track._capture_isaac_frame_async()
                    diagnosis["test_capture"] = {
                        "success": test_frame is not None,
                        "shape": test_frame.shape if test_frame is not None else None,
                        "dtype": str(test_frame.dtype) if test_frame is not None else None,
                    }
                except Exception as e:
                    diagnosis["test_capture"] = {
                        "success": False,
                        "error": str(e)
                    }

            logger.info(f"📊 视频诊断结果: {json.dumps(diagnosis, indent=2)}")

            return web.Response(
                content_type="application/json",
                text=json.dumps(diagnosis, indent=2)
            )

        except Exception as e:
            logger.error(f"诊断失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.Response(
                content_type="application/json",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                }),
                status=500
            )

    async def reinit_video(self, request):
        """重新初始化视频轨道的 Replicator（用于场景切换后）"""
        try:
            if self.video_track is None:
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "error",
                        "message": "视频轨道尚未创建，请先连接 WebRTC"
                    }),
                    status=400
                )

            track = self.video_track
            logger.info("🔧 重新初始化 Replicator...")

            # 使用异步初始化方法
            success = await self._init_replicator_async(track)

            if success:
                # 重置帧计数
                track.frame_count = 0

                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "message": "Replicator 已重新初始化",
                        "resolution": f"{track.width}x{track.height}"
                    })
                )
            else:
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "error",
                        "message": "Replicator 重新初始化失败，请检查场景和相机"
                    }),
                    status=500
                )

        except Exception as e:
            logger.error(f"Replicator 重新初始化失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.Response(
                content_type="application/json",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                }),
                status=500
            )

    async def simulation_control(self, request):
        """控制仿真时间轴（播放/暂停/停止/重置）"""
        params = await request.json()
        action = params.get("action")

        try:
            timeline = omni.timeline.get_timeline_interface()

            if action == "play":
                timeline.play()
                is_playing = timeline.is_playing()
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "action": "play",
                        "is_playing": is_playing
                    })
                )
            elif action == "pause":
                timeline.pause()
                is_playing = timeline.is_playing()
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "action": "pause",
                        "is_playing": is_playing
                    })
                )
            elif action == "stop":
                timeline.stop()
                is_playing = timeline.is_playing()
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "action": "stop",
                        "is_playing": is_playing
                    })
                )
            elif action == "reset":
                # 停止并重置到初始帧
                timeline.stop()
                timeline.set_current_time(timeline.get_start_time())
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "action": "reset",
                        "current_time": timeline.get_current_time()
                    })
                )
            elif action == "status":
                # 获取当前状态
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "ok",
                        "is_playing": timeline.is_playing(),
                        "current_time": timeline.get_current_time(),
                        "start_time": timeline.get_start_time(),
                        "end_time": timeline.get_end_time(),
                        "time_codes_per_second": timeline.get_time_codes_per_seconds()
                    })
                )
            else:
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({
                        "status": "error",
                        "message": f"Unknown action: {action}. Valid actions: play, pause, stop, reset, status"
                    }),
                    status=400
                )
        except Exception as e:
            logger.error(f"Simulation control error: {e}")
            return web.Response(
                content_type="application/json",
                text=json.dumps({"status": "error", "message": str(e)}),
                status=500
            )

    async def websocket_handler(self, request):
        """处理 WebSocket 连接 - 用于控制命令"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self.ws_clients.add(ws)
        logger.info(f"🔌 WebSocket client connected (total: {len(self.ws_clients)})")

        # 确保 timeline 停止（防止自动播放）
        try:
            timeline = omni.timeline.get_timeline_interface()
            if timeline.is_playing():
                timeline.stop()
                logger.info("⏹️ Stopped auto-playing timeline on WebSocket connect")
        except Exception as e:
            logger.warning(f"Failed to stop timeline: {e}")

        # 发送欢迎消息
        await ws.send_json({
            "type": "connected",
            "message": "Connected to Isaac Sim WebSocket server"
        })

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        msg_type = data.get("type")

                        logger.info(f"📩 Received WS message: {msg_type}")

                        # 处理不同类型的消息
                        if msg_type == "start_simulation":
                            await self._handle_start_simulation(ws)
                        elif msg_type == "pause_simulation":
                            await self._handle_pause_simulation(ws)
                        elif msg_type == "resume_simulation":
                            await self._handle_resume_simulation(ws)
                        elif msg_type == "stop_simulation":
                            await self._handle_stop_simulation(ws)
                        elif msg_type == "reset":
                            await self._handle_reset_simulation(ws)
                        elif msg_type == "step_simulation":
                            steps = data.get("steps", 1)
                            await self._handle_step_simulation(ws, steps)
                        elif msg_type == "load_usd":
                            experiment_id = data.get("experiment_id")
                            await self._handle_load_usd_ws(ws, experiment_id)
                        elif msg_type == "enter_experiment":
                            # 进入实验（不重新加载场景，只切换相机和reset物理状态）
                            experiment_id = data.get("experiment_id")
                            logger.info(f"📩 收到 enter_experiment 消息:")
                            logger.info(f"   完整消息: {data}")
                            logger.info(f"   提取的 experiment_id: {repr(experiment_id)}")
                            logger.info(f"   类型: {type(experiment_id)}")
                            logger.info(f"   布尔值: {bool(experiment_id)}")
                            await self._handle_enter_experiment(ws, experiment_id)
                        elif msg_type == "get_simulation_state":
                            await self._handle_get_simulation_state(ws)

                        # ========== 实验1参数设置命令 ==========
                        elif msg_type == "set_mass":
                            value = data.get("value", 1.0)
                            await self._handle_set_mass(ws, value)
                        elif msg_type == "set_disk_mass":
                            value = data.get("value", 1.0)
                            await self._handle_set_disk_mass(ws, value)
                        elif msg_type == "set_ring_mass":
                            value = data.get("value", 1.0)
                            await self._handle_set_ring_mass(ws, value)
                        elif msg_type == "set_initial_velocity":
                            value = data.get("value", 0.0)
                            await self._handle_set_initial_velocity(ws, value)

                        else:
                            logger.warning(f"⚠️ Unknown message type: {msg_type}")
                            await ws.send_json({
                                "type": "error",
                                "message": f"Unknown message type: {msg_type}"
                            })

                    except json.JSONDecodeError as e:
                        logger.error(f"❌ JSON decode error: {e}")
                        await ws.send_json({
                            "type": "error",
                            "message": "Invalid JSON"
                        })
                    except Exception as e:
                        logger.error(f"❌ Message handling error: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        await ws.send_json({
                            "type": "error",
                            "message": str(e)
                        })

                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")

        finally:
            self.ws_clients.discard(ws)
            logger.info(f"🔌 WebSocket client disconnected (remaining: {len(self.ws_clients)})")

        return ws

    # ========== WebSocket 消息处理器 ==========

    async def _handle_start_simulation(self, ws):
        """处理开始仿真命令 - 带防抖保护"""
        try:
            import time
            current_time = time.time()

            # 防抖：如果距离上次start不到0.3秒，忽略
            if current_time - self._last_start_time < 0.3:
                logger.debug("⏸️ Start命令被防抖过滤（距离上次start太近）")
                return

            self._last_start_time = current_time

            # 允许仿真运行
            self.simulation_control_enabled = True
            logger.info("▶️ 用户启动仿真 - 监控器已暂停")

            timeline = omni.timeline.get_timeline_interface()
            timeline.play()
            is_playing = timeline.is_playing()

            await ws.send_json({
                "type": "simulation_started",
                "is_playing": is_playing
            })

            # 广播给所有客户端
            await self._broadcast_ws({
                "type": "simulation_started",
                "is_playing": is_playing
            }, exclude=ws)

        except Exception as e:
            logger.error(f"Start simulation error: {e}")
            await ws.send_json({
                "type": "error",
                "message": str(e)
            })

    async def _handle_pause_simulation(self, ws):
        """处理暂停仿真命令"""
        try:
            # 暂停时仍然保持control_enabled=True (允许恢复)
            timeline = omni.timeline.get_timeline_interface()
            timeline.pause()
            is_playing = timeline.is_playing()

            await ws.send_json({
                "type": "simulation_paused",
                "is_playing": is_playing
            })

            await self._broadcast_ws({
                "type": "simulation_paused",
                "is_playing": is_playing
            }, exclude=ws)

        except Exception as e:
            logger.error(f"Pause simulation error: {e}")
            await ws.send_json({
                "type": "error",
                "message": str(e)
            })

    async def _handle_resume_simulation(self, ws):
        """处理恢复仿真命令"""
        try:
            # 确保允许仿真运行
            self.simulation_control_enabled = True

            timeline = omni.timeline.get_timeline_interface()
            timeline.play()
            is_playing = timeline.is_playing()

            await ws.send_json({
                "type": "simulation_resumed",
                "is_playing": is_playing
            })

            await self._broadcast_ws({
                "type": "simulation_resumed",
                "is_playing": is_playing
            }, exclude=ws)

        except Exception as e:
            logger.error(f"Resume simulation error: {e}")
            await ws.send_json({
                "type": "error",
                "message": str(e)
            })

    async def _handle_stop_simulation(self, ws):
        """处理停止仿真命令 - 带防抖保护"""
        try:
            import time
            current_time = time.time()

            # 防抖：如果距离上次stop不到0.3秒，忽略
            if current_time - self._last_stop_time < 0.3:
                logger.debug("⏸️ Stop命令被防抖过滤（距离上次stop太近）")
                return

            self._last_stop_time = current_time

            # 停止后禁止仿真运行（监控器将阻止自动播放）
            self.simulation_control_enabled = False
            logger.info("⏹️ 用户停止仿真 - 监控器已激活")

            timeline = omni.timeline.get_timeline_interface()
            timeline.stop()
            is_playing = timeline.is_playing()

            await ws.send_json({
                "type": "simulation_stopped",
                "is_playing": is_playing
            })

            await self._broadcast_ws({
                "type": "simulation_stopped",
                "is_playing": is_playing
            }, exclude=ws)

        except Exception as e:
            logger.error(f"Stop simulation error: {e}")
            await ws.send_json({
                "type": "error",
                "message": str(e)
            })

    async def _handle_reset_simulation(self, ws):
        """处理重置仿真命令 - 使用锁防止并发reset"""
        # 使用锁防止并发reset导致的问题
        async with self._reset_lock:
            try:
                # 重置时禁止仿真运行
                self.simulation_control_enabled = False
                logger.info("🔄 用户重置仿真 - 监控器已激活")

                timeline = omni.timeline.get_timeline_interface()

                # 确保停止仿真
                if timeline.is_playing():
                    timeline.stop()
                    # 等待停止完成
                    await asyncio.sleep(0.1)

                # 重置时间线
                timeline.set_current_time(timeline.get_start_time())

                # 等待场景稳定
                await asyncio.sleep(0.3)

                # 重新应用实验1的物理参数
                if self.current_experiment_id == "1":
                    try:
                        await self._apply_exp1_params()
                        logger.info("✅ 实验1参数已重新应用")
                    except Exception as param_error:
                        logger.error(f"⚠️ 应用参数时出错: {param_error}")
                        # 即使参数应用失败也继续，避免卡住

                # 等待一帧，确保所有更改生效
                await asyncio.sleep(0.05)

                await ws.send_json({
                    "type": "reset_complete",
                    "current_time": timeline.get_current_time()
                })

                await self._broadcast_ws({
                    "type": "reset_complete",
                    "current_time": timeline.get_current_time()
                }, exclude=ws)

            except Exception as e:
                logger.error(f"Reset simulation error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await ws.send_json({
                    "type": "error",
                    "message": str(e)
                })

    async def _handle_step_simulation(self, ws, steps: int):
        """处理单步仿真命令"""
        try:
            timeline = omni.timeline.get_timeline_interface()

            # 单步执行
            for _ in range(steps):
                # 执行一帧
                await asyncio.sleep(0.016)  # 约60fps

            await ws.send_json({
                "type": "simulation_stepped",
                "steps": steps,
                "current_time": timeline.get_current_time()
            })

        except Exception as e:
            logger.error(f"Step simulation error: {e}")
            await ws.send_json({
                "type": "error",
                "message": str(e)
            })

    async def _handle_load_usd_ws(self, ws, experiment_id: str):
        """处理加载 USD 场景命令（WebSocket版本）- 统一加载 exp.usd，根据实验ID加载相机"""
        # 统一的场景文件路径（使用全局配置）
        usd_path = DEFAULT_USD_PATH

        try:
            success = omni.usd.get_context().open_stage(usd_path)

            if success:
                # 设置当前实验ID
                self.current_experiment_id = experiment_id
                logger.info(f"✅ 当前实验ID设置为: {experiment_id}")

                # 禁止仿真运行（激活监控器）
                self.simulation_control_enabled = False
                logger.info(f"📂 加载场景(WS): {usd_path} (实验{experiment_id}) - 监控器已激活")

                # 确保停止仿真（立即停止）
                timeline = omni.timeline.get_timeline_interface()
                timeline.stop()

                # 等待场景稳定后再次确保停止（防止自动播放）
                await asyncio.sleep(0.5)
                timeline.stop()

                # 再等待一段时间，多次检查
                for i in range(3):
                    await asyncio.sleep(0.3)
                    if timeline.is_playing():
                        timeline.stop()
                        logger.info(f"⏹️ 第{i+1}次检测到自动播放，已强制停止")

                logger.info(f"✅ 场景加载完成，仿真已停止")

                # 诊断场景中的刚体对象
                self.diagnose_scene_rigid_bodies()

                # 🔄 重置所有刚体的初始速度为0（避免实验间互相影响）
                await self._reset_all_rigid_bodies_velocity()

                # 根据实验ID设置相机参数
                if experiment_id:
                    await self._setup_camera_for_experiment(experiment_id)
                else:
                    logger.warning("⚠️ 未提供 experiment_id，使用默认相机设置")

                stage = omni.usd.get_context().get_stage()
                prim_count = len(list(stage.Traverse())) if stage else 0

                await ws.send_json({
                    "type": "usd_loaded",
                    "experiment_id": experiment_id,
                    "usd_path": usd_path,
                    "prim_count": prim_count
                })

                await self._broadcast_ws({
                    "type": "usd_loaded",
                    "experiment_id": experiment_id,
                    "usd_path": usd_path,
                    "prim_count": prim_count
                }, exclude=ws)
            else:
                await ws.send_json({
                    "type": "error",
                    "message": f"Failed to load: {usd_path}"
                })

        except Exception as e:
            logger.error(f"USD load error: {e}")
            await ws.send_json({
                "type": "error",
                "message": str(e)
            })

    async def _handle_get_simulation_state(self, ws):
        """处理获取仿真状态命令"""
        try:
            timeline = omni.timeline.get_timeline_interface()

            await ws.send_json({
                "type": "simulation_state",
                "running": timeline.is_playing(),
                "paused": not timeline.is_playing() and timeline.get_current_time() > timeline.get_start_time(),
                "time": timeline.get_current_time(),
                "step": 0  # 可以根据需要实现步数计数
            })

        except Exception as e:
            logger.error(f"Get simulation state error: {e}")
            await ws.send_json({
                "type": "error",
                "message": str(e)
            })

    async def _handle_enter_experiment(self, ws, experiment_id: str):
        """
        处理进入实验命令（不重新加载场景，仅切换相机和reset物理状态）

        工作流程：
        1. 停止并重置仿真（时间轴归零）
        2. 重置所有刚体速度为0（清除上一个实验的物理状态）
        3. 切换相机到目标实验视角
        4. 锁定仿真（等待用户点击Run按钮）

        适用场景：
        - 从实验选择界面进入某个实验
        - exp.usd已经加载，只需要准备特定实验的环境
        """
        try:
            # 调试：显示接收到的参数
            logger.info(f"📥 _handle_enter_experiment 接收到参数:")
            logger.info(f"   experiment_id = {repr(experiment_id)}")
            logger.info(f"   type(experiment_id) = {type(experiment_id)}")
            logger.info(f"   bool(experiment_id) = {bool(experiment_id)}")

            # 验证 experiment_id
            if not experiment_id:
                logger.error("❌ experiment_id 为空或 None!")
                await ws.send_json({
                    "type": "error",
                    "message": "experiment_id is required"
                })
                return

            logger.info(f"🚀 进入实验 {experiment_id}（不重新加载USD）")

            # 设置当前实验ID
            old_experiment_id = self.current_experiment_id
            self.current_experiment_id = experiment_id

            # 禁止仿真运行（激活监控器）
            self.simulation_control_enabled = False
            logger.info(f"🔒 仿真已锁定 - 等待用户启动")

            # 确保停止仿真
            timeline = omni.timeline.get_timeline_interface()
            was_playing = timeline.is_playing()
            if was_playing:
                timeline.stop()
                logger.info("⏹️ 已停止仿真")

            # 重置时间轴到初始时间
            timeline.set_current_time(timeline.get_start_time())

            # 等待场景稳定
            await asyncio.sleep(0.3)

            # 🔄 重置所有刚体的初始速度为0（清除物理状态）
            logger.info("🔄 正在重置物理状态...")
            await self._reset_all_rigid_bodies_velocity()

            # 切换相机到对应实验
            logger.info(f"📷 正在加载实验 {experiment_id} 的相机配置...")
            await self._setup_camera_for_experiment(experiment_id)

            # 发送成功响应
            await ws.send_json({
                "type": "experiment_entered",
                "experiment_id": experiment_id,
                "old_experiment_id": old_experiment_id,
                "status": "ok"
            })

            # 广播给其他客户端
            await self._broadcast_ws({
                "type": "experiment_entered",
                "experiment_id": experiment_id,
                "old_experiment_id": old_experiment_id
            }, exclude=ws)

            logger.info(f"✅ 成功进入实验 {experiment_id}，准备就绪")

        except Exception as e:
            logger.error(f"❌ 进入实验失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ws.send_json({
                "type": "error",
                "message": f"Failed to enter experiment: {str(e)}"
            })

    # ========== 实验1参数设置处理器 ==========

    async def _apply_exp1_params(self):
        """
        应用实验1的所有物理参数（在 reset 后调用）
        改进版：添加重试机制和更好的错误处理
        """
        max_retries = 3
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                logger.info(f"🔧 应用实验1参数 (尝试 {attempt + 1}/{max_retries})...")

                stage = omni.usd.get_context().get_stage()
                if not stage:
                    logger.warning("⚠️ Stage not available")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    return

                from pxr import UsdPhysics

                # 设置 disk 的质量
                disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
                if disk_prim and disk_prim.IsValid():
                    mass_api = UsdPhysics.MassAPI.Apply(disk_prim)
                    mass_api.GetMassAttr().Set(self.exp1_disk_mass)
                    logger.info(f"✅ Disk 质量: {self.exp1_disk_mass} kg")
                else:
                    logger.warning("⚠️ Disk prim not found")

                # 设置 ring 的质量
                ring_prim = stage.GetPrimAtPath("/World/exp1/ring")
                if ring_prim and ring_prim.IsValid():
                    mass_api = UsdPhysics.MassAPI.Apply(ring_prim)
                    mass_api.GetMassAttr().Set(self.exp1_ring_mass)
                    logger.info(f"✅ Ring 质量: {self.exp1_ring_mass} kg")
                else:
                    logger.warning("⚠️ Ring prim not found")

                # 设置 disk 的初始角速度
                if self.exp1_disk_initial_velocity != 0.0:
                    if not hasattr(self, '_dc_interface') or self._dc_interface is None:
                        from omni.isaac.dynamic_control import _dynamic_control
                        self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()

                    if self._dc_interface and disk_prim and disk_prim.IsValid():
                        disk_path = "/World/exp1/disk"
                        rb = self._dc_interface.get_rigid_body(disk_path)

                        from omni.isaac.dynamic_control import _dynamic_control
                        if rb != _dynamic_control.INVALID_HANDLE:
                            angular_velocity = [0.0, 0.0, self.exp1_disk_initial_velocity]
                            self._dc_interface.set_rigid_body_angular_velocity(rb, angular_velocity)
                            logger.info(f"✅ Disk 初始角速度: {self.exp1_disk_initial_velocity} rad/s")
                        else:
                            logger.warning("⚠️ 无法获取 disk 刚体句柄")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue

                logger.info("✅ 实验1参数应用完成")
                return  # 成功，退出重试循环

            except Exception as e:
                logger.error(f"❌ 应用实验1参数失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f"⏳ 等待 {retry_delay}s 后重试...")
                    await asyncio.sleep(retry_delay)
                else:
                    import traceback
                    logger.error(traceback.format_exc())
                    raise  # 最后一次尝试失败，抛出异常

    async def _handle_set_mass(self, ws, value: float):
        """
        设置实验1的质量参数
        同时设置 disk 和 ring 的质量
        """
        try:
            logger.info(f"🔧 设置质量: {value} kg")

            # 存储参数
            self.exp1_disk_mass = value
            self.exp1_ring_mass = value

            # 获取舞台
            stage = omni.usd.get_context().get_stage()
            if not stage:
                raise Exception("Stage not available")

            # 设置 disk 的质量
            disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
            if disk_prim and disk_prim.IsValid():
                from pxr import UsdPhysics
                mass_api = UsdPhysics.MassAPI.Apply(disk_prim)
                mass_api.GetMassAttr().Set(value)
                logger.info(f"✅ Disk 质量设置为: {value} kg")
            else:
                logger.warning("⚠️ Disk prim not found at /World/exp1/disk")

            # 设置 ring 的质量
            ring_prim = stage.GetPrimAtPath("/World/exp1/ring")
            if ring_prim and ring_prim.IsValid():
                from pxr import UsdPhysics
                mass_api = UsdPhysics.MassAPI.Apply(ring_prim)
                mass_api.GetMassAttr().Set(value)
                logger.info(f"✅ Ring 质量设置为: {value} kg")
            else:
                logger.warning("⚠️ Ring prim not found at /World/exp1/ring")

            # 确认消息
            await ws.send_json({
                "type": "param_updated",
                "param": "mass",
                "value": value,
                "status": "ok"
            })

        except Exception as e:
            logger.error(f"❌ 设置质量失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ws.send_json({
                "type": "error",
                "message": f"Failed to set mass: {str(e)}"
            })

    async def _handle_set_disk_mass(self, ws, value: float):
        """
        设置实验1的 disk 质量
        """
        try:
            logger.info(f"🔧 设置 Disk 质量: {value} kg")

            # 存储参数
            self.exp1_disk_mass = value

            # 获取舞台
            stage = omni.usd.get_context().get_stage()
            if not stage:
                raise Exception("Stage not available")

            # 设置 disk 的质量
            disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
            if disk_prim and disk_prim.IsValid():
                from pxr import UsdPhysics
                mass_api = UsdPhysics.MassAPI.Apply(disk_prim)
                mass_api.GetMassAttr().Set(value)
                logger.info(f"✅ Disk 质量设置为: {value} kg")
            else:
                logger.warning("⚠️ Disk prim not found at /World/exp1/disk")

            # 确认消息
            await ws.send_json({
                "type": "param_updated",
                "param": "disk_mass",
                "value": value,
                "status": "ok"
            })

        except Exception as e:
            logger.error(f"❌ 设置 Disk 质量失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ws.send_json({
                "type": "error",
                "message": f"Failed to set disk mass: {str(e)}"
            })

    async def _handle_set_ring_mass(self, ws, value: float):
        """
        设置实验1的 ring 质量
        """
        try:
            logger.info(f"🔧 设置 Ring 质量: {value} kg")

            # 存储参数
            self.exp1_ring_mass = value

            # 获取舞台
            stage = omni.usd.get_context().get_stage()
            if not stage:
                raise Exception("Stage not available")

            # 设置 ring 的质量
            ring_prim = stage.GetPrimAtPath("/World/exp1/ring")
            if ring_prim and ring_prim.IsValid():
                from pxr import UsdPhysics
                mass_api = UsdPhysics.MassAPI.Apply(ring_prim)
                mass_api.GetMassAttr().Set(value)
                logger.info(f"✅ Ring 质量设置为: {value} kg")
            else:
                logger.warning("⚠️ Ring prim not found at /World/exp1/ring")

            # 确认消息
            await ws.send_json({
                "type": "param_updated",
                "param": "ring_mass",
                "value": value,
                "status": "ok"
            })

        except Exception as e:
            logger.error(f"❌ 设置 Ring 质量失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ws.send_json({
                "type": "error",
                "message": f"Failed to set ring mass: {str(e)}"
            })

    async def _handle_set_initial_velocity(self, ws, value: float):
        """
        设置实验1的 disk 初始角速度
        """
        try:
            logger.info(f"🔧 设置 disk 初始角速度: {value} rad/s")

            # 存储参数
            self.exp1_disk_initial_velocity = value

            # 获取舞台
            stage = omni.usd.get_context().get_stage()
            if not stage:
                raise Exception("Stage not available")

            # 设置 disk 的角速度
            disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
            if disk_prim and disk_prim.IsValid():
                # 使用 Dynamic Control 接口设置角速度
                if not hasattr(self, '_dc_interface'):
                    from omni.isaac.dynamic_control import _dynamic_control
                    self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()

                if self._dc_interface:
                    disk_path = "/World/exp1/disk"
                    rb = self._dc_interface.get_rigid_body(disk_path)

                    from omni.isaac.dynamic_control import _dynamic_control
                    if rb != _dynamic_control.INVALID_HANDLE:
                        # 设置角速度 (绕 Z 轴旋转)
                        angular_velocity = [0.0, 0.0, value]
                        self._dc_interface.set_rigid_body_angular_velocity(rb, angular_velocity)
                        logger.info(f"✅ Disk 初始角速度设置为: {value} rad/s (Z轴)")
                    else:
                        logger.warning("⚠️ 无法获取 disk 刚体句柄")
                else:
                    logger.warning("⚠️ Dynamic Control 接口不可用")
            else:
                logger.warning("⚠️ Disk prim not found at /World/exp1/disk")

            # 确认消息
            await ws.send_json({
                "type": "param_updated",
                "param": "initial_velocity",
                "value": value,
                "status": "ok"
            })

        except Exception as e:
            logger.error(f"❌ 设置初始角速度失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ws.send_json({
                "type": "error",
                "message": f"Failed to set initial velocity: {str(e)}"
            })

    def get_angular_velocities(self):
        """获取ring和disk的角速度 - 使用 Dynamic Control 接口"""
        try:
            from pxr import UsdPhysics

            stage = omni.usd.get_context().get_stage()
            if not stage:
                return None, None

            # 初始化 Dynamic Control 接口（只初始化一次）
            if not hasattr(self, '_dc_interface'):
                try:
                    from omni.isaac.dynamic_control import _dynamic_control
                    self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()
                    if self._dc_interface:
                        logger.info("✅ Dynamic Control 接口初始化成功")
                    else:
                        logger.error("❌ Dynamic Control 接口初始化失败")
                        self._dc_interface = None
                except ImportError as e:
                    logger.error(f"❌ 无法导入 Dynamic Control: {e}")
                    self._dc_interface = None

            # 如果 DC 接口不可用，返回 0
            if not self._dc_interface:
                return 0.0, 0.0

            # 尝试多个可能的路径
            ring_paths = ["/World/ring", "/World/Robot/ring", "/Robot/ring", "/ring"]
            disk_paths = ["/World/disk", "/World/Robot/disk", "/Robot/disk", "/disk"]

            ring_prim = None
            disk_prim = None
            ring_path = None
            disk_path = None

            # 查找ring
            for path in ring_paths:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    ring_prim = prim
                    ring_path = path
                    if not hasattr(self, '_ring_path_logged'):
                        logger.info(f"✅ 找到 ring at: {path}")
                        self._ring_path_logged = True
                    break

            # 查找disk
            for path in disk_paths:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    disk_prim = prim
                    disk_path = path
                    if not hasattr(self, '_disk_path_logged'):
                        logger.info(f"✅ 找到 disk at: {path}")
                        self._disk_path_logged = True
                    break

            # 如果没找到，尝试遍历场景查找
            if not ring_prim or not disk_prim:
                if not hasattr(self, '_search_logged'):
                    logger.warning("⚠️ 未找到ring/disk，尝试搜索场景...")
                    for prim in stage.Traverse():
                        prim_name = prim.GetName().lower()
                        if not ring_prim and 'ring' in prim_name:
                            # 检查是否有刚体API
                            if UsdPhysics.RigidBodyAPI(prim):
                                ring_prim = prim
                                ring_path = str(prim.GetPath())
                                logger.info(f"✅ 通过搜索找到 ring: {ring_path}")
                        if not disk_prim and 'disk' in prim_name and 'ring' not in prim_name:
                            if UsdPhysics.RigidBodyAPI(prim):
                                disk_prim = prim
                                disk_path = str(prim.GetPath())
                                logger.info(f"✅ 通过搜索找到 disk: {disk_path}")
                        if ring_prim and disk_prim:
                            break
                    self._search_logged = True

            ring_angular_vel = 0.0
            disk_angular_vel = 0.0

            from omni.isaac.dynamic_control import _dynamic_control
            dc = self._dc_interface

            # 获取 ring 角速度
            if ring_prim and ring_prim.IsValid() and ring_path:
                try:
                    # 获取刚体句柄
                    rb = dc.get_rigid_body(ring_path)
                    if rb != _dynamic_control.INVALID_HANDLE:
                        # 获取角速度
                        angular_vel = dc.get_rigid_body_angular_velocity(rb)

                        if angular_vel is not None:
                            # 计算角速度的模（rad/s）
                            ring_angular_vel = math.sqrt(
                                angular_vel[0]**2 +
                                angular_vel[1]**2 +
                                angular_vel[2]**2
                            )

                            if not hasattr(self, '_ring_vel_success_logged'):
                                logger.info(f"✅ Ring angular velocity: {ring_angular_vel:.3f} rad/s")
                                self._ring_vel_success_logged = True
                    else:
                        if not hasattr(self, '_ring_handle_error_logged'):
                            logger.warning(f"⚠️ 无法获取 ring 刚体句柄")
                            self._ring_handle_error_logged = True

                except Exception as e:
                    if not hasattr(self, '_ring_error_logged'):
                        logger.error(f"Failed to get ring angular velocity: {e}")
                        self._ring_error_logged = True

            # 获取 disk 角速度
            if disk_prim and disk_prim.IsValid() and disk_path:
                try:
                    # 获取刚体句柄
                    rb = dc.get_rigid_body(disk_path)
                    if rb != _dynamic_control.INVALID_HANDLE:
                        # 获取角速度
                        angular_vel = dc.get_rigid_body_angular_velocity(rb)

                        if angular_vel is not None:
                            # 计算角速度的模（rad/s）
                            disk_angular_vel = math.sqrt(
                                angular_vel[0]**2 +
                                angular_vel[1]**2 +
                                angular_vel[2]**2
                            )

                            if not hasattr(self, '_disk_vel_success_logged'):
                                logger.info(f"✅ Disk angular velocity: {disk_angular_vel:.3f} rad/s")
                                self._disk_vel_success_logged = True
                    else:
                        if not hasattr(self, '_disk_handle_error_logged'):
                            logger.warning(f"⚠️ 无法获取 disk 刚体句柄")
                            self._disk_handle_error_logged = True

                except Exception as e:
                    if not hasattr(self, '_disk_error_logged'):
                        logger.error(f"Failed to get disk angular velocity: {e}")
                        self._disk_error_logged = True

            return ring_angular_vel, disk_angular_vel

        except Exception as e:
            if not hasattr(self, '_get_vel_error_logged'):
                logger.error(f"Get angular velocities error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self._get_vel_error_logged = True
            return None, None

    def diagnose_scene_rigid_bodies(self):
        """诊断场景中的刚体对象（用于调试角速度获取）"""
        try:
            from pxr import UsdPhysics

            stage = omni.usd.get_context().get_stage()
            if not stage:
                logger.warning("⚠️ Stage not available")
                return

            logger.info("=" * 60)
            logger.info("🔍 场景刚体对象诊断")
            logger.info("=" * 60)

            rigid_bodies = []

            # 遍历场景查找所有刚体
            for prim in stage.Traverse():
                rigid_body_api = UsdPhysics.RigidBodyAPI(prim)
                if rigid_body_api:
                    prim_path = str(prim.GetPath())
                    prim_name = prim.GetName()
                    rigid_bodies.append((prim_path, prim_name))

            if rigid_bodies:
                logger.info(f"✅ 找到 {len(rigid_bodies)} 个刚体对象:")
                for path, name in rigid_bodies:
                    logger.info(f"   - {name} ({path})")
            else:
                logger.warning("⚠️ 场景中没有找到刚体对象！")

            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"场景诊断失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _reset_all_rigid_bodies_velocity(self):
        """
        重置场景中所有刚体的线速度和角速度为0
        用于在切换实验时避免前一个实验的物理状态影响新实验
        """
        try:
            from pxr import UsdPhysics

            stage = omni.usd.get_context().get_stage()
            if not stage:
                logger.warning("⚠️ Stage 不可用，无法重置速度")
                return

            # 初始化 Dynamic Control 接口
            if not hasattr(self, '_dc_interface') or not self._dc_interface:
                try:
                    from omni.isaac.dynamic_control import _dynamic_control
                    self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()
                except Exception as e:
                    logger.warning(f"⚠️ 无法初始化 Dynamic Control 接口: {e}")
                    return

            if not self._dc_interface:
                logger.warning("⚠️ Dynamic Control 接口不可用")
                return

            from omni.isaac.dynamic_control import _dynamic_control
            dc = self._dc_interface
            reset_count = 0

            # 遍历场景查找所有刚体并重置速度
            for prim in stage.Traverse():
                rigid_body_api = UsdPhysics.RigidBodyAPI(prim)
                if rigid_body_api:
                    prim_path = str(prim.GetPath())

                    try:
                        # 获取刚体句柄
                        rb = dc.get_rigid_body(prim_path)

                        if rb != _dynamic_control.INVALID_HANDLE:
                            # 设置线速度为0
                            dc.set_rigid_body_linear_velocity(rb, [0.0, 0.0, 0.0])
                            # 设置角速度为0
                            dc.set_rigid_body_angular_velocity(rb, [0.0, 0.0, 0.0])
                            reset_count += 1

                    except Exception as e:
                        # 忽略单个刚体的错误，继续处理其他刚体
                        pass

            logger.info(f"✅ 已重置 {reset_count} 个刚体的速度为0")

        except Exception as e:
            logger.error(f"❌ 重置刚体速度失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _setup_camera_for_experiment(self, experiment_id: str):
        """
        根据实验ID加载对应的相机配置
        从 camera/usd{N}.py 文件中执行相机设置

        Args:
            experiment_id: 实验编号 "1" 到 "8"
        """
        try:
            # 🔒 锁定相机控制器，防止自动更新覆盖自定义相机设置
            self.camera_controller.use_custom_camera = True
            logger.info(f"🔒 已锁定相机控制器 (实验 {experiment_id})，防止自动覆盖")

            # 等待场景完全加载
            await asyncio.sleep(0.5)

            # 构建相机配置文件路径（使用相对路径）
            camera_script_path = os.path.join(CAMERA_SCRIPT_DIR, f"usd{experiment_id}.py")

            # 检查文件是否存在
            if not os.path.exists(camera_script_path):
                logger.warning(f"⚠️ 相机配置文件不存在: {camera_script_path}")
                logger.info("📷 使用默认相机设置")
                return

            logger.info(f"📷 加载实验{experiment_id}的相机配置: {camera_script_path}")

            # 读取并执行相机配置脚本
            with open(camera_script_path, 'r', encoding='utf-8') as f:
                camera_script_code = f.read()

            # 执行脚本（脚本内部会调用 set_camera() 或 set_my_camera()）
            try:
                # 创建执行命名空间
                # 使用同一个字典作为 globals 和 locals，确保函数定义和调用在同一作用域
                exec_namespace = {
                    'omni': omni,
                    'UsdGeom': UsdGeom,
                    'Gf': Gf,
                    'vp_util': vp_util,  # 添加 vp_util 模块
                    'print': logger.info  # 重定向 print 到 logger
                }

                logger.info(f"📝 开始执行相机脚本: {camera_script_path}")
                logger.info(f"📝 脚本内容预览: {camera_script_code[:200]}...")

                # 使用相同的命名空间作为 globals 和 locals
                exec(camera_script_code, exec_namespace, exec_namespace)
                logger.info(f"✅ 实验{experiment_id}的相机配置已成功应用！")

                # 🔍 验证相机设置是否真的被应用了
                try:
                    viewport = vp_util.get_active_viewport()
                    if viewport:
                        camera_path = viewport.get_active_camera()
                        if camera_path:
                            stage = omni.usd.get_context().get_stage()
                            camera_prim = stage.GetPrimAtPath(camera_path)
                            if camera_prim and camera_prim.IsValid():
                                camera = UsdGeom.Camera(camera_prim)
                                xformable = UsdGeom.Xformable(camera_prim)

                                # 获取当前相机参数
                                focal_length = camera.GetFocalLengthAttr().Get()
                                xform_ops = xformable.GetOrderedXformOps()

                                logger.info(f"🔍 验证相机设置:")
                                logger.info(f"   相机路径: {camera_path}")
                                logger.info(f"   焦距: {focal_length} mm")

                                for op in xform_ops:
                                    if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                                        pos = op.Get()
                                        logger.info(f"   位置: ({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f})")
                                    elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                                        rot = op.Get()
                                        logger.info(f"   旋转: ({rot[0]:.2f}°, {rot[1]:.2f}°, {rot[2]:.2f}°)")
                except Exception as verify_error:
                    logger.warning(f"⚠️ 相机验证失败: {verify_error}")

            except Exception as exec_error:
                logger.error(f"❌ 相机脚本执行失败: {exec_error}")
                import traceback
                logger.error(traceback.format_exc())
                # 尝试手动调用相机设置（作为fallback）
                logger.info(f"⚠️ 尝试手动执行相机设置函数...")

        except FileNotFoundError as e:
            logger.error(f"❌ 相机配置文件未找到: {e}")
            logger.info("📷 使用默认相机设置")
        except Exception as e:
            logger.error(f"❌ 加载相机配置失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.info("📷 使用默认相机设置")

    async def _broadcast_ws(self, message: dict, exclude=None):
        """广播消息给所有 WebSocket 客户端"""
        disconnected = set()

        for client in self.ws_clients:
            if client == exclude:
                continue

            try:
                await client.send_json(message)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                disconnected.add(client)

        # 清理断开的连接
        for client in disconnected:
            self.ws_clients.discard(client)

    async def _simulation_state_monitor(self):
        """
        仿真状态监控器 - 持续检查并强制停止未授权的仿真运行
        当 auto_stop_enabled=True 且 simulation_control_enabled=False 时，
        会自动停止任何试图运行的仿真
        同时广播遥测数据（3Hz，1秒3次），低频率广播仿真状态（2秒）
        """
        logger.info("🔍 仿真状态监控器已启动")
        check_interval = 0.033  # 每33ms检查一次（约30Hz）
        state_broadcast_interval = 2.0  # 状态广播间隔：2秒
        telemetry_broadcast_interval = 0.333  # 遥测数据广播间隔：333ms（3Hz，1秒3次）

        try:
            while True:
                await asyncio.sleep(check_interval)

                current_time = time.time()
                timeline = omni.timeline.get_timeline_interface()

                # 如果自动停止启用，并且不允许仿真运行
                if self.auto_stop_enabled and not self.simulation_control_enabled:
                    try:
                        if timeline.is_playing():
                            # 检测到未授权的播放，立即停止
                            timeline.stop()

                            # 避免日志刷屏，每2秒最多记录一次
                            if current_time - self._last_stop_check > 2.0:
                                logger.info("⏹️ 监控器: 检测到未授权的仿真运行，已强制停止")
                                self._last_stop_check = current_time

                                # 广播状态给所有客户端
                                await self._broadcast_ws({
                                    "type": "simulation_stopped",
                                    "is_playing": False,
                                    "reason": "auto_stopped"
                                })
                    except Exception as e:
                        logger.error(f"监控器检查出错: {e}")

                # 定期广播仿真状态（每2秒）
                if current_time - self._last_state_broadcast > state_broadcast_interval:
                    try:
                        is_playing = timeline.is_playing()
                        current_sim_time = timeline.get_current_time()
                        start_time = timeline.get_start_time()
                        end_time = timeline.get_end_time()

                        # 广播仿真状态
                        await self._broadcast_ws({
                            "type": "simulation_state",
                            "running": is_playing,
                            "paused": not is_playing and current_sim_time > start_time,
                            "time": current_sim_time,
                            "step": 0
                        })

                        self._last_state_broadcast = current_time

                    except Exception as e:
                        logger.error(f"状态广播出错: {e}")

                # 广播遥测数据（每333ms，约3Hz，1秒3次）
                if current_time - self._last_telemetry_broadcast > telemetry_broadcast_interval:
                    try:
                        is_playing = timeline.is_playing()

                        # 只在仿真运行时获取并广播角速度数据
                        if is_playing:
                            ring_vel, disk_vel = self.get_angular_velocities()
                            if ring_vel is not None and disk_vel is not None:
                                # 每10秒输出一次调试日志（避免刷屏）
                                if not hasattr(self, '_last_telemetry_log'):
                                    self._last_telemetry_log = 0
                                    self._telemetry_count = 0

                                self._telemetry_count += 1

                                if current_time - self._last_telemetry_log >= 10:
                                    logger.info(f"📊 遥测数据 (第{self._telemetry_count}次): ring={ring_vel:.3f}, disk={disk_vel:.3f} rad/s, 广播频率=3Hz(1秒3次), 客户端数={len(self.ws_clients)}")
                                    self._last_telemetry_log = current_time

                                # 计算角动量 (简化计算: L = I * ω)
                                # 对于圆盘: I = 0.5 * m * r^2
                                disk_moment_of_inertia = 0.5 * self.exp1_disk_mass * (self.exp1_disk_radius ** 2)
                                ring_moment_of_inertia = 0.5 * self.exp1_ring_mass * (self.exp1_ring_radius ** 2)

                                # 总角动量
                                disk_angular_momentum = disk_moment_of_inertia * disk_vel
                                ring_angular_momentum = ring_moment_of_inertia * ring_vel
                                total_angular_momentum = disk_angular_momentum + ring_angular_momentum

                                # 广播遥测数据（包含ring和disk的角速度）
                                await self._broadcast_ws({
                                    "type": "telemetry",
                                    "data": {
                                        "timestamp": current_time,
                                        "fps": 3,  # 更新频率：1秒3次
                                        "angular_velocity": disk_vel,  # disk的角速度（保持兼容性）
                                        "disk_angular_velocity": disk_vel,  # disk的角速度
                                        "ring_angular_velocity": ring_vel,  # ring的角速度
                                        "angular_momentum": total_angular_momentum  # 总角动量
                                    }
                                })
                            else:
                                # 如果获取失败，记录日志（只记录一次）
                                if not hasattr(self, '_telemetry_fail_logged'):
                                    logger.warning(f"⚠️ 获取角速度失败: ring={ring_vel}, disk={disk_vel}")
                                    self._telemetry_fail_logged = True

                        self._last_telemetry_broadcast = current_time

                    except Exception as e:
                        logger.error(f"遥测数据广播出错: {e}")

        except asyncio.CancelledError:
            logger.info("🛑 仿真状态监控器已停止")
            raise

    async def close_peer_connection(self, pc):
        """关闭peer connection"""
        self.pcs.discard(pc)
        await pc.close()

    async def on_shutdown(self, app):
        """清理资源"""
        # 关闭所有peer connections
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros)
        self.pcs.clear()

    async def start(self):
        """启动HTTP服务器和WebSocket服务器"""
        if not HAS_WEBRTC:
            carb.log_error("❌ Cannot start WebRTC server - aiortc not installed")
            return

        # 创建aiohttp应用
        self.app = web.Application()
        self.app.on_shutdown.append(self.on_shutdown)

        # 添加 HTTP 路由
        self.app.router.add_post("/offer", self.offer)
        self.app.router.add_post("/camera", self.camera_control)
        self.app.router.add_post("/load_usd", self.load_usd)
        self.app.router.add_post("/simulation", self.simulation_control)
        self.app.router.add_post("/reinit_video", self.reinit_video)
        self.app.router.add_get("/diagnose_video", self.diagnose_video)  # 新增诊断接口

        # 添加 WebSocket 路由
        self.app.router.add_get("/ws", self.websocket_handler)

        # 添加CORS支持
        self.app.router.add_options("/offer", self._handle_options)
        self.app.router.add_options("/camera", self._handle_options)
        self.app.router.add_options("/load_usd", self._handle_options)
        self.app.router.add_options("/simulation", self._handle_options)
        self.app.router.add_options("/reinit_video", self._handle_options)
        self.app.router.add_options("/diagnose_video", self._handle_options)

        # 启动 HTTP/WebSocket 服务器
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(self.runner, self.host, self.http_port)
        await self.site.start()

        # 启动独立的 WebSocket 服务器（用于前端连接）
        self.ws_app = web.Application()
        self.ws_app.router.add_get("/", self.websocket_handler)

        self.ws_runner = web.AppRunner(self.ws_app)
        await self.ws_runner.setup()

        self.ws_site = web.TCPSite(self.ws_runner, self.host, self.ws_port)
        await self.ws_site.start()

        # 确保 timeline 停止（防止自动播放）
        try:
            timeline = omni.timeline.get_timeline_interface()
            if timeline.is_playing():
                timeline.stop()
                carb.log_info("⏹️ Stopped auto-playing timeline")
        except Exception as e:
            carb.log_warn(f"Failed to stop timeline: {e}")

        carb.log_info("=" * 60)
        carb.log_info(f"🚀 WebRTC + WebSocket Server Started")
        carb.log_info(f"   HTTP Port: {self.http_port}")
        carb.log_info(f"   WebSocket Port: {self.ws_port}")
        carb.log_info(f"   Video: {self.video_track.width if self.video_track else 1280}x{self.video_track.height if self.video_track else 720}@30fps (H.264)")
        carb.log_info(f"")
        carb.log_info(f"   📡 HTTP API Endpoints:")
        carb.log_info(f"      /offer        - WebRTC connection")
        carb.log_info(f"      /camera       - Camera control")
        carb.log_info(f"      /simulation   - Simulation control (HTTP POST)")
        carb.log_info(f"      /reinit_video - Reinitialize video (after scene change)")
        carb.log_info(f"      /load_usd     - Load USD scene")
        carb.log_info(f"")
        carb.log_info(f"   🔌 WebSocket Server:")
        carb.log_info(f"      ws://{self.host}:{self.ws_port}/  - Control commands")
        carb.log_info("=" * 60)

        # 启动仿真状态监控器
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.ensure_future(self._simulation_state_monitor())
            carb.log_info("✅ 仿真状态监控器已启动（自动阻止未授权运行）")

    async def stop(self):
        """停止服务器和监控器"""
        # 停止监控器
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # 停止HTTP服务器
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

        # 停止WebSocket服务器
        if hasattr(self, 'ws_site') and self.ws_site:
            await self.ws_site.stop()
        if hasattr(self, 'ws_runner') and self.ws_runner:
            await self.ws_runner.cleanup()

        # 关闭所有 WebSocket 客户端
        for ws in list(self.ws_clients):
            try:
                await ws.close()
            except:
                pass
        self.ws_clients.clear()

        carb.log_info("🛑 WebRTC + WebSocket Server stopped")

    async def _handle_options(self, request):
        """处理CORS预检请求"""
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type"
            }
        )


# ============================================================
# Extension 入口
# ============================================================

class WebRTCExtension(omni.ext.IExt):
    """WebRTC Extension入口"""

    def on_startup(self, ext_id):
        if not HAS_WEBRTC:
            carb.log_error("=" * 60)
            carb.log_error("❌ WebRTC dependencies not installed!")
            carb.log_error("   Please install: pip install aiortc aiohttp")
            carb.log_error("=" * 60)
            return

        carb.log_info("🚀 WebRTC Extension Starting...")
        self.server = WebRTCServer(host="0.0.0.0", http_port=8080)
        asyncio.ensure_future(self.server.start())

    def on_shutdown(self):
        carb.log_info("🛑 WebRTC Extension Shutting down...")
        if hasattr(self, 'server'):
            asyncio.ensure_future(self.server.stop())