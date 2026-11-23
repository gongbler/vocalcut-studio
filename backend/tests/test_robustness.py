"""실패 상황 테스트: 예상 못 한 오류 · 디스크 공간 부족 · 작업 안의 오류."""
import logging
import shutil
import time
from collections import namedtuple
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_engine, get_job_manager, get_workspace
from app.jobs.manager import JobManager
from app.main import app
from app.services import disk_guard
from app.storage.workspace import Workspace
from tests.conftest import requires_ffmpeg

Usage = namedtuple("Usage", "total used free")
GB = 1024**3


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    w = Workspace(tmp_path / "workspace")
    w.ensure()
    return w


@pytest.fixture
def client(ws):
    jobs = JobManager(ws.jobs)
    app.dependency_overrides[get_workspace] = lambda: ws
    app.dependency_overrides[get_job_manager] = lambda: jobs
    # raise_server_exceptions=False: 실제 브라우저처럼 '응답'을 받아 본다 (테스트가 오류로 멈추지 않게)
    with TestClient(app, raise_server_exceptions=False) as c:
        c.jobs = jobs
        yield c
    app.dependency_overrides.clear()
    jobs.shutdown(wait=False)


def fake_free_space(monkeypatch, free_bytes: int):
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: Usage(100 * GB, 0, free_bytes))


# ---------- 예상 못 한 오류 ----------

def test_unexpected_error_returns_korean_json_with_error_id(client, caplog):
    def broken_engine():
        raise RuntimeError("secret internal detail C:\\Users\\someone\\path")

    app.dependency_overrides[get_engine] = broken_engine
    with caplog.at_level(logging.ERROR):
        res = client.get(f"/api/files/{'a' * 32}")
    assert res.status_code == 500
    body = res.json()                                         # 예전엔 JSON 이 아닌 영어 한 줄이었다
    assert "예상하지 못한 오류" in body["detail"] and body["error_id"] in body["detail"]
    assert "secret internal detail" not in body["detail"]     # 내부 경로·원인은 화면에 노출하지 않음
    assert any(body["error_id"] in r.getMessage() for r in caplog.records)  # 대신 로그에 같은 번호로 남김
    assert any("secret internal detail" in (r.exc_text or "") or r.exc_info for r in caplog.records)


def test_unexpected_error_inside_a_job_gets_an_error_id(client):
    def broken(report):
        raise KeyError("boom")

    job = client.jobs.submit("broken", broken)
    while not client.jobs.get(job.id).status.finished:
        time.sleep(0.02)
    error = client.jobs.get(job.id).error
    assert "오류 번호" in error and "app.log" in error


# ---------- 디스크 공간 ----------

def test_require_free_space_message_explains_what_to_do(monkeypatch, tmp_path):
    fake_free_space(monkeypatch, 600 * 1024**2)              # 600MB 남음
    with pytest.raises(disk_guard.InsufficientSpaceError) as e:
        disk_guard.require_free_space(tmp_path, 200 * 1024**2, "보컬 분리")  # 200MB 필요 + 여유 500MB
    msg = str(e.value)
    assert "보컬 분리" in msg and "600MB" in msg and "내 파일" in msg
    disk_guard.require_free_space(tmp_path, 50 * 1024**2, "보컬 분리")     # 50MB 면 통과


def test_estimates_are_sensible():
    # 3분 30초 곡 분리: 임시 원본 72MB + 보컬·MR WAV 72MB → 약 170MB (1.2배)
    assert 150 * 1024**2 < disk_guard.separation_bytes(210) < 200 * 1024**2
    assert disk_guard.render_bytes(10, 500 * 1024**2) >= 500 * 1024**2   # 큰 영상은 원본 크기 기준


@requires_ffmpeg
def test_upload_and_jobs_are_refused_when_disk_is_full(client, sine_wav, monkeypatch):
    with open(sine_wav, "rb") as f:
        song = client.post("/api/files", files={"file": ("노래.wav", f)}).json()["id"]

    fake_free_space(monkeypatch, 100 * 1024**2)              # 100MB 만 남음 → 여유분(500MB)도 안 됨
    with open(sine_wav, "rb") as f:
        res = client.post("/api/files", files={"file": ("또 다른 노래.wav", f)})
    assert res.status_code == 507 and "디스크 공간이 부족" in res.json()["detail"]
    res = client.post("/api/edits", json={"source_id": song, "output_format": "mp3"})
    assert res.status_code == 507 and "편집" in res.json()["detail"]
    res = client.post("/api/mixes", json={"tracks": [{"file_id": song}]})
    assert res.status_code == 507 and "믹스" in res.json()["detail"]
    assert client.get("/api/jobs/doesnotexist").status_code == 404  # 다른 기능은 그대로 동작


@requires_ffmpeg
def test_jobs_run_normally_with_enough_space(client, sine_wav, monkeypatch):
    fake_free_space(monkeypatch, 50 * GB)
    with open(sine_wav, "rb") as f:
        song = client.post("/api/files", files={"file": ("노래.wav", f)}).json()["id"]
    assert client.post("/api/edits", json={"source_id": song, "output_format": "mp3"}).status_code == 202


def test_log_file_rotates_and_is_utf8(tmp_path, monkeypatch):
    """로그 파일 설정: 한글이 깨지지 않고, 크기가 넘치면 돌려 쓴다."""
    from logging.handlers import RotatingFileHandler

    from app.core import config, logging_setup

    log_file = tmp_path / "logs" / "app.log"
    monkeypatch.setattr(config, "LOG_FILE", log_file)
    root = logging.getLogger()
    monkeypatch.setattr(root, "_vocalcut_configured", False, raising=False)
    before = list(root.handlers)
    try:
        logging_setup.setup_logging()
        handler = next(h for h in root.handlers if isinstance(h, RotatingFileHandler))
        assert handler.maxBytes == 1_000_000 and handler.backupCount == 3
        logging.getLogger("test").error("한글 오류 메시지 ♪")
        handler.flush()
        assert "한글 오류 메시지 ♪" in log_file.read_text(encoding="utf-8")
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()
    shutil.rmtree(log_file.parent, ignore_errors=True)
