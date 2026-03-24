"""Meshy API client for image-to-3D generation.

Drop-in replacement for rodin.py / hunyuan.py.
Docs: https://docs.meshy.ai/api-image-to-3d
"""
import base64
import json
import os
import time
import urllib.request

_BASE = "https://api.meshy.ai/openapi/v1/image-to-3d"


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def submit_task(
    api_key: str,
    image_bytes: bytes = None,
    image_path: str = None,
    filename: str = "character.png",
    mime_type: str = "image/png",
    ai_model: str = "meshy-5",
) -> dict:
    """Submit image-to-3D job. Returns dict with 'job_id' and 'endpoint' keys."""
    if image_path:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        import mimetypes
        mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
    elif not image_bytes:
        raise ValueError("Provide either image_path or image_bytes")

    image_b64 = base64.b64encode(image_bytes).decode()
    image_data_uri = f"data:{mime_type};base64,{image_b64}"

    body = json.dumps({
        "image_url": image_data_uri,
        "ai_model": ai_model,
        "should_texture": True,
        "enable_pbr": True,
    }).encode()

    req = urllib.request.Request(_BASE, data=body, headers=_headers(api_key), method="POST")
    print(f"Submitting to Meshy image-to-3D ({ai_model})...")
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    job_id = result.get("result") or result.get("id")
    if not job_id:
        raise RuntimeError(f"Meshy submit failed: {result}")

    print(f"  Task ID: {job_id}")
    return {"job_id": job_id, "endpoint": _BASE}


def poll_status(api_key: str, job_id: str, timeout_sec: int = 300, endpoint: str = None) -> bool:
    """Poll until SUCCEEDED or FAILED. Returns True on success."""
    base = endpoint or _BASE
    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(5)
        req = urllib.request.Request(
            f"{base}/{job_id}",
            headers=_headers(api_key),
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        status = result.get("status", "")
        progress = result.get("progress", 0)
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] {job_id}: {status} ({progress}%)")

        if status == "SUCCEEDED":
            return True
        if status in ("FAILED", "CANCELED"):
            print(f"ERROR: {result.get('task_error', {}).get('message', status)}")
            return False

    print(f"ERROR: Timed out after {timeout_sec}s")
    return False


def download_results(api_key: str, job_id: str, output_dir: str, endpoint: str = None) -> list[str]:
    """Download the generated GLB. Returns list of local file paths."""
    base = endpoint or _BASE
    req = urllib.request.Request(
        f"{base}/{job_id}",
        headers=_headers(api_key),
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    model_urls = result.get("model_urls", {})
    glb_url = model_urls.get("glb")
    if not glb_url:
        print("ERROR: No GLB URL in Meshy response.")
        return []

    os.makedirs(output_dir, exist_ok=True)
    dest = os.path.join(output_dir, f"meshy_{job_id}.glb")
    print(f"  Downloading meshy_{job_id}.glb...")
    urllib.request.urlretrieve(glb_url, dest)
    print(f"    ->{dest}")
    return [dest]
