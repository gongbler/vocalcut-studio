"""편집 요청 / 결과물 조회 API.

렌더링은 작업 대기열(Job Queue)에서 처리한다 → 요청은 번호표만 받고 바로 끝나므로 화면이 멈추지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_engine, get_job_manager, get_workspace
from app.jobs.manager import JobManager, ProgressReporter
from app.schemas.edit import EditOutputOut, EditRequest
from app.schemas.job import JobOut
from app.services import disk_guard, edit_service, media_service
from app.services.engines.base import EngineNotAvailableError, MediaEngine
from app.storage.workspace import Workspace

router = APIRouter(tags=["edits"])


@router.post("/edits", response_model=JobOut, status_code=202)
def create_edit(
    req: EditRequest,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
    jobs: JobManager = Depends(get_job_manager),
) -> JobOut:
    """편집 주문 접수.

    1) 검사는 지금 바로 한다 → 잘못된 값이면 대기열에 넣지 않고 즉시 4xx 에러.
    2) 통과하면 렌더링을 대기열에 넣고 '번호표(Job)'를 바로 돌려준다 (202 Accepted = 접수됨).
    3) 결과는 GET /api/jobs/{id} 로 확인 → 완료되면 result.output_id 로 결과물 조회.
    """
    try:
        prepared = edit_service.prepare_edit(
            ws, engine, req.source_id, req.to_spec(), output_format=req.output_format
        )
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except edit_service.EditValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except EngineNotAvailableError as e:
        raise HTTPException(status_code=503, detail=str(e))

    src = prepared.source.info
    disk_guard.require_free_space(ws.root, disk_guard.render_bytes(src.duration_sec, src.size_bytes), "편집")

    def work(report: ProgressReporter) -> dict:
        report(0.0, "렌더링 중")
        output = edit_service.run_edit(ws, engine, prepared, on_progress=lambda p: report(p, None))
        return {"output_id": output.id}

    job = jobs.submit("edit", work, extra={"source_id": req.source_id})
    return JobOut.from_job(job)


@router.get("/outputs/{output_id}", response_model=EditOutputOut)
def get_output(
    output_id: str,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> EditOutputOut:
    try:
        return EditOutputOut.from_output(edit_service.get_output(ws, engine, output_id))
    except edit_service.OutputNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _find_output(ws: Workspace, engine: MediaEngine, output_id: str) -> edit_service.EditOutput:
    try:
        return edit_service.get_output(ws, engine, output_id)
    except edit_service.OutputNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/outputs/{output_id}/content")
def get_output_content(
    output_id: str,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> FileResponse:
    """재생용: 브라우저가 파일을 '화면 안에서 열도록(inline)' 보낸다."""
    output = _find_output(ws, engine, output_id)
    return FileResponse(output.path, filename=output.download_name, content_disposition_type="inline")


@router.get("/outputs/{output_id}/download")
def download_output(
    output_id: str,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> FileResponse:
    """다운로드용: 같은 파일이지만 '첨부파일(attachment)'로 보내서 브라우저가 저장하게 한다.

    한글 파일 이름은 Content-Disposition 헤더의 filename*=utf-8''... 형식으로 자동 인코딩된다.
    """
    output = _find_output(ws, engine, output_id)
    return FileResponse(output.path, filename=output.download_name, content_disposition_type="attachment")
