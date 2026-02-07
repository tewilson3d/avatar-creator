# Rodin API — Official Documentation Summary

**Source:** https://developer.hyper3d.ai/
**Last Updated:** 2025-02-07

## Overview

Rodin is a 3D generation model by Hyper3D (Deemos).
- **Base URL:** `https://api.hyper3d.com/api/v2`
- **Auth:** `Authorization: Bearer <API_KEY>` on all endpoints
- **Async flow:** Submit → Poll status → Download

## Tiers

| Tier | Speed | Quality | Free? | Mesh Mode |
|------|-------|---------|-------|-----------|
| **Sketch** (Gen-1) | ~20s | Basic geometry + 1K texture, low-poly, triangular only | ✅ Free tier | Triangular only (GLB) |
| Regular | ~70s | Adjustable poly, 2K texture | Business sub | Tri or Quad |
| Detail | >70s | Enhanced details | Business sub | Tri or Quad |
| Smooth | >70s | Clearer/sharper | Business sub | Tri or Quad |
| Gen-2 | ~90s | Best quality, 10B params | Business sub | Tri or Quad |

**Pricing:** 0.5 credit/generation base. HighPack addon: +1 credit.

## API Flow

### 1. Submit: `POST /api/v2/rodin`

**Content-Type:** `multipart/form-data`

| Parameter | Type | Description |
|-----------|------|-------------|
| images | file | Image(s) for img-to-3D (up to 5) |
| prompt | string | Text prompt (required for text-to-3D) |
| tier | string | `Sketch`, `Regular`, `Detail`, `Smooth` (default: Regular) |
| geometry_file_format | string | `glb`, `fbx`, `obj`, `usdz`, `stl` (default: glb) |
| material | string | `PBR`, `Shaded`, `All` (default: PBR) |
| quality | string | `high`(50k), `medium`(18k), `low`(8k), `extra-low`(4k). Sketch fixed to medium |
| seed | number | 0-65535, optional |
| TAPose | bool | T/A pose for humanoid models |
| mesh_mode | string | `Raw` (triangular) or `Quad`. Sketch = Raw only |
| use_original_alpha | bool | Use original transparency (default: false) |
| condition_mode | string | `fuse` or `concat` for multi-image |
| bbox_condition | array[3] | [width(Y), height(Z), length(X)] |
| addons | array | `["HighPack"]` for 4K textures |

**Response:**
```json
{
  "error": null,
  "message": "Submitted.",
  "uuid": "task-uuid",
  "jobs": {
    "uuids": ["job-1", "job-2"],
    "subscription_key": "sub-key"
  }
}
```

### 2. Poll: `POST /api/v2/status`

**Content-Type:** `application/json`

```json
{"subscription_key": "sub-key-from-step-1"}
```

**Response:**
```json
{
  "error": "OK",
  "jobs": [
    {"uuid": "job-uuid", "status": "Done"}
  ]
}
```

Statuses: `Waiting` → `Generating` → `Done` / `Failed`

### 3. Download: `POST /api/v2/download`

**Content-Type:** `application/json`

```json
{"task_uuid": "task-uuid-from-step-1"}
```

**Response:**
```json
{
  "list": [
    {"url": "https://...", "name": "model.glb"}
  ]
}
```

## Minimal Sketch Example (cURL)

```bash
curl https://api.hyper3d.com/api/v2/rodin \
  -H "Authorization: Bearer ${RODIN_API_KEY}" \
  -F "images=@image.jpg" \
  -F "tier=Sketch"
```

## Error Codes

| Error | Meaning |
|-------|---------|
| NO_ACTIVE_SUBSCRIPTION | No/expired subscription |
| SUBSCRIPTION_PLAN_TOO_LOW | Business required for Gen-1/1.5 (non-Sketch) |
| INSUFFICIENT_FUND | Not enough credits |
| INVALID_REQUEST | Bad request |
| USER_NOT_FOUND | Invalid API key |
