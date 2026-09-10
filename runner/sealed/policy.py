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
    allowed_ops: list = field(default_factory=lambda: ["*"])

    def allows(self, op: str) -> bool:
        return "*" in self.allowed_ops or op in self.allowed_ops
    output: OutputRules = field(default_factory=OutputRules)
    memory: str = "8g"
    timeout_seconds: int = 300
    audit: bool = True
    warm: bool = True            # keep a loaded container per app between jobs (same sandbox, no network)
    chunk_chars: int = 6000      # document chunking size for file jobs
    allow_remote: bool = False   # may jobs go to a remote provider (outside the sandbox)? never for confidential
    pseudonymize: bool = False   # mask identifiers before a remote call, restore after
    pseudonymize_names: bool = True
    pseudonymize_terms: list = field(default_factory=list)   # your own words to always mask (company, product names)

    @staticmethod
    def load(path: str | Path) -> "Policy":
        d = yaml.safe_load(Path(path).read_text()) or {}
        out = d.pop("output", {}) or {}
        pol = Policy(output=OutputRules(**out), **d)
        if pol.tier == "confidential" and pol.allow_remote:
            raise ValueError(f"policy '{pol.name}': a confidential policy cannot allow remote providers")
        return pol
