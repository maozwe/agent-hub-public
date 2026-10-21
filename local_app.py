"""Loopback-only operator UI and lifecycle owner for the local read-only worker."""
import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import sys
import threading

from hub import Hub
from updates import VERSION, check_update

ROOT = Path(__file__).resolve().parent


class Controller:
    def __init__(self, config, config_path=None):
        self.config, self.config_path = config, config_path
        self.token = secrets.token_urlsafe(32)
        self.process = None
        self.log = None
        self.lock = threading.Lock()
        with closing(Hub(config["database"])) as hub:
            for agent in config["agents"]:
                if not hub.db.execute("SELECT 1 FROM agents WHERE name=?", (agent,)).fetchone():
                    hub.register_agent(agent, True)

    def start_worker(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            if not self.config_path:
                raise ValueError("Worker configuration is unavailable")
            if self.log:
                self.log.close()
            log_path = Path(self.config["database"]).parent / "worker.log"
            self.log = log_path.open("a", encoding="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, str(ROOT / "worker.py"), "--config", str(self.config_path)],
                cwd=ROOT, stdout=self.log, stderr=self.log,
                env={**os.environ, "PYTHONUTF8": "1"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def stop_worker(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                   capture_output=True, check=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    self.process.terminate()
                self.process.wait(timeout=10)
            if self.log:
                self.log.close()
                self.log = None

    def status(self):
        with closing(Hub(self.config["database"])) as hub:
            state = hub.status()
            state["agents"] = [dict(row) for row in hub.db.execute("SELECT * FROM agents ORDER BY name")]
        state["repositories"] = self.config["repositories"]
        state["version"] = VERSION
        hostname = self.config.get("tailnet", {}).get("hostname")
        state["phone_url"] = f"https://{hostname}/" if hostname else None
        state["worker"] = {"running": self.process is not None and self.process.poll() is None,
                           "exit_code": self.process.poll() if self.process else None,
                           "read_only": True}
        return state

    def action(self, data):
        action = data.get("action")
        if action == "check_update":
            return check_update(data.get("client_version"))
        if action == "start_worker":
            self.start_worker()
            return {"ok": True}
        if action == "stop_worker":
            self.stop_worker()
            return {"ok": True}
        with closing(Hub(self.config["database"])) as hub:
            if action == "create":
                if data["repository"] not in self.config["repositories"]:
                    raise ValueError("Unknown repository")
                if len(data["request"]) > 8000:
                    raise ValueError("Request is too long")
                with hub.transaction():
                    task = hub.create_task(data["repository"], data["request"], data.get("priority"))
                    if data.get("agent"):
                        if data["agent"] not in self.config["agents"]:
                            raise ValueError("Unknown agent")
                        hub.assign(task["id"], data["agent"])
                    return hub.set_participants(task["id"], data.get("participants", []))
            if action == "participants":
                return hub.set_participants(data["task_id"], data["participants"])
            if action == "assign":
                if data["agent"] not in self.config["agents"]:
                    raise ValueError("Unknown agent")
                return hub.assign(data["task_id"], data["agent"])
            if action == "answer":
                hub.answer(data["question_id"], data["answer"], self.config["operator"])
            elif action == "decide":
                hub.decide(data["question_id"], data["decision"], self.config["operator"])
            else:
                raise ValueError("Unknown action")
        return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        encoded = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(encoded)

    def request_origin(self):
        local_host = f"127.0.0.1:{self.server.server_port}"
        host = self.headers.get("Host")
        tailnet = self.server.controller.config.get("tailnet", {})
        proxied = (host != local_host or self.headers.get("Tailscale-User-Login") or
                   self.headers.get("X-Forwarded-For") or self.headers.get("X-Forwarded-Proto"))
        if proxied:
            # Serve strips spoofed identity headers; backend stays on loopback.
            if (tailnet.get("hostname") and host in {local_host, tailnet["hostname"]} and
                    self.headers.get("Tailscale-User-Login") == tailnet.get("login")):
                return "https://" + tailnet["hostname"]
            return None
        return "http://" + local_host if host == local_host else None

    def do_GET(self):
        if not self.request_origin():
            return self.send(403, '{"error":"Invalid host"}')
        if self.path == "/api/status":
            return self.send(200, json.dumps(self.server.controller.status(), ensure_ascii=False))
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        if self.path not in files:
            return self.send(404, '{"error":"Not found"}')
        filename, content_type = files[self.path]
        body = (ROOT / "web" / filename).read_text(encoding="utf-8")
        if filename == "index.html":
            body = body.replace("__CSRF__", self.server.controller.token)
            client = self.headers.get("X-Agent-Hub-Client-Version", "")
            client = client if re.fullmatch(r"\d{1,5}\.\d{1,5}\.\d{1,5}", client) else ""
            body = body.replace("__CLIENT_VERSION__", client)
        self.send(200, body, content_type)

    def do_POST(self):
        origin = self.request_origin()
        if (origin is None or self.headers.get("Origin") != origin or
                not secrets.compare_digest(self.headers.get("X-Hub-CSRF", ""), self.server.controller.token)):
            return self.send(403, '{"error":"Invalid origin or request token"}')
        if self.path != "/api/action":
            return self.send(404, '{"error":"Not found"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536 or self.headers.get("Content-Type") != "application/json":
                raise ValueError("Expected a bounded JSON request")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            if data.get("action") == "shutdown":
                self.send(200, '{"ok":true}')
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            result = self.server.controller.action(data)
            self.send(200, json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError, TypeError) as error:
            self.send(400, json.dumps({"error": str(error)}, ensure_ascii=False))
        except Exception:
            self.send(500, '{"error":"Local operation failed; inspect the app log"}')


def make_server(config, port=8876, config_path=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.controller = Controller(config, config_path)
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--no-worker", action="store_true")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    Path(config["database"]).parent.mkdir(parents=True, exist_ok=True)
    server = make_server(config, args.port, config_path)
    control = Path(config["database"]).parent / "control.json"
    control.write_text(json.dumps({"url": f"http://127.0.0.1:{server.server_port}",
                                  "token": server.controller.token}), encoding="utf-8")
    try:
        if not args.no_worker:
            server.controller.start_worker()
        print(f"Agent Hub: http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
    finally:
        server.controller.stop_worker()
        server.server_close()
        control.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
