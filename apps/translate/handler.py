import json
import re
import sys

PAIRS = {"en-de", "de-en", "en-ru", "ru-en", "en-fr", "fr-en"}
_models = {}


def load(pair):
    if pair not in _models:
        import torch
        from transformers import MarianMTModel, MarianTokenizer
        name = f"Helsinki-NLP/opus-mt-{pair}"
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        _models[pair] = (MarianTokenizer.from_pretrained(name), MarianMTModel.from_pretrained(name).to(dev).eval(), dev)
    return _models[pair]


def translate(text, pair):
    import torch
    tok, model, dev = load(pair)
    out_paras = []
    for para in text.split("\n"):
        if not para.strip():
            out_paras.append("")
            continue
        sents = [s for s in re.split(r"(?<=[.!?])\s+", para.strip()) if s]
        batch = tok(sents, return_tensors="pt", padding=True, truncation=True, max_length=512).to(dev)
        with torch.no_grad():
            gen = model.generate(**batch, max_new_tokens=512, num_beams=2)
        out_paras.append(" ".join(tok.batch_decode(gen, skip_special_tokens=True)))
    return "\n".join(out_paras)


def handle(job):
    if job.get("op") != "translate":
        return {"ok": False, "error": f"unsupported op {job.get('op')!r}"}
    text = job.get("input")
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "empty input"}
    p = job.get("params") or {}
    pair = f"{p.get('source', 'en')}-{p.get('target', 'de')}"
    if pair not in PAIRS:
        return {"ok": False, "error": f"unsupported language pair {pair}; available: {sorted(PAIRS)}"}
    return {"ok": True, "output": translate(text, pair)}


for line in sys.stdin:
    if not line.strip():
        continue
    try:
        res = handle(json.loads(line))
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res, ensure_ascii=False), flush=True)
