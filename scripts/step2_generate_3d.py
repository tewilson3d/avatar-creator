#!/usr/bin/env python3
"""Step 2: Generate 3D model from processed image using Rodin API

Usage:
  python step2_generate_3d.py <input_image> <output_model.glb> [options]

Options:
  --tier TIER          Sketch|Regular|Detail|Smooth|Gen-2 (default: Sketch)
  --quality QUALITY    high|medium|low|extra-low (default: medium)
  --mesh-mode MODE     Raw|Quad (default: Raw)
  --material MAT       PBR|Shaded|All (default: PBR)
  --format FMT         glb|fbx|obj|usdz|stl (default: glb)
  --tapose             Enable T/A pose for humanoid models
  --seed N             Seed 0-65535

Requires RODIN_API_KEY environment variable.
"""
import sys
import os
import shutil
from pathlib import Path

# Allow imports from scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.rodin import run_pipeline


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    image_path = args[0]
    output_path = args[1]

    if not os.path.exists(image_path):
        print(f"Input image not found: {image_path}")
        sys.exit(1)

    api_key = os.environ.get("RODIN_API_KEY")
    if not api_key:
        print("ERROR: RODIN_API_KEY environment variable not set.")
        print("Get a free API key at https://hyper3d.ai/")
        sys.exit(1)

    # Parse optional flags
    opts = {}
    i = 2
    while i < len(args):
        if args[i] == "--tier" and i + 1 < len(args):
            opts["tier"] = args[i + 1]; i += 2
        elif args[i] == "--quality" and i + 1 < len(args):
            opts["quality"] = args[i + 1]; i += 2
        elif args[i] == "--mesh-mode" and i + 1 < len(args):
            opts["mesh_mode"] = args[i + 1]; i += 2
        elif args[i] == "--material" and i + 1 < len(args):
            opts["material"] = args[i + 1]; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            opts["geometry_file_format"] = args[i + 1]; i += 2
        elif args[i] == "--tapose":
            opts["tapose"] = True; i += 1
        elif args[i] == "--seed" and i + 1 < len(args):
            opts["seed"] = int(args[i + 1]); i += 2
        else:
            print(f"Unknown argument: {args[i]}"); i += 1

    output_dir = str(Path(output_path).parent)

    try:
        task_uuid, downloaded = run_pipeline(
            api_key=api_key,
            image_path=image_path,
            output_dir=output_dir,
            **opts,
        )
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Find GLB and copy/rename to output_path
    out_ext = Path(output_path).suffix.lower()
    matching = [f for f in downloaded if f.endswith(out_ext)]
    if matching:
        src = matching[0]
        if src != output_path:
            shutil.copy2(src, output_path)
        print(f"\n\u2713 3D model saved: {output_path}")
    elif downloaded:
        print(f"\nWarning: No {out_ext} found. Downloaded: {downloaded}")
        shutil.copy2(downloaded[0], output_path)
        print(f"  Copied {downloaded[0]} \u2192 {output_path}")


if __name__ == "__main__":
    main()
