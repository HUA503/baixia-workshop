from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from . import matting
from .utils import (
    make_zip,
    open_image,
    unique_path,
)

RENDER_EXTS = {"jpg": ".jpg", "jpeg": ".jpg", "png": ".png", "webp": ".webp", "avif": ".avif", "heic": ".heic", "tiff": ".tiff"}
KEEP_FORMATS = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".webp": "webp", ".avif": "avif", ".heic": "heic", ".heif": "heic", ".tif": "tiff", ".tiff": "tiff"}


def _flatten(img, background=(255, 255, 255)):
    from PIL import Image

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, background)
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def save_image(img, dest: Path, fmt: str, quality: int = 85, strip: bool = False) -> Path:
    fmt = (fmt or "png").lower()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt in {"jpg", "jpeg"}:
        img = _flatten(img)
        kwargs = {"quality": int(quality), "optimize": True, "progressive": True}
        if strip:
            kwargs["exif"] = b""
            kwargs.pop("icc_profile", None)
        img.save(dest, "JPEG", **kwargs)
    elif fmt == "png":
        img.save(dest, "PNG", optimize=True)
    elif fmt == "webp":
        kwargs = {"quality": int(quality), "method": 6}
        if strip:
            kwargs["exif"] = b""
        img.save(dest, "WEBP", **kwargs)
    elif fmt == "avif":
        img.convert("RGBA" if img.mode in ("RGBA", "LA") else "RGB").save(
            dest, "AVIF", quality=int(quality)
        )
    elif fmt == "heic":
        img.convert("RGBA" if img.mode in ("RGBA", "LA") else "RGB").save(
            dest, "HEIF", quality=int(quality)
        )
    elif fmt == "tiff":
        img.save(dest, "TIFF", compression="tiff_lzw")
    else:
        img.save(dest)
    return dest


def _resized(img, width: int = 0, height: int = 0, mode: str = "contain"):
    from PIL import Image

    ow, oh = img.size
    width, height = int(width or 0), int(height or 0)
    if width <= 0 and height <= 0:
        return img
    if width > 0 and height <= 0:
        return img.resize((width, max(1, round(oh * width / ow))), Image.Resampling.LANCZOS)
    if height > 0 and width <= 0:
        return img.resize((max(1, round(ow * height / oh)), height), Image.Resampling.LANCZOS)
    if mode == "stretch":
        return img.resize((width, height), Image.Resampling.LANCZOS)
    if mode == "cover":
        ratio = max(width / ow, height / oh)
        new = (max(1, round(ow * ratio)), max(1, round(oh * ratio)))
        resized = img.resize(new, Image.Resampling.LANCZOS)
        left = (new[0] - width) // 2
        top = (new[1] - height) // 2
        return resized.crop((left, top, left + width, top + height))
    ratio = min(width / ow, height / oh)
    return img.resize((max(1, round(ow * ratio)), max(1, round(oh * ratio))), Image.Resampling.LANCZOS)


def _limit_long_edge(img, limit: int):
    if not limit or limit <= 0:
        return img
    ow, oh = img.size
    if max(ow, oh) <= limit:
        return img
    from PIL import Image

    ratio = limit / max(ow, oh)
    return img.resize((max(1, round(ow * ratio)), max(1, round(oh * ratio))), Image.Resampling.LANCZOS)


def image_convert(job, inputs: list[Path], opts: dict):
    fmt = opts.get("format", "jpg")
    ext = RENDER_EXTS.get(fmt, ".png")
    quality = int(float(opts.get("quality", 85)))
    max_width = int(float(opts.get("max_width", 0) or 0))
    strip = bool(opts.get("strip", True))
    total = len(inputs)
    outputs = []
    for i, src in enumerate(inputs, 1):
        job.report(5 + int((i - 1) / total * 90), f"转换 {src.name}")
        with open_image(src) as img:
            img.load()
            if max_width > 0 and img.width > max_width:
                img = _resized(img, width=max_width)
            dest = unique_path(job.outdir, f"{src.stem}{ext}")
            save_image(img, dest, fmt, quality, strip)
            img.close()
        outputs.append(dest)
        job.add_output(dest)
    return outputs


def _encode_lossy(img, fmt: str, quality: int) -> bytes:
    fmt = fmt.lower()
    buf = BytesIO()
    if fmt == "jpg":
        img = _flatten(img)
        img.save(buf, "JPEG", quality=int(quality), optimize=True, progressive=True, exif=b"")
    elif fmt == "webp":
        img.save(buf, "WEBP", quality=int(quality), method=6, exif=b"")
    elif fmt == "avif":
        img.convert("RGBA" if img.mode in ("RGBA", "LA") else "RGB").save(
            buf, "AVIF", quality=int(quality)
        )
    else:
        raise ValueError(f"不支持的目标格式：{fmt}")
    return buf.getvalue()


def _scaled(img, factor: float):
    from PIL import Image

    width, height = img.size
    return img.resize((max(1, round(width * factor)), max(1, round(height * factor))), Image.Resampling.LANCZOS)


def _fit_to_size(img, fmt: str, target_bytes: int) -> bytes:
    best = None
    for factor in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.42, 0.35):
        work = img if factor == 1.0 else _scaled(img, factor)
        low, high = 10, 96
        candidate = None
        while low <= high:
            quality = (low + high) // 2
            data = _encode_lossy(work, fmt, quality)
            if len(data) <= target_bytes:
                candidate = data
                low = quality + 1
            else:
                high = quality - 1
        if candidate is not None:
            best = candidate
            break
    if best is None:
        best = _encode_lossy(_scaled(img, 0.25), fmt, 10)
    return best


def _lossy_format(fmt: str, source: Path) -> str:
    if fmt in {"jpg", "webp", "avif"}:
        return fmt
    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "jpg"
    if suffix == ".webp":
        return "webp"
    if suffix == ".avif":
        return "avif"
    return "webp"


def image_compress(job, inputs: list[Path], opts: dict):
    quality = int(float(opts.get("quality", 72)))
    max_dim = int(float(opts.get("max_dim", 1600) or 0))
    target_kb = float(opts.get("target_kb", 0) or 0)
    fmt = opts.get("format", "keep")
    outputs = []
    for i, src in enumerate(inputs, 1):
        job.report(5 + int((i - 1) / len(inputs) * 90), f"压缩 {src.name}")
        with open_image(src) as img:
            img.load()
            img = _limit_long_edge(img, max_dim)
            if target_kb > 0:
                target = _lossy_format(fmt, src)
                data = _fit_to_size(img, target, max(1024, int(target_kb * 1024)))
                dest = unique_path(job.outdir, f"{src.stem}-min{RENDER_EXTS.get(target, '.jpg')}")
                dest.write_bytes(data)
            else:
                if fmt == "keep":
                    target = KEEP_FORMATS.get(src.suffix.lower(), "jpg")
                else:
                    target = fmt
                ext = RENDER_EXTS.get(target, ".jpg")
                dest = unique_path(job.outdir, f"{src.stem}-min{ext}")
                save_image(img, dest, target, quality, strip=True)
        outputs.append(dest)
        job.add_output(dest)
    if target_kb > 0:
        job.note = f"目标 {target_kb:g} KB/张"
    return outputs


def image_resize(job, inputs: list[Path], opts: dict):
    width = int(float(opts.get("width", 1080) or 0))
    height = int(float(opts.get("height", 0) or 0))
    mode = opts.get("mode", "contain")
    if width <= 0 and height <= 0:
        raise ValueError("请填写目标宽度或高度")
    outputs = []
    for i, src in enumerate(inputs, 1):
        job.report(5 + int((i - 1) / len(inputs) * 90), f"缩放 {src.name}")
        with open_image(src) as img:
            img.load()
            resized = _resized(img, width, height, mode)
            target = KEEP_FORMATS.get(src.suffix.lower(), "png")
            if src.suffix.lower() == ".gif":
                target = "png"
            ext = RENDER_EXTS.get(target, ".png")
            dest = unique_path(job.outdir, f"{src.stem}-{resized.width}x{resized.height}{ext}")
            save_image(resized, dest, target, 92)
        outputs.append(dest)
        job.add_output(dest)
    return outputs


def image_rename(job, inputs: list[Path], opts: dict):
    import shutil

    pattern = (opts.get("pattern") or "{name}_{n:02}").strip()
    start = int(float(opts.get("start", 1) or 0))
    date = datetime.now().strftime("%Y%m%d")
    outputs = []
    for i, src in enumerate(inputs):
        job.report(5 + int(i / len(inputs) * 90), f"重命名 {src.name}")
        ext = src.suffix
        try:
            base = pattern.format(name=src.stem, n=start + i, date=date, ext=ext.lstrip("."))
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError("命名规则中有无法识别的占位符") from exc
        base = (base or src.stem).strip()
        if not base.lower().endswith(ext.lower()):
            base += ext
        dest = unique_path(job.outdir, base)
        shutil.copy2(src, dest)
        outputs.append(dest)
        job.add_output(dest)
    if opts.get("zip", True) and len(outputs) > 1:
        zip_path = make_zip(outputs, unique_path(job.outdir, "renamed-images.zip"))
        job.add_output(zip_path)
        return [zip_path]
    return outputs


def background_alpha(rgb, tolerance: float = 26, feather: float = 1, max_side: int = 2200):
    """Estimate an alpha mask for the foreground from border-connected background colors."""
    import cv2
    import numpy as np

    h, w = rgb.shape[:2]
    scale = 1.0
    work = rgb
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        work = cv2.resize(rgb, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    border = np.concatenate([
        work[0:2].reshape(-1, 3), work[-2:].reshape(-1, 3),
        work[:, 0:2].reshape(-1, 3), work[:, -2:].reshape(-1, 3),
    ]).astype(np.int16)
    bg = np.median(border, axis=0)
    diff = np.linalg.norm(work.astype(np.int16) - bg, axis=2)
    candidate = (diff < tolerance).astype(np.uint8)
    _, labels, _, _ = cv2.connectedComponentsWithStats(candidate, 8)
    edge_labels = set(labels[0, :].tolist()) | set(labels[-1, :].tolist()) | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    edge_labels.discard(0)
    bgmask = np.isin(labels, list(edge_labels)).astype(np.uint8) if edge_labels else np.zeros_like(candidate)
    fraction = float(bgmask.mean())
    if fraction < 0.002:
        alpha_small = np.full((work.shape[0], work.shape[1]), 255, np.uint8)
    else:
        alpha_small = ((1 - bgmask) * 255).astype(np.uint8)
        if feather > 0:
            alpha_small = cv2.GaussianBlur(alpha_small, (0, 0), sigmaX=max(0.5, feather))
    if scale != 1.0:
        return cv2.resize(alpha_small, (w, h), interpolation=cv2.INTER_LINEAR)
    return alpha_small


def image_bg(job, inputs: list[Path], opts: dict):
    import numpy as np

    tolerance = float(opts.get("tolerance", 26))
    feather = float(opts.get("feather", 1))
    method = opts.get("method", "ai")
    outputs = []
    for i, src in enumerate(inputs, 1):
        job.report(5 + int((i - 1) / len(inputs) * 90), f"去背景 {src.name}")
        with open_image(src) as img:
            img.load()
            original_alpha = img.convert("RGBA").split()[-1]
            rgb = np.array(img.convert("RGB"))
            alpha = matting.alpha_mask(img) if method == "ai" else None
            if alpha is None:
                alpha = background_alpha(rgb, tolerance, feather)
            from PIL import Image, ImageChops

            alpha_img = Image.fromarray(alpha, "L")
            if original_alpha.getextrema() != (255, 255):
                alpha_img = ImageChops.multiply(alpha_img, original_alpha)
            out = img.convert("RGB").copy()
            out.putalpha(alpha_img)
            dest = unique_path(job.outdir, f"{src.stem}-transparent.png")
            out.save(dest, "PNG", optimize=True)
        outputs.append(dest)
        job.add_output(dest)
    return outputs


def image_favicon(job, inputs: list[Path], opts: dict):
    from PIL import Image

    src = inputs[0]
    sizes_raw = opts.get("sizes") or "16,32,48,64,128,256"
    sizes = []
    for part in str(sizes_raw).replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(f"无法识别尺寸：{part}") from exc
        if 8 <= value <= 256:
            sizes.append(value)
    if not sizes:
        sizes = [16, 32, 48, 64, 128, 256]
    sizes = sorted(set(sizes))
    job.report(20, "绘制图标")
    with open_image(src) as img:
        img.load()
        rgba = img.convert("RGBA")
        side = max(rgba.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
        dest = unique_path(job.outdir, "favicon.ico")
        canvas.save(dest, "ICO", sizes=[(s, s) for s in sizes])
    job.add_output(dest)
    return [dest]
