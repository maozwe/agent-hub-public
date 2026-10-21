"""Manual browser test server using a temporary database and no provider worker."""
from contextlib import closing
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub import Hub
from local_app import make_server


def main():
    with tempfile.TemporaryDirectory(prefix="agent-hub-ui-") as directory:
        database = str(Path(directory) / "hub.sqlite3")
        config = {"database": database, "agents": ["codex", "cursor", "claude"],
                  "operator": "test-operator", "repositories": {"demo/project": directory}}
        server = make_server(config, port=8891)
        with closing(Hub(database)) as hub:
            for agent, request in [("codex", "[בדיקה מבודדת] סקירת מסמך הדרישות"),
                                   ("cursor", "[בדיקה מבודדת] בחירת סביבת בדיקה"),
                                   ("claude", "[בדיקה מבודדת] אישור קריאת מסמך")]:
                task = hub.create_task("demo/project", request)
                hub.assign(task["id"], agent);hub.claim(agent)
                hub.transition(task["id"], agent, "working")
                if agent == "cursor": hub.ask(task["id"], agent, "באיזו סביבה לבדוק?", ["מקומית", "בדיקות"])
                if agent == "claude": hub.request_approval(task["id"], agent, "קריאת מסמך הדוגמה בלבד", "application")
            hub.create_task("demo/project", "[בדיקה מבודדת] משימה ממתינה לשיוך")
        print("Isolated UI test server: http://127.0.0.1:8891/ (no worker)", flush=True)
        try: server.serve_forever()
        finally: server.server_close()


if __name__ == "__main__": main()
