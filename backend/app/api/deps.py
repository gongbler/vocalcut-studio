"""의존성(Dependency) 공급소.

라우트 함수는 `ws: Workspace = Depends(get_workspace)` 처럼 '필요한 도구'를 선언만 하고,
FastAPI가 요청마다 여기서 꺼내 넣어준다.
→ 테스트할 때는 app.dependency_overrides 로 가짜/임시 도구로 바꿔 끼울 수 있다.
"""
from fastapi import Request

from app.core import config
from app.jobs.manager import JobManager
from app.services.engines.base import MediaEngine, SeparatorEngine
from app.services.engines.registry import get_media_engine, get_separator_engine
from app.storage.workspace import Workspace


def get_workspace() -> Workspace:
    return Workspace(config.WORKSPACE_DIR)


def get_engine() -> MediaEngine:
    return get_media_engine()


def get_separator() -> SeparatorEngine:
    return get_separator_engine()


def get_job_manager(request: Request) -> JobManager:
    # 작업 관리자는 서버 전체에 '딱 하나'만 있어야 한다 (main.py 의 lifespan 에서 만들어 둠)
    return request.app.state.job_manager
