"""Demucs 분리 엔진 — 서버 쪽 '조종기'.

이 파일은 torch 를 import 하지 않는다. 실제 AI 처리는 별도 프로세스(demucs_runner)가 하고,
여기서는 그 프로세스를 실행·감시하고 결과(JSON 줄)를 해석하기만 한다.
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
    SeparationError,
    SeparatorEngine,
    StemPaths,
)
from app.services.engines.runner_client import (  # noqa: F401 — kill_process_tree 는 예전 위치 호환용
    RunnerResult,
    RunnerTimeout,
    describe,
    is_memory_failure,
    kill_process_tree,
    run_runner,
)

logger = logging.getLogger(__name__)

SEPARATE_TIMEOUT_SEC = 3 * 60 * 60  # 저사양 PC에서 긴 곡도 끝낼 수 있게 3시간

# 실행기가 보고하는 단계 이름 → 화면에 보여줄 말
STAGE_LABELS = {
    "decode": "오디오 준비 중",
    "load_model": "AI 모델 불러오는 중",
    "separate": "보컬/MR 분리 중",
}


class DemucsSeparator(SeparatorEngine):
    name = "demucs"

    def __init__(
        self,
        models_dir: Path = config.MODELS_DIR,
        model: str = config.DEMUCS_MODEL,
        chunk_sec: float = config.DEMUCS_CHUNK_SEC,
        runner_cmd: list[str] | None = None,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.model = model
        self.chunk_sec = chunk_sec
        # 테스트에서는 '가짜 실행기'로 바꿔 끼울 수 있다 (torch 없이 통신 규칙만 검사)
        self.runner_cmd = runner_cmd or [sys.executable, "-m", "app.services.engines.separator.demucs_runner"]

    # ------------------------------------------------------------------
    def availability(self) -> Availability:
        # find_spec: 패키지가 '설치돼 있는지'만 찾는다. 실제로 불러오지 않아서 가볍다.
        for pkg in ("torch", "demucs"):
            if importlib.util.find_spec(pkg) is None:
                return Availability(False, f"'{pkg}' 패키지가 설치되지 않았습니다 (requirements-ai.txt 참고).")
        if shutil.which("ffmpeg") is None:
            return Availability(False, "FFmpeg를 찾을 수 없습니다.")
        return Availability(True)

    # ------------------------------------------------------------------
    def separate(
        self,
        src: Path,
        out_dir: Path,
        on_progress: OnProgress | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> StemPaths:
        status = self.availability()
        if not status.ok:
            raise SeparationError(status.reason, status.reason)

        cmd = [
            *self.runner_cmd,
            "--input", str(src),
            "--outdir", str(out_dir),
            # 실행기의 임시 파일도 out_dir 안에 → 호출한 쪽이 out_dir 만 지우면 모두 정리된다
            "--tmpdir", str(Path(out_dir) / "_work"),
            "--models-dir", str(self.models_dir),
            "--model", self.model,
            "--chunk-sec", str(self.chunk_sec),
            "--ffmpeg", shutil.which("ffmpeg") or "ffmpeg",
        ]

        def on_message(msg: dict) -> None:
            if msg.get("event") == "stage" and on_stage:
                on_stage(STAGE_LABELS.get(msg.get("name"), msg.get("name")))

        try:
            run = run_runner(cmd, SEPARATE_TIMEOUT_SEC, on_message=on_message, on_progress=on_progress)
        except RunnerTimeout as e:
            raise SeparationError("timeout", "보컬 분리 시간이 초과되었습니다.") from e
        if not run.ok:
            raise self._to_error(run)
        result = run.final

        logger.info("demucs done: %.1fs, peak %s MB", result.get("elapsed_sec", 0), result.get("peak_mb"))
        if on_progress:
            on_progress(1.0)
        outputs = result["outputs"]
        return StemPaths(vocals=Path(outputs["vocals"]), instrumental=Path(outputs["instrumental"]))

    @staticmethod
    def _to_error(run: RunnerResult) -> SeparationError:
        """실행기의 실패를 '사용자가 이해할 수 있는 문장'으로 바꾼다."""
        if is_memory_failure(run):
            return SeparationError(describe(run), "메모리가 부족해 보컬 분리에 실패했습니다. "
                                                  "다른 프로그램(브라우저 탭 등)을 닫고 다시 시도하세요.")
        return SeparationError(describe(run), "보컬 분리 중 오류가 발생했습니다. 서버 로그를 확인하세요.")
