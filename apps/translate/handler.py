import json
import re
import sys

PAIRS = {"en-de", "de-en", "en-ru", "ru-en", "en-fr", "fr-en"}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(0)


def main():
    job = json.loads(sys.stdin.read() or "{}")
    if job.get("op") != "translate":
        fail(f"unsupported op {job.get('op')!r}")
    text = job.get("input")
    if not isinstance(text, str) or not text.strip():
        fail("empty input")
    p = job.get("params") or {}
    pair = f"{p.get('source', 'en')}-{p.get('target', 'de')}"
    if pair not in PAIRS:
        fail(f"unsupported language pair {pair}; available: {sorted(PAIRS)}")

    from transformers import MarianMTModel, MarianTokenizer
    name = f"Helsinki-NLP/opus-mt-{pair}"
    tok = MarianTokenizer.from_pretrained(name)
    model = MarianMTModel.from_pretrained(name)

    # translate paragraph by paragraph, sentence-batched, to respect the model's 512-token window
    out_paras = []
    for para in text.split("\n"):
        if not para.strip():
            out_paras.append("")
            continue
        sents = [s for s in re.split(r"(?<=[.!?])\s+", para.strip()) if s]
        batch = tok(sents, return_tensors="pt", padding=True, truncation=True, max_length=512)
        gen = model.generate(**batch, max_new_tokens=512, num_beams=2)
        out_paras.append(" ".join(tok.batch_decode(gen, skip_special_tokens=True)))
    print(json.dumps({"ok": True, "output": "\n".join(out_paras)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
