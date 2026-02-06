#!/usr/bin/env python3
"""Step 2: Generate 3D model from processed image

Tries multiple backends in order:
1. Rodin (Hyper Human) - if RODIN_API_KEY set
2. Hunyuan3D - if HUNYUAN_API_KEY set  
3. Trellis (local/API) - fallback
"""
import sys
import os
import json
import base64
import time
import urllib.request
from pathlib import Path


def generate_with_rodin(image_path: str, output_path: str):
    """Generate 3D model using Rodin API (Hyper Human)"""
    api_key = os.environ.get("RODIN_API_KEY")
    if not api_key:
        return False

    print("Using Rodin API for 3D generation...")

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # Submit generation job
    url = "https://hyperhuman.deemos.com/api/v2/rodin"
    payload = {
        "images": [image_data],
        "input_type": "image",
        "output_format": "glb",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        method="POST"
    )

    print("Submitting to Rodin...")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    task_uuid = result.get("uuid")
    if not task_uuid:
        print(f"Rodin error: {result}")
        return False

    # Poll for completion
    status_url = f"https://hyperhuman.deemos.com/api/v2/rodin/status/{task_uuid}"
    print(f"Task submitted: {task_uuid}")

    for attempt in range(120):  # Up to 10 minutes
        time.sleep(5)
        req = urllib.request.Request(
            status_url,
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = json.loads(resp.read())

        state = status.get("status", "unknown")
        print(f"  Status: {state} ({attempt * 5}s)")

        if state == "done":
            # Download the model
            download_url = status.get("output", {}).get("model", "")
            if download_url:
                urllib.request.urlretrieve(download_url, output_path)
                print(f"Model saved: {output_path}")
                return True
            print("No download URL in response")
            return False
        elif state == "failed":
            print(f"Generation failed: {status}")
            return False

    print("Timed out waiting for Rodin")
    return False


def generate_with_trellis(image_path: str, output_path: str):
    """Generate 3D model using Trellis (Gradio Space or local)"""
    trellis_url = os.environ.get("TRELLIS_API_URL")
    if not trellis_url:
        return False

    print(f"Using Trellis at {trellis_url}...")

    try:
        # pip install gradio_client if needed
        from gradio_client import Client, handle_file
        client = Client(trellis_url)
        result = client.predict(
            image=handle_file(image_path),
            api_name="/image_to_3d"
        )
        # Result is typically a file path
        import shutil
        if isinstance(result, str) and Path(result).exists():
            shutil.copy2(result, output_path)
            print(f"Model saved: {output_path}")
            return True
        elif isinstance(result, dict) and "value" in result:
            shutil.copy2(result["value"], output_path)
            return True
    except Exception as e:
        print(f"Trellis error: {e}")

    return False


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_image> <output_model.glb>")
        sys.exit(1)

    image_path = sys.argv[1]
    output_path = sys.argv[2]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Try backends in order
    backends = [
        ("Rodin", generate_with_rodin),
        ("Trellis", generate_with_trellis),
    ]

    for name, fn in backends:
        print(f"\nTrying {name}...")
        try:
            if fn(image_path, output_path):
                print(f"\n3D generation complete via {name}")
                return
        except Exception as e:
            print(f"{name} failed: {e}")

    print("\nERROR: No 3D generation backend available.")
    print("Set one of: RODIN_API_KEY, TRELLIS_API_URL")
    sys.exit(1)


if __name__ == "__main__":
    main()
