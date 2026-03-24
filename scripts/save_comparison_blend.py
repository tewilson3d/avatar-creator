#!/usr/bin/env python3
"""Save a .blend file with the generated mesh + base rig.fbx side by side for comparison.

Run via: blender --background --python save_comparison_blend.py -- <mesh_path> <rig_fbx_path> <output_blend_path>
"""
import sys
import os

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

import bpy
import mathutils
from lib.blender_utils import (
    clear_scene, import_model, get_combined_bounds, parse_blender_args,
)


def main():
    args = parse_blender_args(
        min_args=3,
        usage="Usage: blender --background --python save_comparison_blend.py -- <mesh> <rig.fbx> <output.blend>"
    )

    mesh_path = args[0]
    rig_path = args[1]
    output_path = args[2]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Clear scene
    clear_scene()

    # =========================================================================
    # Import the generated mesh
    # =========================================================================
    print(f"\n=== Importing generated mesh: {mesh_path} ===")
    import_model(mesh_path)

    gen_objects = list(bpy.context.scene.objects)
    gen_meshes = [o for o in gen_objects if o.type == 'MESH']
    print(f"Generated mesh objects: {[o.name for o in gen_meshes]}")

    for obj in gen_objects:
        obj.color = (0.2, 0.8, 0.4, 1.0)  # Green tint

    # =========================================================================
    # Import the base rig.fbx
    # =========================================================================
    print(f"\n=== Importing base rig: {rig_path} ===")
    before_import = set(bpy.context.scene.objects)
    import_model(rig_path)
    rig_objects = [o for o in bpy.context.scene.objects if o not in before_import]
    print(f"Rig objects: {[o.name for o in rig_objects]}")

    for obj in rig_objects:
        obj.color = (0.4, 0.4, 0.8, 1.0)  # Blue tint

    # =========================================================================
    # Offset the rig to the right
    # =========================================================================
    print(f"\n=== Positioning side by side ===")

    if gen_meshes:
        _, _, gen_size, _ = get_combined_bounds(gen_meshes)
        print(f"Generated mesh bounds: size={gen_size.x:.3f}x{gen_size.y:.3f}x{gen_size.z:.3f}")
    else:
        gen_size = mathutils.Vector((1, 1, 1))

    offset_x = gen_size.x * 1.5 + 0.5
    rig_roots = [o for o in rig_objects if o.parent is None or o.parent not in rig_objects]
    for obj in rig_roots:
        obj.location.x += offset_x
    print(f"Offset rig by {offset_x:.3f} on X axis")

    # =========================================================================
    # Organize into collections
    # =========================================================================
    gen_col = bpy.data.collections.new("Generated Mesh")
    rig_col = bpy.data.collections.new("Base Rig (template)")
    bpy.context.scene.collection.children.link(gen_col)
    bpy.context.scene.collection.children.link(rig_col)

    for obj in gen_objects:
        if obj.name in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.unlink(obj)
        gen_col.objects.link(obj)

    for obj in rig_objects:
        if obj.name in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.unlink(obj)
        rig_col.objects.link(obj)

    # =========================================================================
    # Set up lighting
    # =========================================================================
    print(f"\n=== Setting up scene ===")
    light_data = bpy.data.lights.new(name="Sun", type='SUN')
    light_data.energy = 3.0
    light_obj = bpy.data.objects.new(name="Sun", object_data=light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = (2, -4, 6)
    light_obj.rotation_euler = (0.8, 0.2, 0.3)

    # Save
    print(f"\n=== Saving: {output_path} ===")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(output_path))

    print(f"\n\u2713 Comparison .blend saved: {output_path}")
    print(f"  - 'Generated Mesh' collection: {len(gen_objects)} objects")
    print(f"  - 'Base Rig (template)' collection: {len(rig_objects)} objects")


main()
