# Avatar 3D Pipeline

End-to-end pipeline: 2D character image → 3D rigged avatar.

## Pipeline Steps

1. **Image Input** — Character image in `input/`
2. **Image Processing** — Gemini (Nano Banana) cleans/prepares the image for 3D generation
3. **3D Generation** — AI model (Hunyuan3D / Rodin / Trellis) generates mesh from processed image
4. **Blender Import** — Load generated 3D model into Blender
5. **Scale** — Python script to normalize model scale
6. **Retopology** — QuadRemesher via the `quadremesher-plugin` VM
7. **Rig Transfer** — Load `templates/rig.fbx`, transfer skeleton + skin weights to new mesh

## Directory Structure

```
input/          # Source character images
output/         # Final rigged models
models/         # Intermediate 3D models (raw, scaled, retopo'd)
templates/      # Template rig.fbx
scripts/        # All pipeline scripts
```

## Rodin API Settings

Controlled via `.env`, CLI flags, or web admin panel:

| Setting | Values | Default | Notes |
|---------|--------|---------|-------|
| `RODIN_TIER` | `Sketch`, `Regular`, `Detail`, `Smooth`, `Gen-2` | `Sketch` | Sketch is free tier |
| `RODIN_QUALITY` | `high` (50k), `medium` (18k), `low` (8k), `extra-low` (4k) | `medium` | Sketch fixed to medium |
| `RODIN_MESH_MODE` | `Raw` (triangular), `Quad` | `Raw` | Sketch = Raw only |
| `RODIN_MATERIAL` | `PBR`, `Shaded`, `All` | `PBR` | |
| `RODIN_FORMAT` | `glb`, `fbx`, `obj`, `usdz`, `stl` | `glb` | |
| `RODIN_TAPOSE` | `true`, `false` | `false` | Force T/A pose for humanoids |
| `RODIN_SEED` | `0`-`65535` or empty | empty | Reproducible generation |

## Retopology Settings

| Setting | Values | Default | Notes |
|---------|--------|---------|-------|
| `RETOPO_ENABLED` | `true`, `false` | `false` | Enable QuadriFlow retopo |
| `RETOPO_FACES` | `1000`-`100000` | `25000` | Target face count |

## CLI Usage

```bash
# Full pipeline with defaults
python scripts/pipeline.py input/character.png

# With Rodin settings
python scripts/pipeline.py input/character.png \
  --tier Regular --quality high --mesh-mode Quad --tapose

# Skip retopo, custom face count
python scripts/pipeline.py input/character.png --skip-retopo
python scripts/pipeline.py input/character.png --retopo-faces 50000
```

## Requirements

- Blender 4.0.2 (installed)
- Python 3.12 (installed)
- Gemini API key
- 3D generation API key (Rodin/Hunyuan/Trellis)
- Access to quadremesher-plugin VM
