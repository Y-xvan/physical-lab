"""
Camera Controller Module
Extracted from isaac_webrtc_server.py
Handles camera orbit, pan, zoom, and reset operations
"""

import math
import carb
import omni.kit.viewport.utility as vp_util
import omni.usd
from pxr import Gf, UsdGeom
from typing import Optional

from config import (
    DEFAULT_CAMERA_DISTANCE,
    DEFAULT_CAMERA_AZIMUTH,
    DEFAULT_CAMERA_ELEVATION
)
from utils.logging_helper import camera_logger


class CameraController:
    """
    Camera controller for Isaac Sim viewport
    Supports orbit, pan, zoom operations with custom camera locking
    """

    def __init__(
        self,
        distance: float = DEFAULT_CAMERA_DISTANCE,
        azimuth: float = DEFAULT_CAMERA_AZIMUTH,
        elevation: float = DEFAULT_CAMERA_ELEVATION
    ):
        """
        Initialize camera controller

        Args:
            distance: Initial camera distance from target
            azimuth: Initial azimuth angle in degrees
            elevation: Initial elevation angle in degrees
        """
        self.camera_distance = distance
        self.camera_azimuth = azimuth
        self.camera_elevation = elevation
        self.camera_target = Gf.Vec3d(0, 0, 0)

        # Control sensitivity
        self.orbit_speed = 0.3
        self.pan_speed = 0.01
        self.zoom_speed = 0.1

        # Custom camera lock (prevents automatic updates)
        self.use_custom_camera = False

        camera_logger.info(
            f"Camera controller initialized: "
            f"distance={distance}, azimuth={azimuth}, elevation={elevation}"
        )

    def orbit(self, delta_x: float, delta_y: float):
        """
        Orbit camera around target

        Args:
            delta_x: Horizontal movement delta
            delta_y: Vertical movement delta
        """
        self.camera_azimuth += delta_x * self.orbit_speed
        self.camera_elevation = max(-89, min(89, self.camera_elevation + delta_y * self.orbit_speed))
        self.camera_azimuth = self.camera_azimuth % 360
        self._update_camera()

    def pan(self, delta_x: float, delta_y: float):
        """
        Pan camera (move target position)

        Args:
            delta_x: Horizontal pan delta
            delta_y: Vertical pan delta
        """
        azimuth_rad = math.radians(self.camera_azimuth)
        right = Gf.Vec3d(-math.sin(azimuth_rad), math.cos(azimuth_rad), 0)
        up = Gf.Vec3d(0, 0, 1)
        self.camera_target += right * delta_x * self.pan_speed
        self.camera_target += up * delta_y * self.pan_speed
        self._update_camera()

    def zoom(self, delta: float):
        """
        Zoom camera (change distance to target)

        Args:
            delta: Zoom delta (positive = zoom out, negative = zoom in)
        """
        self.camera_distance = max(1.0, self.camera_distance + delta * self.zoom_speed)
        self._update_camera()

    def reset(self):
        """Reset camera to default position"""
        self.camera_distance = DEFAULT_CAMERA_DISTANCE
        self.camera_azimuth = DEFAULT_CAMERA_AZIMUTH
        self.camera_elevation = DEFAULT_CAMERA_ELEVATION
        self.camera_target = Gf.Vec3d(0, 0, 0)
        self._update_camera()
        camera_logger.info("Camera reset to default position")

    def lock_camera(self, locked: bool = True):
        """
        Lock/unlock camera to prevent automatic updates

        Args:
            locked: True to lock, False to unlock
        """
        self.use_custom_camera = locked
        if locked:
            camera_logger.info("Camera locked (custom camera mode)")
        else:
            camera_logger.info("Camera unlocked (automatic mode)")

    def _update_camera(self):
        """
        Update camera position and orientation in the viewport
        Internal method - only updates if camera is not locked
        """
        # If using custom camera, don't update (prevents overwriting user settings)
        if self.use_custom_camera:
            return

        try:
            viewport_api = vp_util.get_active_viewport()
            if not viewport_api:
                camera_logger.warn("No active viewport available", suppress=True)
                return

            camera_path = viewport_api.get_active_camera()
            if not camera_path:
                camera_logger.warn("No active camera in viewport", suppress=True)
                return

            # Calculate camera position from spherical coordinates
            azimuth_rad = math.radians(self.camera_azimuth)
            elevation_rad = math.radians(self.camera_elevation)

            x = self.camera_distance * math.cos(elevation_rad) * math.cos(azimuth_rad)
            y = self.camera_distance * math.cos(elevation_rad) * math.sin(azimuth_rad)
            z = self.camera_distance * math.sin(elevation_rad)

            camera_pos = self.camera_target + Gf.Vec3d(x, y, z)

            # Get USD stage and camera prim
            stage = omni.usd.get_context().get_stage()
            if not stage:
                camera_logger.warn("USD stage not available", suppress=True)
                return

            camera_prim = stage.GetPrimAtPath(camera_path)
            if not camera_prim:
                camera_logger.warn(f"Camera prim not found at {camera_path}", suppress=True)
                return

            xformable = UsdGeom.Xformable(camera_prim)

            # Set translation (avoid duplicate operations)
            translate_ops = [
                op for op in xformable.GetOrderedXformOps()
                if op.GetOpType() == UsdGeom.XformOp.TypeTranslate
            ]
            if translate_ops:
                translate_op = translate_ops[0]
            else:
                translate_op = xformable.AddTranslateOp()
            translate_op.Set(camera_pos)

            # Set rotation (avoid duplicate operations)
            rotation_ops = [
                op for op in xformable.GetOrderedXformOps()
                if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ
            ]
            if rotation_ops:
                rotation_op = rotation_ops[0]
            else:
                rotation_op = xformable.AddRotateXYZOp()

            # Calculate view direction and rotation
            view_dir = (self.camera_target - camera_pos).GetNormalized()
            pitch = math.degrees(math.asin(-view_dir[2]))
            yaw = math.degrees(math.atan2(view_dir[1], view_dir[0]))
            rotation_op.Set(Gf.Vec3f(pitch, 0, yaw - 90))

        except Exception as e:
            camera_logger.error(f"Camera update failed: {e}", suppress=True)

    def get_state(self) -> dict:
        """
        Get current camera state

        Returns:
            Dictionary with camera parameters
        """
        return {
            "distance": self.camera_distance,
            "azimuth": self.camera_azimuth,
            "elevation": self.camera_elevation,
            "target": {
                "x": self.camera_target[0],
                "y": self.camera_target[1],
                "z": self.camera_target[2]
            },
            "locked": self.use_custom_camera
        }

    def set_state(self, state: dict):
        """
        Set camera state from dictionary

        Args:
            state: Dictionary with camera parameters
        """
        if "distance" in state:
            self.camera_distance = state["distance"]
        if "azimuth" in state:
            self.camera_azimuth = state["azimuth"]
        if "elevation" in state:
            self.camera_elevation = state["elevation"]
        if "target" in state:
            t = state["target"]
            self.camera_target = Gf.Vec3d(t.get("x", 0), t.get("y", 0), t.get("z", 0))
        if "locked" in state:
            self.use_custom_camera = state["locked"]

        self._update_camera()
        camera_logger.info(f"Camera state updated: {state}")
