#!/usr/bin/env python3
"""Step 4: Retopologize mesh using Blender's built-in QuadriFlow

Run via: blender --background --python step4_retopo.py -- <input.glb> <output.glb> [--faces N]

Uses Blender's native QuadriFlow remesher (bpy.ops.object.quadriflow_remesh).
This produces clean quad topology suitable for rigging and animation.
"""
import bpy
import sys
import os


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(args) < 2:
        print("Usage: blender --background --python step4_retopo.py -- <input.glb> <output.glb> [--faces N]")
        sys.exit(1)

    input_path = args[0]
    output_path = args[1]

    # Parse optional --faces
    target_faces = 5000
    for i, a in enumerate(args):
        if a == "--faces" and i + 1 < len(args):
            target_faces = int(args[i + 1])

    if not os.path.exists(input_path):
        print(f"ERROR: Input not found: {input_path}")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # =========================================================================
    # Import
    # =========================================================================
    print(f"\n=== Importing: {input_path} ===")
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

    # Collect mesh objects
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        print("ERROR: No mesh objects found")
        sys.exit(1)

    print(f"Found {len(meshes)} mesh(es)")

    # Join all meshes into one if multiple
    if len(meshes) > 1:
        print(f"Joining {len(meshes)} meshes...")
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        meshes = [bpy.context.active_object]

    mesh_obj = meshes[0]
    orig_verts = len(mesh_obj.data.vertices)
    orig_faces = len(mesh_obj.data.polygons)
    print(f"Input mesh: {orig_verts} verts, {orig_faces} faces")

    # =========================================================================
    # QuadriFlow Remesh
    # =========================================================================
    print(f"\n=== QuadriFlow remesh (target: {target_faces} faces) ===")

    # Select and make active
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj

    # Apply all transforms before remeshing
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Run QuadriFlow
    try:
        bpy.ops.object.quadriflow_remesh(
            target_faces=target_faces,
            seed=0,
            use_preserve_sharp=False,
            use_preserve_boundary=True,
            use_mesh_symmetry=True,
        )
    except TypeError:
        # Fallback for older Blender versions with fewer params
        bpy.ops.object.quadriflow_remesh(
            target_faces=target_faces,
        )

    new_verts = len(mesh_obj.data.vertices)
    new_faces = len(mesh_obj.data.polygons)
    print(f"Remeshed: {new_verts} verts, {new_faces} faces")
    print(f"Reduction: {orig_faces} → {new_faces} faces ({new_faces/max(orig_faces,1)*100:.1f}%)")

    # =========================================================================
    # Export
    # =========================================================================
    print(f"\n=== Exporting: {output_path} ===")
    out_ext = os.path.splitext(output_path)[1].lower()
    if out_ext in ('.glb', '.gltf'):
        bpy.ops.export_scene.gltf(filepath=output_path, export_format='GLB')
    elif out_ext == '.fbx':
        bpy.ops.export_scene.fbx(filepath=output_path)
    elif out_ext == '.obj':
        bpy.ops.wm.obj_export(filepath=output_path)
    else:
        bpy.ops.export_scene.gltf(filepath=output_path, export_format='GLB')

    print(f"\n\u2713 Retopology complete: {output_path}")
    print(f"  {orig_verts} verts / {orig_faces} faces → {new_verts} verts / {new_faces} faces")


main()
