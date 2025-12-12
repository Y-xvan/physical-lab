// IsaacStreamViewer.tsx
// 用于显示 Isaac Sim WebSocket 视频流的 React 组件

import React, { useEffect, useRef, useState, useCallback } from 'react';

interface IsaacStreamViewerProps {
  wsUrl?: string;
  usdPath?: string;
  fps?: number;
  quality?: number;
  className?: string;
}

const IsaacStreamViewer: React.FC<IsaacStreamViewerProps> = ({
  wsUrl = 'ws://localhost:30000',
  usdPath,
  fps = 15,
  quality = 70,
  className = ''
}) => {
  const [connected, setConnected] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [frameData, setFrameData] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sceneInfo, setSceneInfo] = useState<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const frameCountRef = useRef(0);
  const lastFrameTimeRef = useRef(Date.now());
  const [actualFps, setActualFps] = useState(0);

  // 连接 WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    console.log('🔌 Connecting to Isaac Sim:', wsUrl);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('✅ Connected to Isaac Sim');
      setConnected(true);
      setError(null);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        switch (data.type) {
          case 'connected':
            console.log('🎉 Server confirmed connection:', data.message);
            // 如果有 USD 路径，加载它
            if (usdPath) {
              sendMessage({ type: 'load_usd', usd_path: usdPath });
            }
            break;

          case 'usd_loaded':
            console.log('✅ USD loaded:', data.usd_path);
            setSceneInfo(data);
            // USD 加载后自动开始流
            startStream();
            break;

          case 'stream_started':
            console.log('🎬 Stream started');
            setStreaming(true);
            break;

          case 'stream_stopped':
            console.log('🛑 Stream stopped');
            setStreaming(false);
            break;

          case 'frame':
            // 更新帧
            setFrameData(data.data);
            
            // 计算实际帧率
            frameCountRef.current++;
            const now = Date.now();
            if (now - lastFrameTimeRef.current >= 1000) {
              setActualFps(frameCountRef.current);
              frameCountRef.current = 0;
              lastFrameTimeRef.current = now;
            }
            break;

          case 'stage_updated':
            console.log('🔄 Stage updated:', data.message);
            break;

          case 'error':
            console.error('❌ Server error:', data.message);
            setError(data.message);
            break;

          default:
            console.log('📩 Received:', data);
        }
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
      setStreaming(false);
      
      // 自动重连
      if (event.code !== 1000) {
        setTimeout(connect, 3000);
      }
    };
  }, [wsUrl, usdPath]);

  // 发送消息
  const sendMessage = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  // 开始流
  const startStream = useCallback(() => {
    sendMessage({
      type: 'start_stream',
      fps: fps,
      quality: quality
    });
  }, [sendMessage, fps, quality]);

  // 停止流
  const stopStream = useCallback(() => {
    sendMessage({ type: 'stop_stream' });
  }, [sendMessage]);

  // 加载 USD
  const loadUsd = useCallback((path: string) => {
    sendMessage({ type: 'load_usd', usd_path: path });
  }, [sendMessage]);

  // 请求单帧
  const requestFrame = useCallback(() => {
    sendMessage({ type: 'request_frame' });
  }, [sendMessage]);

  // 初始化连接
  useEffect(() => {
    connect();
    
    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted');
      }
    };
  }, [connect]);

  // USD 路径变化时加载
  useEffect(() => {
    if (connected && usdPath) {
      loadUsd(usdPath);
    }
  }, [connected, usdPath, loadUsd]);

  return (
    <div className={`isaac-stream-viewer ${className}`} style={styles.container}>
      {/* 状态栏 */}
      <div style={styles.statusBar}>
        <span style={{
          ...styles.statusDot,
          backgroundColor: connected ? '#4CAF50' : '#f44336'
        }} />
        <span>{connected ? 'Connected' : 'Disconnected'}</span>
        {streaming && <span style={styles.fpsDisplay}>FPS: {actualFps}</span>}
        {sceneInfo && (
          <span style={styles.sceneInfo}>
            Prims: {sceneInfo.prim_count}
          </span>
        )}
      </div>

      {/* 视频显示区域 */}
      <div style={styles.videoContainer}>
        {frameData ? (
          <img
            src={`data:image/jpeg;base64,${frameData}`}
            alt="Isaac Sim Viewport"
            style={styles.video}
          />
        ) : (
          <div style={styles.placeholder}>
            {error ? (
              <div style={styles.error}>
                <span>❌ {error}</span>
              </div>
            ) : connected ? (
              <div>
                <span>⏳ Waiting for frames...</span>
                <button onClick={requestFrame} style={styles.button}>
                  Request Frame
                </button>
              </div>
            ) : (
              <span>🔌 Connecting to Isaac Sim...</span>
            )}
          </div>
        )}
      </div>

      {/* 控制按钮 */}
      <div style={styles.controls}>
        {connected && (
          <>
            <button
              onClick={streaming ? stopStream : startStream}
              style={{
                ...styles.button,
                backgroundColor: streaming ? '#f44336' : '#4CAF50'
              }}
            >
              {streaming ? '⏹ Stop Stream' : '▶ Start Stream'}
            </button>
            <button onClick={requestFrame} style={styles.button}>
              📷 Capture Frame
            </button>
          </>
        )}
        {!connected && (
          <button onClick={connect} style={styles.button}>
            🔌 Reconnect
          </button>
        )}
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
    backgroundColor: '#1a1a1a',
    borderRadius: '8px',
    overflow: 'hidden',
  },
  statusBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '8px 12px',
    backgroundColor: '#2a2a2a',
    color: '#fff',
    fontSize: '14px',
  },
  statusDot: {
    width: '10px',
    height: '10px',
    borderRadius: '50%',
  },
  fpsDisplay: {
    marginLeft: 'auto',
    backgroundColor: '#333',
    padding: '2px 8px',
    borderRadius: '4px',
  },
  sceneInfo: {
    backgroundColor: '#333',
    padding: '2px 8px',
    borderRadius: '4px',
  },
  videoContainer: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  video: {
    maxWidth: '100%',
    maxHeight: '100%',
    objectFit: 'contain',
  },
  placeholder: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '16px',
    color: '#888',
    fontSize: '16px',
  },
  error: {
    color: '#f44336',
  },
  controls: {
    display: 'flex',
    gap: '8px',
    padding: '8px 12px',
    backgroundColor: '#2a2a2a',
  },
  button: {
    padding: '8px 16px',
    backgroundColor: '#4a4a4a',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '14px',
  },
};

export default IsaacStreamViewer;


// ============================================
// 使用示例 (在你的 ExperimentView.tsx 中)
// ============================================
/*

import IsaacStreamViewer from './IsaacStreamViewer';

const ExperimentView: React.FC<{ experimentId: string }> = ({ experimentId }) => {
  const usdPath = `/home/zhiren/Isaaclab_Assets/Experiment/${experimentId}/${experimentId}.usd`;
  
  return (
    <div style={{ width: '100%', height: '600px' }}>
      <IsaacStreamViewer
        wsUrl="ws://localhost:30000"
        usdPath={usdPath}
        fps={15}
        quality={70}
      />
    </div>
  );
};

*/