"""자막 API: 받아쓰기 주문 + 저장된 자막 읽기."""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.deps import get_engine, get_job_manager, get_transcriber, get_workspace
from app.jobs.manager import JobManager, ProgressReporter, UserFacingError
from app.schemas.job import JobOut
from app.services import disk_guard, media_service, subtitle_service
from app.services.engines.base import MediaEngine, RenderError, TranscriberEngine, TranscriptionError, TranscriptSegment
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
    edited: bool = False              # 사용자가 편집기에서 고친 적이 있는지
    segments: list[SubtitleLine]


class SubtitleLineIn(BaseModel):
    id: str | None = None             # 새로 추가한 줄은 없어도 된다
    start: float
    end: float
    text: str = Field(max_length=1000)


class SubtitlesIn(BaseModel):
    segments: list[SubtitleLineIn]


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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except subtitle_service.SubtitleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

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
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.") from None
    if data is None:
        raise HTTPException(status_code=404, detail="아직 자막이 없습니다.")
    return data


@router.put("/files/{file_id}/subtitles", response_model=SubtitlesOut)
def save_subtitles(
    file_id: str,
    body: SubtitlesIn,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> dict:
    """편집기에서 고친 자막 저장 (줄 전체를 통째로 바꾼다)."""
    try:
        return subtitle_service.update_lines(ws, engine, file_id, [line.model_dump() for line in body.segments])
    except media_service.MediaNotFoundError:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.") from None
    except subtitle_service.SubtitleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e



@router.get("/files/{file_id}/subtitles.srt")
def download_srt(
    file_id: str, ws: Workspace = Depends(get_workspace), engine: MediaEngine = Depends(get_engine)
) -> Response:
    """저장된 자막을 SRT 파일로 내려받기."""
    try:
        content, name = subtitle_service.export_srt(ws, engine, file_id)
    except media_service.MediaNotFoundError:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.") from None
    except subtitle_service.SubtitleValidationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    # 한글 파일 이름은 filename*=UTF-8''... 형식으로 보내야 깨지지 않는다 (filename 에는 영어 대체 이름)
    disposition = f"attachment; filename=\"subtitles.srt\"; filename*=UTF-8''{quote(name)}"
    return Response(content, media_type="application/x-subrip; charset=utf-8",
                    headers={"Content-Disposition": disposition})


class BurnRequest(BaseModel):
    file_id: str
    size: Literal["small", "medium", "large"] = "medium"
    position: Literal["bottom", "middle", "top"] = "bottom"


@router.post("/subtitle-renders", response_model=JobOut, status_code=202)
def create_burn(
    req: BurnRequest,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
    jobs: JobManager = Depends(get_job_manager),
) -> JobOut:
    """자막을 영상에 입히기 주문 → 번호표. 완료되면 result.output_id (편집 결과와 같은 형식)."""
    try:
        prepared = subtitle_service.prepare_burn(ws, engine, req.file_id, req.size, req.position)
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except subtitle_service.SubtitleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    media = prepared.media
    disk_guard.require_free_space(ws.root, disk_guard.render_bytes(media.info.duration_sec, media.info.size_bytes),
                                  "자막 입히기")

    def work(report: ProgressReporter) -> dict:
        report(0.0, "자막 입히는 중")
        try:
            output = subtitle_service.run_burn(ws, engine, prepared, on_progress=lambda p: report(p, None))
        except RenderError as e:
            raise UserFacingError("자막을 입히지 못했습니다. 서버 로그를 확인하세요.") from e
        return {"output_id": output.id}

    job = jobs.submit("burn_subtitles", work, extra={"file_id": req.file_id})
    return JobOut.from_job(job)
