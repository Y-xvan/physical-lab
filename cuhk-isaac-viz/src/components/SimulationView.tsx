// isaacService.ts
import { ConnectionStatus, type TelemetryData } from '../types';

class IsaacService {
  private status: ConnectionStatus = ConnectionStatus.DISCONNECTED;
  private subscribers: ((data: TelemetryData) => void)[] = [];
  private sceneInfoSubscribers: ((info: any) => void)[] = [];
  
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

  public disconnect() {
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

  private notifySubscribers(data: TelemetryData) {
    this.subscribers.forEach(cb => cb(data));
  }

  private notifySceneInfoSubscribers(info: any) {
    this.sceneInfoSubscribers.forEach(cb => cb(info));
  }

  // --- USD 场景操作方法 ---
  public async loadUSDScene(usdPath: string): Promise<boolean> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket not connected');
      return false;
    }

    return new Promise((resolve) => {
      const command = {
        command: 'load_usd',
        path: usdPath
      };
      
      console.log('Sending load USD command:', command);
      if (this.ws) {
        this.ws.send(JSON.stringify(command));
      } else {
      // 处理ws为null的情况，比如打印错误日志或者尝试重新连接等
        console.error('WebSocket is not connected.');
      }

      
      // 设置超时，假设成功
      setTimeout(() => {
        resolve(true);
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
      this.sendMessage('START_SIMULATION', { 
        command: 'start_simulation'
      });
    }
  }

  public async pauseSimulation(): Promise<void> {
    console.log('Pausing simulation...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.sendMessage('PAUSE_SIMULATION', {
        command: 'pause_simulation' 
      });
    }
  }

  public async resetSimulation(): Promise<void> {
    console.log('Resetting simulation...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.sendMessage('RESET_SIMULATION', {
        command: 'reset_simulation'
      });
    }
  }

  public async stopSimulation(): Promise<void> {
    console.log('Stopping simulation...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.sendMessage('STOP_SIMULATION', {
        command: 'stop_simulation'
      });
    }
    this.disconnect();
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
      this.sendMessage(command, payload);
    }
  }

  private sendMessage(type: string, data?: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }));
    }
  }

  public getStatus(): ConnectionStatus {
    return this.status;
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