"""faster-whisper 자막 엔진 — 서버 쪽 '조종기'.

이 파일은 faster_whisper 를 import 하지 않는다. 실제 AI 처리는 별도 프로세스(whisper_runner)가 하고,
여기서는 그 프로세스를 실행·감시하고 결과(JSON 줄)를 해석하기만 한다. (Demucs 엔진과 같은 구조)
"""
from __future__ import annotations

import importlib.util
import logging
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from app.core import config
from app.services.engines.base import (
    Availability,
    OnProgress,
    TranscriberEngine,
    Transcript,
    TranscriptionError,
    TranscriptSegment,
)
from app.services.engines.runner_client import RunnerTimeout, describe, is_memory_failure, run_runner

logger = logging.getLogger(__name__)

TRANSCRIBE_TIMEOUT_SEC = 2 * 60 * 60

STAGE_LABELS = {
    "decode": "오디오 준비 중",
    "load_model": "AI 모델 불러오는 중",
    "download": "AI 모델 내려받는 중 (처음 한 번만)",
    "detect_language": "언어 확인 중",
    "transcribe": "받아 적는 중",
}


class WhisperTranscriber(TranscriberEngine):
    name = "whisper"

    def __init__(
        self,
        models_dir: Path = config.MODELS_DIR,
        models: dict[str, str] | None = None,
        default_model: str = config.WHISPER_DEFAULT_MODEL,
        max_speech_sec: float = config.WHISPER_MAX_SPEECH_SEC,
        vad_threshold_mixed: float = config.WHISPER_VAD_THRESHOLD_MIXED,
        runner_cmd: list[str] | None = None,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.models = dict(models or config.WHISPER_MODELS)
        self.default_model = default_model
        self.max_speech_sec = max_speech_sec
        self.vad_threshold_mixed = vad_threshold_mixed
        # 테스트에서는 '가짜 실행기'로 바꿔 끼울 수 있다
        self.runner_cmd = runner_cmd or [sys.executable, "-m", "app.services.engines.transcriber.whisper_runner"]

    def availability(self) -> Availability:
        if importlib.util.find_spec("faster_whisper") is None:
            return Availability(False, "'faster_whisper' 패키지가 설치되지 않았습니다 (requirements-asr.txt 참고).")
        if shutil.which("ffmpeg") is None:
            return Availability(False, "FFmpeg를 찾을 수 없습니다.")
        return Availability(True)

    def transcribe(
        self,
        src: Path,
        model: str,
        language: str | None = None,
        on_progress: OnProgress | None = None,
        on_stage: Callable[[str], None] | None = None,
        on_segment: Callable[[TranscriptSegment], None] | None = None,
        isolated_voice: bool = False,
    ) -> Transcript:
        status = self.availability()
        if not status.ok:
            raise TranscriptionError(status.reason, status.reason)
        if model not in self.models:
            raise TranscriptionError(f"unknown model {model}", f"알 수 없는 모델입니다: {model}")

        cmd = self.build_command(src, model, language, isolated_voice)
        segments: list[TranscriptSegment] = []

        def on_message(msg: dict) -> None:
            event = msg.get("event")
            if event == "stage" and on_stage:
                on_stage(STAGE_LABELS.get(msg.get("name"), msg.get("name")))
            elif event == "segment":
                seg = TranscriptSegment(float(msg["start"]), float(msg["end"]), str(msg["text"]))
                segments.append(seg)
                if on_segment:
                    on_segment(seg)
            elif event == "warning":
                logger.warning("whisper runner: %s", msg.get("message"))

        try:
            run = run_runner(cmd, TRANSCRIBE_TIMEOUT_SEC, on_message=on_message, on_progress=on_progress)
        except RunnerTimeout as e:
            raise TranscriptionError("timeout", "자막 받아쓰기 시간이 초과되었습니다.") from e
        if not run.ok:
            if is_memory_failure(run):
                raise TranscriptionError(
                    describe(run),
                    "메모리가 부족해 받아쓰기에 실패했습니다. "
                    "다른 프로그램(브라우저 탭 등)을 닫거나 '빠름' 모델로 다시 시도하세요.",
                )
            raise TranscriptionError(describe(run), "받아쓰기 중 오류가 발생했습니다. 서버 로그를 확인하세요.")

        result = run.final or {}
        logger.info("whisper done: model=%s %.1fs peak %s MB, %d lines",
                    model, result.get("elapsed_sec", 0), result.get("peak_mb"), len(segments))
        if on_progress:
            on_progress(1.0)
        return Transcript(
            language=str(result.get("language") or language or ""),
            segments=tuple(segments),
            detected_language=result.get("detected_language"),
            detected_probability=float(result.get("detected_probability") or 0.0),
        )

    def build_command(self, src: Path, model: str, language: str | None, isolated_voice: bool) -> list[str]:
        cmd = [
            *self.runner_cmd,
            "--input", str(src),
            "--models-dir", str(self.models_dir),
            "--model", model,
            "--language", language or "auto",
            "--max-speech-sec", str(self.max_speech_sec),
            "--ffmpeg", shutil.which("ffmpeg") or "ffmpeg",
        ]
        if not isolated_voice:
            # 반주가 섞인 소리: 목소리 감지 기준을 낮춰 반주 위의 노래를 덜 놓치게
            cmd += ["--vad-threshold", str(self.vad_threshold_mixed)]
        return cmd
