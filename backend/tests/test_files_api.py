"""파일 업로드 API 테스트.

TestClient 는 진짜 서버를 띄우지 않고도 HTTP 요청을 흉내 내 앱을 호출한다.
dependency_overrides 로 작업 폴더를 pytest 임시 폴더로 바꿔서, 실제 workspace 를 더럽히지 않는다.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_workspace
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
    app.dependency_overrides[get_workspace] = lambda: ws
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _upload(client: TestClient, path: Path, name: str | None = None):
    with open(path, "rb") as f:
        return client.post("/api/files", files={"file": (name or path.name, f)})


# ---------- 정상 동작 ----------

def test_upload_audio_returns_info(client, sine_wav):
    res = _upload(client, sine_wav, "내 노래.wav")

    assert res.status_code == 201
    body = res.json()
    assert body["original_name"] == "내 노래.wav"
    assert body["kind"] == "audio"
    assert body["duration_sec"] == pytest.approx(2.0, abs=0.05)
    assert body["audio"]["sample_rate"] == 44100
    assert body["video"] is None
    assert "path" not in body  # 서버 내부 경로는 노출하지 않는다


def test_upload_video_kind(client, test_mp4):
    body = _upload(client, test_mp4).json()
    assert body["kind"] == "video"
    assert body["video"]["width"] == 320


def test_get_and_stream_uploaded_file(client, sine_wav):
    file_id = _upload(client, sine_wav).json()["id"]

    assert client.get(f"/api/files/{file_id}").json()["id"] == file_id

    content = client.get(f"/api/files/{file_id}/content")
    assert content.status_code == 200
    assert content.content == sine_wav.read_bytes()


def test_content_supports_range_requests(client, sine_wav):
    # 재생 바를 움직일 때 브라우저가 보내는 "일부만 보내줘" 요청
    file_id = _upload(client, sine_wav).json()["id"]
    res = client.get(f"/api/files/{file_id}/content", headers={"Range": "bytes=0-99"})
    assert res.status_code == 206
    assert len(res.content) == 100


# ---------- 막아야 하는 경우 ----------

def test_reject_unsupported_extension(client, tmp_path, ws):
    txt = tmp_path / "memo.txt"
    txt.write_text("hello", encoding="utf-8")

    res = _upload(client, txt)
    assert res.status_code == 415
    assert list(ws.uploads.iterdir()) == []  # 아무것도 남기지 않음


def test_reject_fake_media_and_clean_up(client, tmp_path, ws):
    fake = tmp_path / "fake.mp3"
    fake.write_text("이건 mp3가 아님", encoding="utf-8")

    res = _upload(client, fake)
    assert res.status_code == 422
    assert list(ws.uploads.iterdir()) == []  # 반쯤 저장된 파일도 치움

    detail = res.json()["detail"]
    assert "fake.mp3" in detail            # 사용자가 올린 이름으로 안내
    assert str(ws.root) not in detail      # 서버 내부 경로는 노출하지 않음
    assert "source.mp3" not in detail


def test_unknown_id_is_404(client):
    assert client.get("/api/files/" + "0" * 32).status_code == 404


@pytest.mark.parametrize("bad_id", ["..", "abc", "..%2F..%2Fsecret", "Z" * 32])
def test_malformed_id_is_404(client, bad_id):
    # 경로 조작 시도는 형식 검사에서 바로 걸러진다
    assert client.get(f"/api/files/{bad_id}").status_code == 404
