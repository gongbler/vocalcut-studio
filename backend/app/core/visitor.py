"""방문자 구분 (데모 모드 전용) = 물품 보관함 열쇠 나눠 주기.

공개 데모 사이트에서는 여러 사람이 같은 서버를 쓴다. 처음 온 사람에게 보이지 않는 번호표(쿠키)를 주고,
서버는 그 번호마다 작업 폴더를 따로 쓴다 → 다른 사람의 파일은 목록에도 안 보이고, 열거나 지울 수도 없다.

- 번호는 uuid4 (추측할 수 없는 32글자). 형식이 다르면(조작된 값) 새 번호를 준다.
- 평소 모드(DEMO_MODE 꺼짐)에서는 아무것도 하지 않는다.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core import config

_VISITOR_RE = re.compile(r"^[0-9a-f]{32}$")


def visitor_id(request: Request) -> str | None:
    """이 요청을 보낸 방문자 번호 (평소 모드에서는 None)."""
    if not config.DEMO_MODE:
        return None
    return getattr(request.state, "visitor_id", None)


async def visitor_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if not config.DEMO_MODE:
        return await call_next(request)
    vid = request.cookies.get(config.VISITOR_COOKIE)
    is_new = not (vid and _VISITOR_RE.fullmatch(vid))
    if is_new:
        vid = uuid.uuid4().hex
    request.state.visitor_id = vid
    response = await call_next(request)
    if is_new:
        cross = config.COOKIE_CROSS_SITE
        response.set_cookie(
            config.VISITOR_COOKIE, vid, max_age=config.VISITOR_COOKIE_MAX_AGE, path="/",
            httponly=True,                      # 화면의 자바스크립트가 읽을 수 없게 (훔쳐 가기 어렵게)
            samesite="none" if cross else "lax",
            secure=cross,
        )
    return response
