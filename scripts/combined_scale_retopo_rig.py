#!/usr/bin/env python3
"""Combined Pipeline: Scale → Retopology → Rig Transfer

Run via:
  blender --background --python combined_scale_retopo_rig.py -- \
    <input.glb> <source_image> <rig.fbx> <output.fbx> [options]

Options:
  --target-height FLOAT   Target height in scene units (default: 1.8)
  --z-scale METHOD        Depth scale method: average|max|min|x|y (default: average)
  --retopo-faces INT      Target face count for retopology (default: 5000)
  --skip-retopo           Skip retopology step
  --skip-scale            Skip scale step

Example:
  blender --background --python combined_scale_retopo_rig.py -- \
    model.glb character.png rig.fbx output.fbx --retopo-faces 8000
"""
import bpy
import sys
import os
import mathutils


# =============================================================================
# ARGUMENT PARSING
# =============================================================================

def parse_args():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(args) < 4:
        print(__doc__)
        sys.exit(1)

    opts = {
        'input_path': args[0],
        'image_path': args[1],
        'rig_path': args[2],
        'output_path': args[3],
        'target_height': 1.8,
        'z_scale_method': 'average',
        'retopo_faces': 5000,
        'skip_retopo': False,
        'skip_scale': False,
    }

    i = 4
    while i < len(args):
        if args[i] == '--target-height' and i + 1 < len(args):
            opts['target_height'] = float(args[i + 1]); i += 2
        elif args[i] == '--z-scale' and i + 1 < len(args):
            opts['z_scale_method'] = args[i + 1]; i += 2
        elif args[i] == '--retopo-faces' and i + 1 < len(args):
            opts['retopo_faces'] = int(args[i + 1]); i += 2
        elif args[i] == '--skip-retopo':
            opts['skip_retopo'] = True; i += 1
        elif args[i] == '--skip-scale':
            opts['skip_scale'] = True; i += 1
        else:
            print(f"Unknown argument: {args[i]}"); i += 1

    return opts


# =============================================================================
# STEP 3: SCALE
# =============================================================================

def detect_bbox_from_alpha(image_path, threshold=10):
    """Detect subject bounding box using alpha channel."""
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

    print(f"  Image size: {width} x {height}")
    print(f"  Subject bbox: x={x_min}, y={y_min}, w={bbox_w}, h={bbox_h}")
    print(f"  Coverage: {(bbox_w * bbox_h) / (width * height) * 100:.1f}% of image")

    return {
        'bbox': (int(x_min), int(y_min), bbox_w, bbox_h),
        'dimensions': (bbox_w, bbox_h),
        'image_size': (width, height),
    }


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
    """Scale meshes so their bounding box matches target width/height."""
    _, _, size, _ = get_mesh_bounds(meshes)

    current_width = size.x
    current_height = size.z
    current_depth = size.y

    if current_width <= 0 or current_height <= 0:
        print("ERROR: Mesh has zero dimensions")
        return None

    scale_x = target_width / current_width
    scale_z = target_height / current_height

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

    print(f"  Current mesh size: {current_width:.4f} x {current_depth:.4f} x {current_height:.4f} (WxDxH)")
    print(f"  Target size: {target_width:.4f} x {target_height:.4f} (WxH)")
    print(f"  Scale factors: X={scale_x:.4f}, Y(depth)={scale_y:.4f}, Z={scale_z:.4f}")

    for obj in meshes:
        obj.scale.x *= scale_x
        obj.scale.y *= scale_y
        obj.scale.z *= scale_z

    return {'scale_factors': (scale_x, scale_y, scale_z)}


def step_scale(meshes, image_path, target_height, z_scale_method):
    """Run the scale step: detect alpha bbox and scale mesh to match."""
    print("\n" + "=" * 60)
    print("STEP 3: SCALE")
    print("=" * 60)

    bbox_info = detect_bbox_from_alpha(image_path)
    if not bbox_info:
        print("WARNING: Could not detect bbox from alpha, skipping scale")
        return

    bbox_w, bbox_h = bbox_info['dimensions']
    subject_aspect = bbox_w / bbox_h
    target_w = target_height * subject_aspect
    target_h = target_height
    print(f"  Subject aspect ratio: {subject_aspect:.4f}")
    print(f"  Target dimensions: {target_w:.4f} x {target_h:.4f}")

    result = match_bounding_box(meshes, target_w, target_h, z_scale_method)
    if not result:
        print("WARNING: Scale failed")
        return

    # Apply transforms
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    _, _, final_size, _ = get_mesh_bounds(meshes)
    print(f"  Final mesh size: {final_size.x:.4f} x {final_size.y:.4f} x {final_size.z:.4f} (WxDxH)")
    print("✓ Scale complete")


# =============================================================================
# STEP 4: RETOPOLOGY
# =============================================================================

def step_retopo(target_faces):
    """Run QuadriFlow retopology on the active mesh."""
    print("\n" + "=" * 60)
    print("STEP 4: RETOPOLOGY")
    print("=" * 60)

    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        print("ERROR: No mesh objects found")
        return

    # Join all meshes into one if multiple
    if len(meshes) > 1:
        print(f"  Joining {len(meshes)} meshes...")
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        meshes = [bpy.context.active_object]

    mesh_obj = meshes[0]
    orig_verts = len(mesh_obj.data.vertices)
    orig_faces = len(mesh_obj.data.polygons)
    print(f"  Input: {orig_verts} verts, {orig_faces} faces")
    print(f"  Target: {target_faces} faces")

    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    try:
        bpy.ops.object.quadriflow_remesh(
            target_faces=target_faces,
            seed=0,
            use_preserve_sharp=False,
            use_preserve_boundary=True,
            use_mesh_symmetry=True,
        )
    except TypeError:
        bpy.ops.object.quadriflow_remesh(target_faces=target_faces)

    new_verts = len(mesh_obj.data.vertices)
    new_faces = len(mesh_obj.data.polygons)
    print(f"  Result: {new_verts} verts, {new_faces} faces")
    print(f"  Reduction: {orig_faces} → {new_faces} ({new_faces / max(orig_faces, 1) * 100:.1f}%)")
    print("✓ Retopology complete")


# =============================================================================
# STEP 5: RIG TRANSFER
# =============================================================================

def get_bounds(obj):
    """Get world-space bounds of a single mesh object."""
    mn = mathutils.Vector((float('inf'),) * 3)
    mx = mathutils.Vector((float('-inf'),) * 3)
    for v in obj.data.vertices:
        co = obj.matrix_world @ v.co
        for i in range(3):
            mn[i] = min(mn[i], co[i])
            mx[i] = max(mx[i], co[i])
    return mn, mx, mx - mn, (mn + mx) / 2


def find_armature():
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            return obj
    return None


def find_template_mesh(armature):
    """Find the main skinned mesh from the template rig."""
    candidates = []
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and len(obj.vertex_groups) > 1:
            candidates.append(obj)
    if not candidates:
        return None
    return max(candidates, key=lambda o: len(o.data.vertices))


def get_rig_objects(armature):
    """Get all objects that came with the rig."""
    rig_objects = set()
    rig_objects.add(armature)
    for obj in bpy.context.scene.objects:
        if obj.parent == armature or obj.type == 'EMPTY':
            rig_objects.add(obj)
        if obj.type == 'MESH':
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object == armature:
                    rig_objects.add(obj)
    return rig_objects


def step_rig_transfer(new_mesh_obj, rig_path):
    """Import rig, transfer weights, parent mesh to armature."""
    print("\n" + "=" * 60)
    print("STEP 5: RIG TRANSFER")
    print("=" * 60)

    # Remember our mesh name before importing rig
    our_mesh_name = new_mesh_obj.name

    # Import rig
    print(f"  Importing rig: {rig_path}")
    bpy.ops.import_scene.fbx(filepath=rig_path)

    armature = find_armature()
    if not armature:
        print("ERROR: No armature found in rig file")
        sys.exit(1)
    print(f"  Armature: {armature.name} ({len(armature.data.bones)} bones)")

    template_mesh = find_template_mesh(armature)
    if not template_mesh:
        print("ERROR: No skinned template mesh found in rig file")
        sys.exit(1)
    print(f"  Template mesh: {template_mesh.name} ({len(template_mesh.data.vertices)} verts, {len(template_mesh.vertex_groups)} groups)")

    rig_objects = get_rig_objects(armature)

    # Re-find our mesh (name might have changed)
    new_mesh = bpy.data.objects.get(our_mesh_name)
    if not new_mesh:
        print(f"ERROR: Lost track of our mesh '{our_mesh_name}'")
        sys.exit(1)

    # --- Align new mesh to template ---
    print(f"\n  Aligning new mesh to template...")
    t_min, t_max, t_size, t_center = get_bounds(template_mesh)
    n_min, n_max, n_size, n_center = get_bounds(new_mesh)

    print(f"  Template: size={t_size.x:.4f}x{t_size.y:.4f}x{t_size.z:.4f}")
    print(f"  New mesh: size={n_size.x:.4f}x{n_size.y:.4f}x{n_size.z:.4f}")

    scale_x = t_size.x / n_size.x if n_size.x > 0 else 1
    scale_y = t_size.y / n_size.y if n_size.y > 0 else 1
    scale_z = t_size.z / n_size.z if n_size.z > 0 else 1
    new_mesh.scale = (new_mesh.scale.x * scale_x,
                      new_mesh.scale.y * scale_y,
                      new_mesh.scale.z * scale_z)

    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    bpy.context.view_layer.objects.active = new_mesh
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    n_min, n_max, n_size, n_center = get_bounds(new_mesh)
    offset = t_center - n_center
    new_mesh.location += offset
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    print(f"  Aligned: scale=({scale_x:.4f}, {scale_y:.4f}, {scale_z:.4f})")

    # --- Transfer skin weights ---
    print(f"\n  Transferring skin weights...")
    new_mesh.vertex_groups.clear()
    for vg in template_mesh.vertex_groups:
        new_mesh.vertex_groups.new(name=vg.name)
    print(f"  Created {len(new_mesh.vertex_groups)} vertex groups")

    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    bpy.context.view_layer.objects.active = new_mesh

    mod = new_mesh.modifiers.new(name="WeightTransfer", type='DATA_TRANSFER')
    mod.object = template_mesh
    mod.use_vert_data = True
    mod.data_types_verts = {'VGROUP_WEIGHTS'}
    mod.vert_mapping = 'POLYINTERP_NEAREST'

    while new_mesh.modifiers[0] != mod:
        bpy.ops.object.modifier_move_up(modifier=mod.name)

    bpy.ops.object.modifier_apply(modifier=mod.name)
    print(f"  Weight transfer applied")

    # Verify weights
    non_empty = sum(1 for vg in new_mesh.vertex_groups
                    if any(True for v in new_mesh.data.vertices
                           if _safe_weight(vg, v.index) > 0))
    print(f"  Non-empty vertex groups: {non_empty}/{len(new_mesh.vertex_groups)}")

    # --- Parent to armature ---
    print(f"\n  Parenting to armature...")
    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.parent_set(type='ARMATURE_NAME')

    has_armature_mod = any(m.type == 'ARMATURE' and m.object == armature
                          for m in new_mesh.modifiers)
    if not has_armature_mod:
        mod = new_mesh.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = armature
    print(f"  Parented {new_mesh.name} to {armature.name}")

    # --- Clean up template meshes ---
    print(f"\n  Cleaning up template meshes...")
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'MESH' and obj != new_mesh:
            print(f"    Removing: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'EMPTY':
            print(f"    Removing empty: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)

    return armature, new_mesh


def _safe_weight(vg, vert_index):
    try:
        return vg.weight(vert_index)
    except RuntimeError:
        return 0.0


# =============================================================================
# MAIN
# =============================================================================

def main():
    opts = parse_args()

    input_path = opts['input_path']
    image_path = opts['image_path']
    rig_path = opts['rig_path']
    output_path = opts['output_path']

    for path, label in [(input_path, "Input mesh"), (image_path, "Source image"), (rig_path, "Rig")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} not found: {path}")
            sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    print("\n" + "=" * 60)
    print("COMBINED PIPELINE: Scale → Retopology → Rig Transfer")
    print("=" * 60)
    print(f"  Input mesh:   {input_path}")
    print(f"  Source image: {image_path}")
    print(f"  Rig:          {rig_path}")
    print(f"  Output:       {output_path}")
    print(f"  Skip scale:   {opts['skip_scale']}")
    print(f"  Skip retopo:  {opts['skip_retopo']}")
    if not opts['skip_retopo']:
        print(f"  Retopo faces: {opts['retopo_faces']}")

    # =========================================================================
    # Import mesh
    # =========================================================================
    print("\n--- Importing mesh ---")
    bpy.ops.wm.read_factory_settings(use_empty=True)

    ext = os.path.splitext(input_path)[1].lower()
    if ext in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=input_path)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=input_path)
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=input_path)
    else:
        print(f"ERROR: Unsupported format: {ext}")
        sys.exit(1)

    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        print("ERROR: No mesh objects found")
        sys.exit(1)
    print(f"  Found {len(meshes)} mesh(es)")

    # =========================================================================
    # Step 3: Scale
    # =========================================================================
    if not opts['skip_scale']:
        step_scale(meshes, image_path, opts['target_height'], opts['z_scale_method'])
    else:
        print("\nSKIPPING: Scale")

    # =========================================================================
    # Step 4: Retopology
    # =========================================================================
    if not opts['skip_retopo']:
        step_retopo(opts['retopo_faces'])
    else:
        print("\nSKIPPING: Retopology")

    # Get the mesh object after potential join in retopo
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if len(meshes) > 1:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
    mesh_obj = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH'][0]

    # =========================================================================
    # Step 5: Rig Transfer
    # =========================================================================
    armature, final_mesh = step_rig_transfer(mesh_obj, rig_path)

    # =========================================================================
    # Export
    # =========================================================================
    print("\n" + "=" * 60)
    print("EXPORT")
    print("=" * 60)
    print(f"  Output: {output_path}")

    out_ext = os.path.splitext(output_path)[1].lower()
    if out_ext == '.fbx':
        bpy.ops.export_scene.fbx(
            filepath=output_path,
            use_selection=False,
            add_leaf_bones=False,
            bake_anim=False,
            mesh_smooth_type='FACE',
            path_mode='COPY',
            embed_textures=True
        )
    elif out_ext in ('.glb', '.gltf'):
        bpy.ops.export_scene.gltf(filepath=output_path, export_format='GLB')
    else:
        bpy.ops.export_scene.fbx(
            filepath=output_path,
            use_selection=False,
            add_leaf_bones=False,
            bake_anim=False,
        )

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Armature: {armature.name} ({len(armature.data.bones)} bones)")
    print(f"  Mesh: {final_mesh.name} ({len(final_mesh.data.vertices)} verts, {len(final_mesh.data.polygons)} faces)")
    print(f"  Vertex groups: {len(final_mesh.vertex_groups)}")
    print(f"  Output: {output_path}")
    print("\n✓ Done")


main()
