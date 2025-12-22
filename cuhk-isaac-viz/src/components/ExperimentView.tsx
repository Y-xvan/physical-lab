import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Brush } from 'recharts';
import {
  ArrowLeft, Activity
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

  // 保存的历史数据记录
  const [savedRuns, setSavedRuns] = useState<{id: number, data: TelemetryData[], label: string}[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null); // null = 显示实时数据
  const [runCounter, setRunCounter] = useState(1);

  // ========== 控制项状态 ==========
  // 初始化控制值为默认值
  const initialControlValues = useMemo(() => {
    const values: Record<string, number> = {};
    config.controls?.forEach(control => {
      if (control.type === 'slider' && control.defaultValue !== undefined) {
        values[control.id] = control.defaultValue as number;
      }
    });
    return values;
  }, [config.controls]);
  
  const [controlValues, setControlValues] = useState<Record<string, number>>(initialControlValues);

  // 当 config 变化时重置控制值
  useEffect(() => {
    setControlValues(initialControlValues);
  }, [initialControlValues]);

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
        // 点击 Run：清空当前数据，开始新的记录
        setDataHistory([]);
        setSelectedRunId(null); // 切换到实时数据
        isaacService.startSimulation();
      } else if (control.command === 'reset_env') {
        // 点击 Reset：保存当前数据到历史记录
        if (dataHistory.length > 0) {
          const newRun = {
            id: runCounter,
            data: [...dataHistory],
            label: `Run ${runCounter} (M=${controlValues['disk_mass']?.toFixed(1) || '1.0'}kg)`
          };
          setSavedRuns(prev => [...prev, newRun]);
          setRunCounter(prev => prev + 1);
        }
        isaacService.resetSimulation();
      } else {
        isaacService.sendCommand(control.command, value);
      }
    }
  }, [config.controls, dataHistory, runCounter, controlValues]);

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
        console.log(' Entering experiment (switching camera and resetting physics)...');
        const entered = await isaacService.enterExperiment(config.experimentNumber);

        if (entered) {
          console.log('✅ Experiment entered with camera config');
          setLoadingProgress(80);

          // 发送所有 slider 控件的默认值到后端
          config.controls?.forEach(control => {
            if (control.type === 'slider' && control.defaultValue !== undefined && control.command) {
              console.log(` Sending default value for ${control.id}: ${control.defaultValue}`);
              isaacService.sendCommand(control.command, control.defaultValue as number);
            }
          });

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

    // 订阅遥测数据（带平滑处理）
    const unsubscribeTelemetry = isaacService.onTelemetry((data) => {
      setDataHistory(prev => {
        // 增加历史数据长度到 120 点，让曲线更完整
        const maxLength = 120;
        
        // 如果有足够的历史数据，应用指数移动平均平滑
        let smoothedData = { ...data };
        if (prev.length > 0) {
          const lastData = prev[prev.length - 1];
          const smoothFactor = 0.3; // 平滑因子，越小越平滑 (0.1-0.5)
          
          // 对数值类型的字段进行平滑处理
          Object.keys(data).forEach(key => {
            if (typeof data[key] === 'number' && typeof lastData[key] === 'number' && key !== 'timestamp') {
              smoothedData[key] = lastData[key] * (1 - smoothFactor) + data[key] * smoothFactor;
            }
          });
        }
        
        const newData = [...prev, smoothedData];
        if (newData.length > maxLength) return newData.slice(newData.length - maxLength);
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
      console.log(' ExperimentView unmounting, keeping connection alive');
    };
  }, [config.id, config.experimentNumber]);

  // 显示的数据：实时模式显示最新数据，历史模式显示保存数据的最后一个点
  const displayData = selectedRunId === null 
    ? dataHistory 
    : (savedRuns.find(r => r.id === selectedRunId)?.data || []);
  const currentData = displayData.length > 0 ? displayData[displayData.length - 1] : null;
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
            <div className="text-[10px] text-gray-500 font-mono">Experiment {config.experimentNumber}</div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Run 和 Reset 按钮 */}
          <button
            onClick={() => {
              setDataHistory([]);
              setSelectedRunId(null);
              isaacService.startSimulation();
            }}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-bold rounded-lg transition-all shadow-md hover:shadow-lg flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
              <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
            </svg>
            RUN
          </button>
          <button
            onClick={() => {
              if (dataHistory.length > 0) {
                const newRun = {
                  id: runCounter,
                  data: [...dataHistory],
                  label: `Run ${runCounter}`
                };
                setSavedRuns(prev => [...prev, newRun]);
                setRunCounter(prev => prev + 1);
              }
              isaacService.resetSimulation();
            }}
            className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm font-bold rounded-lg transition-all shadow-md hover:shadow-lg flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            RESET
          </button>

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
        {/* Full Screen: 3D Viewport with WebRTC Streaming */}
        <div className="flex-1 relative bg-gray-100 flex flex-col">
          <div className="absolute inset-0 bg-[linear-gradient(rgba(100,116,139,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(100,116,139,0.1)_1px,transparent_1px)] bg-[size:40px_40px] opacity-30 pointer-events-none"></div>

          {/* ========== WebRTC VIDEO STREAM (全屏) ========== */}
          <div className="flex-1 relative z-10">
            {/* 使用WebRTC实现高性能视频流 */}
            <WebRTCIsaacViewer
              serverUrl="http://10.20.5.3:8080"
              usdPath={config.usdPath}
              className="w-full h-full"
            />

            {/* ========== 左上角悬浮速度曲线窗口 ========== */}
            <div className="absolute top-4 left-4 w-[420px] bg-white/90 backdrop-blur-md rounded-xl shadow-2xl border border-gray-200/50 overflow-hidden z-20">
              {/* 标题栏 */}
              <div className="flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-blue-600 to-purple-600">
                <div className="flex items-center gap-2 text-white text-xs font-bold uppercase tracking-wider">
                  <Activity size={14} />
                  <span>Velocity Telemetry</span>
                </div>
                {/* 实时数据显示 */}
                <div className="flex gap-3">
                  {config.chartConfig.map((chart) => (
                    <div key={chart.key} className="flex items-center gap-1.5">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: chart.color }}></div>
                      <span className="text-white/90 text-[10px] font-mono">
                        {chart.label}: {currentData ? (currentData[chart.key]?.toFixed(2) ?? '--') : '--'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              
              {/* 图表区域 */}
              <div className="h-[180px] p-2 bg-white/50">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={dataHistory}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis dataKey="timestamp" hide />
                    <YAxis 
                      yAxisId="left" 
                      stroke="#6b7280" 
                      fontSize={9} 
                      tickFormatter={(val) => val.toFixed(1)}
                      width={35}
                    />
                    <YAxis 
                      yAxisId="right" 
                      orientation="right" 
                      stroke="#6b7280" 
                      fontSize={9} 
                      tickFormatter={(val) => val.toFixed(1)}
                      width={35}
                    />
                    <Tooltip
                      contentStyle={{ 
                        backgroundColor: 'rgba(255,255,255,0.95)', 
                        border: '1px solid #e5e7eb', 
                        fontSize: '11px', 
                        borderRadius: '8px', 
                        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                        padding: '8px 12px'
                      }}
                      labelStyle={{ display: 'none' }}
                      itemStyle={{ color: '#374151', padding: '2px 0' }}
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

        {/* ========== 右侧操作面板 - 暂时隐藏 ========== */}
        {/* 如需恢复，将下面的 false 改为 true */}
        {false && (
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
                          value={currentValue}
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
                <LineChart data={selectedRunId === null ? dataHistory : (savedRuns.find(r => r.id === selectedRunId)?.data || [])}>
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
                  {/* 时间线滑块 - 拖动查看数据（只在查看保存的数据或有足够数据时显示） */}
                  {displayData.length > 10 && (
                    <Brush 
                      dataKey="timestamp" 
                      height={25} 
                      stroke="#6366f1"
                      fill="#f3f4f6"
                      tickFormatter={() => ''}
                    />
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
            
            {/* 保存的运行记录选择器 */}
            {savedRuns.length > 0 && (
              <div className="border-t border-gray-200 p-3 bg-gray-50">
                <div className="text-gray-700 text-xs font-bold mb-2 uppercase tracking-wider">Saved Runs</div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => setSelectedRunId(null)}
                    className={`px-3 py-1.5 text-xs font-mono rounded-lg transition-colors ${
                      selectedRunId === null 
                        ? 'bg-blue-600 text-white' 
                        : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                    }`}
                  >
                    Live
                  </button>
                  {savedRuns.map(run => (
                    <button
                      key={run.id}
                      onClick={() => setSelectedRunId(run.id)}
                      className={`px-3 py-1.5 text-xs font-mono rounded-lg transition-colors ${
                        selectedRunId === run.id 
                          ? 'bg-purple-600 text-white' 
                          : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                      }`}
                    >
                      {run.label}
                    </button>
                  ))}
                  <button
                    onClick={() => setSavedRuns([])}
                    className="px-3 py-1.5 text-xs font-mono rounded-lg bg-red-100 text-red-600 hover:bg-red-200 transition-colors"
                  >
                    Clear All
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
        )}
      </div>
    </div>
  );
};

export default ExperimentView;
