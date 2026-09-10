"""Remote providers: OpenAI-compatible chat endpoints (OpenAI, Gemini's OpenAI API, Mistral, Groq, Ollama...).

Only reachable under a policy with `allow_remote: true`, which no confidential policy has. With
`pseudonymize: true` the gateway masks identifiers before the call and restores them after.
Configured in ~/.sealed/remotes.yaml:

    gemini:
      base_url: https://generativelanguage.googleapis.com/v1beta/openai
      model: gemini-2.5-flash
      api_key_env: GEMINI_API_KEY
"""
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Optional

import yaml

from .paths import HOME
from .sandbox import RunResult
import time

REMOTES = HOME / "remotes.yaml"
LANGS = {"en": "English", "de": "German", "fr": "French", "ru": "Russian", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
         "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian", "sv": "Swedish", "fi": "Finnish", "cs": "Czech", "tr": "Turkish",
         "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ar": "Arabic"}
PRESERVE = " Placeholders that look like [[WORD_N]] are identifiers: keep every one of them exactly as written, in place."


def load() -> dict:
    return (yaml.safe_load(REMOTES.read_text()) or {}) if REMOTES.exists() else {}


def get(name: str) -> Optional[dict]:
    r = load().get(name)
    return dict(r, name=name) if r else None


def prompts(op: str, text: str, params: dict) -> tuple:
    p = params or {}
    if op == "translate":
        src = LANGS.get(p.get("source", "auto"), p.get("source", "the source language"))
        tgt = LANGS.get(p.get("target", "en"), p.get("target"))
        return (f"You are a professional translator. Translate from {src} to {tgt}. Preserve formatting and line breaks. "
                f"Output only the translation.{PRESERVE}", text, "text")
    if op == "summarize":
        return (f"Summarize the document in your own words in at most {int(p.get('max_words', 80))} words. Output only the summary.{PRESERVE}", text, "summary")
    if op == "extract":
        keys = p.get("keys") or ["organizations", "people", "dates", "amounts", "locations"]
        return ("Extract entities from the document. Reply with ONLY a JSON object with keys " + ", ".join(keys) +
                f", each a list of strings exactly as they appear.{PRESERVE}", text, "json")
    if op == "classify":
        labels = p.get("labels") or ["contract", "invoice", "correspondence", "report", "other"]
        return ("Classify the document into exactly one of: " + ", ".join(labels) +
                '. Reply with ONLY a JSON object {"label": "...", "confidence": 0.0-1.0}.', text, "json")
    raise ValueError(f"remote providers do not support operation '{op}'")


def call(remote: dict, op: str, text: str, params: Optional[dict], timeout: int = 120) -> RunResult:
    t0 = time.time()
    try:
        system, user, shape = prompts(op, text, params or {})
    except ValueError as e:
        return RunResult(ok=False, error=str(e))
    key = os.environ.get(remote.get("api_key_env", ""), "") or remote.get("api_key", "")
    body = {"model": remote["model"], "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(remote["base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", **({"authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        content = d["choices"][0]["message"]["content"]
    except Exception as e:
        return RunResult(ok=False, error=f"remote {remote['name']} failed: {e}", duration=time.time() - t0)
    if shape == "json":
        m = re.search(r"\{.*\}", content, re.S)
        try:
            return RunResult(ok=True, output=json.loads(m.group(0)) if m else {}, duration=time.time() - t0)
        except Exception:
            return RunResult(ok=False, error="remote returned non-JSON", stderr=content[:300], duration=time.time() - t0)
    if shape == "summary":
        return RunResult(ok=True, output={"summary": content.strip()}, duration=time.time() - t0)
    return RunResult(ok=True, output=content.strip(), duration=time.time() - t0)
