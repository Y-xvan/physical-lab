"""  
启动脚本 - WebRTC 服务器  
修复路径问题：强制指定项目根目录  
"""  
import sys  
import asyncio  
import carb  
import omni.kit.app  
import os  
import importlib.util  

print("=" * 60)  
print("�� 启动 WebRTC 服务器（V3 全局变量修复版）")  
print("=" * 60)  

# ============================================================================  
# 1. �� 关键修改：手动指定项目路径  
# ============================================================================  
PROJECT_ROOT = '/home/zhiren/IsaacLab'  

print(f"�� 指定项目目录: {PROJECT_ROOT}")  

if not os.path.exists(PROJECT_ROOT):  
    print(f"❌ 错误: 项目目录不存在: {PROJECT_ROOT}")  
    raise FileNotFoundError(f"Project root not found: {PROJECT_ROOT}")  

# ============================================================================  
# 2. 全局服务器实例管理（修复版）
# ============================================================================  
# 使用模块级变量而非 globals() 字典操作
# 通过一个容器类来持久化存储服务器引用

class _ServerHolder:
    """服务器实例持有者 - 解决 Script Editor 环境下的全局变量问题"""
    instance = None
    monitor_subscription = None

# 将 holder 注册到 sys.modules 中，确保跨脚本执行持久化
_HOLDER_KEY = '__webrtc_server_holder__'
if _HOLDER_KEY not in sys.modules:
    import types
    holder_module = types.ModuleType(_HOLDER_KEY)
    setattr(holder_module, '_ServerHolder', _ServerHolder)
    sys.modules[_HOLDER_KEY] = holder_module
else:
    _ServerHolder = getattr(sys.modules[_HOLDER_KEY], '_ServerHolder')

async def _cleanup_old_server():
    """安全清理旧服务器实例"""
    if _ServerHolder.instance is not None:
        print("�� 检测到旧服务器实例，正在清理...")
        old_server = _ServerHolder.instance
        try:
            # 关闭所有 PeerConnection
            if hasattr(old_server, 'pcs') and old_server.pcs:
                print(f"   关闭 {len(old_server.pcs)} 个 WebRTC 连接...")
                close_tasks = [pc.close() for pc in old_server.pcs]
                await asyncio.gather(*close_tasks, return_exceptions=True)
            
            # 停止服务器
            await old_server.stop()
            print("   ✅ 旧服务器已停止")
        except Exception as e:
            print(f"   ⚠️ 清理时出错（可忽略）: {e}")
        finally:
            _ServerHolder.instance = None
    
    # 清理旧的监控订阅
    if _ServerHolder.monitor_subscription is not None:
        try:
            _ServerHolder.monitor_subscription = None
        except:
            pass

# ============================================================================  
# 3. 环境设置  
# ============================================================================  
if PROJECT_ROOT not in sys.path:  
    sys.path.insert(0, PROJECT_ROOT)  
    print(f"✅ 已添加路径到 sys.path")  

MODULE_NAME = 'isaac_webrtc_server'  
MODULE_FILE = str(os.path.join(PROJECT_ROOT, f'{MODULE_NAME}.py'))  
CONFIG_FILE = str(os.path.join(PROJECT_ROOT, 'config.py'))  

if not os.path.exists(MODULE_FILE):  
    raise FileNotFoundError(f"找不到 {MODULE_FILE}")  

if not os.path.exists(CONFIG_FILE):  
    raise FileNotFoundError(f"找不到 {CONFIG_FILE}")  

# ============================================================================  
# 4. 强制重载模块  
# ============================================================================  
print("♻️ 重载模块...")  

try:  
    # 清理已加载的模块缓存
    for mod_name in ['config', MODULE_NAME]:
        if mod_name in sys.modules:  
            del sys.modules[mod_name]  

    # 导入 config  
    import config  
    print(f"   ✅ Config 加载成功")  
    print(f"      视频设置: {config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}")  
    print(f"      端口设置: HTTP={config.HTTP_PORT}, WS={config.WS_PORT}")  

    # 动态导入 Server 模块  
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_FILE)  
    if spec is None:
        raise FileNotFoundError(f"Could not create spec for {MODULE_FILE}")
    module = importlib.util.module_from_spec(spec)  
    sys.modules[MODULE_NAME] = module  
    spec.loader.exec_module(module)  
    WebRTCServer = module.WebRTCServer  
    print(f"   ✅ Server 模块导入成功")  

except Exception as e:  
    print(f"❌ 模块导入失败: {e}")  
    import traceback  
    traceback.print_exc()  
    raise  

# ============================================================================  
# 5. 启动服务器  
# ============================================================================  
async def start_server():
    """主启动流程"""
    # 先清理旧实例
    await _cleanup_old_server()
    
    print("\n�� 正在初始化新服务器...")  
    try:  
        # 创建新服务器实例并存储到 holder
        server = WebRTCServer(  
            host=config.HTTP_HOST,  
            http_port=config.HTTP_PORT,  
            ws_port=config.WS_PORT  
        )  
        
        await server.start()  
        
        # 保存到持久化 holder
        _ServerHolder.instance = server
        
        print("\n" + "=" * 60)  
        print("✅ WebRTC 服务器启动成功！")  
        print("=" * 60)  
        print(f"   WebRTC信令: http://{config.HTTP_HOST}:{config.HTTP_PORT}/offer")  
        print(f"   WebSocket控制: ws://{config.HTTP_HOST}:{config.WS_PORT}/")  
        print("=" * 60)  
        
        # 启动监控  
        _setup_monitor(server)  
        
    except Exception as e:  
        print(f"❌ 启动失败: {e}")  
        import traceback  
        traceback.print_exc()
        _ServerHolder.instance = None

# ============================================================================  
# 6. 轻量级监控  
# ============================================================================  
def _setup_monitor(server_instance):  
    """状态监控"""  
    check_count = [0]  # 使用列表来避免闭包问题
    
    def on_update(event):
        check_count[0] += 1
        # 每 10 秒打印一次状态 (假设 60fps, 600帧)  
        if check_count[0] % 600 == 0:
            if server_instance.video_track:  
                track = server_instance.video_track  
                if not track.use_replicator:  
                    print(f"⚠️ [Monitor] Replicator 未启用 | 分辨率: {track.width}x{track.height}")
    
    app = omni.kit.app.get_app()  
    subscription = app.get_update_event_stream().create_subscription_to_pop(on_update)
    _ServerHolder.monitor_subscription = subscription
    print("�� 状态监控已挂载")  

# ============================================================================  
# 7. 提供便捷的停止函数
# ============================================================================  
async def stop_server():
    """手动停止服务器的便捷函数"""
    await _cleanup_old_server()
    print("✅ 服务器已停止")

def get_server():
    """获取当前服务器实例"""
    return _ServerHolder.instance

# ============================================================================  
# 8. 执行启动
# ============================================================================  
asyncio.ensure_future(start_server())
