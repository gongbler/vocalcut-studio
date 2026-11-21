"""편집(자르기·볼륨·페이드) 담당 주방장.

순서: 원본 찾기 → 주문서 검사 → 결과물 폴더 준비 → 엔진에 렌더링 맡기기 → 결과 분석·기록
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.services import media_service
from app.services.engines.base import EditSpec, MediaEngine, MediaInfo, RenderError
from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)

VOLUME_DB_RANGE = (-30.0, 20.0)
MIN_LENGTH_SEC = 0.1


class EditValidationError(Exception):
    """사용자가 입력한 편집 값이 잘못됨."""


class OutputNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class EditOutput:
    id: str
    source_id: str
    download_name: str  # 사용자에게 보여줄/저장될 이름 (예: 내 노래_edit.mp3)
    path: Path
    info: MediaInfo


def validate_spec(spec: EditSpec, duration: float) -> EditSpec:
    """주문서가 원본 길이에 맞는지 검사하고, end_sec 가 비어 있으면 끝으로 채운다."""
    end = duration if spec.end_sec is None else spec.end_sec

    if spec.start_sec < 0:
        raise EditValidationError("시작 시간은 0초 이상이어야 합니다.")
    if end > duration + 0.05:  # 0.05초 정도의 반올림 오차는 봐준다
        raise EditValidationError(f"끝 시간이 파일 길이({duration:.2f}초)보다 깁니다.")
    end = min(end, duration)
    length = end - spec.start_sec
    if length < MIN_LENGTH_SEC:
        raise EditValidationError("끝 시간은 시작 시간보다 0.1초 이상 뒤여야 합니다.")

    lo, hi = VOLUME_DB_RANGE
    if not lo <= spec.volume_db <= hi:
        raise EditValidationError(f"볼륨은 {lo:g}dB ~ +{hi:g}dB 사이로 설정하세요.")
    if spec.fade_in_sec < 0 or spec.fade_out_sec < 0:
        raise EditValidationError("페이드 시간은 0초 이상이어야 합니다.")
    if spec.fade_in_sec + spec.fade_out_sec > length:
        raise EditValidationError(
            f"페이드 인+아웃({spec.fade_in_sec + spec.fade_out_sec:g}초)이 "
            f"자른 구간 길이({length:.2f}초)보다 깁니다."
        )

    return EditSpec(
        start_sec=spec.start_sec,
        end_sec=end,
        volume_db=spec.volume_db,
        fade_in_sec=spec.fade_in_sec,
        fade_out_sec=spec.fade_out_sec,
    )


def create_edit(ws: Workspace, engine: MediaEngine, source_id: str, spec: EditSpec) -> EditOutput:
    source = media_service.get_media(ws, engine, source_id)  # 없으면 MediaNotFoundError
    spec = validate_spec(spec, source.info.duration_sec)

    # 출력 형식: 영상이면 MP4, 오디오면 MP3 (형식 선택은 1-4에서 추가)
    ext = ".mp4" if source.info.has_video else ".mp3"
    stem = Path(source.original_name).stem or "output"
    download_name = f"{stem}_edit{ext}"

    output_id, out_dir = ws.create_output_dir()
    dst = out_dir / f"result{ext}"
    try:
        engine.render_edit(source.path, dst, spec, source.info)
        info = engine.probe(dst)
    except RenderError:
        logger.exception("render failed for source %s", source_id)
        ws.remove_output(output_id)
        raise
    except Exception:
        ws.remove_output(output_id)
        raise

    ws.write_meta(out_dir, {
        "source_id": source_id,
        "download_name": download_name,
        "stored_name": dst.name,
        "spec": vars(spec),
    })
    return EditOutput(id=output_id, source_id=source_id, download_name=download_name, path=dst, info=info)


def get_output(ws: Workspace, engine: MediaEngine, output_id: str) -> EditOutput:
    out_dir = ws.output_dir(output_id)
    meta = ws.read_meta(out_dir) if out_dir else None
    if not meta:
        raise OutputNotFoundError(f"결과물을 찾을 수 없습니다: {output_id}")
    path = out_dir / meta["stored_name"]
    return EditOutput(
        id=output_id,
        source_id=meta["source_id"],
        download_name=meta["download_name"],
        path=path,
        info=engine.probe(path),
    )
