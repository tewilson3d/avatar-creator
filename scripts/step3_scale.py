#!/usr/bin/env python3
"""Step 3: Scale 3D model to match image bounding box proportions

Run via: blender --background --python step3_scale.py -- <input.glb> <output.glb> <source_image>

Uses alpha channel of the source image to detect subject bounding box,
then scales the 3D model to match those proportions. Works for any subject
(characters, shirts, pants, etc.) — no character detection logic.

Adapted from Maya image_plane_utils.py for Blender pipeline.
"""
import bpy
import sys
import os
import mathutils


# =============================================================================
# ALPHA CHANNEL DETECTION (ported from Maya script)
# =============================================================================

def detect_bbox_from_alpha(image_path, threshold=10):
    """
    Detect subject bounding box using alpha channel.

    Args:
        image_path: Path to the image file (must have alpha)
        threshold: Alpha threshold (0-255). Pixels with alpha > threshold
            are considered part of subject (default: 10)

    Returns:
        dict with bbox, dimensions, image_size or None
    """
    import cv2
    import numpy as np

    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"ERROR: Could not load image: {image_path}")
        return None

    if len(img.shape) < 3 or img.shape[2] != 4:
        print(f"ERROR: Image has no alpha channel: {image_path}")
        return None

    height, width = img.shape[:2]
    alpha = img[:, :, 3]

    # Find pixels where alpha > threshold (non-transparent)
    mask = alpha > threshold

    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)

    if not np.any(rows) or not np.any(cols):
        print("ERROR: No non-transparent pixels found")
        return None

    y_min, y_max = np.where(rows)[0][[0, -1]]
    x_min, x_max = np.where(cols)[0][[0, -1]]

    bbox_w = int(x_max - x_min + 1)
    bbox_h = int(y_max - y_min + 1)

    print(f"Image size: {width} x {height}")
    print(f"Subject bbox: x={x_min}, y={y_min}, w={bbox_w}, h={bbox_h}")
    print(f"Coverage: {(bbox_w * bbox_h) / (width * height) * 100:.1f}% of image")

    return {
        'bbox': (int(x_min), int(y_min), bbox_w, bbox_h),
        'dimensions': (bbox_w, bbox_h),
        'image_size': (width, height),
    }


# =============================================================================
# BLENDER BOUNDING BOX HELPERS
# =============================================================================

def get_mesh_bounds(meshes):
    """Get world-space bounding box of all mesh objects."""
    min_co = mathutils.Vector((float('inf'),) * 3)
    max_co = mathutils.Vector((float('-inf'),) * 3)

    for obj in meshes:
        for v in obj.bound_box:
            world_co = obj.matrix_world @ mathutils.Vector(v)
            for i in range(3):
                min_co[i] = min(min_co[i], world_co[i])
                max_co[i] = max(max_co[i], world_co[i])

    size = max_co - min_co
    center = (min_co + max_co) / 2.0
    return min_co, max_co, size, center


def match_bounding_box(meshes, target_width, target_height, z_scale_method='average'):
    """
    Scale meshes so their bounding box matches target width/height.
    Z (depth) is scaled proportionally based on z_scale_method.

    Args:
        meshes: List of mesh objects
        target_width: Desired width (X axis)
        target_height: Desired height (Z axis)
        z_scale_method: How to derive depth scale:
            'average' - average of X and Z scale factors
            'max' - max of X and Z scale factors
            'min' - min of X and Z scale factors
            'x' - use X scale for Y (depth)
            'y' - use Z scale for Y (depth)
    """
    _, _, size, _ = get_mesh_bounds(meshes)

    current_width = size.x   # X = width
    current_height = size.z  # Z = height (up)
    current_depth = size.y   # Y = depth

    if current_width <= 0 or current_height <= 0:
        print("ERROR: Mesh has zero dimensions")
        return None

    scale_x = target_width / current_width
    scale_z = target_height / current_height

    # Derive depth scale proportionally
    if z_scale_method == 'average':
        scale_y = (scale_x + scale_z) / 2.0
    elif z_scale_method == 'max':
        scale_y = max(scale_x, scale_z)
    elif z_scale_method == 'min':
        scale_y = min(scale_x, scale_z)
    elif z_scale_method == 'x':
        scale_y = scale_x
    elif z_scale_method == 'y':
        scale_y = scale_z
    else:
        scale_y = (scale_x + scale_z) / 2.0

    print(f"Current mesh size: {current_width:.4f} x {current_depth:.4f} x {current_height:.4f} (WxDxH)")
    print(f"Target size: {target_width:.4f} x {target_height:.4f} (WxH)")
    print(f"Scale factors: X={scale_x:.4f}, Y(depth)={scale_y:.4f}, Z={scale_z:.4f}")
    print(f"Z scale method: {z_scale_method}")

    for obj in meshes:
        obj.scale.x *= scale_x
        obj.scale.y *= scale_y
        obj.scale.z *= scale_z

    return {
        'scale_factors': (scale_x, scale_y, scale_z),
        'original_size': (current_width, current_depth, current_height),
        'final_size': (current_width * scale_x, current_depth * scale_y, current_height * scale_z),
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(args) < 3:
        print("Usage: blender --background --python step3_scale.py -- <input.glb> <output.glb> <source_image>")
        print("  source_image must have alpha channel for subject detection")
        sys.exit(1)

    input_path = args[0]
    output_path = args[1]
    image_path = args[2]

    # Optional: target height in scene units (default 1.8m for human-scale)
    target_height = float(args[3]) if len(args) > 3 else 1.8
    z_scale_method = args[4] if len(args) > 4 else 'average'

    if not os.path.exists(input_path):
        print(f"ERROR: Input model not found: {input_path}")
        sys.exit(1)
    if not os.path.exists(image_path):
        print(f"ERROR: Source image not found: {image_path}")
        sys.exit(1)

    # Step 1: Detect subject bbox from alpha channel
    print("\n=== Detecting subject from alpha channel ===")
    bbox_info = detect_bbox_from_alpha(image_path)
    if not bbox_info:
        sys.exit(1)

    bbox_w, bbox_h = bbox_info['dimensions']
    img_w, img_h = bbox_info['image_size']

    # Subject aspect ratio from image
    subject_aspect = bbox_w / bbox_h  # width / height
    print(f"Subject aspect ratio (W/H): {subject_aspect:.4f}")

    # Target dimensions: height is fixed, width from aspect ratio
    target_w = target_height * subject_aspect
    target_h = target_height
    print(f"Target dimensions: {target_w:.4f} x {target_h:.4f} (WxH in scene units)")

    # Step 2: Import GLB
    print("\n=== Importing model ===")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_path)

    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        print("ERROR: No mesh objects found in imported file")
        sys.exit(1)
    print(f"Found {len(meshes)} mesh(es)")

    # Step 3: Scale to match image bbox proportions
    print("\n=== Scaling model ===")
    result = match_bounding_box(meshes, target_w, target_h, z_scale_method)
    if not result:
        sys.exit(1)

    # Step 4: Apply transforms
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # Verify final size
    _, _, final_size, _ = get_mesh_bounds(meshes)
    print(f"\nFinal mesh size: {final_size.x:.4f} x {final_size.y:.4f} x {final_size.z:.4f} (WxDxH)")

    # Step 5: Export
    print(f"\nExporting: {output_path}")
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB'
    )
    print("\n✓ Scale step complete")


main()
