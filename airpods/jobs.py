import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .logfetch import stream_samples, validate_address


class JobBusyError(RuntimeError):
    """Raised when a second fetch is requested while one is running."""


@dataclass
class Job:
    id: str
    address: str
    start: datetime
    end: datetime
    status: str = "queued"
    stage: str = "排队中"
    lines: int = 0
    samples: int = 0
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        end_time = self.finished_at or time.time()
        elapsed = (end_time - self.started_at) if self.started_at else 0.0
        return {
            "id": self.id,
            "address": self.address,
            "start": self.start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": self.end.strftime("%Y-%m-%d %H:%M:%S"),
            "status": self.status,
            "stage": self.stage,
            "lines": self.lines,
            "samples": self.samples,
            "error": self.error,
            "elapsed_seconds": round(elapsed, 1),
        }

    def wait(self, timeout: Optional[float] = None) -> None:
        if self.thread is not None:
            self.thread.join(timeout)


class JobManager:
    def __init__(self, cache, fetcher=None):
        self.cache = cache
        self.fetcher = fetcher or stream_samples
        self._jobs: dict[str, Job] = {}
        self._active: Optional[Job] = None
        self._lock = threading.Lock()

    def start_fetch(self, address: str, start: datetime, end: datetime) -> Job:
        address = validate_address(address)
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间")

        with self._lock:
            if self._active is not None and self._active.status in ("queued", "running"):
                raise JobBusyError("已有抓取任务正在进行，请等待完成或先取消")

            job = Job(
                id=uuid.uuid4().hex,
                address=address,
                start=start,
                end=end,
            )
            missing = self.cache.missing_ranges(
                address, start, end, tolerance_seconds=60
            )
            self._jobs[job.id] = job

            if not missing:
                job.status = "done"
                job.stage = "已使用本地缓存"
                job.finished_at = time.time()
                return job

            self._active = job
            job.thread = threading.Thread(
                target=self._run, args=(job, missing), daemon=True
            )
            job.thread.start()
            return job

    def _run(self, job: Job, missing) -> None:
        job.status = "running"
        job.started_at = time.time()
        try:
            for range_start, range_end in missing:
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.stage = "已取消"
                    return

                job.stage = (
                    f"正在查询 {range_start:%m-%d %H:%M} → {range_end:%m-%d %H:%M}"
                )
                buffer = []
                last_seen = [None]

                def on_line() -> None:
                    job.lines += 1

                def on_sample(sample) -> None:
                    buffer.append(sample)
                    job.samples += 1
                    last_seen[0] = sample.ts
                    if len(buffer) >= 500:
                        self.cache.insert_samples(buffer)
                        buffer.clear()

                result = self.fetcher(
                    job.address,
                    range_start,
                    range_end,
                    on_sample=on_sample,
                    on_line=on_line,
                    cancel_event=job.cancel_event,
                )

                self.cache.insert_samples(buffer)
                buffer.clear()

                if result.cancelled or job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.stage = "已取消"
                    return

                self.cache.add_range(job.address, range_start, range_end)
                self.cache.upsert_device(job.address, "", last_seen[0])

            job.status = "done"
            job.stage = "完成"
        except Exception as error:  # noqa: BLE001 - surfaced through the job payload
            job.status = "error"
            job.stage = "失败"
            job.error = str(error)
        finally:
            job.finished_at = time.time()
            with self._lock:
                if self._active is job:
                    self._active = None

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in ("queued", "running"):
                return False
            job.cancel_event.set()
            return True

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
        for job in jobs:
            job.wait(1)
