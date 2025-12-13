"""
Isaac Sim WebRTC Server (完整修复版)
集成 config.py，包含性能优化和自动 Replicator 修复
"""

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

# ============================================================
# 1. 导入配置模块
# ============================================================
try:
    import config
except ImportError:
    # 尝试将当前目录加入 path 以找到 config
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import config
    except ImportError:
        carb.log_error("❌ Critical: 'config.py' not found! Please check file structure.")
        # 定义一些默认值以防万一
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
        config = ConfigMock()

# WebRTC依赖
try:
    from aiohttp import web
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
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

# 日志设置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc")


# ============================================================
# 2. 视频轨道类 (Video Track)
# ============================================================
class IsaacSimVideoTrack(VideoStreamTrack):
    """
    Isaac Sim视频轨道 - 从Isaac Sim捕获帧并编码为视频流
    """

    def __init__(self, width: int = config.VIDEO_WIDTH, height: int = config.VIDEO_HEIGHT, fps: int = config.VIDEO_FPS):
        super().__init__()
        # 🔑 强制尺寸为偶数（编码器要求）
        self.width = width - (width % 2)
        self.height = height - (height % 2)
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.last_frame_time = 0
        self.frame_count = 0

        self.latest_frame = None
        
        # Replicator设置
        self.use_replicator = HAS_REPLICATOR
        self.render_product = None
        self.rgb_annotator = None

        # 错误计数器
        self._frame_error_count = 0
        self._max_error_log = 5

        # 尝试初始化 Replicator
        if self.use_replicator:
            self._init_replicator_internal()

    def _init_replicator_internal(self):
        """同步尝试初始化 Replicator"""
        try:
            viewport = vp_util.get_active_viewport()
            if not viewport:
                return 
                
            camera_path = viewport.get_active_camera()
            if not camera_path:
                return

            # 清理旧资源
            if self.render_product:
                try: rep.destroy.render_product(self.render_product)
                except Exception as e:
                    carb.log_warn(f"Failed to destroy render_product: {e}")

            # 创建 Render Product
            self.render_product = rep.create.render_product(camera_path, (self.width, self.height))
            self.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
            self.rgb_annotator.attach([self.render_product])
            self.use_replicator = True
            carb.log_info(f"📹 Replicator initialized internal: {self.width}x{self.height}")
        except Exception as e:
            carb.log_warn(f"Replicator internal init deferred: {e}")
            self.use_replicator = False

    async def recv(self):
        """
        接收下一帧 - 性能优化版
        """
        # 1. 帧率控制
        current_time = time.time()
        elapsed = current_time - self.last_frame_time
        if elapsed < self.frame_interval:
            await asyncio.sleep(self.frame_interval - elapsed)
        
        self.last_frame_time = time.time()
        self.frame_count += 1

        # 2. 捕获帧
        frame_array = await self._capture_isaac_frame_async()

        # 3. 验证与修复 (优化路径)
        if frame_array is None:
            # 如果捕获失败，生成测试图案
            frame_array = self._generate_test_pattern()
        else:
            # === 快速通道 (Fast Path) ===
            # 大多数情况下帧是正常的，直接检查最关键的属性，避免昂贵的 _validate_and_fix_frame
            is_valid = (
                frame_array.shape == (self.height, self.width, 3) and
                frame_array.dtype == np.uint8 and
                frame_array.flags['C_CONTIGUOUS']
            )

            if not is_valid:
                # 慢速通道：需要修复
                try:
                    frame_array = self._validate_and_fix_frame(frame_array)
                except Exception as e:
                    self._frame_error_count += 1
                    if self._frame_error_count <= self._max_error_log:
                        carb.log_error(f"Frame validation failed: {e}")
                    frame_array = self._generate_safe_frame()

        # 4. 创建 VideoFrame
        try:
            frame = VideoFrame.from_ndarray(frame_array, format="rgb24")
            frame.pts = self.frame_count
            frame.time_base = fractions.Fraction(1, self.fps)
            return frame
        except Exception as e:
            carb.log_error(f"VideoFrame creation error: {e}")
            # 返回最后的安全帧
            return VideoFrame.from_ndarray(self._generate_safe_frame(), format="rgb24")

    def _validate_and_fix_frame(self, frame_array: np.ndarray) -> np.ndarray:
        """完整验证和修复逻辑（慢速通道）"""
        # 1. 类型转换
        if not isinstance(frame_array, np.ndarray):
             return self._generate_safe_frame()
             
        if frame_array.dtype != np.uint8:
            if frame_array.dtype in (np.float32, np.float64):
                # 处理 NaN/Inf 并缩放到 0-255
                frame_array = np.nan_to_num(frame_array, nan=0.0, posinf=1.0, neginf=0.0)
                frame_array = (frame_array.clip(0, 1) * 255).astype(np.uint8)
            else:
                frame_array = frame_array.astype(np.uint8)

        # 2. 通道处理
        if len(frame_array.shape) == 2: # 灰度
             frame_array = np.stack([frame_array] * 3, axis=-1)
        elif len(frame_array.shape) == 3:
            if frame_array.shape[2] == 4: # RGBA -> RGB
                frame_array = frame_array[:, :, :3]
            elif frame_array.shape[2] == 1:
                frame_array = np.concatenate([frame_array] * 3, axis=-1)

        # 3. 尺寸调整
        if frame_array.shape[0] != self.height or frame_array.shape[1] != self.width:
            try:
                from PIL import Image
                img = Image.fromarray(frame_array)
                img = img.resize((self.width, self.height), Image.BILINEAR)
                frame_array = np.array(img)
            except Exception:
                return self._generate_safe_frame()
            
        return np.ascontiguousarray(frame_array)

    def _generate_safe_frame(self) -> np.ndarray:
        """生成绿色帧表示错误"""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:, :, 1] = 128 
        return frame

    def _generate_test_pattern(self) -> np.ndarray:
        """生成测试条纹"""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        w = self.width
        # 简单的RGB条纹
        frame[:, :w//3] = [200, 0, 0]
        frame[:, w//3:2*w//3] = [0, 200, 0]
        frame[:, 2*w//3:] = [0, 0, 200]
        return frame

    async def _capture_isaac_frame_async(self) -> Optional[np.ndarray]:
        """使用 Replicator 捕获数据"""
        if self.use_replicator and self.rgb_annotator:
            try:
                await rep.orchestrator.step_async()
                data = self.rgb_annotator.get_data()
                
                if data is not None and data.size > 0:
                    return data
            except Exception:
                # 如果连续出错，可以在这里加入逻辑禁用 Replicator
                pass
        return None


# ============================================================
# 3. 相机控制器 (Camera Controller)
# ============================================================
class CameraController:
    def __init__(self):
        self.camera_distance = 10.0
        self.camera_azimuth = 45.0
        self.camera_elevation = 30.0
        self.camera_target = Gf.Vec3d(0, 0, 0)
        self.orbit_speed = 0.3
        self.zoom_speed = 0.1
        self.use_custom_camera = False

    def orbit(self, delta_x, delta_y):
        self.camera_azimuth += delta_x * self.orbit_speed
        self.camera_elevation = max(-89, min(89, self.camera_elevation + delta_y * self.orbit_speed))
        self.camera_azimuth = self.camera_azimuth % 360
        self._update_camera()
        
    def pan(self, delta_x, delta_y):
        # 简化的平移逻辑，如果需要可扩展
        pass
        
    def zoom(self, delta):
        self.camera_distance = max(1.0, self.camera_distance + delta * self.zoom_speed)
        self._update_camera()

    def reset(self):
        self.camera_distance = 10.0
        self.camera_azimuth = 45.0
        self.camera_elevation = 30.0
        self.camera_target = Gf.Vec3d(0, 0, 0)
        self._update_camera()

    def _update_camera(self):
        if self.use_custom_camera: return

        try:
            viewport = vp_util.get_active_viewport()
            if not viewport: return
            camera_path = viewport.get_active_camera()
            if not camera_path: return
            
            # 计算位置
            az_rad = math.radians(self.camera_azimuth)
            el_rad = math.radians(self.camera_elevation)
            x = self.camera_distance * math.cos(el_rad) * math.cos(az_rad)
            y = self.camera_distance * math.cos(el_rad) * math.sin(az_rad)
            z = self.camera_distance * math.sin(el_rad)
            
            camera_pos = self.camera_target + Gf.Vec3d(x, y, z)
            
            # 应用到USD Stage
            stage = omni.usd.get_context().get_stage()
            if not stage: return
            
            prim = stage.GetPrimAtPath(camera_path)
            if prim and prim.IsValid():
                xform = UsdGeom.Xformable(prim)
                
                # 设置位置 (简化版：假设已有Translate Op或新建)
                translate_ops = [op for op in xform.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeTranslate]
                if translate_ops:
                    translate_ops[0].Set(camera_pos)
                else:
                    xform.AddTranslateOp().Set(camera_pos)
                
                # 设置旋转 (LookAt逻辑)
                rotation_ops = [op for op in xform.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ]
                if rotation_ops:
                    rot_op = rotation_ops[0]
                else:
                    rot_op = xform.AddRotateXYZOp()
                    
                view_dir = (self.camera_target - camera_pos).GetNormalized()
                pitch = math.degrees(math.asin(-view_dir[2]))
                yaw = math.degrees(math.atan2(view_dir[1], view_dir[0]))
                rot_op.Set(Gf.Vec3f(pitch, 0, yaw - 90))

        except Exception as e:
            pass


# ============================================================
# 4. WebRTC Server 类
# ============================================================
class WebRTCServer:
    """
    主服务器类：处理 HTTP, WebRTC, WebSocket
    """

    def __init__(self, 
                 host: str = config.HTTP_HOST, 
                 http_port: int = config.HTTP_PORT, 
                 ws_port: int = config.WS_PORT):
        self.host = host
        self.http_port = http_port
        self.ws_port = ws_port
        
        self.app = None
        self.runner = None
        self.site = None
        self.ws_app = None 
        self.ws_runner = None
        self.ws_site = None
        
        self.pcs: Set[RTCPeerConnection] = set()
        self.camera_controller = CameraController()
        self.video_track = None
        self.ws_clients = set()
        
        # 仿真控制
        self.simulation_control_enabled = False
        self.auto_stop_enabled = True
        self._monitor_task = None
        
        # 实验参数
        self.current_experiment_id = None
        self.exp1_disk_mass = config.EXP1_DEFAULT_DISK_MASS
        self.exp1_ring_mass = config.EXP1_DEFAULT_RING_MASS
        self.exp1_initial_vel = config.EXP1_DEFAULT_INITIAL_VELOCITY
        
        # 动态控制接口缓存
        self._dc_interface = None

    async def _init_replicator_async(self, track, max_retries=config.REPLICATOR_INIT_MAX_RETRIES):
        """
        统一的 Replicator 异步修复逻辑
        """
        import omni.replicator.core as rep
        
        for attempt in range(1, max_retries + 1):
            try:
                await asyncio.sleep(config.REPLICATOR_INIT_RETRY_DELAY)
                
                viewport = vp_util.get_active_viewport()
                if not viewport: continue
                
                camera_path = viewport.get_active_camera()
                if not camera_path: continue
                
                # 重新创建资源
                if track.render_product:
                    try: rep.destroy.render_product(track.render_product)
                    except: pass
                    
                track.render_product = rep.create.render_product(camera_path, (track.width, track.height))
                track.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
                track.rgb_annotator.attach([track.render_product])
                track.use_replicator = True
                
                # 验证
                await rep.orchestrator.step_async()
                if track.rgb_annotator.get_data() is not None:
                    logger.info("✅ Replicator fixed successfully")
                    return True
            except Exception as e:
                logger.error(f"Replicator fix attempt {attempt} failed: {e}")
        
        return False

    # ---------------- HTTP/WebRTC Handlers ----------------

    async def offer(self, request):
        """WebRTC Offer 处理"""
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        pc = RTCPeerConnection()
        self.pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc.connectionState in ["failed", "closed"]:
                await self.close_peer_connection(pc)

        # 懒加载 Video Track
        if self.video_track is None:
            self.video_track = IsaacSimVideoTrack()
            # 自动修复
            if not self.video_track.use_replicator:
                asyncio.ensure_future(self._init_replicator_async(self.video_track))

        pc.addTrack(self.video_track)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}),
            headers={"Access-Control-Allow-Origin": "*"}
        )

    async def camera_control(self, request):
        params = await request.json()
        action = params.get("action")
        try:
            if action == "orbit":
                self.camera_controller.orbit(params.get("deltaX", 0), params.get("deltaY", 0))
            elif action == "zoom":
                self.camera_controller.zoom(params.get("delta", 0))
            elif action == "reset":
                self.camera_controller.reset()
            return web.Response(text=json.dumps({"status": "ok"}))
        except Exception as e:
            return web.Response(status=500, text=str(e))

    async def load_usd(self, request):
        params = await request.json()
        experiment_id = params.get("experiment_id")
        usd_path = config.DEFAULT_USD_PATH
        
        try:
            success = omni.usd.get_context().open_stage(usd_path)
            if success:
                self.simulation_control_enabled = False
                omni.timeline.get_timeline_interface().stop()
                await self._reset_all_rigid_bodies_velocity()
                
                # 如果有特定的相机设置脚本，这里可以调用
                if experiment_id:
                     await self._setup_camera_for_experiment(experiment_id)
                
                return web.Response(text=json.dumps({"status": "ok", "usd": usd_path}))
            else:
                return web.Response(status=500, text="Failed to load USD")
        except Exception as e:
            return web.Response(status=500, text=str(e))
            
    async def simulation_control(self, request):
        params = await request.json()
        action = params.get("action")
        tl = omni.timeline.get_timeline_interface()
        
        if action == "play":
            self.simulation_control_enabled = True
            tl.play()
        elif action == "pause":
            tl.pause()
        elif action == "stop":
            self.simulation_control_enabled = False
            tl.stop()
        elif action == "reset":
            self.simulation_control_enabled = False
            tl.stop()
            tl.set_current_time(0.0)
            
        return web.Response(text=json.dumps({"status": "ok", "is_playing": tl.is_playing()}))

    async def reinit_video(self, request):
        if self.video_track:
            success = await self._init_replicator_async(self.video_track)
            return web.Response(text=json.dumps({"status": "ok" if success else "failed"}))
        return web.Response(status=400, text="No track")

    async def diagnose_video(self, request):
        status = {
            "track_exists": self.video_track is not None,
            "replicator_active": self.video_track.use_replicator if self.video_track else False,
            "resolution": f"{self.video_track.width}x{self.video_track.height}" if self.video_track else "N/A"
        }
        return web.Response(text=json.dumps(status))

    # ---------------- WebSocket Handlers ----------------

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    mtype = data.get("type")
                    
                    if mtype == "start_simulation":
                        self.simulation_control_enabled = True
                        omni.timeline.get_timeline_interface().play()
                    elif mtype == "stop_simulation":
                        self.simulation_control_enabled = False
                        omni.timeline.get_timeline_interface().stop()
                    elif mtype == "reset":
                        self.simulation_control_enabled = False
                        omni.timeline.get_timeline_interface().stop()
                        omni.timeline.get_timeline_interface().set_current_time(0.0)
                        await self._reset_all_rigid_bodies_velocity()
                        await self._apply_exp1_params() # 重新应用参数
                    
                    # 实验1特定参数
                    elif mtype == "set_mass":
                         val = float(data.get("value", 1.0))
                         self.exp1_disk_mass = val
                         self.exp1_ring_mass = val
                         await self._apply_exp1_params()
                    elif mtype == "set_initial_velocity":
                         val = float(data.get("value", 0.0))
                         self.exp1_initial_vel = val
                         await self._apply_exp1_params()
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    break

        finally:
            self.ws_clients.discard(ws)
        return ws

    async def _apply_exp1_params(self):
        """应用物理参数"""
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage: return
            
            # 设置质量
            for path, mass in [("/World/exp1/disk", self.exp1_disk_mass), ("/World/exp1/ring", self.exp1_ring_mass)]:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    UsdPhysics.MassAPI.Apply(prim).GetMassAttr().Set(mass)
            
            # 设置初速度 (需要 Dynamic Control)
            if self.exp1_initial_vel != 0.0:
                if not self._dc_interface:
                     from omni.isaac.dynamic_control import _dynamic_control
                     self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()
                
                rb = self._dc_interface.get_rigid_body("/World/exp1/disk")
                if rb:
                    self._dc_interface.set_rigid_body_angular_velocity(rb, [0.0, 0.0, self.exp1_initial_vel])
        except Exception as e:
            logger.error(f"Failed to apply exp1 params: {e}")

    async def _reset_all_rigid_bodies_velocity(self):
        try:
            if not self._dc_interface:
                from omni.isaac.dynamic_control import _dynamic_control
                self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()
            
            stage = omni.usd.get_context().get_stage()
            for prim in stage.Traverse():
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):  # ✅ 正确检查
                    rb = self._dc_interface.get_rigid_body(str(prim.GetPath()))
                    if rb:
                        self._dc_interface.set_rigid_body_linear_velocity(rb, [0,0,0])
                        self._dc_interface.set_rigid_body_angular_velocity(rb, [0,0,0])
        except Exception as e:
            logger.error(f"Reset velocity error: {e}")

    async def _setup_camera_for_experiment(self, exp_id):
        """根据 ID 加载 camera 脚本 (简单实现)"""
        # 这里可以使用 importlib 加载 camera/usd{exp_id}.py
        # 为简化，仅打印日志
        logger.info(f"Setting up camera for experiment {exp_id}")
        self.camera_controller.use_custom_camera = True

    # ---------------- Telemetry & Monitoring ----------------

    async def _simulation_state_monitor(self):
        while True:
            try:
                tl = omni.timeline.get_timeline_interface()
                
                if self.auto_stop_enabled and not self.simulation_control_enabled and tl.is_playing():
                    tl.stop()
                    
                if tl.is_playing() and self.ws_clients:
                    disk_vel = 0.0
                    if self._dc_interface:
                        rb = self._dc_interface.get_rigid_body("/World/exp1/disk")
                        if rb:
                            v = self._dc_interface.get_rigid_body_angular_velocity(rb)
                            disk_vel = v[2]

                    msg = {"type": "telemetry", "data": {"time": tl.get_current_time(), "disk_velocity": disk_vel}}
                    
                    for ws in list(self.ws_clients):
                        if not ws.closed:
                            try:
                                await ws.send_json(msg)
                            except:
                                self.ws_clients.discard(ws)
            except Exception as e:
                logger.error(f"Monitor error: {e}")
            
            await asyncio.sleep(config.TELEMETRY_BROADCAST_INTERVAL)

    # ---------------- Lifecycle ----------------

    async def start(self):
        if not HAS_WEBRTC: return

        # HTTP Server
        self.app = web.Application()
        self.app.router.add_post("/offer", self.offer)
        self.app.router.add_post("/camera", self.camera_control)
        self.app.router.add_post("/load_usd", self.load_usd)
        self.app.router.add_post("/simulation", self.simulation_control)
        self.app.router.add_post("/reinit_video", self.reinit_video)
        self.app.router.add_get("/diagnose_video", self.diagnose_video)
        
        # CORS
        async def options(req):
            return web.Response(headers={
                "Access-Control-Allow-Origin": "*", 
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                })
        self.app.router.add_options("/{tail:.*}", options)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.http_port)
        await self.site.start()

        # WebSocket Server (独立端口)
        self.ws_app = web.Application()
        self.ws_app.router.add_get("/", self.websocket_handler)
        self.ws_runner = web.AppRunner(self.ws_app)
        await self.ws_runner.setup()
        self.ws_site = web.TCPSite(self.ws_runner, self.host, self.ws_port)
        await self.ws_site.start()
        
        # 启动后台监控
        self._monitor_task = asyncio.ensure_future(self._simulation_state_monitor())

        carb.log_info(f"🚀 WebRTC Server started. HTTP: {self.http_port}, WS: {self.ws_port}")

    async def stop(self):
        if self._monitor_task: self._monitor_task.cancel()
        if self.site: await self.site.stop()
        if self.ws_site: await self.ws_site.stop()
        for pc in self.pcs: await pc.close()
        carb.log_info("🛑 Server stopped")

    async def close_peer_connection(self, pc):
        self.pcs.discard(pc)
        await pc.close()

    async def _handle_options(self, request):
        return web.Response(headers={"Access-Control-Allow-Origin": "*"})