"""Source packages: what a publisher signs and what a user builds.

A registry entry points at a deterministic tarball of the app directory (Dockerfile, handler, manifest,
fixtures). The tarball's sha256 is part of the signed entry. `install` fetches it, checks the hash, builds
the image locally, then runs the local admission pipeline. No image hosting, and the guarantee comes from
the user's own verify run, not from the publisher.
"""
import hashlib
import io
import tarfile
from pathlib import Path

EXCLUDE = {"__pycache__", ".DS_Store"}


def pack(app_dir: Path) -> bytes:
    """Deterministic tar.gz of app_dir: sorted names, fixed mtime/uid/gid, no compression timestamp."""
    buf = io.BytesIO()
    files = sorted(p for p in app_dir.rglob("*") if p.is_file() and not (set(p.parts) & EXCLUDE))
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9, format=tarfile.PAX_FORMAT) as tar:
        for f in files:
            ti = tar.gettarinfo(str(f), arcname=str(f.relative_to(app_dir)))
            ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = 0, 0, 0, "", ""
            ti.mode = 0o755 if f.suffix == ".sh" else 0o644
            with f.open("rb") as fh:
                tar.addfile(ti, fh)
    data = buf.getvalue()
    # gzip header carries a timestamp at bytes 4..8; zero it so identical trees give identical bytes
    return data[:4] + b"\x00\x00\x00\x00" + data[8:]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unpack(data: bytes, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"unsafe path in source package: {m.name}")
        tar.extractall(dest)
    return dest
