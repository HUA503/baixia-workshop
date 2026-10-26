from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import socket
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import uvicorn
from core.handlers import HANDLERS
from core import matting, subtitles, upscale
from core.media import hw_encoder_label
from core.jobs import get_manager
from core.previews import generate_preview
from core.registry import CATEGORIES, TOOL_MAP, public_tools
from core.utils import (
    BASE_DIR,
    GALLERY_DIR,
    WEB_DIR,
    clean_gallery,
    clean_old_jobs,
    ensure_dirs,
    ffmpeg_version,
    find_ffmpeg,
    human_size,
    safe_filename,
    unique_path,
)
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

VERSION = "1.4.1"
MAX_FILES = 60
MAX_TOTAL_BYTES = int(os.environ.get("BAIXIA_MAX_UPLOAD_GB", "4")) * 1024**3


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    manager = get_manager()
    if os.environ.get("BAIXIA_WARM_OCR", "1") != "0":
        def warm():
            try:
                from core.ocr import get_engine

                get_engine()
            except Exception:
                pass

        threading.Thread(target=warm, daemon=True).start()

    def cleanup_loop():
        clean_gallery()
        clean_old_jobs()
        while True:
            time.sleep(3600)
            clean_gallery()
            clean_old_jobs()

    threading.Thread(target=cleanup_loop, daemon=True).start()
    yield
    manager.shutdown()


app = FastAPI(title="白匣 BAIXIA", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)

MAX_REQUEST_BYTES = MAX_TOTAL_BYTES + 64 * 1024 * 1024


@app.middleware("http")
async def request_size_limit(request, call_next):
    if request.method == "POST" and request.url.path in {"/api/jobs", "/api/pdf-gallery"}:
        length = request.headers.get("content-length")
        if length:
            try:
                size = int(length)
            except ValueError:
                size = 0
            if size > MAX_REQUEST_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"上传内容超过 {human_size(MAX_TOTAL_BYTES)} 的限制"},
                )
    return await call_next(request)


def _capabilities() -> dict:
    heic = avif = False
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        heic = True
    except Exception:
        pass
    try:
        from PIL import features

        avif = bool(features.check("avif"))
    except Exception:
        pass
    return {
        "ffmpeg": ffmpeg_version(),
        "ocr": True,
        "heic": heic,
        "avif": avif,
        "matting": matting.available(),
        "whisper": subtitles.available(),
        "superres": upscale.available(),
        "hw_encoder": hw_encoder_label(),
        "platform": sys.platform,
        "version": VERSION,
        "max_upload": human_size(MAX_TOTAL_BYTES),
    }


@app.get("/api/tools")
def api_tools():
    return {
        "categories": CATEGORIES,
        "tools": public_tools(),
        "capabilities": _capabilities(),
    }


def _coerce_options(tool: dict, raw: dict) -> dict:
    opts: dict = {}
    for spec in tool.get("options", []):
        key = spec["key"]
        value = raw.get(key, spec.get("default"))
        kind = spec.get("type", "text")
        if kind == "checkbox":
            if isinstance(value, str):
                value = value.strip().lower() in {"1", "true", "on", "yes"}
            opts[key] = bool(value)
        elif kind in {"number", "range"}:
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"「{spec['label']}」需要填写数字")
            low = spec.get("min")
            high = spec.get("max")
            if low is not None:
                number = max(float(low), number)
            if high is not None:
                number = min(float(high), number)
            opts[key] = int(number) if number.is_integer() else number
        elif kind == "select":
            if tool.get("id") == "pdf-compress" and key == "level":
                value = {"ebook": "balanced", "screen": "strong", "print": "balanced"}.get(str(value), value)
            allowed = [c[0] for c in spec.get("choices", [])]
            if str(value) not in allowed:
                raise HTTPException(status_code=400, detail=f"「{spec['label']}」的选项无效")
            opts[key] = str(value)
        else:
            opts[key] = "" if value is None else str(value)
    return opts


GALLERY_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _gallery_source(token: str) -> tuple[Path, str]:
    if not GALLERY_TOKEN.fullmatch(token or ""):
        raise HTTPException(status_code=404, detail="页面预览已过期，请重新选择 PDF")
    folder = GALLERY_DIR / token
    source = folder / "source.pdf"
    if not source.exists():
        raise HTTPException(status_code=404, detail="页面预览已过期，请重新选择 PDF")
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        name = safe_filename(str(meta.get("source_name") or "document.pdf"))
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
    except Exception:
        name = "document.pdf"
    return source, name


@app.post("/api/jobs")
async def create_job(
    tool: str = Form(...),
    options: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
    gallery_token: str = Form(""),
    gallery_ops: str = Form(""),
):
    meta = TOOL_MAP.get(tool)
    if not meta:
        raise HTTPException(status_code=400, detail="未知的工具")
    if tool not in HANDLERS:
        raise HTTPException(status_code=500, detail="这个工具暂时不可用")
    token = (gallery_token or "").strip()
    gallery = bool(token)
    if gallery:
        if tool != "pdf-pages":
            raise HTTPException(status_code=400, detail="页面预览只能用于 PDF 页面管理")
        if files:
            raise HTTPException(status_code=400, detail="页面管理无需重复上传 PDF")
        source, source_name = _gallery_source(token)
    else:
        source = None
        source_name = ""
        if not files:
            raise HTTPException(status_code=400, detail="请先选择文件")
        if len(files) > MAX_FILES:
            raise HTTPException(status_code=400, detail=f"一次最多处理 {MAX_FILES} 个文件")
        if not meta.get("multi") and len(files) > 1:
            raise HTTPException(status_code=400, detail="这个工具一次只能处理 1 个文件")
        accepted = {ext.lower() for ext in meta.get("accept", [])}
        for upload in files:
            ext = Path(upload.filename or "").suffix.lower()
            if ext not in accepted:
                raise HTTPException(
                    status_code=400,
                    detail=f"「{upload.filename}」格式不支持，需要 {' / '.join(sorted(accepted))}",
                )
    try:
        raw_opts = json.loads(options or "{}")
        if not isinstance(raw_opts, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="参数格式不正确")
    opts = _coerce_options(meta, raw_opts)
    if gallery:
        try:
            page_ops = json.loads(gallery_ops or "{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="页面顺序数据无效")
        if not isinstance(page_ops, dict) or not isinstance(page_ops.get("pages"), list):
            raise HTTPException(status_code=400, detail="页面顺序数据无效")
        if not page_ops["pages"]:
            raise HTTPException(status_code=400, detail="请至少保留一页")
        if len(page_ops["pages"]) > 1200:
            raise HTTPException(status_code=400, detail="页面数量过多")
        opts["page_ops"] = page_ops

    manager = get_manager()
    job = manager.new_job(tool, meta["name"], opts)
    inputs: list[Path] = []
    total = 0
    try:
        if gallery:
            dest = unique_path(job.dir / "in", source_name)
            shutil.copy2(source, dest)
            inputs.append(dest)
        else:
            for idx, upload in enumerate(files):
                name = safe_filename(upload.filename or f"input-{idx + 1}")
                dest = unique_path(job.dir / "in", name)
                size = 0
                with dest.open("wb") as fh:
                    while True:
                        chunk = await upload.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        total += len(chunk)
                        if total > MAX_TOTAL_BYTES:
                            raise HTTPException(
                                status_code=413,
                                detail=f"文件总大小超过 {human_size(MAX_TOTAL_BYTES)}",
                            )
                        fh.write(chunk)
                if size == 0:
                    raise HTTPException(status_code=400, detail=f"「{name}」是空文件")
                inputs.append(dest)
    except Exception:
        manager.abort(job)
        raise
    finally:
        for upload in files:
            try:
                await upload.close()
            except Exception:
                pass

    job.inputs = inputs
    job.status = "queued"
    job.message = "排队中"
    manager.submit(job, HANDLERS[tool])
    return {"job": job.public(), "options": opts}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = get_manager().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job.public()


def _job_file(job, kind: str, filename: str) -> Path:
    name = safe_filename(filename)
    if kind == "input":
        base = job.dir / "in"
        allowed = any(p.name == name for p in job.inputs)
    else:
        base = job.outdir
        allowed = any(p.name == name for p in job.outputs)
    if not allowed:
        raise HTTPException(status_code=404, detail="文件不存在")
    target = (base / name).resolve()
    try:
        base_resolved = base.resolve()
        if base_resolved not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="文件名无效")
    return target


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    if not get_manager().get(job_id):
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    async def stream():
        last = None
        while True:
            job = get_manager().get(job_id)
            if not job:
                yield "event: gone\ndata: {}\n\n"
                break
            data = job.public()
            fingerprint = json.dumps(data, ensure_ascii=False, sort_keys=True)
            if fingerprint != last:
                last = fingerprint
                yield f"data: {fingerprint}\n\n"
            if data["status"] in {"done", "error", "cancelled"}:
                break
            await asyncio.sleep(0.15)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{job_id}/preview/{filename}")
def preview_output(job_id: str, filename: str):
    job = get_manager().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    source = _job_file(job, "output", filename)
    preview = generate_preview(source, job.dir / "previews", "out")
    if not preview:
        raise HTTPException(status_code=415, detail="这个文件暂不支持预览")
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(preview.name)}",
        "Cache-Control": "private, max-age=3600",
    }
    return FileResponse(str(preview), media_type="image/png", headers=headers)


@app.get("/api/jobs/{job_id}/input-preview/{filename}")
def preview_input(job_id: str, filename: str):
    job = get_manager().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    source = _job_file(job, "input", filename)
    preview = generate_preview(source, job.dir / "previews", "in")
    if not preview:
        raise HTTPException(status_code=415, detail="这个文件暂不支持预览")
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(preview.name)}",
        "Cache-Control": "private, max-age=3600",
    }
    return FileResponse(str(preview), media_type="image/png", headers=headers)


def _stage_inputs(sources: list[Path], target_job) -> list[Path]:
    staged = []
    for source in sources:
        source = Path(source)
        if not source.exists() or not source.is_file():
            continue
        dest = unique_path(target_job.dir / "in", source.name)
        try:
            os.link(source, dest)
        except Exception:
            shutil.copy2(source, dest)
        staged.append(dest)
    target_job.inputs = staged
    return staged


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    try:
        job = get_manager().cancel(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job.public()


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    old = get_manager().get(job_id)
    if not old:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if old.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="任务还在进行中")
    meta = TOOL_MAP.get(old.tool)
    handler = HANDLERS.get(old.tool)
    if not meta or not handler:
        raise HTTPException(status_code=400, detail="原工具已不可用")
    sources = [p for p in old.inputs if p.exists()]
    if not sources:
        raise HTTPException(status_code=400, detail="原文件已被清理，请重新选择文件")
    opts = _coerce_options(meta, old.opts or {})
    if old.tool == "pdf-pages" and isinstance((old.opts or {}).get("page_ops"), dict):
        opts["page_ops"] = old.opts["page_ops"]
    manager = get_manager()
    new = manager.new_job(old.tool, old.tool_name, opts)
    _stage_inputs(sources, new)
    manager.submit(new, handler)
    return {"job": new.public()}


@app.post("/api/jobs/{job_id}/reuse")
def reuse_job(job_id: str, payload: dict = Body(...)):
    old = get_manager().get(job_id)
    if not old:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    tool_id = str(payload.get("tool", ""))
    meta = TOOL_MAP.get(tool_id)
    handler = HANDLERS.get(tool_id)
    if not meta or not handler:
        raise HTTPException(status_code=400, detail="目标工具不可用")
    sources = [p for p in old.outputs if p.exists() and p.is_file()]
    plain = [p for p in sources if p.suffix.lower() != ".zip"]
    if plain:
        sources = plain
    accepted = {ext.lower() for ext in meta.get("accept", [])}
    compatible = [p for p in sources if p.suffix.lower() in accepted]
    if not compatible:
        raise HTTPException(status_code=400, detail="输出格式与目标工具不兼容")
    if not meta.get("multi") and len(compatible) > 1:
        raise HTTPException(status_code=400, detail="目标工具一次只能处理一个文件")
    opts = _coerce_options(meta, payload.get("options") or {})
    manager = get_manager()
    new = manager.new_job(tool_id, meta["name"], opts)
    _stage_inputs(compatible, new)
    manager.submit(new, handler)
    return {"job": new.public()}


@app.get("/api/jobs/{job_id}/download/{filename}")
def download(job_id: str, filename: str):
    job = get_manager().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    target = job.outdir / safe_filename(filename)
    try:
        resolved = target.resolve()
        outdir = job.outdir.resolve()
        if outdir not in resolved.parents or not resolved.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        if not any(p.name == resolved.name for p in job.outputs):
            raise HTTPException(status_code=404, detail="文件不存在")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="文件名无效")
    return FileResponse(str(resolved), filename=resolved.name, media_type="application/octet-stream")


@app.get("/api/jobs/{job_id}/zip")
def download_zip(job_id: str):
    job = get_manager().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    zip_path = get_manager().zip_outputs(job)
    if not zip_path:
        raise HTTPException(status_code=404, detail="没有可打包的文件")
    return FileResponse(str(zip_path), filename=zip_path.name, media_type="application/zip")


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    try:
        ok = get_manager().delete(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


MAX_GALLERY_PAGES = 300


def _build_gallery(folder: Path, token: str, source_name: str) -> dict:
    import pymupdf

    source = folder / "source.pdf"
    doc = pymupdf.open(str(source))
    try:
        if doc.needs_pass:
            raise RuntimeError("这个 PDF 有打开密码，请先解密")
        count = doc.page_count
        if count < 1:
            raise RuntimeError("PDF 没有页面")
        if count > MAX_GALLERY_PAGES:
            raise RuntimeError(f"页面过多（{count} 页），最多支持 {MAX_GALLERY_PAGES} 页")
        pages = []
        for index in range(count):
            page = doc[index]
            rect = page.rect
            zoom = min(1.0, 160 / max(1.0, rect.width))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            thumb = folder / f"page-{index:04d}.jpg"
            pix.save(str(thumb), jpg_quality=82)
            pages.append({
                "index": index,
                "url": f"/api/pdf-gallery/{token}/thumb/{index}",
                "width": round(rect.width),
                "height": round(rect.height),
            })
        (folder / "meta.json").write_text(
            json.dumps({"source_name": source_name, "page_count": count}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"token": token, "page_count": count, "pages": pages}
    finally:
        doc.close()


@app.post("/api/pdf-gallery")
async def pdf_gallery_upload(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="请选择 PDF 文件")
    token = secrets.token_hex(16)
    folder = GALLERY_DIR / token
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "source.pdf"
    total = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_TOTAL_BYTES:
                    raise HTTPException(status_code=413, detail=f"文件超过 {human_size(MAX_TOTAL_BYTES)}")
                fh.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="PDF 文件为空")
        source_name = safe_filename(file.filename or "document.pdf")
        if not source_name.lower().endswith(".pdf"):
            source_name += ".pdf"
        data = await asyncio.to_thread(_build_gallery, folder, token, source_name)
        return data
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"无法读取 PDF：{exc}") from exc
    finally:
        try:
            await file.close()
        except Exception:
            pass


@app.get("/api/pdf-gallery/{token}/thumb/{index}")
def pdf_gallery_thumb(token: str, index: int):
    if not GALLERY_TOKEN.fullmatch(token or ""):
        raise HTTPException(status_code=404, detail="页面预览不存在")
    thumb = GALLERY_DIR / token / f"page-{int(index):04d}.jpg"
    if int(index) < 0 or not thumb.is_file():
        raise HTTPException(status_code=404, detail="页面预览不存在")
    return FileResponse(str(thumb), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


def _lan_addresses() -> list[str]:
    names = ("wlan", "wi-fi", "wifi", "wireless", "无线", "ethernet", "以太网", "本地连接")
    virtual = ("vethernet", "virtualbox", "vmware", "hyper-v", "loopback", "flclash", "tailscale", "zerotier", "docker", "tap")
    candidates: list[tuple[int, str]] = []
    try:
        import psutil

        stats = psutil.net_if_stats()
        for name, entries in psutil.net_if_addrs().items():
            lowered = name.lower()
            if any(token in lowered for token in virtual):
                continue
            if name in stats and not stats[name].isup:
                continue
            for entry in entries:
                if entry.family != socket.AF_INET:
                    continue
                ip = entry.address
                if not ip or ip.startswith(("127.", "169.254.", "0.")):
                    continue
                try:
                    import ipaddress

                    if ipaddress.ip_address(ip) in ipaddress.ip_network("198.18.0.0/15"):
                        continue
                except Exception:
                    pass
                priority = 2 if any(token in lowered for token in names[:5]) else (1 if any(token in lowered for token in names[5:]) else 0)
                candidates.append((priority, ip))
    except Exception:
        pass
    if not candidates:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 80))
            candidates.append((0, probe.getsockname()[0]))
            probe.close()
        except Exception:
            pass
    if not candidates:
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                candidates.append((0, item[4][0]))
        except Exception:
            pass
    result = []
    for _, ip in sorted(candidates, key=lambda item: -item[0]):
        if ip not in result:
            result.append(ip)
    return result


def _network_payload(request: Request) -> dict:
    host = os.environ.get("BAIXIA_HOST", "127.0.0.1")
    enabled = host in {"0.0.0.0", "::"}
    port = request.url.port or 8765
    local_url = f"http://127.0.0.1:{port}"
    urls = [f"http://{ip}:{port}" for ip in _lan_addresses()] if enabled else []
    return {
        "lan_enabled": enabled,
        "port": port,
        "local_url": local_url,
        "urls": urls,
        "url": urls[0] if urls else "",
        "qr_available": importlib.util.find_spec("qrcode") is not None,
    }


@app.get("/api/network")
def network_info(request: Request):
    return _network_payload(request)


@app.get("/api/network/qr")
def network_qr(request: Request):
    info = _network_payload(request)
    if not info["lan_enabled"]:
        raise HTTPException(status_code=409, detail="当前是本机模式，请用局域网启动脚本启动")
    if not info["url"]:
        raise HTTPException(status_code=409, detail="没有检测到局域网 IP")
    try:
        import qrcode
    except Exception as exc:
        raise HTTPException(status_code=503, detail="未安装二维码组件") from exc
    image = qrcode.make(info["url"])
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "ffmpeg": bool(find_ffmpeg()), "version": VERSION}


@app.exception_handler(Exception)
async def unhandled_exception(request, exc):
    return JSONResponse(status_code=500, content={"detail": f"服务内部错误：{exc}"})


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def _pick_port(start: int = 8765) -> int:
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    host = os.environ.get("BAIXIA_HOST", "127.0.0.1")
    port = int(os.environ.get("BAIXIA_PORT", "0") or 0) or _pick_port()
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    browser_url = f"http://{browser_host}:{port}"
    print("")
    print(f"  白匣 BAIXIA  ·  {browser_url}")
    print("  文件只在本机处理，按 Ctrl+C 停止。")
    print("")
    pid_path = BASE_DIR / ".baixia.pid"
    try:
        pid_path.write_text(str(os.getpid()), encoding="ascii")
    except Exception:
        pass
    if os.environ.get("BAIXIA_NO_BROWSER", "0") != "1":
        def open_browser():
            for _ in range(80):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        webbrowser.open(browser_url)
                        return
                time.sleep(0.2)
        threading.Thread(target=open_browser, daemon=True).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)
    finally:
        try:
            if pid_path.exists() and pid_path.read_text(encoding="ascii").strip() == str(os.getpid()):
                pid_path.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
