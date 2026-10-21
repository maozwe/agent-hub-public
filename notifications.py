"""Generic, opt-in FCM notifications. Task content never leaves the Hub."""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading

from hub import Hub

TITLE = "Agent Hub"
BODY = "יש עדכון במרכז ההחלטות. פתחו את Agent Hub לצפייה."


def events(state):
    result = {f"question:{q['id']}" for q in state.get("pending_questions", [])}
    for task in state.get("tasks", []):
        if task["status"] in {"completed", "blocked"}:
            # Local fingerprint distinguishes a new block without transmitting its reason.
            fingerprint = hashlib.sha256(str(task.get("blocked_reason", "")).encode()).hexdigest()[:16]
            result.add(f"task:{task['id']}:{task['status']}:{fingerprint}")
    return result


def payload(token):
    return {"message": {"token": token, "notification": {"title": TITLE, "body": BODY},
        "android": {"priority": "high", "ttl": "3600s", "collapse_key": "hub-update",
                    "notification": {"channel_id": "hub_updates", "tag": "hub-update"}}}}


class Push:
    def __init__(self, config, sender=None):
        self.database = config["database"]
        self.settings = config.get("firebase", {})
        self.sender = sender or self.send
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None
        self.session = None
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS push_devices(device TEXT PRIMARY KEY, token TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS push_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        with closing(Hub(self.database)) as hub:
            self.previous = events(hub.status())

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database, timeout=10)) as db:
            with db:
                yield db

    @property
    def enabled(self):
        return bool(self.settings.get("project_id") and self.settings.get("credentials"))

    def register(self, device, token):
        if not self.enabled:
            raise ValueError("Firebase is not configured on this server")
        if not isinstance(device, str) or not re.fullmatch(r"[a-zA-Z0-9-]{16,64}", device):
            raise ValueError("Invalid device identifier")
        if token is not None and (not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_:.-]{30,4096}", token)):
            raise ValueError("Invalid device token")
        with self.connect() as db:
            if token is None:
                db.execute("DELETE FROM push_devices WHERE device=?", (device,))
            else:
                count = db.execute("SELECT COUNT(*) FROM push_devices WHERE device<>?", (device,)).fetchone()[0]
                if count >= 8: raise ValueError("At most eight devices may subscribe")
                db.execute("INSERT OR REPLACE INTO push_devices VALUES(?,?)", (device, token))
        return {"ok": True, "enabled": token is not None}

    def send(self, token):
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        if self.session is None:
            credentials = service_account.Credentials.from_service_account_file(
                self.settings["credentials"], scopes=["https://www.googleapis.com/auth/firebase.messaging"])
            self.session = AuthorizedSession(credentials)
        project = self.settings["project_id"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", project): raise ValueError("Invalid Firebase project")
        response = self.session.post(f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
                                     json=payload(token), timeout=10)
        if response.status_code == 404:
            details = response.json().get("error", {}).get("details", [])
            if any(d.get("errorCode") == "UNREGISTERED" for d in details): return False
        response.raise_for_status()
        return True

    def tick(self):
        with closing(Hub(self.database)) as hub:
            current = events(hub.status())
        fresh = current - self.previous
        if not fresh: return
        # One collapsed generic notification for all new events in this interval.
        with self.connect() as db:
            devices = db.execute("SELECT device,token FROM push_devices").fetchall()
        for device, token in devices:
            markers = [hashlib.sha256((device + token + event).encode()).hexdigest() for event in fresh]
            with self.connect() as db:
                markers = [m for m in markers if not db.execute("SELECT 1 FROM push_state WHERE key=?", (m,)).fetchone()]
                if not markers: continue
            if self.sender(token) is False:
                with self.connect() as db: db.execute("DELETE FROM push_devices WHERE device=? AND token=?", (device, token))
            with self.connect() as db: db.executemany("INSERT OR REPLACE INTO push_state VALUES(?,?)", [(m, "sent") for m in markers])
        self.previous = current
        self.error = None

    def start(self):
        if not self.enabled: return
        def loop():
            while not self.stop_event.wait(5 if not self.error else 30):
                try: self.tick()
                except Exception:
                    # Never log tokens, payloads or credential paths to the operator API.
                    self.error = "שליחת פוש נכשלה; יתבצע ניסיון נוסף"
        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=12)
        if self.session: self.session.close()
