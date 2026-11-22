"""자막 API 테스트 — 진짜 AI 대신 '가짜 받아쓰기 엔진'을 끼워서 흐름만 검사한다."""
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_job_manager, get_transcriber, get_workspace
from app.jobs.manager import JobManager
from app.main import app
from app.services import media_service
from app.services.engines.base import (
    Availability,
    TranscriberEngine,
    Transcript,
    TranscriptionError,
    TranscriptSegment,
)
from app.services.engines.registry import get_media_engine
from app.storage.workspace import Workspace
from tests.conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


class FakeTranscriber(TranscriberEngine):
    name = "fake"
    models = {"small": "정확", "base": "빠름"}
    default_model = "small"

    def __init__(self):
        self.available = True
        self.calls: list[tuple[Path, str, str | None]] = []
        self.isolated: list[bool] = []
        self.detected = "ko"
        self.fail = False
        self.release = threading.Event()
        self.release.set()

    def availability(self):
        return Availability(self.available, "" if self.available else "자막 패키지가 없습니다")

    def transcribe(self, src, model, language=None, on_progress=None, on_stage=None, on_segment=None,
                   isolated_voice=False):
        self.calls.append((Path(src), model, language))
        self.isolated.append(isolated_voice)
        if self.fail:
            raise TranscriptionError("boom", "받아쓰기 중 오류가 발생했습니다.")
        if on_stage:
            on_stage("받아 적는 중")
        segs = (TranscriptSegment(0.5, 1.5, "첫 번째 줄"), TranscriptSegment(1.6, 2.0, "두 번째 줄"))
        for s in segs:
            if on_segment:
                on_segment(s)
            while not self.release.wait(0.05):
                if on_progress:
                    on_progress(0.5)
        if on_progress:
            on_progress(1.0)
        return Transcript(language or self.detected, segs, detected_language=self.detected, detected_probability=0.95)


@pytest.fixture
def fake():
    return FakeTranscriber()


@pytest.fixture
def client(tmp_path: Path, fake):
    ws = Workspace(tmp_path / "workspace")
    ws.ensure()
    jobs = JobManager(ws.jobs)
    app.dependency_overrides[get_workspace] = lambda: ws
    app.dependency_overrides[get_job_manager] = lambda: jobs
    app.dependency_overrides[get_transcriber] = lambda: fake
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
        return client.post("/api/files", files={"file": ("내 노래.wav", f)}).json()["id"]


def add_vocals_stem(client, song_id, tmp_path) -> media_service.MediaFile:
    """분리가 끝난 상태를 흉내 낸다: 원곡 메타에 보컬 파일 id 를 적어 둔다."""
    engine = get_media_engine()
    src = media_service.get_media(client.ws, engine, song_id).path
    copy = tmp_path / "vocals.wav"
    shutil.copy(src, copy)
    vocals = media_service.register_file(client.ws, engine, copy, "내 노래 (보컬).wav",
                                         extra_meta={"derived_from": song_id, "stem": "vocals"})
    media_service.update_meta(client.ws, song_id, stems={"vocals": vocals.id})
    return vocals


def test_no_subtitles_before_transcription(client, song_id):
    assert client.get(f"/api/files/{song_id}/subtitles").status_code == 404


def test_transcription_saves_subtitles(client, song_id, fake):
    res = client.post("/api/transcriptions", json={"file_id": song_id})
    assert res.status_code == 202
    job = wait_job(client, res.json()["id"])
    assert job["status"] == "done", job
    assert job["result"] == {"file_id": song_id, "lines": 2, "language": "ko"}

    subs = client.get(f"/api/files/{song_id}/subtitles").json()
    assert [s["text"] for s in subs["segments"]] == ["첫 번째 줄", "두 번째 줄"]
    assert subs["segments"][0]["start"] == 0.5
    assert subs["model"] == "small" and subs["audio_source"] == "original"
    assert len({s["id"] for s in subs["segments"]}) == 2   # 줄마다 다른 이름표
    assert fake.calls[0][1:] == ("small", None)             # 기본값: small · 언어 자동 감지
    assert subs["language_mismatch"] is None
    assert fake.isolated == [False]                         # 원본 소리 → 반주가 섞였다고 알려줌


def test_separated_vocals_are_used_when_available(client, song_id, fake, tmp_path):
    vocals = add_vocals_stem(client, song_id, tmp_path)
    job = wait_job(client, client.post("/api/transcriptions", json={"file_id": song_id}).json()["id"])
    assert job["status"] == "done"
    assert fake.calls[0][0] == vocals.path                  # 반주 없는 보컬로 받아 적음
    subs = client.get(f"/api/files/{song_id}/subtitles").json()
    assert subs["audio_source"] == "vocals"                 # 자막은 원곡(대상 파일)에 저장
    assert fake.isolated == [True]                          # 보컬만 있는 소리라고 알려줌


def test_original_is_used_when_vocals_turned_off(client, song_id, fake, tmp_path):
    add_vocals_stem(client, song_id, tmp_path)
    wait_job(client, client.post("/api/transcriptions",
                                 json={"file_id": song_id, "use_vocals": False}).json()["id"])
    original = media_service.get_media(client.ws, get_media_engine(), song_id).path
    assert fake.calls[0][0] == original


def test_fast_model_and_auto_language(client, song_id, fake):
    job = wait_job(client, client.post("/api/transcriptions",
                                       json={"file_id": song_id, "model": "base", "language": "auto"}).json()["id"])
    assert job["status"] == "done"
    assert fake.calls[0][1:] == ("base", None)              # auto → 엔진에는 '자동 감지(None)'


@pytest.mark.parametrize("body", [{"model": "large-v3"}, {"language": "korean!"}])
def test_invalid_options_are_422(client, song_id, body):
    assert client.post("/api/transcriptions", json={"file_id": song_id, **body}).status_code == 422


def test_unavailable_transcriber_is_503(client, song_id, fake):
    fake.available = False
    res = client.post("/api/transcriptions", json={"file_id": song_id})
    assert res.status_code == 503 and "자막 패키지" in res.json()["detail"]


def test_unknown_file_is_404(client):
    assert client.post("/api/transcriptions", json={"file_id": "0" * 32}).status_code == 404
    assert client.get(f"/api/files/{'0' * 32}/subtitles").status_code == 404


def test_engine_failure_shows_friendly_message(client, song_id, fake):
    fake.fail = True
    job = wait_job(client, client.post("/api/transcriptions", json={"file_id": song_id}).json()["id"])
    assert job["status"] == "error" and job["error"] == "받아쓰기 중 오류가 발생했습니다."


def test_progress_shows_latest_line_and_cancel_works(client, song_id, fake):
    fake.release.clear()
    job_id = client.post("/api/transcriptions", json={"file_id": song_id}).json()["id"]
    time.sleep(0.3)
    running = client.get(f"/api/jobs/{job_id}").json()
    assert running["status"] == "running"
    assert "첫 번째 줄" in running["message"]               # 방금 받아 적은 줄이 진행 상황에 보임

    client.post(f"/api/jobs/{job_id}/cancel")
    assert wait_job(client, job_id)["status"] == "cancelled"
    assert client.get(f"/api/files/{song_id}/subtitles").status_code == 404  # 반쯤 된 자막은 저장 안 함


def test_health_lists_models(client):
    t = client.get("/api/health").json()["transcriber"]
    assert t["available"] is True and t["default_model"] == "small"
    assert [m["id"] for m in t["models"]] == ["small", "base"]


# ---------- 긴 줄 나누기 (순수 함수) ----------

def test_long_line_is_split_by_sentence_with_proportional_time():
    from app.services.subtitle_service import split_long_segment

    seg = TranscriptSegment(10.0, 18.0, "너는 아직도 그 노래를 기억하고 있을까? 시간이 지나도 변하지 않는 것들이 있다고 믿었어.")
    parts = split_long_segment(seg)
    assert [p.text for p in parts] == ["너는 아직도 그 노래를 기억하고 있을까?", "시간이 지나도 변하지 않는 것들이 있다고 믿었어."]
    assert parts[0].start == 10.0 and parts[-1].end == 18.0
    assert parts[0].end == parts[1].start                   # 빈틈·겹침 없이 이어짐
    assert 12.0 < parts[0].end < 14.5                       # 짧은 문장(21자) < 긴 문장(27자) → 앞쪽이 덜 차지


@pytest.mark.parametrize("text", ["짧은 줄입니다. 둘째 줄.", "마침표 없이 아주 길게 이어지는 노래 가사 한 줄은 억지로 자르지 않는다"])
def test_short_or_unsplittable_lines_stay(text):
    from app.services.subtitle_service import split_long_segment

    seg = TranscriptSegment(0.0, 5.0, text)
    assert split_long_segment(seg) == [seg]



def test_wrong_language_choice_is_flagged(client, song_id, fake):
    """버그 재현: 영어 노래를 '한국어'로 받아 적게 하면 중간에 멈췄다 → 결과에 경고를 남긴다."""
    fake.detected = "en"
    wait_job(client, client.post("/api/transcriptions", json={"file_id": song_id, "language": "ko"}).json()["id"])
    subs = client.get(f"/api/files/{song_id}/subtitles").json()
    assert subs["language_mismatch"] == {"chosen": "ko", "detected": "en"}
    assert subs["detected_language"] == "en"


@pytest.mark.parametrize("chosen,detected,prob,expected", [
    ("ko", "en", 0.95, {"chosen": "ko", "detected": "en"}),
    ("ko", "en", 0.4, None),        # AI 도 확신이 없으면 경고하지 않음
    ("ko", "ko", 0.99, None),
    (None, "en", 0.99, None),       # 자동 감지를 골랐으면 비교할 대상이 없음
    ("ko", None, 0.0, None),        # 감지 실패 (목소리가 없는 파일 등)
])
def test_language_mismatch_rule(chosen, detected, prob, expected):
    from app.services.subtitle_service import language_mismatch

    assert language_mismatch(chosen, detected, prob) == expected


# ---------- 편집 후 저장 ----------

def transcribed(client, song_id) -> dict:
    wait_job(client, client.post("/api/transcriptions", json={"file_id": song_id}).json()["id"])
    return client.get(f"/api/files/{song_id}/subtitles").json()


def test_saving_edited_lines_keeps_ai_info(client, song_id):
    subs = transcribed(client, song_id)
    first, second = subs["segments"]
    lines = [
        {**second, "text": "  고친   두 번째\n줄 "},                 # 공백·줄바꿈 정리 대상
        {**first, "start": 0.4},
        {"start": 1.9, "end": 2.0, "text": "새로 추가한 줄"},        # id 없음 → 서버가 붙임
    ]
    res = client.put(f"/api/files/{song_id}/subtitles", json={"segments": lines})
    assert res.status_code == 200, res.json()
    saved = client.get(f"/api/files/{song_id}/subtitles").json()
    assert [s["text"] for s in saved["segments"]] == ["첫 번째 줄", "고친 두 번째 줄", "새로 추가한 줄"]  # 시간순
    assert saved["segments"][0]["start"] == 0.4 and saved["segments"][0]["id"] == first["id"]
    assert len(saved["segments"][2]["id"]) == 12
    assert saved["model"] == "small" and saved["edited"] is True   # AI 정보는 그대로, '고침' 표시


@pytest.mark.parametrize("line,message", [
    ({"start": 0.5, "end": 1.0, "text": "   "}, "비어 있어요"),
    ({"start": 1.0, "end": 1.0, "text": "길이 0"}, "시간이 올바르지"),
    ({"start": -1, "end": 1.0, "text": "음수"}, "시간이 올바르지"),
    ({"start": 1.0, "end": 9.0, "text": "곡보다 김"}, "곡 길이"),       # 테스트 곡은 2초
    ({"start": 0.0, "end": 1.0, "text": "가" * 201}, "너무 길어요"),
])
def test_invalid_lines_are_rejected_with_reason(client, song_id, line, message):
    res = client.put(f"/api/files/{song_id}/subtitles", json={"segments": [line]})
    assert res.status_code == 422
    assert message in res.json()["detail"]


def test_lines_can_be_written_by_hand_without_ai(client, song_id):
    res = client.put(f"/api/files/{song_id}/subtitles", json={"segments": [{"start": 0, "end": 1, "text": "직접 쓴 줄"}]})
    assert res.status_code == 200
    assert res.json()["model"] == "manual"


def test_saving_all_lines_deleted_is_allowed(client, song_id):
    transcribed(client, song_id)
    assert client.put(f"/api/files/{song_id}/subtitles", json={"segments": []}).status_code == 200
    assert client.get(f"/api/files/{song_id}/subtitles").json()["segments"] == []


def test_save_unknown_file_is_404(client):
    assert client.put(f"/api/files/{'0' * 32}/subtitles", json={"segments": []}).status_code == 404
