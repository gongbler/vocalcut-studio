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


@pytest.fixture
def source_id(client, sine_wav) -> str:
    with open(sine_wav, "rb") as f:
        return client.post("/api/files", files={"file": ("내 노래.wav", f)}).json()["id"]


def test_create_edit_and_stream_result(client, source_id):
    res = client.post("/api/edits", json={
        "source_id": source_id, "start_sec": 0.5, "end_sec": 1.5,
        "volume_db": -3, "fade_in_sec": 0.2, "fade_out_sec": 0.2,
    })

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "audio"
    assert body["download_name"] == "내 노래_edit.mp3"
    assert body["duration_sec"] == pytest.approx(1.0, abs=0.06)

    content = client.get(body["content_url"])
    assert content.status_code == 200
    assert len(content.content) == body["size_bytes"]


def test_invalid_range_is_422_and_leaves_nothing(client, source_id, ws):
    res = client.post("/api/edits", json={"source_id": source_id, "start_sec": 1.8, "end_sec": 1.0})
    assert res.status_code == 422
    assert list(ws.outputs.iterdir()) == []


def test_end_beyond_duration_is_422(client, source_id):
    res = client.post("/api/edits", json={"source_id": source_id, "end_sec": 99})
    assert res.status_code == 422
    assert "파일 길이" in res.json()["detail"]


def test_unknown_source_is_404(client):
    assert client.post("/api/edits", json={"source_id": "0" * 32}).status_code == 404


def test_unknown_output_is_404(client):
    assert client.get("/api/outputs/" + "0" * 32).status_code == 404
