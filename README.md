# Avatar 3D Pipeline

End-to-end pipeline: 2D character image → 3D rigged avatar.

**GitHub:** https://github.com/tewilson3d/avatar-creator
**Web UI:** https://avatar-creator.exe.xyz:8000/

## Pipeline Steps

1. **Image Processing** — Gemini removes background, isolates character on white
2. **3D Generation** — Rodin API generates mesh from processed image
3. **Scale** — Blender scales model to match image subject proportions (alpha bbox)
4. **Retopology** — QuadriFlow remesh to target face count (optional)
5. **Rig Transfer** — Transfer skeleton + skin weights from `templates/rig.fbx` to new mesh
6. **Comparison Blend** — Side-by-side .blend with rigged mesh + template rig

## Architecture

### Shared Library (`scripts/lib/`)

All pipeline logic lives in shared modules — no duplication across scripts:

- **`lib/gemini.py`** — Gemini API client (encode, call, retry with model fallback)
- **`lib/rodin.py`** — Rodin API client (multipart, submit, poll, download). All Rodin
  generation params exposed (tier, quality, mesh_mode, material, tapose, seed, etc.)
- **`lib/blender_utils.py`** — Blender helpers: import/export (GLB/FBX/OBJ), bounding
  box calculations, alpha-channel subject detection, mesh scaling, QuadriFlow retopo,
  rig transfer (align, weight transfer, armature parenting), cleanup

### Step Scripts (`scripts/step[1-5]_*.py`)

Thin CLI wrappers around the shared lib. Each can run standalone:

```bash
python scripts/step1_gemini_process.py <input_image> <output_image>
python scripts/step2_generate_3d.py <input_image> <output.glb> [--tier X --quality X ...]
blender --background --python scripts/step3_scale.py -- <in.glb> <out.glb> <image>
blender --background --python scripts/step4_retopo.py -- <in.glb> <out.glb> [--faces N]
blender --background --python scripts/step5_rig_transfer.py -- <mesh.glb> <rig.fbx> <out.fbx>
```

### Combined Script (`scripts/combined_scale_retopo_rig.py`)

Runs steps 3+4+5 in a single Blender session (avoids repeated startup overhead).
Used by the web pipeline.

### Pipeline Orchestrator (`scripts/pipeline.py`)

Runs the full 5-step pipeline end-to-end via subprocess calls.

### Web Server (`web/server.py`)

HTTP server on port 8000 providing:
- `POST /api/process` — Gemini image processing (multipart upload)
- `POST /api/generate3d` — Full async pipeline (Rodin → Scale → Rig → .blend)
- `GET /api/job/<id>` — Poll job status
- `GET /api/outputs` — List output files
- `GET/POST /api/admin/rodin-settings` — Configure Rodin + retopo params
- `GET/POST /api/admin/prompt-prefix` — Configure Gemini prompt
- `GET/POST /api/admin/settings` — UI settings (show_base_image)
- `GET/POST /api/admin/config` — API key management
- Admin auth via session cookies (login at `/admin`)
- Static file serving for `web/`, `models/`, `output/`

Run with systemd or `python web/server.py`.

## Directory Structure

```
scripts/
  lib/                # Shared library (gemini.py, rodin.py, blender_utils.py)
  step1_gemini_process.py
  step2_generate_3d.py
  step3_scale.py      # Blender script
  step4_retopo.py     # Blender script
  step5_rig_transfer.py  # Blender script
  combined_scale_retopo_rig.py  # Blender script (steps 3+4+5)
  save_comparison_blend.py      # Blender script
  pipeline.py         # CLI orchestrator
web/
  server.py           # HTTP server
  index.html          # Main UI
  admin.html          # Admin panel
  admin_login.html
input/                # Source character images
output/               # Final rigged models (.fbx, .blend)
models/               # Intermediate 3D models (raw, scaled, retopo'd)
templates/            # Template rig.fbx
tools/                # Standalone retopo tools (instant-meshes, quadriflow)
research/             # API research notes
```

## Configuration (`.env`)

```bash
# API Keys
GEMINI_API_KEY=...
RODIN_API_KEY=...

# Gemini
GEMINI_PROMPT_PREFIX=keep the exact same style...

# Rodin Generation
RODIN_TIER=Sketch          # Sketch|Regular|Detail|Smooth|Gen-2
RODIN_QUALITY=medium       # high(50k)|medium(18k)|low(8k)|extra-low(4k)
RODIN_MESH_MODE=Raw        # Raw|Quad (Sketch=Raw only)
RODIN_MATERIAL=PBR         # PBR|Shaded|All
RODIN_FORMAT=glb           # glb|fbx|obj|usdz|stl
RODIN_TAPOSE=false         # T/A pose for humanoids
RODIN_SEED=                # 0-65535 or empty

# Retopology
RETOPO_ENABLED=false       # Enable QuadriFlow retopo step
RETOPO_FACES=25000         # Target face count (1000-100000)

# UI
SHOW_BASE_IMAGE=false

# Admin (defaults in server.py if not set)
ADMIN_USER=admin
ADMIN_PASS=...
```

All settings are also configurable via CLI flags (see `pipeline.py --help`)
and the web admin panel (`/api/admin/rodin-settings`).

## CLI Usage

```bash
# Full pipeline with defaults
python scripts/pipeline.py input/character.png

# With Rodin settings
python scripts/pipeline.py input/character.png \
  --tier Regular --quality high --mesh-mode Quad --tapose

# Custom retopo
python scripts/pipeline.py input/character.png --retopo-faces 50000

# Skip steps
python scripts/pipeline.py input/character.png --skip-gemini --skip-retopo
```

## Requirements

- Blender 4.0.2 (installed at `/usr/bin/blender`)
- Python 3.12 (installed)
- OpenCV + NumPy (for alpha bbox detection in Blender scripts)
- Gemini API key (free)
- Rodin API key (free Sketch tier, paid for Regular+)

## Key Notes

- **Sketch tier** (free) is locked to `medium` quality (18k faces) and `Raw` triangular mesh
- **Regular+** (paid) unlocks `Quad` mesh mode, `high` quality (50k), and `TAPose`
- With paid Quad output from Rodin, the QuadriFlow retopo step may be unnecessary
- The web server retopo is disabled by default (`RETOPO_ENABLED=false`)
- Admin password defaults to a hardcoded value — set `ADMIN_PASS` in `.env` for production
