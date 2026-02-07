#!/usr/bin/env python3
"""Step 4: Retopologize mesh using Instant Meshes / QuadriFlow

Converts triangle mesh to clean quad topology.
Uses local binaries from tools/bin/ (downloaded from quadremesher-plugin VM).

Flow:
  1. Convert GLB → OBJ (via Blender)
  2. Run Instant Meshes or QuadriFlow on OBJ
  3. Convert retopo'd OBJ → GLB (via Blender)

Usage: python step4_retopo.py <input.glb> <output.glb> [--faces N] [--method instant|quadriflow]
"""
import sys
import os
import subprocess
import argparse
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = BASE_DIR / "tools"


def glb_to_obj(glb_path: str, obj_path: str):
    """Convert GLB to OBJ via Blender."""
    script = f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath='{glb_path}')
bpy.ops.wm.obj_export(filepath='{obj_path}')
"""
    result = subprocess.run(
        ["blender", "--background", "--python-expr", script],
        capture_output=True, text=True
    )
    if not os.path.exists(obj_path):
        print(f"GLB→OBJ conversion failed")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        sys.exit(1)


def obj_to_glb(obj_path: str, glb_path: str):
    """Convert OBJ to GLB via Blender."""
    script = f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath='{obj_path}')
bpy.ops.export_scene.gltf(filepath='{glb_path}', export_format='GLB')
"""
    result = subprocess.run(
        ["blender", "--background", "--python-expr", script],
        capture_output=True, text=True
    )
    if not os.path.exists(glb_path):
        print(f"OBJ→GLB conversion failed")
        print(result.stderr[-500:] if result.stderr else "no stderr")
        sys.exit(1)


def run_retopo(input_obj: str, output_obj: str, method: str = "instant",
               target_faces: int = 5000, target_vertices: int = 0):
    """Run retopology using standalone_quad_remesh.py or binaries directly."""
    standalone = TOOLS_DIR / "standalone_quad_remesh.py"

    if standalone.exists():
        cmd = [
            sys.executable, str(standalone),
            input_obj, "-o", output_obj,
            "--method", method,
        ]
        if method == "quadriflow":
            cmd.extend(["--faces", str(target_faces)])
        else:
            cmd.extend(["--vertices", str(target_vertices or target_faces)])

        print(f"Running {method} retopo...")
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            print(f"Retopo failed with exit code {result.returncode}")
            sys.exit(1)
        return

    # Fallback: run binaries directly
    if method == "instant":
        bin_path = TOOLS_DIR / "bin" / "instant-meshes"
        cmd = [str(bin_path), input_obj, "-o", output_obj, "-D"]
        if target_vertices:
            cmd.extend(["-v", str(target_vertices)])
    else:
        bin_path = TOOLS_DIR / "bin" / "quadriflow"
        cmd = [str(bin_path), "-i", input_obj, "-o", output_obj, "-f", str(target_faces)]

    if not bin_path.exists():
        print(f"ERROR: Binary not found: {bin_path}")
        print(f"Download from https://quadremesher-plugin.exe.xyz:8000/quad_remesh_addon.zip")
        sys.exit(1)

    print(f"Running {method}: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Retopologize mesh to quad topology")
    parser.add_argument("input", help="Input GLB file")
    parser.add_argument("output", help="Output GLB file")
    parser.add_argument("--faces", type=int, default=5000, help="Target face count (default: 5000)")
    parser.add_argument("--method", choices=["instant", "quadriflow"], default="instant",
                        help="Remeshing method (default: instant)")
    args = parser.parse_args()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        input_obj = os.path.join(tmpdir, "input.obj")
        output_obj = os.path.join(tmpdir, "output.obj")

        # GLB → OBJ
        print(f"Converting GLB → OBJ...")
        glb_to_obj(os.path.abspath(args.input), input_obj)
        print(f"  ✓ {input_obj}")

        # Retopo
        run_retopo(input_obj, output_obj, args.method, args.faces)

        if not os.path.exists(output_obj):
            print("ERROR: Retopo produced no output")
            sys.exit(1)

        # OBJ → GLB
        print(f"Converting OBJ → GLB...")
        obj_to_glb(output_obj, os.path.abspath(args.output))
        print(f"  ✓ {args.output}")

    print(f"\n✓ Retopology complete: {args.output}")


if __name__ == "__main__":
    main()
