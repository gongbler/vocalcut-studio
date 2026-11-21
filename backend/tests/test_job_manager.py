"""작업 대기열 테스트."""
import threading
import time

import pytest

from app.jobs.manager import JobManager, UserFacingError
from app.jobs.models import JobStatus


def wait_finished(jobs: JobManager, job_id: str, timeout: float = 10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = jobs.get(job_id)
        if job.status.finished:
            return job
        time.sleep(0.02)
    raise TimeoutError(job_id)


@pytest.fixture
def jobs(tmp_path):
    m = JobManager(tmp_path / "jobs")
    yield m
    m.shutdown()


def test_submit_returns_immediately_then_completes(jobs):
    gate = threading.Event()

    def work(report):
        gate.wait(5)           # 신호를 줄 때까지 일부러 멈춰 있는 작업
        return {"answer": 42}

    started = time.monotonic()
    job = jobs.submit("test", work)
    assert time.monotonic() - started < 0.5   # 번호표는 바로 나온다
    assert job.status in (JobStatus.QUEUED, JobStatus.RUNNING)

    gate.set()
    done = wait_finished(jobs, job.id)
    assert done.status == JobStatus.DONE
    assert done.result == {"answer": 42}
    assert done.progress == 1.0


def test_progress_is_visible_while_running(jobs):
    halfway, finish = threading.Event(), threading.Event()

    def work(report):
        report(0.5, "절반")
        halfway.set()
        finish.wait(5)
        return {}

    job = jobs.submit("test", work)
    halfway.wait(5)
    running = jobs.get(job.id)
    assert running.status == JobStatus.RUNNING
    assert running.progress == 0.5
    assert running.message == "절반"
    finish.set()
    wait_finished(jobs, job.id)


def test_single_worker_runs_jobs_one_at_a_time(jobs):
    """작업자 1명 → 두 번째 작업은 첫 번째가 끝날 때까지 '대기 중'이어야 한다."""
    release = threading.Event()
    first = jobs.submit("test", lambda r: (release.wait(5), {})[1])
    second = jobs.submit("test", lambda r: {})

    time.sleep(0.2)
    assert jobs.get(first.id).status == JobStatus.RUNNING
    assert jobs.get(second.id).status == JobStatus.QUEUED

    release.set()
    assert wait_finished(jobs, second.id).status == JobStatus.DONE


def test_unexpected_error_hides_details(jobs):
    def work(report):
        raise RuntimeError("C:\\secret\\path exploded")

    job = wait_finished(jobs, jobs.submit("test", work).id)
    assert job.status == JobStatus.ERROR
    assert "secret" not in job.error   # 내부 정보는 화면에 노출하지 않는다


def test_user_facing_error_message_is_kept(jobs):
    def work(report):
        raise UserFacingError("메모리가 부족합니다")

    job = wait_finished(jobs, jobs.submit("test", work).id)
    assert job.error == "메모리가 부족합니다"


def test_restart_marks_unfinished_jobs_as_interrupted(tmp_path):
    store = tmp_path / "jobs"
    first = JobManager(store)
    block = threading.Event()
    running = first.submit("test", lambda r: (block.wait(5), {})[1])
    done = first.submit("test", lambda r: {"ok": True})  # 첫 작업 뒤에서 대기 중
    time.sleep(0.1)

    # 서버가 '갑자기 꺼졌다'고 가정하고, 같은 폴더로 새 관리자를 만든다
    second = JobManager(store)
    try:
        assert second.get(running.id).status == JobStatus.ERROR
        assert "재시작" in second.get(running.id).error
        assert second.get(done.id).status == JobStatus.ERROR  # 대기 중이던 것도 중단 처리
    finally:
        block.set()
        first.shutdown()
        second.shutdown()
