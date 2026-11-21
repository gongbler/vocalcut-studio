"""믹스 요청 API (미리듣기 / 최종)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_engine, get_job_manager, get_workspace
from app.jobs.manager import JobManager, ProgressReporter
from app.schemas.job import JobOut
from app.services import media_service, mix_service
from app.services.engines.base import MediaEngine
from app.storage.workspace import Workspace

router = APIRouter(tags=["mixes"])


class TrackIn(BaseModel):
    file_id: str
    volume_db: float = 0.0
    offset_sec: float = 0.0
    eq_low_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_high_db: float = 0.0
    muted: bool = False


class MixRequest(BaseModel):
    tracks: list[TrackIn] = Field(min_length=1)
    start_sec: float = 0.0
    end_sec: float | None = None
    fade_in_sec: float = 0.0
    fade_out_sec: float = 0.0
    output_format: Literal["mp3", "wav"] = "mp3"
    preview: bool = False  # True 면 짧은 구간만 빠르게 (최대 30초)


@router.post("/mixes", response_model=JobOut, status_code=202)
def create_mix(
    req: MixRequest,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
    jobs: JobManager = Depends(get_job_manager),
) -> JobOut:
    """믹스 주문 → 번호표. 완료되면 result.output_id 로 결과물 조회 (편집 결과와 같은 형식)."""
    try:
        prepared = mix_service.prepare_mix(
            ws, engine,
            [mix_service.TrackSetting(**t.model_dump()) for t in req.tracks],
            start_sec=req.start_sec, end_sec=req.end_sec,
            fade_in_sec=req.fade_in_sec, fade_out_sec=req.fade_out_sec,
            output_format=req.output_format, preview=req.preview,
        )
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except mix_service.MixValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    def work(report: ProgressReporter) -> dict:
        report(0.0, "미리듣기 만드는 중" if req.preview else "믹싱 중")
        output = mix_service.run_mix(ws, engine, prepared, on_progress=lambda p: report(p, None))
        return {"output_id": output.id}

    job = jobs.submit("mix_preview" if req.preview else "mix", work)
    return JobOut.from_job(job)
