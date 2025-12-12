"""
Video Track Module
Extracted from isaac_webrtc_server.py
Handles video frame capture and streaming for WebRTC
"""

import asyncio
import time
import fractions
import numpy as np
from typing import Optional
import carb
import omni.kit.viewport.utility as vp_util

try:
    from aiortc import VideoStreamTrack
    from av import VideoFrame
    HAS_WEBRTC = True
except ImportError:
    HAS_WEBRTC = False
    VideoStreamTrack = object  # Fallback for when aiortc is not available

try:
    import omni.replicator.core as rep
    HAS_REPLICATOR = True
except ImportError:
    HAS_REPLICATOR = False

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    FRAME_CAPTURE_TIMEOUT
)
from utils.logging_helper import video_logger
from utils.frame_validator import FrameValidator
from utils.async_helper import safe_set_event


class CaptureDelegate:
    """
    Capture delegate class - implements Capture interface for schedule_capture
    Handles frame capture callbacks from Isaac Sim viewport
    """

    def __init__(self, video_track):
        """
        Initialize capture delegate

        Args:
            video_track: Reference to the IsaacSimVideoTrack instance
        """
        self.video_track = video_track
        self._capture_error_logged = False
        self._texture_read_error_logged = False

    def capture(self, all_aovs, frame_info, texture, result_handle):
        """
        Capture callback - called when frame rendering is complete

        Args:
            all_aovs: All AOV (Arbitrary Output Variables)
            frame_info: Frame information
            texture: Hydra texture object
            result_handle: Result handle
        """
        try:
            # Method 1: Get LDR color texture from all_aovs
            if 'LdrColor' in all_aovs:
                aov_data = all_aovs['LdrColor']
                if 'texture' in aov_data:
                    texture_info = aov_data['texture']

                    # Get resolution
                    resolution = texture_info.get('resolution')
                    if resolution:
                        width, height = resolution.x, resolution.y
                    else:
                        width, height = frame_info.get('resolution', (VIDEO_WIDTH, VIDEO_HEIGHT))

                    # Get RpResource
                    rp_resource = texture_info.get('rp_resource')
                    if rp_resource:
                        data = self._read_rp_resource(rp_resource, width, height)
                        if data is not None:
                            self.video_track.latest_frame = data
                            safe_set_event(
                                self.video_track.capture_event,
                                logger_name="CaptureDelegate"
                            )
                            return

            # Method 2: Get directly from texture object
            if texture is not None:
                try:
                    # Get resolution
                    if hasattr(texture, 'get_height') and hasattr(texture, 'get_width'):
                        height = texture.get_height()
                        width = texture.get_width()
                    else:
                        width, height = frame_info.get('resolution', (VIDEO_WIDTH, VIDEO_HEIGHT))

                    # Try to get drawable LDR resource
                    if hasattr(texture, 'get_drawable_ldr_resource'):
                        resource = texture.get_drawable_ldr_resource()
                        if resource:
                            data = self._read_rp_resource(resource, width, height)
                            if data is not None:
                                self.video_track.latest_frame = data
                                safe_set_event(
                                    self.video_track.capture_event,
                                    logger_name="CaptureDelegate"
                                )
                                return

                    # Fallback: Try get_drawable_resource
                    if hasattr(texture, 'get_drawable_resource'):
                        resource = texture.get_drawable_resource()
                        if resource:
                            data = self._read_rp_resource(resource, width, height)
                            if data is not None:
                                self.video_track.latest_frame = data
                                safe_set_event(
                                    self.video_track.capture_event,
                                    logger_name="CaptureDelegate"
                                )
                                return

                except Exception as e:
                    if not self._texture_read_error_logged:
                        video_logger.warn(f"Texture read method failed: {e}")
                        self._texture_read_error_logged = True

        except Exception as e:
            if not self._capture_error_logged:
                video_logger.error(f"Capture delegate error: {e}", exc_info=True)
                self._capture_error_logged = True

    def _read_rp_resource(self, resource, width: int, height: int) -> Optional[np.ndarray]:
        """
        Read image data from RpResource

        Args:
            resource: Hydra RpResource object
            width: Image width
            height: Image height

        Returns:
            Numpy array of image data or None if failed
        """
        try:
            if hasattr(resource, 'get_cpu_data'):
                data = resource.get_cpu_data()
                if data is not None and len(data) > 0:
                    # Convert to numpy array
                    img_array = np.frombuffer(data, dtype=np.uint8)
                    # Reshape to image (RGBA format typically)
                    if len(img_array) == width * height * 4:
                        img = img_array.reshape((height, width, 4))
                        return img[:, :, :3].copy()  # RGB only
                    elif len(img_array) == width * height * 3:
                        img = img_array.reshape((height, width, 3))
                        return img.copy()
        except Exception as e:
            video_logger.warn(f"RpResource read failed: {e}", suppress=True)

        return None


class IsaacSimVideoTrack(VideoStreamTrack):
    """
    Isaac Sim video track - captures frames from Isaac Sim and encodes as video stream
    Uses Replicator API for efficient frame capture
    """

    def __init__(
        self,
        width: int = VIDEO_WIDTH,
        height: int = VIDEO_HEIGHT,
        fps: int = VIDEO_FPS
    ):
        """
        Initialize video track

        Args:
            width: Video width (must be even number)
            height: Video height (must be even number)
            fps: Video frame rate
        """
        super().__init__()

        # Force dimensions to be even (required by VPX/H264 encoder)
        self.width = width - (width % 2)
        self.height = height - (height % 2)
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.last_frame_time = 0
        self.frame_count = 0

        # Frame storage
        self.latest_frame = None
        self.capture_event = asyncio.Event()

        # Create capture delegate (fallback method)
        self.capture_delegate = CaptureDelegate(self)

        # Frame validator
        self.frame_validator = FrameValidator(self.width, self.height)

        # Use Replicator for frame capture (new method)
        self.use_replicator = HAS_REPLICATOR
        self.render_product = None
        self.rgb_annotator = None

        # Error tracking
        self._frame_error_count = 0
        self._max_error_log = 5
        self._capture_success_logged = False
        self._replicator_error_logged = False
        self._timeout_warning_count = 0

        if self.use_replicator:
            try:
                # Get current camera
                viewport = vp_util.get_active_viewport()
                camera_path = viewport.get_active_camera()

                # Create render product (using even dimensions)
                self.render_product = rep.create.render_product(
                    camera_path,
                    (self.width, self.height)
                )

                # Create RGB annotator
                self.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
                self.rgb_annotator.attach([self.render_product])

                video_logger.info(
                    f"Video track initialized with Replicator: "
                    f"{self.width}x{self.height}@{fps}fps"
                )
            except Exception as e:
                video_logger.error(f"Replicator init failed: {e}")
                self.use_replicator = False
                video_logger.info(
                    f"Video track initialized (fallback): "
                    f"{self.width}x{self.height}@{fps}fps"
                )
        else:
            video_logger.info(
                f"Video track initialized: {self.width}x{self.height}@{fps}fps"
            )

    async def recv(self):
        """
        Receive next frame - aiortc automatically calls this method
        Returns properly validated VideoFrame
        """
        # Control frame rate
        current_time = time.time()
        elapsed = current_time - self.last_frame_time

        if elapsed < self.frame_interval:
            await asyncio.sleep(self.frame_interval - elapsed)

        self.last_frame_time = time.time()
        self.frame_count += 1

        # Capture frame from Isaac Sim (async)
        frame_array = await self._capture_isaac_frame_async()

        if frame_array is None:
            frame_array = self.frame_validator.generate_test_pattern()

        # Validate and fix frame data using FrameValidator
        try:
            frame_array = self.frame_validator.validate_and_fix(frame_array)

            if frame_array is None:
                raise ValueError("Frame validation failed")

            # Debug: Log first frame details
            if not hasattr(self, '_first_frame_logged'):
                video_logger.info(
                    f"First frame details: "
                    f"shape={frame_array.shape}, "
                    f"dtype={frame_array.dtype}, "
                    f"range=[{frame_array.min()}, {frame_array.max()}], "
                    f"mean={frame_array.mean():.2f}, "
                    f"contiguous={frame_array.flags['C_CONTIGUOUS']}"
                )
                self._first_frame_logged = True

            # Convert to VideoFrame
            frame = VideoFrame.from_ndarray(frame_array, format="rgb24")
            frame.pts = self.frame_count
            frame.time_base = fractions.Fraction(1, self.fps)

            return frame

        except Exception as e:
            self._frame_error_count += 1

            if self._frame_error_count <= self._max_error_log:
                video_logger.error(
                    f"VideoFrame creation failed ({self._frame_error_count}): {e}",
                    exc_info=True
                )

            # Return safe fallback frame
            test_frame = self.frame_validator.generate_blank_frame()
            frame = VideoFrame.from_ndarray(test_frame, format="rgb24")
            frame.pts = self.frame_count
            frame.time_base = fractions.Fraction(1, self.fps)
            return frame

    async def _capture_isaac_frame_async(self) -> Optional[np.ndarray]:
        """
        Capture frame from Isaac Sim viewport - uses Replicator API

        Returns:
            Numpy array of frame data or None if capture failed
        """
        try:
            if self.use_replicator and self.rgb_annotator:
                # Use Replicator method (recommended)
                try:
                    # Wait for one frame to render
                    await rep.orchestrator.step_async()

                    # Get RGB data
                    data = self.rgb_annotator.get_data()

                    if data is not None and isinstance(data, np.ndarray):
                        # Validate data
                        if data.size == 0:
                            video_logger.warn("Replicator returned empty data", suppress=True)
                            return None

                        # Convert RGBA to RGB if needed
                        if len(data.shape) == 3 and data.shape[2] == 4:
                            rgb_data = data[:, :, :3]
                        elif len(data.shape) == 3 and data.shape[2] == 3:
                            rgb_data = data
                        else:
                            video_logger.warn(
                                f"Unexpected data shape: {data.shape}",
                                suppress=True
                            )
                            return None

                        # Handle different data types
                        if rgb_data.dtype in (np.float32, np.float64):
                            # Check for NaN and Inf
                            if np.isnan(rgb_data).any() or np.isinf(rgb_data).any():
                                video_logger.warn(
                                    "Replicator data contains NaN/Inf",
                                    suppress=True
                                )
                                rgb_data = np.nan_to_num(
                                    rgb_data,
                                    nan=0.0,
                                    posinf=1.0,
                                    neginf=0.0
                                )

                            # Replicator returns float32 [0, 1] range, scale to [0, 255]
                            frame = (rgb_data * 255).clip(0, 255).astype(np.uint8)
                        else:
                            # If already integer type, convert directly
                            frame = rgb_data.astype(np.uint8)

                        # Log success (only once)
                        if not self._capture_success_logged:
                            video_logger.info("Replicator capture working!")
                            self._capture_success_logged = True

                        return self._resize_frame(frame)

                except Exception as e:
                    if not self._replicator_error_logged:
                        video_logger.error(f"Replicator capture error: {e}", exc_info=True)
                        self._replicator_error_logged = True
                    # Fallback to old method
                    self.use_replicator = False

            # Fallback method: use schedule_capture
            viewport = vp_util.get_active_viewport()
            if not viewport:
                return None

            # Use schedule_capture with Capture delegate
            self.capture_event.clear()
            viewport.schedule_capture(self.capture_delegate)

            # Wait for capture to complete
            try:
                await asyncio.wait_for(
                    self.capture_event.wait(),
                    timeout=FRAME_CAPTURE_TIMEOUT
                )
                if self.latest_frame is not None:
                    return self._resize_frame(self.latest_frame)
            except asyncio.TimeoutError:
                # Timeout, log warning
                self._timeout_warning_count += 1

                # Only log first few warnings
                if self._timeout_warning_count <= 3:
                    video_logger.warn(
                        f"Frame capture timeout (count: {self._timeout_warning_count})"
                    )

                return None

        except Exception as e:
            video_logger.error(f"Frame capture error: {e}", suppress=True, exc_info=True)
            return None

    def _resize_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Resize frame to target resolution (ensure even dimensions)

        Args:
            frame: Input frame

        Returns:
            Resized frame
        """
        # Ensure input is uint8 format
        if frame.dtype != np.uint8:
            if frame.dtype in (np.float32, np.float64):
                frame = (frame * 255).clip(0, 255).astype(np.uint8)
            else:
                frame = frame.astype(np.uint8)

        # Check if resize is needed
        if frame.shape[0] != self.height or frame.shape[1] != self.width:
            try:
                from PIL import Image
                img = Image.fromarray(frame)
                img = img.resize((self.width, self.height), Image.BILINEAR)
                return np.array(img)
            except Exception as e:
                video_logger.warn(f"Resize failed: {e}", suppress=True)
                return self.frame_validator.generate_blank_frame()

        return frame

    def stop(self):
        """Stop the video track and cleanup resources"""
        try:
            if self.rgb_annotator:
                self.rgb_annotator.detach()
            if self.render_product:
                # Cleanup render product if needed
                pass
            video_logger.info("Video track stopped")
        except Exception as e:
            video_logger.error(f"Error stopping video track: {e}")
