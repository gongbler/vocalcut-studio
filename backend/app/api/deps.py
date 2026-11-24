"""의존성(Dependency) 공급소.

라우트 함수는 `ws: Workspace = Depends(get_workspace)` 처럼 '필요한 도구'를 선언만 하고,
FastAPI가 요청마다 여기서 꺼내 넣어준다.
→ 테스트할 때는 app.dependency_overrides 로 가짜/임시 도구로 바꿔 끼울 수 있다.
"""
from fastapi import Request

from app.core import config
from app.core.visitor import visitor_id
from app.jobs.manager import JobManager, OwnedJobs
from app.services.engines.base import MediaEngine, SeparatorEngine, TranscriberEngine
from app.services.engines.registry import get_media_engine, get_separator_engine, get_transcriber_engine
from app.storage.workspace import Workspace


def base_workspace() -> Workspace:
    """서버 전체의 작업 폴더 (평소 모드에서는 이것 하나만 쓴다)."""
    return Workspace(config.WORKSPACE_DIR)


def get_workspace(request: Request) -> Workspace:
    """이 요청이 쓸 작업 폴더. 데모 모드에서는 방문자마다 따로 (workspace/visitors/<번호>/)."""
    vid = visitor_id(request)
    if vid is None:
        return base_workspace()
    ws = Workspace(config.WORKSPACE_DIR / "visitors" / vid, shared_root=config.WORKSPACE_DIR)
    ws.ensure()
    return ws


def get_engine() -> MediaEngine:
    return get_media_engine()


def get_separator() -> SeparatorEngine:
    return get_separator_engine()


def get_transcriber() -> TranscriberEngine:
    return get_transcriber_engine()


def get_job_manager(request: Request) -> JobManager | OwnedJobs:
    # 작업 관리자는 서버 전체에 '딱 하나'만 있어야 한다 (main.py 의 lifespan 에서 만들어 둠)
    # 데모 모드에서는 같은 작업자를 쓰되, 이 방문자의 번호표만 보이는 창구로 감싸서 준다
    manager: JobManager = request.app.state.job_manager
    vid = visitor_id(request)
    return manager if vid is None else manager.for_owner(vid)
