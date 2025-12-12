"""
Isaac Sim 相机设置脚本 - 实验1（角动量守恒）
自动获取当前活动相机并应用配置
"""

import omni.usd
from pxr import UsdGeom, Gf
import omni.kit.viewport.utility as vp_util

def set_my_camera():
    stage = omni.usd.get_context().get_stage()

    # 自动获取当前活动的相机路径
    try:
        viewport = vp_util.get_active_viewport()
        if viewport:
            camera_path = viewport.get_active_camera()
            if camera_path:
                print(f"📷 使用活动相机: {camera_path}")
            else:
                camera_path = "/OmniverseKit_Persp"
                print(f"⚠️ 无法获取活动相机路径，使用默认: {camera_path}")
        else:
            camera_path = "/OmniverseKit_Persp"
            print(f"⚠️ 无法获取viewport，使用默认相机: {camera_path}")
    except Exception as e:
        camera_path = "/OmniverseKit_Persp"
        print(f"⚠️ 获取相机时出错: {e}，使用默认: {camera_path}")

    camera_prim = stage.GetPrimAtPath(camera_path)

    if not camera_prim.IsValid():
        print(f"❌ 相机未找到: {camera_path}")
        print("   请检查相机路径是否正确")
        return
    
    camera = UsdGeom.Camera(camera_prim)
    xform = UsdGeom.Xformable(camera_prim)

    # 获取或创建变换操作（不清除现有顺序）
    # 获取现有的 translate 操作，如果不存在则创建
    xform_ops = xform.GetOrderedXformOps()
    translate_op = None
    rotate_op = None

    for op in xform_ops:
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            translate_op = op
        elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            rotate_op = op

    # 如果操作不存在，则创建
    if not translate_op:
        translate_op = xform.AddTranslateOp()
    if not rotate_op:
        rotate_op = xform.AddRotateXYZOp()

    # 设置位置
    translate_op.Set(Gf.Vec3d(3.4582791421153924, 4.153730593106229, 2.506881024690692))

    # 设置旋转（欧拉角）
    rotate_op.Set(Gf.Vec3f(67.56452178955078, -3.816665747010707e-14, 136.9764404296875))

    # 设置裁剪范围（近裁剪面, 远裁剪面）
    camera.GetClippingRangeAttr().Set(Gf.Vec2f(0.009999999776482582, 10000000.0))

    # 设置焦距
    camera.GetFocalLengthAttr().Set(18.14756202697754)

    print("✅ 实验1相机设置已应用!")
    print(f"   相机路径: {camera_path}")
    print(f"   位置: (3.458, 4.154, 2.507)")
    print(f"   旋转: (67.56°, 0°, 136.98°)")
    print(f"   焦距: 18.15mm")

# 运行设置
set_my_camera()