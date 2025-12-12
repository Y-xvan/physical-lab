"""
Experiment Manager Module
Extracted from isaac_webrtc_server.py
Handles experiment setup, parameter management, and physics state
"""

import asyncio
import math
import os
import carb
import omni.usd
import omni.timeline
from pxr import UsdGeom, Gf, UsdPhysics
import omni.kit.viewport.utility as vp_util
from typing import Optional, Tuple

from config import (
    EXP1_DEFAULT_DISK_MASS,
    EXP1_DEFAULT_RING_MASS,
    EXP1_DEFAULT_DISK_RADIUS,
    EXP1_DEFAULT_RING_RADIUS,
    EXP1_DEFAULT_INITIAL_VELOCITY,
    CAMERA_SCRIPT_DIR
)
from utils.logging_helper import server_logger


class ExperimentManager:
    """
    Manages experiment setup, parameters, and physics state
    Currently supports Experiment 1 (Angular Momentum Conservation)
    Placeholders for Experiments 2-8
    """

    def __init__(self, camera_controller=None):
        """
        Initialize experiment manager

        Args:
            camera_controller: Optional reference to CameraController instance
        """
        self.camera_controller = camera_controller
        self.current_experiment_id = None

        # Experiment 1 parameters (Angular Momentum Conservation)
        self.exp1_disk_mass = EXP1_DEFAULT_DISK_MASS
        self.exp1_ring_mass = EXP1_DEFAULT_RING_MASS
        self.exp1_disk_radius = EXP1_DEFAULT_DISK_RADIUS
        self.exp1_ring_radius = EXP1_DEFAULT_RING_RADIUS
        self.exp1_disk_initial_velocity = EXP1_DEFAULT_INITIAL_VELOCITY

        # Dynamic Control interface (lazy initialization)
        self._dc_interface = None

        # Error tracking flags
        self._ring_error_logged = False
        self._disk_error_logged = False
        self._ring_handle_error_logged = False
        self._disk_handle_error_logged = False
        self._ring_vel_success_logged = False
        self._disk_vel_success_logged = False

        server_logger.info("Experiment manager initialized")

    async def enter_experiment(self, experiment_id: str) -> bool:
        """
        Enter an experiment without reloading the scene
        Stops simulation, resets physics state, and switches camera

        Args:
            experiment_id: Experiment ID ("1" to "8")

        Returns:
            True if successful, False otherwise
        """
        try:
            if not experiment_id:
                server_logger.error("experiment_id is required")
                return False

            server_logger.info(f"Entering experiment {experiment_id} (without reloading USD)")

            old_experiment_id = self.current_experiment_id
            self.current_experiment_id = experiment_id

            # Ensure simulation is stopped
            timeline = omni.timeline.get_timeline_interface()
            was_playing = timeline.is_playing()
            if was_playing:
                timeline.stop()
                server_logger.info("Simulation stopped")

            # Reset timeline to initial time
            timeline.set_current_time(timeline.get_start_time())

            # Wait for scene to stabilize
            await asyncio.sleep(0.3)

            # Reset all rigid bodies velocity to 0 (clear physics state)
            server_logger.info("Resetting physics state...")
            await self.reset_all_rigid_bodies_velocity()

            # Switch camera to corresponding experiment
            server_logger.info(f"Loading camera configuration for experiment {experiment_id}...")
            await self.setup_camera_for_experiment(experiment_id)

            server_logger.info(
                f"Successfully entered experiment {experiment_id}, "
                f"previous: {old_experiment_id}"
            )
            return True

        except Exception as e:
            server_logger.error(f"Failed to enter experiment: {e}", exc_info=True)
            return False

    async def apply_exp1_params(self) -> bool:
        """
        Apply all Experiment 1 physics parameters (called after reset)
        Includes retry mechanism for better error handling

        Returns:
            True if successful, False otherwise
        """
        max_retries = 3
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                server_logger.info(
                    f"Applying experiment 1 parameters (attempt {attempt + 1}/{max_retries})..."
                )

                stage = omni.usd.get_context().get_stage()
                if not stage:
                    server_logger.warn("Stage not available")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    return False

                # Set disk mass
                disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
                if disk_prim and disk_prim.IsValid():
                    mass_api = UsdPhysics.MassAPI.Apply(disk_prim)
                    mass_api.GetMassAttr().Set(self.exp1_disk_mass)
                    server_logger.info(f"Disk mass: {self.exp1_disk_mass} kg")
                else:
                    server_logger.warn("Disk prim not found")

                # Set ring mass
                ring_prim = stage.GetPrimAtPath("/World/exp1/ring")
                if ring_prim and ring_prim.IsValid():
                    mass_api = UsdPhysics.MassAPI.Apply(ring_prim)
                    mass_api.GetMassAttr().Set(self.exp1_ring_mass)
                    server_logger.info(f"Ring mass: {self.exp1_ring_mass} kg")
                else:
                    server_logger.warn("Ring prim not found")

                # Set disk initial angular velocity
                if self.exp1_disk_initial_velocity != 0.0:
                    if not self._dc_interface:
                        self._initialize_dc_interface()

                    if self._dc_interface and disk_prim and disk_prim.IsValid():
                        disk_path = "/World/exp1/disk"
                        rb = self._dc_interface.get_rigid_body(disk_path)

                        from omni.isaac.dynamic_control import _dynamic_control
                        if rb != _dynamic_control.INVALID_HANDLE:
                            angular_velocity = [0.0, 0.0, self.exp1_disk_initial_velocity]
                            self._dc_interface.set_rigid_body_angular_velocity(
                                rb, angular_velocity
                            )
                            server_logger.info(
                                f"Disk initial angular velocity: "
                                f"{self.exp1_disk_initial_velocity} rad/s"
                            )
                        else:
                            server_logger.warn("Unable to get disk rigid body handle")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue

                server_logger.info("Experiment 1 parameters applied successfully")
                return True

            except Exception as e:
                server_logger.error(
                    f"Failed to apply experiment 1 parameters "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    server_logger.info(f"Waiting {retry_delay}s before retry...")
                    await asyncio.sleep(retry_delay)
                else:
                    server_logger.error("All retries exhausted", exc_info=True)
                    return False

        return False

    async def set_exp1_disk_mass(self, value: float) -> bool:
        """Set Experiment 1 disk mass"""
        try:
            server_logger.info(f"Setting disk mass: {value} kg")
            self.exp1_disk_mass = value

            stage = omni.usd.get_context().get_stage()
            if not stage:
                raise Exception("Stage not available")

            disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
            if disk_prim and disk_prim.IsValid():
                mass_api = UsdPhysics.MassAPI.Apply(disk_prim)
                mass_api.GetMassAttr().Set(value)
                server_logger.info(f"Disk mass set to: {value} kg")
                return True
            else:
                server_logger.warn("Disk prim not found at /World/exp1/disk")
                return False

        except Exception as e:
            server_logger.error(f"Failed to set disk mass: {e}", exc_info=True)
            return False

    async def set_exp1_ring_mass(self, value: float) -> bool:
        """Set Experiment 1 ring mass"""
        try:
            server_logger.info(f"Setting ring mass: {value} kg")
            self.exp1_ring_mass = value

            stage = omni.usd.get_context().get_stage()
            if not stage:
                raise Exception("Stage not available")

            ring_prim = stage.GetPrimAtPath("/World/exp1/ring")
            if ring_prim and ring_prim.IsValid():
                mass_api = UsdPhysics.MassAPI.Apply(ring_prim)
                mass_api.GetMassAttr().Set(value)
                server_logger.info(f"Ring mass set to: {value} kg")
                return True
            else:
                server_logger.warn("Ring prim not found at /World/exp1/ring")
                return False

        except Exception as e:
            server_logger.error(f"Failed to set ring mass: {e}", exc_info=True)
            return False

    async def set_exp1_initial_velocity(self, value: float) -> bool:
        """Set Experiment 1 disk initial angular velocity"""
        try:
            server_logger.info(f"Setting disk initial angular velocity: {value} rad/s")
            self.exp1_disk_initial_velocity = value

            stage = omni.usd.get_context().get_stage()
            if not stage:
                raise Exception("Stage not available")

            disk_prim = stage.GetPrimAtPath("/World/exp1/disk")
            if disk_prim and disk_prim.IsValid():
                if not self._dc_interface:
                    self._initialize_dc_interface()

                if self._dc_interface:
                    disk_path = "/World/exp1/disk"
                    rb = self._dc_interface.get_rigid_body(disk_path)

                    from omni.isaac.dynamic_control import _dynamic_control
                    if rb != _dynamic_control.INVALID_HANDLE:
                        angular_velocity = [0.0, 0.0, value]
                        self._dc_interface.set_rigid_body_angular_velocity(
                            rb, angular_velocity
                        )
                        server_logger.info(
                            f"Disk initial angular velocity set to: {value} rad/s (Z-axis)"
                        )
                        return True
                    else:
                        server_logger.warn("Unable to get disk rigid body handle")
                        return False
                else:
                    server_logger.warn("Dynamic Control interface not available")
                    return False
            else:
                server_logger.warn("Disk prim not found at /World/exp1/disk")
                return False

        except Exception as e:
            server_logger.error(f"Failed to set initial velocity: {e}", exc_info=True)
            return False

    def get_angular_velocities(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Get angular velocities of ring and disk using Dynamic Control interface

        Returns:
            Tuple of (ring_angular_velocity, disk_angular_velocity) in rad/s
            Returns (None, None) if failed
        """
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                return None, None

            # Initialize Dynamic Control interface (lazy initialization)
            if not self._dc_interface:
                self._initialize_dc_interface()

            if not self._dc_interface:
                return 0.0, 0.0

            from omni.isaac.dynamic_control import _dynamic_control
            dc = self._dc_interface

            # Try multiple possible paths
            ring_paths = ["/World/ring", "/World/Robot/ring", "/Robot/ring", "/ring"]
            disk_paths = ["/World/disk", "/World/Robot/disk", "/Robot/disk", "/disk"]

            ring_prim = None
            disk_prim = None
            ring_path = None
            disk_path = None

            # Find ring
            for path in ring_paths:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    ring_prim = prim
                    ring_path = path
                    if not self._ring_vel_success_logged:
                        server_logger.info(f"Found ring at: {path}")
                        self._ring_vel_success_logged = True
                    break

            # Find disk
            for path in disk_paths:
                prim = stage.GetPrimAtPath(path)
                if prim and prim.IsValid():
                    disk_prim = prim
                    disk_path = path
                    if not self._disk_vel_success_logged:
                        server_logger.info(f"Found disk at: {path}")
                        self._disk_vel_success_logged = True
                    break

            ring_angular_vel = 0.0
            disk_angular_vel = 0.0

            # Get ring angular velocity
            if ring_prim and ring_prim.IsValid() and ring_path:
                try:
                    rb = dc.get_rigid_body(ring_path)
                    if rb != _dynamic_control.INVALID_HANDLE:
                        angular_vel = dc.get_rigid_body_angular_velocity(rb)
                        if angular_vel is not None:
                            ring_angular_vel = math.sqrt(
                                angular_vel[0]**2 +
                                angular_vel[1]**2 +
                                angular_vel[2]**2
                            )
                    else:
                        if not self._ring_handle_error_logged:
                            server_logger.warn("Unable to get ring rigid body handle")
                            self._ring_handle_error_logged = True

                except Exception as e:
                    if not self._ring_error_logged:
                        server_logger.error(f"Failed to get ring angular velocity: {e}")
                        self._ring_error_logged = True

            # Get disk angular velocity
            if disk_prim and disk_prim.IsValid() and disk_path:
                try:
                    rb = dc.get_rigid_body(disk_path)
                    if rb != _dynamic_control.INVALID_HANDLE:
                        angular_vel = dc.get_rigid_body_angular_velocity(rb)
                        if angular_vel is not None:
                            disk_angular_vel = math.sqrt(
                                angular_vel[0]**2 +
                                angular_vel[1]**2 +
                                angular_vel[2]**2
                            )
                    else:
                        if not self._disk_handle_error_logged:
                            server_logger.warn("Unable to get disk rigid body handle")
                            self._disk_handle_error_logged = True

                except Exception as e:
                    if not self._disk_error_logged:
                        server_logger.error(f"Failed to get disk angular velocity: {e}")
                        self._disk_error_logged = True

            return ring_angular_vel, disk_angular_vel

        except Exception as e:
            server_logger.error(f"Get angular velocities error: {e}", suppress=True)
            return None, None

    async def reset_all_rigid_bodies_velocity(self):
        """
        Reset linear and angular velocity of all rigid bodies to 0
        Used when switching experiments to avoid previous physics state
        """
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                server_logger.warn("Stage not available, cannot reset velocity")
                return

            # Initialize Dynamic Control interface
            if not self._dc_interface:
                self._initialize_dc_interface()

            if not self._dc_interface:
                server_logger.warn("Dynamic Control interface not available")
                return

            from omni.isaac.dynamic_control import _dynamic_control
            dc = self._dc_interface
            reset_count = 0

            # Traverse scene and reset all rigid bodies
            for prim in stage.Traverse():
                rigid_body_api = UsdPhysics.RigidBodyAPI(prim)
                if rigid_body_api:
                    prim_path = str(prim.GetPath())

                    try:
                        rb = dc.get_rigid_body(prim_path)

                        if rb != _dynamic_control.INVALID_HANDLE:
                            # Set linear velocity to 0
                            dc.set_rigid_body_linear_velocity(rb, [0.0, 0.0, 0.0])
                            # Set angular velocity to 0
                            dc.set_rigid_body_angular_velocity(rb, [0.0, 0.0, 0.0])
                            reset_count += 1

                    except Exception:
                        # Ignore errors for individual rigid bodies
                        pass

            server_logger.info(f"Reset velocity of {reset_count} rigid bodies to 0")

        except Exception as e:
            server_logger.error(f"Failed to reset rigid body velocities: {e}", exc_info=True)

    async def setup_camera_for_experiment(self, experiment_id: str):
        """
        Load camera configuration based on experiment ID
        Executes camera setup from camera/usd{N}.py file

        Args:
            experiment_id: Experiment number "1" to "8"
        """
        try:
            # Lock camera controller to prevent automatic updates
            if self.camera_controller:
                self.camera_controller.lock_camera(True)
                server_logger.info(
                    f"Camera controller locked for experiment {experiment_id}"
                )

            # Wait for scene to fully load
            await asyncio.sleep(0.5)

            # Build camera configuration file path
            camera_script_path = os.path.join(CAMERA_SCRIPT_DIR, f"usd{experiment_id}.py")

            # Check if file exists
            if not os.path.exists(camera_script_path):
                server_logger.warn(f"Camera config file not found: {camera_script_path}")
                server_logger.info("Using default camera settings")
                return

            server_logger.info(
                f"Loading camera configuration for experiment {experiment_id}: "
                f"{camera_script_path}"
            )

            # Read and execute camera configuration script
            with open(camera_script_path, 'r', encoding='utf-8') as f:
                camera_script_code = f.read()

            # Execute script
            try:
                # Create execution namespace
                exec_namespace = {
                    'omni': omni,
                    'UsdGeom': UsdGeom,
                    'Gf': Gf,
                    'vp_util': vp_util,
                    'print': server_logger.info
                }

                server_logger.info(f"Executing camera script: {camera_script_path}")

                # Execute with same namespace for globals and locals
                exec(camera_script_code, exec_namespace, exec_namespace)
                server_logger.info(
                    f"Camera configuration for experiment {experiment_id} "
                    f"applied successfully!"
                )

                # Verify camera settings were applied
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

                                focal_length = camera.GetFocalLengthAttr().Get()
                                xform_ops = xformable.GetOrderedXformOps()

                                server_logger.info(f"Camera settings verified:")
                                server_logger.info(f"  Camera path: {camera_path}")
                                server_logger.info(f"  Focal length: {focal_length} mm")

                                for op in xform_ops:
                                    if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                                        pos = op.Get()
                                        server_logger.info(
                                            f"  Position: ({pos[0]:.3f}, "
                                            f"{pos[1]:.3f}, {pos[2]:.3f})"
                                        )
                                    elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                                        rot = op.Get()
                                        server_logger.info(
                                            f"  Rotation: ({rot[0]:.2f}, "
                                            f"{rot[1]:.2f}, {rot[2]:.2f})"
                                        )
                except Exception as verify_error:
                    server_logger.warn(f"Camera verification failed: {verify_error}")

            except Exception as exec_error:
                server_logger.error(f"Camera script execution failed: {exec_error}", exc_info=True)

        except FileNotFoundError as e:
            server_logger.error(f"Camera config file not found: {e}")
            server_logger.info("Using default camera settings")
        except Exception as e:
            server_logger.error(f"Failed to load camera configuration: {e}", exc_info=True)
            server_logger.info("Using default camera settings")

    def _initialize_dc_interface(self):
        """Initialize Dynamic Control interface (lazy initialization)"""
        try:
            from omni.isaac.dynamic_control import _dynamic_control
            self._dc_interface = _dynamic_control.acquire_dynamic_control_interface()
            if self._dc_interface:
                server_logger.info("Dynamic Control interface initialized successfully")
            else:
                server_logger.error("Dynamic Control interface initialization failed")
                self._dc_interface = None
        except ImportError as e:
            server_logger.error(f"Cannot import Dynamic Control: {e}")
            self._dc_interface = None

    # ========== Placeholders for Experiments 2-8 ==========

    async def apply_exp2_params(self):
        """Placeholder for Experiment 2 parameter application"""
        server_logger.info("Experiment 2 not yet implemented")
        pass

    async def apply_exp3_params(self):
        """Placeholder for Experiment 3 parameter application"""
        server_logger.info("Experiment 3 not yet implemented")
        pass

    async def apply_exp4_params(self):
        """Placeholder for Experiment 4 parameter application"""
        server_logger.info("Experiment 4 not yet implemented")
        pass

    async def apply_exp5_params(self):
        """Placeholder for Experiment 5 parameter application"""
        server_logger.info("Experiment 5 not yet implemented")
        pass

    async def apply_exp6_params(self):
        """Placeholder for Experiment 6 parameter application"""
        server_logger.info("Experiment 6 not yet implemented")
        pass

    async def apply_exp7_params(self):
        """Placeholder for Experiment 7 parameter application"""
        server_logger.info("Experiment 7 not yet implemented")
        pass

    async def apply_exp8_params(self):
        """Placeholder for Experiment 8 parameter application"""
        server_logger.info("Experiment 8 not yet implemented")
        pass
