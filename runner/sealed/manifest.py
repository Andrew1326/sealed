import json
import subprocess
from typing import Optional

import jsonschema

from .paths import SPEC_DIR
from .sandbox import run_raw


def image_id(image: str) -> Optional[str]:
    """Content-addressed image ID (sha256 of the image config). Stable across tags."""
    p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def image_config(image: str) -> dict:
    p = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, check=True)
    return json.loads(p.stdout)[0]


def read_manifest(image: str) -> dict:
    p = run_raw(image, ["cat", "/sealed/manifest.json"], timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"image has no /sealed/manifest.json: {p.stderr.decode(errors='replace').strip()}")
    return json.loads(p.stdout.decode())


def read_fixtures(image: str, op: str) -> list:
    p = run_raw(image, ["cat", f"/sealed/tests/{op}.json"], timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"image has no conformance fixtures for '{op}' (/sealed/tests/{op}.json)")
    return json.loads(p.stdout.decode())


def validate_manifest(manifest: dict) -> None:
    schema = json.loads((SPEC_DIR / "manifest.schema.json").read_text())
    jsonschema.validate(manifest, schema)
