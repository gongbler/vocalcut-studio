"""작업 대기열 관리자 = '주문 접수대 + 주방 작업자'.

- submit(): 주문을 받으면 번호표(Job)를 '바로' 돌려주고, 실제 일은 뒤에서 작업자 스레드가 한다.
- get(): 번호표로 현재 상태를 조회한다 (화면이 1초마다 물어본다 = 폴링).
- 작업자 수는 기본 1명 → 무거운 작업(보컬 분리 등)이 동시에 돌아 메모리가 터지는 것을 막는다.
- 상태가 바뀔 때마다 jobs/<id>.json 으로 저장 → 서버가 재시작돼도 기록이 남는다.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.jobs.models import Job, JobStatus

logger = logging.getLogger(__name__)

# 작업 함수가 진행 상황을 알릴 때 쓰는 콜백: report(0.37, "인코딩 중")
ProgressReporter = Callable[[float, str | None], None]
JobFunc = Callable[[ProgressReporter], dict[str, Any]]


class UserFacingError(Exception):
    """메시지를 그대로 사용자에게 보여줘도 되는 에러."""


class JobManager:
    def __init__(self, store_dir: Path, max_workers: int = 1) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()  # 여러 스레드가 동시에 _jobs 를 고치지 못하게 잠금
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._load_saved_jobs()

    # ---------------- 공개 기능 ----------------
    def submit(self, kind: str, func: JobFunc, extra: dict[str, Any] | None = None) -> Job:
        now = time.time()
        job = Job(id=uuid.uuid4().hex, kind=kind, created_at=now, updated_at=now,
                  message="대기 중", extra=extra or {})
        with self._lock:
            self._jobs[job.id] = job
        self._save(job)
        self._executor.submit(self._run, job.id, func)
        return self.get(job.id)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            # 복사본을 돌려준다 → 바깥에서 고쳐도 원본이 망가지지 않음
            return Job.from_dict(job.to_dict()) if job else None

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    # ---------------- 내부 동작 ----------------
    def _run(self, job_id: str, func: JobFunc) -> None:
        self._update(job_id, status=JobStatus.RUNNING, message="처리 중", progress=0.0)

        def report(progress: float, message: str | None = None) -> None:
            fields: dict[str, Any] = {"progress": min(max(progress, 0.0), 1.0)}
            if message:
                fields["message"] = message
            self._update(job_id, persist=False, **fields)  # 진행률은 너무 자주 바뀌어 파일 저장 생략

        try:
            result = func(report)
        except UserFacingError as e:
            self._update(job_id, status=JobStatus.ERROR, error=str(e), message=None)
        except Exception:
            logger.exception("job %s failed", job_id)  # 자세한 원인은 서버 로그에
            self._update(job_id, status=JobStatus.ERROR, message=None,
                         error="작업 중 오류가 발생했습니다. 서버 로그를 확인하세요.")
        else:
            self._update(job_id, status=JobStatus.DONE, progress=1.0, message="완료", result=result)

    def _update(self, job_id: str, persist: bool = True, **fields: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = time.time()
            snapshot = job.to_dict()
        if persist:
            self._write(job_id, snapshot)

    def _save(self, job: Job) -> None:
        self._write(job.id, job.to_dict())

    def _write(self, job_id: str, data: dict[str, Any]) -> None:
        path = self.store_dir / f"{job_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)  # 다 쓴 뒤 한 번에 교체 → 쓰다 만 파일이 남지 않음

    def _load_saved_jobs(self) -> None:
        """서버 시작 시 이전 기록을 불러온다. 끝나지 못한 작업은 '중단됨'으로 표시."""
        for path in self.store_dir.glob("*.json"):
            try:
                job = Job.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("broken job file skipped: %s", path.name)
                continue
            if not job.status.finished:
                job.status = JobStatus.ERROR
                job.message = None
                job.error = "서버가 재시작되어 작업이 중단되었습니다. 다시 시도하세요."
                self._write(job.id, job.to_dict())
            self._jobs[job.id] = job
