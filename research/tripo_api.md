# Tripo3D API Reference

## Base URL

```
https://api.tripo3d.ai/v2/openapi
```

## Authentication

- Method: **HTTP Bearer Token**
- Header: `Authorization: Bearer YOUR_TRIPO_API_KEY`
- API keys are generated at https://platform.tripo3d.ai (visible only once on creation)
- Key format: `tsk_***`
- Keys must only be used server-side (never in client code)

## Response Structure

All responses follow a unified format:

**Success:**
```json
{ "code": 0, "data": { ... } }
```

**Error:**
```json
{ "code": 2002, "message": "...", "suggestion": "..." }
```

All responses include `X-Tripo-Trace-ID` header for debugging.

---

## Complete Image-to-3D Flow

### Step 1: Upload Image

**`POST /upload/sts`** (preferred endpoint)

- Content-Type: `multipart/form-data`
- Body field: `file` — the image file
- Accepted formats: **webp, jpeg, png**
- Resolution: 20px–6000px (recommended ≥256px)

```bash
curl -X POST 'https://api.tripo3d.ai/v2/openapi/upload/sts' \
  -H 'Content-Type: multipart/form-data' \
  -H "Authorization: Bearer ${APIKEY}" \
  -F "file=@image.jpeg"
```

**Response:**
```json
{
  "code": 0,
  "data": {
    "image_token": "ce85f375-3ccc-440b-b847-571588872ec2"
  }
}
```

### Step 2: Create Generation Task

**`POST /task`**

- Content-Type: `application/json`
- `type`: `"image_to_model"`
- `file.type`: file extension (e.g. `"jpg"`, `"png"`)
- `file.file_token`: the `image_token` from upload (mutually exclusive with `file.url` and `file.object`)
- Alternatively, pass `file.url` with a direct image URL (JPEG/PNG, max 20MB) — **no upload step needed**

```bash
curl -X POST 'https://api.tripo3d.ai/v2/openapi/task' \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${APIKEY}" \
  -d '{
    "type": "image_to_model",
    "file": {
      "type": "jpg",
      "file_token": "ce85f375-3ccc-440b-b847-571588872ec2"
    }
  }'
```

**Response:**
```json
{
  "code": 0,
  "data": {
    "task_id": "1ec04ced-4b87-44f6-a296-beee80777941"
  }
}
```

**Key optional parameters for `image_to_model`:**

| Parameter | Default | Description |
|---|---|---|
| `model_version` | `v2.5-20250123` | Options: `Turbo-v1.0-20250506`, `v3.0-20250812`, `v2.5-20250123`, `v2.0-20240919`, `v1.4-20240625` |
| `texture` | `true` | Enable texturing |
| `pbr` | `true` | Enable PBR materials (forces texture=true) |
| `texture_quality` | `standard` | `standard` or `detailed` (HD) |
| `texture_alignment` | `original_image` | `original_image` or `geometry` |
| `face_limit` | adaptive | Max faces on output mesh |
| `auto_size` | `false` | Scale to real-world dimensions (meters) |
| `orientation` | `default` | `align_image` to auto-rotate to match input |
| `quad` | `false` | Quad mesh output (forces FBX format) |
| `smart_low_poly` | `false` | Hand-crafted low-poly topology |
| `generate_parts` | `false` | Segmented/editable parts (incompatible with texture/pbr) |
| `model_seed` | random | Seed for geometry (deterministic with same seed) |
| `texture_seed` | random | Seed for texture (deterministic with same seed) |
| `enable_image_autofix` | `false` | Optimize input image (slower) |
| `geometry_quality` | `standard` | v3.0+ only: `standard` or `detailed` (Ultra) |
| `export_uv` | `true` | UV unwrapping; false = faster generation |
| `compress` | none | `geometry` for meshopt compression |

### Step 3: Poll Task Status

**`GET /task/{task_id}`**

```bash
curl 'https://api.tripo3d.ai/v2/openapi/task/1ec04ced-4b87-44f6-a296-beee80777941' \
  -H "Authorization: Bearer ${APIKEY}"
```

**Response:**
```json
{
  "code": 0,
  "data": {
    "task_id": "1ec04ced-4b87-44f6-a296-beee80777941",
    "type": "image_to_model",
    "status": "running",
    "input": { ... },
    "output": {},
    "progress": 50,
    "create_time": 1709048933
  }
}
```

**Status values:**

| Status | Type | Meaning |
|---|---|---|
| `queued` | ongoing | Waiting in queue (progress=0) |
| `running` | ongoing | Processing (progress=0–99) |
| `success` | finalized | Done (progress=100), output URLs available |
| `failed` | finalized | Failed (server-side issue) |
| `banned` | finalized | Content policy violation |
| `expired` | finalized | Task expired |
| `cancelled` | finalized | Task was cancelled |
| `unknown` | finalized | System-level problem |

**Important:** Must poll with the **same API key** that created the task.

### Step 4: Download Result

When `status === "success"`, the `output` object contains download URLs:

```json
{
  "output": {
    "model": "https://...signed-url...",
    "base_model": "https://...signed-url...",
    "pbr_model": "https://...signed-url...",
    "rendered_image": "https://...signed-url..."
  }
}
```

| Field | Description |
|---|---|
| `model` | Default textured model (GLB) |
| `base_model` | Base model without PBR |
| `pbr_model` | Model with PBR materials |
| `rendered_image` | Preview image of the model |

**⚠️ All download URLs expire after 5 minutes.** Re-poll the task to get fresh URLs.

Default output format is **GLB**. Use the conversion endpoint for other formats.

### Step 5 (Optional): Format Conversion

**`POST /task`** with `type: "convert_model"`

```json
{
  "type": "convert_model",
  "format": "FBX",
  "original_model_task_id": "<task_id from image_to_model>",
  "face_limit": 10000
}
```

**Supported output formats:** `GLTF`, `USDZ`, `FBX`, `OBJ`, `STL`, `3MF`

**Conversion options:**
- `quad`: Enable quad remeshing / auto retopology
- `face_limit`: Default 10000
- `texture_size`: Default 4096 (v2.0+), max pixel dimension
- `texture_format`: `JPEG` (default), `PNG`, `BMP`, `WEBP`, `TARGA`, `TIFF`, `HDR`, `OPEN_EXR`, `DPX`
- `flatten_bottom` / `flatten_bottom_threshold`: Flatten model bottom
- `pivot_to_center_bottom`: Move pivot point
- `scale_factor`: Scale the model (default 1)
- `with_animation`: Include skeleton/animation data (default true)
- `pack_uv`: Combine all UV islands into one layout
- `bake`: Bake advanced materials into base textures (default true)
- `export_orientation`: Facing direction: `+x` (default), `-x`, `-y`, `+y`
- `fbx_preset`: Target platform: `blender` (default), `3dsmax`, `mixamo`

Note: OBJ and STL don't support rigged models. STL loses textures.

---

## Pricing (API)

**Base rate: $1.00 = 100 credits**

**Free tier: 300 credits on signup**

### Generation Costs (Turbo v1.0 / v3.0 / v2.5 / v2.0)

| Task | Without Texture | Standard Texture |
|---|---|---|
| Text to 3D Model | 10 | 20 |
| **Image to 3D Model** | **20** | **30** |
| Multiview to 3D Model | 20 | 30 |

### Add-on Costs (on top of generation)

| Feature | Extra Credits |
|---|---|
| Style / Quadrangular | +5 each |
| Low Poly | +10 |
| Generate in Parts | +20 |
| Quad Topology | +5 |
| HD Texture (`texture_quality=detailed`) | +10 |

### Other Costs

| Task | Credits |
|---|---|
| Image Generation | 5 |
| Standard Texture (retexture) | 10 |
| HD Texture (retexture) | 20 |
| Rigging | 25 |
| Animation Retarget | 10 per animation |
| Format Conversion (basic) | 5 |
| Format Conversion (advanced, with retopo etc.) | 10 |
| Post Stylization (lego/voxel/etc.) | 20 |
| Retopology | 10 |
| Post Low Poly | 30 |
| Mesh Segmentation | 40 |
| Part Completion | 50 |
| Rig Check | Free |

**Typical image-to-3D cost: 30 credits ($0.30) for standard textured model.**

With 300 free credits, you get ~10 free image-to-3D generations.

---

## Rate Limits

| Task Type | Max Concurrent |
|---|---|
| Refine Model | 5 |
| All other tasks | 10 |

- Concurrency is per task type (e.g., 10 image_to_model + 10 text_to_model simultaneously is fine)
- Image upload: 10 requests per second

---

## Model Versions

| Version | Notes |
|---|---|
| `v3.0-20250812` | Latest, supports `geometry_quality: detailed` (Ultra mode) |
| `Turbo-v1.0-20250506` | Fastest generation |
| `v2.5-20250123` | **Default** — good balance |
| `v2.0-20240919` | Older, supports seeds and all advanced params |
| `v1.4-20240625` | Legacy fast model |
| `v1.3-20240522` | Deprecated |

---

## Python SDK

```bash
pip install tripo3d
```

```python
import asyncio
from tripo3d import TripoClient

async def main():
    async with TripoClient(api_key="YOUR_API_KEY") as client:
        task_id = await client.text_to_model(prompt="a small cat")
        task = await client.wait_for_task(task_id, verbose=True)
        if task.status == TaskStatus.SUCCESS:
            files = await client.download_task_models(task, "./output")

asyncio.run(main())
```

GitHub: https://github.com/VAST-AI-Research/tripo-python-sdk

---

## Check Balance

**`GET /user/balance`**

Returns `{ "balance": number, "frozen": number }`

---

## Error Codes Reference

| HTTP | Code | Description |
|---|---|---|
| 429 | 2000 | Rate limit exceeded |
| 404 | 2001 | Task not found |
| 400 | 2002 | Unsupported task type |
| 400 | 2003 | Input file empty |
| 400 | 2004 | Unsupported file type |
| 400 | 2006 | Invalid original task type |
| 400 | 2007 | Original task not successful |
| 400 | 2008 | Content policy violation |
| 403 | 2010 | Insufficient credits |
| 500 | 2014 | Audit service error |
| 400 | 2015 | Deprecated version |
| 400 | 2017 | Invalid model version |
| 400 | 2018 | Model too complex to remesh |
| 404 | 2019 | File not found in storage |
