"""Tencent Cloud Hunyuan 3D Pro API client.

Drop-in replacement for rodin.py — implements submit_task / poll_status / download_results
with the same signatures so web/server.py needs minimal changes.

Auth: TC Signature v3 (HmacSHA256), pure Python stdlib — no pip installs.
API:  https://hunyuan.intl.tencentcloudapi.com
Docs: https://www.tencentcloud.com/document/product/1284/75539
"""
import hashlib
import hmac
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HOST = "hunyuan.intl.tencentcloudapi.com"
_ENDPOINT = f"https://{_HOST}"
_SERVICE = "hunyuan"
_VERSION = "2023-09-01"
_REGION = "ap-guangzhou"


# ---------------------------------------------------------------------------
# TC Signature v3
# ---------------------------------------------------------------------------

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _build_auth_header(secret_id: str, secret_key: str, action: str, body: bytes) -> dict:
    """Return the headers dict needed for a signed Hunyuan API call."""
    now = int(time.time())
    date = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

    payload_hash = hashlib.sha256(body).hexdigest()
    content_type = "application/json"

    # Canonical request
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{_HOST}\n"
        f"x-tc-action:{action.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    canonical_request = "\n".join([
        "POST", "/", "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    # String to sign
    credential_scope = f"{date}/{_SERVICE}/tc3_request"
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256",
        str(now),
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    # Signing key chain
    secret_date = _sign(f"TC3{secret_key}".encode(), date)
    secret_service = _sign(secret_date, _SERVICE)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    authorization = (
        f"TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": _HOST,
        "X-TC-Action": action,
        "X-TC-Version": _VERSION,
        "X-TC-Timestamp": str(now),
        "X-TC-Region": _REGION,
    }


def _call(secret_id: str, secret_key: str, action: str, params: dict) -> dict:
    body = json.dumps(params).encode()
    headers = _build_auth_header(secret_id, secret_key, action, body)
    req = urllib.request.Request(_ENDPOINT, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    if "Error" in result.get("Response", {}):
        err = result["Response"]["Error"]
        raise RuntimeError(f"Hunyuan API error [{err.get('Code')}]: {err.get('Message')}")
    return result["Response"]


# ---------------------------------------------------------------------------
# Public API — matches rodin.py interface
# ---------------------------------------------------------------------------

def submit_task(
    secret_id: str,
    secret_key: str,
    image_bytes: bytes = None,
    image_path: str = None,
    filename: str = "character.png",
    mime_type: str = "image/png",
    model: str = "3.1",
) -> dict:
    """Submit image-to-3D job.

    Returns dict with 'job_id' key (mirrors rodin's 'uuid').
    """
    import base64 as _b64

    if image_path:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
    elif not image_bytes:
        raise ValueError("Provide either image_path or image_bytes")

    image_b64 = _b64.b64encode(image_bytes).decode()

    print(f"Submitting to Hunyuan 3D Pro (model {model})...")
    resp = _call(secret_id, secret_key, "SubmitHunyuanTo3DProJob", {
        "ImageBase64": image_b64,
        "Model": model,
    })

    job_id = resp["JobId"]
    print(f"  JobId: {job_id}")
    return {"job_id": job_id, "request_id": resp.get("RequestId")}


def poll_status(
    secret_id: str,
    secret_key: str,
    job_id: str,
    timeout_sec: int = 300,
) -> bool:
    """Poll until job is DONE or FAIL. Returns True on success."""
    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(5)
        resp = _call(secret_id, secret_key, "QueryHunyuanTo3DProJob", {"JobId": job_id})
        status = resp.get("Status", "")
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] Job {job_id}: {status}")
        if status == "DONE":
            return True
        if status == "FAIL":
            print(f"ERROR: {resp.get('ErrorMessage', 'Job failed')}")
            return False
    print(f"ERROR: Timed out after {timeout_sec}s")
    return False


def download_results(
    secret_id: str,
    secret_key: str,
    job_id: str,
    output_dir: str,
) -> list[str]:
    """Download generated GLB files. Returns list of local file paths."""
    resp = _call(secret_id, secret_key, "QueryHunyuanTo3DProJob", {"JobId": job_id})
    files_3d = resp.get("ResultFile3Ds", [])
    if not files_3d:
        print("ERROR: No 3D files in job response.")
        return []

    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    for i, item in enumerate(files_3d):
        url = item.get("Url", "")
        if not url:
            continue
        name = f"hunyuan_{job_id}_{i}.glb"
        dest = os.path.join(output_dir, name)
        print(f"  Downloading {name}...")
        urllib.request.urlretrieve(url, dest)
        print(f"    → {dest}")
        downloaded.append(dest)

    return downloaded
