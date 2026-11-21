"""보컬/MR 분리 담당 주방장.

순서: 원본 확인 → (이미 분리한 적 있으면 그 결과 재사용) → 엔진에 분리 맡기기
      → 결과 2개를 '일반 파일'로 등록 → 원본 메타에 결과 id 기록(캐시)
"""
from __future__ import annotations

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
        stems = separator.separate(source.path, work_dir, on_progress=on_progress, on_stage=on_stage)
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
