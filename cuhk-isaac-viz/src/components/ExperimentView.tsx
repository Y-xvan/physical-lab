import React, { useEffect, useState, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import {
  ArrowLeft, Activity, RotateCcw
} from 'lucide-react';
import { isaacService, type SimulationState } from '../services/isaacService';
import { ConnectionStatus, type TelemetryData, type ExperimentConfig } from '../types';
import UltraFastIsaacViewer from './UltraFastIsaacViewer';
import WebRTCIsaacViewer from './WebRTCIsaacViewer';

interface ExperimentViewProps {
  config: ExperimentConfig;
  onBack: () => void;
}

const ExperimentView: React.FC<ExperimentViewProps> = ({ config, onBack }) => {
  const [status, setStatus] = useState<ConnectionStatus>(ConnectionStatus.DISCONNECTED);
  const [dataHistory, setDataHistory] = useState<TelemetryData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadingProgress, setLoadingProgress] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // 仿真状态
  const [simState, setSimState] = useState<SimulationState>({
    running: false,
    paused: false,
    time: 0,
    step: 0
  });

  // ========== 仿真控制 ==========

  const handleResetSimulation = useCallback(() => {
    isaacService.resetSimulation();
  }, []);

  // ========== 控制项状态 ==========
  const [controlValues, setControlValues] = useState<Record<string, number>>({});

  // ========== 控制项处理 ==========

  const handleControlChange = useCallback((controlId: string, value: number | boolean) => {
    // 更新控制值状态（用于显示）
    if (typeof value === 'number') {
      setControlValues(prev => ({ ...prev, [controlId]: value }));
    }

    const control = config.controls.find(c => c.id === controlId);
    if (control) {
      // 特殊处理仿真控制命令
      if (control.command === 'start_simulation') {
        isaacService.startSimulation();
      } else if (control.command === 'reset_env') {
        isaacService.resetSimulation();
      } else {
        isaacService.sendCommand(control.command, value);
      }
    }
  }, [config.controls]);

  // ========== 初始化 ==========

  useEffect(() => {
    console.log('Entering experiment:', {
      id: config.id,
      experimentNumber: config.experimentNumber,
      title: config.title,
      note: 'Using enterExperiment (no USD reload, only camera switch and physics reset)'
    });

    // 开始加载
    setIsLoading(true);
    setLoadingProgress(10);

    // 初始化实验（不重新加载USD，只切换相机和reset物理状态）
    const initExperiment = async () => {
      try {
        // 确保WebSocket已连接（通常已经在LevelSelect中连接了）
        if (!isaacService.isConnected()) {
          console.warn('⚠️ WebSocket not connected, reconnecting...');
          const connected = await isaacService.connect(config.id);
          if (!connected) {
            setStatus(ConnectionStatus.ERROR);
            setLoadingProgress(0);
            setErrorMessage('Failed to connect to Isaac Sim server. Please ensure the server is running on ws://10.20.5.3:30000');
            return;
          }
        }

        setStatus(ConnectionStatus.CONNECTED);
        setLoadingProgress(40);

        // 进入实验（只切换相机和reset物理状态，不重新加载USD）
        console.log('🚀 Entering experiment (switching camera and resetting physics)...');
        const entered = await isaacService.enterExperiment(config.experimentNumber);

        if (entered) {
          console.log('✅ Experiment entered with camera config');
          setLoadingProgress(80);

          // 加载完成后，立即查询仿真状态
          setTimeout(() => {
            isaacService.requestSimulationState();
            setLoadingProgress(100);

            // 延迟一下再隐藏加载界面，让用户看到100%
            setTimeout(() => {
              setIsLoading(false);
            }, 300);
          }, 500);
        } else {
          console.warn('⚠️ Failed to enter experiment');
          setLoadingProgress(0);
          setErrorMessage('Failed to enter experiment. Please check the server status.');
        }
      } catch (error) {
        console.error('❌ Experiment initialization error:', error);
        setStatus(ConnectionStatus.ERROR);
        setLoadingProgress(0);
        setErrorMessage('An error occurred while entering the experiment.');
      }
    };

    // 执行初始化
    initExperiment();

    // 订阅遥测数据
    const unsubscribeTelemetry = isaacService.onTelemetry((data) => {
      setDataHistory(prev => {
        const newData = [...prev, data];
        if (newData.length > 60) return newData.slice(newData.length - 60);
        return newData;
      });
    });

    // 订阅仿真状态
    const unsubscribeSimState = isaacService.onSimulationState((state) => {
      setSimState(state);
    });

    // 定期轮询状态（作为备用，后端也会主动推送）
    const statePollingInterval = setInterval(() => {
      if (isaacService.isConnected()) {
        isaacService.requestSimulationState();
      }
    }, 3000); // 每3秒轮询一次

    return () => {
      unsubscribeTelemetry();
      unsubscribeSimState();
      clearInterval(statePollingInterval);
      // 不断开连接，保持WebSocket在线
      console.log('🔄 ExperimentView unmounting, keeping connection alive');
    };
  }, [config.id, config.experimentNumber]);

  const currentData = dataHistory.length > 0 ? dataHistory[dataHistory.length - 1] : null;
  const isConnected = status === ConnectionStatus.CONNECTED;

  // 加载界面
  if (isLoading) {
    return (
      <div className="h-screen w-full bg-gradient-to-br from-white via-blue-50/30 to-purple-50/30 text-gray-900 flex flex-col items-center justify-center font-sans overflow-hidden relative" style={{ fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
        {/* 背景装饰 */}
        <div className="fixed top-0 right-0 w-[400px] h-[400px] bg-gradient-to-br from-blue-100/40 to-purple-100/40 rounded-full blur-[120px] pointer-events-none" />
        <div className="fixed bottom-0 left-0 w-[350px] h-[350px] bg-gradient-to-tr from-cyan-100/30 to-pink-100/30 rounded-full blur-[120px] pointer-events-none" />

        {/* 返回按钮 */}
        <button
          onClick={onBack}
          className="absolute top-6 left-6 text-gray-600 hover:text-blue-600 transition-colors flex items-center gap-2 text-sm font-mono border-2 border-gray-200 px-3 py-1.5 rounded-lg hover:bg-white/80 hover:border-blue-300 shadow-sm"
        >
          <ArrowLeft size={14} /> BACK
        </button>

        {/* 加载内容 */}
        <div className="flex flex-col items-center gap-8 z-10">
          {/* 动画图标 */}
          <div className="relative">
            <div className="absolute inset-0 blur-2xl opacity-40 bg-gradient-to-r from-blue-400 to-purple-400 rounded-full animate-pulse" />
            <div className="relative p-6 bg-white/80 backdrop-blur-sm rounded-2xl border-2 border-gray-200 shadow-lg">
              <Activity size={48} className="text-blue-600 animate-pulse" />
            </div>
          </div>

          {/* 标题 */}
          <div className="text-center space-y-2">
            <h2 className="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-gray-700 via-blue-600 to-purple-600">
              {config.title}
            </h2>
            <p className="text-sm text-gray-500 font-mono">Initializing experiment...</p>
          </div>

          {/* 进度条 */}
          {!errorMessage && (
            <div className="w-80 space-y-2">
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden shadow-inner">
                <div
                  className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all duration-500 ease-out"
                  style={{ width: `${loadingProgress}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-gray-500 font-mono">
                <span>Connecting to server...</span>
                <span>{loadingProgress}%</span>
              </div>
            </div>
          )}

          {/* 加载状态指示器 */}
          {!errorMessage && (
            <div className="flex gap-2">
              <div className={`w-2 h-2 rounded-full transition-all duration-300 ${loadingProgress >= 10 ? 'bg-blue-500 scale-100' : 'bg-gray-300 scale-75'}`} />
              <div className={`w-2 h-2 rounded-full transition-all duration-300 ${loadingProgress >= 40 ? 'bg-blue-500 scale-100' : 'bg-gray-300 scale-75'}`} />
              <div className={`w-2 h-2 rounded-full transition-all duration-300 ${loadingProgress >= 80 ? 'bg-blue-500 scale-100' : 'bg-gray-300 scale-75'}`} />
              <div className={`w-2 h-2 rounded-full transition-all duration-300 ${loadingProgress >= 100 ? 'bg-blue-500 scale-100' : 'bg-gray-300 scale-75'}`} />
            </div>
          )}

          {/* 错误信息 */}
          {errorMessage && (
            <div className="w-96 space-y-4">
              <div className="p-4 bg-red-50 border-2 border-red-200 rounded-xl">
                <p className="text-sm text-red-700 font-mono text-center leading-relaxed">
                  {errorMessage}
                </p>
              </div>
              <button
                onClick={() => window.location.reload()}
                className="w-full px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-mono font-semibold rounded-lg transition-colors shadow-md hover:shadow-lg"
              >
                Retry Connection
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen w-full bg-gradient-to-br from-gray-50 via-blue-50 to-purple-50 text-gray-900 flex flex-col font-sans overflow-hidden" style={{ fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      {/* Top Navigation */}
      <div className="h-14 border-b border-gray-200 flex items-center justify-between px-6 bg-white/80 backdrop-blur-sm z-20 shadow-sm">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="text-gray-700 hover:text-blue-600 transition-colors flex items-center gap-2 text-sm font-mono border-2 border-gray-300 px-3 py-1.5 rounded-lg hover:bg-gray-100 hover:border-blue-400 shadow-sm">
            <ArrowLeft size={14} /> BACK
          </button>
          <div className="h-6 w-px bg-gray-300 mx-2"></div>
          <div>
            <h2 className="font-bold text-sm tracking-widest text-blue-600 uppercase">{config.title}</h2>
            <div className="text-[10px] text-gray-500 font-mono">{config.usdPath}</div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* ========== 仿真控制按钮 ========== */}
          <div className="flex items-center gap-1 border-2 border-gray-300 rounded-lg p-1 shadow-sm bg-white">
            {/* 重置 */}
            <button
              onClick={handleResetSimulation}
              className="p-2 rounded hover:bg-purple-100 text-gray-700 hover:text-purple-600 transition-colors flex items-center gap-2"
              title="Reset Simulation"
            >
              <RotateCcw size={14} />
              <span className="text-xs font-mono font-semibold">RESET</span>
            </button>
          </div>

          <div className="h-6 w-px bg-gray-300"></div>

          {/* 连接状态 */}
          <div className={`flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded-full border-2 shadow-sm ${
            isConnected
              ? 'border-green-500/50 text-green-700 bg-green-50'
              : 'border-red-500/50 text-red-700 bg-red-50'
          }`}>
            <div className={`w-2 h-2 rounded-full ${
              isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'
            }`}></div>
            <span className="font-semibold">{isConnected ? 'CONNECTED' : 'DISCONNECTED'}</span>
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden relative">
        {/* Left: 3D Viewport with Ultra Fast Streaming */}
        <div className="flex-[2] relative bg-gray-100 border-r border-gray-200 flex flex-col shadow-inner">
          <div className="absolute inset-0 bg-[linear-gradient(rgba(100,116,139,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(100,116,139,0.1)_1px,transparent_1px)] bg-[size:40px_40px] opacity-30 pointer-events-none"></div>

          {/* ========== WebRTC VIDEO STREAM ========== */}
          <div className="flex-1 relative z-10">
            {/* 使用WebRTC实现高性能视频流 */}
            <WebRTCIsaacViewer
              serverUrl="http://10.20.5.3:8080"
              usdPath={config.usdPath}
              className="w-full h-full"
            />

            {/* 如果想使用旧的JPEG流，取消注释下面的代码并注释掉上面的WebRTC组件 */}
            {/* <UltraFastIsaacViewer
              wsUrl={isaacService.getBackendUrl()}
              usdPath={config.usdPath}
              initialWidth={640}
              initialHeight={480}
              initialQuality={60}
              className="w-full h-full"
            /> */}
          </div>
        </div>

        {/* Right: Data Telemetry & Controls */}
        <div className="flex-1 bg-white/90 backdrop-blur-sm border-l border-gray-200 flex flex-col min-w-[350px] shadow-lg overflow-y-auto">
          <div className="grid grid-cols-2 gap-px bg-gray-200 border-b border-gray-200">
            {config.chartConfig.map((chart) => (
              <div key={chart.key} className="bg-white p-4">
                <div className="text-gray-600 text-[10px] font-mono mb-1 uppercase tracking-wider flex items-center gap-1 font-semibold">
                  <div className="w-2 h-2 rounded-full shadow-sm" style={{ backgroundColor: chart.color }}></div>
                  {chart.label}
                </div>
                <div className="text-xl font-mono text-gray-900 font-bold">
                  {currentData ? (currentData[chart.key]?.toFixed(2) ?? '--') : '--'}
                </div>
              </div>
            ))}
          </div>

          {/* Control Panel */}
          {config.controls && config.controls.length > 0 && (
            <div className="border-b border-gray-200 p-4 bg-gray-50">
              <div className="text-gray-700 text-xs font-bold mb-3 uppercase tracking-wider">Controls</div>
              <div className="space-y-3">
                {config.controls.map((control) => {
                  if (control.type === 'slider') {
                    const currentValue = controlValues[control.id] ?? (control.defaultValue as number);
                    return (
                      <div key={control.id} className="space-y-1">
                        <div className="flex items-center justify-between">
                          <label className="text-gray-700 text-xs font-mono font-semibold">{control.label}</label>
                          <span className="text-blue-600 text-xs font-mono font-bold bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                            {currentValue.toFixed(1)}
                          </span>
                        </div>
                        <input
                          type="range"
                          min={control.min}
                          max={control.max}
                          step={control.step}
                          defaultValue={control.defaultValue as number}
                          onChange={(e) => handleControlChange(control.id, parseFloat(e.target.value))}
                          className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer slider accent-blue-600"
                        />
                      </div>
                    );
                  } else if (control.type === 'button') {
                    return (
                      <button
                        key={control.id}
                        onClick={() => handleControlChange(control.id, true)}
                        className="w-full px-3 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-mono font-semibold rounded-lg transition-colors shadow-md hover:shadow-lg"
                      >
                        {control.label}
                      </button>
                    );
                  } else if (control.type === 'toggle') {
                    return (
                      <div key={control.id} className="flex items-center justify-between">
                        <label className="text-gray-700 text-xs font-mono font-semibold">{control.label}</label>
                        <input
                          type="checkbox"
                          defaultChecked={control.defaultValue as boolean}
                          onChange={(e) => handleControlChange(control.id, e.target.checked)}
                          className="w-4 h-4"
                        />
                      </div>
                    );
                  }
                  return null;
                })}
              </div>
            </div>
          )}

          <div className="flex-1 p-2 flex flex-col min-h-0 bg-white/50">
            <div className="flex items-center gap-2 text-gray-700 text-xs font-bold p-2 uppercase tracking-wider">
              <Activity size={14} /> LIVE TELEMETRY
            </div>
            <div className="flex-1 w-full min-h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={dataHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#d1d5db" vertical={false} />
                  <XAxis dataKey="timestamp" hide />
                  <YAxis yAxisId="left" stroke="#6b7280" fontSize={10} tickFormatter={(val) => val.toFixed(1)} />
                  <YAxis yAxisId="right" orientation="right" stroke="#6b7280" fontSize={10} tickFormatter={(val) => val.toFixed(1)} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#ffffff', border: '2px solid #e5e7eb', fontSize: '12px', borderRadius: '8px', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}
                    labelStyle={{ display: 'none' }}
                    itemStyle={{ color: '#374151' }}
                  />
                  {config.chartConfig.map(chart => (
                    <Line
                      key={chart.key}
                      yAxisId={chart.yAxisId}
                      type="monotone"
                      dataKey={chart.key}
                      stroke={chart.color}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExperimentView;
