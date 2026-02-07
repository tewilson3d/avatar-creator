#!/usr/bin/env python3
"""Web server for Avatar Pipeline - Gemini image processing + Trellis 2 3D generation."""
import os
import sys
import json
import base64
import time
import threading
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 8000
WEB_DIR = Path(__file__).parent
BASE_DIR = Path(__file__).parent.parent
MODELS_DIR = BASE_DIR / "models"
ENV_FILE = BASE_DIR / ".env"


def load_env():
    """Load key=value pairs from .env file into os.environ."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
OUTPUT_DIR = Path(__file__).parent.parent / "output"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3-pro-image-preview"

PROMPT = (
    "Edit this image: Remove the entire background and replace it with a plain solid white background. "
    "Keep the character exactly as they are — same pose, same proportions, same details, same colors. "
    "Do not change, crop, or alter the character in any way. "
    "The output should be the full character cleanly isolated on a pure white (#FFFFFF) background, "
    "suitable as input for an AI 3D model generator."
)

# Async job tracking
jobs = {}  # job_id -> {"status": "running"|"done"|"error", "result": ..., "error": ...}
job_counter = 0
job_lock = threading.Lock()


def call_gemini(image_bytes: bytes, mime_type: str, prompt: str = "") -> tuple[bool, str]:
    """Send image to Gemini, return (success, base64_image_or_error)."""
    image_b64 = base64.b64encode(image_bytes).decode()
    text = prompt.strip() if prompt.strip() else PROMPT

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [
            {"inlineData": {"mimeType": mime_type, "data": image_b64}},
            {"text": text},
        ]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"], "temperature": 0.2},
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        return False, f"Gemini API error {e.code}: {body}"
    except Exception as e:
        return False, str(e)

    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                return True, part["inlineData"]["data"]
    return False, "Gemini returned no image"


def generate_3d_trellis(image_bytes: bytes, job_id: str):
    """Run Trellis 2 in background thread. Updates jobs[job_id]."""
    try:
        from gradio_client import Client, handle_file
        import tempfile
        import shutil

        tmp_img = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_img.write(image_bytes)
        tmp_img.close()

        try:
            print(f"[Job {job_id}] Connecting to Trellis 2...")
            jobs[job_id]["status"] = "connecting"
            client = Client("microsoft/TRELLIS.2")

            print(f"[Job {job_id}] Starting session...")
            jobs[job_id]["status"] = "starting"
            client.predict(api_name="/start_session")

            print(f"[Job {job_id}] Preprocessing image...")
            jobs[job_id]["status"] = "preprocessing"
            processed = client.predict(input=handle_file(tmp_img.name), api_name="/preprocess_image")

            seed = client.predict(randomize_seed=True, seed=0, api_name="/get_seed")
            print(f"[Job {job_id}] Seed: {seed}")

            print(f"[Job {job_id}] Generating 3D model...")
            jobs[job_id]["status"] = "generating"
            client.predict(
                image=processed, seed=seed, resolution="512",
                ss_guidance_strength=7.5, ss_guidance_rescale=0.7,
                ss_sampling_steps=12, ss_rescale_t=5.0,
                shape_slat_guidance_strength=7.5, shape_slat_guidance_rescale=0.5,
                shape_slat_sampling_steps=12, shape_slat_rescale_t=3.0,
                tex_slat_guidance_strength=1.0, tex_slat_guidance_rescale=0.0,
                tex_slat_sampling_steps=12, tex_slat_rescale_t=3.0,
                api_name="/image_to_3d"
            )

            print(f"[Job {job_id}] Extracting GLB...")
            jobs[job_id]["status"] = "extracting"
            result = client.predict(decimation_target=300000, texture_size=2048, api_name="/extract_glb")

            glb_source = result[0] if isinstance(result, (list, tuple)) else result
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            glb_dest = MODELS_DIR / f"trellis_{job_id}.glb"
            shutil.copy2(glb_source, glb_dest)

            print(f"[Job {job_id}] Done! {glb_dest}")
            jobs[job_id]["status"] = "done"
            jobs[job_id]["result"] = {"glb_url": f"/models/{glb_dest.name}", "filename": glb_dest.name}

        finally:
            os.unlink(tmp_img.name)

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Job {job_id}] ERROR: {e}")
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


def generate_comparison_blend(mesh_path: str, rig_path: str, output_path: str) -> tuple[bool, str]:
    """Run Blender to create a comparison .blend file."""
    import subprocess
    script = str(SCRIPTS_DIR / "save_comparison_blend.py")
    cmd = [
        "blender", "--background", "--python", script,
        "--", mesh_path, rig_path, output_path
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"Blender stderr: {result.stderr}")
        return False, result.stderr[-500:] if result.stderr else "Blender failed"
    print(f"Blend saved: {output_path}")
    return True, output_path


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith("/models/"):
            filename = self.path.split("/models/")[-1]
            filepath = MODELS_DIR / filename
            if filepath.exists() and filepath.suffix == ".glb":
                with open(filepath, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "model/gltf-binary")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        if self.path.startswith("/output/"):
            filename = self.path.split("/output/")[-1]
            filepath = OUTPUT_DIR / filename
            if filepath.exists():
                content_types = {
                    '.fbx': 'application/octet-stream',
                    '.blend': 'application/x-blender',
                    '.glb': 'model/gltf-binary',
                }
                ct = content_types.get(filepath.suffix, 'application/octet-stream')
                with open(filepath, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404, f"File not found: {filename}")
            return
        if self.path == "/api/outputs":
            return self._handle_list_outputs()
        if self.path == "/api/admin/config":
            return self._handle_get_config()
        if self.path == "/admin":
            return self._serve_admin()
        if self.path.startswith("/api/job/"):
            job_id = self.path.split("/api/job/")[-1]
            if job_id in jobs:
                self._json_response(jobs[job_id])
            else:
                self._json_response({"status": "not_found"}, 404)
            return
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/generate3d":
            return self._handle_generate3d()
        if self.path == "/api/process":
            return self._handle_process()
        if self.path == "/api/generate-blend":
            return self._handle_generate_blend()
        if self.path == "/api/admin/config":
            return self._handle_save_config()
        self.send_error(404)

    def _handle_process(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        boundary = content_type.split("boundary=")[-1].encode()
        parts = body.split(b"--" + boundary)

        image_bytes = None
        mime_type = "image/png"
        prompt = ""

        for part in parts:
            if b'name="image"' in part:
                if b"Content-Type: " in part:
                    ct_line = part.split(b"Content-Type: ")[1].split(b"\r\n")[0]
                    mime_type = ct_line.decode().strip()
                data_start = part.find(b"\r\n\r\n")
                if data_start != -1:
                    image_bytes = part[data_start + 4:].rstrip(b"\r\n--")
                    if image_bytes.endswith(b"--"): image_bytes = image_bytes[:-2]
                    if image_bytes.endswith(b"\r\n"): image_bytes = image_bytes[:-2]
            elif b'name="prompt"' in part:
                data_start = part.find(b"\r\n\r\n")
                if data_start != -1:
                    prompt = part[data_start + 4:].rstrip(b"\r\n--").decode("utf-8", errors="replace").strip()
                    if prompt.endswith("--"): prompt = prompt[:-2].strip()

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

    def _handle_generate3d(self):
        """Start async 3D generation, return job_id for polling."""
        global job_counter
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)

        image_b64 = data.get("image", "")
        if not image_b64:
            self._json_response({"success": False, "error": "No image provided"})
            return

        image_bytes = base64.b64decode(image_b64)

        with job_lock:
            job_counter += 1
            job_id = str(job_counter)

        jobs[job_id] = {"status": "queued"}
        thread = threading.Thread(target=generate_3d_trellis, args=(image_bytes, job_id), daemon=True)
        thread.start()

        self._json_response({"success": True, "job_id": job_id})

    def _handle_list_outputs(self):
        """List available output files."""
        files = []
        if OUTPUT_DIR.exists():
            for f in sorted(OUTPUT_DIR.iterdir()):
                if f.suffix in ('.fbx', '.blend', '.glb') and f.is_file():
                    files.append({
                        "name": f.name,
                        "url": f"/output/{f.name}",
                        "size": f.stat().st_size,
                        "type": f.suffix[1:],
                    })
        self._json_response({"files": files})

    def _handle_generate_blend(self):
        """Generate a comparison .blend with the output mesh + base rig."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body) if body else {}

        # Find the mesh to use — either specified or the latest rigged FBX
        mesh_name = data.get("mesh")
        if mesh_name:
            mesh_path = OUTPUT_DIR / mesh_name
        else:
            # Find latest rigged FBX in output
            fbx_files = sorted(OUTPUT_DIR.glob("*_rigged.fbx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not fbx_files:
                # Fallback: any GLB in models
                glb_files = sorted(MODELS_DIR.glob("*.glb"), key=lambda p: p.stat().st_mtime, reverse=True)
                if glb_files:
                    mesh_path = glb_files[0]
                else:
                    self._json_response({"success": False, "error": "No output mesh found"})
                    return
            else:
                mesh_path = fbx_files[0]

        rig_path = TEMPLATES_DIR / "rig.fbx"
        if not rig_path.exists():
            self._json_response({"success": False, "error": "Base rig.fbx not found"})
            return

        if not mesh_path.exists():
            self._json_response({"success": False, "error": f"Mesh not found: {mesh_path.name}"})
            return

        blend_name = mesh_path.stem + "_comparison.blend"
        blend_path = OUTPUT_DIR / blend_name

        success, result = generate_comparison_blend(str(mesh_path), str(rig_path), str(blend_path))
        if success:
            self._json_response({
                "success": True,
                "url": f"/output/{blend_name}",
                "filename": blend_name,
            })
        else:
            self._json_response({"success": False, "error": result})

    def _handle_get_config(self):
        """Return current config (keys masked)."""
        config = {}
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    config[k.strip()] = v.strip()
        # Return with masked values for display, full values for editing
        items = []
        for k, v in config.items():
            masked = v[:8] + '...' + v[-4:] if len(v) > 16 else '****'
            items.append({"key": k, "value": v, "masked": masked})
        self._json_response({"config": items})

    def _handle_save_config(self):
        """Save config to .env file."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        entries = data.get("config", {})
        lines = []
        for k, v in entries.items():
            lines.append(f"{k}={v}")
        ENV_FILE.write_text('\n'.join(lines) + '\n')
        # Reload into environment
        for k, v in entries.items():
            os.environ[k] = v
        # Update the global API key
        global GEMINI_API_KEY
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        self._json_response({"success": True})

    def _serve_admin(self):
        """Serve the admin page."""
        admin_path = WEB_DIR / "admin.html"
        if admin_path.exists():
            data = admin_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)


def main():
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set")
        sys.exit(1)
    server = HTTPServer(("", PORT), Handler)
    print(f"Server running on http://localhost:{PORT}", flush=True)
    print(f"Gemini model: {MODEL}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
