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
from lib.rodin import make_multipart, submit_task, poll_status, download_results

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
RODIN_API_KEY = os.environ.get("RODIN_API_KEY", "")
GEMINI_MODEL = "gemini-3-pro-image-preview"

DEFAULT_GEMINI_PROMPT_PREFIX = (
    "keep the exact same style, proportions and pose, please change the character "
    "to look the following, but do not add a face:"
)
GEMINI_PROMPT_PREFIX = os.environ.get("GEMINI_PROMPT_PREFIX", DEFAULT_GEMINI_PROMPT_PREFIX)
SHOW_BASE_IMAGE = os.environ.get("SHOW_BASE_IMAGE", "true").lower() == "true"

# Rodin generation settings (configurable via admin)
RODIN_TIER = os.environ.get("RODIN_TIER", "Sketch")
RODIN_QUALITY = os.environ.get("RODIN_QUALITY", "medium")
RODIN_MESH_MODE = os.environ.get("RODIN_MESH_MODE", "Raw")
RODIN_MATERIAL = os.environ.get("RODIN_MATERIAL", "PBR")
RODIN_FORMAT = os.environ.get("RODIN_FORMAT", "glb")
RODIN_TAPOSE = os.environ.get("RODIN_TAPOSE", "false").lower() == "true"
RODIN_SEED = os.environ.get("RODIN_SEED", "")

# Retopology settings
RETOPO_ENABLED = os.environ.get("RETOPO_ENABLED", "false").lower() == "true"
RETOPO_FACES = int(os.environ.get("RETOPO_FACES", "25000"))

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

        # Phase 1: Rodin 3D Generation (using shared lib)
        print(f"[Job {job_id}] Submitting to Rodin Sketch...")
        jobs[job_id]["status"] = "submitting"

        task = submit_task(
            api_key=RODIN_API_KEY,
            image_bytes=image_bytes,
            filename="character.png",
            mime_type="image/png",
            tier=RODIN_TIER,
            quality=RODIN_QUALITY,
            mesh_mode=RODIN_MESH_MODE,
            geometry_file_format=RODIN_FORMAT,
            material=RODIN_MATERIAL,
            tapose=RODIN_TAPOSE,
            seed=int(RODIN_SEED) if RODIN_SEED else None,
        )
        task_uuid = task["uuid"]
        subscription_key = task["jobs"]["subscription_key"]
        print(f"[Job {job_id}] Task UUID: {task_uuid}")

        jobs[job_id]["status"] = "generating"
        if not poll_status(RODIN_API_KEY, subscription_key, timeout_sec=300):
            raise Exception("Rodin job failed or timed out")

        print(f"[Job {job_id}] Downloading Rodin results...")
        jobs[job_id]["status"] = "downloading"
        downloaded = download_results(RODIN_API_KEY, task_uuid, str(MODELS_DIR))

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

        # Phase 3: Retopology
        if RETOPO_ENABLED:
            retopo_glb = MODELS_DIR / f"job{job_id}_retopo.glb"
            print(f"[Job {job_id}] Retopologizing ({RETOPO_FACES} faces)...")
            jobs[job_id]["status"] = "retopologizing"
            ok, msg = run_blender_script("step4_retopo.py",
                [str(scaled_glb), str(retopo_glb), "--faces", str(RETOPO_FACES)],
                label=f"Job {job_id} Retopo")
            if not ok:
                print(f"[Job {job_id}] Retopo failed, using scaled mesh: {msg}")
                retopo_glb = scaled_glb
        else:
            retopo_glb = scaled_glb
            print(f"[Job {job_id}] Retopology SKIPPED (disabled in settings)")

        # Phase 4: Rig Transfer
        rig_path = TEMPLATES_DIR / "rig.fbx"
        rigged_fbx = OUTPUT_DIR / f"job{job_id}_rigged.fbx"

        print(f"[Job {job_id}] Transferring rig...")
        jobs[job_id]["status"] = "rigging"
        ok, msg = run_blender_script("step5_rig_transfer.py",
            [str(retopo_glb), str(rig_path), str(rigged_fbx)],
            label=f"Job {job_id} Rig")
        if not ok:
            raise Exception(f"Rig transfer failed: {msg}")

        # Phase 5: Comparison .blend
        comparison_blend = OUTPUT_DIR / f"job{job_id}_comparison.blend"

        print(f"[Job {job_id}] Saving comparison .blend...")
        jobs[job_id]["status"] = "saving_blend"
        ok, msg = run_blender_script("save_comparison_blend.py",
            [str(rigged_fbx), str(rig_path), str(comparison_blend)],
            label=f"Job {job_id} Blend")
        if not ok:
            print(f"[Job {job_id}] Comparison blend failed (non-fatal): {msg}")
            comparison_blend = None

        # Done!
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
        if self.path == "/api/admin/rodin-settings":
            if not self._require_admin(): return
            return self._handle_get_rodin_settings()
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
        if self.path == "/api/admin/rodin-settings":
            if not self._require_admin(): return
            return self._handle_save_rodin_settings()
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
        global GEMINI_API_KEY, RODIN_API_KEY
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        RODIN_API_KEY = os.environ.get("RODIN_API_KEY", "")
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

    def _handle_get_rodin_settings(self):
        self._json_response({
            "tier": RODIN_TIER,
            "quality": RODIN_QUALITY,
            "mesh_mode": RODIN_MESH_MODE,
            "material": RODIN_MATERIAL,
            "format": RODIN_FORMAT,
            "tapose": RODIN_TAPOSE,
            "seed": RODIN_SEED,
            "retopo_enabled": RETOPO_ENABLED,
            "retopo_faces": RETOPO_FACES,
        })

    def _handle_save_rodin_settings(self):
        global RODIN_TIER, RODIN_QUALITY, RODIN_MESH_MODE, RODIN_MATERIAL
        global RODIN_FORMAT, RODIN_TAPOSE, RODIN_SEED
        global RETOPO_ENABLED, RETOPO_FACES

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)

        # Validate tier
        valid_tiers = {"Sketch", "Regular", "Detail", "Smooth", "Gen-2"}
        valid_quality = {"high", "medium", "low", "extra-low"}
        valid_mesh_mode = {"Raw", "Quad"}
        valid_material = {"PBR", "Shaded", "All"}
        valid_format = {"glb", "fbx", "obj", "usdz", "stl"}

        if "tier" in data:
            if data["tier"] not in valid_tiers:
                self._json_response({"success": False, "error": f"Invalid tier. Must be one of: {valid_tiers}"}, 400)
                return
            RODIN_TIER = data["tier"]

        if "quality" in data:
            if data["quality"] not in valid_quality:
                self._json_response({"success": False, "error": f"Invalid quality. Must be one of: {valid_quality}"}, 400)
                return
            RODIN_QUALITY = data["quality"]

        if "mesh_mode" in data:
            if data["mesh_mode"] not in valid_mesh_mode:
                self._json_response({"success": False, "error": f"Invalid mesh_mode. Must be one of: {valid_mesh_mode}"}, 400)
                return
            RODIN_MESH_MODE = data["mesh_mode"]

        if "material" in data:
            if data["material"] not in valid_material:
                self._json_response({"success": False, "error": f"Invalid material. Must be one of: {valid_material}"}, 400)
                return
            RODIN_MATERIAL = data["material"]

        if "format" in data:
            if data["format"] not in valid_format:
                self._json_response({"success": False, "error": f"Invalid format. Must be one of: {valid_format}"}, 400)
                return
            RODIN_FORMAT = data["format"]

        if "tapose" in data:
            RODIN_TAPOSE = bool(data["tapose"])

        if "seed" in data:
            RODIN_SEED = str(data["seed"]).strip() if data["seed"] else ""

        if "retopo_enabled" in data:
            RETOPO_ENABLED = bool(data["retopo_enabled"])

        if "retopo_faces" in data:
            try:
                RETOPO_FACES = max(1000, min(100000, int(data["retopo_faces"])))
            except (ValueError, TypeError):
                self._json_response({"success": False, "error": "retopo_faces must be a number (1000-100000)"}, 400)
                return

        # Persist to .env
        _update_env_key("RODIN_TIER", RODIN_TIER)
        _update_env_key("RODIN_QUALITY", RODIN_QUALITY)
        _update_env_key("RODIN_MESH_MODE", RODIN_MESH_MODE)
        _update_env_key("RODIN_MATERIAL", RODIN_MATERIAL)
        _update_env_key("RODIN_FORMAT", RODIN_FORMAT)
        _update_env_key("RODIN_TAPOSE", str(RODIN_TAPOSE).lower())
        _update_env_key("RODIN_SEED", RODIN_SEED)
        _update_env_key("RETOPO_ENABLED", str(RETOPO_ENABLED).lower())
        _update_env_key("RETOPO_FACES", str(RETOPO_FACES))

        print(f"Updated Rodin settings: tier={RODIN_TIER}, quality={RODIN_QUALITY}, "
              f"mesh_mode={RODIN_MESH_MODE}, material={RODIN_MATERIAL}, format={RODIN_FORMAT}, "
              f"tapose={RODIN_TAPOSE}, seed={RODIN_SEED}")
        print(f"Updated Retopo settings: enabled={RETOPO_ENABLED}, faces={RETOPO_FACES}")

        self._json_response({"success": True})

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
