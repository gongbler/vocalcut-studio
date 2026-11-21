"""보컬 분리 API 테스트 — 진짜 AI 대신 '가짜 분리 엔진'을 끼워서 흐름만 검사한다."""
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_job_manager, get_separator, get_workspace
from app.jobs.manager import JobManager
from app.main import app
from app.services.engines.base import Availability, SeparatorEngine, StemPaths
from app.storage.workspace import Workspace
from tests.conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


class FakeSeparator(SeparatorEngine):
    """원본 파일을 그대로 복사해서 '보컬', '반주'라고 돌려주는 가짜 엔진."""
    name = "fake"

    def __init__(self):
        self.calls = 0
        self.available = True
        self.release = threading.Event()
        self.release.set()            # 기본은 바로 끝남. clear() 하면 멈춰서 기다림

    def availability(self):
        return Availability(self.available, "" if self.available else "AI 패키지가 없습니다")

    def separate(self, src, out_dir, on_progress=None, on_stage=None):
        self.calls += 1
        if on_stage:
            on_stage("보컬/MR 분리 중")
        while not self.release.wait(0.05):   # 멈춰 있는 동안에도 진행률을 보고 → 취소 신호를 받을 수 있음
            if on_progress:
                on_progress(0.5)
        v, i = Path(out_dir) / "vocals.wav", Path(out_dir) / "instrumental.wav"
        shutil.copy(src, v)
        shutil.copy(src, i)
        if on_progress:
            on_progress(1.0)
        return StemPaths(vocals=v, instrumental=i)


@pytest.fixture
def fake():
    return FakeSeparator()


@pytest.fixture
def client(tmp_path: Path, fake):
    ws = Workspace(tmp_path / "workspace")
    ws.ensure()
    jobs = JobManager(ws.jobs)
    app.dependency_overrides[get_workspace] = lambda: ws
    app.dependency_overrides[get_job_manager] = lambda: jobs
    app.dependency_overrides[get_separator] = lambda: fake
    with TestClient(app) as c:
        c.ws = ws
        yield c
    fake.release.set()
    app.dependency_overrides.clear()
    jobs.shutdown()


def wait_job(client, job_id, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise TimeoutError(job_id)


@pytest.fixture
def song_id(client, sine_wav):
    with open(sine_wav, "rb") as f:
        return client.post("/api/files", files={"file": ("내 커버곡.wav", f)}).json()["id"]


def test_separation_registers_two_stem_files(client, song_id):
    res = client.post("/api/separations", json={"source_id": song_id})
    assert res.status_code == 202
    job = wait_job(client, res.json()["id"])
    assert job["status"] == "done", job

    vocals = client.get(f"/api/files/{job['result']['vocals']}").json()
    inst = client.get(f"/api/files/{job['result']['instrumental']}").json()
    assert vocals["original_name"] == "내 커버곡 (보컬).wav"
    assert inst["original_name"] == "내 커버곡 (MR).wav"
    assert vocals["stem"] == "vocals" and vocals["derived_from"] == song_id
    # 등록된 결과는 일반 파일처럼 파형·다운로드 기능을 그대로 쓸 수 있다
    assert client.get(f"/api/files/{vocals['id']}/peaks").status_code == 200
    assert client.get(vocals["download_url"]).headers["content-disposition"].startswith("attachment")
    assert list(client.ws.temp.iterdir()) == []           # 임시 폴더는 깨끗이 정리됨


def test_second_request_reuses_previous_result(client, song_id, fake):
    first = wait_job(client, client.post("/api/separations", json={"source_id": song_id}).json()["id"])
    second = wait_job(client, client.post("/api/separations", json={"source_id": song_id}).json()["id"])
    assert second["result"] == first["result"]
    assert fake.calls == 1                                 # 10분짜리 AI 작업을 두 번 하지 않음


def test_cannot_separate_a_stem_again(client, song_id):
    job = wait_job(client, client.post("/api/separations", json={"source_id": song_id}).json()["id"])
    res = client.post("/api/separations", json={"source_id": job["result"]["vocals"]})
    assert res.status_code == 422


def test_unavailable_separator_is_503(client, song_id, fake):
    fake.available = False
    res = client.post("/api/separations", json={"source_id": song_id})
    assert res.status_code == 503
    assert "AI 패키지" in res.json()["detail"]


def test_unknown_source_is_404(client):
    assert client.post("/api/separations", json={"source_id": "0" * 32}).status_code == 404


def test_cancel_running_separation(client, song_id, fake):
    fake.release.clear()                                   # 분리가 끝나지 않고 계속 '처리 중'
    job_id = client.post("/api/separations", json={"source_id": song_id}).json()["id"]
    time.sleep(0.3)
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "running"

    client.post(f"/api/jobs/{job_id}/cancel")
    job = wait_job(client, job_id)
    assert job["status"] == "cancelled"
    assert list(client.ws.temp.iterdir()) == []            # 취소돼도 임시 파일 정리


def test_cancel_queued_job_never_runs(client, song_id, fake):
    fake.release.clear()
    first = client.post("/api/separations", json={"source_id": song_id}).json()["id"]
    # 첫 작업이 작업자를 차지한 동안 두 번째 작업은 대기 중
    edit = client.post("/api/edits", json={"source_id": song_id}).json()["id"]
    assert client.post(f"/api/jobs/{edit}/cancel").json()["status"] == "cancelled"

    fake.release.set()
    wait_job(client, first)
    time.sleep(0.2)
    assert client.get(f"/api/jobs/{edit}").json()["status"] == "cancelled"  # 차례가 와도 실행 안 함
    assert list(client.ws.outputs.iterdir()) == []


def test_health_reports_separator(client):
    sep = client.get("/api/health").json()["separator"]
    assert sep == {"engine": "fake", "available": True, "reason": None}
