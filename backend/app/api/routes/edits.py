"""편집 요청 / 결과물 조회 API.

※ 지금은 렌더링이 끝날 때까지 요청이 기다리는 '동기' 방식이다.
   짧은 노래는 금방 끝나지만, 긴 영상은 수십 초~수 분 걸릴 수 있다.
   → Step 2에서 작업 대기열(Job Queue)로 바꿔 화면이 기다리지 않게 만든다.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_engine, get_workspace
from app.schemas.edit import EditOutputOut, EditRequest
from app.services import edit_service, media_service
from app.services.engines.base import EngineNotAvailableError, MediaEngine, RenderError
from app.storage.workspace import Workspace

router = APIRouter(tags=["edits"])


@router.post("/edits", response_model=EditOutputOut, status_code=201)
def create_edit(
    req: EditRequest,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> EditOutputOut:
    try:
        output = edit_service.create_edit(
            ws, engine, req.source_id, req.to_spec(), output_format=req.output_format
        )
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except edit_service.EditValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except EngineNotAvailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RenderError:
        # 자세한 원인은 서버 로그에 남아 있다 (edit_service 에서 기록)
        raise HTTPException(status_code=500, detail="편집 결과물을 만드는 중 오류가 발생했습니다. 서버 로그를 확인하세요.")
    return EditOutputOut.from_output(output)


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
