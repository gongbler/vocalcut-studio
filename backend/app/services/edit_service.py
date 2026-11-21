"""편집(자르기·볼륨·페이드) 담당 주방장.

순서: 원본 찾기 → 주문서 검사 → 결과물 폴더 준비 → 엔진에 렌더링 맡기기 → 결과 분석·기록
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.services import media_service
from app.services.engines.base import EditSpec, MediaEngine, MediaInfo, OnProgress, RenderError
from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)

VOLUME_DB_RANGE = (-30.0, 20.0)
MIN_LENGTH_SEC = 0.1

VIDEO_FORMATS = {"mp4"}
AUDIO_FORMATS = {"mp3", "wav"}
OUTPUT_FORMATS = VIDEO_FORMATS | AUDIO_FORMATS


class EditValidationError(Exception):
    """사용자가 입력한 편집 값이 잘못됨."""


class OutputNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class EditOutput:
    id: str
    source_id: str
    download_name: str  # 사용자에게 보여줄/저장될 이름 (예: 내 노래_edit.mp3)
    format: str         # "mp4" | "mp3" | "wav"
    path: Path
    info: MediaInfo


def resolve_format(requested: str | None, info: MediaInfo) -> str:
    """출력 형식을 정한다. 지정하지 않으면 영상→mp4, 오디오→mp3."""
    if requested is None:
        return "mp4" if info.has_video else "mp3"
    fmt = requested.lower()
    if fmt not in OUTPUT_FORMATS:
        raise EditValidationError(f"지원하지 않는 출력 형식입니다: {requested}")
    if fmt in VIDEO_FORMATS and not info.has_video:
        raise EditValidationError("오디오 파일은 MP4(영상)로 내보낼 수 없습니다. MP3 또는 WAV를 선택하세요.")
    if fmt in AUDIO_FORMATS and not info.has_audio:
        raise EditValidationError("소리가 없는 영상은 MP3/WAV로 내보낼 수 없습니다.")
    return fmt


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


@dataclass(frozen=True)
class PreparedEdit:
    """검사를 통과한 편집 주문. 이 상태로 작업 대기열에 넣는다."""
    source: media_service.MediaFile
    spec: EditSpec
    format: str


def prepare_edit(
    ws: Workspace,
    engine: MediaEngine,
    source_id: str,
    spec: EditSpec,
    output_format: str | None = None,
) -> PreparedEdit:
    """빠른 검사만 한다 (몇 밀리초). 잘못된 주문은 대기열에 넣기 '전에' 바로 거절하기 위함."""
    source = media_service.get_media(ws, engine, source_id)  # 없으면 MediaNotFoundError
    return PreparedEdit(
        source=source,
        spec=validate_spec(spec, source.info.duration_sec),
        format=resolve_format(output_format, source.info),
    )


def create_edit(
    ws: Workspace,
    engine: MediaEngine,
    source_id: str,
    spec: EditSpec,
    output_format: str | None = None,
) -> EditOutput:
    """검사 + 렌더링을 한 번에 (테스트·스크립트용)."""
    return run_edit(ws, engine, prepare_edit(ws, engine, source_id, spec, output_format))


def run_edit(
    ws: Workspace,
    engine: MediaEngine,
    prepared: PreparedEdit,
    on_progress: OnProgress | None = None,
) -> EditOutput:
    """실제 렌더링 (오래 걸림). 작업 대기열의 작업자 스레드에서 실행된다."""
    source, spec, fmt = prepared.source, prepared.spec, prepared.format
    source_id = source.id

    ext = f".{fmt}"
    stem = Path(source.original_name).stem or "output"
    download_name = f"{stem}_edit{ext}"

    output_id, out_dir = ws.create_output_dir()
    dst = out_dir / f"result{ext}"
    try:
        engine.render_edit(source.path, dst, spec, source.info, on_progress=on_progress)
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
        "format": fmt,
        "stored_name": dst.name,
        "spec": vars(spec),
    })
    return EditOutput(
        id=output_id, source_id=source_id, download_name=download_name,
        format=fmt, path=dst, info=info,
    )


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
        format=meta.get("format", path.suffix.lstrip(".")),  # 1-3 때 만든 결과물엔 format 이 없음
        path=path,
        info=engine.probe(path),
    )
