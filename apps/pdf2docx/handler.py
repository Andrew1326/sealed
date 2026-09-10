"""PDF -> DOCX with layout (pdf2docx). One JSON line in, one out. No network, ever."""
import base64
import json
import os
import shutil
import sys
import tempfile


def convert(data: bytes) -> bytes:
    if not data.startswith(b"%PDF"):
        raise ValueError("input is not a PDF")
    from pdf2docx import Converter
    work = tempfile.mkdtemp(dir="/tmp")
    try:
        src, dst = os.path.join(work, "in.pdf"), os.path.join(work, "out.docx")
        with open(src, "wb") as f:
            f.write(data)
        cv = Converter(src)
        cv.convert(dst, start=0, end=None)
        cv.close()
        with open(dst, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def handle(job):
    if job.get("op") != "convert":
        return {"ok": False, "error": f"unsupported op {job.get('op')!r}"}
    inp = job.get("input")
    if not isinstance(inp, str) or not inp:
        return {"ok": False, "error": "empty input"}
    try:
        data = base64.b64decode(inp, validate=True)
    except Exception:
        return {"ok": False, "error": "input must be base64"}
    return {"ok": True, "output": base64.b64encode(convert(data)).decode()}


for line in sys.stdin:
    if not line.strip():
        continue
    try:
        res = handle(json.loads(line))
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res), flush=True)
