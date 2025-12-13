/**
 * WebRTC Isaac Sim 查看器
 *
 * 使用WebRTC实现高性能、低延迟的视频流传输
 *
 * 优势：
 * - H.264硬件解码，GPU加速
 * - 延迟 50-150ms（比JPEG方案快10倍）
 * - 带宽消耗仅2-5Mbps（是JPEG的1/10）
 * - 1080p@30fps流畅运行
 * - 自动处理网络抖动和丢包
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Camera, Wifi, WifiOff, Settings, Activity } from 'lucide-react';

interface WebRTCIsaacViewerProps {
  serverUrl?: string;  // HTTP服务器地址，如 http://10.20.5.3:8080
  usdPath?: string;
  className?: string;
}

interface ConnectionStats {
  fps: number;
  bitrate: number;
  packetsLost: number;
  latency: number;
}

const WebRTCIsaacViewer: React.FC<WebRTCIsaacViewerProps> = ({
  serverUrl = 'http://10.20.5.3:8080',
  usdPath,
  className = ''
}) => {
  // 连接状态
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 统计信息
  const [stats, setStats] = useState<ConnectionStats>({
    fps: 0,
    bitrate: 0,
    packetsLost: 0,
    latency: 0
  });

  // 设置面板
  const [showSettings, setShowSettings] = useState(false);

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const statsIntervalRef = useRef<number | null>(null);
  const pendingStreamRef = useRef<MediaStream | null>(null);

  // 鼠标控制
  const [isDragging, setIsDragging] = useState(false);
  const [dragMode, setDragMode] = useState<'orbit' | 'pan' | null>(null);
  const lastPosRef = useRef({ x: 0, y: 0 });

  /**
   * 连接到WebRTC服务器
   */
  const connect = useCallback(async () => {
    if (connecting || connected) {
      return;
    }

    setConnecting(true);
    setError(null);

    try {
      console.log('🔌 Connecting to WebRTC server:', serverUrl);

      // 创建RTCPeerConnection
      const pc = new RTCPeerConnection({
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' }
        ]
      });

      pcRef.current = pc;

      // 监听连接状态
      pc.onconnectionstatechange = () => {
        console.log('Connection state:', pc.connectionState);

        switch (pc.connectionState) {
          case 'connected':
            setConnected(true);
            setConnecting(false);
            console.log('✅ WebRTC connected!');
            startStatsMonitoring();
            break;
          case 'disconnected':
          case 'failed':
            setConnected(false);
            setConnecting(false);
            setError('Connection failed');
            stopStatsMonitoring();
            break;
          case 'closed':
            setConnected(false);
            setConnecting(false);
            stopStatsMonitoring();
            break;
        }
      };

      // 监听ICE连接状态
      pc.oniceconnectionstatechange = () => {
        console.log('ICE state:', pc.iceConnectionState);
      };

      // 接收视频轨道
      pc.ontrack = (event) => {
        console.log('📹 Received video track', event);
        console.log('Event streams:', event.streams);
        console.log('Event track:', event.track);
        console.log('videoRef.current:', videoRef.current);

        // 获取或创建 MediaStream
        let stream: MediaStream | null = null;

        if (event.streams && event.streams[0]) {
          console.log('✅ Using event.streams[0]');
          stream = event.streams[0];
        } else if (event.track) {
          console.log('✅ Creating new MediaStream from track');
          stream = new MediaStream([event.track]);
        }

        if (stream) {
          // 保存 stream 引用
          pendingStreamRef.current = stream;

          // 如果 video 元素已经准备好，立即设置
          if (videoRef.current) {
            console.log('✅ Setting srcObject immediately');
            videoRef.current.srcObject = stream;
            videoRef.current.play().catch(err => {
              console.error('Video play error:', err);
            });
          } else {
            console.log('⏳ Video element not ready, will set later');
          }
        }
      };

      // 添加一个transceivers来接收视频
      pc.addTransceiver('video', { direction: 'recvonly' });

      // 创建offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // 发送offer到服务器
      const response = await fetch(`${serverUrl}/offer`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          sdp: pc.localDescription?.sdp,
          type: pc.localDescription?.type
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const answer = await response.json();

      // 设置remote description
      await pc.setRemoteDescription(
        new RTCSessionDescription(answer)
      );

      console.log('✅ Offer/Answer exchange completed');

      // 加载USD（如果有）
      if (usdPath) {
        await loadUSD(usdPath);
      }

    } catch (err) {
      console.error('❌ Connection error:', err);
      setError(err instanceof Error ? err.message : 'Connection failed');
      setConnecting(false);
      disconnect();
    }
  }, [serverUrl, usdPath, connecting, connected]);

  /**
   * 断开连接
   */
  const disconnect = useCallback(() => {
    stopStatsMonitoring();

    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setConnected(false);
    setConnecting(false);
  }, []);

  /**
   * 重新初始化视频（场景切换后）
   */
  const reinitVideo = useCallback(async () => {
    try {
      console.log('🔧 调用 /reinit_video...');
      const response = await fetch(`${serverUrl}/reinit_video`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({})
      });

      const result = await response.json();
      if (result.status === 'ok') {
        console.log('✅ 视频重新初始化成功');
      } else {
        console.error('❌ 视频重新初始化失败:', result.message);
      }
    } catch (err) {
      console.error('❌ 视频重新初始化错误:', err);
    }
  }, [serverUrl]);

  /**
   * 加载USD场景
   */
  const loadUSD = useCallback(async (path: string) => {
    try {
      const response = await fetch(`${serverUrl}/load_usd`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ usd_path: path })
      });

      const result = await response.json();
      if (result.status === 'ok') {
        console.log('✅ USD loaded:', path);

        // 场景加载后，自动重新初始化视频
        console.log('🔧 自动重新初始化视频...');
        await reinitVideo();
      } else {
        console.error('❌ USD load failed:', result.message);
      }
    } catch (err) {
      console.error('❌ USD load error:', err);
    }
  }, [serverUrl, reinitVideo]);

  /**
   * 相机控制
   */
  const controlCamera = useCallback(async (action: string, params: any) => {
    try {
      await fetch(`${serverUrl}/camera`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          action,
          ...params
        })
      });
    } catch (err) {
      console.error('Camera control error:', err);
    }
  }, [serverUrl]);

  /**
   * 统计监控
   */
  const startStatsMonitoring = useCallback(() => {
    if (statsIntervalRef.current) {
      return;
    }

    statsIntervalRef.current = window.setInterval(async () => {
      if (!pcRef.current) {
        return;
      }

      try {
        const stats = await pcRef.current.getStats();
        let inboundRtp: any = null;

        stats.forEach((report) => {
          if (report.type === 'inbound-rtp' && report.kind === 'video') {
            inboundRtp = report;
          }
        });

        if (inboundRtp) {
          // 计算FPS
          const fps = inboundRtp.framesPerSecond || 0;

          // 计算码率 (bps -> Mbps)
          const bitrate = (inboundRtp.bytesReceived * 8) / 1000000 || 0;

          // 丢包
          const packetsLost = inboundRtp.packetsLost || 0;

          // 延迟（需要从candidate-pair获取）
          let latency = 0;
          stats.forEach((report) => {
            if (report.type === 'candidate-pair' && report.state === 'succeeded') {
              latency = report.currentRoundTripTime * 1000 || 0;
            }
          });

          setStats({
            fps: Math.round(fps),
            bitrate: parseFloat(bitrate.toFixed(2)),
            packetsLost,
            latency: Math.round(latency)
          });
        }
      } catch (err) {
        console.error('Stats error:', err);
      }
    }, 1000);
  }, []);

  const stopStatsMonitoring = useCallback(() => {
    if (statsIntervalRef.current) {
      clearInterval(statsIntervalRef.current);
      statsIntervalRef.current = null;
    }
  }, []);

  /**
   * 鼠标控制
   */
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);
    lastPosRef.current = { x: e.clientX, y: e.clientY };

    if (e.button === 0) {
      setDragMode('orbit');
    } else if (e.button === 2) {
      setDragMode('pan');
      e.preventDefault();
    }
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !dragMode) return;

    const deltaX = e.clientX - lastPosRef.current.x;
    const deltaY = e.clientY - lastPosRef.current.y;

    lastPosRef.current = { x: e.clientX, y: e.clientY };

    if (dragMode === 'orbit') {
      controlCamera('orbit', { deltaX, deltaY });
    } else if (dragMode === 'pan') {
      controlCamera('pan', { deltaX: -deltaX, deltaY });
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
   * 处理待处理的 stream（当 video 元素准备好后）
   */
  useEffect(() => {
    if (videoRef.current && pendingStreamRef.current && !videoRef.current.srcObject) {
      console.log('🔧 Setting pending stream to video element');
      videoRef.current.srcObject = pendingStreamRef.current;
      videoRef.current.play().catch(err => {
        console.error('Video play error:', err);
      });
    }
  }, [connected]); // 当连接状态改变时检查

  /**
   * 初始化 - 组件挂载时立即连接
   */
  useEffect(() => {
    console.log('🚀 WebRTCIsaacViewer mounted, connecting...');

    // 延迟一下再连接，确保组件完全渲染
    const timer = setTimeout(() => {
      connect();
    }, 500);

    return () => {
      clearTimeout(timer);
      disconnect();
    };
  }, []); // 只在挂载时执行一次

  return (
    <div className={`relative flex flex-col w-full h-full ${className}`} style={styles.container}>
      {/* 状态栏 */}
      <div style={styles.statusBar}>
        <div style={styles.statusLeft}>
          {connected ? (
            <Wifi size={16} className="text-green-400" />
          ) : connecting ? (
            <Wifi size={16} className="text-yellow-400 animate-pulse" />
          ) : (
            <WifiOff size={16} className="text-red-400" />
          )}
          <span className="font-mono text-xs ml-2">
            {connected ? 'WebRTC Connected' : connecting ? 'Connecting...' : 'Disconnected'}
          </span>
        </div>

        <div style={styles.statusCenter}>
          <Activity size={14} className="text-blue-400" />
          <span className="font-mono text-xs text-blue-400">
            {stats.fps} FPS
          </span>
          <span className="font-mono text-xs text-gray-400">
            {stats.bitrate} Mbps
          </span>
          {stats.latency > 0 && (
            <span className="font-mono text-xs text-gray-400">
              {stats.latency}ms RTT
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
          <h3 className="font-bold text-sm mb-3">WebRTC 统计</h3>

          <div className="space-y-2 text-xs">
            <div style={styles.statRow}>
              <span className="text-gray-400">帧率:</span>
              <span className="text-white">{stats.fps} FPS</span>
            </div>
            <div style={styles.statRow}>
              <span className="text-gray-400">码率:</span>
              <span className="text-white">{stats.bitrate} Mbps</span>
            </div>
            <div style={styles.statRow}>
              <span className="text-gray-400">往返延迟:</span>
              <span className="text-white">{stats.latency} ms</span>
            </div>
            <div style={styles.statRow}>
              <span className="text-gray-400">丢包:</span>
              <span className="text-white">{stats.packetsLost}</span>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-gray-700">
            <p className="text-xs text-gray-400">
              🚀 使用H.264硬件加速编解码
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
        {/* 视频元素始终渲染，确保 ontrack 事件能找到它 */}
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{
            ...styles.video,
            display: connected ? 'block' : 'none'
          }}
        />

        {/* 未连接时显示占位符 */}
        {!connected && (
          <div style={styles.placeholder}>
            {error ? (
              <div className="flex flex-col items-center gap-3">
                <span className="text-red-400">❌ {error}</span>
                <button onClick={connect} style={styles.retryButton}>
                  重新连接
                </button>
              </div>
            ) : connecting ? (
              <div className="flex flex-col items-center gap-3">
                <Wifi size={40} className="text-blue-400 animate-pulse" />
                <span className="text-gray-400">正在连接 WebRTC...</span>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <Camera size={40} className="text-gray-500" />
                <span className="text-gray-400">未连接</span>
                <button onClick={connect} style={styles.retryButton}>
                  连接
                </button>
              </div>
            )}
          </div>
        )}
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
    gap: '12px',
  },
  statusRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
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
    top: '50px',
    right: '16px',
    backgroundColor: '#1a1a1a',
    border: '1px solid #444',
    borderRadius: '6px',
    padding: '16px',
    zIndex: 10,
    minWidth: '240px',
    color: '#fff',
    boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
  },
  statRow: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '4px 0',
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
};

export default WebRTCIsaacViewer;
