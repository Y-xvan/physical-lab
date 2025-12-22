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
# 1. 导入配置模块
# ============================================================
try:
    import config
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import config
    except ImportError:
        carb.log_error("❌ Critical: 'config.py' not found!")
        class ConfigMock:
            HTTP_HOST = "0.0.0.0"
            HTTP_PORT = 8080
            WS_HOST = "0.0.0.0"
            WS_PORT = 30000
            VIDEO_WIDTH = 1280
            VIDEO_HEIGHT = 720
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
        """尝试多种方法获取帧"""
        # 方法1: 尝试从 viewport 直接获取
        frame = await self._capture_from_viewport()
        if frame is not None:
            return frame
        
        # 方法2: 使用 Replicator
        frame = await self._capture_from_replicator()
        if frame is not None:
            return frame
        
        return None

    async def _capture_from_viewport(self):
        """直接从 viewport 获取帧 - 禁用，viewport 捕获 API 在当前版本有问题"""
        # viewport 捕获在当前 Isaac Sim 版本中有 API 兼容性问题
        # ByteCapture 和 HdrCaptureHelper 对象需要特殊处理
        # 暂时禁用此方法，只使用 Replicator
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

            # === 1. 触发渲染更新 ===
            app = omni.kit.app.get_app()
            await app.next_update_async()
            
            # === 2. 触发 Replicator 渲染（关键！）===
            try:
                await rep.orchestrator.step_async()
            except Exception as e:
                # 如果 step_async 失败，继续尝试获取数据
                pass

            # === 3. 获取数据 ===
            try:
                data = self.rgb_annotator.get_data()
            except KeyError as e:
                carb.log_warn(f"⚠️ KeyError getting data, reinitializing: {e}")
                self._replicator_initialized = False
                self.rgb_annotator = None
                self.render_product = None
                return None
            
            if data is None:
                # 可能只是渲染还没完成，不要重新初始化
                return None
            
            if data.size == 0:
                # 可能只是渲染还没完成，不要立即重新初始化
                # 只有连续多次失败才重新初始化
                if not hasattr(self, '_empty_count'):
                    self._empty_count = 0
                self._empty_count += 1
                if self._empty_count > 30:  # 连续30次空数据才重新初始化
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
        
        self.exp1_disk_mass = config.EXP1_DEFAULT_DISK_MASS
        self.exp1_ring_mass = config.EXP1_DEFAULT_RING_MASS
        self.exp1_initial_vel = config.EXP1_DEFAULT_INITIAL_VELOCITY
        
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
        
        config = RTCConfiguration(iceServers=[
            RTCIceServer(urls="stun:stun.l.google.com:19302")
        ])
        pc = RTCPeerConnection(configuration=config)
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
        sdp_lines = answer.sdp.splitlines()
        new_sdp_lines = []
        for line in sdp_lines:
            if "c=IN IP4" in line:
                new_sdp_lines.append(f"c=IN IP4 {server_ip}")
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
                carb.log_warn(f"📩 Raw WS message type: {msg.type}")
                if msg.type == web.WSMsgType.TEXT:
                    carb.log_warn(f"📩 Raw data: {msg.data[:200]}")
                    data = json.loads(msg.data)
                    mtype = data.get("type")
                    carb.log_warn(f"📨 Parsed message type: {mtype}")
                    if mtype == "start_simulation":
                        carb.log_warn("▶️ Starting simulation...")
                        self.simulation_control_enabled = True
                        # 设置初始角速度
                        await self._set_initial_angular_velocity()
                        omni.timeline.get_timeline_interface().play()
                        carb.log_warn("✅ Simulation started!")
                    elif mtype == "stop_simulation":
                        carb.log_warn("⏹️ Stopping simulation...")
                        self.simulation_control_enabled = False
                        omni.timeline.get_timeline_interface().stop()
                        carb.log_warn("✅ Simulation stopped!")
                    elif mtype == "reset":
                        # 重置实验：停止仿真，重置时间，重置角速度为0
                        carb.log_warn("🔄 Resetting experiment...")
                        self.simulation_control_enabled = False
                        
                        tl = omni.timeline.get_timeline_interface()
                        tl.stop()
                        tl.set_current_time(0.0)
                        
                        # 重置参数到初始值
                        self.exp1_disk_mass = config.EXP1_DEFAULT_DISK_MASS
                        self.exp1_ring_mass = config.EXP1_DEFAULT_RING_MASS
                        self.exp1_initial_vel = 0.0
                        
                        # 重置到初始位置（不改变速度设置）
                        await self._reset_positions()
                        
                        carb.log_warn("✅ Experiment reset complete!")
                    elif mtype == "enter_experiment":
                        # 进入实验 - 只记录日志，不做其他操作
                        exp_id = data.get("experiment_id", "unknown")
                        carb.log_warn(f"📍 Entered experiment: {exp_id}")
                        # 发送确认消息
                        await ws.send_json({"type": "experiment_entered", "experiment_id": exp_id})
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
                    else:
                        carb.log_warn(f"📨 Received unknown message type: {mtype}")
        finally:
            self.ws_clients.discard(ws)
        return ws

    async def _set_initial_angular_velocity(self):
        """设置 disk 的初始角速度 - 使用多种方法尝试"""
        try:
            # 方法1: 使用 Isaac Sim 的 RigidPrimView
            try:
                from omni.isaac.core.prims import RigidPrim
                disk_rigid = RigidPrim(prim_path="/World/exp1/disk")
                scaled_vel = float(self.exp1_initial_vel) * 1000.0
                # 设置角速度 [wx, wy, wz]
                disk_rigid.set_angular_velocity([0.0, 0.0, scaled_vel])
                carb.log_warn(f"✅ [RigidPrim] Set disk angular velocity: {scaled_vel} rad/s")
                return
            except Exception as e1:
                carb.log_warn(f"⚠️ RigidPrim method failed: {e1}")
            
            # 方法2: 使用 Dynamic Control
            try:
                from omni.isaac.dynamic_control import _dynamic_control
                dc = _dynamic_control.acquire_dynamic_control_interface()
                
                # 获取 rigid body handle
                disk_handle = dc.get_rigid_body("/World/exp1/disk")
                if disk_handle != _dynamic_control.INVALID_HANDLE:
                    scaled_vel = float(self.exp1_initial_vel) * 1000.0
                    dc.set_rigid_body_angular_velocity(disk_handle, [0.0, 0.0, scaled_vel])
                    carb.log_warn(f"✅ [DynamicControl] Set disk angular velocity: {scaled_vel} rad/s")
                    return
                else:
                    carb.log_warn("⚠️ DynamicControl: Invalid disk handle")
            except Exception as e2:
                carb.log_warn(f"⚠️ DynamicControl method failed: {e2}")
            
            # 方法3: 使用 USD API (fallback)
            stage = omni.usd.get_context().get_stage()
            if stage:
                disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
                if disk_prim and disk_prim.IsValid() and disk_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    rb_api = UsdPhysics.RigidBodyAPI(disk_prim)
                    scaled_vel = float(self.exp1_initial_vel) * 1000.0
                    angular_vel = Gf.Vec3f(0.0, 0.0, scaled_vel)
                    rb_api.GetAngularVelocityAttr().Set(angular_vel)
                    carb.log_warn(f"✅ [USD API] Set disk angular velocity: {scaled_vel} rad/s")
                else:
                    carb.log_warn("⚠️ USD API: disk prim not found or no RigidBodyAPI")
                
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
        """只设置质量参数，不动态设置角速度（角速度由物理引擎控制）"""
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage: 
                carb.log_warn("⚠️ No stage found, cannot apply params")
                return
            
            # 设置质量
            paths_and_masses = [("/World/exp1/disk", self.exp1_disk_mass), ("/World/exp1/ring", self.exp1_ring_mass)]
            for path, mass in paths_and_masses:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    if prim.HasAPI(UsdPhysics.MassAPI):
                        UsdPhysics.MassAPI(prim).GetMassAttr().Set(mass)
                        carb.log_info(f"✅ Set mass for {path}: {mass} kg")
                    else:
                        UsdPhysics.MassAPI.Apply(prim).GetMassAttr().Set(mass)
                        carb.log_info(f"✅ Applied MassAPI and set mass for {path}: {mass} kg")
                else:
                    carb.log_warn(f"⚠️ Prim not found: {path}")
            
            carb.log_info(f"📊 Params applied: Disk Mass={self.exp1_disk_mass}kg, Ring Mass={self.exp1_ring_mass}kg")
        except Exception as e:
            carb.log_error(f"💥 Failed to apply params: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_actual_angular_velocities(self):
        """从物理仿真中读取实际的角速度 - 使用简单的 USD API"""
        disk_vel = 0.0
        ring_vel = 0.0
        
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                return 0.0, 0.0
            
            # 读取 disk 的角速度（反向缩放，除以1000）
            disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
            if disk_prim and disk_prim.IsValid() and disk_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                rb_api = UsdPhysics.RigidBodyAPI(disk_prim)
                vel_attr = rb_api.GetAngularVelocityAttr()
                if vel_attr and vel_attr.Get():
                    vel = vel_attr.Get()
                    disk_vel = float(vel[2]) / 1000.0 if vel else 0.0
            
            # 读取 ring 的角速度（反向缩放，除以1000）
            ring_prim = stage.GetPrimAtPath("/World/exp1/ring")
            if ring_prim and ring_prim.IsValid() and ring_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                rb_api = UsdPhysics.RigidBodyAPI(ring_prim)
                vel_attr = rb_api.GetAngularVelocityAttr()
                if vel_attr and vel_attr.Get():
                    vel = vel_attr.Get()
                    ring_vel = float(vel[2]) / 1000.0 if vel else 0.0
            
            return disk_vel, ring_vel
        except:
            return 0.0, 0.0

    async def _simulation_state_monitor(self):
        while True:
            try:
                tl = omni.timeline.get_timeline_interface()
                # 注意：已禁用自动停止逻辑，让用户完全控制仿真
                
                # 发送遥测数据（使用实际的物理数据）
                if tl.is_playing() and self.ws_clients:
                    # 读取实际的角速度
                    disk_vel, ring_vel = self._get_actual_angular_velocities()
                    # 计算角动量 L = I * ω（简化：假设惯性矩与质量成正比）
                    angular_momentum = self.exp1_disk_mass * disk_vel + self.exp1_ring_mass * ring_vel
                    
                    msg = {
                        "type": "telemetry", 
                        "data": {
                            "timestamp": time.time(), 
                            "disk_angular_velocity": disk_vel,
                            "ring_angular_velocity": ring_vel,
                            "angular_momentum": angular_momentum,
                            "disk_mass": self.exp1_disk_mass,
                            "ring_mass": self.exp1_ring_mass
                        }
                    }
                    for ws in list(self.ws_clients):
                        if not ws.closed: await ws.send_json(msg)
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
