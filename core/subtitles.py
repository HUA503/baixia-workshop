from __future__ import annotations

import importlib.util
import subprocess
import threading
import time
from pathlib import Path

from .utils import find_ffmpeg, probe_duration, unique_path

MODEL_DIR = Path(__file__).resolve().parent / "data" / "faster-whisper-tiny"
_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")

_model = None
_model_failed = False
_model_lock = threading.Lock()

LANG_NAMES = {
    "zh": "中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
}


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None and all(
        (MODEL_DIR / name).exists() for name in _MODEL_FILES
    )


def _get_model():
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    with _model_lock:
        if _model is None and not _model_failed:
            try:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    str(MODEL_DIR), device="cpu", compute_type="int8", local_files_only=True
                )
            except Exception:
                _model_failed = True
    return _model


def _timestamp(seconds: float) -> str:
    total = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _extract_audio(src: Path, dest: Path) -> None:
    exe = find_ffmpeg()
    if not exe:
        raise RuntimeError("未找到 FFmpeg，无法读取音轨")
    proc = subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900, creationflags=0x08000000,
    )
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 44:
        detail = (proc.stderr or "").strip().splitlines()
        raise RuntimeError("无法读取音轨" + (f"：{detail[-1]}" if detail else ""))


def subtitles(job, inputs: list[Path], opts: dict) -> list[Path]:
    if not available():
        raise RuntimeError(
            "本地字幕模型未就绪：请运行 install.bat 安装 faster-whisper，"
            "并确认 core/data/faster-whisper-tiny 模型完整"
        )
    src = inputs[0]
    language = str(opts.get("language", "auto") or "auto")
    if language == "auto":
        language = None
    elif language not in LANG_NAMES:
        language = None
    fmt = str(opts.get("format", "srt") or "srt")
    if fmt not in {"srt", "txt", "both"}:
        fmt = "srt"
    vad = bool(opts.get("vad", True))
    duration = probe_duration(src)
    wav = job.dir / "speech-16k.wav"
    started = time.time()
    try:
        job.report(4, "提取音轨")
        _extract_audio(src, wav)
        model = _get_model()
        if model is None:
            raise RuntimeError("Whisper 模型加载失败，请检查模型文件与 faster-whisper 安装")
        job.report(12, "加载本地 Whisper 模型")
        segments, info = model.transcribe(
            str(wav), language=language, vad_filter=vad, beam_size=5,
            condition_on_previous_text=False,
        )
        rows = []
        for segment in segments:
            job.report(15 + int(min(1.0, (segment.end / duration if duration else 0)) * 78), "识别语音")
            text = " ".join((segment.text or "").split())
            if text:
                rows.append((float(segment.start), float(segment.end), text))
        if not rows:
            raise RuntimeError("没有识别到语音，请确认文件包含清晰人声")

        detected = (info.language or "auto") if info else "auto"
        lang_label = LANG_NAMES.get(detected, detected)
        outputs: list[Path] = []
        if fmt in {"srt", "both"}:
            dest = unique_path(job.outdir, f"{src.stem}.srt")
            with dest.open("w", encoding="utf-8-sig", newline="\n") as fh:
                for index, (start, end, text) in enumerate(rows, 1):
                    fh.write(f"{index}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}\n\n")
            outputs.append(dest)
            job.add_output(dest)
        if fmt in {"txt", "both"}:
            dest = unique_path(job.outdir, f"{src.stem}.txt")
            dest.write_text("\n".join(row[2] for row in rows) + "\n", encoding="utf-8")
            outputs.append(dest)
            job.add_output(dest)
        job.note = f"Whisper tiny · {lang_label} · {len(rows)} 段 · {time.time() - started:.0f}s"
        job.report(97, "字幕完成")
        return outputs
    finally:
        try:
            wav.unlink(missing_ok=True)
        except Exception:
            pass
