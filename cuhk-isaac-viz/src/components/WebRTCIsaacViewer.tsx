import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Camera, Wifi, WifiOff, Settings, Activity, RefreshCw } from 'lucide-react';

interface WebRTCIsaacViewerProps {
  serverUrl?: string;
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
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<ConnectionStats>({ fps: 0, bitrate: 0, packetsLost: 0, latency: 0 });

  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const statsIntervalRef = useRef<number | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null); // 引用 AbortController
  const connectionAttemptRef = useRef(false);

  // 鼠标控制状态
  const [isDragging, setIsDragging] = useState(false);
  const [dragMode, setDragMode] = useState<'orbit' | 'pan' | null>(null);
  const lastPosRef = useRef({ x: 0, y: 0 });

  const disconnect = useCallback(() => {
    // 1. 清理统计定时器
    if (statsIntervalRef.current) {
      clearInterval(statsIntervalRef.current);
      statsIntervalRef.current = null;
    }
    
    // 2. 中止正在进行的 Fetch 请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // 3. 关闭 PeerConnection
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    // 4. 清理视频源
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setConnected(false);
    setConnecting(false);
    connectionAttemptRef.current = false;
  }, []);

  const connect = useCallback(async () => {
    if (connectionAttemptRef.current || connected) return;
    connectionAttemptRef.current = true;

    setConnecting(true);
    setError(null);

    // 创建新的 AbortController
    const controller = new AbortController();
    abortControllerRef.current = controller;

    // ⏳ 延长超时时间到 20 秒 (Isaac Sim 初始化 Replicator 可能很慢)
    const timeoutId = setTimeout(() => {
      if (abortControllerRef.current === controller) {
        controller.abort();
        setError('Connection timed out (Server is busy)');
      }
    }, 20000);

    try {
      console.log(' Connecting to WebRTC server:', serverUrl);

      const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
      });
      pcRef.current = pc;

      pc.onconnectionstatechange = () => {
        console.log(' Connection state:', pc.connectionState);
        if (pc.connectionState === 'connected') {
          setConnected(true);
          setConnecting(false);
          startStatsMonitoring();
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
          setConnected(false);
          // 仅在非断开连接操作时报错
          if (connectionAttemptRef.current) {
             setError('Connection lost (ICE Failed)');
          }
        }
      };

      pc.ontrack = (event) => {
        console.log(' Received video track');
        if (videoRef.current && event.streams[0]) {
          const stream = event.streams[0];
          if (videoRef.current.srcObject !== stream) {
            videoRef.current.srcObject = stream;
            videoRef.current.play().catch(e => {
              // 忽略被中断的错误
              if (e.name !== 'AbortError') console.error('Video play error:', e);
            });
          }
        }
      };

      pc.addTransceiver('video', { direction: 'recvonly' });

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const response = await fetch(`${serverUrl}/offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sdp: pc.localDescription?.sdp, type: pc.localDescription?.type }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const answer = await response.json();
      await pc.setRemoteDescription(new RTCSessionDescription(answer));

      if (usdPath) {
        setTimeout(() => loadUSD(usdPath), 1000);
      }

    } catch (err: any) {
      clearTimeout(timeoutId);
      
      // 区分超时中断和用户手动中断
      if (err.name === 'AbortError') {
        console.warn(' Connection aborted or timed out');
      } else {
        console.error('❌ Connection error:', err);
        setError(err instanceof Error ? err.message : 'Connection failed');
      }
      
      disconnect();
    } finally {
      connectionAttemptRef.current = false;
      setConnecting(false);
      abortControllerRef.current = null;
    }
  }, [serverUrl, usdPath, disconnect]);

  const loadUSD = useCallback(async (path: string) => {
    try {
      console.log(' Loading USD:', path);
      await fetch(`${serverUrl}/load_usd`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ usd_path: path })
      });
    } catch (err) {
      console.error('USD Load error:', err);
    }
  }, [serverUrl]);

  const controlCamera = useCallback(async (action: string, params: any) => {
    try {
      await fetch(`${serverUrl}/camera`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...params })
      });
    } catch (err) { }
  }, [serverUrl]);

  const startStatsMonitoring = () => {
    if (statsIntervalRef.current) return;
    statsIntervalRef.current = window.setInterval(async () => {
      if (!pcRef.current) return;
      try {
        const stats = await pcRef.current.getStats();
        let videoStats: any = null;
        stats.forEach(report => {
          if (report.type === 'inbound-rtp' && report.kind === 'video') videoStats = report;
        });

        if (videoStats) {
          setStats({
            fps: Math.round(videoStats.framesPerSecond || 0),
            bitrate: parseFloat(((videoStats.bytesReceived * 8) / 1000000).toFixed(2)),
            packetsLost: videoStats.packetsLost || 0,
            latency: 0
          });
        }
      } catch (e) { }
    }, 1000);
  };

  // 鼠标交互
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    lastPosRef.current = { x: e.clientX, y: e.clientY };
    setDragMode(e.button === 0 ? 'orbit' : e.button === 2 ? 'pan' : null);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || !dragMode) return;
    const deltaX = e.clientX - lastPosRef.current.x;
    const deltaY = e.clientY - lastPosRef.current.y;
    lastPosRef.current = { x: e.clientX, y: e.clientY };
    
    if (dragMode === 'orbit') controlCamera('orbit', { deltaX, deltaY });
    else if (dragMode === 'pan') controlCamera('pan', { deltaX: -deltaX, deltaY });
  };

  useEffect(() => {
    const timer = setTimeout(() => connect(), 100);
    return () => {
      clearTimeout(timer);
      disconnect();
    };
  }, []);

  return (
    <div className={`relative flex flex-col w-full h-full bg-black rounded-lg overflow-hidden ${className}`}>
      {/* 顶部状态栏 */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 text-xs font-mono">
        <div className="flex items-center gap-2">
          {connected ? <Wifi size={14} className="text-green-500"/> : <WifiOff size={14} className="text-red-500"/>}
          <span className={connected ? 'text-green-500' : 'text-red-500'}>
            {connected ? 'ONLINE' : connecting ? 'CONNECTING...' : 'OFFLINE'}
          </span>
        </div>
        <div className="flex items-center gap-4 text-gray-400">
          <span>{stats.fps} FPS</span>
          <span>{stats.bitrate} Mbps</span>
          <button onClick={() => { disconnect(); setTimeout(connect, 500); }} className="hover:text-white" title="Reconnect">
            <RefreshCw size={12}/>
          </button>
        </div>
      </div>

      {/* 视频区域 */}
      <div 
        className="flex-1 relative overflow-hidden cursor-move"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={() => setIsDragging(false)}
        onMouseLeave={() => setIsDragging(false)}
        onWheel={(e) => controlCamera('zoom', { delta: e.deltaY > 0 ? 1 : -1 })}
        onContextMenu={(e) => e.preventDefault()}
      >
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="w-full h-full object-contain pointer-events-none"
        />
        
        {(!connected && !connecting) && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-900/80 text-gray-400">
            <Activity size={48} className="mb-4 opacity-50"/>
            <p>{error || 'Connection Failed'}</p>
            <button 
              onClick={() => connect()}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-500 transition"
            >
              Retry Connection
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

  export default WebRTCIsaacViewer;