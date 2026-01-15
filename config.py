
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
HOST_IP = "10.20.5.3"  

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_HOST = "0.0.0.0"
WS_PORT = 30000

# ============================================================
# 视频配置
# ============================================================
VIDEO_WIDTH = 2560
VIDEO_HEIGHT = 1440
VIDEO_FPS = 30

# ============================================================
# 监控与遥测配置 (关键修改)
# ============================================================
SIMULATION_CHECK_INTERVAL = 0.1
STATE_BROADCAST_INTERVAL = 2.0

# 修复：提高遥测频率到 0.01 (100Hz)，确保高速采样，减少波动
TELEMETRY_BROADCAST_INTERVAL = 0.01 

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
# 实验2默认参数
# ============================================================
EXP2_GROUP_PATH = "/World/exp2/Group_01"  # 整个摆的组，用于设置初始角度
EXP2_CYLINDER_PATH = "/World/exp2/Group_01/Cylinder"  # 旋转杆，用于读取角度
EXP2_REVOLUTE_JOINT_PATH = "/World/exp2/Group_01/RevoluteJoint"  # 关节（仅用于路径引用，不修改其配置）
EXP2_MASS1_PATH = "/World/exp2/Group_01/Cylinder_01"
EXP2_MASS2_PATH = "/World/exp2/Group_01/Cylinder_02"
EXP2_DEFAULT_INITIAL_ANGLE = 90  # 度（默认90度，水平位置）
EXP2_DEFAULT_MASS1 = 1.0  # kg
EXP2_DEFAULT_MASS2 = 1.0  # kg

# ============================================================
# 性能配置
# ============================================================
FRAME_CAPTURE_TIMEOUT = 0.2
REPLICATOR_INIT_MAX_RETRIES = 3
REPLICATOR_INIT_RETRY_DELAY = 1.0