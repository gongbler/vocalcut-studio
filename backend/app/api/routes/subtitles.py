"""자막 API: 받아쓰기 주문 + 저장된 자막 읽기."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_engine, get_job_manager, get_transcriber, get_workspace
from app.jobs.manager import JobManager, ProgressReporter, UserFacingError
from app.schemas.job import JobOut
from app.services import media_service, subtitle_service
from app.services.engines.base import MediaEngine, TranscriberEngine, TranscriptionError, TranscriptSegment
from app.storage.workspace import Workspace

router = APIRouter(tags=["subtitles"])


class TranscriptionRequest(BaseModel):
    file_id: str
    model: str | None = None          # 없으면 엔진 기본값 (small)
    language: str = "auto"            # "auto" = 자동 감지 (기본값: 잘못 고르면 받아쓰기가 중간에 멈춘다)
    use_vocals: bool = True           # 분리된 보컬이 있으면 그걸로 받아 적기 (반주가 없어 더 정확)


class SubtitleLine(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class LanguageMismatch(BaseModel):
    chosen: str
    detected: str


class SubtitlesOut(BaseModel):
    language: str
    detected_language: str | None = None
    language_mismatch: LanguageMismatch | None = None
    model: str
    audio_source: str
    updated_at: float
    segments: list[SubtitleLine]


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


@router.post("/transcriptions", response_model=JobOut, status_code=202)
def create_transcription(
    req: TranscriptionRequest,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
    transcriber: TranscriberEngine = Depends(get_transcriber),
    jobs: JobManager = Depends(get_job_manager),
) -> JobOut:
    """자동 자막 주문 → 번호표. 완료되면 result = {"file_id", "lines", "language"}."""
    status = transcriber.availability()
    if not status.ok:
        raise HTTPException(status_code=503, detail=status.reason)
    try:
        prepared = subtitle_service.prepare(
            ws, engine, transcriber, req.file_id, req.model, req.language, req.use_vocals
        )
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except subtitle_service.SubtitleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    def work(report: ProgressReporter) -> dict:
        last = {"progress": 0.0, "label": "준비 중"}

        def on_progress(p: float) -> None:
            last["progress"] = p
            report(p, None)

        def on_stage(label: str) -> None:
            last["label"] = label
            report(last["progress"], label)

        def on_segment(seg: TranscriptSegment) -> None:
            # 방금 받아 적은 줄을 진행 상황에 보여준다 → 기다리는 동안 '잘 되고 있는지' 바로 보인다
            report(last["progress"], f"받아 적는 중 · “{_short(seg.text)}”")

        report(0.0, "준비 중")
        try:
            return subtitle_service.run(ws, transcriber, prepared, on_progress, on_stage, on_segment)
        except TranscriptionError as e:
            raise UserFacingError(e.user_message) from e

    job = jobs.submit("transcribe", work, extra={"file_id": prepared.target.id, "model": prepared.model})
    return JobOut.from_job(job)


@router.get("/files/{file_id}/subtitles", response_model=SubtitlesOut)
def read_subtitles(file_id: str, ws: Workspace = Depends(get_workspace)) -> dict:
    try:
        data = subtitle_service.get_subtitles(ws, file_id)
    except media_service.MediaNotFoundError:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    if data is None:
        raise HTTPException(status_code=404, detail="아직 자막이 없습니다.")
    return data
