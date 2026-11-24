"""보컬/MR 분리 담당 주방장.

순서: 원본 확인 → (이미 분리한 적 있으면 그 결과 재사용) → 엔진에 분리 맡기기
      → 결과 2개를 '일반 파일'로 등록 → 원본 메타에 결과 id 기록(캐시)
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from app.services import media_service
from app.services.engines.base import MediaEngine, OnProgress, SeparationError, SeparatorEngine
from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)

STEM_LABELS = {"vocals": "보컬", "instrumental": "MR"}


class SeparationValidationError(Exception):
    pass


def remove_dir_with_retry(path: Path, attempts: int = 10, delay: float = 0.3) -> None:
    """폴더 삭제. 윈도우는 프로세스가 끝난 직후 잠깐 파일을 잠가 두므로 몇 번 다시 시도한다."""
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(delay)
    logger.warning("could not remove temp dir: %s", path)


# ---------- 처리 속도 기록 (예상 시간을 '이 PC의 실제 기록'으로 계산하기 위함) ----------

SPEED_FILE = "separation_speed.json"
SPEED_KEEP = 10  # 최근 10번만 기억 (PC 상태가 바뀌면 자연스럽게 새 기록으로 교체)


def record_speed(ws: Workspace, elapsed: float, audio_sec: float) -> None:
    """이번 분리가 '곡 길이의 몇 배' 걸렸는지 저장한다."""
    if audio_sec < 30:  # 짧은 곡은 모델 불러오는 시간 비중이 커서(실측 10초 곡 3.7~3.9배) 기준으로 부적절
        return
    path = ws.shared_root / SPEED_FILE
    try:
        ratios = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ratios = []
    ratios = (ratios + [round(elapsed / audio_sec, 3)])[-SPEED_KEEP:]
    path.write_text(json.dumps(ratios), encoding="utf-8")


def speed_ratio(ws: Workspace) -> float | None:
    """최근 기록의 중앙값 (기록이 없으면 None). 중앙값은 한 번 유난히 느렸던 기록에 덜 흔들린다."""
    try:
        ratios = sorted(json.loads((ws.shared_root / SPEED_FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    if not ratios:
        return None
    mid = len(ratios) // 2
    return ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2


def prepare(ws: Workspace, engine: MediaEngine, source_id: str) -> media_service.MediaFile:
    """빠른 검사 (대기열에 넣기 전에)."""
    source = media_service.get_media(ws, engine, source_id)  # 없으면 MediaNotFoundError
    if not source.info.has_audio:
        raise SeparationValidationError("소리 트랙이 없는 파일은 분리할 수 없습니다.")
    if source.stem:
        raise SeparationValidationError("이미 분리된 트랙입니다. 원곡에서 분리하세요.")
    return source


def cached_stems(ws: Workspace, engine: MediaEngine, source_id: str) -> dict[str, str] | None:
    """이전에 분리한 결과가 아직 남아 있으면 그 id 들을 돌려준다 (10분 넘는 작업을 반복하지 않기 위해)."""
    stems = media_service.read_meta(ws, source_id).get("stems")
    if not stems:
        return None
    for file_id in stems.values():
        try:
            media_service.get_media(ws, engine, file_id)
        except media_service.MediaNotFoundError:
            return None  # 결과 파일이 지워졌으면 다시 분리
    return stems


def run(
    ws: Workspace,
    engine: MediaEngine,
    separator: SeparatorEngine,
    source: media_service.MediaFile,
    on_progress: OnProgress | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """실제 분리 (오래 걸림). 작업 대기열의 작업자 스레드에서 실행된다.

    반환: {"vocals": <file_id>, "instrumental": <file_id>}
    """
    cached = cached_stems(ws, engine, source.id)
    if cached:
        return cached

    work_dir = ws.temp / f"sep_{uuid.uuid4().hex}"
    work_dir.mkdir(parents=True)
    try:
        started = time.monotonic()
        stems = separator.separate(source.path, work_dir, on_progress=on_progress, on_stage=on_stage)
        record_speed(ws, elapsed=time.monotonic() - started, audio_sec=source.info.duration_sec)
        base = Path(source.original_name).stem or "track"
        ids: dict[str, str] = {}
        try:
            for key, path in (("vocals", stems.vocals), ("instrumental", stems.instrumental)):
                media = media_service.register_file(
                    ws, engine, path, f"{base} ({STEM_LABELS[key]}).wav",
                    extra_meta={"derived_from": source.id, "stem": key},
                )
                ids[key] = media.id
        except Exception:
            for file_id in ids.values():  # 둘 중 하나만 등록된 어중간한 상태를 남기지 않는다
                ws.remove_upload(file_id)
            raise
    except SeparationError:
        logger.exception("separation failed for %s", source.id)
        raise
    finally:
        remove_dir_with_retry(work_dir)  # 실패·취소돼도 임시 파일은 치운다

    media_service.update_meta(ws, source.id, stems=ids)
    return ids
