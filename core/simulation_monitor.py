"""
Simulation Monitor Module
Extracted from isaac_webrtc_server.py
Monitors simulation state and broadcasts telemetry data
"""

import asyncio
import time
from typing import Optional, Callable, Any
import omni.timeline

from config import (
    SIMULATION_CHECK_INTERVAL,
    STATE_BROADCAST_INTERVAL,
    TELEMETRY_BROADCAST_INTERVAL
)
from utils.logging_helper import simulation_logger


class SimulationMonitor:
    """
    Monitors simulation state and broadcasts updates
    - Enforces auto-stop when simulation control is disabled
    - Broadcasts simulation state periodically
    - Broadcasts telemetry data (angular velocities, etc.)
    """

    def __init__(
        self,
        experiment_manager=None,
        broadcast_callback: Optional[Callable] = None
    ):
        """
        Initialize simulation monitor

        Args:
            experiment_manager: Reference to ExperimentManager for telemetry data
            broadcast_callback: Async callback function for broadcasting messages
                              Signature: async def callback(message: dict)
        """
        self.experiment_manager = experiment_manager
        self.broadcast_callback = broadcast_callback

        # Control flags
        self.auto_stop_enabled = True
        self.simulation_control_enabled = False

        # Monitoring state
        self._monitor_task = None
        self._is_running = False

        # Broadcast timing
        self._last_stop_check = 0
        self._last_state_broadcast = 0
        self._last_telemetry_broadcast = 0
        self._last_telemetry_log = 0
        self._telemetry_count = 0
        self._telemetry_fail_logged = False

        simulation_logger.info("Simulation monitor initialized")

    def enable_auto_stop(self, enabled: bool = True):
        """
        Enable/disable automatic simulation stop

        Args:
            enabled: True to enable auto-stop, False to disable
        """
        self.auto_stop_enabled = enabled
        simulation_logger.info(f"Auto-stop {'enabled' if enabled else 'disabled'}")

    def enable_simulation_control(self, enabled: bool = True):
        """
        Enable/disable simulation control

        Args:
            enabled: True to allow simulation to run, False to lock it
        """
        self.simulation_control_enabled = enabled
        simulation_logger.info(
            f"Simulation control {'enabled' if enabled else 'disabled'}"
        )

    async def start(self):
        """Start the simulation monitor"""
        if self._is_running:
            simulation_logger.warn("Monitor already running")
            return

        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        simulation_logger.info("Simulation monitor started")

    async def stop(self):
        """Stop the simulation monitor"""
        if not self._is_running:
            return

        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        simulation_logger.info("Simulation monitor stopped")

    async def _monitor_loop(self):
        """
        Main monitoring loop
        - Checks and enforces auto-stop when enabled
        - Broadcasts simulation state periodically
        - Broadcasts telemetry data at higher frequency
        """
        simulation_logger.info("Simulation state monitor started")

        try:
            while self._is_running:
                await asyncio.sleep(SIMULATION_CHECK_INTERVAL)

                current_time = time.time()
                timeline = omni.timeline.get_timeline_interface()

                # Auto-stop enforcement
                if self.auto_stop_enabled and not self.simulation_control_enabled:
                    try:
                        if timeline.is_playing():
                            # Detected unauthorized playback, stop immediately
                            timeline.stop()

                            # Avoid log spam, max once per 2 seconds
                            if current_time - self._last_stop_check > 2.0:
                                simulation_logger.info(
                                    "Monitor: Detected unauthorized simulation, force stopped"
                                )
                                self._last_stop_check = current_time

                                # Broadcast to all clients
                                await self._broadcast({
                                    "type": "simulation_stopped",
                                    "is_playing": False,
                                    "reason": "auto_stopped"
                                })
                    except Exception as e:
                        simulation_logger.error(f"Monitor check error: {e}", suppress=True)

                # Broadcast simulation state periodically
                if current_time - self._last_state_broadcast > STATE_BROADCAST_INTERVAL:
                    try:
                        is_playing = timeline.is_playing()
                        current_sim_time = timeline.get_current_time()
                        start_time = timeline.get_start_time()
                        end_time = timeline.get_end_time()

                        await self._broadcast({
                            "type": "simulation_state",
                            "running": is_playing,
                            "paused": not is_playing and current_sim_time > start_time,
                            "time": current_sim_time,
                            "step": 0
                        })

                        self._last_state_broadcast = current_time

                    except Exception as e:
                        simulation_logger.error(f"State broadcast error: {e}", suppress=True)

                # Broadcast telemetry data (higher frequency)
                if current_time - self._last_telemetry_broadcast > TELEMETRY_BROADCAST_INTERVAL:
                    try:
                        is_playing = timeline.is_playing()

                        # Only get and broadcast angular velocity data when simulation is running
                        if is_playing and self.experiment_manager:
                            ring_vel, disk_vel = self.experiment_manager.get_angular_velocities()

                            if ring_vel is not None and disk_vel is not None:
                                # Log debug info every 10 seconds (avoid spam)
                                self._telemetry_count += 1

                                if current_time - self._last_telemetry_log >= 10:
                                    simulation_logger.info(
                                        f"Telemetry data (#{self._telemetry_count}): "
                                        f"ring={ring_vel:.3f}, disk={disk_vel:.3f} rad/s, "
                                        f"broadcast frequency=3Hz (3x per second)"
                                    )
                                    self._last_telemetry_log = current_time

                                # Calculate angular momentum (simplified: L = I * ω)
                                # For disk: I = 0.5 * m * r^2
                                if hasattr(self.experiment_manager, 'exp1_disk_mass'):
                                    disk_moment = (
                                        0.5 *
                                        self.experiment_manager.exp1_disk_mass *
                                        (self.experiment_manager.exp1_disk_radius ** 2)
                                    )
                                    ring_moment = (
                                        0.5 *
                                        self.experiment_manager.exp1_ring_mass *
                                        (self.experiment_manager.exp1_ring_radius ** 2)
                                    )

                                    # Total angular momentum
                                    disk_angular_momentum = disk_moment * disk_vel
                                    ring_angular_momentum = ring_moment * ring_vel
                                    total_angular_momentum = (
                                        disk_angular_momentum + ring_angular_momentum
                                    )

                                    # Broadcast telemetry data
                                    await self._broadcast({
                                        "type": "telemetry",
                                        "data": {
                                            "timestamp": current_time,
                                            "fps": 3,  # Update frequency: 3x per second
                                            "angular_velocity": disk_vel,  # Disk angular velocity (compatibility)
                                            "disk_angular_velocity": disk_vel,
                                            "ring_angular_velocity": ring_vel,
                                            "angular_momentum": total_angular_momentum
                                        }
                                    })
                                else:
                                    # No experiment manager parameters, send basic data
                                    await self._broadcast({
                                        "type": "telemetry",
                                        "data": {
                                            "timestamp": current_time,
                                            "fps": 3,
                                            "disk_angular_velocity": disk_vel,
                                            "ring_angular_velocity": ring_vel
                                        }
                                    })
                            else:
                                # If failed to get angular velocities, log once
                                if not self._telemetry_fail_logged:
                                    simulation_logger.warn(
                                        f"Failed to get angular velocities: "
                                        f"ring={ring_vel}, disk={disk_vel}"
                                    )
                                    self._telemetry_fail_logged = True

                        self._last_telemetry_broadcast = current_time

                    except Exception as e:
                        simulation_logger.error(f"Telemetry broadcast error: {e}", suppress=True)

        except asyncio.CancelledError:
            simulation_logger.info("Simulation state monitor stopped")
            raise

    async def _broadcast(self, message: dict):
        """
        Broadcast message using the callback

        Args:
            message: Message dictionary to broadcast
        """
        if self.broadcast_callback:
            try:
                await self.broadcast_callback(message)
            except Exception as e:
                simulation_logger.error(
                    f"Broadcast callback error: {e}",
                    suppress=True
                )

    def get_state(self) -> dict:
        """
        Get current monitor state

        Returns:
            Dictionary with monitor state
        """
        return {
            "is_running": self._is_running,
            "auto_stop_enabled": self.auto_stop_enabled,
            "simulation_control_enabled": self.simulation_control_enabled,
            "telemetry_count": self._telemetry_count
        }
