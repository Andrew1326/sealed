"""Local allowlist of verified image IDs. The gateway only routes confidential tiers to these."""
import json
import time
from typing import Optional

from .paths import ALLOWLIST


def load() -> dict:
    if ALLOWLIST.exists():
        return json.loads(ALLOWLIST.read_text())
    return {}


def save(d: dict) -> None:
    ALLOWLIST.write_text(json.dumps(d, indent=2))


def add(image_id: str, image: str, manifest: dict, report_path: str) -> None:
    d = load()
    d[image_id] = {
        "image": image, "name": manifest["name"], "version": manifest["version"],
        "operations": manifest["operations"], "requires": manifest.get("requires", {}),
        "input": manifest.get("input", "text/plain"), "output": manifest.get("output", "text/plain"),
        "output_extension": manifest.get("output_extension"),
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "report": report_path,
    }
    save(d)


def remove(image_id: str) -> bool:
    d = load()
    if image_id in d:
        del d[image_id]
        save(d)
        return True
    return False


def lookup(image_id: str) -> Optional[dict]:
    return load().get(image_id)


def find_by_name(name: str) -> Optional[tuple]:
    """Newest verified image with this app name wins."""
    hits = [(iid, e) for iid, e in load().items() if e["name"] == name]
    if not hits:
        return None
    return max(hits, key=lambda h: h[1]["verified_at"])
