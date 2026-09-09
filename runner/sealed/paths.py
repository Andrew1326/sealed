import os
from pathlib import Path

HOME = Path(os.environ.get("SEALED_HOME", Path.home() / ".sealed"))
HOME.mkdir(parents=True, exist_ok=True)
ALLOWLIST = HOME / "allowlist.json"
AUDIT = HOME / "audit.jsonl"
REPORTS = HOME / "reports"
REPORTS.mkdir(exist_ok=True)
SPEC_DIR = Path(os.environ.get("SEALED_SPEC_DIR", Path(__file__).resolve().parents[2] / "spec"))
