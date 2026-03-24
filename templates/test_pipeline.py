#!/usr/bin/env python3
"""Local pipeline test: runs steps 3 (scale) -> 4 (retopo) -> 5 (rig) -> save .blend

Run from anywhere:
    python avatar-creator-server/templates/test_pipeline.py

Inputs (all in templates/):
    model.glb        — generated 3D mesh
    rig.fbx          — template skeleton
    sourceimage.png  — character image with alpha (used by step 3 to detect proportions)

Outputs (written to templates/):
    _scaled.glb      — after step 3 (scale)
    _retopo.glb      — after step 4 (retopo)
    rigged.fbx       — after step 5 (rig transfer)
    rigged.glb       — after step 5 (rig transfer, GLB format)
    review.blend     — final Blender file for review
"""
import subprocess
import sys
from pathlib import Path

BLENDER = r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"

TEMPLATES  = Path(__file__).parent.resolve()
SCRIPTS    = TEMPLATES.parent / "scripts"

model      = TEMPLATES / "model.glb"
rig        = TEMPLATES / "rig.fbx"
image      = TEMPLATES / "sourceimage.png"
scaled     = TEMPLATES / "_scaled.glb"
retopo     = TEMPLATES / "_retopo.glb"
rigged_fbx = TEMPLATES / "review.fbx"
rigged_glb = TEMPLATES / "review.glb"
blend_out  = TEMPLATES / "review.blend"


def run_step(script_name: str, args: list, label: str, output: Path) -> bool:
    """Run a Blender step. Returns True if output file was produced."""
    script = str(SCRIPTS / script_name)
    cmd = [BLENDER, "--background", "--python", script, "--"] + [str(a) for a in args]
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  CMD: {' '.join(cmd)}\n")
    sys.stdout.flush()

    result = subprocess.run(cmd, text=True, cwd=str(TEMPLATES.parent))

    # Blender exits 0 even on Python exceptions, so check the output file too
    if result.returncode != 0 or not output.exists():
        print(f"\n[FAILED] {label} — exit code {result.returncode}, output exists: {output.exists()}")
        return False

    print(f"\n[OK] {label} -> {output.name}")
    return True


def main():
    for path, name in [(model, "model.glb"), (rig, "rig.fbx"), (image, "sourceimage.png")]:
        if not path.exists():
            print(f"ERROR: Missing required file: {path}")
            sys.exit(1)

    # Step 3 — scale (falls back to model.glb if cv2 unavailable)
    if not run_step("step3_scale.py", [model, scaled, image], "Step 3 — Scale", scaled):
        print("  [SKIP] Step 3 failed — using model.glb directly for step 4")
        scaled.write_bytes(model.read_bytes())

    # Step 4 — retopo
    if not run_step("step4_retopo.py", [scaled, retopo], "Step 4 — Retopo", retopo):
        print("  [SKIP] Step 4 failed — using scaled/raw mesh directly for step 5")
        retopo.write_bytes(scaled.read_bytes())

    # Step 5 — rig transfer (required)
    if not run_step("step5_rig_transfer.py", [retopo, rig, rigged_fbx, rigged_glb],
                    "Step 5 — Rig Transfer", rigged_fbx):
        print("\n[ERROR] Rig transfer failed — cannot continue.")
        sys.exit(1)

    # Save .blend (required)
    if not run_step("save_comparison_blend.py", [rigged_fbx, rig, blend_out],
                    "Save review.blend", blend_out):
        print("\n[ERROR] Could not save .blend file.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("  Pipeline complete!")
    print(f"{'='*60}")
    print(f"  review.blend  -> {blend_out}")
    print(f"  rigged.fbx    -> {rigged_fbx}")
    print(f"  rigged.glb    -> {rigged_glb}")


main()
