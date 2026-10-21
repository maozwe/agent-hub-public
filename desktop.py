"""Windows launcher; installed assets and writable operator data stay separate."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import webbrowser

from updates import VERSION


def command(mode, *args):
    if getattr(sys, "frozen", False):
        return [sys.executable, mode, *args]
    return [sys.executable, str(Path(__file__).resolve()), mode, *args]


def initialize(directory):
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "worker.local.json"
    if not config.exists():
        config.write_text(json.dumps({"database": str(directory / "hub.sqlite3"),
            "agents": [], "worker_agents": [], "operator": "local-user", "repositories": {}}, indent=2), encoding="utf-8")
    return config


def state(url):
    try:
        with urlopen(url + "/api/status", timeout=1) as response:
            data = json.load(response)
        return data if data.get("worker", {}).get("read_only") in (True, False) else None
    except (OSError, ValueError):
        return None


def launcher():
    import tkinter as tk
    from tkinter import filedialog, messagebox
    data = Path(os.environ["LOCALAPPDATA"]) / "AgentHub"
    config = initialize(data)
    root = tk.Tk()
    root.title("Agent Hub " + VERSION["version"])
    root.geometry("540x580")
    root.configure(bg="#171c20")
    label = tk.StringVar(value="בחרו פתיחת Hub קיים או שרת בדיקה נפרד")
    notify = tk.BooleanVar(value=False)
    port = tk.IntVar(value=8876)
    previous = None
    def status(text):
        label.set(text); root.update_idletasks()
    def guarded(action):
        try: action()
        except Exception as error: messagebox.showerror("Agent Hub", str(error), parent=root)
    def refresh_status():
        current = state(f"http://127.0.0.1:{port.get()}")
        if current is None:
            status(f"אין חיבור לשרת בפורט {port.get()}. ודאו שה־Hub פועל.")
        else:
            status(f"עודכן כעת · שרת {port.get()} · גרסה {current['version']['version']}\n"
                   f"{len(current['repositories'])} ריפואים · {len(current['tasks'])} משימות · "
                   f"{len(current['pending_questions'])} החלטות ממתינות")
    def start():
        port.set(8892)
        url = "http://127.0.0.1:8892"
        if not state(url):
            with (data / "app.log").open("a", encoding="utf-8") as log:
                subprocess.Popen(command("--serve", "--config", str(config), "--port", "8892", "--no-worker"),
                    stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                    env={**os.environ, "HUB_LOG_PATH": str(data / "app.log")},
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            status("מפעיל את שרת הבדיקה…")
            for _ in range(60):
                if state(url): break
                time.sleep(.1)
            else: raise RuntimeError("השרת לא עלה. פרטים בקובץ app.log בתיקיית הנתונים.")
        webbrowser.open(url)
        status("שרת הבדיקה פעיל ב־8892. סגירת החלון משאירה אותו פועל.")
    def stop():
        control = data / "control.json"
        if not control.exists(): return status("אין שרת בדיקה בבעלות ההתקנה")
        info = json.loads(control.read_text(encoding="utf-8"))
        if info["url"] != "http://127.0.0.1:8892": raise ValueError("Unexpected control address")
        with urlopen(Request(info["url"] + "/api/action", data=b'{"action":"shutdown"}',
                headers={"Origin": info["url"], "X-Hub-CSRF": info["token"], "Content-Type": "application/json"}), timeout=10): pass
        status("נשלחה בקשת עצירה לשרת הבדיקה")
    def configure():
        source = filedialog.askopenfilename(title="בחירת תצורת סוכנים קיימת", filetypes=[("JSON", "*.json")])
        if not source: return
        if state("http://127.0.0.1:8892"): raise ValueError("עצרו קודם את שרת הבדיקה")
        imported = json.loads(Path(source).read_text(encoding="utf-8-sig"))
        if not isinstance(imported.get("agents"), list) or not isinstance(imported.get("repositories"), dict):
            raise ValueError("קובץ הגדרות Hub לא תקין")
        # Never attach an installed test worker to the development database.
        imported["database"] = str(data / "hub.sqlite3")
        imported.pop("tailnet", None)
        config.write_text(json.dumps(imported, ensure_ascii=False, indent=2), encoding="utf-8")
        status("הגדרות הועתקו; הנתונים נפרדים וה־worker יופעל רק מהווב")
    tk.Label(root, text="מרכז החלטות · " + VERSION["version"], font=("Segoe UI", 22), bg="#171c20", fg="#a8dbbb").pack(pady=18)
    for title, action in [("פתיחת ה־Hub הקיים (8876)", lambda: webbrowser.open("http://127.0.0.1:8876/")),
                          ("↻ רענון מצב ה־Hub", refresh_status),
                          ("הפעלת שרת בדיקה נפרד (8892)", start), ("עצירת שרת הבדיקה", stop),
                          ("ייבוא הגדרות סוכנים וריפוזיטוריז", configure),
                          ("פתיחת תיקיית נתונים ולוגים", lambda: os.startfile(data))]:
        tk.Button(root, text=title, command=lambda fn=action: guarded(fn), font=("Segoe UI", 11), width=45).pack(pady=5)
    tk.Label(root, textvariable=label, wraplength=480, bg="#171c20", fg="white").pack(pady=14)
    tk.Checkbutton(root, text="התראות מחשב כלליות כשהחלון פתוח או ממוזער", variable=notify,
                   bg="#171c20", fg="white", selectcolor="#20272b").pack()
    for value in (8876, 8892):
        tk.Radiobutton(root, text=f"התראות מהשרת בפורט {value}", value=value, variable=port,
                       bg="#171c20", fg="white", selectcolor="#20272b").pack()
    def poll():
        nonlocal previous
        from notifications import events
        if not notify.get(): previous = None
        else:
            current = state(f"http://127.0.0.1:{port.get()}")
            if current is not None:
                snapshot = (port.get(), events(current))
                if previous and previous[0] == snapshot[0] and snapshot[1] - previous[1]:
                    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(Path(__file__).parent / "windows" / "toast.ps1"), "-Port", str(port.get())],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                previous = snapshot
        root.after(5000, poll)
    root.after(5000, poll)
    root.mainloop()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        sys.argv.pop(1)
        from local_app import main as serve
        serve()
    elif len(sys.argv) > 1 and sys.argv[1] == "--worker":
        from worker import run
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", required=True)
        parser.add_argument("--once", action="store_true")
        asyncio.run(run(parser.parse_args(sys.argv[2:])))
    else:
        launcher()


if __name__ == "__main__":
    # Windowed PyInstaller executables have no stdio handles.
    for stream in ("stdin", "stdout", "stderr"):
        if getattr(sys, stream) is None:
            path = os.devnull if stream == "stdin" else os.environ.get("HUB_LOG_PATH", os.devnull)
            setattr(sys, stream, open(path, "r" if stream == "stdin" else "a", encoding="utf-8", buffering=1))
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
