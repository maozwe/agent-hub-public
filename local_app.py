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
from notifications import Push
from worker import task_write_scope, parse_agent_response
from activity import ActivityReader

ROOT = Path(__file__).resolve().parent


class Controller:
    def __init__(self, config, config_path=None):
        self.config, self.config_path = config, config_path
        self.token = secrets.token_urlsafe(32)
        self.activity = ActivityReader()
        self.process = None
        self.log = None
        self.lock = threading.Lock()
        with closing(Hub(config["database"])) as hub:
            for agent in config["agents"]:
                if not hub.db.execute("SELECT 1 FROM agents WHERE name=?", (agent,)).fetchone():
                    hub.register_agent(agent, True)
        self.push = Push(config)

    def start_worker(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            if not self.config_path:
                raise ValueError("Worker configuration is unavailable")
            if not self.config.get("worker_agents", self.config["agents"]) or not self.config.get("rutherford_command"):
                raise ValueError("Import an operator configuration before starting the worker")
            if self.log:
                self.log.close()
            log_path = Path(self.config["database"]).parent / "worker.log"
            self.log = log_path.open("a", encoding="utf-8")
            command = ([sys.executable, "--worker"] if getattr(sys, "frozen", False)
                       else [sys.executable, str(ROOT / "worker.py")])
            self.process = subprocess.Popen(
                [*command, "--config", str(self.config_path)],
                cwd=ROOT, stdout=self.log, stderr=self.log,
                env={**os.environ, "PYTHONUTF8": "1", "HUB_LOG_PATH": str(log_path)},
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
        for task in state["tasks"]:
            runs = [run for run in state.get("runs", []) if run["task_id"] == task["id"]]
            run = max(runs, key=lambda r:r["turn"]) if runs else None
            task["activity"] = self.activity.read(task, run, self.config["repositories"].get(task["repository"], ""),
                manual=None if any(q['task_id']==task['id'] and q['kind']=='followup' for q in state['questions']) else self.config.get("manual_sessions", {}).get(str(task["id"])))
            self.sync_manual_completion(task)
            if task['status']=='completed':
                task['activity']['manual']=False
                task['activity']['stale']=False
        state["repositories"] = self.config["repositories"]
        state["version"] = VERSION
        state["push"] = {"configured": self.push.enabled, "error": self.push.error}
        hostname = self.config.get("tailnet", {}).get("hostname")
        state["phone_url"] = f"https://{hostname}/" if hostname else None
        write_tasks = [task["id"] for task in state["tasks"] if task["status"] != "completed"
                       and task_write_scope(self.config, {"task": task})]
        state["worker"] = {"running": self.process is not None and self.process.poll() is None,
                           "exit_code": self.process.poll() if self.process else None,
                           "read_only": not write_tasks, "write_tasks": write_tasks}
        return state

    def sync_manual_completion(self, task):
        activity=task.get('activity',{})
        if not activity.get('manual') or not activity.get('report') or task['status']!='blocked': return
        try: report=parse_agent_response(activity['report'])
        except ValueError: return
        if report['state']!='completed': return
        with closing(Hub(self.config['database'])) as hub:
            with hub.transaction():
                current=hub.task(task['id'])
                if current['status']!='blocked' or current['agent']!=task['agent'] or current['repository']!=task['repository']: return
                if hub.db.execute("SELECT 1 FROM questions WHERE task_id=? AND (answer IS NULL OR (kind='approval' AND answer='denied'))",(task['id'],)).fetchone(): return
                # Atomic transitions: the worker never sees a runnable intermediate state.
                hub.transition(task['id'],task['agent'],'working')
                hub.transition(task['id'],task['agent'],'testing')
                done=hub.transition(task['id'],task['agent'],'completed',report['summary']+'\n\n'+report['verification'])
                hub.db.execute('UPDATE tasks SET blocked_reason=NULL WHERE id=?',(task['id'],))
                task.update(done); task['blocked_reason']=None

    def watch_manual_sessions(self, stop):
        while not stop.wait(3):
            try: self.status()
            except Exception as error:
                print('Manual session synchronization failed: '+type(error).__name__,flush=True)

    def action(self, data):
        action = data.get("action")
        if action == "push_register":
            return self.push.register(data.get("device"), data.get("token"))
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
            if action == "followup":
                return hub.follow_up(data['task_id'],data['note'],self.config['operator'])
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
                 "/task-filters.js": ("task-filters.js", "text/javascript; charset=utf-8"),
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
        manual_stop=threading.Event()
        manual_thread=threading.Thread(target=server.controller.watch_manual_sessions,args=(manual_stop,),daemon=True)
        manual_thread.start()
        server.controller.push.start()
        if not args.no_worker:
            server.controller.start_worker()
        print(f"Agent Hub: http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
    finally:
        manual_stop.set()
        manual_thread.join(timeout=5)
        server.controller.push.close()
        server.controller.stop_worker()
        server.server_close()
        control.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
