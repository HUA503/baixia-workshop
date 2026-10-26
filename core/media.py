from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

from .utils import (
    even,
    find_ffmpeg,
    fmt_time,
    has_stream,
    make_zip,
    parse_time,
    probe_duration,
    run_ffmpeg,
    unique_path,
)

class TargetMiss(Exception):
    def __init__(self, size: int):
        super().__init__("target miss")
        self.size = size


_hw_encoder: str | None = None
_hw_detected = False
_hw_lock = threading.Lock()

AUDIO_CODEC = {
    "mp3": ["-c:a", "libmp3lame"],
    "m4a": ["-c:a", "aac"],
    "aac": ["-c:a", "aac"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
}


def _require_ffmpeg() -> None:
    if not find_ffmpeg():
        raise RuntimeError("未找到 FFmpeg，请安装后重试")


def _prog(job, lo: int, hi: int, message: str = ""):
    def cb(pct: int):
        job.report(lo + int(max(0, min(100, pct)) * (hi - lo) / 100), message)
    return cb


def _scale_filter(height: int | None) -> list[str]:
    if not height:
        return []
    return ["-vf", f"scale=-2:min({int(height)}\\,ih)"]


def _probe_size(path: Path) -> tuple[int, int] | None:
    exe = find_ffmpeg()
    if not exe:
        return None
    import subprocess

    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=0x08000000,
        )
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", proc.stderr or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None


def _probe_display_size(path: Path) -> tuple[int, int] | None:
    exe = find_ffmpeg()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=0x08000000,
        )
        text = proc.stderr or ""
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
        if not m:
            return None
        width, height = int(m.group(1)), int(m.group(2))
        rotation = re.search(r"rotation of\s*(-?\d+(?:\.\d+)?)\s*degrees", text, re.I)
        if not rotation:
            rotation = re.search(r"rotate\s*:\s*(-?\d+)", text, re.I)
        degrees = abs(int(float(rotation.group(1)))) if rotation else 0
        if degrees % 180 == 90:
            width, height = height, width
        return width, height
    except Exception:
        return None


def _test_hw_encoder(exe: str, encoder: str) -> bool:
    probe = [
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24", "-t", "0.4",
    ]
    if encoder == "h264_nvenc":
        probe += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "28", "-pix_fmt", "yuv420p"]
    elif encoder == "h264_qsv":
        probe += ["-c:v", "h264_qsv", "-global_quality", "28", "-pix_fmt", "yuv420p"]
    elif encoder == "h264_amf":
        probe += ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                  "-qp_i", "28", "-qp_p", "28", "-qp_b", "28", "-pix_fmt", "yuv420p"]
    else:
        return False
    probe += ["-f", "null", "-"]
    try:
        proc = subprocess.run(
            [exe, *probe], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=45,
            creationflags=0x08000000,
        )
        return proc.returncode == 0
    except Exception:
        return False


def detect_hw_encoder() -> str:
    global _hw_encoder, _hw_detected
    if _hw_detected and _hw_encoder is not None:
        return _hw_encoder
    with _hw_lock:
        if _hw_detected and _hw_encoder is not None:
            return _hw_encoder
        override = (os.environ.get("BAIXIA_VIDEO_ENCODER") or "").strip()
        if override == "libx264":
            _hw_encoder = "libx264"
            _hw_detected = True
            return _hw_encoder
        exe = find_ffmpeg()
        _hw_encoder = "libx264"
        if exe:
            try:
                listing = subprocess.run(
                    [exe, "-hide_banner", "-encoders"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30,
                    creationflags=0x08000000,
                ).stdout or ""
                candidates = [override] if override else ["h264_nvenc", "h264_qsv", "h264_amf"]
                for encoder in candidates:
                    if encoder and encoder in listing and _test_hw_encoder(exe, encoder):
                        _hw_encoder = encoder
                        break
            except Exception:
                pass
        _hw_detected = True
        return _hw_encoder


def hw_encoder_name() -> str:
    return detect_hw_encoder()


def hw_encoder_label() -> str:
    return {
        "h264_nvenc": "NVENC",
        "h264_qsv": "Quick Sync",
        "h264_amf": "AMF",
    }.get(detect_hw_encoder(), "CPU")


def _video_codec(fmt: str, crf: int, encoder: str | None = None) -> list[str]:
    fmt = fmt.lower()
    if fmt == "webm":
        return ["-c:v", "libvpx-vp9", "-crf", str(crf + 8), "-b:v", "0",
                "-row-mt", "1", "-deadline", "good", "-cpu-used", "2",
                "-c:a", "libopus", "-b:a", "128k"]
    chosen = encoder or detect_hw_encoder()
    if chosen == "h264_nvenc":
        args = ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
                "-rc", "vbr", "-cq", str(crf), "-b:v", "0", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k"]
    elif chosen == "h264_qsv":
        args = ["-c:v", "h264_qsv", "-global_quality", str(crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k"]
    elif chosen == "h264_amf":
        args = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                "-qp_i", str(crf), "-qp_p", str(crf), "-qp_b", str(crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    else:
        args = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k"]
    if fmt in {"mp4", "mov"}:
        args += ["-movflags", "+faststart"]
    return args


def video_convert(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    fmt = opts.get("format", "mp4")
    crf = max(16, min(38, int(float(opts.get("crf", 23)))))
    resolution = str(opts.get("resolution", "keep"))
    height = int(resolution) if resolution.isdigit() else None
    dest = unique_path(job.outdir, f"{src.stem}.{fmt}")
    duration = probe_duration(src)
    encoder = detect_hw_encoder()
    used_encoder = encoder
    args = ["-i", str(src), "-map", "0:V:0", "-map", "0:a:0?", *_scale_filter(height), *_video_codec(fmt, crf, encoder), str(dest)]
    job.report(6, f"准备转码 · {hw_encoder_label() if fmt != 'webm' else 'CPU'}")
    try:
        run_ffmpeg(args, duration=duration, progress=_prog(job, 8, 94, "转码中"))
    except RuntimeError:
        if encoder == "libx264" or fmt == "webm":
            raise
        used_encoder = "libx264"
        job.report(15, "硬件编码失败，回退 CPU")
        args = ["-i", str(src), "-map", "0:V:0", "-map", "0:a:0?", *_scale_filter(height), *_video_codec(fmt, crf, "libx264"), str(dest)]
        run_ffmpeg(args, duration=duration, progress=_prog(job, 20, 94, "CPU 转码中"))
    if fmt == "webm":
        job.note = "CPU VP9 编码"
    else:
        job.note = f"{hw_encoder_label() if used_encoder != 'libx264' else 'CPU'} 编码"
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def _compress_to_target(job, src: Path, dest: Path, target_mb: float, height: int | None,
                        duration: float | None):
    if not duration or duration <= 0:
        raise ValueError("无法读取视频时长，不能按目标大小压缩")
    target_bytes = target_mb * 1024 * 1024
    has_audio = has_stream(src, "audio")
    total_kbps = target_bytes * 8 / duration / 1000
    compact = total_kbps < 480
    audio_kbps = (48 if compact else 128) if has_audio else 0
    video_kbps = max(48, int((total_kbps - audio_kbps - 6) * 0.97))
    passlog = job.dir / "x264pass"

    def clear_passlog():
        for leftover in job.dir.glob("x264pass*"):
            try:
                leftover.unlink()
            except Exception:
                pass

    def encode(bitrate: int, lo: int, hi: int, note: str) -> int:
        try:
            first = [
                "-i", str(src), "-map", "0:V:0", *_scale_filter(height),
                "-c:v", "libx264", "-preset", "medium", "-b:v", f"{bitrate}k",
                "-pix_fmt", "yuv420p", "-pass", "1", "-passlogfile", str(passlog),
                "-an", "-f", "null", os.devnull,
            ]
            run_ffmpeg(first, duration=duration, progress=_prog(job, lo, lo + int((hi - lo) * 0.42), "两遍压缩 1/2"))
            second = [
                "-i", str(src), "-map", "0:V:0",
                *(["-map", "0:a:0?"] if has_audio else []), *_scale_filter(height),
                "-c:v", "libx264", "-preset", "medium", "-b:v", f"{bitrate}k",
                "-pix_fmt", "yuv420p", "-pass", "2", "-passlogfile", str(passlog),
            ]
            if has_audio:
                second += ["-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ac", "2"]
            second += ["-movflags", "+faststart", str(dest)]
            run_ffmpeg(second, duration=duration, progress=_prog(job, lo + int((hi - lo) * 0.42), hi, note))
            return dest.stat().st_size
        finally:
            clear_passlog()

    job.report(6, f"目标上限 {target_mb:g} MB · CPU 两遍编码")
    size = encode(video_kbps, 8, 54, "两遍压缩 2/2")
    if size > target_bytes:
        video_kbps = max(48, int(video_kbps * (target_bytes / size) * 0.96))
        job.report(55, "体积超出目标，校准一次")
        size = encode(video_kbps, 56, 94, "校准编码")
    if size > target_bytes:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise TargetMiss(size)
    actual = size / 1048576
    job.note = f"目标上限 {target_mb:g} MB · 实际 {actual:.2f} MB · CPU 两遍"
    if actual < target_mb * 0.9:
        job.note += " · 视频内容简单，已接近最高画质（未填充）"
    job.message = f"{target_mb:g} MB 上限 → 实际 {actual:.2f} MB"
    job.report(96, job.message)
    job.add_output(dest)
    return [dest]


def video_compress(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    resolution = str(opts.get("resolution", "auto"))
    dest = unique_path(job.outdir, f"{src.stem}-compressed.mp4")
    duration = probe_duration(src)
    custom_size = bool(opts.get("custom_size", False))
    target_mb = float(opts.get("target_mb", 0) or 0)
    if custom_size:
        source_mb = src.stat().st_size / 1048576
        if target_mb <= 0:
            raise ValueError("请设置有效的目标大小")
        if target_mb >= source_mb * 0.995:
            raise ValueError(f"目标大小必须小于原视频（{source_mb:.1f} MB）")
        source_size = _probe_size(src)
        source_h = source_size[1] if source_size else None
        if resolution == "auto":
            heights = [None]
            for candidate in (1080, 720, 480):
                if source_h is None or source_h > candidate:
                    heights.append(candidate)
        elif resolution == "keep":
            heights = [None]
        else:
            heights = [int(resolution) if resolution.isdigit() else None]
        last_miss = None
        used_height = heights[0]
        for index, current_h in enumerate(heights):
            try:
                _compress_to_target(job, src, dest, target_mb, current_h, duration)
                used_height = current_h
                last_miss = None
                break
            except TargetMiss as miss:
                last_miss = miss
                if index + 1 < len(heights):
                    job.report(30, "目标偏小，降低分辨率重试")
                    continue
                break
        if last_miss is not None:
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
            raise ValueError(f"无法压到 {target_mb:g} MB：最低约 {last_miss.size / 1048576:.2f} MB，请调大目标")
        if used_height != heights[0]:
            job.note += f" · {used_height}p"
        elif used_height is None and source_h and source_h > 1080:
            job.note += " · 原分辨率"
        return [dest]
    height = 720 if resolution == "auto" else (int(resolution) if resolution.isdigit() else None)
    level = opts.get("level", "standard")
    crf = {"light": 23, "standard": 28, "strong": 33}.get(level, 28)
    encoder = detect_hw_encoder()
    used_encoder = encoder
    args = ["-i", str(src), "-map", "0:V:0", "-map", "0:a:0?", *_scale_filter(height), *_video_codec("mp4", crf, encoder), str(dest)]
    job.report(6, f"开始压缩 · {hw_encoder_label()}")
    try:
        run_ffmpeg(args, duration=duration, progress=_prog(job, 8, 94, "压缩中"))
    except RuntimeError:
        if encoder == "libx264":
            raise
        used_encoder = "libx264"
        job.report(15, "硬件编码失败，回退 CPU")
        args = ["-i", str(src), "-map", "0:V:0", "-map", "0:a:0?", *_scale_filter(height), *_video_codec("mp4", crf, "libx264"), str(dest)]
        run_ffmpeg(args, duration=duration, progress=_prog(job, 20, 94, "CPU 压缩中"))
    before = src.stat().st_size
    after = dest.stat().st_size if dest.exists() else 0
    if after and before:
        job.message = f"完成 · {before / 1048576:.1f} MB → {after / 1048576:.1f} MB"
    job.note = f"{hw_encoder_label() if used_encoder != 'libx264' else 'CPU'} 编码"
    job.report(96, job.message or "完成")
    job.add_output(dest)
    return [dest]


def video_crop(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    size = _probe_display_size(src) or _probe_size(src)
    if not size:
        raise RuntimeError("无法读取视频尺寸")
    width, height = size
    ratio_key = str(opts.get("ratio", "original"))
    if ratio_key == "original":
        ratio = width / max(1, height)
    elif ratio_key == "custom":
        try:
            ratio = float(opts.get("ratio_w", 16)) / max(0.01, float(opts.get("ratio_h", 9)))
        except (TypeError, ValueError) as exc:
            raise ValueError("自定义比例无效") from exc
    else:
        ratio = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1, "4:3": 4 / 3, "3:4": 3 / 4}.get(ratio_key)
        if not ratio:
            raise ValueError("不支持的画面比例")
    if width / max(1, height) > ratio:
        crop_w, crop_h = round(height * ratio), height
    else:
        crop_w, crop_h = width, round(width / ratio)
    zoom = max(30, min(100, int(float(opts.get("zoom", 100))))) / 100.0
    crop_w, crop_h = max(16, round(crop_w * zoom)), max(16, round(crop_h * zoom))
    anchor = str(opts.get("anchor", "center"))
    ax = 0.0 if anchor in {"left", "top-left", "bottom-left"} else (1.0 if anchor in {"right", "top-right", "bottom-right"} else 0.5)
    ay = 0.0 if anchor in {"top", "top-left", "top-right"} else (1.0 if anchor in {"bottom", "bottom-left", "bottom-right"} else 0.5)
    x = round(max(0, min(width - crop_w, (width - crop_w) * ax)))
    y = round(max(0, min(height - crop_h, (height - crop_h) * ay)))
    crop_w, crop_h, x, y = even(crop_w), even(crop_h), even(x), even(y)
    if crop_w < 16 or crop_h < 16:
        raise ValueError("裁剪区域太小")
    duration = probe_duration(src)
    dest = unique_path(job.outdir, f"{src.stem}-crop.mp4")
    encoder = detect_hw_encoder()
    used_encoder = encoder
    args = ["-i", str(src), "-map", "0:V:0", "-map", "0:a:0?", "-vf", f"crop={crop_w}:{crop_h}:{x}:{y}",
            *_video_codec("mp4", 20, encoder), "-c:a", "aac", "-b:a", "192k", str(dest)]
    job.report(6, f"画面裁剪 · {hw_encoder_label()}")
    try:
        run_ffmpeg(args, duration=duration, progress=_prog(job, 8, 94, "裁剪画面"))
    except RuntimeError:
        if encoder == "libx264":
            raise
        used_encoder = "libx264"
        job.report(15, "硬件编码失败，回退 CPU")
        args = ["-i", str(src), "-map", "0:V:0", "-map", "0:a:0?", "-vf", f"crop={crop_w}:{crop_h}:{x}:{y}",
                *_video_codec("mp4", 20, "libx264"), "-c:a", "aac", "-b:a", "192k", str(dest)]
        run_ffmpeg(args, duration=duration, progress=_prog(job, 20, 94, "CPU 裁剪画面"))
    job.note = f"{crop_w}×{crop_h} · {hw_encoder_label() if used_encoder != 'libx264' else 'CPU'} 编码"
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def video_trim(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    start = parse_time(opts.get("start", 0))
    end = parse_time(opts.get("end", ""))
    if end <= 0:
        raise ValueError("请填写结束时间")
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    total = probe_duration(src)
    if total:
        if start >= total:
            raise ValueError(f"开始时间超过了视频长度（{fmt_time(total)}）")
        end = min(end, total)
    duration = end - start
    if duration <= 0:
        raise ValueError("裁剪后的片段长度为 0，请调整时间")
    copy_mode = bool(opts.get("copy", True))
    dest = unique_path(job.outdir, f"{src.stem}-trim.mp4")
    if copy_mode and src.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        args = ["-ss", str(start), "-i", str(src), "-t", str(duration), "-c", "copy",
                "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(dest)]
        job.report(10, "快速裁剪")
        run_ffmpeg(args, duration=duration, progress=_prog(job, 15, 94, "裁剪中"))
        job.report(96, "完成")
        job.add_output(dest)
        return [dest]
    args = ["-ss", str(start), "-i", str(src), "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)]
    job.report(8, "重新编码裁剪")
    run_ffmpeg(args, duration=duration, progress=_prog(job, 10, 94, "裁剪中"))
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def video_concat(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    if len(inputs) < 2:
        raise ValueError("请至少选择两段视频")
    size = _probe_size(inputs[0])
    if size:
        first_w, first_h = size
        target_h = even(min(1080, first_h))
        target_w = even(max(2, round(first_w * target_h / max(1, first_h))))
    else:
        target_w, target_h = 1280, 720
    temp_dir = job.dir / "concat-parts"
    temp_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    total = len(inputs)
    for i, src in enumerate(inputs, 1):
        lo = 3 + int((i - 1) / total * 65)
        hi = 3 + int(i / total * 65)
        job.report(lo, f"统一格式 {i}/{total}")
        out = temp_dir / f"part-{i:03d}.mp4"
        audio = has_stream(src, "audio")
        args = ["-i", str(src)]
        if not audio:
            args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        args += ["-map", "0:v:0"]
        args += ["-map", "1:a:0"] if not audio else ["-map", "0:a:0"]
        args += [
            "-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                   f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        ]
        if not audio:
            args += ["-shortest"]
        args += [str(out)]
        run_ffmpeg(args, duration=probe_duration(src), progress=_prog(job, lo, hi, f"统一格式 {i}/{total}"))
        normalized.append(out)
    list_file = temp_dir / "list.txt"
    with list_file.open("w", encoding="utf-8") as fh:
        for p in normalized:
            safe = str(p).replace("\\", "/").replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")
    dest = unique_path(job.outdir, "video-concat.mp4")
    job.report(72, "拼接视频")
    total_duration = sum(d for d in (probe_duration(p) for p in inputs) if d) or None
    args = ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy",
            "-movflags", "+faststart", str(dest)]
    run_ffmpeg(args, duration=total_duration, progress=_prog(job, 74, 95, "拼接视频"))
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def video_to_gif(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    start = parse_time(opts.get("start", 0))
    duration = max(0.3, float(opts.get("duration", 3)))
    total = probe_duration(src)
    if total:
        if start >= total:
            raise ValueError(f"开始时间超过了视频长度（{fmt_time(total)}）")
        duration = min(duration, max(0.3, total - start))
    fps = max(5, min(30, int(float(opts.get("fps", 12)))))
    width = max(120, min(1280, int(float(opts.get("width", 640)))))
    dest = unique_path(job.outdir, f"{src.stem}.gif")
    vf = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[s0][s1];"
        f"[s0]palettegen=max_colors=256:stats_mode=diff[p];"
        f"[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle"
    )
    args = ["-ss", str(start), "-t", str(duration), "-i", str(src), "-vf", vf,
            "-loop", "0", str(dest)]
    job.report(8, "生成调色板与 GIF")
    run_ffmpeg(args, duration=duration, progress=_prog(job, 10, 94, "生成 GIF"))
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def video_audio(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    if not has_stream(src, "audio"):
        raise RuntimeError("这个视频没有音轨")
    fmt = opts.get("format", "mp3")
    bitrate = str(opts.get("bitrate", "192"))
    ext = {"mp3": ".mp3", "m4a": ".m4a", "wav": ".wav", "flac": ".flac"}.get(fmt, ".mp3")
    dest = unique_path(job.outdir, f"{src.stem}{ext}")
    codec = AUDIO_CODEC.get(fmt, AUDIO_CODEC["mp3"])
    args = ["-i", str(src), "-vn", *codec]
    if fmt in {"mp3", "m4a"}:
        args += ["-b:a", f"{bitrate}k"]
    args += [str(dest)]
    job.report(8, "提取音轨")
    run_ffmpeg(args, duration=probe_duration(src), progress=_prog(job, 10, 94, "提取音轨"))
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def video_frames(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    interval = max(0.2, float(opts.get("interval", 1)))
    fmt = "png" if opts.get("format") == "png" else "jpg"
    frames_dir = job.dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = frames_dir / f"{src.stem}-%04d.{fmt}"
    fps = 1.0 / interval
    args = ["-i", str(src), "-vf", f"fps={fps:.6f}".rstrip("0").rstrip(".")]
    if fmt == "jpg":
        args += ["-q:v", "2"]
    args += [str(pattern)]
    duration = probe_duration(src)
    job.report(8, "抽取画面")
    run_ffmpeg(args, duration=duration, progress=_prog(job, 10, 94, "抽取画面"))
    frames = sorted(frames_dir.glob(f"*-[0-9][0-9][0-9][0-9].{fmt}"))
    if not frames:
        raise RuntimeError("没有抽到任何画面，请检查视频或间隔设置")
    zip_path = unique_path(job.outdir, f"{src.stem}-frames.zip")
    make_zip(frames, zip_path)
    job.report(96, f"完成 · {len(frames)} 张")
    job.add_output(zip_path)
    return [zip_path]


def video_mute(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    dest = unique_path(job.outdir, f"{src.stem}-silent.mp4")
    if src.suffix.lower() in {".mp4", ".m4v", ".mov", ".mkv"}:
        args = ["-i", str(src), "-c", "copy", "-an", str(dest)]
        try:
            job.report(20, "移除音轨")
            run_ffmpeg(args, duration=probe_duration(src), progress=_prog(job, 20, 92, "移除音轨"))
        except Exception:
            args = ["-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-pix_fmt", "yuv420p", "-an", str(dest)]
            run_ffmpeg(args, duration=probe_duration(src), progress=_prog(job, 20, 92, "重新编码"))
    else:
        args = ["-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p", "-an", str(dest)]
        run_ffmpeg(args, duration=probe_duration(src), progress=_prog(job, 20, 92, "重新编码"))
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def gif_to_video(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    fmt = opts.get("format", "mp4")
    ext = ".webm" if fmt == "webm" else ".mp4"
    dest = unique_path(job.outdir, f"{src.stem}{ext}")
    filters = "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=25"
    if fmt == "webm":
        codec = ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-row-mt", "1"]
    else:
        codec = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", "-an"]
    job.report(10, "转换 GIF")
    run_ffmpeg(["-i", str(src), "-vf", filters, *codec, str(dest)],
               duration=probe_duration(src), progress=_prog(job, 12, 94, "转换 GIF"))
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]


def audio_convert(job, inputs: list[Path], opts: dict):
    _require_ffmpeg()
    src = inputs[0]
    fmt = opts.get("format", "mp3")
    bitrate = str(opts.get("bitrate", "192"))
    sample_rate = str(opts.get("sample_rate", "keep"))
    ext = {"mp3": ".mp3", "wav": ".wav", "flac": ".flac", "m4a": ".m4a", "aac": ".aac"}.get(fmt, ".mp3")
    dest = unique_path(job.outdir, f"{src.stem}{ext}")
    args = ["-i", str(src), "-vn", *AUDIO_CODEC.get(fmt, AUDIO_CODEC["mp3"])]
    if fmt in {"mp3", "m4a", "aac"}:
        args += ["-b:a", f"{bitrate}k"]
    if sample_rate.isdigit():
        args += ["-ar", sample_rate]
    args += [str(dest)]
    job.report(8, "转换音频")
    run_ffmpeg(args, duration=probe_duration(src), progress=_prog(job, 10, 94, "转换音频"))
    job.report(96, "完成")
    job.add_output(dest)
    return [dest]
