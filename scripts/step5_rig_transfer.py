#!/usr/bin/env python3
"""Step 5: Transfer skeleton and skin weights from template rig to new mesh

Run via: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx>

Flow:
  1. Import template rig.fbx (armature + skinned base mesh)
  2. Import new mesh (retopo'd GLB)
  3. Transfer skin weights from template base mesh to new mesh
  4. Parent new mesh to armature, remove template mesh
  5. Export as FBX with skeleton
"""
import bpy
import sys
import os


def find_armature():
    """Find the armature in the scene."""
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            return obj
    return None


def find_template_mesh(armature):
    """Find the main skinned mesh from the template rig.
    Pick the mesh with the most vertices that has vertex groups."""
    candidates = []
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and len(obj.vertex_groups) > 1:
            candidates.append(obj)

    if not candidates:
        return None

    # Pick the one with the most vertices (that's the base body)
    return max(candidates, key=lambda o: len(o.data.vertices))


def get_rig_objects(armature):
    """Get all objects that came with the rig (children + parented)."""
    rig_objects = set()
    rig_objects.add(armature)
    for obj in bpy.context.scene.objects:
        if obj.parent == armature or obj.type == 'EMPTY':
            rig_objects.add(obj)
        # Also check for armature modifier pointing to our armature
        if obj.type == 'MESH':
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object == armature:
                    rig_objects.add(obj)
    return rig_objects


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(args) < 3:
        print("Usage: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx>")
        sys.exit(1)

    mesh_path = args[0]
    rig_path = args[1]
    output_path = args[2]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # =========================================================================
    # Step 1: Import template rig
    # =========================================================================
    print(f"\n=== Importing rig: {rig_path} ===")
    bpy.ops.import_scene.fbx(filepath=rig_path)

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

    # Track all objects from the rig import
    rig_objects = get_rig_objects(armature)
    rig_mesh_names = {obj.name for obj in rig_objects if obj.type == 'MESH'}
    print(f"Rig objects: {[o.name for o in rig_objects]}")

    # =========================================================================
    # Step 2: Import new mesh
    # =========================================================================
    print(f"\n=== Importing new mesh: {mesh_path} ===")
    bpy.ops.import_scene.gltf(filepath=mesh_path)

    # Find newly imported meshes (not from the rig)
    new_meshes = [obj for obj in bpy.context.scene.objects
                  if obj.type == 'MESH' and obj.name not in rig_mesh_names
                  and obj not in rig_objects]

    if not new_meshes:
        print("ERROR: No new mesh objects found after import")
        sys.exit(1)

    # Join all new meshes into one if multiple
    if len(new_meshes) > 1:
        print(f"Joining {len(new_meshes)} new mesh objects...")
        bpy.ops.object.select_all(action='DESELECT')
        for obj in new_meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = new_meshes[0]
        bpy.ops.object.join()

    new_mesh = new_meshes[0]
    print(f"New mesh: {new_mesh.name} ({len(new_mesh.data.vertices)} verts)")

    # =========================================================================
    # Step 2b: Align new mesh to template mesh
    # =========================================================================
    print(f"\n=== Aligning new mesh to template ===")

    import mathutils

    def get_bounds(obj):
        mn = mathutils.Vector((float('inf'),)*3)
        mx = mathutils.Vector((float('-inf'),)*3)
        for v in obj.data.vertices:
            co = obj.matrix_world @ v.co
            for i in range(3):
                mn[i] = min(mn[i], co[i])
                mx[i] = max(mx[i], co[i])
        return mn, mx, mx - mn, (mn + mx) / 2

    t_min, t_max, t_size, t_center = get_bounds(template_mesh)
    n_min, n_max, n_size, n_center = get_bounds(new_mesh)

    print(f"Template: size={t_size.x:.4f}x{t_size.y:.4f}x{t_size.z:.4f}, center={t_center.x:.3f},{t_center.y:.3f},{t_center.z:.3f}")
    print(f"New mesh: size={n_size.x:.4f}x{n_size.y:.4f}x{n_size.z:.4f}, center={n_center.x:.3f},{n_center.y:.3f},{n_center.z:.3f}")

    # Scale new mesh to match template size
    scale_x = t_size.x / n_size.x if n_size.x > 0 else 1
    scale_y = t_size.y / n_size.y if n_size.y > 0 else 1
    scale_z = t_size.z / n_size.z if n_size.z > 0 else 1
    new_mesh.scale = (new_mesh.scale.x * scale_x,
                      new_mesh.scale.y * scale_y,
                      new_mesh.scale.z * scale_z)

    # Apply scale before repositioning
    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    bpy.context.view_layer.objects.active = new_mesh
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # Recalculate bounds after scale
    n_min, n_max, n_size, n_center = get_bounds(new_mesh)

    # Translate to align centers
    offset = t_center - n_center
    new_mesh.location += offset
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    # Verify alignment
    n_min, n_max, n_size, n_center = get_bounds(new_mesh)
    print(f"Aligned:  size={n_size.x:.4f}x{n_size.y:.4f}x{n_size.z:.4f}, center={n_center.x:.3f},{n_center.y:.3f},{n_center.z:.3f}")
    print(f"Scale factors: X={scale_x:.4f}, Y={scale_y:.4f}, Z={scale_z:.4f}")

    # =========================================================================
    # Step 3: Transfer skin weights from template
    # =========================================================================
    print(f"\n=== Transferring skin weights ===")

    # Clear any existing vertex groups on new mesh
    new_mesh.vertex_groups.clear()

    # Create vertex groups on new mesh matching template
    for vg in template_mesh.vertex_groups:
        new_mesh.vertex_groups.new(name=vg.name)
    print(f"Created {len(new_mesh.vertex_groups)} vertex groups")

    # Data transfer modifier for weight transfer
    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    bpy.context.view_layer.objects.active = new_mesh

    mod = new_mesh.modifiers.new(name="WeightTransfer", type='DATA_TRANSFER')
    mod.object = template_mesh
    mod.use_vert_data = True
    mod.data_types_verts = {'VGROUP_WEIGHTS'}
    mod.vert_mapping = 'POLYINTERP_NEAREST'  # Nearest face interpolated

    # Move modifier to top of stack
    while new_mesh.modifiers[0] != mod:
        bpy.ops.object.modifier_move_up(modifier=mod.name)

    # Apply modifier
    bpy.ops.object.modifier_apply(modifier=mod.name)
    print(f"Weight transfer complete")

    # Verify weights
    non_empty_groups = 0
    for vg in new_mesh.vertex_groups:
        count = 0
        for v in new_mesh.data.vertices:
            try:
                w = vg.weight(v.index)
                if w > 0.0:
                    count += 1
            except RuntimeError:
                pass
        if count > 0:
            non_empty_groups += 1
    print(f"Non-empty vertex groups: {non_empty_groups}/{len(new_mesh.vertex_groups)}")

    # =========================================================================
    # Step 4: Parent to armature and set up
    # =========================================================================
    print(f"\n=== Setting up rig ===")

    # Parent new mesh to armature
    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.parent_set(type='ARMATURE_NAME')

    # Ensure armature modifier exists
    has_armature_mod = any(m.type == 'ARMATURE' and m.object == armature
                          for m in new_mesh.modifiers)
    if not has_armature_mod:
        mod = new_mesh.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = armature
    print(f"Parented {new_mesh.name} to {armature.name}")

    # =========================================================================
    # Step 5: Clean up template meshes and export
    # =========================================================================
    print(f"\n=== Cleaning up ===")

    # Remove all template meshes (keep armature + new mesh)
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'MESH' and obj != new_mesh:
            print(f"  Removing template mesh: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)

    # Remove empty groups
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'EMPTY':
            print(f"  Removing empty: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)

    print(f"\n=== Exporting: {output_path} ===")
    bpy.ops.export_scene.fbx(
        filepath=output_path,
        use_selection=False,
        add_leaf_bones=False,
        bake_anim=False,
        mesh_smooth_type='FACE',
        path_mode='COPY',
        embed_textures=True
    )

    # Summary
    print(f"\n=== Summary ===")
    print(f"Armature: {armature.name} ({len(armature.data.bones)} bones)")
    print(f"Mesh: {new_mesh.name} ({len(new_mesh.data.vertices)} verts, {len(new_mesh.data.polygons)} faces)")
    print(f"Vertex groups: {len(new_mesh.vertex_groups)}")
    print(f"Output: {output_path}")
    print(f"\n\u2713 Rig transfer complete")


main()
