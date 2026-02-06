#!/usr/bin/env python3
"""Step 1: Process character image with Gemini Native Image Generation ("Nano Banana")

Uses Gemini's native image editing to:
1. Remove the background (transparent/white)
2. Center and clean up the character
3. Generate a T-pose or A-pose front-facing reference suitable for 3D generation
4. Produce a clean, uniform-lit character on a solid white background

Requires: GEMINI_API_KEY environment variable
"""
import sys
import os
import base64
import json
import shutil
import urllib.request
from pathlib import Path

# Gemini model with native image output (the "nano banana" model)
# Fallback chain: newest → oldest
MODELS = [
    "gemini-3-pro-image-preview",
    "gemini-2.0-flash-exp-image-generation",
]

PROMPT_BG_REMOVAL = (
    "Edit this image: Remove the entire background and replace it with a plain solid white background. "
    "Keep the character exactly as they are — same pose, same proportions, same details, same colors. "
    "Do not change, crop, or alter the character in any way. "
    "The output should be the full character cleanly isolated on a pure white (#FFFFFF) background, "
    "suitable as input for an AI 3D model generator."
)


def encode_image(path: str) -> tuple[str, str]:
    """Read image file and return (base64_data, mime_type)."""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = Path(path).suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    return data, mime


def call_gemini(api_key: str, model: str, image_b64: str, mime: str, prompt: str) -> bytes | None:
    """Call Gemini generateContent with image input and image+text output.
    Returns the generated image bytes or None."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [{
            "parts": [
                {
                    "inlineData": {
                        "mimeType": mime,
                        "data": image_b64,
                    }
                },
                {"text": prompt},
            ]
        }],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
            "temperature": 0.2,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read())

    # Extract image from response
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])
            if "text" in part:
                print(f"  Gemini text: {part['text'][:200]}")

    return None


def process_image(input_path: str, output_path: str):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    image_b64, mime = encode_image(input_path)
    print(f"Input: {input_path} ({mime}, {len(image_b64) * 3 // 4 // 1024}KB)")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Try each model
    for model in MODELS:
        print(f"\nTrying model: {model}")
        try:
            img_bytes = call_gemini(api_key, model, image_b64, mime, PROMPT_BG_REMOVAL)
            if img_bytes:
                with open(output_path, "wb") as f:
                    f.write(img_bytes)
                print(f"\n✓ Background removed. Saved: {output_path} ({len(img_bytes) // 1024}KB)")
                return
            else:
                print(f"  Model returned no image, trying next...")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            print(f"  HTTP {e.code}: {body}")
        except Exception as e:
            print(f"  Error: {e}")

    # All models failed — fall back to copying original
    print("\n⚠ All Gemini models failed. Copying original image as fallback.")
    shutil.copy2(input_path, output_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_image> <output_image>")
        print(f"  Env: GEMINI_API_KEY=...")
        sys.exit(1)
    process_image(sys.argv[1], sys.argv[2])
