"""Start the packaged binary from its release folder and check it answers.

usage: python packaging/smoke_test.py <release-folder>
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main() -> int:
    folder = Path(sys.argv[1]).resolve()
    exe = next(p for p in folder.glob("fault-assistant*") if p.is_file() and p.suffix in ("", ".exe"))
    port = 18080
    env = {**os.environ, "PORT": str(port), "LLM_PROVIDER": "none"}
    # Log to a file, not a pipe: on Windows the real server is a child of the PyInstaller launcher
    # and can keep a pipe open after the launcher is killed, which would hang this script.
    log_path = Path(tempfile.gettempdir()) / "fault-assistant-smoke.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen([str(exe)], cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        health = None
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    health = json.load(r)
                    break
            except OSError:
                time.sleep(1)
        if not health:
            print("binary did not come up")
            return 1
        print("health:", health)
        assert health["ok"] and health["series"] >= 3 and health["entries"] > 200, health
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert "变频器故障查询" in r.read().decode("utf-8")
        print("smoke test passed")
        return 0
    finally:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        print(log_path.read_text(encoding="utf-8", errors="replace")[-1500:])


if __name__ == "__main__":
    sys.exit(main())
