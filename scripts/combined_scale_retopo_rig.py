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
"""
import sys
import os

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

import bpy
from lib.blender_utils import (
    clear_scene, import_model, export_model, get_scene_meshes,
    get_mesh_bounds, join_meshes, scale_to_image, quadriflow_remesh,
    find_armature, find_template_mesh, get_rig_objects,
    align_mesh_to_template, transfer_weights, parent_to_armature,
    cleanup_template_objects, apply_transforms,
)


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
        'retopo_faces': 25000,
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
# STEP WRAPPERS
# =============================================================================

def step_scale(meshes, image_path, target_height, z_scale_method):
    """Run the scale step."""
    print("\n" + "=" * 60)
    print("STEP 3: SCALE")
    print("=" * 60)

    result = scale_to_image(meshes, image_path, target_height, z_scale_method)
    if not result:
        print("WARNING: Scale failed")
        return
    print("\u2713 Scale complete")


def step_retopo(target_faces):
    """Run the retopology step."""
    print("\n" + "=" * 60)
    print("STEP 4: RETOPOLOGY")
    print("=" * 60)

    meshes = get_scene_meshes()
    if not meshes:
        print("ERROR: No mesh objects found")
        return

    mesh_obj = join_meshes(meshes)
    quadriflow_remesh(mesh_obj, target_faces)
    print("\u2713 Retopology complete")


def step_rig_transfer(new_mesh_obj, rig_path):
    """Import rig, transfer weights, parent mesh to armature."""
    print("\n" + "=" * 60)
    print("STEP 5: RIG TRANSFER")
    print("=" * 60)

    our_mesh_name = new_mesh_obj.name

    print(f"  Importing rig: {rig_path}")
    import_model(rig_path)

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

    # Re-find our mesh
    new_mesh = bpy.data.objects.get(our_mesh_name)
    if not new_mesh:
        print(f"ERROR: Lost track of our mesh '{our_mesh_name}'")
        sys.exit(1)

    print(f"\n  Aligning new mesh to template...")
    align_mesh_to_template(new_mesh, template_mesh)

    print(f"\n  Transferring skin weights...")
    transfer_weights(new_mesh, template_mesh)

    print(f"\n  Parenting to armature...")
    parent_to_armature(new_mesh, armature)

    print(f"\n  Cleaning up template meshes...")
    cleanup_template_objects(keep_mesh=new_mesh)

    return armature, new_mesh


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
    print("COMBINED PIPELINE: Scale \u2192 Retopology \u2192 Rig Transfer")
    print("=" * 60)
    print(f"  Input mesh:   {input_path}")
    print(f"  Source image: {image_path}")
    print(f"  Rig:          {rig_path}")
    print(f"  Output:       {output_path}")
    print(f"  Skip scale:   {opts['skip_scale']}")
    print(f"  Skip retopo:  {opts['skip_retopo']}")
    if not opts['skip_retopo']:
        print(f"  Retopo faces: {opts['retopo_faces']}")

    # Import mesh
    print("\n--- Importing mesh ---")
    clear_scene()
    import_model(input_path)

    meshes = get_scene_meshes()
    if not meshes:
        print("ERROR: No mesh objects found")
        sys.exit(1)
    print(f"  Found {len(meshes)} mesh(es)")

    # Step 3: Scale
    if not opts['skip_scale']:
        step_scale(meshes, image_path, opts['target_height'], opts['z_scale_method'])
    else:
        print("\nSKIPPING: Scale")

    # Step 4: Retopology
    if not opts['skip_retopo']:
        step_retopo(opts['retopo_faces'])
    else:
        print("\nSKIPPING: Retopology")

    # Ensure single mesh for rig transfer
    meshes = get_scene_meshes()
    mesh_obj = join_meshes(meshes)

    # Step 5: Rig Transfer
    armature, final_mesh = step_rig_transfer(mesh_obj, rig_path)

    # Export
    print("\n" + "=" * 60)
    print("EXPORT")
    print("=" * 60)
    print(f"  Output: {output_path}")
    export_model(output_path)

    # Summary
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Armature: {armature.name} ({len(armature.data.bones)} bones)")
    print(f"  Mesh: {final_mesh.name} ({len(final_mesh.data.vertices)} verts, {len(final_mesh.data.polygons)} faces)")
    print(f"  Vertex groups: {len(final_mesh.vertex_groups)}")
    print(f"  Output: {output_path}")
    print("\n\u2713 Done")


main()
