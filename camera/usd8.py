"""
Isaac Sim 相机设置脚本 - 实验8 (Shadow Hand Dexterity)
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

    # 设置位置 - 适合观察灵巧手
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(0.15, 0.20, 0.15))

    # 设置旋转（四元数 w, x, y, z）
    orient_op = xform.AddOrientOp()
    orient_op.Set(Gf.Quatd(0.94, 0.06, 0.28, 0.16))

    # 设置裁剪范围
    camera.GetClippingRangeAttr().Set(Gf.Vec2f(0.01, 100000.0))

    # 设置焦距
    camera.GetFocalLengthAttr().Set(50.0)

    print("✓ 相机设置已应用 - 实验8!")

# 运行设置
set_camera()
