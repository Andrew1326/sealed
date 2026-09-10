import json
import re
import sys

REV = {m["id"]: m["revision"] for m in json.load(open("/sealed/manifest.json"))["models"]}

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
_m = None
LANGS = {"en": "English", "de": "German", "fr": "French", "ru": "Russian", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
         "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian", "sv": "Swedish", "fi": "Finnish", "cs": "Czech", "tr": "Turkish",
         "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ar": "Arabic"}


def load():
    global _m
    if _m is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if dev == "cuda" else torch.float32
        tok = AutoTokenizer.from_pretrained(MODEL, revision=REV[MODEL])
        model = AutoModelForCausalLM.from_pretrained(MODEL, revision=REV[MODEL], torch_dtype=dtype).to(dev).eval()
        _m = (tok, model, dev)
        print(f"loaded {MODEL} on {dev}", file=sys.stderr, flush=True)
    return _m


def generate(system, user, max_new_tokens):
    import torch
    tok, model, dev = load()
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False, repetition_penalty=1.05)
    return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()


def flat(x):
    """Small models sometimes return {'name': ..., 'address': ...} instead of a string."""
    if isinstance(x, dict):
        return str(x.get("name") or x.get("value") or next((v for v in x.values() if isinstance(v, str)), x))
    return str(x)


def parse_json(s):
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


def handle(job):
    op, text, p = job.get("op"), job.get("input"), job.get("params") or {}
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "empty input"}
    text = text[:24000]
    if op == "translate":
        src = LANGS.get(p.get("source", "auto"), p.get("source", "the source language"))
        tgt = LANGS.get(p.get("target", "en"), p.get("target"))
        sys_p = (f"You are a professional translator. Translate the user's text from {src} to {tgt}. "
                 "Preserve formatting, line breaks, numbers, names and placeholders like [[1]] exactly. "
                 "Output only the translation, nothing else.")
        out = generate(sys_p, text, min(4096, len(text) // 2 + 256))
        return {"ok": True, "output": {"text": out}}
    if op == "summarize":
        n = int(p.get("max_words", 80))
        out = generate(f"Summarize the user's document in your own words in at most {n} words. Do not quote verbatim. Output only the summary.", text, n * 3)
        return {"ok": True, "output": {"summary": out}}
    if op == "extract":
        keys = p.get("keys") or ["organizations", "people", "dates", "amounts", "locations"]
        sys_p = ("Extract entities from the document. Reply with ONLY a JSON object with keys " + ", ".join(keys) +
                 ". Each value is a list of strings exactly as they appear in the text. Use empty lists when nothing is found.")
        raw = generate(sys_p, text, 600)
        try:
            data = parse_json(raw)
        except Exception as e:
            return {"ok": False, "error": f"could not parse model output: {e}"}
        return {"ok": True, "output": {k: [flat(x) for x in (data.get(k) or [])] for k in keys}}
    if op == "classify":
        labels = p.get("labels") or ["contract", "invoice", "correspondence", "report", "other"]
        raw = generate("Classify the document into exactly one of these labels: " + ", ".join(labels) +
                       '. Reply with ONLY a JSON object {"label": "...", "confidence": 0.0-1.0}.', text, 60)
        try:
            data = parse_json(raw)
        except Exception as e:
            return {"ok": False, "error": f"could not parse model output: {e}"}
        return {"ok": True, "output": {"label": str(data.get("label", "")), "confidence": float(data.get("confidence", 0) or 0)}}
    return {"ok": False, "error": f"unsupported op {op!r}"}


for line in sys.stdin:
    if not line.strip():
        continue
    try:
        res = handle(json.loads(line))
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res, ensure_ascii=False), flush=True)
