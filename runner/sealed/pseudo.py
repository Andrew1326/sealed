"""Pseudonymization: swap identifying strings for stable placeholders before text leaves the machine,
restore them in the result. Deterministic and local, no model.

This is a REDUCTION, not a guarantee. It catches structured identifiers reliably (emails, phones,
IBANs, card numbers, URLs, money, dates), your own dictionary of terms (company and product names),
and capitalised name sequences heuristically. Free-text facts ("the merger closes in May") stay.
Use it for the standard tier; the confidential tier never needs it because nothing leaves.
"""
import re
from dataclasses import dataclass, field
from typing import List, Tuple

HONORIFICS = r"(?:Mr|Mrs|Ms|Dr|Prof|Herr|Frau|Dott|Sig|M|Mme)\.?"
PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("URL", re.compile(r"https?://[^\s<>\"')\]]+|www\.[^\s<>\"')\]]+")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("DATE", re.compile(r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b")),
    ("PHONE", re.compile(r"(?<![\w.,])\+?\(?\d[\d\s().-]{5,18}\d(?![\w.,]\d)")),
    ("MONEY", re.compile(r"(?:(?:EUR|USD|GBP|CHF|€|\$|£)\s?\d(?:[\d,.]*\d)?(?:\s?(?:million|mio|k|m|bn)\b)?|\d(?:[\d,.]*\d)?(?:\s?(?:million|mio|k|m|bn))?\s?(?:EUR|USD|GBP|CHF|€|\$|£|euros?|dollars?|pounds?)\b)", re.I)),
    ("NAME", re.compile(r"\b(?:" + HONORIFICS + r"\s+)?[A-ZÄÖÜÉ][a-zäöüéß'-]+(?:\s+(?:von|van|de|der|del|di|da|le|la)\s+)?(?:\s+[A-ZÄÖÜÉ][a-zäöüéß'-]+){1,2}\b")),
]
STOP_NAME = {"The", "This", "That", "These", "Those", "Our", "Your", "Their", "Dear", "Best", "Kind", "Yours", "Please", "Thank",
             "Supply", "Confidentiality", "Agreement", "Internal", "Memo", "Board", "Chief", "Financial", "Officer", "Subject",
             "Total", "Late", "Each", "Neither", "Delivery", "Payment", "Price", "Governing", "Signed", "New", "United", "European",
             "Central", "Bank", "Third", "Fourth", "First", "Second", "Quarter", "Revenue", "Costs", "Management", "Directors",
             "Contact", "Attention", "Attn", "Regards", "Sincerely", "Hello", "Hi", "From", "To", "Date", "Re", "Cc"}
PLACEHOLDER = re.compile(r"\[\[([A-Z]+)_(\d+)\]\]")


@dataclass
class Mapping:
    forward: dict = field(default_factory=dict)    # original -> placeholder
    back: dict = field(default_factory=dict)       # placeholder -> original
    counts: dict = field(default_factory=dict)

    def placeholder(self, kind: str, original: str) -> str:
        key = (kind, original.strip())
        if key in self.forward:
            return self.forward[key]
        n = self.counts.get(kind, 0) + 1
        self.counts[kind] = n
        ph = f"[[{kind}_{n}]]"
        self.forward[key] = ph
        self.back[ph] = original.strip()
        return ph

    def summary(self) -> dict:
        return dict(self.counts)


def _phone_ok(m: re.Match) -> bool:
    digits = sum(c.isdigit() for c in m.group(0))
    return 7 <= digits <= 15


def _trim_name(m: re.Match):
    """Drop leading stop words ("Contact Maria Lindqvist" -> "Maria Lindqvist"); reject if a stop word remains inside."""
    text = m.group(0)
    words = text.split()
    start = m.start()
    while words and words[0].rstrip(".") in STOP_NAME:
        start += len(words[0]) + 1
        words = words[1:]
    if len(words) < 2 or any(w.rstrip(".") in STOP_NAME for w in words):
        return None
    return start, start + len(" ".join(words))


def mask(text: str, dictionary: List[str] = (), names: bool = True) -> Tuple[str, Mapping]:
    """Returns (masked_text, mapping). Dictionary terms are matched case-insensitively, longest first."""
    mp = Mapping()
    spans: List[Tuple[int, int, str]] = []
    taken = [False] * (len(text) + 1)

    def claim(a: int, b: int, kind: str):
        if any(taken[a:b]):
            return
        for i in range(a, b):
            taken[i] = True
        spans.append((a, b, kind))

    for term in sorted({t for t in dictionary if t.strip()}, key=len, reverse=True):
        for m in re.finditer(re.escape(term), text, re.I):
            claim(m.start(), m.end(), "TERM")
    for kind, rx in PATTERNS:
        if kind == "NAME" and not names:
            continue
        for m in rx.finditer(text):
            if kind == "PHONE" and not _phone_ok(m):
                continue
            if kind == "NAME":
                span = _trim_name(m)
                if span:
                    claim(span[0], span[1], kind)
                continue
            claim(m.start(), m.end(), kind)
    out, pos = [], 0
    for a, b, kind in sorted(spans):
        out.append(text[pos:a])
        out.append(mp.placeholder(kind, text[a:b]))
        pos = b
    out.append(text[pos:])
    return "".join(out), mp


def unmask(text: str, mp: Mapping) -> str:
    """Restore placeholders. Tolerates the usual model damage: spaces inside, lowercased kind, lost brackets."""
    def sub(m):
        return mp.back.get(f"[[{m.group(1).upper()}_{m.group(2)}]]", m.group(0))
    text = PLACEHOLDER.sub(sub, text)
    loose = re.compile(r"\[?\[?\s*([A-Za-z]+)\s*_\s*(\d+)\s*\]?\]?")
    return loose.sub(lambda m: mp.back.get(f"[[{m.group(1).upper()}_{m.group(2)}]]", m.group(0)), text)


def unmask_value(value, mp: Mapping):
    if isinstance(value, str):
        return unmask(value, mp)
    if isinstance(value, list):
        return [unmask_value(v, mp) for v in value]
    if isinstance(value, dict):
        return {k: unmask_value(v, mp) for k, v in value.items()}
    return value
