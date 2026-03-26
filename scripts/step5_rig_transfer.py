#!/usr/bin/env python3
"""Step 5: Transfer skeleton and skin weights from template rig to new mesh

Run via: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx> [output.glb]
If output.glb is provided, exports the same rigged scene to GLB (same skeleton as FBX).
"""
import sys
import os
import traceback

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

from lib.blender_utils import (
    clear_scene, import_model, export_model, get_scene_meshes,
    join_meshes, find_armature, find_template_mesh,
    align_mesh_to_template, transfer_weights, parent_to_armature,
    cleanup_template_objects, parse_blender_args,
)
import bpy


def main():
    args = parse_blender_args(
        min_args=3,
        usage="Usage: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx> [output.glb]"
    )

    mesh_path = os.path.abspath(args[0])
    rig_path = os.path.abspath(args[1])
    output_path = os.path.abspath(args[2])
    output_glb = os.path.abspath(args[3]) if len(args) > 3 else None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

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

    # Snapshot every mesh name currently in the scene (all are rig/template objects)
    pre_import_mesh_names = {obj.name for obj in bpy.context.scene.objects if obj.type == 'MESH'}
    print(f"Pre-import meshes: {sorted(pre_import_mesh_names)}")

    # =========================================================================
    # Step 2: Import new mesh (wrap to capture Python exceptions; C-level crash exits without traceback)
    # =========================================================================
    if not os.path.isfile(mesh_path):
        print(f"ERROR: Mesh file not found: {mesh_path}")
        sys.exit(1)
    print(f"\n=== Importing new mesh: {mesh_path} ===")
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        import_model(mesh_path)
    except Exception as e:
        print("STEP5 IMPORT NEW MESH FAILED (Python exception):")
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(1)
    print("STEP5: import_model(new mesh) returned")
    sys.stdout.flush()

    new_meshes = [
        obj for obj in bpy.context.scene.objects
        if obj.type == 'MESH' and obj.name not in pre_import_mesh_names
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
    # Step 3.5: Post-transfer skinning cleanup (non-fatal)
    # =========================================================================
    print(f"\n=== Post-transfer weight cleanup ===")
    try:
        bpy.ops.object.select_all(action='DESELECT')
        new_mesh.select_set(True)
        bpy.context.view_layer.objects.active = new_mesh

        bpy.ops.object.vertex_group_smooth()
        bpy.ops.object.vertex_group_normalize_all()
        bpy.ops.object.vertex_group_limit_total()
        bpy.ops.object.vertex_group_clean()
        print("Weight cleanup done (smooth, normalize, limit total, clean)")
    except Exception as e:
        print(f"WARNING: Weight cleanup ops failed (non-fatal): {e}")

    try:
        # Enable Preserve Volume on the Armature modifier
        arm_mod = next((m for m in new_mesh.modifiers if m.type == 'ARMATURE'), None)
        if arm_mod:
            arm_mod.use_deform_preserve_volume = True
            print("Armature modifier: Preserve Volume enabled")

        # Add Corrective Smooth modifier after the Armature modifier
        cs_mod = new_mesh.modifiers.new(name="CorrectiveSmooth", type='CORRECTIVE_SMOOTH')
        cs_mod.use_only_smooth = True
        cs_mod.iterations = 5

        # Move it to just after the Armature modifier (stack index arm_idx + 1)
        if arm_mod:
            arm_idx = next(i for i, m in enumerate(new_mesh.modifiers) if m.type == 'ARMATURE')
            cs_idx = next(i for i, m in enumerate(new_mesh.modifiers) if m.name == cs_mod.name)
            while cs_idx > arm_idx + 1:
                bpy.ops.object.modifier_move_up(modifier=cs_mod.name)
                cs_idx -= 1
        print("Added CorrectiveSmooth modifier (only_smooth=True, iterations=5) after Armature")
    except Exception as e:
        print(f"WARNING: Corrective smooth / preserve volume setup failed (non-fatal): {e}")

    # =========================================================================
    # Step 4: Clean up and export
    # =========================================================================
    print(f"\n=== Cleaning up ===")
    cleanup_template_objects(keep_mesh=new_mesh)

    print(f"\n=== Exporting: {output_path} ===")
    export_model(output_path)
    if not os.path.isfile(output_path):
        print(f"ERROR: Export did not create file: {output_path}")
        sys.exit(1)

    if output_glb:
        print(f"\n=== Exporting rigged GLB: {output_glb} ===")
        os.makedirs(os.path.dirname(output_glb), exist_ok=True)
        export_model(output_glb)
        if not os.path.isfile(output_glb):
            print(f"ERROR: GLB export did not create file: {output_glb}")
            sys.exit(1)

    # Summary
    print(f"\n=== Summary ===")
    print(f"Armature: {armature.name} ({len(armature.data.bones)} bones)")
    print(f"Mesh: {new_mesh.name} ({len(new_mesh.data.vertices)} verts, {len(new_mesh.data.polygons)} faces)")
    print(f"Vertex groups: {len(new_mesh.vertex_groups)}")
    print(f"Output: {output_path}")
    print(f"\n\u2713 Rig transfer complete")


main()
