#!/usr/bin/env python3
"""Step 3: Scale 3D model to match image bounding box proportions

Run via: blender --background --python step3_scale.py -- <input.glb> <output.glb> <source_image>

Uses alpha channel of the source image to detect subject bounding box,
then scales the 3D model to match those proportions.
"""
import sys
import os
import traceback

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

from lib.blender_utils import (
    clear_scene, import_model, export_model, get_scene_meshes,
    get_mesh_bounds, scale_to_image, parse_blender_args,
)


def main():
    args = parse_blender_args(
        min_args=3,
        usage="Usage: blender --background --python step3_scale.py -- <input.glb> <output.glb> <source_image>"
    )

    input_path = os.path.abspath(args[0])
    output_path = os.path.abspath(args[1])
    image_path = os.path.abspath(args[2])
    target_height = float(args[3]) if len(args) > 3 else 1.8
    z_scale_method = args[4] if len(args) > 4 else 'average'

    if not os.path.exists(input_path):
        print(f"ERROR: Input model not found: {input_path}")
        sys.exit(1)
    if not os.path.exists(image_path):
        print(f"ERROR: Source image not found: {image_path}")
        sys.exit(1)

    # Import (wrap to capture Python exceptions; C-level crash will still exit without traceback)
    print("\n=== Importing model ===")
    sys.stdout.flush()
    sys.stderr.flush()
    clear_scene()
    try:
        import_model(input_path)
    except Exception as e:
        print("STEP3 IMPORT FAILED (Python exception):")
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(1)
    print("STEP3: import_model() returned")
    sys.stdout.flush()

    meshes = get_scene_meshes()
    if not meshes:
        print("ERROR: No mesh objects found in imported file")
        sys.exit(1)
    print(f"Found {len(meshes)} mesh(es)")

    # Scale
    print("\n=== Scaling model ===")
    result = scale_to_image(meshes, image_path, target_height, z_scale_method)
    if not result:
        sys.exit(1)

    # Export
    print(f"\nExporting: {output_path}")
    export_model(output_path)
    if not os.path.isfile(output_path):
        print(f"ERROR: Export did not produce: {output_path}")
        sys.exit(1)
    print("\n\u2713 Scale step complete")


main()
