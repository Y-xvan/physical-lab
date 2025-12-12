

// 实验控制组件类型
export type ControlType = 'slider' | 'button' | 'toggle';

export interface ControlConfig {
  id: string;
  label: string;
  type: ControlType;
  min?: number; // 仅 Slider 用
  max?: number; // 仅 Slider 用
  step?: number; // 仅 Slider 用
  defaultValue?: number | boolean;
  command: string; // 发送给后端的指令名
}

// 图表配置
export interface ChartConfig {
  key: string; // 对应 TelemetryData 中的字段名
  color: string;
  label: string;
  yAxisId: 'left' | 'right';
}

// 核心实验配置接口
export interface ExperimentConfig {
  id: string;
  title: string;
  description: string;
  thumbnail: string;
  usdPath: string; // 统一的场景文件路径 (所有实验共用同一个 exp.usd)
  experimentNumber: string; // 实验编号 ("1", "2", ..., "8") - 用于加载对应的相机配置
  difficulty: 'Easy' | 'Medium' | 'Hard';
  isLocked: boolean;

  // 动态配置
  controls: ControlConfig[];
  chartConfig: ChartConfig[];
}

// 通用遥测数据 (允许任意键值对)
export interface TelemetryData {
  timestamp: number;
  fps: number;
  [key: string]: number; // 动态键值，例如 'velocity', 'altitude', 'joint_angle_0'
}

export enum ConnectionStatus {
  DISCONNECTED = 'disconnected',
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  ERROR = 'error'
}

let data: TelemetryData = {
  timestamp: Date.now(),
  fps: 60 + Math.random() * 5,
  pole_angle: 0,
  cart_velocity: 0,
  end_effector_vel: 0,
  gripper_force: 0,
  altitude: 0,
  battery: 100,
  body_velocity: 0,
  slip_ratio: 0,
  com_height: 0,
  energy: 0,
  deformation: 0,
  stress: 0,
  lidar_points: 0,
  path_error: 0,
  cube_rot_vel: 0,
  finger_contacts: 0,
  value: 0
};

export interface SceneInfo {
  stage?: string;
  root_prims_count?: number;
  root_prims?: string[];
  current_time?: number;
  error?: string;
}