"""
项目配置文件
集中管理所有配置项，避免硬编码
"""
import os

# ============================================================
# 路径配置
# ============================================================

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Camera配置脚本目录
CAMERA_SCRIPT_DIR = os.path.join(PROJECT_ROOT, "camera")
PHY_USD_PATH = "/home/zhiren/IsaaclabAssets/experiment/exp.usd"
# USD场景文件路径（优先使用环境变量）
DEFAULT_USD_PATH = os.getenv(
    "PHY_USD_PATH",
    os.path.join(PROJECT_ROOT, "assets", "exp.usd")
)

# 日志目录
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


# ============================================================
# 服务器配置
# ============================================================

# HTTP服务器
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080

# WebSocket服务器
WS_HOST = "0.0.0.0"
WS_PORT = 30000  # 确保 extension.py 已删除，否则会冲突


# ============================================================
# 视频配置
# ============================================================

# 视频分辨率（必须是偶数）
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720

# 视频帧率
VIDEO_FPS = 30


# ============================================================
# 监控配置
# ============================================================

SIMULATION_CHECK_INTERVAL = 0.1
STATE_BROADCAST_INTERVAL = 2.0
TELEMETRY_BROADCAST_INTERVAL = 0.333
DEBOUNCE_WINDOW = 0.5

# ============================================================
# 实验1配置
# ============================================================

EXP1_DEFAULT_DISK_MASS = 1.0
EXP1_DEFAULT_RING_MASS = 1.0
EXP1_DEFAULT_DISK_RADIUS = 0.5
EXP1_DEFAULT_RING_RADIUS = 0.5
EXP1_DEFAULT_INITIAL_VELOCITY = 0.0

# ============================================================
# 性能配置
# ============================================================

FRAME_CAPTURE_TIMEOUT = 0.2
REPLICATOR_INIT_MAX_RETRIES = 3
REPLICATOR_INIT_RETRY_DELAY = 1.0