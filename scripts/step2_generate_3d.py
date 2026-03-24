#!/usr/bin/env python3
"""Step 2: Generate 3D model from processed image using Rodin Sketch (Gen-1)

Uses the Hyper3D Rodin API (free tier = Sketch).
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
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_image> <output_model.glb>")
        sys.exit(1)

    image_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(image_path):
        print(f"Input image not found: {image_path}")
        sys.exit(1)

    api_key = os.environ.get("RODIN_API_KEY")
    if not api_key:
        print("ERROR: RODIN_API_KEY environment variable not set.")
        print("Get a free API key at https://hyper3d.ai/")
        sys.exit(1)

    output_dir = str(Path(output_path).parent)

    try:
        task_uuid, downloaded = run_pipeline(
            api_key=api_key,
            image_path=image_path,
            output_dir=output_dir,
        )
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Find GLB and copy/rename to output_path
    glb_files = [f for f in downloaded if f.endswith(".glb")]
    if glb_files:
        src = glb_files[0]
        if src != output_path:
            shutil.copy2(src, output_path)
        print(f"\n\u2713 3D model saved: {output_path}")
    elif downloaded:
        print(f"\nWarning: No .glb found. Downloaded: {downloaded}")
        shutil.copy2(downloaded[0], output_path)
        print(f"  Copied {downloaded[0]} \u2192 {output_path}")


if __name__ == "__main__":
    main()
