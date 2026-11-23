"""미디어 파일 가져오기/조회 담당 = '주방장'.

순서를 조립하는 역할만 한다:
  확장자 확인 → 창고에 저장 → 엔진으로 분석 → 메타 정보 기록
실제 저장은 Workspace 에게, 실제 분석은 MediaEngine 에게 맡긴다.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from app.core import config
from app.services.engines.base import MediaEngine, MediaInfo, MediaProbeError, Peaks
from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)


class UnsupportedFileError(Exception):
    pass


class MediaNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class MediaFile:
    id: str
    original_name: str
    path: Path
    info: MediaInfo
    derived_from: str | None = None  # AI 분리로 만들어진 파일이면 원곡의 id
    stem: str | None = None          # "vocals" | "instrumental"


def register_file(
    ws: Workspace,
    engine: MediaEngine,
    src: Path,
    display_name: str,
    extra_meta: dict | None = None,
) -> MediaFile:
    """서버가 만든 파일(예: 분리된 보컬)을 '업로드된 파일'과 똑같이 등록한다.

    → 등록만 하면 파형·자르기·다운로드 등 기존 기능을 그대로 쓸 수 있다.
    """
    file_id, upload_dir = ws.create_upload_dir()
    dest = upload_dir / f"source{src.suffix.lower()}"
    try:
        shutil.move(str(src), dest)
        info = engine.probe(dest)
    except Exception:
        ws.remove_upload(file_id)
        raise
    meta = {"original_name": display_name, "stored_name": dest.name, **_list_info(info), **(extra_meta or {})}
    ws.write_meta(upload_dir, meta)
    return MediaFile(id=file_id, original_name=display_name, path=dest, info=info,
                     derived_from=meta.get("derived_from"), stem=meta.get("stem"))


def _list_info(info: MediaInfo) -> dict:
    """'내 파일' 목록에 보여줄 정보. 목록을 열 때마다 파일을 다시 분석하지 않도록 meta 에 미리 적는다."""
    return {"created_at": time.time(), "kind": "video" if info.has_video else "audio",
            "duration_sec": info.duration_sec}


def read_meta(ws: Workspace, file_id: str) -> dict:
    upload_dir = ws.upload_dir(file_id)
    meta = ws.read_meta(upload_dir) if upload_dir else None
    if not meta:
        raise MediaNotFoundError(f"파일을 찾을 수 없습니다: {file_id}")
    return meta


def update_meta(ws: Workspace, file_id: str, **fields) -> None:
    upload_dir = ws.upload_dir(file_id)
    if not upload_dir:
        raise MediaNotFoundError(f"파일을 찾을 수 없습니다: {file_id}")
    ws.write_meta(upload_dir, {**read_meta(ws, file_id), **fields})


def import_upload(
    ws: Workspace,
    engine: MediaEngine,
    filename: str,
    stream: BinaryIO,
    max_bytes: int = config.MAX_UPLOAD_BYTES,
) -> MediaFile:
    ext = Path(filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXTS:
        allowed = ", ".join(sorted(config.ALLOWED_EXTS))
        raise UnsupportedFileError(f"지원하지 않는 파일 형식입니다: '{ext or '없음'}' (허용: {allowed})")

    file_id, upload_dir = ws.create_upload_dir()
    # 저장 이름은 항상 source.<확장자>. 사용자가 보낸 파일 이름은 경로에 쓰지 않는다(보안).
    dest = upload_dir / f"source{ext}"
    try:
        ws.save_stream(stream, dest, max_bytes)
        info = engine.probe(dest)  # 확장자만 mp3고 내용은 가짜인 파일도 여기서 걸러진다
    except MediaProbeError as e:
        ws.remove_upload(file_id)
        # 기술적인 원인(서버 내부 경로 포함)은 서버 로그에만 남기고,
        # 사용자에게는 '사용자가 올린 파일 이름'으로 이해하기 쉬운 문장만 보여준다.
        logger.warning("probe failed for upload %r: %s", filename, e)
        raise MediaProbeError(
            f"'{filename}' 파일을 읽을 수 없습니다. 손상되었거나 확장자와 실제 형식이 다른 파일일 수 있어요."
        ) from e
    except Exception:
        ws.remove_upload(file_id)  # 실패하면 반쯤 저장된 파일을 치운다
        raise

    ws.write_meta(upload_dir, {"original_name": filename, "stored_name": dest.name, **_list_info(info)})
    return MediaFile(id=file_id, original_name=filename, path=dest, info=info)


MAX_PEAKS_PER_SEC = 50     # 1초에 50개 = 0.02초 단위 → 노래 편집에 충분히 세밀함
MAX_TOTAL_PEAKS = 30_000   # 아주 긴 파일도 응답이 수백 KB를 넘지 않도록 상한
PEAKS_CACHE_NAME = "peaks.json"


def get_peaks(ws: Workspace, engine: MediaEngine, file_id: str) -> Peaks:
    """파형 데이터. 처음 한 번만 계산하고 파일로 저장해 두었다가(캐시) 다음부터는 바로 돌려준다."""
    media = get_media(ws, engine, file_id)
    if not media.info.has_audio:
        raise MediaProbeError("소리 트랙이 없는 파일이라 파형을 그릴 수 없습니다.")

    cache = media.path.parent / PEAKS_CACHE_NAME
    if cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        return Peaks(**data)

    duration = max(media.info.duration_sec, 0.001)
    peaks_per_sec = min(MAX_PEAKS_PER_SEC, MAX_TOTAL_PEAKS / duration)
    peaks = engine.extract_peaks(media.path, peaks_per_sec)
    cache.write_text(json.dumps(asdict(peaks)), encoding="utf-8")
    return peaks


def get_media(ws: Workspace, engine: MediaEngine, file_id: str) -> MediaFile:
    upload_dir = ws.upload_dir(file_id)
    meta = ws.read_meta(upload_dir) if upload_dir else None
    if not meta:
        raise MediaNotFoundError(f"파일을 찾을 수 없습니다: {file_id}")

    path = upload_dir / meta["stored_name"]
    return MediaFile(
        id=file_id,
        original_name=meta["original_name"],
        path=path,
        info=engine.probe(path),
        derived_from=meta.get("derived_from"),
        stem=meta.get("stem"),
    )
