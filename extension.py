# extension.py
from omni.isaac.core.utils.extensions import enable_extension
enable_extension()

import carb
import asyncio
import threading
import sys
import time
import omni.ext

# 日志函数
def log(msg, level="info"):
    timestamp = asyncio.get_event_loop().time()
    formatted = f"[{timestamp:.2f}] {msg}"
    if level == "info":
        carb.log_info(formatted)
    elif level == "warn":
        carb.log_warn(formatted)
    elif level == "error":
        carb.log_error(formatted)
    print(formatted)

class WebSocketServerExtension:
    def __init__(self):
        self._server_task = None
        self._stop_event = asyncio.Event()
        self.port = 30000

    async def _handle_client(self, websocket, path):
        log(f"Client connected: {websocket.remote_address}")
        try:
            welcome = '{"type": "connected", "message": "Welcome to Isaac Sim"}'
            await websocket.send(welcome)
            log("Sent welcome message")

            async for message in websocket:
                log(f"Received: {message}")
                response = f'{{"type": "echo", "received": {message}, "timestamp": {time.time()}}}'
                await websocket.send(response)
        except Exception as e:
            log(f"Client error: {e}", "error")
        finally:
            log("Client disconnected")

    async def _start_server(self):
        try:
            import websockets
        except ImportError:
            log("❌ Please install 'websockets': pip install websockets", "error")
            return

        try:
            log(f"Starting WebSocket server on ws://0.0.0.0:{self.port}")
            server = await websockets.serve(
                self._handle_client,
                "0.0.0.0",
                self.port,
                ping_interval=None
            )
            log(f"✅ WebSocket server running! Connect via ws://<your-ip>:{self.port}")
            log(f"🌐 Example: ws://10.20.5.3:{self.port}")

            # 等待停止信号
            await self._stop_event.wait()
            log("Shutting down server...")
        except Exception as e:
            log(f"💥 Failed to start server: {e}", "error")

    def start(self):
        """由 Omniverse 在 on_startup 时调用"""
        log("Starting WebSocket Server Extension...")
        # 创建任务但不 await —— 让它在后台运行
        self._server_task = asyncio.ensure_future(self._start_server())

    def shutdown(self):
        """由 Omniverse 在 on_shutdown 时调用"""
        log("Shutting down WebSocket server...")
        if self._server_task:
            self._stop_event.set()
            self._server_task.cancel()


# --- 全局实例 ---
_ext_instance = None

class Extension(omni.ext.IExt):
    def on_startup(self, ext_id):
        global _ext_instance
        log("WebSocket Extension Startup", "info")
        _ext_instance = WebSocketServerExtension()
        _ext_instance.start()

    def on_shutdown(self):
        global _ext_instance
        if _ext_instance:
            _ext_instance.shutdown()
        _ext_instance = None
        log("WebSocket Extension Shutdown", "info")
