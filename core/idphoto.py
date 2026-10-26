from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance

from . import matting
from .images import background_alpha
from .utils import open_image, unique_path

PRESETS = {
    "one": ("一寸", 25, 35),
    "small_one": ("小一寸", 22, 32),
    "big_one": ("大一寸", 33, 48),
    "two": ("二寸", 35, 49),
    "small_two": ("小二寸", 35, 45),
    "big_two": ("大二寸", 35, 53),
    "passport": ("中国护照", 33, 48),
    "visa_us": ("美国签证", 51, 51),
}

BG_COLORS = {
    "white": (255, 255, 255),
    "blue": (67, 142, 219),
    "red": (217, 0, 27),
    "gray": (217, 217, 217),
}

_detector = None
_detector_failed = False
_detector_lock = threading.Lock()
_haar = None
_haar_failed = False


def _ascii_cache_dir() -> Path | None:
    candidates = []
    if os.environ.get("PUBLIC"):
        candidates.append(Path(os.environ["PUBLIC"]) / "baixia-cache")
    candidates.append(Path(tempfile.gettempdir()) / "baixia-cache")
    for candidate in candidates:
        if not all(ord(ch) < 128 for ch in str(candidate)):
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    return None


def _model_path() -> str | None:
    source = Path(__file__).resolve().parent / "data" / "face_detection_yunet_2023mar.onnx"
    if not source.exists():
        return None
    path = str(source)
    if all(ord(ch) < 128 for ch in path):
        return path
    cache = _ascii_cache_dir()
    if cache is None:
        return None
    target = cache / "face_detection_yunet_2023mar.onnx"
    try:
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copy2(source, target)
        return str(target)
    except Exception:
        return None


def _get_detector():
    global _detector, _detector_failed
    if _detector_failed:
        return None
    if _detector is not None:
        return _detector
    with _detector_lock:
        if _detector is None and not _detector_failed:
            import cv2

            model = _model_path()
            if not model:
                _detector_failed = True
                return None
            try:
                _detector = cv2.FaceDetectorYN.create(model, "", (320, 320), 0.85, 0.3, 5000)
            except Exception:
                _detector_failed = True
    return _detector


def _get_haar():
    global _haar, _haar_failed
    if _haar_failed:
        return None
    if _haar is not None:
        return _haar
    with _detector_lock:
        if _haar is None and not _haar_failed:
            import cv2

            try:
                cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
                if not all(ord(ch) < 128 for ch in str(cascade_path)):
                    cache = _ascii_cache_dir()
                    if cache is not None:
                        target = cache / "haarcascade_frontalface_default.xml"
                        if not target.exists():
                            shutil.copy2(cascade_path, target)
                        cascade_path = target
                cascade = cv2.CascadeClassifier(str(cascade_path))
                if cascade.empty():
                    _haar_failed = True
                else:
                    _haar = cascade
            except Exception:
                _haar_failed = True
    return _haar


def detect_faces(image: Image.Image) -> list[tuple[float, float, float, float]]:
    import cv2
    import numpy as np

    rgb = np.array(image.convert("RGB"))
    bgr = rgb[:, :, ::-1].copy()
    height, width = bgr.shape[:2]
    faces: list[tuple[float, float, float, float]] = []

    detector = _get_detector()
    if detector is not None:
        try:
            with _detector_lock:
                detector.setInputSize((width, height))
                _, raw = detector.detect(bgr)
            if raw is not None and len(raw):
                for item in raw:
                    x, y, w, h = [float(v) for v in item[:4]]
                    if w > 8 and h > 8:
                        faces.append((x, y, w, h))
        except Exception:
            faces = []

    if not faces:
        cascade = _get_haar()
        if cascade is not None:
            try:
                scale = min(1.0, 1200 / max(width, height))
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                if scale < 1.0:
                    small = cv2.resize(gray, (max(1, int(width * scale)), max(1, int(height * scale))))
                else:
                    small = gray
                found = cascade.detectMultiScale(small, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
                for x, y, w, h in found:
                    faces.append((x / scale, y / scale, w / scale, h / scale))
            except Exception:
                pass

    faces.sort(key=lambda box: box[2] * box[3], reverse=True)
    return faces


def _crop_box(size: tuple[int, int], aspect: float, face):
    width, height = size
    if face:
        x, y, w, h = face
        box_h = h * 1.95
        if box_h > height:
            box_h = height
        box_w = box_h * aspect
        if box_w > width:
            box_w = width
            box_h = box_w / aspect
        if box_h > height:
            box_h = height
            box_w = box_h * aspect
        center_x = x + w / 2
        top = y - h * 0.55
        left = center_x - box_w / 2
    else:
        if width / height >= aspect:
            box_h = height
            box_w = height * aspect
        else:
            box_w = width
            box_h = width / aspect
        left = (width - box_w) / 2
        top = (height - box_h) * 0.18
    left = min(max(0.0, left), max(0.0, width - box_w))
    top = min(max(0.0, top), max(0.0, height - box_h))
    return (round(left), round(top), round(left + box_w), round(top + box_h))


def _flatten(image: Image.Image, color=(255, 255, 255)) -> Image.Image:
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, color)
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return image.convert("RGB")


def idphoto(job, inputs: list[Path], opts: dict):
    preset_key = opts.get("size", "one")
    label, mm_w, mm_h = PRESETS.get(preset_key, PRESETS["one"])
    bg_key = opts.get("bg", "keep")
    bg_color = BG_COLORS.get(bg_key)
    dpi = max(200, min(600, int(float(opts.get("dpi", 300)))))
    auto_face = bool(opts.get("auto_face", True))
    enhance = bool(opts.get("enhance", True))
    ai_cutout = bool(opts.get("ai_cutout", True))
    tolerance = float(opts.get("tolerance", 30))
    target_w = max(60, round(mm_w / 25.4 * dpi))
    target_h = max(60, round(mm_h / 25.4 * dpi))
    aspect = mm_w / mm_h
    outputs = []

    for index, src in enumerate(inputs, 1):
        job.report(5 + int((index - 1) / len(inputs) * 88), f"制作证件照 {index}/{len(inputs)}")
        with open_image(src) as opened:
            opened.load()
            image = opened.copy()
        faces = detect_faces(image) if auto_face else []
        if faces:
            face = faces[0]
            if len(faces) > 1:
                job.report(5 + int((index - 1) / len(inputs) * 88), f"检测到 {len(faces)} 张人脸，使用最大的一张")
        else:
            face = None
            if auto_face:
                job.report(5 + int((index - 1) / len(inputs) * 88), "未检测到人脸，按构图中心裁剪")
        box = _crop_box(image.size, aspect, face)
        crop = image.crop(box)
        image.close()

        if enhance:
            crop = ImageEnhance.Brightness(crop).enhance(1.02)
            crop = ImageEnhance.Contrast(crop).enhance(1.03)
            crop = ImageEnhance.Color(crop).enhance(1.01)

        if bg_color is not None:
            import numpy as np

            rgb = np.array(_flatten(crop))
            alpha = matting.alpha_mask(crop) if ai_cutout else None
            if alpha is None:
                alpha = background_alpha(rgb, tolerance, feather=1.2, max_side=2000)
            foreground = crop.convert("RGBA")
            alpha_img = Image.fromarray(alpha, "L")
            if foreground.getchannel("A").getextrema() != (255, 255):
                alpha_img = ImageChops.multiply(alpha_img, foreground.getchannel("A"))
            foreground.putalpha(alpha_img)
            canvas = Image.new("RGBA", crop.size, (*bg_color, 255))
            canvas.alpha_composite(foreground)
            crop = canvas.convert("RGB")
        else:
            crop = _flatten(crop)

        resized = crop.resize((target_w, target_h), Image.Resampling.LANCZOS)
        suffix = f"{label}"
        dest = unique_path(job.outdir, f"{src.stem}-{suffix}-{target_w}x{target_h}.jpg")
        resized.save(
            dest,
            "JPEG",
            quality=95,
            optimize=True,
            progressive=True,
            subsampling=0,
            dpi=(dpi, dpi),
        )
        crop.close()
        resized.close()
        outputs.append(dest)
        job.add_output(dest)
        job.report(5 + int(index / len(inputs) * 88), f"完成 {index}/{len(inputs)}")

    return outputs
