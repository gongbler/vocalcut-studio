"""Whisper 엔진(조종기) 테스트 — 가짜 실행기로 '통신 규칙'과 에러 처리를 검사한다."""
import sys
import time
from pathlib import Path

import pytest

from app.jobs.manager import JobCancelled
from app.services.engines.base import Availability, TranscriptionError
from app.services.engines.transcriber.whisper_engine import WhisperTranscriber

FAKE = Path(__file__).parent / "fakes" / "fake_whisper_runner.py"


def make_engine(mode: str, monkeypatch) -> WhisperTranscriber:
    engine = WhisperTranscriber(runner_cmd=[sys.executable, str(FAKE), "--mode", mode])
    monkeypatch.setattr(engine, "availability", lambda: Availability(True))
    return engine


def test_success_returns_korean_lines_in_order(monkeypatch, tmp_path):
    progress, stages, live = [], [], []
    t = make_engine("ok", monkeypatch).transcribe(
        tmp_path / "in.wav", "small", "ko",
        on_progress=progress.append, on_stage=stages.append, on_segment=live.append,
    )
    assert t.language == "ko"
    assert [s.text for s in t.segments] == ["오늘 밤 창문을 열면", "차가운 바람이 불어와 ♪"]  # 한글이 깨지지 않음
    assert t.segments[0].start == 0.5 and t.segments[1].end == 4.0
    assert live == list(t.segments)                       # 줄이 완성될 때마다 바로 알림
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert stages == ["오디오 준비 중", "AI 모델 불러오는 중", "언어 확인 중", "받아 적는 중"]
    assert t.detected_language == "ko" and t.detected_probability == 0.98


def test_auto_language_uses_detected_language(monkeypatch, tmp_path):
    t = make_engine("ok", monkeypatch).transcribe(tmp_path / "in.wav", "base", None)
    assert t.language == "ko"


def test_unknown_model_is_rejected(monkeypatch, tmp_path):
    with pytest.raises(TranscriptionError):
        make_engine("ok", monkeypatch).transcribe(tmp_path / "in.wav", "large-v3")


def test_memory_error_suggests_fast_model(monkeypatch, tmp_path):
    with pytest.raises(TranscriptionError) as e:
        make_engine("memory", monkeypatch).transcribe(tmp_path / "in.wav", "small")
    assert "메모리가 부족" in e.value.user_message
    assert "빠름" in e.value.user_message                 # 해결 방법(작은 모델)까지 안내


def test_silent_crash_is_reported(monkeypatch, tmp_path):
    with pytest.raises(TranscriptionError) as e:
        make_engine("crash", monkeypatch).transcribe(tmp_path / "in.wav", "small")
    assert e.value.user_message


def test_cancel_stops_runner_quickly(monkeypatch, tmp_path):
    def on_progress(p):
        if p > 0.05:
            raise JobCancelled()

    started = time.monotonic()
    with pytest.raises(JobCancelled):
        make_engine("slow", monkeypatch).transcribe(tmp_path / "in.wav", "small", on_progress=on_progress)
    assert time.monotonic() - started < 5                 # 'slow' 모드는 끝까지 가면 10초 이상


def test_availability_does_not_import_faster_whisper():
    """서버가 상태를 확인할 때 AI 라이브러리를 불러오면 안 된다 (메모리 절약)."""
    WhisperTranscriber().availability()
    assert "faster_whisper" not in sys.modules
    assert "ctranslate2" not in sys.modules


def test_detected_language_is_reported_even_when_language_is_forced(monkeypatch, tmp_path):
    t = make_engine("english", monkeypatch).transcribe(tmp_path / "in.wav", "small", "ko")
    assert t.language == "ko"                              # 고른 언어로 받아 적었지만
    assert t.detected_language == "en"                     # 실제로는 영어라는 사실을 알려준다


def test_mixed_audio_lowers_voice_detection_threshold():
    """반주가 섞인 원곡은 VAD 기준을 낮추고, 분리된 보컬은 기본값을 쓴다."""
    engine = WhisperTranscriber(runner_cmd=["runner"])
    mixed = engine.build_command(Path("a.wav"), "small", None, isolated_voice=False)
    vocals = engine.build_command(Path("a.wav"), "small", None, isolated_voice=True)
    assert mixed[mixed.index("--vad-threshold") + 1] == str(engine.vad_threshold_mixed)
    assert "--vad-threshold" not in vocals
    assert mixed[mixed.index("--language") + 1] == "auto"
