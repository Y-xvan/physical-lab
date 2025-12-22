
import asyncio
import math
import os
import omni.usd
import omni.timeline
from pxr import UsdGeom, Gf, UsdPhysics
import omni.kit.viewport.utility as vp_util
from typing import Optional, Tuple

import config
from utils.logging_helper import server_logger

class ExperimentManager:
    """
    实验管理器 - 负责物理参数设置和状态获取
    """

    def __init__(self, camera_controller=None):
        self.camera_controller = camera_controller
        self.current_experiment_id = None

        # 实验1参数
        self.exp1_disk_mass = config.EXP1_DEFAULT_DISK_MASS
        self.exp1_ring_mass = config.EXP1_DEFAULT_RING_MASS
        self.exp1_initial_vel = config.EXP1_DEFAULT_INITIAL_VELOCITY

        # Dynamic Control 接口与句柄缓存
        self._dc_interface = None
        self._disk_handle = None
        self._ring_handle = None
        
        # 标记是否需要重新获取句柄
        self._dirty_handles = True

        server_logger.info("Experiment manager initialized")

    def _initialize_dc_interface(self):
        """初始化 DC 接口"""
        if not self._dc_interface:
            try:
                from omni.isaac.dynamic_control import _dynamic_control
                self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()
            except ImportError:
                server_logger.error("Failed to import Dynamic Control")

    def _refresh_handles(self):
        """
        刷新刚体句柄缓存。
        在场景加载、重置或首次运行时调用，避免每帧查找路径。
        """
        self._initialize_dc_interface()
        if not self._dc_interface:
            return

        from omni.isaac.dynamic_control import _dynamic_control
        INVALID = _dynamic_control.INVALID_HANDLE

        # 获取 Disk 句柄
        self._disk_handle = self._dc_interface.get_rigid_body(config.EXP1_DISK_PATH)
        if self._disk_handle == INVALID:
            # 尝试备用路径（兼容性）
            self._disk_handle = self._dc_interface.get_rigid_body("/World/disk")
        
        # 获取 Ring 句柄
        self._ring_handle = self._dc_interface.get_rigid_body(config.EXP1_RING_PATH)
        if self._ring_handle == INVALID:
            self._ring_handle = self._dc_interface.get_rigid_body("/World/ring")

        server_logger.info(f"Handles refreshed. Disk: {self._disk_handle}, Ring: {self._ring_handle}")
        self._dirty_handles = False

    async def _update_mass_safe(self, prim_path: str, mass: float) -> bool:
        """
        [关键修复] 安全地更新质量
        如果在播放中，先暂停 -> 修改 -> 恢复播放，确保物理引擎生效。
        """
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage: return False

            prim = stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                server_logger.warn(f"Prim not found: {prim_path}")
                return False

            tl = omni.timeline.get_timeline_interface()
            was_playing = tl.is_playing()

            if was_playing:
                tl.pause()
                # 等待一帧以确保状态切换
                await asyncio.sleep(0.05)

            # 修改 USD 属性
            mass_api = UsdPhysics.MassAPI.Apply(prim)
            mass_api.GetMassAttr().Set(mass)

            # 强制刷新句柄（物理属性改变可能导致内部重置）
            self._dirty_handles = True

            if was_playing:
                await asyncio.sleep(0.05)
                tl.play()
            
            return True
        except Exception as e:
            server_logger.error(f"Failed to update mass for {prim_path}: {e}")
            return False

    async def set_exp1_disk_mass(self, value: float) -> bool:
        """设置圆盘质量"""
        self.exp1_disk_mass = value
        server_logger.info(f"Setting Disk Mass -> {value}")
        return await self._update_mass_safe(config.EXP1_DISK_PATH, value)

    async def set_exp1_ring_mass(self, value: float) -> bool:
        """设置圆环质量"""
        self.exp1_ring_mass = value
        server_logger.info(f"Setting Ring Mass -> {value}")
        return await self._update_mass_safe(config.EXP1_RING_PATH, value)

    async def set_exp1_initial_velocity(self, value: float) -> bool:
        """设置初始角速度"""
        self.exp1_initial_vel = value
        
        # 初始速度通常只需要在 Reset 后设置一次，或者立即设置
        # 这里直接通过 DC 设置瞬时速度
        self._initialize_dc_interface()
        if self._dirty_handles: self._refresh_handles()

        from omni.isaac.dynamic_control import _dynamic_control
        if self._dc_interface and self._disk_handle != _dynamic_control.INVALID_HANDLE:
            # Z轴角速度
            self._dc_interface.set_rigid_body_angular_velocity(self._disk_handle, [0.0, 0.0, value])
            # 唤醒刚体
            self._dc_interface.wake_up_rigid_body(self._disk_handle)
            return True
        return False

    def get_angular_velocities(self) -> Tuple[Optional[float], Optional[float]]:
        """
        [关键优化] 高频获取角速度
        使用缓存的句柄直接读取，不进行字符串路径查找。
        """
        if self._dirty_handles:
            self._refresh_handles()

        if not self._dc_interface:
            return 0.0, 0.0

        from omni.isaac.dynamic_control import _dynamic_control
        INVALID = _dynamic_control.INVALID_HANDLE
        
        d_vel = 0.0
        r_vel = 0.0

        # 获取 Disk 速度
        if self._disk_handle != INVALID:
            v = self._dc_interface.get_rigid_body_angular_velocity(self._disk_handle)
            if v: d_vel = v[2] # 取 Z 轴分量

        # 获取 Ring 速度
        if self._ring_handle != INVALID:
            v = self._dc_interface.get_rigid_body_angular_velocity(self._ring_handle)
            if v: r_vel = v[2] # 取 Z 轴分量

        return r_vel, d_vel

    async def reset_all_rigid_bodies_velocity(self):
        """重置所有速度并清理句柄缓存"""
        self._dirty_handles = True # 标记句柄需要刷新
        try:
            # 简化的重置逻辑：调用 Stop 实际上 Isaac Sim 会重置物理
            # 这里只需确保逻辑层面的清理
            pass 
        except Exception as e:
            server_logger.error(f"Reset error: {e}")

    async def enter_experiment(self, experiment_id: str):
        """进入实验"""
        self.current_experiment_id = experiment_id
        # 强制刷新句柄，因为可能加载了新 USD
        self._dirty_handles = True 
        server_logger.info(f"Entered Experiment {experiment_id}")
        # 这里可以加入加载 Camera 配置的逻辑