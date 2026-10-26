from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
WORK_DIR = BASE_DIR / ".work"
JOBS_DIR = WORK_DIR / "jobs"
GALLERY_DIR = WORK_DIR / "gallery"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif", ".bmp", ".tif", ".tiff", ".gif"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mts", ".3gp"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".aif"}

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)


def safe_filename(name: str, fallback: str = "file") -> str:
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = INVALID_CHARS.sub("_", name).strip().strip(".")
    if not name:
        name = fallback
    stem, dot, ext = name.rpartition(".")
    if dot and stem.lower() in RESERVED_NAMES:
        stem = f"_{stem}"
    if len(name) > 140:
        ext = "." + ext if dot else ""
        name = name[: 140 - len(ext)] + ext
    if name.lower() in RESERVED_NAMES:
        name = "_" + name
    return name


def unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / safe_filename(filename)
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for i in range(2, 10000):
        candidate = directory / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{int(time.time())}{suffix}"


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def parse_page_spec(spec: str, total: int) -> list[list[int]]:
    """Return groups of 0-based page numbers. '1-3, 5' -> [[0,1,2],[4]]"""
    spec = (spec or "").strip()
    if not spec or spec.lower() in {"all", "*", "全部"}:
        return [list(range(total))]
    groups: list[list[int]] = []
    for chunk in re.split(r"[,，;；\n]+", spec):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, _, b = chunk.partition("-")
            try:
                start = int(a.strip())
                end = int(b.strip())
            except ValueError as exc:
                raise ValueError(f"无法识别的页码：{chunk}") from exc
            if start > end:
                start, end = end, start
            pages = list(range(start, end + 1))
        else:
            try:
                pages = [int(chunk)]
            except ValueError as exc:
                raise ValueError(f"无法识别的页码：{chunk}") from exc
        normalized = []
        for p in pages:
            if p < 1 or p > total:
                raise ValueError(f"页码 {p} 超出范围（共 {total} 页）")
            normalized.append(p - 1)
        groups.append(normalized)
    if not groups:
        raise ValueError("请填写页码范围")
    return groups


def page_label(groups: list[list[int]]) -> str:
    labels = []
    for g in groups:
        if len(g) == 1:
            labels.append(str(g[0] + 1))
        elif len(g) <= 6:
            labels.append(f"{g[0] + 1}-{g[-1] + 1}")
        else:
            labels.append(f"{g[0] + 1}-{g[-1] + 1}")
    return "_".join(labels) or "pages"


def make_zip(paths: list[Path], out_path: Path, arc_prefix: str = "") -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in paths:
            p = Path(p)
            if not p.exists() or p.is_dir():
                continue
            name = p.name
            if arc_prefix:
                name = f"{arc_prefix}/{name}"
            if name in seen:
                seen[name] += 1
                stem, suffix = os.path.splitext(name)
                name = f"{stem}-{seen[name]}{suffix}"
            else:
                seen[name] = 0
            zf.write(p, name)
    return out_path


_ffmpeg_cache: str | None = None


def find_ffmpeg() -> str | None:
    global _ffmpeg_cache
    if _ffmpeg_cache and Path(_ffmpeg_cache).exists():
        return _ffmpeg_cache
    candidates = []
    if os.environ.get("FFMPEG_PATH"):
        candidates.append(os.environ["FFMPEG_PATH"])
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)
    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    for c in candidates:
        if c and Path(c).exists():
            _ffmpeg_cache = str(c)
            return _ffmpeg_cache
    return None


def ffmpeg_version() -> str:
    exe = find_ffmpeg()
    if not exe:
        return ""
    try:
        out = subprocess.run(
            [exe, "-hide_banner", "-version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW,
        ).stdout
        m = re.search(r"ffmpeg version (\d+(?:\.\d+){0,2})", out)
        return m.group(1) if m else "ready"
    except Exception:
        return "ready"


def probe_duration(path: Path) -> float | None:
    exe = find_ffmpeg()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return None


def has_stream(path: Path, kind: str = "audio") -> bool:
    exe = find_ffmpeg()
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW,
        )
        return f"{kind}:" in (proc.stderr or "") or (kind == "audio" and "Audio:" in (proc.stderr or ""))
    except Exception:
        return False


def run_ffmpeg(args: list[str], duration: float | None = None, progress=None) -> None:
    """Run ffmpeg, reporting 0-100 progress when a duration is known."""
    exe = find_ffmpeg()
    if not exe:
        raise RuntimeError("未找到 FFmpeg，请先安装或设置 FFMPEG_PATH 环境变量")
    cmd = [exe, "-hide_banner", "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
    cmd += [str(a) for a in args]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=_NO_WINDOW,
    )
    last_pct = -1
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line or duration is None or duration <= 0:
                continue
            seconds = None
            if line.startswith("out_time_us="):
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    pass
            elif line.startswith("out_time="):
                m = re.match(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
                if m:
                    seconds = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            if seconds is not None:
                pct = max(0, min(99, int(seconds / duration * 100)))
                if pct != last_pct:
                    last_pct = pct
                    if progress:
                        progress(pct)
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        raise
    proc.wait()
    err = (proc.stderr.read() if proc.stderr else "") or ""
    if proc.returncode != 0:
        lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
        detail = lines[-1] if lines else "FFmpeg 处理失败"
        raise RuntimeError(_friendly_ffmpeg_error(detail))
    if progress:
        progress(100)


def _friendly_ffmpeg_error(detail: str) -> str:
    low = detail.lower()
    if "no such file" in low:
        return "找不到输入文件"
    if "invalid data" in low or "moov atom" in low:
        return "文件已损坏或无法被 FFmpeg 识别"
    if "unknown encoder" in low:
        return "当前 FFmpeg 缺少所需编码器"
    if "permission denied" in low:
        return "文件被占用或没有写入权限"
    return f"视频处理失败：{detail[:240]}"


def parse_time(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    value = (value or "").strip()
    if not value:
        return 0.0
    if ":" in value:
        parts = value.split(":")
        try:
            parts = [float(p) for p in parts]
        except ValueError as exc:
            raise ValueError(f"时间格式不正确：{value}") from exc
        if len(parts) == 2:
            return max(0.0, parts[0] * 60 + parts[1])
        if len(parts) == 3:
            return max(0.0, parts[0] * 3600 + parts[1] * 60 + parts[2])
        raise ValueError(f"时间格式不正确：{value}")
    try:
        return max(0.0, float(value))
    except ValueError as exc:
        raise ValueError(f"时间格式不正确：{value}") from exc


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def copy_output(src: Path, outdir: Path, name: str | None = None) -> Path:
    dest = unique_path(outdir, name or src.name)
    shutil.copy2(src, dest)
    return dest


def open_image(path: Path):
    from PIL import Image, ImageOps
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass
    Image.MAX_IMAGE_PIXELS = 400_000_000
    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img


def fit_size(size: tuple[int, int], box: tuple[int, int], mode: str = "contain") -> tuple[int, int]:
    w, h = size
    bw, bh = box
    if bw <= 0 or bh <= 0 or w <= 0 or h <= 0:
        return (w, h)
    if mode == "stretch":
        return (max(1, round(bw)), max(1, round(bh)))
    ratio = min(bw / w, bh / h) if mode == "contain" else max(bw / w, bh / h)
    return (max(1, round(w * ratio)), max(1, round(h * ratio)))


def even(n: int) -> int:
    return max(2, int(n) - int(n) % 2)


def clean_old_jobs(max_age_hours: float = 12.0) -> None:
    if not JOBS_DIR.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for child in JOBS_DIR.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except Exception:
            pass


def resource_path(*parts: str) -> Path:
    return BASE_DIR.joinpath(*parts)


def clean_gallery(max_age_hours: float = 12.0) -> None:
    if not GALLERY_DIR.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for child in GALLERY_DIR.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except Exception:
            pass
