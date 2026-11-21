"""의존성(Dependency) 공급소.

라우트 함수는 `ws: Workspace = Depends(get_workspace)` 처럼 '필요한 도구'를 선언만 하고,
FastAPI가 요청마다 여기서 꺼내 넣어준다.
→ 테스트할 때는 app.dependency_overrides 로 가짜/임시 도구로 바꿔 끼울 수 있다.
"""
from app.core import config
from app.services.engines.base import MediaEngine
from app.services.engines.registry import get_media_engine
from app.storage.workspace import Workspace


def get_workspace() -> Workspace:
    return Workspace(config.WORKSPACE_DIR)


def get_engine() -> MediaEngine:
    return get_media_engine()
