#!/usr/bin/env python3
"""Web server for Avatar Pipeline - Gemini image processing UI."""
import os
import sys
import json
import base64
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 8000
WEB_DIR = Path(__file__).parent
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3-pro-image-preview"

PROMPT = (
    "Edit this image: Remove the entire background and replace it with a plain solid white background. "
    "Keep the character exactly as they are — same pose, same proportions, same details, same colors. "
    "Do not change, crop, or alter the character in any way. "
    "The output should be the full character cleanly isolated on a pure white (#FFFFFF) background, "
    "suitable as input for an AI 3D model generator."
)


def call_gemini(image_bytes: bytes, mime_type: str, prompt: str = "") -> tuple[bool, str]:
    """Send image to Gemini, return (success, base64_image_or_error)."""
    image_b64 = base64.b64encode(image_bytes).decode()
    text = prompt.strip() if prompt.strip() else PROMPT

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": image_b64}},
                {"text": text},
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

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        return False, f"Gemini API error {e.code}: {body}"
    except Exception as e:
        return False, str(e)

    # Extract image
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                return True, part["inlineData"]["data"]

    return False, "Gemini returned no image"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_POST(self):
        if self.path != "/api/process":
            self.send_error(404)
            return

        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Parse multipart form data
        boundary = content_type.split("boundary=")[-1].encode()
        parts = body.split(b"--" + boundary)

        image_bytes = None
        mime_type = "image/png"
        prompt = ""

        for part in parts:
            if b"name=\"image\"" in part:
                # Find content type
                if b"Content-Type: " in part:
                    ct_line = part.split(b"Content-Type: ")[1].split(b"\r\n")[0]
                    mime_type = ct_line.decode().strip()
                # Extract binary data (after double CRLF)
                data_start = part.find(b"\r\n\r\n")
                if data_start != -1:
                    image_bytes = part[data_start + 4:].rstrip(b"\r\n--")
                    if image_bytes.endswith(b"--"):
                        image_bytes = image_bytes[:-2]
                    if image_bytes.endswith(b"\r\n"):
                        image_bytes = image_bytes[:-2]
            elif b"name=\"prompt\"" in part:
                data_start = part.find(b"\r\n\r\n")
                if data_start != -1:
                    prompt = part[data_start + 4:].rstrip(b"\r\n--").decode("utf-8", errors="replace").strip()
                    if prompt.endswith("--"):
                        prompt = prompt[:-2].strip()

        if not image_bytes:
            self._json_response({"success": False, "error": "No image in request"})
            return

        print(f"Processing image: {len(image_bytes)} bytes, {mime_type}")
        print(f"Prompt: {prompt[:100]}..." if len(prompt) > 100 else f"Prompt: {prompt}")
        success, result = call_gemini(image_bytes, mime_type, prompt)

        if success:
            self._json_response({"success": True, "image": result})
        else:
            self._json_response({"success": False, "error": result})

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def main():
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set")
        sys.exit(1)

    server = HTTPServer(("", PORT), Handler)
    print(f"Server running on http://localhost:{PORT}")
    print(f"Gemini model: {MODEL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
