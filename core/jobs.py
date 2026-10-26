from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .utils import (
    JOBS_DIR,
    clean_old_jobs,
    ensure_dirs,
    make_zip,
    safe_filename,
)


class TaskCancelled(Exception):
    """Raised when a running job has been asked to stop."""


HEAVY_TOOLS = {
    "pdf-ocr",
    "docx-to-pdf",
    "pdf-watermark",
    "image-upscale",
    "subtitles",
    "video-convert",
    "video-compress",
    "video-trim",
    "video-crop",
    "video-concat",
    "video-to-gif",
    "video-audio",
    "video-frames",
    "video-mute",
    "gif-to-video",
}


@dataclass
class Job:
    id: str
    tool: str
    tool_name: str
    opts: dict
    inputs: list[Path]
    dir: Path
    status: str = "queued"
    progress: int = 0
    message: str = "排队中"
    error: str = ""
    note: str = ""
    outputs: list[Path] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    finished: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def outdir(self) -> Path:
        return self.dir / "out"

    def report(self, pct: int, message: str = "") -> None:
        if self.cancel_event.is_set():
            raise TaskCancelled("任务已取消")
        with self._lock:
            self.progress = max(self.progress, max(0, min(100, int(pct))))
            if message:
                self.message = message
            self.status = "running"

    def add_output(self, path: Path) -> Path:
        path = Path(path)
        if not path.exists():
            raise RuntimeError(f"输出文件不存在：{path.name}")
        with self._lock:
            if path not in self.outputs:
                self.outputs.append(path)
        return path

    def public(self) -> dict:
        with self._lock:
            output_files = [p for p in self.outputs if p.exists()]
            plain_outputs = [p for p in output_files if p.suffix.lower() != ".zip"]
            compared = plain_outputs or output_files
            input_files = [p for p in self.inputs if p.exists()]
            input_size = sum(p.stat().st_size for p in input_files)
            output_size = sum(p.stat().st_size for p in compared)
            saved = input_size - output_size if input_size else 0
            saved_pct = round(saved / input_size * 100, 1) if input_size else 0
            outputs = [
                {
                    "name": p.name,
                    "size": p.stat().st_size,
                    "url": f"/api/jobs/{self.id}/download/{p.name}",
                    "preview": f"/api/jobs/{self.id}/preview/{p.name}",
                }
                for p in output_files
            ]
            inputs = [
                {
                    "name": p.name,
                    "size": p.stat().st_size,
                    "preview": f"/api/jobs/{self.id}/input-preview/{p.name}",
                }
                for p in input_files
            ]
            return {
                "id": self.id,
                "tool": self.tool,
                "tool_name": self.tool_name,
                "status": self.status,
                "progress": self.progress,
                "message": self.message,
                "error": self.error,
                "note": self.note,
                "outputs": outputs,
                "inputs": inputs,
                "input_size": input_size,
                "output_size": output_size,
                "saved": saved,
                "saved_percent": saved_pct,
                "created": self.created,
                "finished": self.finished,
                "elapsed": round((self.finished or time.time()) - self.created, 1),
            }

    def save_meta(self) -> None:
        data = self.public()
        data["output_names"] = [p.name for p in self.outputs]
        data["input_names"] = [p.name for p in self.inputs if p.exists()]
        try:
            (self.dir / "meta.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


class JobManager:
    def __init__(self) -> None:
        ensure_dirs()
        clean_old_jobs()
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        cores = os.cpu_count() or 4
        light_workers = max(2, min(6, int(os.environ.get("BAIXIA_LIGHT_WORKERS", cores))))
        heavy_workers = max(1, min(2, int(os.environ.get("BAIXIA_HEAVY_WORKERS", 1))))
        self._light = ThreadPoolExecutor(max_workers=light_workers, thread_name_prefix="baixia-light")
        self._heavy = ThreadPoolExecutor(max_workers=heavy_workers, thread_name_prefix="baixia-heavy")
        self._restore()

    def _restore(self) -> None:
        try:
            for meta in sorted(JOBS_DIR.glob("*/meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]:
                data = json.loads(meta.read_text(encoding="utf-8"))
                if data.get("status") not in {"done", "error", "cancelled"}:
                    continue
                job = Job(
                    id=data["id"], tool=data.get("tool", ""), tool_name=data.get("tool_name", ""),
                    opts={}, inputs=[], dir=meta.parent,
                    status=data.get("status", "done"), progress=100,
                    message=data.get("message", ""), error=data.get("error", ""),
                    note=data.get("note", ""),
                    created=data.get("created", meta.stat().st_mtime),
                    finished=data.get("finished"),
                )
                outdir = meta.parent / "out"
                for name in data.get("output_names", []):
                    p = outdir / name
                    if p.exists():
                        job.outputs.append(p)
                indir = meta.parent / "in"
                input_names = data.get("input_names")
                if input_names is None:
                    input_names = [p.name for p in indir.iterdir()] if indir.exists() else []
                for name in input_names:
                    p = indir / name
                    if p.exists() and p.is_file():
                        job.inputs.append(p)
                self.jobs[job.id] = job
        except Exception:
            pass

    def new_job(self, tool: str, tool_name: str, opts: dict, job_id: str | None = None) -> Job:
        job_id = job_id or (time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6])
        job_dir = JOBS_DIR / job_id
        (job_dir / "in").mkdir(parents=True, exist_ok=True)
        (job_dir / "out").mkdir(parents=True, exist_ok=True)
        job = Job(id=job_id, tool=tool, tool_name=tool_name, opts=opts, inputs=[], dir=job_dir)
        with self._lock:
            self.jobs[job.id] = job
        return job

    def submit(self, job: Job, handler) -> None:
        pool = self._heavy if job.tool in HEAVY_TOOLS else self._light
        pool.submit(self._run, job, handler)

    def _run(self, job: Job, handler) -> None:
        try:
            job.status = "running"
            job.report(1, "开始处理")
            result = handler(job, job.inputs, job.opts) or []
            if job.cancel_event.is_set():
                raise TaskCancelled("任务已取消")
            for p in result:
                job.add_output(Path(p))
            if job.cancel_event.is_set():
                raise TaskCancelled("任务已取消")
            if not job.outputs:
                raise RuntimeError("没有生成任何文件")
            with job._lock:
                job.status = "done"
                job.progress = 100
                job.message = f"完成 · {len(job.outputs)} 个文件"
                job.finished = time.time()
        except TaskCancelled:
            self._mark_cancelled(job)
        except Exception as exc:
            with job._lock:
                job.status = "error"
                job.error = str(exc) or exc.__class__.__name__
                job.message = "处理失败"
                job.finished = time.time()
            traceback.print_exc()
        finally:
            job.save_meta()

    def _mark_cancelled(self, job: Job) -> None:
        with job._lock:
            job.status = "cancelled"
            job.message = "已取消"
            job.error = ""
            job.finished = time.time()
            outputs = list(job.outputs)
            job.outputs.clear()
        for path in outputs:
            try:
                path.unlink()
            except Exception:
                pass
        import shutil

        shutil.rmtree(job.outdir, ignore_errors=True)
        job.outdir.mkdir(parents=True, exist_ok=True)

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status not in {"queued", "running"}:
            raise RuntimeError("任务已经结束，无法取消")
        job.cancel_event.set()
        with job._lock:
            job.message = "正在取消"
        return job

    def abort(self, job: Job) -> None:
        """Forget a job that never started and remove its files."""
        with self._lock:
            self.jobs.pop(job.id, None)
        import shutil

        shutil.rmtree(job.dir, ignore_errors=True)

    def delete(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.status in {"queued", "running"}:
            raise RuntimeError("任务还在进行中，无法清除")
        with self._lock:
            self.jobs.pop(job_id, None)
        try:
            import shutil

            shutil.rmtree(job.dir, ignore_errors=True)
        except Exception:
            pass
        return True

    def zip_outputs(self, job: Job) -> Path | None:
        files = [p for p in job.outputs if p.exists() and p.is_file()]
        plain = [p for p in files if p.suffix.lower() != ".zip"]
        if plain:
            files = plain
        if not files:
            return None
        target = job.dir / f"{safe_filename(job.tool or 'output')}-{job.id[-4:]}.zip"
        if target.exists():
            target.unlink()
        return make_zip(files, target)

    def shutdown(self) -> None:
        self._light.shutdown(wait=False, cancel_futures=True)
        self._heavy.shutdown(wait=False, cancel_futures=True)


manager: JobManager | None = None


def get_manager() -> JobManager:
    global manager
    if manager is None:
        manager = JobManager()
    return manager
