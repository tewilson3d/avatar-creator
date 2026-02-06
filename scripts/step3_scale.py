#!/usr/bin/env python3
"""Step 3: Import and scale 3D model in Blender

Run via: blender --background --python step3_scale.py -- input.glb output.glb

Placeholder - user will provide their own scaling script.
"""
import bpy
import sys


def main():
    argv = sys.argv
    # Everything after "--" is our args
    args = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(args) < 2:
        print("Usage: blender --background --python step3_scale.py -- <input.glb> <output.glb>")
        sys.exit(1)

    input_path = args[0]
    output_path = args[1]

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Import GLB
    print(f"Importing: {input_path}")
    bpy.ops.import_scene.gltf(filepath=input_path)

    # Get all mesh objects
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        print("ERROR: No mesh objects found in imported file")
        sys.exit(1)

    print(f"Found {len(meshes)} mesh(es)")

    # === SCALING LOGIC (placeholder - user will provide) ===
    # Default: normalize to 1.8m tall (average human height)
    import mathutils
    
    # Calculate bounding box of all meshes
    min_co = mathutils.Vector((float('inf'),) * 3)
    max_co = mathutils.Vector((float('-inf'),) * 3)
    
    for obj in meshes:
        for v in obj.bound_box:
            world_co = obj.matrix_world @ mathutils.Vector(v)
            for i in range(3):
                min_co[i] = min(min_co[i], world_co[i])
                max_co[i] = max(max_co[i], world_co[i])
    
    current_height = max_co.z - min_co.z
    target_height = 1.8  # meters
    
    if current_height > 0:
        scale_factor = target_height / current_height
        print(f"Current height: {current_height:.4f}, scaling by {scale_factor:.4f}")
        
        for obj in meshes:
            obj.scale *= scale_factor
    
    # Apply transforms
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    # === END SCALING LOGIC ===

    # Export
    print(f"Exporting: {output_path}")
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB'
    )
    print("Scale step complete")


main()
