#!/usr/bin/env python3
"""Debug script: import a single GLB and report success or full traceback.

Use this to isolate whether Blender is crashing (C-level) or raising a Python
exception when importing a Rodin GLB. Run in the same environment as the worker
(e.g. Fly container or same Docker image).

Usage:
  blender --background --python scripts/debug_import_glb.py -- /path/to/model.glb

If you see "Import OK" and object counts, the import succeeded.
If you see a traceback, the failure is a Python exception.
If Blender exits with no traceback after "About to import...", it's likely a crash in C code.
"""
import sys
import os
import traceback

def flush():
    sys.stdout.flush()
    sys.stderr.flush()

sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    if not args:
        print("Usage: blender --background --python debug_import_glb.py -- <path/to/model.glb>")
        flush()
        sys.exit(1)
    path = os.path.abspath(args[0])
    print(f"DEBUG: Input path: {path}")
    print(f"DEBUG: File exists: {os.path.isfile(path)}")
    flush()
    if not os.path.isfile(path):
        print("ERROR: File not found")
        flush()
        sys.exit(1)

    from lib.blender_utils import clear_scene, import_model, get_scene_meshes

    print("DEBUG: About to clear_scene()")
    flush()
    clear_scene()
    print("DEBUG: About to import_model(...)")
    flush()
    try:
        import_model(path)
        print("DEBUG: import_model() returned")
        flush()
    except Exception as e:
        print("EXCEPTION in import_model:")
        traceback.print_exc()
        flush()
        sys.exit(1)

    meshes = get_scene_meshes()
    print(f"Import OK. Meshes: {len(meshes)}")
    for m in meshes:
        print(f"  - {m.name}: {len(m.data.vertices)} verts, {len(m.data.polygons)} faces")
    flush()
    print("DEBUG: Script finished normally")
    flush()


main()
