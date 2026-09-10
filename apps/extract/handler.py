import json
import re
import sys

REV = {m["id"]: m["revision"] for m in json.load(open("/sealed/manifest.json"))["models"]}

MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
_m = None


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
    return _m


def generate(messages, max_new_tokens):
    import torch
    tok, model, dev = load()
    ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False)
    return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)


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
    text = text[:12000]
    if op == "extract":
        sys_prompt = ("You extract entities from documents. Reply with ONLY a JSON object with keys "
                      "organizations, people, dates, amounts, locations. Each value is a list of strings found in the text. "
                      "Use empty lists when nothing is found.")
        raw = generate([{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}], 400)
        try:
            data = parse_json(raw)
        except Exception as e:
            return {"ok": False, "error": f"could not parse model output: {e}"}
        out = {k: [flat(x) for x in (data.get(k) or [])] for k in ["organizations", "people", "dates", "amounts", "locations"]}
        return {"ok": True, "output": out}
    if op == "summarize":
        n = int(p.get("max_words", 80))
        sys_prompt = f"Summarize the user's document in your own words in at most {n} words. Do not quote sentences verbatim. Reply with only the summary."
        raw = generate([{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}], n * 3)
        return {"ok": True, "output": {"summary": raw.strip()}}
    return {"ok": False, "error": f"unsupported op {op!r}"}


for line in sys.stdin:
    if not line.strip():
        continue
    try:
        res = handle(json.loads(line))
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res, ensure_ascii=False), flush=True)
