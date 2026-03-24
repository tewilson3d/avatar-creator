"""Shared Blender utilities for the Avatar Pipeline.

Import/export helpers, bounding box calculations, mesh operations.
Requires: bpy, mathutils (Blender Python environment).
"""
import bpy
import mathutils
import os
import sys


# =============================================================================
# IMPORT / EXPORT
# =============================================================================

def import_model(filepath: str):
    """Import a 3D model (GLB/FBX/OBJ) into the current Blender scene."""
    filepath = os.path.abspath(os.path.normpath(filepath))
    ext = os.path.splitext(filepath)[1].lower()
    if ext in ('.glb', '.gltf'):
        _import_gltf(filepath)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=filepath)
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=filepath)
    else:
        raise ValueError(f"Unsupported format: {ext}")


def _import_gltf(filepath: str):
    """Import glTF/GLB. Use addon's unit_import in background (operator often fails without GUI)."""
    filepath = os.path.abspath(os.path.normpath(filepath))
    if not os.path.isfile(filepath):
        raise RuntimeError("glTF file not found: %s" % filepath)
    directory = os.path.dirname(filepath) + os.sep

    # Ensure glTF addon is loaded (needed in background)
    try:
        import addon_utils
        addon_utils.enable("io_scene_gltf2", default_set=True, persistent=False)
    except Exception:
        pass

    # Prefer unit_import when it works (bypasses operator poll/context issues in some Blender versions).
    # In 4.3.x unit_import can raise (e.g. bpy_struct.__new__), so fall back to operator.
    import sys
    mod = sys.modules.get("io_scene_gltf2")
    if not mod:
        for name, m in list(sys.modules.items()):
            if m and hasattr(m, "ImportGLTF2"):
                mod = m
                break
    if mod and hasattr(mod, "ImportGLTF2"):
        op_class = mod.ImportGLTF2
        if hasattr(op_class, "unit_import"):
            try:
                op = op_class()
                op.filepath = filepath
                op.directory = directory
                op.files = None
                op.loglevel = 0
                import_settings = op.as_keywords(ignore=("filter_glob",))
                result = op.unit_import(filepath, import_settings)
                if result == {"FINISHED"}:
                    return
            except Exception as e:
                # unit_import broken in this Blender (e.g. 4.3.2 API); use operator below
                pass

    # Operator path (works in background in 4.3.x; 4.3+ dropped "directory" keyword)
    res = bpy.ops.import_scene.gltf(filepath=filepath)
    if res != {"FINISHED"}:
        raise RuntimeError("glTF import failed (operator returned %s). File: %s" % (res, filepath))


def export_model(filepath: str, **kwargs):
    """Export scene to GLB/FBX/OBJ based on file extension."""
    filepath = os.path.abspath(os.path.normpath(filepath))
    ext = os.path.splitext(filepath)[1].lower()
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    if ext in ('.glb', '.gltf'):
        gltf_defaults = {'export_yup': True}
        gltf_defaults.update(kwargs)
        res = bpy.ops.export_scene.gltf(filepath=filepath, export_format='GLB', **gltf_defaults)
        if res != {"FINISHED"}:
            raise RuntimeError("GLB/GLTF export failed (operator returned %s). File: %s" % (res, filepath))
    elif ext == '.fbx':
        defaults = {
            'use_selection': False,
            'add_leaf_bones': False,
            'bake_anim': False,
            'mesh_smooth_type': 'FACE',
            'path_mode': 'COPY',
            'embed_textures': True,
        }
        defaults.update(kwargs)
        res = bpy.ops.export_scene.fbx(filepath=filepath, **defaults)
        if res != {"FINISHED"}:
            raise RuntimeError("FBX export failed (operator returned %s). File: %s" % (res, filepath))
    elif ext == '.obj':
        res = bpy.ops.wm.obj_export(filepath=filepath, **kwargs)
        if res != {"FINISHED"}:
            raise RuntimeError("OBJ export failed (operator returned %s). File: %s" % (res, filepath))
    else:
        # Default to GLB
        gltf_defaults = {'export_yup': True}
        gltf_defaults.update(kwargs)
        res = bpy.ops.export_scene.gltf(filepath=filepath, export_format='GLB', **gltf_defaults)
        if res != {"FINISHED"}:
            raise RuntimeError("GLB export failed (operator returned %s). File: %s" % (res, filepath))


def clear_scene():
    """Reset Blender to an empty scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def get_scene_meshes() -> list:
    """Return all MESH objects in the current scene."""
    return [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']


def join_meshes(meshes: list) -> object:
    """Join multiple mesh objects into one. Returns the joined object."""
    if len(meshes) <= 1:
        return meshes[0] if meshes else None

    print(f"Joining {len(meshes)} meshes...")
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    return bpy.context.active_object


def apply_transforms(obj, location=False, rotation=True, scale=True):
    """Select an object and apply its transforms."""
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=location, rotation=rotation, scale=scale)


# =============================================================================
# BOUNDING BOX
# =============================================================================

def get_mesh_bounds(meshes):
    """Get world-space bounding box of mesh objects (uses bound_box, fast).

    Args:
        meshes: Single mesh object or list of mesh objects.

    Returns:
        (min_co, max_co, size, center) as mathutils.Vectors
    """
    if not isinstance(meshes, (list, tuple)):
        meshes = [meshes]

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


def get_object_bounds(obj):
    """Get world-space bounds of a single object (vertex-accurate for meshes,
    bone-based for armatures).

    Returns:
        (min_co, max_co, size, center) as mathutils.Vectors
    """
    mn = mathutils.Vector((float('inf'),) * 3)
    mx = mathutils.Vector((float('-inf'),) * 3)

    if obj.type == 'MESH':
        for v in obj.data.vertices:
            co = obj.matrix_world @ v.co
            for i in range(3):
                mn[i] = min(mn[i], co[i])
                mx[i] = max(mx[i], co[i])
    elif obj.type == 'ARMATURE':
        for b in obj.data.bones:
            co = obj.matrix_world @ b.head_local
            for i in range(3):
                mn[i] = min(mn[i], co[i])
                mx[i] = max(mx[i], co[i])
    else:
        # Fallback to bound_box
        for v in obj.bound_box:
            co = obj.matrix_world @ mathutils.Vector(v)
            for i in range(3):
                mn[i] = min(mn[i], co[i])
                mx[i] = max(mx[i], co[i])

    return mn, mx, mx - mn, (mn + mx) / 2


def get_combined_bounds(objects):
    """Get combined bounds of multiple objects of any type.

    Returns:
        (min_co, max_co, size, center) as mathutils.Vectors
    """
    mn = mathutils.Vector((float('inf'),) * 3)
    mx = mathutils.Vector((float('-inf'),) * 3)

    for obj in objects:
        o_mn, o_mx, _, _ = get_object_bounds(obj)
        for i in range(3):
            mn[i] = min(mn[i], o_mn[i])
            mx[i] = max(mx[i], o_mx[i])

    return mn, mx, mx - mn, (mn + mx) / 2


# =============================================================================
# ALPHA BBOX DETECTION
# =============================================================================

def detect_bbox_from_alpha(image_path: str, threshold: int = 10) -> dict | None:
    """Detect subject bounding box using image alpha channel.

    Args:
        image_path: Path to image file (must have alpha channel)
        threshold: Alpha threshold (0-255), pixels above are "subject"

    Returns:
        Dict with 'bbox', 'dimensions', 'image_size' or None on failure.
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
# SCALE
# =============================================================================

def match_bounding_box(meshes, target_width: float, target_height: float,
                       z_scale_method: str = 'average') -> dict | None:
    """Scale meshes so bounding box matches target width (X) and height (Z).

    Args:
        meshes: List of mesh objects
        target_width: Desired width (X axis)
        target_height: Desired height (Z axis)
        z_scale_method: How to derive depth (Y) scale:
            'average', 'max', 'min', 'x', 'y'

    Returns:
        Dict with scale info, or None on failure.
    """
    _, _, size, _ = get_mesh_bounds(meshes)

    current_width = size.x
    current_height = size.z
    current_depth = size.y

    if current_width <= 0 or current_height <= 0:
        print("ERROR: Mesh has zero dimensions")
        return None

    scale_x = target_width / current_width
    scale_z = target_height / current_height

    depth_methods = {
        'average': lambda: (scale_x + scale_z) / 2.0,
        'max': lambda: max(scale_x, scale_z),
        'min': lambda: min(scale_x, scale_z),
        'x': lambda: scale_x,
        'y': lambda: scale_z,
    }
    scale_y = depth_methods.get(z_scale_method, depth_methods['average'])()

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


def scale_to_image(meshes, image_path: str, target_height: float = 1.8,
                   z_scale_method: str = 'average') -> dict | None:
    """Scale meshes to match the subject proportions detected from an image's alpha channel.

    Returns:
        Scale result dict, or None on failure.
    """
    bbox_info = detect_bbox_from_alpha(image_path)
    if not bbox_info:
        return None

    bbox_w, bbox_h = bbox_info['dimensions']
    subject_aspect = bbox_w / bbox_h
    target_w = target_height * subject_aspect
    print(f"Subject aspect ratio (W/H): {subject_aspect:.4f}")
    print(f"Target dimensions: {target_w:.4f} x {target_height:.4f} (WxH in scene units)")

    result = match_bounding_box(meshes, target_w, target_height, z_scale_method)
    if not result:
        return None

    # Apply transforms
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    _, _, final_size, _ = get_mesh_bounds(meshes)
    print(f"Final mesh size: {final_size.x:.4f} x {final_size.y:.4f} x {final_size.z:.4f} (WxDxH)")
    return result


# =============================================================================
# RETOPOLOGY
# =============================================================================

def quadriflow_remesh(mesh_obj, target_faces: int = 5000) -> dict:
    """Run QuadriFlow remesh on a mesh object.

    Returns:
        Dict with original and new vertex/face counts.
    """
    orig_verts = len(mesh_obj.data.vertices)
    orig_faces = len(mesh_obj.data.polygons)
    print(f"Input: {orig_verts} verts, {orig_faces} faces")
    print(f"Target: {target_faces} faces")

    apply_transforms(mesh_obj, location=True, rotation=True, scale=True)

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
    print(f"Result: {new_verts} verts, {new_faces} faces")
    print(f"Reduction: {orig_faces} \u2192 {new_faces} ({new_faces / max(orig_faces, 1) * 100:.1f}%)")

    return {
        'orig_verts': orig_verts, 'orig_faces': orig_faces,
        'new_verts': new_verts, 'new_faces': new_faces,
    }


# =============================================================================
# RIG TRANSFER
# =============================================================================

def find_armature():
    """Find the first armature in the scene."""
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            return obj
    return None


def find_template_mesh(armature):
    """Find the main skinned mesh from a template rig.

    Picks the mesh with the most vertices that has vertex groups.
    """
    candidates = [
        obj for obj in bpy.context.scene.objects
        if obj.type == 'MESH' and len(obj.vertex_groups) > 1
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda o: len(o.data.vertices))


def get_rig_objects(armature) -> set:
    """Get all objects associated with a rig (children, parented, armature-modified)."""
    rig_objects = {armature}
    for obj in bpy.context.scene.objects:
        if obj.parent == armature or obj.type == 'EMPTY':
            rig_objects.add(obj)
        if obj.type == 'MESH':
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object == armature:
                    rig_objects.add(obj)
    return rig_objects


def _safe_weight(vg, vert_index: int) -> float:
    """Get vertex group weight, returning 0.0 if vertex is not in group."""
    try:
        return vg.weight(vert_index)
    except RuntimeError:
        return 0.0


def align_mesh_to_template(new_mesh, template_mesh):
    """Scale and translate new_mesh to match template_mesh bounds.

    Returns:
        (scale_x, scale_y, scale_z) applied.
    """
    t_min, t_max, t_size, t_center = get_object_bounds(template_mesh)
    n_min, n_max, n_size, n_center = get_object_bounds(new_mesh)

    print(f"Template: size={t_size.x:.4f}x{t_size.y:.4f}x{t_size.z:.4f}, center={t_center.x:.3f},{t_center.y:.3f},{t_center.z:.3f}")
    print(f"New mesh: size={n_size.x:.4f}x{n_size.y:.4f}x{n_size.z:.4f}, center={n_center.x:.3f},{n_center.y:.3f},{n_center.z:.3f}")

    scale_x = t_size.x / n_size.x if n_size.x > 0 else 1
    scale_y = t_size.y / n_size.y if n_size.y > 0 else 1
    scale_z = t_size.z / n_size.z if n_size.z > 0 else 1

    new_mesh.scale = (
        new_mesh.scale.x * scale_x,
        new_mesh.scale.y * scale_y,
        new_mesh.scale.z * scale_z,
    )

    apply_transforms(new_mesh, location=False, rotation=True, scale=True)

    # Recalculate and align centers
    _, _, _, n_center = get_object_bounds(new_mesh)
    offset = t_center - n_center
    new_mesh.location += offset
    apply_transforms(new_mesh, location=True, rotation=False, scale=False)

    # Verify
    _, _, n_size, n_center = get_object_bounds(new_mesh)
    print(f"Aligned:  size={n_size.x:.4f}x{n_size.y:.4f}x{n_size.z:.4f}, center={n_center.x:.3f},{n_center.y:.3f},{n_center.z:.3f}")
    print(f"Scale factors: X={scale_x:.4f}, Y={scale_y:.4f}, Z={scale_z:.4f}")

    return scale_x, scale_y, scale_z


def transfer_weights(new_mesh, template_mesh) -> int:
    """Transfer skin weights from template_mesh to new_mesh via DATA_TRANSFER modifier.

    Returns:
        Number of non-empty vertex groups after transfer.
    """
    # Clear existing vertex groups
    new_mesh.vertex_groups.clear()

    # Create matching vertex groups
    for vg in template_mesh.vertex_groups:
        new_mesh.vertex_groups.new(name=vg.name)
    print(f"Created {len(new_mesh.vertex_groups)} vertex groups")

    # Data transfer modifier
    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    bpy.context.view_layer.objects.active = new_mesh

    mod = new_mesh.modifiers.new(name="WeightTransfer", type='DATA_TRANSFER')
    mod.object = template_mesh
    mod.use_vert_data = True
    mod.data_types_verts = {'VGROUP_WEIGHTS'}
    mod.vert_mapping = 'POLYINTERP_NEAREST'

    # Move to top of stack
    while new_mesh.modifiers[0] != mod:
        bpy.ops.object.modifier_move_up(modifier=mod.name)

    bpy.ops.object.modifier_apply(modifier=mod.name)
    print("Weight transfer applied")

    # Count non-empty groups
    non_empty = sum(
        1 for vg in new_mesh.vertex_groups
        if any(_safe_weight(vg, v.index) > 0 for v in new_mesh.data.vertices)
    )
    print(f"Non-empty vertex groups: {non_empty}/{len(new_mesh.vertex_groups)}")
    return non_empty


def parent_to_armature(new_mesh, armature):
    """Parent a mesh to an armature with armature modifier."""
    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.parent_set(type='ARMATURE_NAME')

    # Ensure armature modifier exists
    has_armature_mod = any(
        m.type == 'ARMATURE' and m.object == armature
        for m in new_mesh.modifiers
    )
    if not has_armature_mod:
        mod = new_mesh.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = armature

    print(f"Parented {new_mesh.name} to {armature.name}")


def cleanup_template_objects(keep_mesh):
    """Remove all meshes and empties except the specified mesh."""
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'MESH' and obj != keep_mesh:
            print(f"  Removing template mesh: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'EMPTY':
            print(f"  Removing empty: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)


def parse_blender_args(min_args: int = 0, usage: str = "") -> list[str]:
    """Parse arguments after '--' in Blender command line."""
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    if len(args) < min_args:
        if usage:
            print(usage)
        sys.exit(1)
    return args
