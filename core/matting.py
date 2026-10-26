from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image

_MODEL = Path(__file__).resolve().parent / "data" / "u2netp.onnx"
_session = None
_session_failed = False
_session_lock = threading.Lock()
_run_lock = threading.Lock()


def available() -> bool:
    return _MODEL.exists()


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
                _session = ort.InferenceSession(
                    _MODEL.read_bytes(),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
            except Exception:
                _session_failed = True
    return _session


def alpha_mask(image: Image.Image) -> np.ndarray | None:
    """Return a soft 0-255 alpha mask estimated by the bundled U2-Netp model."""
    session = _get_session()
    if session is None:
        return None
    try:
        rgb = image.convert("RGB")
        original_size = rgb.size
        small = rgb.resize((320, 320), Image.Resampling.LANCZOS)
        data = np.asarray(small, dtype=np.float32) / 255.0
        data[:, :, 0] = (data[:, :, 0] - 0.485) / 0.229
        data[:, :, 1] = (data[:, :, 1] - 0.456) / 0.224
        data[:, :, 2] = (data[:, :, 2] - 0.406) / 0.225
        input_data = np.expand_dims(data.transpose((2, 0, 1)), axis=0).astype(np.float32)
        input_name = session.get_inputs()[0].name
        with _run_lock:
            prediction = session.run(None, {input_name: input_data})[0][0, 0]
        high = float(prediction.max())
        if high < 0.2:
            return None
        prediction = np.clip(prediction, 0.0, 1.0)
        mask = Image.fromarray((prediction * 255).astype(np.uint8), "L")
        mask = mask.resize(original_size, Image.Resampling.LANCZOS)
        return np.asarray(mask, dtype=np.uint8)
    except Exception:
        return None
