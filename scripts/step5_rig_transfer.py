#!/usr/bin/env python3
"""Step 5: Transfer skeleton and skin weights from template rig to new mesh

Run via: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx>
"""
import bpy
import sys


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []

    if len(args) < 3:
        print("Usage: blender --background --python step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <output.fbx>")
        sys.exit(1)

    mesh_path = args[0]
    rig_path = args[1]
    output_path = args[2]

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Import the template rig
    print(f"Importing rig: {rig_path}")
    bpy.ops.import_scene.fbx(filepath=rig_path)

    # Find armature and template mesh from the rig file
    armature = None
    template_mesh = None
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            armature = obj
        elif obj.type == 'MESH':
            template_mesh = obj

    if not armature:
        print("ERROR: No armature found in rig file")
        sys.exit(1)

    print(f"Armature: {armature.name} ({len(armature.data.bones)} bones)")
    if template_mesh:
        print(f"Template mesh: {template_mesh.name}")

    # Import the new mesh
    print(f"Importing mesh: {mesh_path}")
    bpy.ops.import_scene.gltf(filepath=mesh_path)

    # Find the newly imported mesh (objects not in the rig)
    new_meshes = [obj for obj in bpy.context.scene.objects
                  if obj.type == 'MESH' and obj != template_mesh]

    if not new_meshes:
        print("ERROR: No new mesh objects found")
        sys.exit(1)

    # Join all new meshes into one if multiple
    if len(new_meshes) > 1:
        print(f"Joining {len(new_meshes)} mesh objects...")
        bpy.ops.object.select_all(action='DESELECT')
        for obj in new_meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = new_meshes[0]
        bpy.ops.object.join()
        new_mesh = new_meshes[0]
    else:
        new_mesh = new_meshes[0]

    print(f"New mesh: {new_mesh.name} ({len(new_mesh.data.vertices)} verts)")

    # Parent new mesh to armature
    bpy.ops.object.select_all(action='DESELECT')
    new_mesh.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.parent_set(type='ARMATURE_NAME')

    # Transfer weights from template mesh if available
    if template_mesh:
        print("Transferring skin weights from template...")

        # Select new mesh, make active
        bpy.ops.object.select_all(action='DESELECT')
        new_mesh.select_set(True)
        template_mesh.select_set(True)
        bpy.context.view_layer.objects.active = new_mesh

        # Data transfer modifier for vertex groups (skin weights)
        mod = new_mesh.modifiers.new(name="WeightTransfer", type='DATA_TRANSFER')
        mod.object = template_mesh
        mod.use_vert_data = True
        mod.data_types_verts = {'VGROUP_WEIGHTS'}
        mod.vert_mapping = 'POLYINTERP_NEAREST'  # Nearest face interpolated

        # Apply modifier
        bpy.context.view_layer.objects.active = new_mesh
        bpy.ops.object.modifier_apply(modifier=mod.name)

        print(f"Transferred {len(new_mesh.vertex_groups)} vertex groups")

        # Remove template mesh
        bpy.data.objects.remove(template_mesh, do_unlink=True)
    else:
        print("WARNING: No template mesh for weight transfer. Using automatic weights.")
        bpy.ops.object.select_all(action='DESELECT')
        new_mesh.select_set(True)
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')

    # Ensure armature modifier is on the mesh
    has_armature_mod = any(m.type == 'ARMATURE' for m in new_mesh.modifiers)
    if not has_armature_mod:
        mod = new_mesh.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = armature

    # Export
    print(f"Exporting: {output_path}")
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.export_scene.fbx(
        filepath=output_path,
        use_selection=False,
        add_leaf_bones=False,
        bake_anim=False,
        mesh_smooth_type='FACE',
        path_mode='COPY',
        embed_textures=True
    )
    print("Rig transfer complete")


main()
