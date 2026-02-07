#!/usr/bin/env python3
"""Step 2: Generate 3D model from processed image using Rodin Sketch (Gen-1)

Uses the Hyper3D Rodin API (free tier = Sketch).
API docs: https://developer.hyper3d.ai/

Requires RODIN_API_KEY environment variable.

Flow:
  1. POST /api/v2/rodin  (multipart/form-data, tier=Sketch) → uuid + subscription_key
  2. POST /api/v2/status  (poll with subscription_key until Done)
  3. POST /api/v2/download (get download URLs by task_uuid)
"""
import sys
import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "https://api.hyper3d.com/api/v2"


def make_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build multipart/form-data body. Returns (body_bytes, content_type)."""
    import uuid as _uuid
    boundary = f"----PipelineBoundary{_uuid.uuid4().hex}"
    parts = []

    for key, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n"
        )

    for key, (filename, data, mime) in files.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        )
        # We need to handle binary data specially
        parts.append(None)  # placeholder for binary
        parts.append(data)
        parts.append(b"\r\n")

    closing = f"--{boundary}--\r\n"

    # Assemble
    body = b""
    for part in parts:
        if part is None:
            continue
        elif isinstance(part, bytes):
            body += part
        else:
            body += part.encode("utf-8")
    body += closing.encode("utf-8")

    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def submit_task(api_key: str, image_path: str) -> dict:
    """Submit image-to-3D generation task with Sketch tier."""
    url = f"{BASE_URL}/rodin"

    with open(image_path, "rb") as f:
        image_data = f.read()

    filename = os.path.basename(image_path)
    ext = Path(image_path).suffix.lower()
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }.get(ext, "image/png")

    fields = {
        "tier": "Sketch",
        "geometry_file_format": "glb",
        "material": "PBR",
    }
    files = {
        "images": (filename, image_data, mime),
    }

    body, content_type = make_multipart(fields, files)

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
        method="POST",
    )

    print(f"Submitting to Rodin Sketch (Gen-1)...")
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    if result.get("error"):
        print(f"Rodin error: {result['error']} - {result.get('message', '')}")
        sys.exit(1)

    print(f"  Task UUID: {result['uuid']}")
    print(f"  Jobs: {result['jobs']['uuids']}")
    return result


def poll_status(api_key: str, subscription_key: str, timeout_sec: int = 300) -> bool:
    """Poll task status until all jobs are Done or Failed."""
    url = f"{BASE_URL}/status"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"subscription_key": subscription_key}).encode()

    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(5)
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
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
    """Download generated files. Returns list of downloaded paths."""
    url = f"{BASE_URL}/download"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"task_uuid": task_uuid}).encode()

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
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
        print(f"    → {dest}")

    return downloaded


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_image> <output_model.glb>")
        sys.exit(1)

    image_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(image_path):
        print(f"Input image not found: {image_path}")
        sys.exit(1)

    api_key = os.environ.get("RODIN_API_KEY")
    if not api_key:
        print("ERROR: RODIN_API_KEY environment variable not set.")
        print("Get a free API key at https://hyper3d.ai/")
        sys.exit(1)

    # 1. Submit task
    task = submit_task(api_key, image_path)
    task_uuid = task["uuid"]
    subscription_key = task["jobs"]["subscription_key"]

    # 2. Poll until done (~20s for Sketch)
    print("\nPolling for completion...")
    if not poll_status(api_key, subscription_key, timeout_sec=300):
        sys.exit(1)

    # 3. Download results
    print("\nDownloading results...")
    output_dir = str(Path(output_path).parent)
    downloaded = download_results(api_key, task_uuid, output_dir)

    if not downloaded:
        sys.exit(1)

    # Find the GLB file and copy/rename to output_path
    glb_files = [f for f in downloaded if f.endswith(".glb")]
    if glb_files:
        import shutil
        src = glb_files[0]
        if src != output_path:
            shutil.copy2(src, output_path)
        print(f"\n✓ 3D model saved: {output_path}")
    else:
        # If no GLB, just use the first file
        print(f"\nWarning: No .glb found. Downloaded: {downloaded}")
        if downloaded:
            import shutil
            shutil.copy2(downloaded[0], output_path)
            print(f"  Copied {downloaded[0]} → {output_path}")


if __name__ == "__main__":
    main()
