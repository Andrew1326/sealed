"""Gateway API keys. Stored hashed in ~/.sealed/api_keys.json: {sha256(key): {label, created, policies}}.

Rules: if any key exists, every /v1 request needs `Authorization: Bearer <key>`. With no keys, the gateway
serves only when bound to localhost (dev mode) and refuses to start on any other address.
"""
import hashlib
import json
import secrets
import time
from typing import Optional

from .paths import HOME

KEYS = HOME / "api_keys.json"


def load() -> dict:
    return json.loads(KEYS.read_text()) if KEYS.exists() else {}


def save(d: dict) -> None:
    KEYS.write_text(json.dumps(d, indent=2))
    KEYS.chmod(0o600)


def create(label: str, policies: Optional[list] = None) -> str:
    key = "sk_" + secrets.token_urlsafe(24)
    d = load()
    d[hashlib.sha256(key.encode()).hexdigest()] = {"label": label, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                    "policies": policies or ["*"]}
    save(d)
    return key


def revoke(label: str) -> int:
    d = load()
    keep = {h: e for h, e in d.items() if e["label"] != label}
    save(keep)
    return len(d) - len(keep)


def check(bearer: str) -> Optional[dict]:
    """Returns the key entry when valid."""
    if not bearer:
        return None
    return load().get(hashlib.sha256(bearer.encode()).hexdigest())
