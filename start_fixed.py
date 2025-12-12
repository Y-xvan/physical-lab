"""
修复版启动脚本 - WebRTC 服务器 + 自动视频修复
使用 importlib 强制重新加载模块

在 Isaac Sim Script Editor 中运行此脚本
"""
import sys
import asyncio
import carb
import omni.kit.app
import omni.replicator.core as rep
import omni.kit.viewport.utility as vp_util
import os
import shutil
import importlib
import importlib.util

print("=" * 60)
print("🚀 启动 WebRTC 服务器（修复版）")
print("=" * 60)

# ============================================================================
# 1. 停止旧服务器（如果有）
# ============================================================================
if 'server' in globals():
    print("\n🛑 检测到旧服务器，正在停止...")
    try:
        old_server = globals()['server']
        if hasattr(old_server, 'pcs'):
            for pc in list(old_server.pcs):
                try:
                    pc.close()
                except:
                    pass
            old_server.pcs.clear()
        asyncio.ensure_future(old_server.stop())
        del globals()['server']
        print("✅ 旧服务器已停止")
    except Exception as e:
        print(f"⚠️ 停止旧服务器时出错: {e}")

# ============================================================================
# 2. 环境检查和路径设置
# ============================================================================
print("\n🔍 检查环境...")

# 设置模块路径
MODULE_DIR = '/home/zhiren/IsaacLab'
MODULE_NAME = 'isaac_webrtc_server'
MODULE_FILE = f'{MODULE_DIR}/{MODULE_NAME}.py'

print(f"   模块目录: {MODULE_DIR}")
print(f"   模块文件: {MODULE_FILE}")
print(f"   当前工作目录: {os.getcwd()}")

# 检查文件是否存在
if not os.path.exists(MODULE_FILE):
    print(f"❌ 错误: 模块文件不存在: {MODULE_FILE}")
    raise FileNotFoundError(f"Module file not found: {MODULE_FILE}")

print(f"✅ 模块文件存在")
print(f"   文件大小: {os.path.getsize(MODULE_FILE)} 字节")

# ============================================================================
# 3. 清除缓存
# ============================================================================
print("\n🧹 清除缓存...")

# 清除 sys.modules
if MODULE_NAME in sys.modules:
    del sys.modules[MODULE_NAME]
    print(f"   ✅ 已从 sys.modules 删除 {MODULE_NAME}")

# 清除 __pycache__
pycache_dir = f'{MODULE_DIR}/__pycache__'
if os.path.exists(pycache_dir):
    try:
        shutil.rmtree(pycache_dir)
        print(f"   ✅ 已删除缓存目录: {pycache_dir}")
    except Exception as e:
        print(f"   ⚠️ 删除缓存失败: {e}")

# 清除 .pyc 文件
pyc_file = f'{MODULE_DIR}/{MODULE_NAME}.pyc'
if os.path.exists(pyc_file):
    try:
        os.remove(pyc_file)
        print(f"   ✅ 已删除 .pyc 文件")
    except Exception as e:
        print(f"   ⚠️ 删除 .pyc 失败: {e}")

# ============================================================================
# 4. 使用 importlib 导入模块
# ============================================================================
print("\n📦 导入模块...")

# 添加路径到 sys.path
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)
    print(f"   ✅ 已添加路径: {MODULE_DIR}")

try:
    # 使用 importlib.util 导入模块
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_FILE)
    if spec is None:
        raise ImportError(f"Cannot create module spec for {MODULE_FILE}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)

    print(f"   ✅ 成功导入 {MODULE_NAME}")

    # 获取 WebRTCServer 类
    WebRTCServer = module.WebRTCServer

    # 验证类
    import inspect
    sig = inspect.signature(WebRTCServer.__init__)
    params = list(sig.parameters.keys())
    print(f"   ✅ WebRTCServer 参数: {params}")

    if 'ws_port' not in params:
        raise ValueError("WebRTCServer 缺少 ws_port 参数！请检查文件是否正确更新。")

    print(f"   ✅ ws_port 参数存在")

except Exception as e:
    print(f"❌ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    raise

# ============================================================================
# 5. 创建服务器
# ============================================================================
print("\n🔧 创建 WebRTC + WebSocket 服务器...")
try:
    server = WebRTCServer(host="0.0.0.0", http_port=8080, ws_port=30000)
    print("✅ 服务器创建成功")
except Exception as e:
    print(f"❌ 创建服务器失败: {e}")
    import traceback
    traceback.print_exc()
    raise

# ============================================================================
# 6. Replicator 初始化函数（改进版）
# ============================================================================
async def init_replicator_improved(track, max_retries=3):
    """
    改进的 Replicator 初始化函数
    - 多次重试
    - 更详细的日志
    - 更长的等待时间
    """
    print("\n" + "=" * 60)
    print("🔧 初始化 Replicator（改进版）")
    print("=" * 60)

    retry_delay = 2.0

    for attempt in range(1, max_retries + 1):
        print(f"\n🔄 尝试 {attempt}/{max_retries}")
        print("-" * 40)

        try:
            # 等待足够时间让视口稳定
            print(f"   ⏳ 等待 {retry_delay} 秒让 Isaac Sim 稳定...")
            await asyncio.sleep(retry_delay)

            # 获取当前相机
            print("   🔍 获取视口...")
            viewport = vp_util.get_active_viewport()
            if not viewport:
                print("   ❌ 无法获取视口")
                if attempt < max_retries:
                    continue
                return False

            print("   ✅ 视口获取成功")

            print("   🔍 获取相机路径...")
            camera_path = viewport.get_active_camera()
            if not camera_path:
                print("   ❌ 无法获取相机路径")
                if attempt < max_retries:
                    continue
                return False

            print(f"   ✅ 相机路径: {camera_path}")

            # 清理旧资源
            if hasattr(track, 'render_product') and track.render_product:
                print("   🧹 清理旧的 Render Product...")
                try:
                    rep.destroy.render_product(track.render_product)
                except:
                    pass

            # 创建 render product
            print(f"   🎬 创建 Render Product ({track.width}x{track.height})...")
            track.render_product = rep.create.render_product(
                camera_path,
                (track.width, track.height)
            )
            print("   ✅ Render product 创建成功")

            # 创建 RGB annotator
            print("   🎨 创建 RGB annotator...")
            track.rgb_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
            track.rgb_annotator.attach([track.render_product])
            print("   ✅ RGB annotator 创建成功")

            # 启用 Replicator
            track.use_replicator = True
            print("   ✅ Replicator 已启用")

            # 测试帧捕获
            print("\n   🧪 测试帧捕获...")
            await rep.orchestrator.step_async()
            data = track.rgb_annotator.get_data()

            if data is not None:
                print(f"   ✅ 成功捕获测试帧: {data.shape}")
                print(f"   数据范围: min={data.min()}, max={data.max()}")

                if data.max() == 0:
                    print("   ⚠️ 警告: 捕获的帧是全黑的（可能是场景问题）")
                else:
                    print("   ✅ 帧数据正常")

                print("\n" + "=" * 60)
                print("✅ Replicator 初始化成功！")
                print("=" * 60)
                return True
            else:
                print("   ❌ 帧捕获测试失败: 返回 None")
                if attempt < max_retries:
                    continue
                return False

        except Exception as e:
            print(f"   ❌ 初始化失败: {e}")
            import traceback
            print(traceback.format_exc())
            if attempt < max_retries:
                continue
            return False

    return False

# ============================================================================
# 7. 启动和验证函数
# ============================================================================
async def start_and_verify():
    """启动服务器并验证"""
    print("\n🚀 启动服务器...")
    try:
        await server.start()
        print("✅ 服务器启动完成！")

        # 等待 Isaac Sim 稳定
        print("\n⏳ 等待 Isaac Sim 稳定...")
        await asyncio.sleep(2.0)

        # 检查视频轨道
        if not server.video_track:
            print("\n" + "=" * 60)
            print("📋 服务器状态：等待 WebRTC 连接")
            print("=" * 60)
            print("\n⚠️ 视频轨道尚未创建（这是正常的）")
            print("   视频轨道将在首次 WebRTC 连接时创建")
            print("\n📝 接下来的步骤：")
            print("   1. 监控器已启动，会自动检测视频轨道创建")
            print("   2. 在浏览器中打开前端并连接")
            print("   3. 连接成功后，监控器会自动修复 Replicator")
            print("=" * 60)
            return True

        # 如果视频轨道已存在（不太可能），直接初始化
        track = server.video_track
        print("\n📹 视频轨道信息:")
        print(f"   分辨率: {track.width}x{track.height}")
        print(f"   帧率: {track.fps}")
        print(f"   使用 Replicator: {track.use_replicator}")

        if not track.use_replicator:
            print("\n⚠️ Replicator 未启用，开始初始化...")
            success = await init_replicator_improved(track)
            return success

        return True

    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        print(traceback.format_exc())
        return False

# ============================================================================
# 8. 执行启动任务
# ============================================================================
print("\n🔧 调度启动任务...")
task = asyncio.ensure_future(start_and_verify())

def check_startup():
    if task.done():
        try:
            result = task.result()
            if result:
                print("\n" + "=" * 60)
                print("✅ WebRTC + WebSocket 服务器已就绪！")
                print("=" * 60)
                print("\n📝 使用说明:")
                print("   1. 在浏览器打开前端: http://<远程主机IP>:5173")
                print("   2. 点击 'Connect' 连接服务器")
                print("   3. 选择实验，场景会自动加载")
                print("   4. 使用控制按钮控制仿真")
                print("\n🌐 服务器信息:")
                print(f"   HTTP/WebRTC: http://0.0.0.0:8080")
                print(f"   WebSocket: ws://0.0.0.0:30000")
                print("=" * 60)

                # 启动后台监控（在启动成功后）
                setup_video_monitor()
            else:
                print("\n" + "=" * 60)
                print("❌ 服务器启动失败或验证未通过")
                print("=" * 60)
        except Exception as e:
            print(f"❌ 启动任务异常: {e}")
            import traceback
            traceback.print_exc()
        return False
    return True

app = omni.kit.app.get_app()
sub = app.get_update_event_stream().create_subscription_to_pop(
    lambda e: check_startup() if not task.done() else None
)

print("\n💡 提示：服务器已设置为全局变量 'server'")
print("=" * 60)

# ============================================================================
# 9. 改进的视频轨道监控器
# ============================================================================
class ImprovedVideoTrackMonitor:
    """改进的视频轨道监控器"""

    def __init__(self, server_instance):
        self.server = server_instance
        self.check_count = 0
        self.max_checks = 600  # 检查 600 次（约60秒）
        self.fixed = False
        self.monitoring = False
        self.last_log_time = 0
        print("\n🔍 改进的视频轨道监控器已初始化")

    def start(self):
        """开始监控"""
        if self.monitoring:
            return

        self.monitoring = True
        print("✅ 开始监控视频轨道（每 3 帧检查一次）...")
        print("   当浏览器连接并创建视频轨道时，会自动修复 Replicator")

        app = omni.kit.app.get_app()
        self.sub = app.get_update_event_stream().create_subscription_to_pop(
            lambda e: self.check_and_fix()
        )

    def check_and_fix(self):
        """检查并修复视频轨道"""
        if self.fixed or not self.monitoring:
            return True

        self.check_count += 1

        # 每 3 帧检查一次（更频繁）
        if self.check_count % 3 != 0:
            return True

        try:
            # 每 300 帧（约10秒）输出一次进度
            import time
            current_time = time.time()
            if current_time - self.last_log_time >= 10:
                elapsed = self.check_count // 30
                print(f"   ⏳ 等待视频轨道创建... ({elapsed}秒)")
                self.last_log_time = current_time

            # 检查视频轨道
            if self.server.video_track is not None:
                track = self.server.video_track

                print(f"\n" + "=" * 60)
                print(f"✅ 检测到视频轨道！")
                print(f"   分辨率: {track.width}x{track.height}")
                print(f"   Replicator 状态: {track.use_replicator}")
                print("=" * 60)

                if not track.use_replicator:
                    print("\n🔧 Replicator 未启用，开始自动修复...")

                    # 创建修复任务
                    fix_task = asyncio.ensure_future(init_replicator_improved(track))

                    # 等待修复完成
                    def check_fix():
                        if fix_task.done():
                            try:
                                success = fix_task.result()
                                if success:
                                    print("\n" + "=" * 60)
                                    print("✅ 自动修复成功！")
                                    print("   视频流现在应该可以正常工作了")
                                    print("   你可以在前端看到视频画面")
                                    print("=" * 60)
                                else:
                                    print("\n" + "=" * 60)
                                    print("⚠️ 自动修复失败")
                                    print("   请检查日志查看具体错误")
                                    print("=" * 60)
                            except Exception as e:
                                print(f"❌ 修复任务异常: {e}")

                            self.fixed = True
                            self.monitoring = False
                            return False
                        return True

                    # 创建检查任务的订阅
                    app = omni.kit.app.get_app()
                    fix_sub = app.get_update_event_stream().create_subscription_to_pop(
                        lambda e: check_fix()
                    )

                    # 停止当前监控
                    return False
                else:
                    print("✅ Replicator 已启用，无需修复")
                    print("   视频流应该已经可以正常工作了！")
                    self.fixed = True
                    self.monitoring = False
                    return False

            # 超时检查
            if self.check_count >= self.max_checks * 3:
                print("\n" + "=" * 60)
                print("⚠️ 监控超时（60秒）")
                print("   视频轨道可能尚未创建")
                print("\n可能的原因：")
                print("   1. 前端还没有连接到服务器")
                print("   2. WebRTC 连接建立失败")
                print("\n建议：")
                print("   1. 检查前端是否成功连接")
                print("   2. 检查浏览器控制台是否有错误")
                print("   3. 确认服务器地址正确")
                print("=" * 60)
                self.monitoring = False
                return False

        except Exception as e:
            print(f"⚠️ 监控出错: {e}")
            import traceback
            print(traceback.format_exc())

        return True

# 创建全局监控器实例
video_monitor = ImprovedVideoTrackMonitor(server)

def setup_video_monitor():
    """设置视频监控器（在服务器启动成功后调用）"""
    video_monitor.start()

print("✅ 改进的视频轨道监控器已准备就绪")
print("=" * 60)
