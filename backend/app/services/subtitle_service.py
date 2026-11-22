"""자막 담당 주방장.

순서: 대상 파일 확인 → (분리된 보컬이 있으면 그걸로) 받아쓰기 맡기기 → 결과를 subtitles.json 으로 저장

자막은 '대상 파일'(예: 내 영상) 폴더에 저장한다.
보컬 트랙으로 받아 적어도 시간축이 원곡과 똑같기 때문에, 자막 시간은 그대로 영상에 맞는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core import config
from app.services import media_service
from app.services.engines.base import (
    MediaEngine,
    OnProgress,
    TranscriberEngine,
    TranscriptionError,
    TranscriptSegment,
)
from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)

SUBTITLES_FILE = "subtitles.json"
LANGUAGE_RE = re.compile(r"^(auto|[a-z]{2,3})$")
MAX_LINE_CHARS = 30  # 화면 한 줄에 읽기 편한 길이 (이보다 긴 줄은 문장 단위로 나눈다)
SENTENCE_END_RE = re.compile(r"(?<=[.?!。？！…])\s+")


class SubtitleValidationError(Exception):
    pass


@dataclass(frozen=True)
class PreparedTranscription:
    target: media_service.MediaFile  # 자막이 붙을 파일
    audio_path: Path                 # 실제로 AI 에게 들려줄 소리 (보컬 트랙일 수 있음)
    audio_source: str                # "vocals" | "original" (화면 안내용)
    model: str
    language: str | None             # None = 자동 감지


def _vocals_of(ws: Workspace, engine: MediaEngine, target: media_service.MediaFile) -> Path | None:
    """대상 파일의 '분리된 보컬' 경로 (없으면 None)."""
    if target.stem == "vocals":
        return target.path
    vocals_id = (media_service.read_meta(ws, target.id).get("stems") or {}).get("vocals")
    if not vocals_id:
        return None
    try:
        return media_service.get_media(ws, engine, vocals_id).path
    except media_service.MediaNotFoundError:
        return None  # 보컬 파일이 지워졌으면 원본으로


def prepare(
    ws: Workspace,
    engine: MediaEngine,
    transcriber: TranscriberEngine,
    file_id: str,
    model: str | None,
    language: str,
    use_vocals: bool,
) -> PreparedTranscription:
    """빠른 검사 (대기열에 넣기 전에)."""
    target = media_service.get_media(ws, engine, file_id)  # 없으면 MediaNotFoundError
    if not target.info.has_audio:
        raise SubtitleValidationError("소리 트랙이 없는 파일은 받아 적을 수 없습니다.")
    model = model or transcriber.default_model
    if model not in transcriber.models:
        raise SubtitleValidationError(f"알 수 없는 모델입니다: {model}")
    if not LANGUAGE_RE.match(language):
        raise SubtitleValidationError(f"언어 코드가 올바르지 않습니다: {language}")

    vocals = _vocals_of(ws, engine, target) if use_vocals else None
    return PreparedTranscription(
        target=target,
        audio_path=vocals or target.path,
        audio_source="vocals" if vocals else "original",
        model=model,
        language=None if language == "auto" else language,
    )


def split_long_segment(seg: TranscriptSegment, max_chars: int = MAX_LINE_CHARS) -> list[TranscriptSegment]:
    """한 줄에 문장이 여러 개 붙어 있으면 문장마다 나눈다.

    Whisper 는 8초짜리 줄에 두 문장을 몰아 넣는 일이 많다 → 자막으로 읽기 힘들다.
    시간은 '글자 수 비율'로 나눈다 (말하는 속도가 대체로 일정하다고 보는 근사값 → 어긋나면 편집기에서 고친다).
    """
    if len(seg.text) <= max_chars:
        return [seg]
    parts = [p for p in SENTENCE_END_RE.split(seg.text) if p.strip()]
    if len(parts) < 2:
        return [seg]
    total = sum(len(p) for p in parts)
    out, t = [], seg.start
    for i, part in enumerate(parts):
        end = seg.end if i == len(parts) - 1 else t + (seg.end - seg.start) * len(part) / total
        out.append(TranscriptSegment(round(t, 2), round(end, 2), part.strip()))
        t = end
    return out


def _segment_out(seg: TranscriptSegment) -> dict:
    # id: 화면 편집기에서 줄을 구분하는 이름표 (줄을 지우거나 끼워 넣어도 안 섞이게)
    return {"id": uuid.uuid4().hex[:12], "start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text}


def save_subtitles(ws: Workspace, file_id: str, data: dict) -> None:
    """임시 파일에 다 쓴 뒤 바꿔치기 → 저장 도중 꺼져도 반쯤 쓰인 파일이 남지 않는다."""
    upload_dir = ws.upload_dir(file_id)
    if upload_dir is None:
        raise media_service.MediaNotFoundError(file_id)
    tmp = upload_dir / (SUBTITLES_FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, upload_dir / SUBTITLES_FILE)


def get_subtitles(ws: Workspace, file_id: str) -> dict | None:
    upload_dir = ws.upload_dir(file_id)
    if upload_dir is None:
        raise media_service.MediaNotFoundError(file_id)
    path = upload_dir / SUBTITLES_FILE
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run(
    ws: Workspace,
    transcriber: TranscriberEngine,
    job: PreparedTranscription,
    on_progress: OnProgress | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_segment: Callable[[TranscriptSegment], None] | None = None,
) -> dict:
    """실제 받아쓰기 (곡 길이의 0.3~0.8배). 작업 대기열의 작업자 스레드에서 실행된다."""
    try:
        transcript = transcriber.transcribe(
            job.audio_path, job.model, job.language,
            on_progress=on_progress, on_stage=on_stage, on_segment=on_segment,
            isolated_voice=job.audio_source == "vocals",
        )
    except TranscriptionError:
        logger.exception("transcription failed for %s", job.target.id)
        raise
    mismatch = language_mismatch(job.language, transcript.detected_language, transcript.detected_probability)
    data = {
        "language": transcript.language,
        "detected_language": transcript.detected_language,
        "language_mismatch": mismatch,
        "model": job.model,
        "audio_source": job.audio_source,
        "updated_at": time.time(),
        "segments": [_segment_out(p) for s in transcript.segments for p in split_long_segment(s)],
    }
    save_subtitles(ws, job.target.id, data)
    return {"file_id": job.target.id, "lines": len(data["segments"]), "language": transcript.language}


def language_mismatch(chosen: str | None, detected: str | None, probability: float) -> dict | None:
    """사용자가 고른 언어와 실제 언어가 확실히 다르면 {"chosen", "detected"} (화면 경고용)."""
    if chosen is None or detected is None or chosen == detected:
        return None
    if probability < config.LANGUAGE_MISMATCH_PROB:
        return None  # AI 도 확신이 없으면 괜히 경고하지 않는다
    return {"chosen": chosen, "detected": detected}


# ---------- 사용자가 고친 자막 저장 ----------

MAX_LINES = 2000
MAX_TEXT_CHARS = 200
END_TOLERANCE_SEC = 0.5  # 마지막 줄이 곡 길이를 살짝 넘는 정도는 허용 (AI 시간도 이 정도는 어긋난다)


def update_lines(ws: Workspace, engine: MediaEngine, file_id: str, lines: list[dict]) -> dict:
    """편집기에서 고친 자막 줄들을 검사한 뒤 저장한다. (AI 정보 = 언어·모델은 그대로 둔다)

    lines: [{"id": 선택, "start": 초, "end": 초, "text": 글자}, ...]
    """
    media = media_service.get_media(ws, engine, file_id)  # 없으면 MediaNotFoundError
    if len(lines) > MAX_LINES:
        raise SubtitleValidationError(f"자막은 최대 {MAX_LINES}줄까지 저장할 수 있어요.")
    limit = media.info.duration_sec + END_TOLERANCE_SEC

    cleaned = []
    # 시간 순서로 정렬해서 검사 → 오류 메시지의 'N번째 줄'이 화면 순서와 같다
    for n, line in enumerate(sorted(lines, key=lambda x: (x["start"], x["end"])), start=1):
        text = " ".join(str(line["text"]).split())  # 앞뒤 공백·여러 칸 공백·줄바꿈 정리
        start, end = round(float(line["start"]), 2), round(float(line["end"]), 2)
        if not text:
            raise SubtitleValidationError(f"{n}번째 줄({start:g}초)이 비어 있어요. 글자를 넣거나 줄을 삭제하세요.")
        if len(text) > MAX_TEXT_CHARS:
            raise SubtitleValidationError(f"{n}번째 줄이 너무 길어요 (최대 {MAX_TEXT_CHARS}자). 줄을 나눠 주세요.")
        if start < 0 or end <= start:
            raise SubtitleValidationError(f"{n}번째 줄의 시간이 올바르지 않아요 (끝 시간이 시작보다 뒤여야 해요).")
        if end > limit:
            raise SubtitleValidationError(f"{n}번째 줄이 곡 길이({media.info.duration_sec:.1f}초)를 넘어요.")
        line_id = str(line.get("id") or "")
        if not re.fullmatch(r"[0-9a-f]{1,32}", line_id):
            line_id = uuid.uuid4().hex[:12]  # 새로 추가한 줄은 서버가 이름표를 붙인다
        cleaned.append({"id": line_id, "start": start, "end": end, "text": text})

    previous = get_subtitles(ws, file_id) or {
        # AI 없이 처음부터 손으로 만든 자막
        "language": "", "detected_language": None, "language_mismatch": None,
        "model": "manual", "audio_source": "manual",
    }
    data = {**previous, "segments": cleaned, "updated_at": time.time(), "edited": True}
    save_subtitles(ws, file_id, data)
    return data
