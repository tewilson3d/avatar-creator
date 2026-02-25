"""Rodin (Hyper3D) API client for 3D model generation.

Shared by step2_generate_3d.py and web/server.py.

Rodin API parameters:
    tier:       Sketch (free), Regular, Detail, Smooth, Gen-2
    quality:    high (50k), medium (18k), low (8k), extra-low (4k)
                Sketch is fixed to medium.
    mesh_mode:  Raw (triangular) or Quad. Sketch = Raw only.
    TAPose:     bool - force T/A pose for humanoid models
    seed:       0-65535
    material:   PBR, Shaded, All
    geometry_file_format: glb, fbx, obj, usdz, stl
    addons:     ["HighPack"] for 4K textures
    bbox_condition: [width(Y), height(Z), length(X)] - bounding box hint
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "https://api.hyper3d.com/api/v2"

# Default settings
DEFAULTS = {
    "tier": "Sketch",
    "quality": "medium",
    "mesh_mode": "Raw",
    "geometry_file_format": "glb",
    "material": "PBR",
    "TAPose": False,
    "seed": None,
    "addons": None,
    "bbox_condition": None,
}


def make_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build multipart/form-data body.

    Args:
        fields: {name: value} for text fields
        files: {name: (filename, data_bytes, mime_type)} for file fields

    Returns:
        (body_bytes, content_type_header)
    """
    import uuid as _uuid
    boundary = f"----PipelineBoundary{_uuid.uuid4().hex}"
    body = b""

    for key, value in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    for key, (filename, data, mime) in files.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
        body += data + b"\r\n"

    body += f"--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def submit_task(
    api_key: str,
    image_path: str = None,
    image_bytes: bytes = None,
    filename: str = "character.png",
    mime_type: str = "image/png",
    tier: str = None,
    quality: str = None,
    mesh_mode: str = None,
    geometry_file_format: str = None,
    material: str = None,
    tapose: bool = None,
    seed: int = None,
    addons: list[str] = None,
    bbox_condition: list[float] = None,
) -> dict:
    """Submit image-to-3D generation task.

    Provide either image_path (reads from disk) or image_bytes (raw bytes).
    All Rodin parameters default to DEFAULTS if not specified.

    Returns:
        Rodin API response dict with 'uuid' and 'jobs' keys.
    """
    if image_path:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        filename = os.path.basename(image_path)
        ext = Path(image_path).suffix.lower()
        mime_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
        }.get(ext, "image/png")
    elif not image_bytes:
        raise ValueError("Provide either image_path or image_bytes")

    # Build fields with defaults
    tier = tier or DEFAULTS["tier"]
    quality = quality or DEFAULTS["quality"]
    mesh_mode = mesh_mode or DEFAULTS["mesh_mode"]
    geometry_file_format = geometry_file_format or DEFAULTS["geometry_file_format"]
    material = material or DEFAULTS["material"]

    fields = {
        "tier": tier,
        "geometry_file_format": geometry_file_format,
        "material": material,
    }

    # Quality is only configurable on non-Sketch tiers
    if tier != "Sketch":
        fields["quality"] = quality
        fields["mesh_mode"] = mesh_mode

    # Optional boolean/value params
    if tapose is True or (tapose is None and DEFAULTS["TAPose"]):
        fields["TAPose"] = "true"

    if seed is not None:
        fields["seed"] = str(seed)
    elif DEFAULTS["seed"] is not None:
        fields["seed"] = str(DEFAULTS["seed"])

    if addons or DEFAULTS["addons"]:
        a = addons or DEFAULTS["addons"]
        fields["addons"] = json.dumps(a)

    if bbox_condition or DEFAULTS["bbox_condition"]:
        bc = bbox_condition or DEFAULTS["bbox_condition"]
        fields["bbox_condition"] = json.dumps(bc)

    files = {
        "images": (filename, image_bytes, mime_type),
    }

    body, content_type = make_multipart(fields, files)

    req = urllib.request.Request(
        f"{BASE_URL}/rodin",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
        method="POST",
    )

    print(f"Submitting to Rodin ({tier})...")
    print(f"  Settings: quality={quality}, mesh_mode={mesh_mode}, "
          f"material={material}, format={geometry_file_format}")
    if tapose or DEFAULTS["TAPose"]:
        print(f"  TAPose: enabled")
    if seed is not None or DEFAULTS["seed"] is not None:
        print(f"  Seed: {seed or DEFAULTS['seed']}")

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    if result.get("error"):
        raise RuntimeError(f"Rodin error: {result['error']} - {result.get('message', '')}")

    print(f"  Task UUID: {result['uuid']}")
    print(f"  Jobs: {result['jobs']['uuids']}")
    return result


def poll_status(api_key: str, subscription_key: str, timeout_sec: int = 300) -> bool:
    """Poll task status until all jobs are Done or Failed.

    Returns:
        True if all jobs completed successfully, False otherwise.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"subscription_key": subscription_key}).encode()

    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(5)
        req = urllib.request.Request(
            f"{BASE_URL}/status", data=payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        jobs = result.get("jobs", [])
        for j in jobs:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] Job {j['uuid']}: {j['status']}")

        if all(j["status"] in ("Done", "Failed") for j in jobs) and jobs:
            if any(j["status"] == "Failed" for j in jobs):
                print("ERROR: One or more jobs failed.")
                return False
            return True

    print(f"ERROR: Timed out after {timeout_sec}s")
    return False


def download_results(api_key: str, task_uuid: str, output_dir: str) -> list[str]:
    """Download generated files.

    Returns:
        List of downloaded file paths.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"task_uuid": task_uuid}).encode()

    req = urllib.request.Request(
        f"{BASE_URL}/download", data=payload, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    items = result.get("list", [])
    if not items:
        print("ERROR: No files in download response.")
        return []

    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    for item in items:
        name = item["name"]
        file_url = item["url"]
        dest = os.path.join(output_dir, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        print(f"  Downloading {name}...")
        urllib.request.urlretrieve(file_url, dest)
        downloaded.append(dest)
        print(f"    \u2192 {dest}")

    return downloaded


def run_pipeline(
    api_key: str,
    image_path: str = None,
    image_bytes: bytes = None,
    output_dir: str = ".",
    filename: str = "character.png",
    mime_type: str = "image/png",
    timeout_sec: int = 300,
    # Rodin generation settings (all optional, use DEFAULTS)
    tier: str = None,
    quality: str = None,
    mesh_mode: str = None,
    geometry_file_format: str = None,
    material: str = None,
    tapose: bool = None,
    seed: int = None,
    addons: list[str] = None,
    bbox_condition: list[float] = None,
) -> tuple[str, list[str]]:
    """Run full Rodin pipeline: submit \u2192 poll \u2192 download.

    Returns:
        (task_uuid, downloaded_paths)

    Raises:
        RuntimeError on failure.
    """
    task = submit_task(
        api_key, image_path=image_path, image_bytes=image_bytes,
        filename=filename, mime_type=mime_type,
        tier=tier, quality=quality, mesh_mode=mesh_mode,
        geometry_file_format=geometry_file_format, material=material,
        tapose=tapose, seed=seed, addons=addons, bbox_condition=bbox_condition,
    )
    task_uuid = task["uuid"]
    subscription_key = task["jobs"]["subscription_key"]

    print("\nPolling for completion...")
    if not poll_status(api_key, subscription_key, timeout_sec=timeout_sec):
        raise RuntimeError("Rodin job failed or timed out")

    print("\nDownloading results...")
    downloaded = download_results(api_key, task_uuid, output_dir)
    if not downloaded:
        raise RuntimeError("No files downloaded from Rodin")

    return task_uuid, downloaded
