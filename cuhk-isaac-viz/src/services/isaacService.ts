// isaacService.ts
import { ConnectionStatus, type TelemetryData } from '../types';

// 仿真状态接口
export interface SimulationState {
  running: boolean;
  paused: boolean;
  time: number;
  step: number;
}

class IsaacService {
  private status: ConnectionStatus = ConnectionStatus.DISCONNECTED;
  private subscribers: ((data: TelemetryData) => void)[] = [];
  private sceneInfoSubscribers: ((info: any) => void)[] = [];
  private simStateSubscribers: ((state: SimulationState) => void)[] = [];

  // 真实连接相关
  public ws: WebSocket | null = null; // 添加 public 修饰符
  private useMock: boolean = false;
  private backendUrl: string = 'ws://10.20.5.3:30000';

  // Mock 状态
  private activeExperimentId: string | null = null;
  private simulationInterval: any = null;
  private mockTime: number = 0;

  constructor() {}

  public connect(experimentId: string): Promise<boolean> {
    console.log(`Initializing Isaac Lab for: ${experimentId}`);
    this.activeExperimentId = experimentId;
    this.status = ConnectionStatus.CONNECTING;

    if (this.useMock) {
      return this.connectMock();
    } else {
      return this.connectReal(experimentId);
    }
  }

  // --- 真实连接逻辑 ---
  private connectReal(experimentId: string): Promise<boolean> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.backendUrl);

        this.ws.onopen = () => {
          console.log('Connected to Isaac Sim WebSocket');
          this.status = ConnectionStatus.CONNECTED;

          // 发送初始化指令
          this.sendMessage('INIT', {
            experimentId,
            type: 'connection_init'
          });

          resolve(true);
        };

        this.ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            console.log('Received message:', payload);

            // 处理不同类型的消息
            if (payload.type === 'telemetry') {
              this.notifySubscribers(payload.data);
            } else if (payload.type === 'simulation_state') {
              // 处理仿真状态更新
              this.notifySimStateSubscribers(payload);
            } else if (payload.type === 'scene_info' || payload.type === 'scene_status') {
              this.notifySceneInfoSubscribers(payload.data);
            } else if (payload.type === 'connected') {
              console.log('Server connection confirmed:', payload.message);
            } else if (payload.type === 'command_result') {
              console.log('Command result:', payload);
            } else if (payload.type === 'error') {
              console.error('Server error:', payload.message);
            }
          } catch (e) {
            console.error('Failed to parse message', e);
          }
        };

        this.ws.onclose = () => {
          this.status = ConnectionStatus.DISCONNECTED;
          console.log('Isaac Sim Disconnected');
        };

        this.ws.onerror = (err) => {
          console.error('Isaac Sim Connection Error', err);
          this.status = ConnectionStatus.ERROR;
          resolve(false);
        };

      } catch (error) {
        resolve(false);
      }
    });
  }

  // --- Mock 连接逻辑 ---
  private connectMock(): Promise<boolean> {
    return new Promise((resolve) => {
      setTimeout(() => {
        this.status = ConnectionStatus.CONNECTED;
        this.startMockDataStream();
        resolve(true);
      }, 800);
    });
  }

  /**
   * 断开WebSocket连接
   * @param force 是否强制断开（默认false，退出实验时保持连接）
   */
  public disconnect(force: boolean = false) {
    if (!force) {
      console.log('📌 Keeping WebSocket connection alive');
      return;  // 不断开连接，保持在线
    }

    console.log('🔌 Disconnecting from Isaac Sim...');
    this.status = ConnectionStatus.DISCONNECTED;
    if (this.simulationInterval) clearInterval(this.simulationInterval);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  public onTelemetry(callback: (data: TelemetryData) => void) {
    this.subscribers.push(callback);
    return () => {
      this.subscribers = this.subscribers.filter(cb => cb !== callback);
    };
  }

  public onSceneInfo(callback: (info: any) => void) {
    this.sceneInfoSubscribers.push(callback);
    return () => {
      this.sceneInfoSubscribers = this.sceneInfoSubscribers.filter(cb => cb !== callback);
    };
  }

  public onSimulationState(callback: (state: SimulationState) => void) {
    this.simStateSubscribers.push(callback);
    return () => {
      this.simStateSubscribers = this.simStateSubscribers.filter(cb => cb !== callback);
    };
  }

  private notifySubscribers(data: TelemetryData) {
    this.subscribers.forEach(cb => cb(data));
  }

  private notifySceneInfoSubscribers(info: any) {
    this.sceneInfoSubscribers.forEach(cb => cb(info));
  }

  private notifySimStateSubscribers(state: SimulationState) {
    this.simStateSubscribers.forEach(cb => cb(state));
  }

  // --- USD 场景操作方法 ---
  public async loadUSDScene(experimentNumber: string): Promise<boolean> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket not connected');
      return false;
    }

    return new Promise((resolve) => {
      // 新的消息格式：发送 experiment_id 而不是完整路径
      // 后端会自动加载统一的 exp.usd 文件，并根据 experiment_id 加载对应的相机配置
      const message = {
        type: 'load_usd',
        experiment_id: experimentNumber
      };

      console.log('Sending load USD command:', message);
      console.log(`  → Will load: /home/zhiren/Isaaclab_Assets/Experiment/exp.usd`);
      console.log(`  → Camera config: camera/usd${experimentNumber}.py`);

      if (this.ws) {
        this.ws.send(JSON.stringify(message));
      } else {
        // 处理ws为null的情况
        console.error('WebSocket is not connected.');
      }

      // 设置超时，假设成功
      setTimeout(() => {
        resolve(true);
      }, 2000);
    });
  }

  /**
   * 进入实验（不重新加载USD，只切换相机和reset物理状态）
   * 用于在实验选择界面已经加载了exp.usd后，进入特定实验
   * @param experimentNumber 实验编号 "1", "2", "3" 等
   */
  public async enterExperiment(experimentNumber: string): Promise<boolean> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket not connected');
      return false;
    }

    return new Promise((resolve) => {
      const message = {
        type: 'enter_experiment',
        experiment_id: experimentNumber
      };

      console.log('🚀 Entering experiment:', experimentNumber);
      console.log('  → Will switch camera to:', `camera/usd${experimentNumber}.py`);
      console.log('  → Will reset physics state');

      // 监听响应
      const responseHandler = (event: MessageEvent) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'experiment_entered' && payload.experiment_id === experimentNumber) {
            console.log('✅ Experiment entered successfully');
            this.ws?.removeEventListener('message', responseHandler);
            resolve(true);
          } else if (payload.type === 'error') {
            console.error('❌ Failed to enter experiment:', payload.message);
            this.ws?.removeEventListener('message', responseHandler);
            resolve(false);
          }
        } catch (e) {
          console.error('Failed to parse response', e);
        }
      };

      if (this.ws) {
        this.ws.addEventListener('message', responseHandler);

        // 发送消息
        this.ws.send(JSON.stringify(message));
      }

      // 超时处理
      setTimeout(() => {
        this.ws?.removeEventListener('message', responseHandler);
        resolve(true);  // 即使超时也返回true，让UI继续
      }, 2000);
    });
  }

  public async getSceneInfo(): Promise<any> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return null;
    }

    return new Promise((resolve) => {
      const command = {
        command: 'get_scene_info'
      };

      console.log('Sending get scene info command');
      if (this.ws) {
        this.ws.send(JSON.stringify(command));
      } else {
      // 处理ws为null的情况，比如打印错误日志或者尝试重新连接等
        console.error('WebSocket is not connected.');
      }
      // 简化处理，不等待实际响应
      setTimeout(() => {
        resolve({ stage: 'unknown', root_prims_count: 0 });
      }, 1000);
    });
  }

  // --- 模拟控制方法 ---
  public async startSimulation(): Promise<void> {
    console.log('Starting simulation...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // 发送正确的消息格式：{ type: "start_simulation" }
      this.ws.send(JSON.stringify({ type: 'start_simulation' }));
    }
  }

  public async pauseSimulation(): Promise<void> {
    console.log('Pausing simulation...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // 发送正确的消息格式：{ type: "pause_simulation" }
      this.ws.send(JSON.stringify({ type: 'pause_simulation' }));
    }
  }

  public async resetSimulation(): Promise<void> {
    console.log('Resetting simulation...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // 发送正确的消息格式：{ type: "reset" }
      this.ws.send(JSON.stringify({ type: 'reset' }));
    }
  }

  public async stopSimulation(): Promise<void> {
    console.log('Stopping simulation...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // 发送正确的消息格式：{ type: "stop_simulation" }
      this.ws.send(JSON.stringify({ type: 'stop_simulation' }));
    }
    // 不再自动断开连接，让调用者决定是否断开
  }

  // --- 向后兼容的旧方法 ---
  public setRunning(running: boolean): void {
    if (running) {
      this.startSimulation();
    } else {
      this.pauseSimulation();
    }
  }

  public resetExperiment(): void {
    this.resetSimulation();
  }

  public sendCommand(command: string, payload?: any) {
    console.log(`[CMD] ${command}`, payload);

    if (this.ws && this.status === ConnectionStatus.CONNECTED) {
      // 发送正确的消息格式
      // 如果 payload 存在，合并到消息中；否则只发送 type
      const message = payload ? { type: command, ...payload } : { type: command };
      this.ws.send(JSON.stringify(message));
    }
  }

  // 已废弃：不再使用，保留用于向后兼容
  private sendMessage(type: string, data?: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // 新格式：直接发送 { type: "xxx", ...其他字段 }
      const message = data ? { type, ...data } : { type };
      this.ws.send(JSON.stringify(message));
    }
  }

  public getStatus(): ConnectionStatus {
    return this.status;
  }

  public isConnected(): boolean {
    return this.status === ConnectionStatus.CONNECTED && this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  public getBackendUrl(): string {
    return this.backendUrl;
  }

  public requestSimulationState(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // 发送正确的消息格式：{ type: "get_simulation_state" }
      this.ws.send(JSON.stringify({ type: 'get_simulation_state' }));
    }
  }

  // --- Mock 数据生成器 ---
  private startMockDataStream() {
    this.mockTime = 0;
    this.simulationInterval = setInterval(() => {
      this.mockTime += 0.016;
      const t = this.mockTime;

      let data: TelemetryData = {
        timestamp: Date.now(),
        fps: 60 + Math.random() * 5,
      };

      switch (this.activeExperimentId) {
        case 'exp-01-cartpole':
          data.pole_angle = Math.sin(t) * 0.1 + (Math.random() - 0.5) * 0.02;
          data.cart_velocity = Math.cos(t) * 0.5;
          break;
        case 'exp-02-franka':
          data.end_effector_vel = Math.abs(Math.sin(t * 2));
          data.gripper_force = t % 5 > 2.5 ? 20 : 0;
          break;
        case 'exp-03-quadcopter':
          data.altitude = 5 + Math.sin(t * 0.5) * 2;
          data.battery = Math.max(0, 100 - t * 0.5);
          break;
        case 'exp-04-anymal':
          data.body_velocity = 0.5 + (Math.random() - 0.5) * 0.1;
          data.slip_ratio = Math.abs(Math.random() * 0.1);
          break;
        case 'exp-05-humanoid':
          data.com_height = 0.9 + Math.cos(t * 10) * 0.02;
          data.energy = 200 + Math.random() * 50;
          break;
        case 'exp-06-softbody':
          data.deformation = Math.abs(Math.sin(t * 5)) * 10;
          data.stress = data.deformation * 500;
          break;
        case 'exp-07-amr':
          data.lidar_points = 15000 + Math.random() * 1000;
          data.path_error = Math.abs(Math.sin(t * 0.1)) * 0.2;
          break;
        case 'exp-08-shadow':
          data.cube_rot_vel = 1.5 + Math.random() * 0.2;
          data.finger_contacts = Math.floor(3 + Math.random() * 2);
          break;
        default:
          data.value = Math.random();
      }

      this.notifySubscribers(data);
    }, 50);
  }
}

export const isaacService = new IsaacService();
