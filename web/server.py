#!/usr/bin/env python3
"""Web server for Avatar Pipeline - Gemini image processing + Rodin 3D generation."""
import os
import sys
import json
import base64
import time
import hashlib
import secrets
import subprocess
import threading
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Allow imports from scripts/ directory
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib.gemini import call_gemini_with_retry
from lib.meshy import submit_task, poll_status, download_results

PORT = 8000
WEB_DIR = Path(__file__).parent
BASE_DIR = Path(__file__).parent.parent
MODELS_DIR = BASE_DIR / "models"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MESHY_API_KEY = os.environ.get("MESHY_API_KEY", "")
GEMINI_MODEL = "gemini-3-pro-image-preview"

DEFAULT_GEMINI_PROMPT_PREFIX = (
    "keep the exact same style, proportions and pose, please change the character to look the following, "
    "no matter what the prompt says keep all hair styles short, "
    "absolutely no hats or head wear, absolutely no headwear that protrudes the head silhouette "
    "from any costume or head design or literal prompt, on a solid white background."
)
GEMINI_PROMPT_PREFIX = os.environ.get("GEMINI_PROMPT_PREFIX", DEFAULT_GEMINI_PROMPT_PREFIX)
SHOW_BASE_IMAGE = os.environ.get("SHOW_BASE_IMAGE", "true").lower() == "true"

# Async job tracking
jobs = {}  # job_id -> {"status": ..., "result": ..., "error": ...}
job_counter = 0
job_lock = threading.Lock()

# Admin auth
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "andyprez69")
admin_sessions = set()  # valid session tokens


# =============================================================================
# GEMINI WRAPPER (uses shared lib)
# =============================================================================

def call_gemini(image_bytes: bytes, mime_type: str, prompt: str = "") -> tuple[bool, str]:
    """Send image to Gemini with retry. Returns (success, base64_image_or_error)."""
    image_b64 = base64.b64encode(image_bytes).decode()
    text = prompt.strip() if prompt.strip() else GEMINI_PROMPT_PREFIX

    success, result = call_gemini_with_retry(
        api_key=GEMINI_API_KEY,
        image_b64=image_b64,
        mime_type=mime_type,
        prompt=text,
        model=GEMINI_MODEL,
        max_retries=3,
    )

    if success:
        # Return base64-encoded for JSON response
        return True, base64.b64encode(result).decode()
    return False, result


# =============================================================================
# 3D PIPELINE (uses shared lib)
# =============================================================================

def generate_3d_rodin(image_bytes: bytes, job_id: str, source_image_path: str = None):
    """Full pipeline in background thread: Rodin → Scale → Rig Transfer → .blend"""
    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Phase 1: Meshy 3D Generation
        print(f"[Job {job_id}] Submitting to Meshy...")
        jobs[job_id]["status"] = "submitting"

        task = submit_task(
            api_key=MESHY_API_KEY,
            image_bytes=image_bytes,
            filename="character.png",
            mime_type="image/png",
        )
        task_uuid = task["job_id"]
        task_endpoint = task["endpoint"]
        print(f"[Job {job_id}] Meshy Task ID: {task_uuid}")

        jobs[job_id]["status"] = "generating"
        if not poll_status(MESHY_API_KEY, task_uuid, timeout_sec=300, endpoint=task_endpoint):
            raise Exception("Meshy job failed or timed out")

        print(f"[Job {job_id}] Downloading Meshy results...")
        jobs[job_id]["status"] = "downloading"
        downloaded = download_results(MESHY_API_KEY, task_uuid, str(MODELS_DIR), endpoint=task_endpoint)

        # Rename downloaded files with job prefix
        raw_glb = None
        for src_path in downloaded:
            name = os.path.basename(src_path)
            dest = MODELS_DIR / f"job{job_id}_raw_{name}"
            if src_path != str(dest):
                os.rename(src_path, dest)
            print(f"  Saved: {dest}")
            if name.endswith(".glb"):
                raw_glb = dest

        if not raw_glb:
            raise Exception("No GLB file in Rodin output")

        print(f"[Job {job_id}] Raw mesh: {raw_glb}")

        # Phase 2: Scale
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

        # Phase 3: Retopology (TEMPORARILY DISABLED)
        retopo_glb = scaled_glb
        print(f"[Job {job_id}] Retopology SKIPPED (temporarily disabled)")

        # Phase 4: Rig Transfer
        rig_path = TEMPLATES_DIR / "rig.fbx"
        rigged_fbx = OUTPUT_DIR / f"job{job_id}_rigged.fbx"

        print(f"[Job {job_id}] Transferring rig...")
        jobs[job_id]["status"] = "rigging"
        ok, msg = run_blender_script("step5_rig_transfer.py",
            [str(retopo_glb), str(rig_path), str(rigged_fbx)],
            label=f"Job {job_id} Rig")
        if not ok:
            print(f"[Job {job_id}] Rig transfer failed (non-fatal, returning raw GLB): {msg}")
            rigged_fbx = None

        # Phase 5: Comparison .blend (only if rig succeeded)
        comparison_blend = None
        if rigged_fbx and rigged_fbx.exists():
            blend_path = OUTPUT_DIR / f"job{job_id}_comparison.blend"
            print(f"[Job {job_id}] Saving comparison .blend...")
            jobs[job_id]["status"] = "saving_blend"
            ok, msg = run_blender_script("save_comparison_blend.py",
                [str(rigged_fbx), str(rig_path), str(blend_path)],
                label=f"Job {job_id} Blend")
            if ok:
                comparison_blend = blend_path

        # Done!
        print(f"[Job {job_id}] Pipeline complete!")
        jobs[job_id]["status"] = "done"
        result_data = {
            "glb_url": f"/models/{raw_glb.name}",
            "glb_filename": raw_glb.name,
        }
        if rigged_fbx and rigged_fbx.exists():
            result_data["fbx_url"] = f"/output/{rigged_fbx.name}"
            result_data["fbx_filename"] = rigged_fbx.name
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
    blender = os.environ.get("BLENDER_PATH", "blender")
    script = str(SCRIPTS_DIR / script_name)
    cmd = [blender, "--background", "--python", script, "--"] + args
    print(f"[{label}] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        print(f"[{label}] SKIPPED: Blender not found on PATH")
        return False, "Blender not installed or not on PATH"
    print(result.stdout[-1000:] if result.stdout else "")
    if result.returncode != 0:
        err = result.stderr[-500:] if result.stderr else "Blender failed"
        print(f"[{label}] FAILED: {err}")
        return False, err
    print(f"[{label}] Done")
    return True, result.stdout


# =============================================================================
# HTTP HANDLER
# =============================================================================

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    # --- Auth helpers ---

    def _get_session(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("admin_session="):
                return part.split("=", 1)[1]
        return None

    def _is_admin_authed(self):
        token = self._get_session()
        return token in admin_sessions if token else False

    def _require_admin(self):
        if self._is_admin_authed():
            return True
        self._json_response({"error": "Unauthorized"}, 401)
        return False

    # --- Response helpers ---

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filepath, content_type=None, attachment=False):
        if not filepath.exists():
            self.send_error(404, f"File not found: {filepath.name}")
            return
        data = filepath.read_bytes()
        ct_map = {
            '.glb': 'model/gltf-binary', '.fbx': 'application/octet-stream',
            '.blend': 'application/x-blender', '.html': 'text/html',
            '.py': 'text/x-python',
        }
        if not content_type:
            content_type = ct_map.get(filepath.suffix, 'application/octet-stream')
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
        self.end_headers()
        self.wfile.write(data)

    # --- Routing ---

    def do_GET(self):
        if self.path.startswith("/models/"):
            filename = self.path.split("/models/")[-1]
            filepath = MODELS_DIR / filename
            if filepath.exists() and filepath.suffix == ".glb":
                return self._serve_file(filepath)
        if self.path == "/scripts/combined_scale_retopo_rig.py":
            return self._serve_file(SCRIPTS_DIR / "combined_scale_retopo_rig.py", attachment=True)
        if self.path.startswith("/output/"):
            filename = self.path.split("/output/")[-1]
            return self._serve_file(OUTPUT_DIR / filename, attachment=True)
        if self.path == "/api/outputs":
            return self._handle_list_outputs()
        if self.path == "/admin/login":
            return self._serve_file(WEB_DIR / "admin_login.html")
        if self.path == "/api/admin/check":
            return self._json_response({"authed": self._is_admin_authed()})
        if self.path == "/admin":
            if not self._is_admin_authed():
                self.send_response(302)
                self.send_header("Location", "/admin/login")
                self.end_headers()
                return
            return self._serve_file(WEB_DIR / "admin.html")
        if self.path == "/api/admin/config":
            if not self._require_admin(): return
            return self._handle_get_config()
        if self.path == "/api/admin/prompt-prefix":
            if not self._require_admin(): return
            return self._handle_get_prompt_prefix()
        if self.path == "/api/admin/settings":
            if not self._require_admin(): return
            return self._handle_get_settings()
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
        if self.path == "/api/admin/login":
            return self._handle_login()
        if self.path == "/api/admin/logout":
            return self._handle_logout()
        if self.path == "/api/admin/config":
            if not self._require_admin(): return
            return self._handle_save_config()
        if self.path == "/api/admin/prompt-prefix":
            if not self._require_admin(): return
            return self._handle_save_prompt_prefix()
        if self.path == "/api/admin/settings":
            if not self._require_admin(): return
            return self._handle_save_settings()
        if self.path == "/api/admin/cleanup":
            if not self._require_admin(): return
            return self._handle_cleanup()
        self.send_error(404)

    # --- API: Image processing ---

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

        final_prompt = (GEMINI_PROMPT_PREFIX + " " + prompt.strip()) if prompt.strip() else GEMINI_PROMPT_PREFIX
        print(f"Processing image: {len(image_bytes)} bytes, {mime_type}")
        print(f"Final prompt: {final_prompt[:200]}..." if len(final_prompt) > 200 else f"Final prompt: {final_prompt}")

        success, result = call_gemini(image_bytes, mime_type, final_prompt)
        if success:
            self._json_response({"success": True, "image": result})
        else:
            self._json_response({"success": False, "error": result})

    # --- API: 3D Generation ---

    def _handle_generate3d(self):
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

        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        source_image_path = str(MODELS_DIR / f"job{job_id}_source.png")
        with open(source_image_path, "wb") as f:
            f.write(image_bytes)

        jobs[job_id] = {"status": "queued"}
        thread = threading.Thread(
            target=generate_3d_rodin,
            args=(image_bytes, job_id, source_image_path),
            daemon=True,
        )
        thread.start()

        self._json_response({"success": True, "job_id": job_id})

    def _handle_list_outputs(self):
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
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body) if body else {}

        mesh_name = data.get("mesh")
        if mesh_name:
            mesh_path = OUTPUT_DIR / mesh_name
        else:
            fbx_files = sorted(OUTPUT_DIR.glob("*_rigged.fbx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not fbx_files:
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

        ok, msg = run_blender_script("save_comparison_blend.py",
            [str(mesh_path), str(rig_path), str(blend_path)],
            label="Generate Blend")
        if ok:
            self._json_response({"success": True, "url": f"/output/{blend_name}", "filename": blend_name})
        else:
            self._json_response({"success": False, "error": msg})

    # --- API: Admin ---

    def _handle_login(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        if data.get("username") == ADMIN_USER and data.get("password") == ADMIN_PASS:
            token = secrets.token_hex(32)
            admin_sessions.add(token)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"admin_session={token}; Path=/; HttpOnly; SameSite=Strict")
            body = json.dumps({"success": True}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print("Admin login successful")
        else:
            self._json_response({"success": False, "error": "Invalid credentials"}, 401)

    def _handle_logout(self):
        token = self._get_session()
        if token:
            admin_sessions.discard(token)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "admin_session=; Path=/; HttpOnly; Max-Age=0")
        body = json.dumps({"success": True}).encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_get_config(self):
        config = {}
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    config[k.strip()] = v.strip()
        items = []
        for k, v in config.items():
            if k in ("GEMINI_PROMPT_PREFIX", "SHOW_BASE_IMAGE"):
                continue
            masked = v[:8] + '...' + v[-4:] if len(v) > 16 else '****'
            items.append({"key": k, "value": v, "masked": masked})
        self._json_response({"config": items})

    def _handle_save_config(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        entries = data.get("config", {})
        lines = [f"{k}={v}" for k, v in entries.items()]
        ENV_FILE.write_text('\n'.join(lines) + '\n')
        for k, v in entries.items():
            os.environ[k] = v
        global GEMINI_API_KEY, MESHY_API_KEY
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        MESHY_API_KEY = os.environ.get("MESHY_API_KEY", "")
        self._json_response({"success": True})

    def _handle_get_settings(self):
        self._json_response({"show_base_image": SHOW_BASE_IMAGE})

    def _handle_save_settings(self):
        global SHOW_BASE_IMAGE
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        if "show_base_image" in data:
            SHOW_BASE_IMAGE = bool(data["show_base_image"])
            os.environ["SHOW_BASE_IMAGE"] = str(SHOW_BASE_IMAGE).lower()
            _update_env_key("SHOW_BASE_IMAGE", str(SHOW_BASE_IMAGE).lower())
            print(f"Updated SHOW_BASE_IMAGE: {SHOW_BASE_IMAGE}")
        self._json_response({"success": True})

    def _handle_cleanup(self):
        deleted = []
        for directory in [MODELS_DIR, OUTPUT_DIR]:
            if not directory.exists():
                continue
            for f in directory.iterdir():
                if f.is_file() and f.suffix != '.gitkeep':
                    try:
                        f.unlink()
                        deleted.append(str(f.relative_to(BASE_DIR)))
                    except Exception as e:
                        print(f"Failed to delete {f}: {e}")
        global jobs, job_counter
        jobs = {}
        job_counter = 0
        print(f"Cleanup: deleted {len(deleted)} files")
        self._json_response({"success": True, "deleted": len(deleted), "files": deleted})

    def _handle_get_prompt_prefix(self):
        self._json_response({"prefix": GEMINI_PROMPT_PREFIX})

    def _handle_save_prompt_prefix(self):
        global GEMINI_PROMPT_PREFIX
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        new_prefix = data.get("prefix", "").strip()
        if not new_prefix:
            self._json_response({"success": False, "error": "Prefix cannot be empty"})
            return
        GEMINI_PROMPT_PREFIX = new_prefix
        os.environ["GEMINI_PROMPT_PREFIX"] = new_prefix
        _update_env_key("GEMINI_PROMPT_PREFIX", new_prefix)
        print(f"Updated GEMINI_PROMPT_PREFIX: {new_prefix[:80]}...")
        self._json_response({"success": True})

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)


# =============================================================================
# .env helpers
# =============================================================================

def _update_env_key(key, value):
    """Update a single key in the .env file."""
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text().splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        ENV_FILE.write_text('\n'.join(lines) + '\n')
    else:
        ENV_FILE.write_text(f"{key}={value}\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set")
        sys.exit(1)
    server = HTTPServer(("", PORT), Handler)
    print(f"Server running on http://localhost:{PORT}", flush=True)
    print(f"Gemini model: {GEMINI_MODEL}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
