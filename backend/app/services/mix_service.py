"""믹싱 담당 주방장.

순서: 트랙 파일 확인 → 설정값 검사 → (대기열에서) 엔진에 믹스 렌더링 맡기기 → 결과물 등록
결과물은 편집 결과와 같은 형식(outputs/<id>)으로 저장해서, 재생·다운로드 기능을 그대로 쓴다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.services import edit_service, media_service
from app.services.engines.base import MediaEngine, MixSpec, MixTrack, OnProgress, RenderError
from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)

MAX_TRACKS = 6
VOLUME_RANGE = (-30.0, 12.0)
EQ_RANGE = (-12.0, 12.0)
OFFSET_RANGE = (-30.0, 30.0)
MIX_FORMATS = {"mp3", "wav"}
PREVIEW_MAX_SEC = 30.0


class MixValidationError(Exception):
    pass


@dataclass(frozen=True)
class TrackSetting:
    """화면에서 받은 트랙 설정 (파일은 id 로 가리킨다)."""
    file_id: str
    volume_db: float = 0.0
    offset_sec: float = 0.0
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_high_db: float = 0.0
    muted: bool = False


@dataclass(frozen=True)
class PreparedMix:
    spec: MixSpec
    format: str
    download_name: str
    first_source_id: str


def _check(value: float, rng: tuple[float, float], label: str) -> None:
    lo, hi = rng
    if not lo <= value <= hi:
        raise MixValidationError(f"{label}은(는) {lo:g} ~ {hi:g} 사이로 설정하세요.")


def prepare_mix(
    ws: Workspace,
    engine: MediaEngine,
    settings: list[TrackSetting],
    start_sec: float = 0.0,
    end_sec: float | None = None,
    fade_in_sec: float = 0.0,
    fade_out_sec: float = 0.0,
    output_format: str = "mp3",
    preview: bool = False,
) -> PreparedMix:
    """빠른 검사만 한다 (대기열에 넣기 전에). 잘못된 값은 바로 422."""
    if output_format not in MIX_FORMATS:
        raise MixValidationError("믹스는 MP3 또는 WAV로 내보낼 수 있습니다.")
    if not settings:
        raise MixValidationError("트랙이 없습니다.")
    if len(settings) > MAX_TRACKS:
        raise MixValidationError(f"트랙은 최대 {MAX_TRACKS}개까지 섞을 수 있습니다.")

    tracks: list[MixTrack] = []
    names: list[str] = []
    for s in settings:
        media = media_service.get_media(ws, engine, s.file_id)  # 없으면 MediaNotFoundError
        if not media.info.has_audio:
            raise MixValidationError(f"'{media.original_name}'에는 소리가 없습니다.")
        _check(s.volume_db, VOLUME_RANGE, "볼륨(dB)")
        _check(s.offset_sec, OFFSET_RANGE, "싱크(초)")
        for v in (s.eq_low_db, s.eq_mid_db, s.eq_high_db):
            _check(v, EQ_RANGE, "EQ(dB)")
        if s.offset_sec < 0 and -s.offset_sec >= media.info.duration_sec:
            raise MixValidationError(f"'{media.original_name}'을(를) 길이보다 더 많이 당길 수 없습니다.")
        if s.muted:
            continue  # 음소거 트랙은 아예 섞지 않는다 (처리 시간도 절약)
        tracks.append(MixTrack(
            path=media.path, duration_sec=media.info.duration_sec, volume_db=s.volume_db,
            offset_sec=s.offset_sec, eq_low_db=s.eq_low_db, eq_mid_db=s.eq_mid_db, eq_high_db=s.eq_high_db,
        ))
        names.append(_song_name(ws, engine, media))

    if not tracks:
        raise MixValidationError("모든 트랙이 음소거되어 있습니다.")

    spec = MixSpec(tracks=tuple(tracks), start_sec=start_sec, end_sec=end_sec,
                   fade_in_sec=fade_in_sec, fade_out_sec=fade_out_sec)
    total = spec.mix_length
    end = total if end_sec is None else end_sec
    if start_sec < 0 or end > total + 0.05:
        raise MixValidationError(f"구간은 0 ~ {total:.2f}초 안에서 정하세요.")
    end = min(end, total)
    length = end - start_sec
    if length < 0.1:
        raise MixValidationError("끝 시간은 시작 시간보다 0.1초 이상 뒤여야 합니다.")
    if preview and length > PREVIEW_MAX_SEC:
        raise MixValidationError(f"미리듣기는 최대 {PREVIEW_MAX_SEC:g}초까지 가능합니다.")
    if fade_in_sec < 0 or fade_out_sec < 0 or fade_in_sec + fade_out_sec > length:
        raise MixValidationError("페이드 인+아웃이 믹스 구간보다 깁니다.")

    spec = MixSpec(tracks=spec.tracks, start_sec=start_sec, end_sec=end,
                   fade_in_sec=fade_in_sec, fade_out_sec=fade_out_sec)
    suffix = "_preview" if preview else "_mix"
    return PreparedMix(spec=spec, format=output_format,
                       download_name=f"{names[0]}{suffix}.{output_format}",
                       first_source_id=settings[0].file_id)


def _song_name(ws: Workspace, engine: MediaEngine, media: media_service.MediaFile) -> str:
    """'내 커버곡 (보컬).wav' 같은 분리 트랙이면 원곡 이름('내 커버곡')을 쓴다."""
    if media.derived_from:
        try:
            return Path(media_service.get_media(ws, engine, media.derived_from).original_name).stem
        except media_service.MediaNotFoundError:
            pass
    return Path(media.original_name).stem or "mix"


def run_mix(
    ws: Workspace,
    engine: MediaEngine,
    prepared: PreparedMix,
    on_progress: OnProgress | None = None,
) -> edit_service.EditOutput:
    """실제 믹스 렌더링. 작업 대기열의 작업자 스레드에서 실행된다."""
    output_id, out_dir = ws.create_output_dir()
    dst = out_dir / f"result.{prepared.format}"
    try:
        engine.render_mix(dst, prepared.spec, on_progress=on_progress)
        info = engine.probe(dst)
    except RenderError:
        logger.exception("mix render failed")
        ws.remove_output(output_id)
        raise
    except Exception:
        ws.remove_output(output_id)
        raise

    ws.write_meta(out_dir, {
        "source_id": prepared.first_source_id,
        "download_name": prepared.download_name,
        "format": prepared.format,
        "stored_name": dst.name,
        "kind": "mix",
    })
    return edit_service.EditOutput(
        id=output_id, source_id=prepared.first_source_id, download_name=prepared.download_name,
        format=prepared.format, path=dst, info=info,
    )
