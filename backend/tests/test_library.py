"""'내 파일' 테스트: 묶음 목록 · 통째 삭제 · 작업 중 삭제 금지 · 용량 · 서버 시작 정리."""
import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_job_manager, get_workspace
from app.jobs.manager import JobManager
from app.main import app
from app.services import library_service, media_service
from app.services.engines.registry import get_media_engine
from app.storage.workspace import Workspace
from tests.conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


@pytest.fixture
def client(tmp_path: Path):
    ws = Workspace(tmp_path / "workspace")
    ws.ensure()
    jobs = JobManager(ws.jobs)
    app.dependency_overrides[get_workspace] = lambda: ws
    app.dependency_overrides[get_job_manager] = lambda: jobs
    with TestClient(app) as c:
        c.ws, c.jobs = ws, jobs
        yield c
    app.dependency_overrides.clear()
    jobs.shutdown(wait=False)


def upload(client, path: Path, name: str) -> str:
    with open(path, "rb") as f:
        return client.post("/api/files", files={"file": (name, f)}).json()["id"]


def make_separated(client, song_id: str, tmp_path: Path) -> dict[str, str]:
    """분리가 끝난 상태를 흉내 낸다: 보컬/MR 등록 + 원곡 메타에 기록."""
    engine = get_media_engine()
    src = media_service.get_media(client.ws, engine, song_id).path
    ids = {}
    for stem in ("vocals", "instrumental"):
        copy = tmp_path / f"{stem}.wav"
        shutil.copy(src, copy)
        ids[stem] = media_service.register_file(client.ws, engine, copy, f"노래 ({stem}).wav",
                                                extra_meta={"derived_from": song_id, "stem": stem}).id
    media_service.update_meta(client.ws, song_id, stems=ids)
    return ids


def make_output(client, source_id: str, size: int = 1000) -> str:
    output_id, out_dir = client.ws.create_output_dir()
    (out_dir / "result.mp3").write_bytes(b"0" * size)
    client.ws.write_meta(out_dir, {"source_id": source_id, "download_name": "x.mp3", "format": "mp3",
                                   "stored_name": "result.mp3"})
    return output_id


def test_library_groups_stems_outputs_and_subtitles_under_the_song(client, sine_wav, tmp_path):
    song = upload(client, sine_wav, "내 노래.wav")
    time.sleep(0.05)
    other = upload(client, sine_wav, "다른 노래.wav")
    stems = make_separated(client, song, tmp_path)
    make_output(client, stems["vocals"], size=5000)      # 보컬로 만든 결과물도 원곡 묶음으로
    make_output(client, song)
    client.put(f"/api/files/{song}/subtitles", json={"segments": [{"start": 0, "end": 1, "text": "가사"}]})

    items = client.get("/api/library").json()
    assert [i["original_name"] for i in items] == ["다른 노래.wav", "내 노래.wav"]  # 최근 것부터
    mine = items[1]
    assert mine["id"] == song and mine["stems"] == stems
    assert mine["derived_count"] == 2 and mine["output_count"] == 2 and mine["has_subtitles"] is True
    assert mine["kind"] == "audio" and mine["duration_sec"] == pytest.approx(2.0, abs=0.05)
    assert mine["size_bytes"] > items[0]["size_bytes"] + 6000  # 보컬·MR·결과물까지 합친 크기
    assert other not in (stems["vocals"], stems["instrumental"])


def test_old_files_without_list_info_are_filled_in_once(client, sine_wav):
    song = upload(client, sine_wav, "예전 노래.wav")
    meta_path = client.ws.uploads / song / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in ("kind", "duration_sec", "created_at"):  # 4-2 이전에 올린 파일 흉내
        meta.pop(key)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert client.get("/api/library").json()[0]["duration_sec"] == pytest.approx(2.0, abs=0.05)
    assert "duration_sec" in json.loads(meta_path.read_text(encoding="utf-8"))  # 다음부터는 분석 안 함


def test_orphan_stem_is_listed_on_its_own(client, sine_wav, tmp_path):
    song = upload(client, sine_wav, "노래.wav")
    stems = make_separated(client, song, tmp_path)
    shutil.rmtree(client.ws.uploads / song)              # 원곡 폴더만 사라진 상태
    ids = {i["id"] for i in client.get("/api/library").json()}
    assert ids == set(stems.values())                    # 숨지 않고 보여서 지울 수 있다


def test_delete_removes_the_whole_bundle_only(client, sine_wav, tmp_path):
    song = upload(client, sine_wav, "지울 노래.wav")
    keep = upload(client, sine_wav, "남길 노래.wav")
    stems = make_separated(client, song, tmp_path)
    outputs = [make_output(client, stems["vocals"]), make_output(client, song)]
    kept_output = make_output(client, keep)

    res = client.delete(f"/api/library/{song}")
    assert res.status_code == 200
    body = res.json()
    assert body["deleted_files"] == 3 and body["deleted_outputs"] == 2 and body["freed_bytes"] > 0
    for file_id in (song, *stems.values()):
        assert client.get(f"/api/files/{file_id}").status_code == 404
    for output_id in outputs:
        assert client.ws.output_dir(output_id) is None
    assert client.get(f"/api/files/{keep}").status_code == 200       # 다른 노래는 그대로
    assert client.ws.output_dir(kept_output) is not None


def test_cannot_delete_while_a_job_is_running(client, sine_wav):
    song = upload(client, sine_wav, "노래.wav")
    release = threading.Event()

    def slow(report):
        while not release.wait(0.05):
            report(0.5)
        return {}

    job = client.jobs.submit("slow", slow)
    try:
        res = client.delete(f"/api/library/{song}")
        assert res.status_code == 409 and "작업" in res.json()["detail"]
        assert client.get(f"/api/files/{song}").status_code == 200
    finally:
        release.set()
    while not client.jobs.get(job.id).status.finished:
        time.sleep(0.05)
    assert client.delete(f"/api/library/{song}").status_code == 200    # 끝난 뒤에는 삭제됨


def test_delete_unknown_or_malformed_id_is_404(client):
    assert client.delete(f"/api/library/{'0' * 32}").status_code == 404
    assert client.delete("/api/library/..%2F..%2Fwindows").status_code == 404


def test_storage_reports_sizes(client, sine_wav):
    upload(client, sine_wav, "노래.wav")
    s = client.get("/api/storage").json()
    assert s["uploads_bytes"] > 0
    assert s["workspace_bytes"] == s["uploads_bytes"] + s["outputs_bytes"] + s["temp_bytes"] + s["jobs_bytes"]
    assert s["disk_free_bytes"] > 0


# ---------------------------------------------------------------- 서버 시작 정리

def test_startup_cleanup_removes_only_leftovers(tmp_path, sine_wav):
    ws = Workspace(tmp_path / "ws")
    ws.ensure()
    (ws.temp / "sep_abc").mkdir()
    (ws.temp / "sep_abc" / "input.f32").write_bytes(b"0" * 2048)   # 강제 종료로 남은 임시 파일
    (ws.temp / "stray.tmp").write_bytes(b"0" * 10)
    upload_id, upload_dir = ws.create_upload_dir()
    shutil.copy(sine_wav, upload_dir / "source.wav")
    output_id, out_dir = ws.create_output_dir()
    (out_dir / "result.mp3").write_bytes(b"0")

    now = time.time()
    day = 86400

    def job(name, status, age_days):
        (ws.jobs / f"{name}.json").write_text(json.dumps({"status": status, "updated_at": now - age_days * day}))

    job("old_done", "done", 40)
    job("old_error", "error", 31)
    job("recent_done", "done", 3)
    job("old_running", "running", 40)                   # 끝나지 않은 기록은 남긴다 (재시작 시 '중단됨' 표시용)

    result = library_service.startup_cleanup(ws, now=now)
    assert result == {"temp_entries": 2, "temp_bytes": 2058, "job_records": 2}
    assert list(ws.temp.iterdir()) == []
    assert sorted(p.stem for p in ws.jobs.glob("*.json")) == ["old_running", "recent_done"]
    assert (upload_dir / "source.wav").is_file() and (out_dir / "result.mp3").is_file()  # 사용자 파일은 그대로


def test_delete_reports_files_that_could_not_be_removed(client, sine_wav, monkeypatch):
    """윈도우에서 파일이 사용 중이라 안 지워지면 '삭제 완료'라고 하지 않는다."""
    song = upload(client, sine_wav, "열려 있는 노래.wav")
    monkeypatch.setattr(library_service, "remove_dir_with_retry", lambda path: None)  # 지우기 실패 흉내
    res = client.delete(f"/api/library/{song}")
    assert res.status_code == 409 and "지우지 못했어요" in res.json()["detail"]
