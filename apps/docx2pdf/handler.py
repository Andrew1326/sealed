"""docx/xlsx/pptx/odt/rtf -> PDF via LibreOffice headless. One JSON line in, one out. No network, ever."""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

MAGIC = {b"PK\x03\x04": "docx", b"{\\rtf": "rtf", b"\xd0\xcf\x11\xe0": "doc"}


def convert(data: bytes) -> bytes:
    ext = next((e for m, e in MAGIC.items() if data.startswith(m)), None)
    if not ext:
        raise ValueError("input is not an Office document (docx/xlsx/pptx/odt/rtf/doc)")
    work = tempfile.mkdtemp(dir="/tmp")
    try:
        src = os.path.join(work, f"input.{ext}")
        with open(src, "wb") as f:
            f.write(data)
        env = dict(os.environ, HOME=work)
        r = subprocess.run(["soffice", "--headless", "--norestore", "--nologo", "--convert-to", "pdf", "--outdir", work, src],
                           capture_output=True, text=True, timeout=110, env=env)
        out = os.path.join(work, "input.pdf")
        if not os.path.exists(out):
            raise RuntimeError(f"libreoffice failed: {(r.stderr or r.stdout).strip()[-300:]}")
        with open(out, "rb") as f:
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
