"""Publisher signatures for verified images (Ed25519) and a file/https registry the runner installs from.

A registry entry is the verify result a publisher vouches for: app name, version, operations, requirements,
the content-addressed image ID, the image reference to pull, and the report hash. The runner accepts an entry
only if it is signed by a key in ~/.sealed/trusted_keys, and only if the pulled image's ID matches the signed one.
"""
import base64
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .paths import HOME

KEYS = HOME / "keys"
TRUSTED = HOME / "trusted_keys.json"


def keygen(name: str = "publisher") -> tuple:
    KEYS.mkdir(exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    (KEYS / f"{name}.key").write_bytes(priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    (KEYS / f"{name}.key").chmod(0o600)
    pub = pub_b64(priv.public_key())
    (KEYS / f"{name}.pub").write_text(pub)
    return KEYS / f"{name}.key", pub


def load_private(name: str = "publisher") -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes((KEYS / f"{name}.key").read_bytes())


def pub_b64(pub: Ed25519PublicKey) -> str:
    return base64.b64encode(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def canonical(entry: dict) -> bytes:
    body = {k: v for k, v in entry.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_entry(entry: dict, key_name: str = "publisher") -> dict:
    priv = load_private(key_name)
    entry = dict(entry)
    entry["publisher_key"] = pub_b64(priv.public_key())
    entry["signature"] = base64.b64encode(priv.sign(canonical(entry))).decode()
    return entry


def verify_entry(entry: dict) -> tuple:
    """Returns (label, None) when the signature is valid and the key trusted, else (None, reason)."""
    trusted = load_trusted()
    key = entry.get("publisher_key")
    if key not in trusted:
        return None, "untrusted"
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(base64.b64decode(entry["signature"]), canonical(entry))
    except Exception:
        return None, "bad-signature"
    return trusted[key], None


def load_trusted() -> dict:
    return json.loads(TRUSTED.read_text()) if TRUSTED.exists() else {}


def trust(pub: str, label: str) -> None:
    d = load_trusted()
    d[pub] = label
    TRUSTED.write_text(json.dumps(d, indent=2))


def make_entry(image_ref: str, image_id: str, manifest: dict, report_path: str) -> dict:
    return {
        "name": manifest["name"], "version": manifest["version"], "description": manifest.get("description", ""),
        "operations": manifest["operations"], "requires": manifest.get("requires", {}), "models": manifest.get("models", []),
        "image": image_ref, "image_id": image_id,
        "report_sha256": hashlib.sha256(Path(report_path).read_bytes()).hexdigest(),
        "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def write_registry_entry(registry_dir: Path, entry: dict) -> Path:
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / f"{entry['name']}-{entry['version']}.json"
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False))
    index = {"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "apps": []}
    for f in sorted(registry_dir.glob("*.json")):
        if f.name == "index.json":
            continue
        e = json.loads(f.read_text())
        index["apps"].append({"name": e["name"], "version": e["version"], "description": e["description"],
                              "operations": e["operations"], "requires": e["requires"], "image": e["image"],
                              "image_id": e["image_id"], "entry": f.name})
    (registry_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))
    return path


def fetch(url: str) -> bytes:
    if url.startswith("file://"):
        return Path(url[7:]).read_bytes()
    if "://" not in url:
        return Path(url).read_bytes()
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def fetch_index(base: str) -> dict:
    return json.loads(fetch(base.rstrip("/") + "/index.json"))


def fetch_entry(base: str, entry_file: str) -> dict:
    return json.loads(fetch(base.rstrip("/") + "/" + entry_file))
