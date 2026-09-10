"""The only path out of the sandbox. Enforces the policy's output rules and writes the audit line."""
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from .paths import AUDIT
from .policy import Policy


@dataclass
class GateVerdict:
    allowed: bool
    reason: Optional[str] = None


def _words(s: str) -> list:
    return [w for w in "".join(c if c.isalnum() else " " for c in s.lower()).split() if w]


def longest_verbatim_span(inp: str, out: str) -> int:
    """Longest run of consecutive words that appears in both input and output."""
    a, b = _words(inp), _words(out)
    if not a or not b:
        return 0
    n = 8
    grams = set()
    for i in range(len(a)):
        grams.add(tuple(a[i:i + n]))
    best = 0
    for j in range(len(b)):
        if tuple(b[j:j + n]) in grams:
            k = n
            while j + k < len(b):
                # extend greedily while every 8-gram window stays inside the input
                if tuple(b[j + k - n + 1:j + k + 1]) in grams:
                    k += 1
                else:
                    break
            best = max(best, k)
    if best == 0:
        # fall back to shorter exact matches
        for m in range(n - 1, 0, -1):
            small = {tuple(a[i:i + m]) for i in range(len(a) - m + 1)}
            if any(tuple(b[j:j + m]) in small for j in range(len(b) - m + 1)):
                return m
    return best


def _looks_base64(s: str) -> bool:
    return len(s) > 64 and " " not in s[:256] and all(c.isalnum() or c in "+/=" for c in s[:256])


def check(policy: Policy, op: str, input_value: Any, output: Any) -> GateVerdict:
    rules = policy.output
    if not policy.allows(op):
        return GateVerdict(False, f"operation '{op}' not allowed by policy '{policy.name}'")
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    if len(text) > rules.max_chars:
        return GateVerdict(False, f"output {len(text)} chars exceeds max_chars={rules.max_chars}")
    if rules.allowed_keys is not None and isinstance(output, dict):
        extra = set(output) - set(rules.allowed_keys)
        if extra:
            return GateVerdict(False, f"output contains keys outside policy: {sorted(extra)}")
    if rules.max_verbatim_span_words and op not in ("translate", "convert") and isinstance(input_value, str) and not _looks_base64(input_value):
        span = longest_verbatim_span(input_value, text)
        if span > rules.max_verbatim_span_words:
            return GateVerdict(False, f"output repeats {span} consecutive input words, limit {rules.max_verbatim_span_words}")
    return GateVerdict(True)


def audit(policy: Policy, image: str, image_id: str, op: str, input_value: Any, output: Any,
          verdict: GateVerdict, duration: float, ok: bool, client: str = "cli", extra: Optional[dict] = None) -> None:
    if not policy.audit:
        return
    raw_in = input_value if isinstance(input_value, str) else json.dumps(input_value, ensure_ascii=False)
    raw_out = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    line = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy": policy.name, "tier": policy.tier, "client": client,
        "image": image, "image_id": image_id, "op": op,
        "input_sha256": hashlib.sha256(raw_in.encode()).hexdigest(), "input_chars": len(raw_in),
        "output_chars": len(raw_out or ""), "app_ok": ok,
        "gate": "allow" if verdict.allowed else "block", "gate_reason": verdict.reason,
        "duration_s": round(duration, 2),
        **(extra or {}),
    }
    with AUDIT.open("a") as f:
        f.write(json.dumps(line) + "\n")
