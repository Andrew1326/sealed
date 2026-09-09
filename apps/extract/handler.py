import json
import re
import sys

MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(0)


def generate(messages, max_new_tokens):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32)
    ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False)
    return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)


def parse_json(s):
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


def main():
    job = json.loads(sys.stdin.read() or "{}")
    op, text, p = job.get("op"), job.get("input"), job.get("params") or {}
    if not isinstance(text, str) or not text.strip():
        fail("empty input")
    text = text[:12000]
    if op == "extract":
        sys_prompt = ("You extract entities from documents. Reply with ONLY a JSON object with keys "
                      "organizations, people, dates, amounts, locations. Each value is a list of strings found in the text. "
                      "Use empty lists when nothing is found.")
        raw = generate([{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}], 400)
        try:
            data = parse_json(raw)
        except Exception as e:
            fail(f"could not parse model output: {e}")
        out = {k: [str(x) for x in (data.get(k) or [])] for k in ["organizations", "people", "dates", "amounts", "locations"]}
        print(json.dumps({"ok": True, "output": out}, ensure_ascii=False))
    elif op == "summarize":
        n = int(p.get("max_words", 80))
        sys_prompt = f"Summarize the user's document in your own words in at most {n} words. Do not quote sentences verbatim. Reply with only the summary."
        raw = generate([{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}], n * 3)
        print(json.dumps({"ok": True, "output": {"summary": raw.strip()}}, ensure_ascii=False))
    else:
        fail(f"unsupported op {op!r}")


if __name__ == "__main__":
    main()
