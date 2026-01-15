import asyncio
import time
from typing import Optional, Callable
import omni.timeline

from config import (
    SIMULATION_CHECK_INTERVAL,
    TELEMETRY_BROADCAST_INTERVAL
)
from utils.logging_helper import simulation_logger

class SimulationMonitor:
    """
    仿真监控器
    负责以高频率（如 20Hz）广播物理数据
    """

    def __init__(self, experiment_manager=None, broadcast_callback: Optional[Callable] = None):
        self.experiment_manager = experiment_manager
        self.broadcast_callback = broadcast_callback
        self._monitor_task = None
        self._is_running = False

    async def start(self):
        if self._is_running: return
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        simulation_logger.info(f"Telemetry Monitor started at {1.0/TELEMETRY_BROADCAST_INTERVAL:.1f} Hz")

    async def stop(self):
        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

    async def _monitor_loop(self):
        """主监控循环"""
        tl = omni.timeline.get_timeline_interface()
        
        while self._is_running:
            start_time = time.time()
            
            try:
                is_playing = tl.is_playing()

                # 只有在播放时才发送高频遥测数据
                if is_playing and self.experiment_manager:
                    # 使用优化后的方法获取速度
                    r_vel, d_vel = self.experiment_manager.get_angular_velocities()
                    
                    # 构建数据包
                    msg = {
                        "type": "telemetry",
                        "data": {
                            "timestamp": tl.get_current_time(), # 仿真时间
                            "disk_angular_velocity": d_vel,
                            "ring_angular_velocity": r_vel,
                            # 可以根据质量计算角动量 L = I * w
                            "disk_mass": self.experiment_manager.exp1_disk_mass,
                            "ring_mass": self.experiment_manager.exp1_ring_mass
                        }
                    }
                    
                    if self.broadcast_callback:
                        await self.broadcast_callback(msg)

            except Exception as e:
                simulation_logger.error(f"Monitor Loop Error: {e}", suppress=True)

            # 精确控制频率
            elapsed = time.time() - start_time
            sleep_time = max(0, TELEMETRY_BROADCAST_INTERVAL - elapsed)
            await asyncio.sleep(sleep_time)