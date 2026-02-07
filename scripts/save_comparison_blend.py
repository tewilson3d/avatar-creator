#!/usr/bin/env python3
"""Save a .blend file with the generated mesh + base rig.fbx side by side for comparison.

Run via: blender --background --python save_comparison_blend.py -- <mesh_path> <rig_fbx_path> <output_blend_path>

Imports both into one scene, offsets the rig to the right so you can compare.
"""
import bpy
import sys
import os
import mathutils


def get_bounds(objects):
    """Get combined bounding box of a list of objects."""
    mn = mathutils.Vector((float('inf'),) * 3)
    mx = mathutils.Vector((float('-inf'),) * 3)
    for obj in objects:
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
    return mn, mx, mx - mn, (mn + mx) / 2


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(args) < 3:
        print("Usage: blender --background --python save_comparison_blend.py -- <mesh> <rig.fbx> <output.blend>")
        sys.exit(1)

    mesh_path = args[0]
    rig_path = args[1]
    output_path = args[2]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # =========================================================================
    # Import the generated mesh (GLB or FBX)
    # =========================================================================
    print(f"\n=== Importing generated mesh: {mesh_path} ===")
    ext = os.path.splitext(mesh_path)[1].lower()
    if ext == '.glb' or ext == '.gltf':
        bpy.ops.import_scene.gltf(filepath=mesh_path)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=mesh_path)
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=mesh_path)
    else:
        print(f"ERROR: Unsupported mesh format: {ext}")
        sys.exit(1)

    # Collect generated mesh objects
    gen_objects = list(bpy.context.scene.objects)
    gen_meshes = [o for o in gen_objects if o.type == 'MESH']
    print(f"Generated mesh objects: {[o.name for o in gen_meshes]}")

    # Tag generated objects with a color for easy identification
    for obj in gen_objects:
        obj.color = (0.2, 0.8, 0.4, 1.0)  # Green tint

    # =========================================================================
    # Import the base rig.fbx
    # =========================================================================
    print(f"\n=== Importing base rig: {rig_path} ===")
    before_import = set(bpy.context.scene.objects)
    bpy.ops.import_scene.fbx(filepath=rig_path)
    rig_objects = [o for o in bpy.context.scene.objects if o not in before_import]
    rig_meshes = [o for o in rig_objects if o.type == 'MESH']
    rig_armatures = [o for o in rig_objects if o.type == 'ARMATURE']
    print(f"Rig objects: {[o.name for o in rig_objects]}")

    # Tag rig objects
    for obj in rig_objects:
        obj.color = (0.4, 0.4, 0.8, 1.0)  # Blue tint

    # =========================================================================
    # Offset the rig to the right so they sit side by side
    # =========================================================================
    print(f"\n=== Positioning side by side ===")

    if gen_meshes:
        gen_mn, gen_mx, gen_size, gen_center = get_bounds(gen_meshes)
        print(f"Generated mesh bounds: size={gen_size.x:.3f}x{gen_size.y:.3f}x{gen_size.z:.3f}")
    else:
        gen_size = mathutils.Vector((1, 1, 1))

    # Offset rig objects to the right
    offset_x = gen_size.x * 1.5 + 0.5  # 1.5x width + gap

    # Find the root rig objects (no parent or parent not in rig_objects)
    rig_roots = [o for o in rig_objects if o.parent is None or o.parent not in rig_objects]
    for obj in rig_roots:
        obj.location.x += offset_x
    print(f"Offset rig by {offset_x:.3f} on X axis")

    # =========================================================================
    # Organize into collections
    # =========================================================================
    # Create collections
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
    # Set up lighting and camera
    # =========================================================================
    print(f"\n=== Setting up scene ===")

    # Add a light
    light_data = bpy.data.lights.new(name="Sun", type='SUN')
    light_data.energy = 3.0
    light_obj = bpy.data.objects.new(name="Sun", object_data=light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = (2, -4, 6)
    light_obj.rotation_euler = (0.8, 0.2, 0.3)

    # Save
    print(f"\n=== Saving: {output_path} ===")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(output_path))

    print(f"\n✓ Comparison .blend saved: {output_path}")
    print(f"  - 'Generated Mesh' collection: {len(gen_objects)} objects")
    print(f"  - 'Base Rig (template)' collection: {len(rig_objects)} objects")


main()
