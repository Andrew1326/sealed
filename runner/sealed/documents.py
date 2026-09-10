"""Document handling: split a file into text units, run them through an app, rebuild the file.

txt/md : paragraphs preserved.
docx   : every paragraph and table cell is a unit; formatting of the first run is kept.
pdf    : text extracted with pypdf; output is .txt (layout is not reconstructed, and we say so).
Units are batched into chunks of ~policy.chunk_chars, one job per chunk, joined with newlines so the
app sees paragraph boundaries. If an app returns a different number of lines than it was given, the
chunk is retried unit by unit.
"""
import json
from pathlib import Path
from typing import Callable, List

TEXT_EXT = {".txt", ".md", ".csv"}


def _units_txt(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").split("\n")


def _units_docx(path: Path):
    import docx
    d = docx.Document(str(path))
    paras = list(d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                paras.extend(cell.paragraphs)
    return d, paras


def _units_pdf(path: Path) -> List[str]:
    from pypdf import PdfReader
    out = []
    for page in PdfReader(str(path)).pages:
        out.extend((page.extract_text() or "").split("\n"))
        out.append("")
    return out


def _chunks(units: List[str], chunk_chars: int):
    """Yield (indexes, text) batches of non-empty units."""
    idx, buf, size = [], [], 0
    for i, u in enumerate(units):
        if not u.strip():
            continue
        if buf and size + len(u) > chunk_chars:
            yield idx, buf
            idx, buf, size = [], [], 0
        idx.append(i); buf.append(u); size += len(u) + 1
    if buf:
        yield idx, buf


def _text_of(output) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for k in ("text", "translation", "summary"):
            if k in output:
                return str(output[k])
    return json.dumps(output, ensure_ascii=False)


def transform_units(units: List[str], run: Callable[[str], object], chunk_chars: int, log=None) -> List[str]:
    """run(text) -> output. Returns a list the same length as units with transformed text."""
    out = list(units)
    for idx, buf in _chunks(units, chunk_chars):
        joined = "\n".join(u.replace("\n", " ") for u in buf)
        res = _text_of(run(joined)).split("\n")
        if len(res) != len(buf):
            if log:
                log(f"chunk of {len(buf)} units came back as {len(res)} lines, retrying unit by unit")
            res = [_text_of(run(u)) for u in buf]
        for i, r in zip(idx, res):
            out[i] = r
    return out


def process_file(src: Path, dst: Path, run: Callable[[str], object], chunk_chars: int, log=None) -> Path:
    ext = src.suffix.lower()
    if ext in TEXT_EXT:
        units = _units_txt(src)
        dst.write_text("\n".join(transform_units(units, run, chunk_chars, log)), encoding="utf-8")
        return dst
    if ext == ".docx":
        d, paras = _units_docx(src)
        units = [p.text for p in paras]
        new = transform_units(units, run, chunk_chars, log)
        for p, t in zip(paras, new):
            if p.text == t or not p.runs:
                continue
            p.runs[0].text = t
            for r in p.runs[1:]:
                r.text = ""
        if dst.suffix.lower() != ".docx":
            dst = dst.with_suffix(".docx")
        d.save(str(dst))
        return dst
    if ext == ".pdf":
        units = _units_pdf(src)
        dst = dst.with_suffix(".txt")
        dst.write_text("\n".join(transform_units(units, run, chunk_chars, log)), encoding="utf-8")
        return dst
    raise ValueError(f"unsupported file type {ext}; supported: txt md csv docx pdf")


def whole_text(src: Path) -> str:
    """For ops that take the whole document (summarize, extract, classify)."""
    ext = src.suffix.lower()
    if ext in TEXT_EXT:
        return src.read_text(encoding="utf-8", errors="replace")
    if ext == ".docx":
        _, paras = _units_docx(src)
        return "\n".join(p.text for p in paras)
    if ext == ".pdf":
        return "\n".join(_units_pdf(src))
    raise ValueError(f"unsupported file type {ext}")
