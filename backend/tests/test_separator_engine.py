"""Demucs 엔진(조종기) 테스트 — 가짜 실행기로 '통신 규칙'과 에러 처리를 검사한다."""
import sys
import time
from pathlib import Path

import pytest

from app.jobs.manager import JobCancelled
from app.services.engines.base import Availability, SeparationError
from app.services.engines.separator.demucs_engine import DemucsSeparator

FAKE = Path(__file__).parent / "fakes" / "fake_runner.py"


def make_engine(mode: str, monkeypatch) -> DemucsSeparator:
    engine = DemucsSeparator(runner_cmd=[sys.executable, str(FAKE), "--mode", mode])
    monkeypatch.setattr(engine, "availability", lambda: Availability(True))
    return engine


def test_success_reports_progress_stages_and_files(monkeypatch, tmp_path):
    progress, stages = [], []
    stems = make_engine("ok", monkeypatch).separate(
        tmp_path / "in.wav", tmp_path / "out", on_progress=progress.append, on_stage=stages.append
    )

    assert stems.vocals.is_file() and stems.instrumental.is_file()
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert stages == ["오디오 준비 중", "AI 모델 불러오는 중", "보컬/MR 분리 중"]  # 화면용 한국어


def test_memory_error_becomes_friendly_message(monkeypatch, tmp_path):
    with pytest.raises(SeparationError) as e:
        make_engine("memory", monkeypatch).separate(tmp_path / "in.wav", tmp_path / "out")
    assert "메모리가 부족" in e.value.user_message
    assert "브라우저" in e.value.user_message             # 해결 방법까지 안내


def test_silent_crash_is_reported(monkeypatch, tmp_path):
    with pytest.raises(SeparationError) as e:
        make_engine("crash", monkeypatch).separate(tmp_path / "in.wav", tmp_path / "out")
    assert e.value.user_message                            # 아무 말 없이 죽어도 사용자에게 알림


def test_cancel_kills_runner_quickly(monkeypatch, tmp_path):
    """진행률 콜백이 JobCancelled 를 던지면(=사용자 취소) 실행기 프로세스를 바로 종료해야 한다."""
    seen = []

    def on_progress(p):
        seen.append(p)
        if p > 0.1:
            raise JobCancelled()

    started = time.monotonic()
    with pytest.raises(JobCancelled):
        make_engine("slow", monkeypatch).separate(tmp_path / "in.wav", tmp_path / "out", on_progress=on_progress)
    assert time.monotonic() - started < 5                  # 'slow' 모드는 끝까지 가면 10초 이상
    assert not (tmp_path / "out" / "vocals.wav").exists()  # 결과를 만들기 전에 멈춤

    # 실제로 일하던 프로세스(.venv 런처의 '자식')까지 종료됐는지 확인
    pid = int((tmp_path / "out" / "_work" / "pid.txt").read_text())
    assert not pid_alive(pid)


def test_cancel_is_fast_even_when_runner_is_silent(monkeypatch, tmp_path):
    """실행기가 30초 동안 아무 보고도 안 하는 중이라도, 취소는 1~2초 안에 반영돼야 한다.
    (수정 전: 다음 보고 줄이 올 때까지 기다려서 실제 Demucs에서 10~16초 걸렸음)"""
    import threading

    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()  # 0.5초 뒤 사용자가 '취소'를 누름

    def on_progress(_p):
        if cancel.is_set():
            raise JobCancelled()

    started = time.monotonic()
    with pytest.raises(JobCancelled):
        make_engine("silent", monkeypatch).separate(tmp_path / "in.wav", tmp_path / "out", on_progress=on_progress)
    assert time.monotonic() - started < 3


def pid_alive(pid: int) -> bool:
    import os
    import subprocess
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def test_availability_does_not_import_torch():
    """서버 메모리를 지키는 약속: 사용 가능 여부 확인만으로 torch 가 메모리에 올라오면 안 된다."""
    import subprocess
    code = ("import sys; from app.services.engines.separator.demucs_engine import DemucsSeparator; "
            "DemucsSeparator().availability(); print('torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).parents[1], check=True).stdout.strip()
    assert out == "False"
