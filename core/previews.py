from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pymupdf

from .utils import IMAGE_EXTS, VIDEO_EXTS, find_ffmpeg, open_image, safe_filename

_preview_lock = threading.Lock()
_NO_WINDOW = 0x08000000


def _cache_path(cache_dir: Path, source: Path, tag: str) -> Path:
    return cache_dir / f"{tag}-{safe_filename(source.name)}.png"


def _save_image_preview(source: Path, target: Path) -> bool:
    try:
        with open_image(source) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            image.thumbnail((1400, 1400))
            tmp = target.with_name(target.stem + ".tmp.png")
            image.save(tmp, "PNG", optimize=True)
            tmp.replace(target)
        return True
    except Exception:
        return False


def _save_pdf_preview(source: Path, target: Path) -> bool:
    try:
        doc = pymupdf.open(str(source))
        if doc.needs_pass or doc.page_count == 0:
            doc.close()
            return False
        pix = doc[0].get_pixmap(dpi=120, alpha=False)
        tmp = target.with_name(target.stem + ".tmp.png")
        pix.save(str(tmp))
        doc.close()
        tmp.replace(target)
        return True
    except Exception:
        return False


def _save_video_preview(source: Path, target: Path) -> bool:
    exe = find_ffmpeg()
    if not exe:
        return False
    tmp = target.with_name(target.stem + ".tmp.png")
    for seek in ("0.5", "0"):
        try:
            proc = subprocess.run(
                [
                    exe, "-hide_banner", "-y", "-ss", seek, "-i", str(source),
                    "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(tmp),
                ],
                capture_output=True, timeout=60, creationflags=_NO_WINDOW,
            )
            if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(target)
                return True
        except Exception:
            continue
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def generate_preview(source: Path, cache_dir: Path, tag: str = "out") -> Path | None:
    source = Path(source)
    if not source.exists() or not source.is_file():
        return None
    suffix = source.suffix.lower()
    if suffix not in IMAGE_EXTS and suffix != ".pdf" and suffix not in VIDEO_EXTS:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _cache_path(cache_dir, source, tag)
    with _preview_lock:
        try:
            if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
                return target
        except Exception:
            pass
        if suffix in IMAGE_EXTS:
            ok = _save_image_preview(source, target)
        elif suffix == ".pdf":
            ok = _save_pdf_preview(source, target)
        else:
            ok = _save_video_preview(source, target)
        return target if ok and target.exists() else None
