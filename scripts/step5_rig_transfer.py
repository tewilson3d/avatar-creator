#!/usr/bin/env python3
"""Step 5: Transfer skeleton and skin weights from template rig to new mesh

Run via: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx>
"""
import sys
import os

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

from lib.blender_utils import (
    clear_scene, import_model, export_model, get_scene_meshes,
    join_meshes, find_armature, find_template_mesh, get_rig_objects,
    align_mesh_to_template, transfer_weights, parent_to_armature,
    cleanup_template_objects, parse_blender_args,
)
import bpy


def main():
    args = parse_blender_args(
        min_args=3,
        usage="Usage: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx>"
    )

    mesh_path = args[0]
    rig_path = args[1]
    output_path = args[2]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # =========================================================================
    # Step 1: Import template rig
    # =========================================================================
    print(f"\n=== Importing rig: {rig_path} ===")
    clear_scene()
    import_model(rig_path)

    armature = find_armature()
    if not armature:
        print("ERROR: No armature found in rig file")
        sys.exit(1)
    print(f"Armature: {armature.name} ({len(armature.data.bones)} bones)")

    template_mesh = find_template_mesh(armature)
    if not template_mesh:
        print("ERROR: No skinned template mesh found in rig file")
        sys.exit(1)
    print(f"Template mesh: {template_mesh.name} ({len(template_mesh.data.vertices)} verts, {len(template_mesh.vertex_groups)} groups)")

    # Track rig objects
    rig_objects = get_rig_objects(armature)
    rig_mesh_names = {obj.name for obj in rig_objects if obj.type == 'MESH'}
    print(f"Rig objects: {[o.name for o in rig_objects]}")

    # =========================================================================
    # Step 2: Import new mesh
    # =========================================================================
    print(f"\n=== Importing new mesh: {mesh_path} ===")
    import_model(mesh_path)

    new_meshes = [
        obj for obj in bpy.context.scene.objects
        if obj.type == 'MESH' and obj.name not in rig_mesh_names and obj not in rig_objects
    ]
    if not new_meshes:
        print("ERROR: No new mesh objects found after import")
        sys.exit(1)

    new_mesh = join_meshes(new_meshes)
    print(f"New mesh: {new_mesh.name} ({len(new_mesh.data.vertices)} verts)")

    # =========================================================================
    # Step 3: Align, transfer weights, parent
    # =========================================================================
    print(f"\n=== Aligning new mesh to template ===")
    align_mesh_to_template(new_mesh, template_mesh)

    print(f"\n=== Transferring skin weights ===")
    transfer_weights(new_mesh, template_mesh)

    print(f"\n=== Setting up rig ===")
    parent_to_armature(new_mesh, armature)

    # =========================================================================
    # Step 4: Clean up and export
    # =========================================================================
    print(f"\n=== Cleaning up ===")
    cleanup_template_objects(keep_mesh=new_mesh)

    print(f"\n=== Exporting: {output_path} ===")
    export_model(output_path)

    # Summary
    print(f"\n=== Summary ===")
    print(f"Armature: {armature.name} ({len(armature.data.bones)} bones)")
    print(f"Mesh: {new_mesh.name} ({len(new_mesh.data.vertices)} verts, {len(new_mesh.data.polygons)} faces)")
    print(f"Vertex groups: {len(new_mesh.vertex_groups)}")
    print(f"Output: {output_path}")
    print(f"\n\u2713 Rig transfer complete")


main()
