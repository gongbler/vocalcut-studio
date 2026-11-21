import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_job_manager, get_workspace
from app.jobs.manager import JobManager
from app.main import app
from app.storage.workspace import Workspace
from tests.conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    w = Workspace(tmp_path / "workspace")
    w.ensure()
    return w


@pytest.fixture
def client(ws: Workspace):
    # 테스트마다 임시 폴더를 쓰는 작업 관리자를 따로 만든다
    jobs = JobManager(ws.jobs)
    app.dependency_overrides[get_workspace] = lambda: ws
    app.dependency_overrides[get_job_manager] = lambda: jobs
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    jobs.shutdown()


def wait_job(client: TestClient, job_id: str, timeout: float = 60) -> dict:
    """화면이 하는 일을 흉내: 작업이 끝날 때까지 상태를 반복 조회."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise TimeoutError(job_id)


def edit(client: TestClient, **payload) -> dict:
    """편집 주문 → 번호표 → 완료 대기 → 결과물 정보."""
    res = client.post("/api/edits", json=payload)
    assert res.status_code == 202, res.text
    job = wait_job(client, res.json()["id"])
    assert job["status"] == "done", job
    return client.get(f"/api/outputs/{job['result']['output_id']}").json()


@pytest.fixture
def source_id(client, sine_wav) -> str:
    with open(sine_wav, "rb") as f:
        return client.post("/api/files", files={"file": ("내 노래.wav", f)}).json()["id"]


# ---------- 작업 대기열 흐름 ----------

def test_edit_returns_job_ticket_immediately(client, source_id):
    res = client.post("/api/edits", json={"source_id": source_id})
    assert res.status_code == 202          # 202 Accepted = "접수됨, 처리는 나중에"
    job = res.json()
    assert job["kind"] == "edit"
    assert job["status"] in ("queued", "running", "done")

    final = wait_job(client, job["id"])
    assert final["status"] == "done"
    assert final["progress"] == 1.0
    assert "output_id" in final["result"]


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404


def test_create_edit_and_stream_result(client, source_id):
    body = edit(client, source_id=source_id, start_sec=0.5, end_sec=1.5,
                volume_db=-3, fade_in_sec=0.2, fade_out_sec=0.2)

    assert body["kind"] == "audio"
    assert body["download_name"] == "내 노래_edit.mp3"
    assert body["duration_sec"] == pytest.approx(1.0, abs=0.06)

    content = client.get(body["content_url"])
    assert content.status_code == 200
    assert len(content.content) == body["size_bytes"]


# ---------- 잘못된 주문은 대기열에 들어가기 전에 바로 거절 ----------

def test_invalid_range_is_422_and_leaves_nothing(client, source_id, ws):
    res = client.post("/api/edits", json={"source_id": source_id, "start_sec": 1.8, "end_sec": 1.0})
    assert res.status_code == 422
    assert list(ws.outputs.iterdir()) == []
    assert list(ws.jobs.iterdir()) == []   # 번호표도 발급되지 않음


def test_end_beyond_duration_is_422(client, source_id):
    res = client.post("/api/edits", json={"source_id": source_id, "end_sec": 99})
    assert res.status_code == 422
    assert "파일 길이" in res.json()["detail"]


def test_unknown_source_is_404(client):
    assert client.post("/api/edits", json={"source_id": "0" * 32}).status_code == 404


def test_unknown_output_is_404(client):
    assert client.get("/api/outputs/" + "0" * 32).status_code == 404
    assert client.get("/api/outputs/" + "0" * 32 + "/download").status_code == 404


# ---------- 1-4: 출력 형식 + 다운로드 ----------

@pytest.fixture
def video_id(client, test_mp4) -> str:
    with open(test_mp4, "rb") as f:
        return client.post("/api/files", files={"file": ("뮤직비디오.mp4", f)}).json()["id"]


def test_default_format_audio_is_mp3(client, source_id):
    assert edit(client, source_id=source_id)["format"] == "mp3"


def test_wav_output_is_lossless_pcm(client, source_id, ws):
    from app.services.engines.media.ffmpeg_engine import FFmpegEngine

    body = edit(client, source_id=source_id, output_format="wav")

    assert body["format"] == "wav"
    assert body["download_name"] == "내 노래_edit.wav"
    info = FFmpegEngine().probe(ws.outputs / body["id"] / "result.wav")
    assert info.audio.codec == "pcm_s16le"  # 무손실 WAV


def test_extract_audio_from_video(client, video_id):
    body = edit(client, source_id=video_id, output_format="mp3")
    assert body["kind"] == "audio"          # 영상에서 소리만 뽑아냄
    assert body["download_name"] == "뮤직비디오_edit.mp3"


def test_audio_cannot_become_mp4(client, source_id, ws):
    res = client.post("/api/edits", json={"source_id": source_id, "output_format": "mp4"})
    assert res.status_code == 422
    assert "MP4" in res.json()["detail"]
    assert list(ws.outputs.iterdir()) == []


def test_unknown_format_rejected_by_schema(client, source_id):
    res = client.post("/api/edits", json={"source_id": source_id, "output_format": "exe"})
    assert res.status_code == 422


def test_download_is_attachment_with_korean_name(client, source_id):
    body = edit(client, source_id=source_id)

    res = client.get(body["download_url"])
    assert res.status_code == 200
    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment")
    # 한글 이름은 퍼센트 인코딩된 UTF-8 로 전달된다: 내 노래_edit.mp3
    assert "filename*=utf-8''%EB%82%B4%20%EB%85%B8%EB%9E%98_edit.mp3" in disposition

    # 재생용 주소는 inline (브라우저 안에서 재생)
    assert client.get(body["content_url"]).headers["content-disposition"].startswith("inline")
