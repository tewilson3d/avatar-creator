#!/usr/bin/env python3
"""Step 1: Process character image with Gemini (Nano Banana)

Prepares the image for 3D generation:
- Remove background
- Normalize pose/lighting
- Generate clean front-facing reference
"""
import sys
import os
import base64
import json
import urllib.request
from pathlib import Path


def process_with_gemini(input_path: str, output_path: str):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    # Read and encode input image
    with open(input_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # Determine MIME type
    ext = Path(input_path).suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/png")

    # Gemini API request - image editing/generation
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"

    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": image_data}},
                {"text": (
                    "Process this character image for 3D model generation. "
                    "Remove the background to pure white. "
                    "Ensure the character is centered and well-lit. "
                    "Clean up any artifacts. "
                    "Return the processed image."
                )}
            ]
        }],
        "generationConfig": {
            "responseModalities": ["image", "text"],
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    print(f"Sending image to Gemini for processing...")
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    # Extract generated image from response
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                img_bytes = base64.b64decode(part["inlineData"]["data"])
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(img_bytes)
                print(f"Processed image saved: {output_path}")
                return

    # If no image returned, copy original
    print("WARNING: Gemini did not return an image, using original")
    import shutil
    shutil.copy2(input_path, output_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_image> <output_image>")
        sys.exit(1)
    process_with_gemini(sys.argv[1], sys.argv[2])
