"""Gemini API client for image processing.

Shared by step1_gemini_process.py and web/server.py.
"""
import base64
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

# Gemini model with native image output
DEFAULT_MODELS = [
    "gemini-3-pro-image-preview",
    "gemini-2.0-flash-exp-image-generation",
]

DEFAULT_BG_REMOVAL_PROMPT = (
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


def call_gemini_once(
    api_key: str,
    model: str,
    image_b64: str,
    mime_type: str,
    prompt: str,
    temperature: float = 0.2,
) -> tuple[bool, str | bytes, bool]:
    """Single Gemini API call.

    Returns:
        (success, result, content_blocked)
        - On success: result is image bytes
        - On failure: result is error string, content_blocked indicates policy block
    """
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [{"parts": [
            {"inlineData": {"mimeType": mime_type, "data": image_b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
            "temperature": temperature,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        return False, f"Gemini API error {e.code}: {body}", False
    except Exception as e:
        return False, str(e), False

    # Check for blocked content
    if "promptFeedback" in result:
        block_reason = result["promptFeedback"].get("blockReason", "")
        if block_reason:
            print(f"  Gemini blocked: {block_reason}")
            return False, f"Gemini blocked the request: {block_reason}", True

    # Extract image and text from response
    gemini_text = ""
    content_blocked = False
    for candidate in result.get("candidates", []):
        finish_reason = candidate.get("finishReason", "")
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                img_bytes = base64.b64decode(part["inlineData"]["data"])
                return True, img_bytes, False
            if "text" in part:
                gemini_text = part["text"]
                print(f"  Gemini text: {gemini_text[:200]}")
        if finish_reason == "OTHER":
            print(f"  Gemini finishReason: OTHER (content filter)")
            content_blocked = True
        elif finish_reason and finish_reason != "STOP":
            print(f"  Gemini finishReason: {finish_reason}")

    if content_blocked:
        msg = (
            "Gemini's content filter blocked image generation. "
            "This often happens with copyrighted characters (e.g. Marvel, Disney) "
            "or content that triggers safety filters. Try rephrasing your description "
            "to avoid trademarked names."
        )
        if gemini_text:
            msg += f" Gemini said: {gemini_text[:200]}"
        return False, msg, True
    if gemini_text:
        return False, f"Gemini returned text instead of image: {gemini_text[:300]}", False
    return False, "Gemini returned no image (empty response)", False


def call_gemini_with_retry(
    api_key: str,
    image_b64: str,
    mime_type: str,
    prompt: str,
    model: str | None = None,
    models: list[str] | None = None,
    max_retries: int = 3,
    temperature: float = 0.2,
) -> tuple[bool, str | bytes]:
    """Call Gemini with retry logic and optional model fallback.

    Args:
        api_key: Gemini API key
        image_b64: Base64-encoded image data
        mime_type: Image MIME type
        prompt: Text prompt
        model: Single model to use (if set, no fallback chain)
        models: List of models to try in order (fallback chain)
        max_retries: Retries per model
        temperature: Generation temperature

    Returns:
        (success, result) where result is image bytes on success or error string on failure
    """
    if model:
        model_list = [model]
    elif models:
        model_list = models
    else:
        model_list = DEFAULT_MODELS

    last_error = ""
    for m in model_list:
        for attempt in range(1, max_retries + 1):
            print(f"  Gemini attempt {attempt}/{max_retries} (model: {m})...")
            success, result, content_blocked = call_gemini_once(
                api_key, m, image_b64, mime_type, prompt, temperature
            )
            if success:
                return True, result
            last_error = result
            print(f"  Attempt {attempt} failed: {str(last_error)[:200]}")
            # Don't retry content policy blocks
            if content_blocked:
                return False, last_error
            if attempt < max_retries:
                time.sleep(2)

    return False, last_error
