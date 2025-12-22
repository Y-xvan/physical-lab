
"""
项目配置文件
集中管理所有配置项，避免硬编码
"""
import os

# ============================================================
# 路径配置
# ============================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CAMERA_SCRIPT_DIR = os.path.join(PROJECT_ROOT, "camera")

# 关键：定义实验 USD 中刚体的具体路径，防止代码中硬编码
# 如果你的 USD 结构不同，请在这里修改
EXP1_DISK_PATH = "/World/exp1/disk"
EXP1_RING_PATH = "/World/exp1/ring"

# USD场景文件路径
DEFAULT_USD_PATH = os.getenv(
    "PHY_USD_PATH",
    "/home/zhiren/Isaaclab_Assets/Experiment/exp.usd"
)


# 日志目录
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ============================================================
# 服务器配置
# ============================================================
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_HOST = "0.0.0.0"
WS_PORT = 30000

# ============================================================
# 视频配置
# ============================================================
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30

# ============================================================
# 监控与遥测配置 (关键修改)
# ============================================================
SIMULATION_CHECK_INTERVAL = 0.1
STATE_BROADCAST_INTERVAL = 2.0

# 修复：将遥测频率从 0.333 改为 0.05 (20Hz)，保证前端曲线平滑
TELEMETRY_BROADCAST_INTERVAL = 0.05 

DEBOUNCE_WINDOW = 0.5

# ============================================================
# 实验1默认参数
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