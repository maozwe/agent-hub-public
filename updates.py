"""Read public release metadata on demand. Never downloads or executes installers."""
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "maozwe/agent-hub-public"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
VERSION = json.loads((Path(__file__).parent / "version.json").read_text(encoding="utf-8"))


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d{1,5}\.\d{1,5}\.\d{1,5}", value):
        raise ValueError("Expected a stable version number")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


def release_result(data, current):
    version_tuple(current)
    latest = data.get("tag_name", "")
    newer = (not data.get("prerelease") and not data.get("draft") and
             version_tuple(latest) > version_tuple(current))
    return {"current": current, "latest": latest.removeprefix("v"), "available": newer,
            "release_url": RELEASES_URL, "notes": str(data.get("body") or "")[:1600],
            "status": "available" if newer else "current"}


def check_update(current=None):
    current = current or VERSION["version"]
    version_tuple(current)
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "Agent-Hub-update-check"})
    try:
        with urlopen(request, timeout=6) as response:
            payload = response.read(262145)
        if len(payload) > 262144:
            raise ValueError("Release metadata is too large")
        return release_result(json.loads(payload), current)
    except HTTPError as error:
        status = "unpublished" if error.code == 404 else "unavailable"
    except (URLError, TimeoutError, OSError, ValueError, TypeError, AttributeError):
        status = "unavailable"
    return {"current": current, "available": False, "release_url": RELEASES_URL, "status": status}
