#!/usr/bin/env python3
"""Step 4: Retopologize mesh using Blender's built-in QuadriFlow

Run via: blender --background --python step4_retopo.py -- <input.glb> <output.glb> [--faces N]
"""
import sys
import os

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

from lib.blender_utils import (
    clear_scene, import_model, export_model, get_scene_meshes,
    join_meshes, quadriflow_remesh, parse_blender_args,
)


def main():
    args = parse_blender_args(
        min_args=2,
        usage="Usage: blender --background --python step4_retopo.py -- <input.glb> <output.glb> [--faces N]"
    )

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

    # Import
    print(f"\n=== Importing: {input_path} ===")
    clear_scene()
    import_model(input_path)

    meshes = get_scene_meshes()
    if not meshes:
        print("ERROR: No mesh objects found")
        sys.exit(1)
    print(f"Found {len(meshes)} mesh(es)")

    # Join if multiple
    mesh_obj = join_meshes(meshes)

    # Remesh
    print(f"\n=== QuadriFlow remesh (target: {target_faces} faces) ===")
    result = quadriflow_remesh(mesh_obj, target_faces)

    # Export
    print(f"\n=== Exporting: {output_path} ===")
    export_model(output_path)

    print(f"\n\u2713 Retopology complete: {output_path}")
    print(f"  {result['orig_verts']} verts / {result['orig_faces']} faces \u2192 {result['new_verts']} verts / {result['new_faces']} faces")


main()
