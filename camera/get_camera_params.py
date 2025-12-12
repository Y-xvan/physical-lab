"""
Isaac Sim 相机参数获取脚本
在 Window > Script Editor 中运行此脚本，获取当前相机的所有参数
然后可以复制这些参数到对应的 usdX.py 文件中
"""

import omni.usd
import omni.timeline
from pxr import UsdGeom, Gf
import omni.kit.viewport.utility as vp_util
import math

def get_current_camera_params():
    """获取当前相机的所有参数并验证"""

    print("=" * 80)
    print("📷 当前相机参数 [详细调试版本]")
    print("=" * 80)

    # 获取当前stage
    stage = omni.usd.get_context().get_stage()
    if not stage:
        print("❌ 未找到stage!")
        return

    print(f"✅ Stage已加载")
    print(f"   时间码: {stage.GetTimeCodesPerSecond()} fps")
    current_time = omni.timeline.get_timeline_interface().get_current_time()
    print(f"   当前时间: {current_time}")
    print()

    # 获取当前活动的viewport和相机
    viewport_api = vp_util.get_active_viewport()
    if not viewport_api:
        print("❌ 未找到活动的viewport!")
        return

    print("✅ Viewport信息:")
    try:
        # 尝试获取viewport分辨率
        viewport_window = viewport_api.viewport_window
        if viewport_window:
            width = viewport_window.get_width()
            height = viewport_window.get_height()
            print(f"   分辨率: {width} x {height}")
            print(f"   宽高比: {width/height:.4f}")
        else:
            print("   分辨率: 无法获取 (viewport_window为空)")
    except AttributeError:
        print("   分辨率: 无法获取 (API不支持)")
    print()

    camera_path = viewport_api.get_active_camera()
    if not camera_path:
        print("❌ 未找到活动的相机!")
        return

    print(f"✅ 相机路径: {camera_path}")
    print()

    # 获取相机prim
    camera_prim = stage.GetPrimAtPath(camera_path)
    if not camera_prim:
        print(f"❌ 无法获取相机prim: {camera_path}")
        return

    print(f"✅ 相机Prim类型: {camera_prim.GetTypeName()}")
    print(f"   Prim有效: {camera_prim.IsValid()}")
    print(f"   Prim活跃: {camera_prim.IsActive()}")
    print()

    # 获取相机对象
    camera = UsdGeom.Camera(camera_prim)
    xformable = UsdGeom.Xformable(camera_prim)

    # 验证相机对象
    if not camera:
        print("❌ 无法创建UsdGeom.Camera对象!")
        return
    print("✅ UsdGeom.Camera对象创建成功")
    print()

    # ========== 获取变换信息 ==========
    print("🔧 变换信息:")
    print("-" * 80)

    # 获取所有transform操作
    xform_ops = xformable.GetOrderedXformOps()
    print(f"   发现 {len(xform_ops)} 个变换操作")

    if not xform_ops:
        print("   ⚠️  警告: 没有找到任何变换操作！")
    print()

    translate_value = None
    rotate_value = None
    orient_value = None
    scale_value = None

    for i, op in enumerate(xform_ops):
        op_type = op.GetOpType()
        op_name = op.GetName()
        value = op.Get()

        print(f"   变换操作 #{i+1}:")
        print(f"   - 名称: {op_name}")
        print(f"   - 类型: {op_type}")
        print(f"   - 值类型: {type(value).__name__}")

        if op_type == UsdGeom.XformOp.TypeTranslate:
            translate_value = value
            print(f"   📍 位置 (Translate): {value}")
            print(f"      值: X={value[0]:.6f}, Y={value[1]:.6f}, Z={value[2]:.6f}")
            print(f"      代码: Gf.Vec3d({value[0]}, {value[1]}, {value[2]})")

        elif op_type == UsdGeom.XformOp.TypeOrient:
            orient_value = value
            print(f"   🔄 旋转四元数 (Orient): {value}")
            real = value.GetReal()
            imag = value.GetImaginary()
            print(f"      值: W={real:.6f}, X={imag[0]:.6f}, Y={imag[1]:.6f}, Z={imag[2]:.6f}")
            print(f"      代码: Gf.Quatd({real}, {imag[0]}, {imag[1]}, {imag[2]})")

            # 四元数长度验证（应该接近1）
            quat_length = math.sqrt(real**2 + imag[0]**2 + imag[1]**2 + imag[2]**2)
            print(f"      四元数长度: {quat_length:.6f} {'✓' if abs(quat_length - 1.0) < 0.001 else '⚠️  (应该接近1.0)'}")

        elif op_type == UsdGeom.XformOp.TypeRotateXYZ:
            rotate_value = value
            print(f"   🔄 旋转欧拉角 (RotateXYZ): {value}")
            print(f"      值: X={value[0]:.6f}°, Y={value[1]:.6f}°, Z={value[2]:.6f}°")
            print(f"      代码: Gf.Vec3f({value[0]}, {value[1]}, {value[2]})")

        elif op_type == UsdGeom.XformOp.TypeScale:
            scale_value = value
            print(f"   📏 缩放 (Scale): {value}")
            print(f"      值: X={value[0]:.6f}, Y={value[1]:.6f}, Z={value[2]:.6f}")

        print()

    # 获取世界变换矩阵
    print("🌍 世界变换矩阵:")
    print("-" * 80)
    world_transform = xformable.ComputeLocalToWorldTransform(current_time)
    print("   4x4 变换矩阵:")
    for row in range(4):
        values = [world_transform[row][col] for col in range(4)]
        print(f"   [{values[0]:10.6f}, {values[1]:10.6f}, {values[2]:10.6f}, {values[3]:10.6f}]")

    # 从矩阵提取位置
    matrix_position = world_transform.ExtractTranslation()
    print(f"\n   从矩阵提取的位置: ({matrix_position[0]:.6f}, {matrix_position[1]:.6f}, {matrix_position[2]:.6f})")

    # 比对验证
    if translate_value:
        diff = math.sqrt(sum((matrix_position[i] - translate_value[i])**2 for i in range(3)))
        print(f"   与Translate差异: {diff:.6f} {'✓' if diff < 0.001 else '⚠️  (差异较大)'}")

    print()

    # ========== 获取相机属性 ==========
    print("🎥 相机属性:")
    print("-" * 80)

    # 焦距
    focal_length_attr = camera.GetFocalLengthAttr()
    focal_length = focal_length_attr.Get()
    print(f"   🔍 焦距 (Focal Length):")
    print(f"      值: {focal_length} mm")
    print(f"      属性存在: {focal_length_attr.HasValue()}")
    print(f"      代码: camera.GetFocalLengthAttr().Set({focal_length})")
    print()

    # 裁剪范围
    clipping_range_attr = camera.GetClippingRangeAttr()
    clipping_range = clipping_range_attr.Get()
    print(f"   ✂️  裁剪范围 (Clipping Range):")
    print(f"      近裁剪面: {clipping_range[0]}")
    print(f"      远裁剪面: {clipping_range[1]}")
    print(f"      属性存在: {clipping_range_attr.HasValue()}")
    print(f"      代码: camera.GetClippingRangeAttr().Set(Gf.Vec2f({clipping_range[0]}, {clipping_range[1]}))")
    print()

    # 水平光圈（传感器宽度）
    h_aperture_attr = camera.GetHorizontalApertureAttr()
    h_aperture = h_aperture_attr.Get()
    print(f"   📐 水平光圈 (Horizontal Aperture):")
    print(f"      值: {h_aperture} mm")
    print(f"      属性存在: {h_aperture_attr.HasValue()}")

    # 垂直光圈（传感器高度）
    v_aperture_attr = camera.GetVerticalApertureAttr()
    v_aperture = v_aperture_attr.Get()
    print(f"   📐 垂直光圈 (Vertical Aperture):")
    print(f"      值: {v_aperture} mm")
    print(f"      属性存在: {v_aperture_attr.HasValue()}")
    print()

    # 计算FOV（视场角）
    if focal_length and h_aperture and v_aperture:
        h_fov = 2 * math.atan(h_aperture / (2 * focal_length)) * 180 / math.pi
        v_fov = 2 * math.atan(v_aperture / (2 * focal_length)) * 180 / math.pi
        print(f"   📐 计算出的视场角 (FOV):")
        print(f"      水平FOV: {h_fov:.2f}°")
        print(f"      垂直FOV: {v_fov:.2f}°")
        print(f"      传感器宽高比: {h_aperture/v_aperture:.4f}")
        print()

    # 投影类型
    projection_attr = camera.GetProjectionAttr()
    projection = projection_attr.Get()
    print(f"   🎯 投影类型 (Projection):")
    print(f"      值: {projection}")
    print(f"      属性存在: {projection_attr.HasValue()}")
    print()

    # F-Stop (光圈大小)
    fstop_attr = camera.GetFStopAttr()
    if fstop_attr.HasValue():
        fstop = fstop_attr.Get()
        print(f"   📷 F-Stop:")
        print(f"      值: f/{fstop}")
        print()

    # 焦点距离
    focus_distance_attr = camera.GetFocusDistanceAttr()
    if focus_distance_attr.HasValue():
        focus_distance = focus_distance_attr.Get()
        print(f"   🎯 焦点距离 (Focus Distance):")
        print(f"      值: {focus_distance}")
        print()

    # ========== 验证总结 ==========
    print("=" * 80)
    print("✅ 数据验证总结")
    print("=" * 80)

    validation_passed = True

    # 检查关键参数是否存在
    print("📋 关键参数检查:")
    if translate_value:
        print("   ✓ 位置 (Translate): 已获取")
    else:
        print("   ✗ 位置 (Translate): 未找到")
        validation_passed = False

    if orient_value or rotate_value:
        print(f"   ✓ 旋转: 已获取 ({'四元数' if orient_value else '欧拉角'})")
    else:
        print("   ✗ 旋转: 未找到")
        validation_passed = False

    if focal_length:
        print(f"   ✓ 焦距: {focal_length} mm")
    else:
        print("   ✗ 焦距: 未找到")
        validation_passed = False

    if clipping_range:
        print(f"   ✓ 裁剪范围: [{clipping_range[0]}, {clipping_range[1]}]")
    else:
        print("   ✗ 裁剪范围: 未找到")
        validation_passed = False

    print()

    if validation_passed:
        print("🎉 所有关键参数都已成功获取！这些是实际的相机参数。")
    else:
        print("⚠️  警告: 某些关键参数缺失，请检查相机设置。")

    print()
    print("=" * 80)
    print("📝 可复制的设置代码")
    print("=" * 80)
    print()

    # 位置
    if translate_value:
        print('    # 设置位置')
        print('    translate_op = xform.AddTranslateOp()')
        print(f'    translate_op.Set(Gf.Vec3d({translate_value[0]}, {translate_value[1]}, {translate_value[2]}))')
        print()

    # 旋转
    if orient_value:
        print('    # 设置旋转（四元数 w, x, y, z）')
        print('    orient_op = xform.AddOrientOp()')
        quat = orient_value
        print(f'    orient_op.Set(Gf.Quatd({quat.GetReal()}, {quat.GetImaginary()[0]}, {quat.GetImaginary()[1]}, {quat.GetImaginary()[2]}))')
        print()
    elif rotate_value:
        print('    # 设置旋转（欧拉角）')
        print('    rotate_op = xform.AddRotateXYZOp()')
        print(f'    rotate_op.Set(Gf.Vec3f({rotate_value[0]}, {rotate_value[1]}, {rotate_value[2]}))')
        print()

    # 裁剪范围
    if clipping_range:
        print('    # 设置裁剪范围（近裁剪面, 远裁剪面）')
        print(f'    camera.GetClippingRangeAttr().Set(Gf.Vec2f({clipping_range[0]}, {clipping_range[1]}))')
        print()

    # 焦距
    if focal_length:
        print('    # 设置焦距')
        print(f'    camera.GetFocalLengthAttr().Set({focal_length})')
        print()

    print('    print("✓ 相机设置已应用!")')
    if translate_value:
        print(f'    print("  位置: ({translate_value[0]}, {translate_value[1]}, {translate_value[2]})")')
    if orient_value:
        quat = orient_value
        print(f'    print("  旋转: ({quat.GetReal()}, {quat.GetImaginary()[0]}, {quat.GetImaginary()[1]}, {quat.GetImaginary()[2]})")')

    print()
    print("=" * 80)
    print("🏁 相机参数获取完成")
    print("=" * 80)

# 运行函数
get_current_camera_params()
