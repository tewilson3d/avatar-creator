#!/usr/bin/env python3
"""Step 1: Process character image with Gemini Native Image Generation

Uses Gemini's native image editing to remove the background and
produce a clean character on solid white, suitable for 3D generation.

Requires: GEMINI_API_KEY environment variable
"""
import sys
import os
import shutil
from pathlib import Path

# Allow imports from scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.gemini import encode_image, call_gemini_with_retry, DEFAULT_BG_REMOVAL_PROMPT


def process_image(input_path: str, output_path: str):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    image_b64, mime = encode_image(input_path)
    print(f"Input: {input_path} ({mime}, {len(image_b64) * 3 // 4 // 1024}KB)")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    success, result = call_gemini_with_retry(
        api_key=api_key,
        image_b64=image_b64,
        mime_type=mime,
        prompt=DEFAULT_BG_REMOVAL_PROMPT,
    )

    if success:
        with open(output_path, "wb") as f:
            f.write(result)
        print(f"\n\u2713 Background removed. Saved: {output_path} ({len(result) // 1024}KB)")
    else:
        print(f"\n\u26a0 All Gemini models failed: {result}")
        print("Copying original image as fallback.")
        shutil.copy2(input_path, output_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_image> <output_image>")
        print(f"  Env: GEMINI_API_KEY=...")
        sys.exit(1)
    process_image(sys.argv[1], sys.argv[2])
