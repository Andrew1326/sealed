from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class OutputRules:
    max_chars: int = 200_000
    max_verbatim_span_words: int = 0   # 0 disables the check
    allowed_keys: Optional[list] = None


@dataclass
class Policy:
    name: str
    tier: str = "confidential"
    require_verified: bool = True
    allowed_ops: list = field(default_factory=lambda: ["translate", "summarize", "extract", "classify", "ocr", "transcribe"])
    output: OutputRules = field(default_factory=OutputRules)
    memory: str = "8g"
    timeout_seconds: int = 300
    audit: bool = True
    warm: bool = True            # keep a loaded container per app between jobs (same sandbox, no network)
    chunk_chars: int = 6000      # document chunking size for file jobs

    @staticmethod
    def load(path: str | Path) -> "Policy":
        d = yaml.safe_load(Path(path).read_text()) or {}
        out = d.pop("output", {}) or {}
        return Policy(output=OutputRules(**out), **d)
