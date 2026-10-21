"""Start/stop the app owned by this checkout, without installing an OS service."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


def running(url):
    try:
        with urlopen(url + "/api/status", timeout=2) as response:
            return json.load(response).get("worker", {}).get("read_only") is True
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    config_path = ROOT / "worker.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    runtime = Path(config["database"]).parent
    runtime.mkdir(parents=True, exist_ok=True)
    control = runtime / "control.json"
    url = "http://127.0.0.1:8876"
    if args.action == "start":
        if running(url):
            print(url)
            return
        with (runtime / "app.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "local_app.py"), "--config", str(config_path), "--port", "8876"],
                cwd=ROOT, stdout=log, stderr=log, env={**os.environ, "PYTHONUTF8": "1"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(100):
            if running(url):
                print(url)
                return
            if process.poll() is not None:
                raise SystemExit("App did not start; inspect .local/app.log")
            time.sleep(.1)
        raise SystemExit("App is still starting; inspect .local/app.log")
    if not control.exists():
        print("No running app owned by this checkout.")
        return
    data = json.loads(control.read_text(encoding="utf-8"))
    request = Request(data["url"] + "/api/action", data=b'{"action":"shutdown"}',
                      headers={"Origin": data["url"], "Content-Type": "application/json", "X-Hub-CSRF": data["token"]})
    with urlopen(request, timeout=10):
        pass
    for _ in range(100):
        if not running(data["url"]):
            print("Agent Hub stopped.")
            return
        time.sleep(.1)
    raise SystemExit("Shutdown requested; inspect the app log if it remains active.")


if __name__ == "__main__":
    main()
