#!/usr/bin/env python3
"""Step 3: Scale 3D model to match image bounding box proportions

Run via:
  blender --background --python step3_scale.py -- <input.glb> <output.glb> <front_image> [<side_image>]

Uses alpha channel of the source image(s) to detect subject bounding box,
then scales the 3D model to match those proportions.

When a side image is provided, depth (Y) is derived from the side view
instead of being estimated from the front view.
"""
import sys
import os
import traceback

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

from lib.blender_utils import (
    clear_scene, import_model, export_model, get_scene_meshes,
    get_mesh_bounds, scale_to_image, scale_to_images, parse_blender_args,
)


def main():
    args = parse_blender_args(
        min_args=3,
        usage="Usage: blender --background --python step3_scale.py -- <input.glb> <output.glb> <front_image> [<side_image>]"
    )

    input_path = os.path.abspath(args[0])
    output_path = os.path.abspath(args[1])
    front_image_path = os.path.abspath(args[2])
    side_image_path = os.path.abspath(args[3]) if len(args) > 3 and not args[3].replace('.', '', 1).isdigit() else None

    # Remaining positional args after images
    extra_start = 4 if side_image_path else 3
    target_height = float(args[extra_start]) if len(args) > extra_start else 1.8
    z_scale_method = args[extra_start + 1] if len(args) > extra_start + 1 else 'average'

    if not os.path.exists(input_path):
        print(f"ERROR: Input model not found: {input_path}")
        sys.exit(1)
    if not os.path.exists(front_image_path):
        print(f"ERROR: Front image not found: {front_image_path}")
        sys.exit(1)
    if side_image_path and not os.path.exists(side_image_path):
        print(f"WARNING: Side image not found: {side_image_path}, falling back to front-only scaling")
        side_image_path = None

    # Import
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
    if side_image_path:
        print(f"Using front + side images for 3-axis scaling")
        result = scale_to_images(meshes, front_image_path, side_image_path, target_height)
    else:
        print(f"Using front image only (depth estimated via '{z_scale_method}')")
        result = scale_to_image(meshes, front_image_path, target_height, z_scale_method)

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
