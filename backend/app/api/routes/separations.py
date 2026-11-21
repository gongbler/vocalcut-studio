"""보컬/MR 분리 요청 API."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_engine, get_job_manager, get_separator, get_workspace
from app.jobs.manager import JobManager, ProgressReporter, UserFacingError
from app.schemas.job import JobOut
from app.services import media_service, separation_service
from app.services.engines.base import MediaEngine, SeparationError, SeparatorEngine
from app.storage.workspace import Workspace

router = APIRouter(tags=["separations"])


class SeparationRequest(BaseModel):
    source_id: str


@router.post("/separations", response_model=JobOut, status_code=202)
def create_separation(
    req: SeparationRequest,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
    separator: SeparatorEngine = Depends(get_separator),
    jobs: JobManager = Depends(get_job_manager),
) -> JobOut:
    """보컬/MR 분리 주문 → 번호표. 완료되면 result = {"vocals": id, "instrumental": id}."""
    status = separator.availability()
    if not status.ok:
        raise HTTPException(status_code=503, detail=status.reason)
    try:
        source = separation_service.prepare(ws, engine, req.source_id)
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except separation_service.SeparationValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    def work(report: ProgressReporter) -> dict:
        last = {"progress": 0.0}

        def on_progress(p: float) -> None:
            last["progress"] = p
            report(p, None)

        def on_stage(label: str) -> None:
            report(last["progress"], label)

        report(0.0, "준비 중")
        try:
            return separation_service.run(ws, engine, separator, source, on_progress, on_stage)
        except SeparationError as e:
            raise UserFacingError(e.user_message) from e

    job = jobs.submit("separate", work, extra={"source_id": source.id})
    return JobOut.from_job(job)
