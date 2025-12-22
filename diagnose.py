"""
Replicator 诊断脚本 - 检查为什么没有画面
"""
import carb
import omni.usd
import omni.kit.viewport.utility as vp_util
import asyncio

print("=" * 60)
print("🔍 Replicator 诊断开始")
print("=" * 60)

# 1. 检查 Stage
stage = omni.usd.get_context().get_stage()
if stage is None:
    print("❌ [问题1] 没有打开的 USD Stage！")
    print("   解决: 请先打开一个 USD 场景文件")
else:
    print(f"✅ Stage 已加载: {stage.GetRootLayer().identifier}")

# 2. 检查 Viewport
viewport = vp_util.get_active_viewport()
if viewport is None:
    print("❌ [问题2] 没有活动的 Viewport！")
else:
    print(f"✅ Viewport 存在")
    
    # 3. 检查相机
    camera_path = viewport.get_active_camera()
    if not camera_path:
        print("❌ [问题3] Viewport 没有激活的相机！")
    else:
        print(f"✅ 活动相机: {camera_path}")
        
        # 检查相机 prim 是否有效
        if stage:
            cam_prim = stage.GetPrimAtPath(camera_path)
            if cam_prim and cam_prim.IsValid():
                print(f"✅ 相机 Prim 有效")
            else:
                print(f"❌ [问题4] 相机 Prim 无效: {camera_path}")

# 4. 检查 Replicator
try:
    import omni.replicator.core as rep
    print("✅ Replicator 模块可用")
    
    # 5. 尝试创建 render product
    if viewport and camera_path:
        print("\n🔧 尝试创建 Render Product...")
        
        try:
            rp = rep.create.render_product(camera_path, (1280, 720))
            print(f"✅ Render Product 创建成功: {rp}")
            
            # 6. 创建 annotator
            rgb_annot = rep.AnnotatorRegistry.get_annotator("rgb")
            rgb_annot.attach([rp])
            print("✅ RGB Annotator 已附加")
            
            # 7. 尝试获取数据
            async def test_capture():
                print("\n📸 尝试捕获帧...")
                for i in range(5):
                    await rep.orchestrator.step_async()
                    data = rgb_annot.get_data()
                    
                    if data is None:
                        print(f"   帧 {i+1}: ❌ 返回 None")
                    elif data.size == 0:
                        print(f"   帧 {i+1}: ❌ 返回空数组")
                    else:
                        print(f"   帧 {i+1}: ✅ 成功! shape={data.shape}, dtype={data.dtype}")
                        print(f"            min={data.min()}, max={data.max()}")
                        return True
                    
                    await asyncio.sleep(0.1)
                
                return False
            
            asyncio.ensure_future(test_capture())
            
        except Exception as e:
            print(f"❌ [问题5] 创建 Render Product 失败: {e}")
            import traceback
            traceback.print_exc()
            
except ImportError as e:
    print(f"❌ [问题6] Replicator 模块导入失败: {e}")

# 8. 检查 Fabric Scene Delegate (FSD) 设置
print("\n🔧 检查渲染设置...")
try:
    import carb.settings
    settings = carb.settings.get_settings()
    
    # FSD 可能导致 Replicator 返回空数据
    fsd_enabled = settings.get("/app/useFabricSceneDelegate")
    print(f"   Fabric Scene Delegate: {'启用' if fsd_enabled else '禁用'}")
    
    if fsd_enabled:
        print("   ⚠️ FSD 启用可能导致 Replicator 问题！")
        print("   解决: 在 Isaac Sim 设置中禁用 Fabric Scene Delegate")
        
except Exception as e:
    print(f"   无法检查设置: {e}")

print("\n" + "=" * 60)
print("🔍 诊断完成")
print("=" * 60)