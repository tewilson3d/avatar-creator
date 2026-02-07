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
RODIN_API_KEY = os.environ.get("RODIN_API_KEY", "")
MODEL = "gemini-3-pro-image-preview"
RODIN_BASE_URL = "https://api.hyper3d.com/api/v2"

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


def _rodin_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build multipart/form-data body."""
    import uuid as _uuid
    boundary = f"----PipelineBoundary{_uuid.uuid4().hex}"
    body = b""
    for key, value in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
    for key, (filename, data, mime) in files.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def generate_3d_rodin(image_bytes: bytes, job_id: str, source_image_path: str = None):
    """Full pipeline in background thread: Rodin → Scale → Rig Transfer → .blend
    Updates jobs[job_id] with status throughout."""
    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # =====================================================================
        # Phase 1: Rodin 3D Generation
        # =====================================================================
        print(f"[Job {job_id}] Submitting to Rodin Sketch...")
        jobs[job_id]["status"] = "submitting"

        fields = {"tier": "Sketch", "geometry_file_format": "glb", "material": "PBR"}
        files_data = {"images": ("character.png", image_bytes, "image/png")}
        body, content_type = _rodin_multipart(fields, files_data)

        req = urllib.request.Request(
            f"{RODIN_BASE_URL}/rodin", data=body,
            headers={"Authorization": f"Bearer {RODIN_API_KEY}", "Content-Type": content_type},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())

        if result.get("error"):
            raise Exception(f"Rodin error: {result['error']} - {result.get('message', '')}")

        task_uuid = result["uuid"]
        subscription_key = result["jobs"]["subscription_key"]
        print(f"[Job {job_id}] Task UUID: {task_uuid}")

        jobs[job_id]["status"] = "generating"
        start = time.time()
        while time.time() - start < 300:
            time.sleep(5)
            req = urllib.request.Request(
                f"{RODIN_BASE_URL}/status",
                data=json.dumps({"subscription_key": subscription_key}).encode(),
                headers={"Authorization": f"Bearer {RODIN_API_KEY}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                status_result = json.loads(resp.read())

            job_list = status_result.get("jobs", [])
            for j in job_list:
                elapsed = int(time.time() - start)
                print(f"  [{elapsed}s] Job {j['uuid']}: {j['status']}")

            if job_list and all(j["status"] in ("Done", "Failed") for j in job_list):
                if any(j["status"] == "Failed" for j in job_list):
                    raise Exception("Rodin job failed")
                break
        else:
            raise Exception("Rodin timed out after 300s")

        print(f"[Job {job_id}] Downloading Rodin results...")
        jobs[job_id]["status"] = "downloading"
        req = urllib.request.Request(
            f"{RODIN_BASE_URL}/download",
            data=json.dumps({"task_uuid": task_uuid}).encode(),
            headers={"Authorization": f"Bearer {RODIN_API_KEY}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            dl_result = json.loads(resp.read())

        raw_glb = None
        for item in dl_result.get("list", []):
            name = item["name"]
            dest = MODELS_DIR / f"job{job_id}_raw_{name}"
            urllib.request.urlretrieve(item["url"], str(dest))
            print(f"  Downloaded: {dest}")
            if name.endswith(".glb"):
                raw_glb = dest

        if not raw_glb:
            raise Exception("No GLB file in Rodin output")

        print(f"[Job {job_id}] Raw mesh: {raw_glb}")

        # =====================================================================
        # Phase 2: Scale (if we have source image with alpha)
        # =====================================================================
        scaled_glb = MODELS_DIR / f"job{job_id}_scaled.glb"
        if source_image_path and Path(source_image_path).exists():
            print(f"[Job {job_id}] Scaling mesh...")
            jobs[job_id]["status"] = "scaling"
            ok, msg = run_blender_script("step3_scale.py",
                [str(raw_glb), str(scaled_glb), source_image_path],
                label=f"Job {job_id} Scale")
            if not ok:
                print(f"[Job {job_id}] Scale failed, using raw mesh: {msg}")
                scaled_glb = raw_glb
        else:
            print(f"[Job {job_id}] No source image for scaling, using raw mesh")
            scaled_glb = raw_glb

        # =====================================================================
        # Phase 3: Rig Transfer
        # =====================================================================
        rig_path = TEMPLATES_DIR / "rig.fbx"
        rigged_fbx = OUTPUT_DIR / f"job{job_id}_rigged.fbx"

        print(f"[Job {job_id}] Transferring rig...")
        jobs[job_id]["status"] = "rigging"
        ok, msg = run_blender_script("step5_rig_transfer.py",
            [str(scaled_glb), str(rig_path), str(rigged_fbx)],
            label=f"Job {job_id} Rig")
        if not ok:
            raise Exception(f"Rig transfer failed: {msg}")

        # =====================================================================
        # Phase 4: Comparison .blend
        # =====================================================================
        comparison_blend = OUTPUT_DIR / f"job{job_id}_comparison.blend"

        print(f"[Job {job_id}] Saving comparison .blend...")
        jobs[job_id]["status"] = "saving_blend"
        ok, msg = run_blender_script("save_comparison_blend.py",
            [str(rigged_fbx), str(rig_path), str(comparison_blend)],
            label=f"Job {job_id} Blend")
        if not ok:
            print(f"[Job {job_id}] Comparison blend failed (non-fatal): {msg}")
            comparison_blend = None

        # =====================================================================
        # Done!
        # =====================================================================
        print(f"[Job {job_id}] Pipeline complete!")
        jobs[job_id]["status"] = "done"
        result_data = {
            "glb_url": f"/models/{raw_glb.name}",
            "glb_filename": raw_glb.name,
            "fbx_url": f"/output/{rigged_fbx.name}",
            "fbx_filename": rigged_fbx.name,
        }
        if comparison_blend and comparison_blend.exists():
            result_data["blend_url"] = f"/output/{comparison_blend.name}"
            result_data["blend_filename"] = comparison_blend.name
        jobs[job_id]["result"] = result_data

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Job {job_id}] ERROR: {e}")
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


def run_blender_script(script_name: str, args: list[str], label: str = "") -> tuple[bool, str]:
    """Run a Blender script. Returns (success, stdout_or_error)."""
    import subprocess
    script = str(SCRIPTS_DIR / script_name)
    cmd = ["blender", "--background", "--python", script, "--"] + args
    print(f"[{label}] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    print(result.stdout[-1000:] if result.stdout else "")
    if result.returncode != 0:
        err = result.stderr[-500:] if result.stderr else "Blender failed"
        print(f"[{label}] FAILED: {err}")
        return False, err
    print(f"[{label}] Done")
    return True, result.stdout


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
        """Start async full pipeline: Rodin → Scale → Rig → .blend. Returns job_id for polling."""
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

        # Save processed image for the scale step (needs alpha bbox)
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        source_image_path = str(MODELS_DIR / f"job{job_id}_source.png")
        with open(source_image_path, "wb") as f:
            f.write(image_bytes)

        jobs[job_id] = {"status": "queued"}
        thread = threading.Thread(
            target=generate_3d_rodin,
            args=(image_bytes, job_id, source_image_path),
            daemon=True
        )
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
        # Update global API keys
        global GEMINI_API_KEY, RODIN_API_KEY
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        RODIN_API_KEY = os.environ.get("RODIN_API_KEY", "")
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
