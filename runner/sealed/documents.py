"""Document handling: split a file into text units, run them through an app, rebuild the file.

txt/md : paragraphs preserved.
docx   : every paragraph and table cell is a unit; formatting of the first run is kept.
pdf    : with converters (pdf2docx + docx2pdf apps verified): pdf -> docx -> translate -> pdf, layout kept.
         without: text extracted with pypdf; output is .txt, and we say so.
Units are batched into chunks of ~policy.chunk_chars, one job per chunk, joined with newlines so the
app sees paragraph boundaries. If an app returns a different number of lines than it was given, the
chunk is retried unit by unit.
"""
import json
import re
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

TEXT_EXT = {".txt", ".md", ".csv"}


def _units_txt(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").split("\n")


def _run_groups(paragraph):
    """Consecutive runs that share bold/italic/size form one unit. A heading that a PDF converter glued to
    its body paragraph therefore translates as its own sentence and keeps its own style."""
    groups, cur, key = [], [], None
    for r in paragraph.runs:
        k = (bool(r.bold), bool(r.italic), r.font.size.pt if r.font.size else None)
        if cur and k != key and r.text.strip() and "".join(x.text for x in cur).strip():
            groups.append(cur)
            cur = []
        cur.append(r)
        key = k
    if cur:
        groups.append(cur)
    return groups


def _units_docx(path: Path):
    import docx
    d = docx.Document(str(path))
    paras = list(d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                paras.extend(cell.paragraphs)
    targets = []          # list of run groups; each group is translated as one unit
    for p in paras:
        for ts in p.paragraph_format.tab_stops:
            try:
                ts.leader = 0     # WD_TAB_LEADER.SPACES: no dot fill after a converted PDF
            except Exception:
                pass
        if not p.runs:
            continue
        gs = _run_groups(p)
        targets.extend(gs if len(gs) > 1 else [p.runs])
    return d, targets


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


MARK = "\u27e6{}\u27e7"   # ⟦n⟧ : survives LLM translators, is stripped before output
_MARK_RE = re.compile(r"\u27e6\s*(\d+)\s*\u27e7\s*")


def _align_by_markers(buf: List[str], run) -> Optional[List[str]]:
    """Send the chunk with ⟦n⟧ markers and rebuild by marker, tolerant to merged or split lines."""
    joined = "\n".join(MARK.format(i + 1) + " " + u.replace("\n", " ") for i, u in enumerate(buf))
    text = _text_of(run(joined))
    parts = _MARK_RE.split(text)
    # parts = [pre, n1, text1, n2, text2, ...]
    found = {}
    for n, t in zip(parts[1::2], parts[2::2]):
        found[int(n)] = (found.get(int(n), "") + " " + t.strip()).strip()
    if len(found) != len(buf) or set(found) != set(range(1, len(buf) + 1)):
        return None
    return [found[i + 1] for i in range(len(buf))]


def transform_units(units: List[str], run: Callable[[str], object], chunk_chars: int, log=None) -> List[str]:
    """run(text) -> output. Returns a list the same length as units with transformed text.
    Order of attempts per chunk: plain lines -> ⟦n⟧ markers -> one job per unit."""
    out = list(units)
    for idx, buf in _chunks(units, chunk_chars):
        joined = "\n".join(u.replace("\n", " ") for u in buf)
        res = _text_of(run(joined)).split("\n")
        if len(res) != len(buf):
            res = _align_by_markers(buf, run)
            if res is None:
                if log:
                    log(f"chunk of {len(buf)} units could not be aligned, retrying unit by unit")
                res = [_text_of(run(u)) for u in buf]
            elif log:
                log(f"chunk of {len(buf)} units aligned by markers")
        for i, r in zip(idx, res):
            out[i] = r
    return out


def process_file(src: Path, dst: Path, run: Callable[[str], object], chunk_chars: int, log=None,
                 converters: Optional[Dict[str, Callable[[bytes], bytes]]] = None) -> Path:
    """converters: {"pdf2docx": bytes->bytes, "docx2pdf": bytes->bytes} enables the layout-preserving PDF path."""
    ext = src.suffix.lower()
    conv = converters or {}
    if ext == ".pdf" and "pdf2docx" in conv and "docx2pdf" in conv:
        work = Path(tempfile.mkdtemp(prefix="sealed-pdf-"))
        mid = work / "in.docx"
        mid.write_bytes(conv["pdf2docx"](src.read_bytes()))
        if log:
            log("pdf rebuilt as docx (pdf2docx)")
        out_docx = process_file(mid, work / "out.docx", run, chunk_chars, log)
        if dst.suffix.lower() != ".pdf":
            dst = dst.with_suffix(".pdf")
        dst.write_bytes(conv["docx2pdf"](out_docx.read_bytes()))
        if log:
            log("docx rendered back to pdf (docx2pdf)")
        return dst
    if ext in TEXT_EXT:
        units = _units_txt(src)
        dst.write_text("\n".join(transform_units(units, run, chunk_chars, log)), encoding="utf-8")
        return dst
    if ext == ".docx":
        d, groups = _units_docx(src)
        units = ["".join(r.text for r in g) for g in groups]
        new = transform_units(units, run, chunk_chars, log)
        for g, old, t in zip(groups, units, new):
            if old == t:
                continue
            lead = old[: len(old) - len(old.lstrip())]
            trail = old[len(old.rstrip()):]
            g[0].text = lead + t.strip() + trail
            for r in g[1:]:
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
        _, groups = _units_docx(src)
        return "\n".join("".join(r.text for r in g) for g in groups)
    if ext == ".pdf":
        return "\n".join(_units_pdf(src))
    raise ValueError(f"unsupported file type {ext}")
