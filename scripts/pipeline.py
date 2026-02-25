#!/usr/bin/env python3
"""Avatar Pipeline Orchestrator

Runs the full pipeline:
  1. Process image with Gemini
  2. Generate 3D model via Rodin
  3. Import to Blender, scale
  4. Retopologize (QuadriFlow)
  5. Transfer rig
"""
import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = BASE_DIR / "scripts"
INPUT = BASE_DIR / "input"
MODELS = BASE_DIR / "models"
OUTPUT = BASE_DIR / "output"
TEMPLATES = BASE_DIR / "templates"


def run_step(name, cmd):
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"FAILED: {name}")
        sys.exit(1)
    print(f"DONE: {name}")


def main():
    parser = argparse.ArgumentParser(description="Avatar 3D Pipeline")
    parser.add_argument("image", help="Input character image path")
    parser.add_argument("--skip-gemini", action="store_true", help="Skip Gemini processing")
    parser.add_argument("--skip-retopo", action="store_true", help="Skip retopology")

    # Rodin settings
    parser.add_argument("--tier", default="Sketch",
                        choices=["Sketch", "Regular", "Detail", "Smooth", "Gen-2"],
                        help="Rodin tier (default: Sketch)")
    parser.add_argument("--quality", default="medium",
                        choices=["high", "medium", "low", "extra-low"],
                        help="Rodin quality (default: medium)")
    parser.add_argument("--mesh-mode", default="Raw", choices=["Raw", "Quad"],
                        help="Rodin mesh mode (default: Raw)")
    parser.add_argument("--material", default="PBR", choices=["PBR", "Shaded", "All"],
                        help="Rodin material (default: PBR)")
    parser.add_argument("--tapose", action="store_true", help="Enable T/A pose")
    parser.add_argument("--seed", type=int, default=None, help="Rodin seed (0-65535)")

    # Retopo settings
    parser.add_argument("--retopo-faces", type=int, default=25000,
                        help="Target face count for retopology (default: 25000)")

    args = parser.parse_args()

    image_path = Path(args.image).resolve()
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        sys.exit(1)

    # Derived paths
    stem = image_path.stem
    processed_image = MODELS / f"{stem}_processed.png"
    raw_model = MODELS / f"{stem}_raw.glb"
    scaled_model = MODELS / f"{stem}_scaled.glb"
    retopo_model = MODELS / f"{stem}_retopo.glb"
    final_model = OUTPUT / f"{stem}_rigged.fbx"

    # Step 1: Gemini image processing
    if not args.skip_gemini:
        run_step("Gemini Image Processing", [
            sys.executable, str(SCRIPTS / "step1_gemini_process.py"),
            str(image_path), str(processed_image)
        ])
    else:
        processed_image = image_path

    # Step 2: 3D Generation (with Rodin settings)
    step2_cmd = [
        sys.executable, str(SCRIPTS / "step2_generate_3d.py"),
        str(processed_image), str(raw_model),
        "--tier", args.tier,
        "--quality", args.quality,
        "--mesh-mode", args.mesh_mode,
        "--material", args.material,
    ]
    if args.tapose:
        step2_cmd.append("--tapose")
    if args.seed is not None:
        step2_cmd.extend(["--seed", str(args.seed)])
    run_step("3D Model Generation", step2_cmd)

    # Step 3: Blender scale
    run_step("Scale Model", [
        "blender", "--background", "--python", str(SCRIPTS / "step3_scale.py"),
        "--", str(raw_model), str(scaled_model), str(processed_image)
    ])

    # Step 4: Retopology
    if not args.skip_retopo:
        run_step("Retopology (QuadriFlow)", [
            "blender", "--background", "--python", str(SCRIPTS / "step4_retopo.py"),
            "--", str(scaled_model), str(retopo_model),
            "--faces", str(args.retopo_faces)
        ])
    else:
        retopo_model = scaled_model

    # Step 5: Rig transfer
    run_step("Rig Transfer", [
        "blender", "--background", "--python", str(SCRIPTS / "step5_rig_transfer.py"),
        "--", str(retopo_model), str(TEMPLATES / "rig.fbx"), str(final_model)
    ])

    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE: {final_model}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
