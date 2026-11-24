"""화면(React 빌드 결과) 보여주기 = 배포할 때 '한 주소'로 합치기.

개발할 때는 화면(Vite, 5173)과 서버(FastAPI, 8000)가 따로 돈다. 공개 서버에는 주소(포트)가 하나뿐이므로,
미리 만들어 둔 화면 파일(frontend/dist)을 FastAPI 가 직접 내려준다.

- /api/... 는 지금까지처럼 API. (없는 API 주소는 화면이 아니라 JSON 404)
- /assets/... 처럼 실제 파일이 있으면 그 파일.
- 그 밖의 주소(예: /?file=…)는 index.html → React 가 화면을 그린다.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """dist 에 index.html 이 있으면 화면 주소들을 등록한다. 등록했으면 True."""
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        return False

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="없는 API 주소입니다.")
        if path:
            file = (dist / path).resolve()
            # dist 밖의 파일(../../ 같은 주소)은 절대 내주지 않는다
            if file.is_relative_to(dist) and file.is_file():
                # 빌드 파일 이름에 내용 지문(hash)이 들어 있어 바뀌면 이름도 바뀐다 → 오래 보관해도 안전
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
                return FileResponse(file, headers={"Cache-Control": cache})
        # index.html 은 항상 새로 확인 → 새 버전을 올리면 바로 반영
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True
