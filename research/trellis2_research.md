# TRELLIS.2 Research Summary

## Overview
TRELLIS.2 is a state-of-the-art 4B-parameter 3D generative model by Microsoft for **image-to-3D** generation.
It uses a novel "O-Voxel" sparse voxel representation and generates textured 3D assets with full PBR materials
(base color, roughness, metallic, opacity).

**License**: MIT
**Repo**: https://github.com/microsoft/TRELLIS.2
**HuggingFace Model**: microsoft/TRELLIS.2-4B
**HuggingFace Demo**: https://huggingface.co/spaces/microsoft/TRELLIS.2

## 1. System Requirements

### Minimum Hardware
- **GPU**: NVIDIA GPU with **at least 24GB VRAM** (tested on A100, H100)
- **RAM**: Not explicitly stated, but given 4B parameters + sparse voxels, expect **32GB+ system RAM**
- **OS**: Linux only (currently tested)
- **CUDA Toolkit**: 12.4 recommended
- **Python**: 3.8+

### Performance Benchmarks (on H100)
| Resolution | Total Time | Breakdown (Shape + Material) |
|-----------|-----------|-----------------------------|
| 512³      | ~3s       | 2s + 1s                     |
| 1024³     | ~17s      | 10s + 7s                    |
| 1536³     | ~60s      | 35s + 25s                   |

## 2. Installation

```bash
# Clone repo with submodules
git clone -b main https://github.com/microsoft/TRELLIS.2.git --recursive
cd TRELLIS.2

# Create conda env and install all dependencies
. ./setup.sh --new-env --basic --flash-attn --nvdiffrast --nvdiffrec --cumesh --o-voxel --flexgemm
```

### Key Dependencies
- PyTorch 2.6.0 with CUDA 12.4
- flash-attn 2.7.3 (or xformers for older GPUs like V100)
- nvdiffrast v0.4.0 (NVIDIA differentiable rasterizer)
- nvdiffrec (split-sum PBR renderer)
- CuMesh (CUDA mesh utilities)
- FlexGEMM (Triton-based sparse convolution)
- O-Voxel (custom voxel representation library)
- transformers, gradio, trimesh, opencv, etc.

**No Dockerfile or environment.yaml provided** — installation is via setup.sh only.
**No requirements.txt or pyproject.toml** — the setup.sh script is the sole installer.

## 3. Usage for Image-to-3D Generation

### Python API (Primary Method)
```python
import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
import cv2
import imageio
from PIL import Image
import torch
from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2.utils import render_utils
from trellis2.renderers import EnvMap
import o_voxel

# Load pipeline (auto-downloads from HuggingFace)
pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
pipeline.cuda()

# Run image-to-3D
image = Image.open("input.png")
mesh = pipeline.run(image)[0]
mesh.simplify(16777216)  # nvdiffrast limit

# Export to GLB
glb = o_voxel.postprocess.to_glb(
    vertices=mesh.vertices, faces=mesh.faces,
    attr_volume=mesh.attrs, coords=mesh.coords,
    attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
    aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
    decimation_target=1000000, texture_size=4096,
    remesh=True, remesh_band=1, remesh_project=0, verbose=True
)
glb.export("output.glb", extension_webp=True)
```

### Web Demo (Gradio)
```bash
python app.py
```
Provides a browser-based UI for image-to-3D generation.

### CLI
No dedicated CLI tool — use `python example.py` or write a script using the Python API.

### Texture Generation (Shape-conditioned)
```bash
python example_texturing.py  # Script example
python app_texturing.py       # Web demo
```

## 4. Output Formats

- **GLB** — Primary export format, PBR-ready with base color, roughness, metallic textures.
  Exported in OPAQUE mode by default (alpha channel preserved but inactive).
  Supports WebP-compressed textures via `extension_webp=True`.
- **MP4** — Rendered video visualization of the 3D asset with environmental lighting.
- **Internal mesh object** — Has vertices, faces, attrs (PBR attributes), coords, layout, voxel_size.
  Can be further processed before export.

**Note**: The o_voxel.postprocess.to_glb function handles decimation, remeshing, UV unwrapping,
and texture baking automatically. The `decimation_target` parameter controls face count.
The `texture_size` parameter controls texture resolution (up to 4096).

OBJ export is NOT directly provided, but GLB can be converted to OBJ/FBX using tools like
trimesh, Blender, or assimp.

## 5. Can It Run on 7GB RAM, 2 CPU, No GPU?

**Absolutely NOT.** Here's why:

1. **No GPU = Cannot run**: The setup.sh script explicitly checks for nvidia-smi or rocminfo
   and exits with "Error: No supported GPU found" if neither is present. Every key dependency
   (flash-attn, nvdiffrast, nvdiffrec, CuMesh, FlexGEMM, O-Voxel) requires CUDA or ROCm.

2. **24GB+ VRAM required**: The model needs at minimum 24GB GPU VRAM (A100/H100 class).

3. **7GB RAM is insufficient**: The 4B parameter model alone would need ~8GB in bf16,
   plus sparse voxel structures, plus the VAE, plus image processing overhead.
   Realistic system RAM requirement is 32GB+.

4. **2 CPU cores are marginal**: While the GPU does the heavy lifting, data preprocessing
   and mesh postprocessing benefit from more cores.

### Alternatives for Low-Resource Machines
- **HuggingFace Spaces Demo**: https://huggingface.co/spaces/microsoft/TRELLIS.2 — Free web demo.
- **Cloud GPU**: Use a cloud provider (RunPod, Lambda, etc.) with an A100 or H100.
- **API service**: Consider wrapping the HF Spaces demo or deploying on a GPU server and
  calling it via API from the low-resource machine.

## 6. Model Architecture Details

The 4B model consists of multiple sub-models:
- Shape SC-VAE (encoder + decoder)
- Texture SC-VAE (encoder + decoder)
- Sparse Structure Flow Model (ss_flow_img_dit_1_3B)
- Shape Flow Model (slat_flow_img2shape_dit_1_3B)
- Texture Flow Model (slat_flow_imgshape2tex_dit_1_3B)
- Each has 512 and 1024 resolution variants

Checkpoint files on HuggingFace: ~12 safetensors files total.
