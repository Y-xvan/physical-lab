"""
Isaac Sim 相机设置脚本 - 实验6 (Soft Body Deformation)
"""

import omni.usd
from pxr import UsdGeom, Gf

def set_camera():
    stage = omni.usd.get_context().get_stage()
    camera_prim = stage.GetPrimAtPath("/OmniverseKit_Persp")

    if not camera_prim.IsValid():
        print("相机未找到!")
        return

    camera = UsdGeom.Camera(camera_prim)
    xform = UsdGeom.Xformable(camera_prim)

    # 清除现有变换操作，重新设置
    xform.ClearXformOpOrder()

    # 设置位置 - 适合观察软体变形
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(0.25, 0.35, 0.2))

    # 设置旋转（四元数 w, x, y, z）
    orient_op = xform.AddOrientOp()
    orient_op.Set(Gf.Quatd(0.92, 0.08, 0.32, 0.18))

    # 设置裁剪范围
    camera.GetClippingRangeAttr().Set(Gf.Vec2f(0.01, 100000.0))

    # 设置焦距
    camera.GetFocalLengthAttr().Set(50.0)

    print("✓ 相机设置已应用 - 实验6!")

# 运行设置
set_camera()
