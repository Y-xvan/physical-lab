"""
Isaac Sim 相机设置脚本 - 实验2 (Franka Arm Pick & Place)
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

    # 设置位置
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(1.2911285411046918, 4.989581325130292, 2.46158263470752))

    # 设置旋转（欧拉角）
    rotate_op = xform.AddRotateXYZOp()
    rotate_op.Set(Gf.Vec3f(65.40235137939453, -3.1805548456444524e-14, 178.0237579345703))

    # 设置裁剪范围（近裁剪面, 远裁剪面）
    camera.GetClippingRangeAttr().Set(Gf.Vec2f(0.009999999776482582, 10000000.0))

    # 设置焦距
    camera.GetFocalLengthAttr().Set(18.14756202697754)

    print("✓ 相机设置已应用!")
    print("  位置: (1.2911285411046918, 4.989581325130292, 2.46158263470752)")


    print("✓ 相机设置已应用 - 实验2!")

# 运行设置
set_camera()
