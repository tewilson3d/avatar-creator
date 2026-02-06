#!/usr/bin/env python3
"""Step 4: Retopologize mesh via QuadRemesher on the other VM

Sends the scaled model to the quadremesher-plugin VM for processing.
Expects the VM to expose an HTTP API or be reachable via SSH/SCP.

Config via environment:
  QUADREMESHER_VM_URL  - e.g. https://quadremesher-plugin.exe.xyz:8000
  QUADREMESHER_VM_SSH  - e.g. exedev@quadremesher-plugin.exe.xyz (for SCP approach)
"""
import sys
import os
import time
import json
import urllib.request
import subprocess
from pathlib import Path


def retopo_via_http(input_path: str, output_path: str) -> bool:
    """Send model to QuadRemesher VM via HTTP API"""
    vm_url = os.environ.get("QUADREMESHER_VM_URL")
    if not vm_url:
        return False

    print(f"Sending to QuadRemesher VM: {vm_url}")

    import base64
    with open(input_path, "rb") as f:
        model_data = base64.b64encode(f.read()).decode()

    payload = json.dumps({
        "model": model_data,
        "format": "glb",
        "target_face_count": 10000,  # Reasonable for game-ready character
        "adaptive_size": 50,
    }).encode()

    req = urllib.request.Request(
        f"{vm_url}/api/retopo",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())

    if "task_id" in result:
        # Poll for completion
        task_id = result["task_id"]
        for _ in range(120):
            time.sleep(5)
            status_req = urllib.request.Request(f"{vm_url}/api/status/{task_id}")
            with urllib.request.urlopen(status_req, timeout=30) as resp:
                status = json.loads(resp.read())
            if status.get("status") == "done":
                model_b64 = status.get("model")
                with open(output_path, "wb") as f:
                    f.write(base64.b64decode(model_b64))
                return True
            elif status.get("status") == "failed":
                print(f"Retopo failed: {status}")
                return False
    elif "model" in result:
        import base64
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(result["model"]))
        return True

    return False


def retopo_via_ssh(input_path: str, output_path: str) -> bool:
    """Send model to QuadRemesher VM via SCP + remote execution"""
    vm_ssh = os.environ.get("QUADREMESHER_VM_SSH")
    if not vm_ssh:
        return False

    print(f"Using SSH to QuadRemesher VM: {vm_ssh}")
    remote_input = "/tmp/retopo_input.glb"
    remote_output = "/tmp/retopo_output.glb"

    # Upload
    subprocess.run(["scp", input_path, f"{vm_ssh}:{remote_input}"], check=True)

    # Run retopo remotely
    subprocess.run([
        "ssh", vm_ssh,
        f"cd /home/exedev/quadremesher-plugin && python3 retopo.py {remote_input} {remote_output}"
    ], check=True)

    # Download result
    subprocess.run(["scp", f"{vm_ssh}:{remote_output}", output_path], check=True)

    return True


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.glb> <output.glb>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    for name, fn in [("HTTP", retopo_via_http), ("SSH", retopo_via_ssh)]:
        print(f"Trying {name} method...")
        try:
            if fn(input_path, output_path):
                print(f"Retopology complete via {name}")
                return
        except Exception as e:
            print(f"{name} method failed: {e}")

    print("ERROR: Cannot reach QuadRemesher VM.")
    print("Set QUADREMESHER_VM_URL or QUADREMESHER_VM_SSH")
    sys.exit(1)


if __name__ == "__main__":
    main()
