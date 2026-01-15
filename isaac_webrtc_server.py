"""
Isaac Sim WebRTC Server (最终修复版 V4)
1. 修复 IndentationError (缩进错误)
2. 包含强制 IP 替换逻辑 (解决 ICE Disconnected)
3. 包含 Replicator 自动修复
"""
from aiortc import RTCConfiguration, RTCIceServer
import carb
import omni.ext
import omni.kit.viewport.utility as vp_util
import omni.usd
import omni.timeline
from pxr import Gf, UsdGeom, UsdPhysics
from pxr import PhysxSchema
import asyncio
import json
import math
import time
import numpy as np
from typing import Optional, Dict, Any, Set
import logging
import fractions
import os
import sys
import socket

RTCConfiguration(
    iceServers=[
        RTCIceServer(urls="stun:stun.l.google.com:19302"),
    ]
)
# ============================================================
# 1. 导入配置模块 (使用绝对路径确保导入正确的 config)
# ============================================================
import importlib.util

# 智能查找项目根目录（修复 Isaac Sim Script Editor 环境下的路径问题）
# 在 Isaac Sim Script Editor 中，__file__ 会解析到临时目录，因此需要从 sys.path 中查找
_PROJECT_ROOT = None

# 策略1：检查 sys.path 中的第一个路径（start_fixed.py 会设置正确的 PROJECT_ROOT）
for candidate_path in sys.path[:5]:  # 检查前5个路径
    if os.path.exists(os.path.join(candidate_path, 'config.py')):
        _PROJECT_ROOT = candidate_path
        carb.log_info(f"🔍 [Config] Found PROJECT_ROOT from sys.path: {_PROJECT_ROOT}")
        break

# 策略2：如果策略1失败，尝试使用 __file__（兜底方案）
if _PROJECT_ROOT is None:
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    carb.log_warn(f"⚠️ [Config] Using __file__ as fallback: {_PROJECT_ROOT}")

# 确保找到的路径在 sys.path 最前面
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
elif sys.path[0] != _PROJECT_ROOT:
    sys.path.remove(_PROJECT_ROOT)
    sys.path.insert(0, _PROJECT_ROOT)

# 强制从项目目录加载 config，避免与其他 config 模块冲突
_config_path = os.path.join(_PROJECT_ROOT, 'config.py')
if os.path.exists(_config_path):
    _spec = importlib.util.spec_from_file_location("config", _config_path)
    config = importlib.util.module_from_spec(_spec)
    sys.modules['config'] = config  # 替换缓存中的 config
    _spec.loader.exec_module(config)
    carb.log_info(f"✅ Config loaded from: {_config_path}")
else:
    carb.log_error(f"❌ Critical: 'config.py' not found at {_config_path}!")
    carb.log_error(f"   Searched in PROJECT_ROOT: {_PROJECT_ROOT}")
    carb.log_error(f"   sys.path[0:5]: {sys.path[:5]}")
    class ConfigMock:
        HTTP_HOST = "0.0.0.0"
        HTTP_PORT = 8080
        WS_HOST = "0.0.0.0"
        WS_PORT = 30000
        VIDEO_WIDTH = 2560
        VIDEO_HEIGHT = 1440
        VIDEO_FPS = 30
        DEFAULT_USD_PATH = ""
        REPLICATOR_INIT_MAX_RETRIES = 3
        REPLICATOR_INIT_RETRY_DELAY = 1.0
        EXP1_DEFAULT_DISK_MASS = 1.0
        EXP1_DEFAULT_RING_MASS = 1.0
        EXP1_DEFAULT_INITIAL_VELOCITY = 0.0
        SIMULATION_CHECK_INTERVAL = 0.1
        TELEMETRY_BROADCAST_INTERVAL = 0.05
        HOST_IP = "127.0.0.1"
    config = ConfigMock()

# WebRTC依赖
try:
    from aiohttp import web
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCConfiguration, RTCIceServer
    from av import VideoFrame
    HAS_WEBRTC = True
except ImportError:
    HAS_WEBRTC = False
    carb.log_error("❌ WebRTC not available. Install: pip install aiortc aiohttp")

# Replicator依赖
try:
    import omni.replicator.core as rep
    HAS_REPLICATOR = True
except ImportError:
    HAS_REPLICATOR = False
    carb.log_warn("❌ Replicator not available")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc")

# ============================================================
# 辅助函数：获取本机局域网 IP
# ============================================================
def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# ============================================================
# 2. 视频轨道类 (Video Track)
# ============================================================
class IsaacSimVideoTrack(VideoStreamTrack):
    def __init__(self, width: int = config.VIDEO_WIDTH, height: int = config.VIDEO_HEIGHT, fps: int = config.VIDEO_FPS):
        super().__init__()
        self.width = width - (width % 2)
        self.height = height - (height % 2)
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.last_frame_time = 0
        self.frame_count = 0
        self.warmup_frames = 30  # 增加预热帧数，等待场景稳定
        self.use_replicator = HAS_REPLICATOR
        self.render_product = None
        self.rgb_annotator = None
        self._replicator_initialized = False
        self._init_retry_count = 0
        self._max_init_retries = 5
        # 不在构造函数中初始化 replicator，等待场景稳定后再初始化

    async def _init_replicator_async(self):
        """异步初始化 Replicator，确保场景已经渲染"""
        try:
            import omni.replicator.core as rep
            
            carb.log_warn("🔄 Starting Replicator initialization...")
            
            # 启用相机和 RTX 传感器（IsaacLab 需要这些设置）
            carb_settings = carb.settings.get_settings()
            carb_settings.set_bool("/isaaclab/cameras_enabled", True)
            carb_settings.set_bool("/isaaclab/render/rtx_sensors", True)
            carb_settings.set_bool("/app/runLoops/rendering/io/waitIdle", True)
            
            # 等待几帧让场景稳定
            app = omni.kit.app.get_app()
            for _ in range(10):
                await app.next_update_async()
            
            viewport = vp_util.get_active_viewport()
            if not viewport:
                carb.log_warn("⚠️ No active viewport found, will retry...")
                return False

            camera_path = viewport.get_active_camera()
            if not camera_path:
                carb.log_warn("⚠️ No active camera in viewport, will retry...")
                return False
            
            carb.log_warn(f"📷 Found camera: {camera_path}")

            # 销毁旧资源
            if self.render_product:
                try:
                    rep.destroy.render_product(self.render_product)
                    carb.log_warn("🗑️ Destroyed old render product")
                except: 
                    pass
                self.render_product = None
                self.rgb_annotator = None

            # 创建 Render Product
            resolution = (self.width, self.height)
            carb.log_warn(f"🎥 Creating render product: {resolution}")

            self.render_product = rep.create.render_product(str(camera_path), resolution)
            carb.log_warn(f"📦 Render product created: {self.render_product}")
            
            # 重要：必须指定 device="cpu" 才能正确获取数据
            self.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb", device="cpu")
            self.rgb_annotator.attach([self.render_product])
            carb.log_warn(f"📎 Annotator attached")

            # 等待 replicator 完成初始化 - 增加等待帧数
            carb.log_warn("⏳ Waiting for render pipeline...")
            for _ in range(20):
                await app.next_update_async()

            carb.log_warn(f"✅ Replicator initialized successfully!")
            self._replicator_initialized = True
            self._init_retry_count = 0
            return True

        except Exception as e:
            carb.log_error(f"💥 Replicator init failed: {e}")
            import traceback
            traceback.print_exc()
            self._replicator_initialized = False
            return False

    async def recv(self):
        if self.frame_count < self.warmup_frames:
            self.frame_count += 1
            await asyncio.sleep(0.1)
            return VideoFrame.from_ndarray(self._generate_test_pattern(), format="rgb24")
        current_time = time.time()
        elapsed = current_time - self.last_frame_time
        if elapsed < self.frame_interval:
            await asyncio.sleep(self.frame_interval - elapsed)
        
        self.last_frame_time = time.time()
        self.frame_count += 1

        frame_array = await self._capture_isaac_frame_async()

        if frame_array is None:
            carb.log_warn("⚠️ No frame from replicator → using test pattern")
            frame_array = self._generate_test_pattern()
        elif frame_array.size == 0:
            carb.log_error("❌ Empty array received from replicator")
            frame_array = self._generate_test_pattern()
        else:
            # 调试：每100帧打印一次帧大小
            if self.frame_count % 100 == 0:
                carb.log_warn(f"📐 Frame shape: {frame_array.shape}, expected: ({self.height}, {self.width}, 3)")
            
            # 如果帧大小不对，调整大小
            if frame_array.shape[0] != self.height or frame_array.shape[1] != self.width:
                from PIL import Image
                img = Image.fromarray(frame_array[:, :, :3] if frame_array.shape[2] == 4 else frame_array)
                img = img.resize((self.width, self.height), Image.LANCZOS)
                frame_array = np.array(img)
            
            if not (frame_array.dtype == np.uint8 and frame_array.flags['C_CONTIGUOUS']):
                frame_array = self._validate_and_fix_frame(frame_array)

        try:
            frame = VideoFrame.from_ndarray(frame_array, format="rgb24")
            frame.pts = self.frame_count
            frame.time_base = fractions.Fraction(1, self.fps)
            return frame
        except Exception:
            return VideoFrame.from_ndarray(self._generate_test_pattern(), format="rgb24")

    def _validate_and_fix_frame(self, frame_array):
        if not isinstance(frame_array, np.ndarray): return self._generate_test_pattern()
        if frame_array.dtype != np.uint8:
            frame_array = (frame_array.clip(0, 1) * 255).astype(np.uint8) if frame_array.dtype in (np.float32, np.float64) else frame_array.astype(np.uint8)
        if len(frame_array.shape) == 3 and frame_array.shape[2] == 4:
            frame_array = frame_array[:, :, :3]
        return np.ascontiguousarray(frame_array)

    def _generate_test_pattern(self):
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:, :, 1] = 128
        return frame

    async def _capture_isaac_frame_async(self):
        """优先使用 viewport 获取帧（不影响仿真）"""
        # 方法1: 使用 viewport 直接获取（不影响仿真）
        frame = await self._capture_from_viewport()
        if frame is not None:
            return frame
        
        # 方法2: 使用 Replicator（备用，可能影响仿真）
        frame = await self._capture_from_replicator()
        if frame is not None:
            self._empty_count = 0
            return frame
        
        return None

    async def _capture_from_viewport(self):
        """直接从 viewport 获取帧 - 使用缓存的 Camera 对象"""
        try:
            from omni.isaac.sensor import Camera
            
            # 获取活动视口的相机路径
            viewport = vp_util.get_active_viewport()
            if viewport is None:
                return None
            
            camera_path = viewport.get_active_camera()
            if not camera_path:
                return None
            
            # 使用缓存的 Camera 对象
            if not hasattr(self, '_cached_camera') or self._cached_camera_path != str(camera_path):
                try:
                    self._cached_camera = Camera(
                        prim_path=str(camera_path),
                        resolution=(self.width, self.height)
                    )
                    self._cached_camera.initialize()
                    self._cached_camera_path = str(camera_path)
                    carb.log_warn(f"📷 Created cached camera: {camera_path} at {self.width}x{self.height}")
                except Exception as e:
                    carb.log_warn(f"⚠️ Failed to create camera: {e}")
                    return None
            
            # 获取 RGBA 图像
            try:
                rgba = self._cached_camera.get_rgba()
                if rgba is not None and rgba.size > 0:
                    rgb = rgba[:, :, :3]
                    return np.ascontiguousarray(rgb)
            except Exception as e:
                if hasattr(self, '_cached_camera'):
                    del self._cached_camera
                pass
            
            return None
        except Exception as e:
            return None

    async def _capture_from_replicator(self):
        """使用 Replicator 获取帧"""
        try:
            import omni.replicator.core as rep

            # === 0. 检查并初始化 replicator ===
            if not self._replicator_initialized or self.rgb_annotator is None:
                carb.log_warn(f"🔄 Need to initialize replicator (attempt {self._init_retry_count + 1}/{self._max_init_retries})...")
                self._init_retry_count += 1
                success = await self._init_replicator_async()
                if not success:
                    if self._init_retry_count >= self._max_init_retries:
                        carb.log_warn("⚠️ Max init retries reached, resetting...")
                        self._init_retry_count = 0
                    return None

            # === 1. 触发 Replicator 渲染（作为备用方案）===
            try:
                await rep.orchestrator.step_async()
            except Exception:
                pass

            # === 2. 获取数据 ===
            try:
                data = self.rgb_annotator.get_data()
            except KeyError as e:
                carb.log_warn(f"⚠️ KeyError getting data, reinitializing: {e}")
                self._replicator_initialized = False
                self.rgb_annotator = None
                self.render_product = None
                return None
            
            if data is None:
                return None
            
            if data.size == 0:
                if not hasattr(self, '_empty_count'):
                    self._empty_count = 0
                self._empty_count += 1
                if self._empty_count > 30:
                    carb.log_warn("⚠️ get_data() returned empty too many times, reinitializing...")
                    self._replicator_initialized = False
                    self._empty_count = 0
                return None
            
            # 转换数据
            if hasattr(data, 'shape') and data.size > 0:
                data = np.frombuffer(data, dtype=np.uint8).reshape(*data.shape)
            
            if data.size == 0:
                return None

            # 验证格式
            if len(data.shape) != 3 or data.shape[2] not in (3, 4):
                return None

            if data.shape[2] == 4:
                data = data[:, :, :3]

            self._init_retry_count = 0
            return data

        except Exception:
            self._replicator_initialized = False
            return None


# ============================================================
# 3. 相机控制器
# ============================================================
class CameraController:
    def __init__(self):
        self.camera_distance = 10.0
        self.camera_azimuth = 45.0
        self.camera_elevation = 30.0
        self.camera_target = Gf.Vec3d(0, 0, 0)
        self.use_custom_camera = False

    def orbit(self, delta_x, delta_y):
        self.camera_azimuth = (self.camera_azimuth + delta_x * 0.3) % 360
        self.camera_elevation = max(-89, min(89, self.camera_elevation + delta_y * 0.3))
        self._update_camera()
        
    def zoom(self, delta):
        self.camera_distance = max(1.0, self.camera_distance + delta * 0.1)
        self._update_camera()

    def reset(self):
        self.camera_distance = 10.0
        self.camera_azimuth = 45.0
        self.camera_elevation = 30.0
        self._update_camera()

    def _update_camera(self):
        if self.use_custom_camera: return
        try:
            viewport = vp_util.get_active_viewport()
            if not viewport: return
            camera_path = viewport.get_active_camera()
            if not camera_path: return
            
            az_rad = math.radians(self.camera_azimuth)
            el_rad = math.radians(self.camera_elevation)
            x = self.camera_distance * math.cos(el_rad) * math.cos(az_rad)
            y = self.camera_distance * math.cos(el_rad) * math.sin(az_rad)
            z = self.camera_distance * math.sin(el_rad)
            camera_pos = self.camera_target + Gf.Vec3d(x, y, z)
            
            stage = omni.usd.get_context().get_stage()
            if not stage: return
            prim = stage.GetPrimAtPath(camera_path)
            
            if prim and prim.IsValid():
                xform = UsdGeom.Xformable(prim)
                xform.AddTranslateOp().Set(camera_pos)
        except: pass

# ============================================================
# 4. WebRTC Server
# ============================================================
class WebRTCServer:
    def __init__(self, host=config.HTTP_HOST, http_port=config.HTTP_PORT, ws_port=config.WS_PORT):
        self.host = host
        self.http_port = http_port
        self.ws_port = ws_port
        self.pcs = set()
        self.camera_controller = CameraController()
        self.video_track = None
        self.ws_clients = set()

        self.simulation_control_enabled = False
        self.auto_stop_enabled = True
        self._monitor_task = None

        # 实验1参数
        self.exp1_disk_mass = config.EXP1_DEFAULT_DISK_MASS
        self.exp1_ring_mass = config.EXP1_DEFAULT_RING_MASS
        self.exp1_initial_vel = config.EXP1_DEFAULT_INITIAL_VELOCITY

        # 实验2参数
        self.exp2_initial_angle = config.EXP2_DEFAULT_INITIAL_ANGLE
        self.exp2_mass1 = config.EXP2_DEFAULT_MASS1
        self.exp2_mass2 = config.EXP2_DEFAULT_MASS2

        # 当前实验编号（用于区分遥测数据）
        self.current_experiment = "1"

        # 实验2周期检测变量
        self.exp2_angle_history = []
        self.exp2_last_peak_time = None
        self.exp2_period = 0.0
        self.exp2_period_samples = []  # 用于平滑周期

        # 实验2周期计算变量（改进版 - 零交叉检测）
        self.exp2_zero_cross_times = []  # 记录零交叉时刻
        self.exp2_last_angle_sign = None  # 上一次角度的符号

        self._dc_interface = None
        self.config_module = config

    async def _init_replicator_async(self, track):
        import omni.replicator.core as rep
        await asyncio.sleep(1.0)
        viewport = vp_util.get_active_viewport()
        if viewport:
            camera_path = viewport.get_active_camera()
            if track.render_product: 
                try: rep.destroy.render_product(track.render_product)
                except: pass
            track.render_product = rep.create.render_product(camera_path, (track.width, track.height))
            track.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
            track.rgb_annotator.attach([track.render_product])
            track.use_replicator = True
            return True
        return False

    async def offer(self, request):
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        
        rtc_config = RTCConfiguration(iceServers=[
            RTCIceServer(urls="stun:stun.l.google.com:19302")
        ])
        pc = RTCPeerConnection(configuration=rtc_config)
        self.pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            carb.log_info(f"WebRTC Connection State: {pc.connectionState}")
            if pc.connectionState in ["failed", "closed"]:
                self.pcs.discard(pc)
                await pc.close()

        if self.video_track is None:
            self.video_track = IsaacSimVideoTrack()
            if not self.video_track.use_replicator:
                asyncio.ensure_future(self._init_replicator_async(self.video_track))

        pc.addTrack(self.video_track)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        
        # === 打印原始 Answer SDP ===
        carb.log_info("📤 OUTGOING SDP (before patch):\n" + answer.sdp)
        
        # --- IP Patching Logic ---
        server_ip = getattr(config, 'HOST_IP', get_host_ip())
        carb.log_info(f"🌐 Using server IP for SDP patch: {server_ip}")
        sdp_lines = answer.sdp.splitlines()
        new_sdp_lines = []
        for line in sdp_lines:
            if "c=IN IP4" in line:
                new_sdp_lines.append(f"c=IN IP4 {server_ip}")
            elif line.startswith("o="):
                # 替换 origin 行中的 IP 地址
                line = line.replace("0.0.0.0", server_ip)\
                        .replace("127.0.0.1", server_ip)
                new_sdp_lines.append(line)
            elif "a=candidate" in line:
                # 强制替换所有无效地址
                line = line.replace("0.0.0.0", server_ip)\
                        .replace("127.0.0.1", server_ip)\
                        .replace(".local", "")
                new_sdp_lines.append(line)
            else:
                new_sdp_lines.append(line)
        
        new_sdp = "\r\n".join(new_sdp_lines) + "\r\n"
        patched_answer = RTCSessionDescription(sdp=new_sdp, type=answer.type)
        
        # === 打印修补后的 SDP ===
        carb.log_info("✅ PATCHED SDP:\n" + new_sdp)
        
        await pc.setLocalDescription(patched_answer)
        
        return web.Response(
            content_type="application/json", 
            text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}), 
            headers={"Access-Control-Allow-Origin": "*"}
        )

    async def camera_control(self, request):
        params = await request.json()
        action = params.get("action")
        if action == "orbit": self.camera_controller.orbit(params.get("deltaX", 0), params.get("deltaY", 0))
        elif action == "zoom": self.camera_controller.zoom(params.get("delta", 0))
        elif action == "reset": self.camera_controller.reset()
        return web.Response(text=json.dumps({"status": "ok"}))

    async def load_usd(self, request):
        params = await request.json()
        usd_path = params.get("usd_path", config.DEFAULT_USD_PATH)
        success = omni.usd.get_context().open_stage(usd_path)
        if success:
            self.simulation_control_enabled = False
            omni.timeline.get_timeline_interface().stop()
            await self._apply_exp1_params()
            return web.Response(text=json.dumps({"status": "ok"}))
        return web.Response(status=500, text="Failed")

    async def reinit_video(self, request):
        if self.video_track:
            await self._init_replicator_async(self.video_track)
        return web.Response(text=json.dumps({"status": "ok"}))

    async def diagnose_video(self, request):
        status = {
            "track_exists": self.video_track is not None,
            "replicator_active": self.video_track.use_replicator if self.video_track else False
        }
        return web.Response(text=json.dumps(status))

    # ============================================================
    # WebSocket Logic
    # ============================================================
    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)
        carb.log_warn("🔌 WebSocket client connected!")
        # 发送连接确认
        await ws.send_json({"type": "connected", "message": "WebSocket connected to Isaac Sim"})
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    mtype = data.get("type")
                    # 只对重要命令打印日志，减少噪音
                    if mtype not in ("get_simulation_state",):
                        carb.log_warn(f"📨 Received command: {mtype}")
                    if mtype == "start_simulation":
                        tl = omni.timeline.get_timeline_interface()
                        # 检查是否需要设置初始角速度（只在第一次运行或 reset 后）
                        if not hasattr(self, '_has_started') or not self._has_started:
                            carb.log_warn("▶️ Starting simulation (first run)...")
                            # 只有实验1需要设置初始角速度
                            if self.current_experiment == "1":
                                await self._set_initial_angular_velocity()
                            self._has_started = True
                        else:
                            carb.log_warn("▶️ Resuming simulation...")
                        self.simulation_control_enabled = True
                        tl.play()
                        carb.log_warn("✅ Simulation running!")
                    elif mtype == "stop_simulation":
                        carb.log_warn("⏹️ Stopping simulation...")
                        self.simulation_control_enabled = False
                        omni.timeline.get_timeline_interface().stop()
                        carb.log_warn("✅ Simulation stopped!")
                    elif mtype == "reset":
                        # 重置实验：停止仿真，重置时间
                        carb.log_warn("🔄 Resetting experiment...")
                        self.simulation_control_enabled = False
                        self._has_started = False  # 重置标志，下次 Run 会重新设置初始角速度

                        # 清空实验2的历史数据和周期检测变量
                        self.exp2_angle_history = []
                        self.exp2_last_peak_time = None
                        self.exp2_period = 0.0
                        self.exp2_period_samples = []
                        self.exp2_zero_cross_times = []
                        self.exp2_last_angle_sign = None

                        tl = omni.timeline.get_timeline_interface()
                        # 多次停止确保真正停止
                        tl.stop()
                        tl.set_current_time(0.0)
                        tl.stop()

                        # 不重置初始速度，保留用户设置的值
                        # self.exp1_initial_vel 保持不变

                        # 重置到初始位置
                        await self._reset_positions()

                        # 再次确保停止
                        await asyncio.sleep(0.1)
                        tl.stop()

                        carb.log_warn("✅ Experiment reset complete!")
                    elif mtype == "enter_experiment":
                        # 进入实验 - 切换相机并重置物理状态
                        exp_id = data.get("experiment_id", "unknown")
                        carb.log_warn(f"📍 Entering experiment: {exp_id}")

                        # 更新当前实验编号
                        self.current_experiment = exp_id

                        # 清空实验2的历史数据和周期检测变量（切换实验时）
                        self.exp2_angle_history = []
                        self.exp2_last_peak_time = None
                        self.exp2_period = 0.0
                        self.exp2_period_samples = []
                        self.exp2_zero_cross_times = []
                        self.exp2_last_angle_sign = None

                        # 切换到对应实验的相机
                        await self._switch_camera(exp_id)

                        # 根据实验编号应用对应的参数
                        if exp_id == "1":
                            await self._apply_exp1_params()
                        elif exp_id == "2":
                            await self._apply_exp2_params()

                        # 发送确认消息
                        await ws.send_json({"type": "experiment_entered", "experiment_id": exp_id})
                    elif mtype == "switch_camera":
                        # 切换相机（不改变其他状态）
                        exp_id = data.get("experiment_id", "2")  # 默认 exp2
                        carb.log_warn(f"📷 Switching camera to experiment: {exp_id}")
                        await self._switch_camera(exp_id)
                        await ws.send_json({"type": "camera_switched", "experiment_id": exp_id})
                    elif mtype == "get_simulation_state":
                        # 返回仿真状态（不打印日志，避免刷屏）
                        tl = omni.timeline.get_timeline_interface()
                        state = {
                            "type": "simulation_state",
                            "running": tl.is_playing(),
                            "paused": not tl.is_playing(),
                            "time": tl.get_current_time(),
                            "step": 0
                        }
                        await ws.send_json(state)
                    elif mtype == "set_disk_mass" or mtype == "set_mass":
                         self.exp1_disk_mass = float(data.get("value", 1.0))
                         carb.log_warn(f"📊 Set disk mass: {self.exp1_disk_mass} kg")
                         await self._apply_exp1_params()
                    elif mtype == "set_ring_mass":
                         self.exp1_ring_mass = float(data.get("value", 1.0))
                         carb.log_warn(f"📊 Set ring mass: {self.exp1_ring_mass} kg")
                         await self._apply_exp1_params()
                    elif mtype == "set_initial_velocity":
                         self.exp1_initial_vel = float(data.get("value", 5.0))
                         carb.log_warn(f"📊 Set initial velocity: {self.exp1_initial_vel} rad/s")
                         # 不立即应用，等点击 Run 时再应用
                    elif mtype == "set_initial_angle":
                         # 设置初始角度（在停止状态下设置，避免物理引擎误认为是目标姿态）
                         self.exp2_initial_angle = float(data.get("value", 90.0))
                         carb.log_warn(f"📊 [Exp2] Set initial angle: {self.exp2_initial_angle}°")
                         await self._apply_exp2_params()
                    elif mtype == "set_exp2_mass1":
                         self.exp2_mass1 = float(data.get("value", 1.0))
                         carb.log_warn(f"📊 [Exp2] Set Cylinder_01 mass: {self.exp2_mass1} kg")
                         await self._apply_exp2_params()
                    elif mtype == "set_exp2_mass2":
                         self.exp2_mass2 = float(data.get("value", 1.0))
                         carb.log_warn(f"📊 [Exp2] Set Cylinder_02 mass: {self.exp2_mass2} kg")
                         await self._apply_exp2_params()
                    else:
                        carb.log_warn(f"📨 Received unknown message type: {mtype}")
        finally:
            self.ws_clients.discard(ws)
        return ws

    def _switch_camera_sync(self, experiment_id: str):
        """同步切换相机（在主线程中执行）"""
        try:
            camera_script = os.path.join(_PROJECT_ROOT, 'camera', f'usd{experiment_id}.py')
            carb.log_warn(f"📷 Looking for camera script: {camera_script}")
            carb.log_warn(f"📷 PROJECT_ROOT: {_PROJECT_ROOT}")
            
            if os.path.exists(camera_script):
                carb.log_warn(f"📷 Found script, reading content...")
                
                # 读取脚本内容
                with open(camera_script, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                
                carb.log_warn(f"📷 Script content length: {len(script_content)} chars")
                
                # 直接执行相机设置逻辑，不使用 exec
                stage = omni.usd.get_context().get_stage()
                if not stage:
                    carb.log_error("💥 No USD stage available!")
                    return
                
                # 获取活动相机
                viewport = vp_util.get_active_viewport()
                if viewport:
                    camera_path = viewport.get_active_camera()
                else:
                    camera_path = "/OmniverseKit_Persp"
                
                carb.log_warn(f"📷 Using camera: {camera_path}")
                
                camera_prim = stage.GetPrimAtPath(camera_path)
                if not camera_prim.IsValid():
                    carb.log_error(f"💥 Camera not found: {camera_path}")
                    return
                
                camera = UsdGeom.Camera(camera_prim)
                xform = UsdGeom.Xformable(camera_prim)
                
                # 获取现有的 xformOp
                xform_ops = xform.GetOrderedXformOps()
                translate_op = None
                orient_op = None
                
                for op in xform_ops:
                    if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                        translate_op = op
                    elif op.GetOpType() == UsdGeom.XformOp.TypeOrient:
                        orient_op = op
                
                # 如果操作不存在，则创建
                if not translate_op:
                    translate_op = xform.AddTranslateOp()
                if not orient_op:
                    orient_op = xform.AddOrientOp()
                
                # 根据实验ID设置相机参数
                if experiment_id == "1":
                    # 实验1相机参数
                    translate_op.Set(Gf.Vec3d(3.5422114387995194, 4.789534293747461, 2.734575842472313))
                    orient_op.Set(Gf.Quatd(0.2293882119384616, 0.14807866885692916, 0.5217433897762196, 0.8082311496583482))
                    carb.log_warn("📷 Applied camera params for Experiment 1")
                elif experiment_id == "2":
                    # 实验2相机参数
                    translate_op.Set(Gf.Vec3d(1.169913776980235, 5.384567671926622, 2.5526077469676727))
                    orient_op.Set(Gf.Quatd(0.014359612064957861, 0.009788101829553237, 0.5631514231667778, 0.8261709684981379))
                    carb.log_warn("📷 Applied camera params for Experiment 2")
                else:
                    carb.log_warn(f"⚠️ No camera params defined for experiment {experiment_id}, using default")
                
                # 设置通用相机参数
                camera.GetClippingRangeAttr().Set(Gf.Vec2f(0.009999999776482582, 10000000.0))
                camera.GetFocalLengthAttr().Set(18.14756202697754)
                
                carb.log_warn(f"✅ Camera switched to experiment {experiment_id}")
            else:
                carb.log_warn(f"⚠️ Camera script not found: {camera_script}")
        except Exception as e:
            carb.log_error(f"💥 Failed to switch camera: {e}")
            import traceback
            traceback.print_exc()

    async def _switch_camera(self, experiment_id: str):
        """切换到指定实验的相机配置"""
        # 直接调用同步版本
        self._switch_camera_sync(experiment_id)

    async def _set_initial_angular_velocity(self):
        """设置 disk 的初始角速度"""
        try:
            import math
            # 使用 USD API 设置角速度
            # 用户输入是 rad/s，Isaac Sim 使用度/秒
            # 转换公式：度/秒 = rad/s × 180/π
            stage = omni.usd.get_context().get_stage()
            if stage:
                disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
                if disk_prim and disk_prim.IsValid() and disk_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    rb_api = UsdPhysics.RigidBodyAPI(disk_prim)
                    # rad/s 转换为 度/秒: 乘以 180/π，缩放因子改为 10
                    SCALE_FACTOR = 10.0
                    deg_per_sec = float(self.exp1_initial_vel) * (180.0 / math.pi) * SCALE_FACTOR
                    angular_vel = Gf.Vec3f(0.0, 0.0, deg_per_sec)
                    rb_api.GetAngularVelocityAttr().Set(angular_vel)
                    carb.log_warn(f"✅ Set disk angular velocity: {self.exp1_initial_vel} rad/s = {deg_per_sec:.2f} deg/s (×{SCALE_FACTOR:.0f})")
                else:
                    carb.log_warn("⚠️ disk prim not found or no RigidBodyAPI")
                
        except Exception as e:
            carb.log_error(f"💥 Failed to set initial velocity: {e}")

    async def _reset_positions(self):
        """重置 disk 和 ring 到初始位置（不改变速度）"""
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                carb.log_warn("⚠️ No stage found, cannot reset positions")
                return
            
            # 重置 timeline 到初始时间即可，Isaac Sim 会自动恢复初始状态
            carb.log_warn("✅ Reset to initial position (timeline reset)")
                
        except Exception as e:
            carb.log_error(f"💥 Failed to reset positions: {e}")

    async def _apply_exp1_params(self):
        """只设置质量（其他使用 USD 默认值）"""
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                carb.log_warn("⚠️ No stage found, cannot apply params")
                return

            paths_and_masses = [("/World/exp1/disk", self.exp1_disk_mass), ("/World/exp1/ring", self.exp1_ring_mass)]
            for path, mass in paths_and_masses:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    # 只设置质量
                    if not prim.HasAPI(UsdPhysics.MassAPI):
                        UsdPhysics.MassAPI.Apply(prim)
                    mass_api = UsdPhysics.MassAPI(prim)
                    mass_api.GetMassAttr().Set(float(mass))
                    carb.log_warn(f"✅ Set mass for {path}: {mass}kg")
                else:
                    carb.log_warn(f"⚠️ Prim not found: {path}")

            carb.log_warn(f"📊 Mass applied: Disk={self.exp1_disk_mass}kg, Ring={self.exp1_ring_mass}kg")
        except Exception as e:
            carb.log_error(f"💥 Failed to apply params: {e}")
            import traceback
            traceback.print_exc()

    async def _apply_exp2_params(self):
        """设置实验2的参数：质量和初始角度

        只设置用户要求的4个功能相关的参数：
        1. 初始角度设置（默认90度）
        2. 两个重物的质量设置
        3. 角度实时读取（在其他函数中实现）
        4. 周期计算（在其他函数中实现）

        注意：不修改阻尼、摩擦、关节驱动等物理参数，保持USD原始配置
        """
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                carb.log_warn("⚠️ [Exp2] No stage found, cannot apply params")
                return

            # 1. 设置初始角度（在停止状态下）
            tl = omni.timeline.get_timeline_interface()
            was_playing = tl.is_playing()

            # 确保在停止状态下设置角度
            if was_playing:
                tl.stop()
                await asyncio.sleep(0.1)  # 等待停止完成

            # 设置 Group_01 的旋转角度
            group_prim = stage.GetPrimAtPath(config.EXP2_GROUP_PATH)
            if group_prim and group_prim.IsValid():
                xformable = UsdGeom.Xformable(group_prim)

                # 清除现有的旋转操作
                xformable.ClearXformOpOrder()

                # 添加新的旋转操作（绕Y轴）
                rotate_op = xformable.AddRotateYOp()
                rotate_op.Set(float(self.exp2_initial_angle))

                carb.log_warn(f"✅ [Exp2] Set initial angle: {self.exp2_initial_angle}°")
            else:
                carb.log_warn(f"⚠️ [Exp2] Group_01 not found: {config.EXP2_GROUP_PATH}")

            # 2. 设置两个重物的质量
            mass_paths = [
                (config.EXP2_MASS1_PATH, self.exp2_mass1, "Cylinder_01"),
                (config.EXP2_MASS2_PATH, self.exp2_mass2, "Cylinder_02")
            ]
            for path, mass, name in mass_paths:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    # 只设置质量，不修改其他物理属性
                    if not prim.HasAPI(UsdPhysics.MassAPI):
                        UsdPhysics.MassAPI.Apply(prim)
                    mass_api = UsdPhysics.MassAPI(prim)
                    mass_api.GetMassAttr().Set(float(mass))

                    carb.log_warn(f"✅ [Exp2] Set {name} mass: {mass}kg")
                else:
                    carb.log_warn(f"⚠️ [Exp2] Mass prim not found: {path}")

            carb.log_warn(f"📊 [Exp2] Params applied: Angle={self.exp2_initial_angle}°, Mass1={self.exp2_mass1}kg, Mass2={self.exp2_mass2}kg")

        except Exception as e:
            carb.log_error(f"💥 [Exp2] Failed to apply params: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_actual_angular_velocities(self):
        """从物理仿真中读取实际的角速度"""
        disk_vel = 0.0
        ring_vel = 0.0
        
        try:
            # 方法1: 尝试使用 Dynamic Control API
            try:
                from omni.isaac.dynamic_control import _dynamic_control
                
                if self._dc_interface is None:
                    self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()
                
                dc = self._dc_interface
                
                SCALE_FACTOR = 10.0
                
                # 读取 disk 的角速度
                disk_handle = dc.get_rigid_body("/World/exp1/disk")
                if disk_handle != _dynamic_control.INVALID_HANDLE:
                    ang_vel = dc.get_rigid_body_angular_velocity(disk_handle)
                    if ang_vel is not None:
                        # Dynamic Control 返回 rad/s，除以 SCALE_FACTOR 还原缩放
                        disk_vel = float(ang_vel[2]) / SCALE_FACTOR
                
                # 读取 ring 的角速度
                ring_handle = dc.get_rigid_body("/World/exp1/ring")
                if ring_handle != _dynamic_control.INVALID_HANDLE:
                    ang_vel = dc.get_rigid_body_angular_velocity(ring_handle)
                    if ang_vel is not None:
                        ring_vel = float(ang_vel[2]) / SCALE_FACTOR
                
                return disk_vel, ring_vel
            except:
                pass
            
            # 方法2: 使用 Isaac Core RigidPrim
            try:
                from omni.isaac.core.prims import RigidPrim
                SCALE_FACTOR = 10.0
                
                disk_prim = RigidPrim("/World/exp1/disk")
                vel = disk_prim.get_angular_velocity()
                if vel is not None:
                    disk_vel = float(vel[2]) / SCALE_FACTOR
                
                ring_prim = RigidPrim("/World/exp1/ring")
                vel = ring_prim.get_angular_velocity()
                if vel is not None:
                    ring_vel = float(vel[2]) / SCALE_FACTOR
                
                return disk_vel, ring_vel
            except:
                pass
            
            # 方法3: 使用 USD API (只能读初始值，作为后备)
            stage = omni.usd.get_context().get_stage()
            if stage:
                import math
                SCALE_FACTOR = 10.0
                disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
                if disk_prim and disk_prim.IsValid() and disk_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    rb_api = UsdPhysics.RigidBodyAPI(disk_prim)
                    vel_attr = rb_api.GetAngularVelocityAttr()
                    if vel_attr and vel_attr.Get():
                        vel = vel_attr.Get()
                        disk_vel = float(vel[2]) * (math.pi / 180.0) / SCALE_FACTOR if vel else 0.0
                
                ring_prim = stage.GetPrimAtPath("/World/exp1/ring")
                if ring_prim and ring_prim.IsValid() and ring_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    rb_api = UsdPhysics.RigidBodyAPI(ring_prim)
                    vel_attr = rb_api.GetAngularVelocityAttr()
                    if vel_attr and vel_attr.Get():
                        vel = vel_attr.Get()
                        ring_vel = float(vel[2]) * (math.pi / 180.0) / SCALE_FACTOR if vel else 0.0
            
            return disk_vel, ring_vel
        except Exception as e:
            return 0.0, 0.0

    def _get_exp2_angle(self):
        """获取实验2中摆杆的实时旋转角度（度）

        方法：RigidPrim + scipy 读取世界姿态的 Y 轴角度
        用户验证：旋转90度后角度变化正确
        """
        try:
            import math
            angle_deg = None

            # 使用 Isaac Core RigidPrim + scipy（用户验证正确）
            try:
                from omni.isaac.core.prims import RigidPrim
                from scipy.spatial.transform import Rotation as R

                # 读取 Cylinder 的世界姿态
                cylinder_rigid = RigidPrim(config.EXP2_CYLINDER_PATH)
                position, orientation = cylinder_rigid.get_world_pose()

                if orientation is not None:
                    # 四元数 [x, y, z, w] 转换为欧拉角
                    quat_xyzw = [float(orientation[0]), float(orientation[1]),
                                float(orientation[2]), float(orientation[3])]
                    rotation_scipy = R.from_quat(quat_xyzw)
                    euler_xyz = rotation_scipy.as_euler('xyz', degrees=True)

                    # 直接使用 Y 轴角度（用户测试验证正确）
                    angle_deg = float(euler_xyz[1])

                    if not hasattr(self, '_method_logged'):
                        carb.log_warn("✅ [Exp2] Using RigidPrim + scipy (user verified)")
                        self._method_logged = True

            except ImportError:
                # scipy 不可用，回退到 USD API
                if not hasattr(self, '_scipy_warn_logged'):
                    carb.log_warn("⚠️ [Exp2] scipy not available, using USD fallback")
                    self._scipy_warn_logged = True
                angle_deg = self._get_exp2_angle_fallback()

            except Exception as e:
                if not hasattr(self, '_rigidprim_error_logged'):
                    carb.log_warn(f"⚠️ [Exp2] RigidPrim failed: {e}, using fallback")
                    self._rigidprim_error_logged = True
                angle_deg = self._get_exp2_angle_fallback()

            # 如果所有方法都失败
            if angle_deg is None:
                return 0.0

            # 归一化到 [-180, 180] 范围
            while angle_deg > 180:
                angle_deg -= 360
            while angle_deg < -180:
                angle_deg += 360

            # 直接返回原始角度，不做额外的平滑或过滤
            # scipy 的四元数转换已经足够稳定，高频采样(100Hz)可以保证平滑
            return angle_deg

        except Exception as e:
            carb.log_error(f"❌ [Exp2] Error reading angle: {e}")
            import traceback
            traceback.print_exc()
            return 0.0

    def _get_exp2_angle_fallback(self):
        """备用方法：使用 USD API 读取角度（当 RigidPrim 不可用时）"""
        try:
            import math
            stage = omni.usd.get_context().get_stage()
            if not stage:
                return 0.0

            # 读取 Cylinder 和 Group_01 的世界变换
            cylinder_prim = stage.GetPrimAtPath(config.EXP2_CYLINDER_PATH)
            group_prim = stage.GetPrimAtPath(config.EXP2_GROUP_PATH)

            if not (cylinder_prim and cylinder_prim.IsValid() and group_prim and group_prim.IsValid()):
                return 0.0

            cylinder_xform = UsdGeom.Xformable(cylinder_prim)
            group_xform = UsdGeom.Xformable(group_prim)

            cylinder_world = cylinder_xform.ComputeLocalToWorldTransform(0)
            group_world = group_xform.ComputeLocalToWorldTransform(0)

            # 修正矩阵乘法顺序：relative = parent_inv * child
            relative_transform = group_world.GetInverse() * cylinder_world

            # 提取旋转并转换为欧拉角
            rotation = relative_transform.ExtractRotation()
            angles = rotation.Decompose(Gf.Vec3d.XAxis(), Gf.Vec3d.YAxis(), Gf.Vec3d.ZAxis())
            angle_deg = float(angles[1]) * (180.0 / math.pi)

            return angle_deg
        except Exception:
            return 0.0

    def _calculate_exp2_period(self, current_angle, current_time):
        """计算实验2的周期 - 改进版（零交叉检测法）

        原理：单摆通过平衡位置（0度）时为零交叉点
        两次同向零交叉之间的时间间隔 = 一个完整周期
        比峰值检测更稳定，不受振幅衰减影响
        """
        try:
            # 确定当前角度的符号（正或负）
            current_sign = 1 if current_angle >= 0 else -1

            # 检测零交叉（从正到负，或从负到正）
            if self.exp2_last_angle_sign is not None:
                # 检测到符号变化 = 零交叉
                if current_sign != self.exp2_last_angle_sign:
                    # 记录零交叉时刻和类型（1=从正到负，-1=从负到正）
                    cross_type = self.exp2_last_angle_sign
                    self.exp2_zero_cross_times.append((current_time, cross_type))

                    # 只保留最近10秒的数据
                    cutoff_time = current_time - 10.0
                    self.exp2_zero_cross_times = [
                        (t, ct) for t, ct in self.exp2_zero_cross_times if t >= cutoff_time
                    ]

                    # 计算周期：找到最近两次同类型的零交叉
                    if len(self.exp2_zero_cross_times) >= 2:
                        # 找到所有同类型的零交叉
                        same_type_crosses = [
                            (t, ct) for t, ct in self.exp2_zero_cross_times if ct == cross_type
                        ]

                        if len(same_type_crosses) >= 2:
                            # 最近两次同类型零交叉的时间间隔 = 一个周期
                            latest_period = same_type_crosses[-1][0] - same_type_crosses[-2][0]

                            # 合理性检查：周期应该在0.3秒到10秒之间
                            if 0.3 < latest_period < 10.0:
                                # 添加到平滑样本列表
                                self.exp2_period_samples.append(latest_period)

                                # 保留最近3个样本用于平滑（减少噪声影响）
                                if len(self.exp2_period_samples) > 3:
                                    self.exp2_period_samples.pop(0)

                                # 计算平均周期
                                self.exp2_period = sum(self.exp2_period_samples) / len(self.exp2_period_samples)

                                carb.log_warn(
                                    f"📊 [Exp2] Zero-crossing detected! "
                                    f"Period: {latest_period:.2f}s (smoothed: {self.exp2_period:.2f}s)"
                                )
                            else:
                                carb.log_warn(
                                    f"⚠️ [Exp2] Invalid period: {latest_period:.2f}s (out of range 0.3-10s)"
                                )

            # 更新上一次的符号
            self.exp2_last_angle_sign = current_sign

            return self.exp2_period

        except Exception as e:
            carb.log_error(f"❌ [Exp2] Period calculation error: {e}")
            import traceback
            traceback.print_exc()
            return self.exp2_period

    async def _simulation_state_monitor(self):
        while True:
            try:
                tl = omni.timeline.get_timeline_interface()

                # 始终发送遥测数据（无论仿真是否运行）
                if self.ws_clients:
                    current_time = time.time()

                    # 根据当前实验发送不同的遥测数据
                    if self.current_experiment == "1":
                        # 实验1：角动量守恒
                        disk_vel, ring_vel = 0.0, 0.0
                        if tl.is_playing():
                            disk_vel, ring_vel = self._get_actual_angular_velocities()

                        # 保留两位小数精度
                        disk_vel = round(disk_vel, 2)
                        ring_vel = round(ring_vel, 2)

                        # 计算角动量 L = I * ω
                        angular_momentum = round(self.exp1_disk_mass * disk_vel + self.exp1_ring_mass * ring_vel, 2)

                        msg = {
                            "type": "telemetry",
                            "data": {
                                "timestamp": current_time,
                                "disk_angular_velocity": disk_vel,
                                "ring_angular_velocity": ring_vel,
                                "angular_momentum": angular_momentum,
                                "disk_mass": self.exp1_disk_mass,
                                "ring_mass": self.exp1_ring_mass,
                                "initial_velocity": round(self.exp1_initial_vel, 2),
                                "is_running": tl.is_playing()
                            }
                        }
                    elif self.current_experiment == "2":
                        # 实验2：大角度单摆（角度单位：度）
                        angle = 0.0
                        period = 0.0
                        if tl.is_playing():
                            angle = self._get_exp2_angle()
                            period = self._calculate_exp2_period(angle, current_time)

                        # 度数保留2位小数精度
                        angle = round(angle, 2)
                        period = round(period, 2)

                        # 调试日志：每5秒打印一次角度值
                        if not hasattr(self, '_last_angle_log_time'):
                            self._last_angle_log_time = 0
                        if current_time - self._last_angle_log_time >= 5.0:
                            carb.log_warn(f"📊 [Exp2 Telemetry] Angle={angle}° (range should be -180 to 180)")
                            self._last_angle_log_time = current_time

                        msg = {
                            "type": "telemetry",
                            "data": {
                                "timestamp": current_time,
                                "angle": angle,
                                "period": period,
                                "initial_angle": self.exp2_initial_angle,
                                "mass1": self.exp2_mass1,
                                "mass2": self.exp2_mass2,
                                "is_running": tl.is_playing()
                            }
                        }
                    else:
                        # 默认发送空数据
                        msg = {
                            "type": "telemetry",
                            "data": {
                                "timestamp": current_time,
                                "is_running": tl.is_playing()
                            }
                        }

                    for ws in list(self.ws_clients):
                        if not ws.closed:
                            await ws.send_json(msg)
            except Exception as e:
                carb.log_warn(f"⚠️ Telemetry error: {e}")
            await asyncio.sleep(config.TELEMETRY_BROADCAST_INTERVAL)

    async def start(self):
        if not HAS_WEBRTC: return
        self.app = web.Application()
        self.app.router.add_post("/offer", self.offer)
        self.app.router.add_post("/camera", self.camera_control)
        self.app.router.add_post("/load_usd", self.load_usd)
        self.app.router.add_post("/reinit_video", self.reinit_video)
        self.app.router.add_get("/diagnose_video", self.diagnose_video)
        self.app.router.add_get("/diagnose", self.diagnose)
        async def options(r): 
            return web.Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type"})
        self.app.router.add_options("/{tail:.*}", options)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.http_port)
        await self.site.start()

        self.ws_app = web.Application()
        self.ws_app.router.add_get("/", self.websocket_handler)
        self.ws_runner = web.AppRunner(self.ws_app)
        await self.ws_runner.setup()
        self.ws_site = web.TCPSite(self.ws_runner, self.host, self.ws_port)
        await self.ws_site.start()
        
        self._monitor_task = asyncio.ensure_future(self._simulation_state_monitor())
        carb.log_info(f"🚀 Server started: HTTP {self.http_port}, WS {self.ws_port}, HostIP: {getattr(config, 'HOST_IP', 'Auto')}")

        # 不要在启动时自动应用实验2参数！
        # 原因：这会修改 USD 场景中的物理参数（质量、阻尼、关节配置）
        # 正确做法：只在用户进入实验2时才应用参数（见 line 677: enter_experiment 处理）
        # await self._apply_exp2_params()
        # carb.log_info(f"✅ Applied default params: Angle={self.exp2_initial_angle}°, Mass1={self.exp2_mass1}kg, Mass2={self.exp2_mass2}kg")

    async def stop(self):
        if self._monitor_task: self._monitor_task.cancel()
        if self.site: await self.site.stop()
        if self.ws_site: await self.ws_site.stop()
        for pc in self.pcs: await pc.close()
    # ---- 新增：诊断接口 ----
    async def diagnose(self, request):
        try:
            from diagnose import run_diagnostics
            result = await run_diagnostics(self)
            return web.json_response(result, status=200 if result["success"] else 500)
        except Exception as e:
            carb.log_error(f"[Diagnose] Error: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response({"error": "Diagnosis internal error"}, status=500)
