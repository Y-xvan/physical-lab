/**
 * 超流畅 Isaac Sim 查看器
 *
 * 优化策略：
 * 1. 持续流模式（不是按需请求）
 * 2. 极低分辨率（320x240）+ 客户端放大
 * 3. CSS图像平滑处理
 * 4. 预加载和缓存
 * 5. 降低鼠标控制灵敏度以减少频繁更新
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Camera, Maximize2, Minimize2, Settings, Gauge } from 'lucide-react';

interface UltraFastIsaacViewerProps {
  wsUrl?: string;
  usdPath?: string;
  initialWidth?: number;
  initialHeight?: number;
  initialQuality?: number;
  className?: string;
}

const UltraFastIsaacViewer: React.FC<UltraFastIsaacViewerProps> = ({
  wsUrl = 'ws://10.20.5.3:30000',
  usdPath,
  initialWidth = 320,
  initialHeight = 240,
  initialQuality = 35,
  className = ''
}) => {
  // 连接状态
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 视频状态
  const [frameData, setFrameData] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);

  // FPS 统计
  const [currentFps, setCurrentFps] = useState(0);
  const [latency, setLatency] = useState(0);

  // 质量设置
  const [showSettings, setShowSettings] = useState(false);
  const [width, setWidth] = useState(initialWidth);
  const [height, setHeight] = useState(initialHeight);
  const [quality, setQuality] = useState(initialQuality);

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const frameCountRef = useRef(0);
  const lastFrameTimeRef = useRef(Date.now());
  const fpsTimerRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 鼠标控制
  const [isDragging, setIsDragging] = useState(false);
  const [dragMode, setDragMode] = useState<'orbit' | 'pan' | null>(null);
  const lastDragTimeRef = useRef(0);
  const dragThrottleMs = 16; // 限制拖动更新频率（约60fps）

  /**
   * 连接到服务器
   */
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    console.log('🔌 Connecting to Ultra-Fast Isaac Sim:', wsUrl);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('✅ Connected!');
      setConnected(true);
      setError(null);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleMessage(data);
      } catch (e) {
        console.error('Parse error:', e);
      }
    };

    ws.onerror = (event) => {
      console.error('🚨 WebSocket error:', event);
      setError('Connection error');
    };

    ws.onclose = (event) => {
      console.log('🔌 Disconnected');
      setConnected(false);
      setStreaming(false);

      // 自动重连
      if (event.code !== 1000) {
        setTimeout(connect, 3000);
      }
    };
  }, [wsUrl]);

  /**
   * 处理消息
   */
  const handleMessage = useCallback((data: any) => {
    switch (data.type) {
      case 'connected':
        console.log('🎉', data.message);
        // 连接后立即开始流
        startStream();
        // 加载USD（如果有）
        if (usdPath) {
          loadUSD(usdPath);
        }
        break;

      case 'frame':
        // 更新帧
        setFrameData(data.data);

        // 计算延迟
        const now = Date.now();
        const frameLatency = now - (data.timestamp * 1000);
        setLatency(Math.round(frameLatency));

        // FPS计数
        frameCountRef.current++;
        lastFrameTimeRef.current = now;
        break;

      case 'stream_started':
        console.log('🎬 Streaming started');
        setStreaming(true);
        break;

      case 'stream_stopped':
        console.log('🛑 Streaming stopped');
        setStreaming(false);
        break;

      case 'usd_loaded':
        console.log('✅ USD loaded:', data.usd_path);
        break;

      case 'quality_updated':
        console.log('📹 Quality updated');
        break;

      case 'error':
        console.error('❌', data.message);
        setError(data.message);
        break;

      default:
        console.log('📩', data);
    }
  }, [usdPath]);

  /**
   * 发送消息
   */
  const sendMessage = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  /**
   * 开始流
   */
  const startStream = useCallback(() => {
    sendMessage({ type: 'start_stream' });
  }, [sendMessage]);

  /**
   * 停止流
   */
  const stopStream = useCallback(() => {
    sendMessage({ type: 'stop_stream' });
  }, [sendMessage]);

  /**
   * 加载USD
   */
  const loadUSD = useCallback((path: string) => {
    sendMessage({ type: 'load_usd', usd_path: path });
  }, [sendMessage]);

  /**
   * 更新质量设置
   */
  const updateQuality = useCallback(() => {
    sendMessage({
      type: 'set_quality',
      width,
      height,
      quality
    });
    setShowSettings(false);
  }, [sendMessage, width, height, quality]);

  /**
   * 相机控制（带节流）
   */
  const controlCamera = useCallback((action: string, params: any) => {
    const now = Date.now();
    if (now - lastDragTimeRef.current < dragThrottleMs) {
      return; // 跳过过于频繁的更新
    }

    sendMessage({
      type: 'camera_control',
      action,
      ...params
    });

    lastDragTimeRef.current = now;
  }, [sendMessage]);

  /**
   * 鼠标事件
   */
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);

    if (e.button === 0) {
      setDragMode('orbit');
    } else if (e.button === 2) {
      setDragMode('pan');
      e.preventDefault();
    }
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !dragMode) return;

    const deltaX = e.movementX;
    const deltaY = e.movementY;

    if (dragMode === 'orbit') {
      controlCamera('orbit', { deltaX, deltaY });
    } else if (dragMode === 'pan') {
      controlCamera('pan', { deltaX: -deltaX, deltaY: deltaY });
    }
  }, [isDragging, dragMode, controlCamera]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    setDragMode(null);
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 1 : -1;
    controlCamera('zoom', { delta });
  }, [controlCamera]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
  }, []);

  /**
   * 初始化
   */
  useEffect(() => {
    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000);
      }
    };
  }, [connect]);

  /**
   * FPS 计算
   */
  useEffect(() => {
    fpsTimerRef.current = window.setInterval(() => {
      setCurrentFps(frameCountRef.current);
      frameCountRef.current = 0;
    }, 1000);

    return () => {
      if (fpsTimerRef.current) {
        clearInterval(fpsTimerRef.current);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={`relative flex flex-col w-full h-full ${className}`}
      style={styles.container}
    >
      {/* 状态栏 */}
      <div style={styles.statusBar}>
        <div style={styles.statusLeft}>
          <div style={{
            ...styles.statusDot,
            backgroundColor: connected ? '#4CAF50' : '#f44336'
          }} />
          <span className="font-mono text-xs">
            {connected ? (streaming ? '🎬 流式传输' : '已连接') : '未连接'}
          </span>
        </div>

        <div style={styles.statusCenter}>
          <Gauge size={14} className="text-blue-400" />
          <span className="font-mono text-xs text-blue-400">
            {currentFps} FPS
          </span>
          {latency > 0 && (
            <span className="font-mono text-xs text-gray-400">
              {latency}ms
            </span>
          )}
        </div>

        <div style={styles.statusRight}>
          <button
            onClick={() => setShowSettings(!showSettings)}
            style={styles.iconButton}
            title="设置"
          >
            <Settings size={14} />
          </button>
        </div>
      </div>

      {/* 设置面板 */}
      {showSettings && (
        <div style={styles.settingsPanel}>
          <h3 className="font-bold text-sm mb-3">性能设置</h3>

          <div className="space-y-2">
            <div style={styles.settingRow}>
              <label className="text-xs">分辨率:</label>
              <select
                value={`${width}x${height}`}
                onChange={(e) => {
                  const [w, h] = e.target.value.split('x').map(Number);
                  setWidth(w);
                  setHeight(h);
                }}
                style={styles.select}
              >
                <option value="240x180">240x180 (最快)</option>
                <option value="320x240">320x240 (推荐)</option>
                <option value="480x360">480x360 (平衡)</option>
                <option value="640x480">640x480 (高质量)</option>
              </select>
            </div>

            <div style={styles.settingRow}>
              <label className="text-xs">压缩质量:</label>
              <input
                type="range"
                min="20"
                max="80"
                value={quality}
                onChange={(e) => setQuality(Number(e.target.value))}
                style={styles.slider}
              />
              <span className="text-xs">{quality}</span>
            </div>

            <div className="flex gap-2 mt-3">
              <button onClick={updateQuality} style={styles.applyButton}>
                应用
              </button>
              <button onClick={() => setShowSettings(false)} style={styles.cancelButton}>
                取消
              </button>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-gray-700">
            <p className="text-xs text-gray-400">
              💡 降低分辨率和质量可大幅提升流畅度
            </p>
          </div>
        </div>
      )}

      {/* 视频显示 */}
      <div
        style={styles.videoContainer}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
        onContextMenu={handleContextMenu}
      >
        {frameData ? (
          <img
            src={`data:image/jpeg;base64,${frameData}`}
            alt="Isaac Sim"
            style={styles.video}
            draggable={false}
          />
        ) : (
          <div style={styles.placeholder}>
            {error ? (
              <div className="flex flex-col items-center gap-3">
                <span className="text-red-400">❌ {error}</span>
                <button onClick={connect} style={styles.retryButton}>
                  重新连接
                </button>
              </div>
            ) : connected ? (
              <div className="flex flex-col items-center gap-3">
                <Camera size={40} className="text-gray-500 animate-pulse" />
                <span className="text-gray-400">等待视频流...</span>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <span className="text-gray-400">正在连接...</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 控制栏 */}
      <div style={styles.controlBar}>
        <div></div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {streaming && (
            <button onClick={stopStream} style={styles.stopButton}>
              停止
            </button>
          )}
          {!streaming && connected && (
            <button onClick={startStream} style={styles.startButton}>
              开始
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// 样式
const styles: { [key: string]: React.CSSProperties } = {
  container: {
    backgroundColor: '#0a0a0a',
    borderRadius: '8px',
    overflow: 'hidden',
  },
  statusBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '6px 12px',
    backgroundColor: '#1a1a1a',
    borderBottom: '1px solid #333',
  },
  statusLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  statusCenter: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  statusRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  statusDot: {
    width: '6px',
    height: '6px',
    borderRadius: '50%',
  },
  iconButton: {
    padding: '4px',
    backgroundColor: 'transparent',
    color: '#fff',
    border: '1px solid #444',
    borderRadius: '3px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
  },
  settingsPanel: {
    position: 'absolute',
    top: '40px',
    right: '12px',
    backgroundColor: '#1a1a1a',
    border: '1px solid #444',
    borderRadius: '6px',
    padding: '12px',
    zIndex: 10,
    minWidth: '220px',
    color: '#fff',
    boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
  },
  settingRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '8px',
  },
  select: {
    flex: 1,
    padding: '3px 6px',
    backgroundColor: '#0a0a0a',
    border: '1px solid #444',
    borderRadius: '3px',
    color: '#fff',
    fontSize: '12px',
  },
  slider: {
    flex: 1,
  },
  applyButton: {
    flex: 1,
    padding: '6px 12px',
    backgroundColor: '#4CAF50',
    color: '#fff',
    border: 'none',
    borderRadius: '3px',
    cursor: 'pointer',
    fontSize: '12px',
  },
  cancelButton: {
    flex: 1,
    padding: '6px 12px',
    backgroundColor: '#555',
    color: '#fff',
    border: 'none',
    borderRadius: '3px',
    cursor: 'pointer',
    fontSize: '12px',
  },
  videoContainer: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    cursor: 'grab',
    backgroundColor: '#000',
  },
  video: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    imageRendering: 'auto', // 使用浏览器的图像平滑算法
    userSelect: 'none',
  },
  placeholder: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    height: '100%',
  },
  retryButton: {
    padding: '8px 16px',
    backgroundColor: '#4CAF50',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '13px',
  },
  controlBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '6px 12px',
    backgroundColor: '#1a1a1a',
    borderTop: '1px solid #333',
  },
  stopButton: {
    padding: '4px 12px',
    backgroundColor: '#f44336',
    color: '#fff',
    border: 'none',
    borderRadius: '3px',
    cursor: 'pointer',
    fontSize: '12px',
  },
  startButton: {
    padding: '4px 12px',
    backgroundColor: '#4CAF50',
    color: '#fff',
    border: 'none',
    borderRadius: '3px',
    cursor: 'pointer',
    fontSize: '12px',
  },
};

export default UltraFastIsaacViewer;
