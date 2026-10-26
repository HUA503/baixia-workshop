from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .images import save_image
from .utils import open_image, unique_path

MODEL_DIR = Path(__file__).resolve().parent / "data" / "realesrgan"
MODEL_PATH = MODEL_DIR / "model.onnx"
TILE = 128
SCALE = 4
MAX_OUTPUT_PIXELS = 24_000_000
MAX_OUTPUT_SIDE = 8192

_session = None
_session_failed = False
_session_lock = threading.Lock()
_run_lock = threading.Lock()


def available() -> bool:
    return MODEL_PATH.exists() and (MODEL_DIR / "model.data").exists()


def _get_session():
    global _session, _session_failed
    if _session is not None or _session_failed:
        return _session
    with _session_lock:
        if _session is None and not _session_failed:
            try:
                import onnxruntime as ort

                options = ort.SessionOptions()
                options.log_severity_level = 3
                options.intra_op_num_threads = max(1, min(4, __import__("os").cpu_count() or 4))
                _session = ort.InferenceSession(
                    str(MODEL_PATH), sess_options=options, providers=["CPUExecutionProvider"]
                )
            except Exception:
                _session_failed = True
    return _session


def _starts(length: int, tile: int, stride: int) -> list[int]:
    if length <= tile:
        return [0]
    values = list(range(0, length - tile + 1, stride))
    if values[-1] != length - tile:
        values.append(length - tile)
    return values


def _ai_upscale(rgb: np.ndarray, job) -> np.ndarray:
    session = _get_session()
    if session is None:
        raise RuntimeError("超分模型加载失败，请确认 core/data/realesrgan 完整")
    input_name = session.get_inputs()[0].name
    height, width = rgb.shape[:2]
    out_h, out_w = height * SCALE, width * SCALE
    out = np.zeros((out_h, out_w, 3), dtype=np.float32)
    weight = np.zeros((out_h, out_w, 1), dtype=np.float32)
    stride = TILE - 32
    xs = _starts(width, TILE, stride)
    ys = _starts(height, TILE, stride)
    total = max(1, len(xs) * len(ys))
    done = 0
    with _run_lock:
        for y in ys:
            for x in xs:
                tile = rgb[y:y + TILE, x:x + TILE]
                if tile.shape[0] < TILE or tile.shape[1] < TILE:
                    tile = np.pad(tile, ((0, TILE - tile.shape[0]), (0, TILE - tile.shape[1]), (0, 0)), mode="edge")
                data = tile.astype(np.float32) / 255.0
                data = np.expand_dims(data.transpose(2, 0, 1), axis=0)
                pred = session.run(None, {input_name: data})[0][0]
                pred = np.clip(pred.transpose(1, 2, 0), 0.0, 1.0) * 255.0
                oy, ox = y * SCALE, x * SCALE
                vh = min(TILE, height - y) * SCALE
                vw = min(TILE, width - x) * SCALE
                out[oy:oy + vh, ox:ox + vw] += pred[:vh, :vw]
                weight[oy:oy + vh, ox:ox + vw] += 1.0
                done += 1
                job.report(8 + int(done / total * 84), f"AI 超分 {done}/{total} 块")
    out /= np.maximum(weight, 1.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def _fast_upscale(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    up = img.resize(size, Image.Resampling.LANCZOS)
    return up.filter(ImageFilter.UnsharpMask(radius=1.2, percent=85, threshold=2))


def _process(src: Path, dest_stem: str, job, scale: int, method: str, fmt: str) -> Path:
    with open_image(src) as opened:
        opened.load()
        image = opened.copy()
    try:
        has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
        alpha = image.getchannel("A") if has_alpha else None
        rgb = image.convert("RGBA")
        if has_alpha:
            canvas = Image.new("RGBA", image.size, (255, 255, 255, 255))
            canvas.alpha_composite(rgb)
            rgb = canvas
        rgb = rgb.convert("RGB")
        width, height = rgb.size
        target_w, target_h = width * scale, height * scale
        if target_w > MAX_OUTPUT_SIDE or target_h > MAX_OUTPUT_SIDE or target_w * target_h > MAX_OUTPUT_PIXELS:
            raise ValueError(
                f"输出尺寸 {target_w}×{target_h} 过大，请降低倍率或先缩小原图"
            )
        if method == "fast":
            job.report(20, "高质量插值放大")
            up = _fast_upscale(rgb, (target_w, target_h))
        else:
            job.report(6, "加载本地 Real-ESRGAN 模型")
            arr = _ai_upscale(np.asarray(rgb), job)
            up = Image.fromarray(arr, "RGB")
            if scale != SCALE:
                up = up.resize((target_w, target_h), Image.Resampling.LANCZOS)
        if alpha is not None:
            up_alpha = alpha.resize((target_w, target_h), Image.Resampling.LANCZOS)
            up = up.convert("RGBA")
            up.putalpha(up_alpha)
        suffix = ".png" if fmt == "png" or (fmt == "auto" and alpha is not None) else (".webp" if fmt == "webp" else ".jpg")
        dest = unique_path(job.outdir, f"{dest_stem}{suffix}")
        save_fmt = suffix.lstrip(".")
        save_image(up, dest, save_fmt, quality=94)
        up.close()
        return dest
    finally:
        image.close()


def image_upscale(job, inputs: list[Path], opts: dict):
    scale = int(float(opts.get("scale", 2)))
    if scale not in (2, 3, 4):
        raise ValueError("放大倍率只能是 2×、3× 或 4×")
    method = str(opts.get("method", "ai"))
    if method not in {"ai", "fast"}:
        method = "ai"
    if method == "ai" and not available():
        method = "fast"
    fmt = str(opts.get("format", "auto"))
    if fmt not in {"auto", "png", "jpg", "webp"}:
        fmt = "auto"
    outputs = []
    for index, src in enumerate(inputs, 1):
        job.report(4 + int((index - 1) / len(inputs) * 90), f"处理 {index}/{len(inputs)}")
        dest = _process(src, f"{src.stem}-{scale}x-{method}", job, scale, method, fmt)
        outputs.append(dest)
        job.add_output(dest)
    used = "Real-ESRGAN" if method == "ai" else "Lanczos 锐化"
    job.note = f"{used} · {scale}×"
    job.report(97, "完成")
    return outputs
