/**
 * 优化的 Isaac Sim 查看器组件
 *
 * 优化策略：
 * 1. 按需请求帧：只在必要时才请求新帧
 * 2. 智能帧请求：用户交互后自动请求更新
 * 3. 可配置质量：根据网络状况调整图像质量
 * 4. 帧率限制：避免过于频繁的请求
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Camera, Maximize2, Minimize2, RefreshCw, Settings } from 'lucide-react';

interface OptimizedIsaacViewerProps {
  wsUrl?: string;
  usdPath?: string;
  width?: number;
  height?: number;
  quality?: number;
  autoRefresh?: boolean;  // 是否自动刷新
  refreshInterval?: number;  // 自动刷新间隔（毫秒）
  className?: string;
}

const OptimizedIsaacViewer: React.FC<OptimizedIsaacViewerProps> = ({
  wsUrl = 'ws://10.20.5.3:30000',
  usdPath,
  width = 640,
  height = 480,
  quality = 60,
  autoRefresh = false,
  refreshInterval = 100,  // 默认100ms（10fps）
  className = ''
}) => {
  // 连接状态
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 视频状态
  const [frameData, setFrameData] = useState<string | null>(null);
  const [lastFrameTime, setLastFrameTime] = useState<number>(0);
  const [currentFps, setCurrentFps] = useState(0);

  // 设置
  const [currentWidth, setCurrentWidth] = useState(width);
  const [currentHeight, setCurrentHeight] = useState(height);
  const [currentQuality, setCurrentQuality] = useState(quality);
  const [showSettings, setShowSettings] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const frameCountRef = useRef(0);
  const fpsTimerRef = useRef<number | null>(null);
  const autoRefreshTimerRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 鼠标交互状态
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [dragMode, setDragMode] = useState<'orbit' | 'pan' | null>(null);

  /**
   * WebSocket 连接
   */
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    console.log('🔌 Connecting to Optimized Isaac Sim:', wsUrl);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('✅ Connected to Optimized Isaac Sim');
      setConnected(true);
      setError(null);

      // 设置初始质量
      sendQualitySettings();

      // 加载 USD（如果提供）
      if (usdPath) {
        loadUSD(usdPath);
      }

      // 请求第一帧
      requestFrame();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleMessage(data);
      } catch (e) {
        console.error('Failed to parse message:', e);
      }
    };

    ws.onerror = (event) => {
      console.error('🚨 WebSocket error:', event);
      setError('WebSocket connection error');
    };

    ws.onclose = (event) => {
      console.log('🔌 Disconnected:', event.code);
      setConnected(false);

      // 自动重连
      if (event.code !== 1000) {
        setTimeout(connect, 3000);
      }
    };
  }, [wsUrl, usdPath]);

  /**
   * 处理消息
   */
  const handleMessage = useCallback((data: any) => {
    switch (data.type) {
      case 'connected':
        console.log('🎉 Server:', data.message);
        break;

      case 'frame':
        // 更新帧
        setFrameData(data.data);
        setLastFrameTime(Date.now());

        // 计算 FPS
        frameCountRef.current++;
        break;

      case 'usd_loaded':
        console.log('✅ USD loaded:', data.usd_path);
        // USD 加载后请求一帧
        requestFrame();
        break;

      case 'camera_updated':
        console.log('📷 Camera updated');
        break;

      case 'quality_updated':
        console.log('📹 Quality updated:', data);
        break;

      case 'error':
        console.error('❌ Server error:', data.message);
        setError(data.message);
        break;

      default:
        console.log('📩 Received:', data);
    }
  }, []);

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
   * 请求单帧
   */
  const requestFrame = useCallback(() => {
    sendMessage({ type: 'request_frame' });
  }, [sendMessage]);

  /**
   * 加载 USD
   */
  const loadUSD = useCallback((path: string) => {
    sendMessage({ type: 'load_usd', usd_path: path });
  }, [sendMessage]);

  /**
   * 发送质量设置
   */
  const sendQualitySettings = useCallback(() => {
    sendMessage({
      type: 'set_quality',
      width: currentWidth,
      height: currentHeight,
      quality: currentQuality
    });
  }, [sendMessage, currentWidth, currentHeight, currentQuality]);

  /**
   * 相机控制
   */
  const controlCamera = useCallback((action: string, params: any) => {
    const sent = sendMessage({
      type: 'camera_control',
      action,
      ...params
    });

    // 相机移动后，服务器会自动发送一帧
    // 不需要额外请求
  }, [sendMessage]);

  /**
   * 鼠标事件处理
   */
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);
    setDragStart({ x: e.clientX, y: e.clientY });

    // 左键：旋转，右键或中键：平移
    if (e.button === 0) {
      setDragMode('orbit');
    } else if (e.button === 1 || e.button === 2) {
      setDragMode('pan');
      e.preventDefault();
    }
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !dragMode) return;

    const deltaX = e.clientX - dragStart.x;
    const deltaY = e.clientY - dragStart.y;

    if (dragMode === 'orbit') {
      controlCamera('orbit', { deltaX, deltaY });
    } else if (dragMode === 'pan') {
      controlCamera('pan', { deltaX: -deltaX, deltaY: deltaY });
    }

    setDragStart({ x: e.clientX, y: e.clientY });
  }, [isDragging, dragMode, dragStart, controlCamera]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    setDragMode(null);
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 1 : -1;
    controlCamera('zoom', { delta });
  }, [controlCamera]);

  /**
   * 右键菜单禁用（用于平移）
   */
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
  }, []);

  /**
   * 全屏切换
   */
  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return;

    if (!isFullscreen) {
      containerRef.current.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  }, [isFullscreen]);

  /**
   * 应用质量设置
   */
  const applyQualitySettings = useCallback(() => {
    sendQualitySettings();
    setShowSettings(false);
    // 请求新帧以应用设置
    requestFrame();
  }, [sendQualitySettings, requestFrame]);

  /**
   * 初始化连接
   */
  useEffect(() => {
    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted');
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

  /**
   * 自动刷新
   */
  useEffect(() => {
    if (autoRefresh && connected) {
      autoRefreshTimerRef.current = window.setInterval(() => {
        requestFrame();
      }, refreshInterval);
    } else {
      if (autoRefreshTimerRef.current) {
        clearInterval(autoRefreshTimerRef.current);
        autoRefreshTimerRef.current = null;
      }
    }

    return () => {
      if (autoRefreshTimerRef.current) {
        clearInterval(autoRefreshTimerRef.current);
      }
    };
  }, [autoRefresh, connected, refreshInterval, requestFrame]);

  /**
   * 全屏状态监听
   */
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, []);

  return (
    <div ref={containerRef} className={`relative ${className}`} style={styles.container}>
      {/* 状态栏 */}
      <div style={styles.statusBar}>
        <div style={styles.statusLeft}>
          <span style={{
            ...styles.statusDot,
            backgroundColor: connected ? '#4CAF50' : '#f44336'
          }} />
          <span className="font-mono text-sm">
            {connected ? '已连接' : '未连接'}
          </span>
        </div>

        <div style={styles.statusCenter}>
          <span className="font-mono text-xs text-gray-400">
            {currentWidth}x{currentHeight} @ Q{currentQuality}
          </span>
          {frameData && (
            <span className="font-mono text-xs text-green-400">
              {currentFps} FPS
            </span>
          )}
        </div>

        <div style={styles.statusRight}>
          <button
            onClick={() => setShowSettings(!showSettings)}
            style={styles.iconButton}
            title="设置"
          >
            <Settings size={16} />
          </button>
          <button
            onClick={requestFrame}
            style={styles.iconButton}
            title="刷新"
            disabled={!connected}
          >
            <RefreshCw size={16} />
          </button>
          <button
            onClick={toggleFullscreen}
            style={styles.iconButton}
            title="全屏"
          >
            {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>
      </div>

      {/* 设置面板 */}
      {showSettings && (
        <div style={styles.settingsPanel}>
          <h3 className="font-bold mb-3">质量设置</h3>

          <div style={styles.settingRow}>
            <label className="text-sm">宽度:</label>
            <input
              type="number"
              value={currentWidth}
              onChange={(e) => setCurrentWidth(Number(e.target.value))}
              style={styles.input}
              min={320}
              max={1920}
              step={160}
            />
          </div>

          <div style={styles.settingRow}>
            <label className="text-sm">高度:</label>
            <input
              type="number"
              value={currentHeight}
              onChange={(e) => setCurrentHeight(Number(e.target.value))}
              style={styles.input}
              min={240}
              max={1080}
              step={120}
            />
          </div>

          <div style={styles.settingRow}>
            <label className="text-sm">质量 (1-100):</label>
            <input
              type="number"
              value={currentQuality}
              onChange={(e) => setCurrentQuality(Number(e.target.value))}
              style={styles.input}
              min={1}
              max={100}
            />
          </div>

          <div style={styles.settingRow}>
            <button onClick={applyQualitySettings} style={styles.applyButton}>
              应用设置
            </button>
            <button onClick={() => setShowSettings(false)} style={styles.cancelButton}>
              取消
            </button>
          </div>

          <div style={styles.settingHint}>
            <p className="text-xs text-gray-400">
              💡 降低分辨率和质量可以提高响应速度
            </p>
          </div>
        </div>
      )}

      {/* 视频显示区域 */}
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
            alt="Isaac Sim Viewport"
            style={styles.video}
            draggable={false}
          />
        ) : (
          <div style={styles.placeholder}>
            {error ? (
              <div style={styles.error}>
                <span>❌ {error}</span>
                <button onClick={connect} style={styles.retryButton}>
                  重新连接
                </button>
              </div>
            ) : connected ? (
              <div className="flex flex-col items-center gap-4">
                <Camera size={48} className="text-gray-500" />
                <span className="text-gray-400">等待帧数据...</span>
                <button onClick={requestFrame} style={styles.requestButton}>
                  请求帧
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-4">
                <span className="text-gray-400">正在连接到 Isaac Sim...</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 控制提示 */}
      <div style={styles.controlHints}>
        <span className="text-xs text-gray-500">
          左键拖动: 旋转 | 右键拖动: 平移 | 滚轮: 缩放
        </span>
      </div>
    </div>
  );
};

// 样式
const styles: { [key: string]: React.CSSProperties } = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    width: '100%',
    height: '100%',
    backgroundColor: '#0a0a0a',
    borderRadius: '8px',
    overflow: 'hidden',
    position: 'relative',
  },
  statusBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '8px 16px',
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
    gap: '16px',
  },
  statusRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  statusDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
  },
  iconButton: {
    padding: '6px',
    backgroundColor: 'transparent',
    color: '#fff',
    border: '1px solid #444',
    borderRadius: '4px',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  settingsPanel: {
    position: 'absolute',
    top: '50px',
    right: '16px',
    backgroundColor: '#1a1a1a',
    border: '1px solid #444',
    borderRadius: '8px',
    padding: '16px',
    zIndex: 10,
    minWidth: '250px',
    color: '#fff',
  },
  settingRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '12px',
    gap: '8px',
  },
  input: {
    padding: '4px 8px',
    backgroundColor: '#0a0a0a',
    border: '1px solid #444',
    borderRadius: '4px',
    color: '#fff',
    width: '100px',
  },
  applyButton: {
    flex: 1,
    padding: '8px 16px',
    backgroundColor: '#4CAF50',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '14px',
  },
  cancelButton: {
    flex: 1,
    padding: '8px 16px',
    backgroundColor: '#555',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '14px',
  },
  settingHint: {
    marginTop: '12px',
    paddingTop: '12px',
    borderTop: '1px solid #333',
  },
  videoContainer: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    cursor: 'grab',
    position: 'relative',
  },
  video: {
    maxWidth: '100%',
    maxHeight: '100%',
    objectFit: 'contain',
    userSelect: 'none',
  },
  placeholder: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#888',
  },
  error: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '16px',
    color: '#f44336',
  },
  retryButton: {
    padding: '8px 16px',
    backgroundColor: '#4CAF50',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
  },
  requestButton: {
    padding: '10px 20px',
    backgroundColor: '#2196F3',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '14px',
  },
  controlHints: {
    padding: '6px 16px',
    backgroundColor: '#1a1a1a',
    borderTop: '1px solid #333',
    textAlign: 'center',
  },
};

export default OptimizedIsaacViewer;
