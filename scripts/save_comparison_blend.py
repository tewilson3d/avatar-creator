#!/usr/bin/env python3
"""Save a .blend file with the generated mesh + base rig.fbx side by side for comparison.

Run via: blender --background --python save_comparison_blend.py -- <mesh_path> <rig_fbx_path> <output_blend_path>
"""
import sys
import os

# Allow imports from scripts/ directory
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

import bpy
import mathutils
from lib.blender_utils import (
    clear_scene, import_model, get_combined_bounds, parse_blender_args,
)


def main():
    args = parse_blender_args(
        min_args=3,
        usage="Usage: blender --background --python save_comparison_blend.py -- <mesh> <rig.fbx> <output.blend> [source.png]"
    )

    mesh_path = args[0]
    rig_path = args[1]
    output_path = args[2]
    source_image_path = args[3] if len(args) > 3 else None

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Clear scene
    clear_scene()

    # =========================================================================
    # Import the generated mesh
    # =========================================================================
    print(f"\n=== Importing generated mesh: {mesh_path} ===")
    import_model(mesh_path)

    gen_objects = list(bpy.context.scene.objects)
    gen_meshes = [o for o in gen_objects if o.type == 'MESH']
    print(f"Generated mesh objects: {[o.name for o in gen_meshes]}")

    for obj in gen_objects:
        obj.color = (0.2, 0.8, 0.4, 1.0)  # Green tint

    # =========================================================================
    # Import the base rig.fbx
    # =========================================================================
    print(f"\n=== Importing base rig: {rig_path} ===")
    before_import = set(bpy.context.scene.objects)
    import_model(rig_path)
    rig_objects = [o for o in bpy.context.scene.objects if o not in before_import]
    print(f"Rig objects: {[o.name for o in rig_objects]}")

    for obj in rig_objects:
        obj.color = (0.4, 0.4, 0.8, 1.0)  # Blue tint

    # =========================================================================
    # Keep everything at origin
    # =========================================================================
    print(f"\n=== All assets at origin (0,0,0) ===")

    # =========================================================================
    # Organize into collections
    # =========================================================================
    gen_col = bpy.data.collections.new("Generated Mesh")
    rig_col = bpy.data.collections.new("Base Rig (template)")
    bpy.context.scene.collection.children.link(gen_col)
    bpy.context.scene.collection.children.link(rig_col)

    for obj in gen_objects:
        if obj.name in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.unlink(obj)
        gen_col.objects.link(obj)

    for obj in rig_objects:
        if obj.name in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.unlink(obj)
        rig_col.objects.link(obj)

    # =========================================================================
    # Add reference image plane
    # =========================================================================
    if source_image_path and os.path.exists(source_image_path):
        print(f"\n=== Adding reference image plane: {source_image_path} ===")
        img = bpy.data.images.load(os.path.abspath(source_image_path))
        w, h = img.size
        aspect = w / h if h > 0 else 1.0

        # Get mesh height for scaling the plane
        if gen_meshes:
            _, _, gen_size, _ = get_combined_bounds(gen_meshes)
            plane_height = gen_size.z
        else:
            plane_height = 2.0
        plane_width = plane_height * aspect

        bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, plane_height / 2))
        plane = bpy.context.active_object
        plane.name = "Reference Image"
        plane.scale = (plane_width, plane_height, 1)
        # Rotate to face front (stand upright on XZ plane)
        plane.rotation_euler = (1.5708, 0, 0)  # 90 degrees on X
        # Move behind the mesh
        plane.location.y = gen_size.y if gen_meshes else 0.5

        # Create material with image texture
        mat = bpy.data.materials.new(name="Reference Image")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.image = img
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Roughness'].default_value = 1.0
        output = nodes.new('ShaderNodeOutputMaterial')
        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
        links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        mat.blend_method = 'BLEND' if hasattr(mat, 'blend_method') else None
        plane.data.materials.append(mat)

        # Add to a collection
        ref_col = bpy.data.collections.new("Reference Image")
        bpy.context.scene.collection.children.link(ref_col)
        if plane.name in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.unlink(plane)
        ref_col.objects.link(plane)
        print(f"Image plane: {plane_width:.2f}x{plane_height:.2f}, behind mesh at Y={plane.location.y:.2f}")
    else:
        print("\n=== No source image provided, skipping image plane ===")

    # =========================================================================
    # Set up lighting
    # =========================================================================
    print(f"\n=== Setting up scene ===")
    light_data = bpy.data.lights.new(name="Sun", type='SUN')
    light_data.energy = 3.0
    light_obj = bpy.data.objects.new(name="Sun", object_data=light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = (2, -4, 6)
    light_obj.rotation_euler = (0.8, 0.2, 0.3)

    # Save
    print(f"\n=== Saving: {output_path} ===")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(output_path))

    print(f"\n\u2713 Comparison .blend saved: {output_path}")
    print(f"  - 'Generated Mesh' collection: {len(gen_objects)} objects")
    print(f"  - 'Base Rig (template)' collection: {len(rig_objects)} objects")


main()
