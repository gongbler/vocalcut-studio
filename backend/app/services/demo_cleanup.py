"""데모 모드 자동 정리 = '1시간 지난 짐은 보관함에서 치우기'.

- 방문자 폴더(workspace/visitors/<번호>/) 안의 올린 파일·결과물 중 마지막으로 손댄 지 TTL 이 지난 것을 지운다.
- 그 방문자의 작업이 아직 돌고 있으면 건드리지 않는다 (쓰고 있는 파일을 지우면 작업이 깨진다).
- 남은 파일이 하나도 없는 방문자 폴더는 통째로 지운다 (빈 폴더가 쌓이지 않게).
  방문자가 다시 오면 deps.get_workspace 가 폴더를 새로 만든다.
"""
from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)


def _age(path: Path, now: float) -> float:
    try:
        return now - path.stat().st_mtime
    except OSError:
        return 0.0


def cleanup_visitors(
    root: Path,
    is_busy: Callable[[str], bool],
    ttl_sec: float,
    now: float | None = None,
) -> dict:
    """root/visitors 를 훑어 오래된 파일을 지운다. 지운 개수를 돌려준다 (로그·테스트용)."""
    now = time.time() if now is None else now
    removed = {"items": 0, "visitors": 0}
    visitors = root / "visitors"
    if not visitors.is_dir():
        return removed
    for vdir in visitors.iterdir():
        if not vdir.is_dir() or is_busy(vdir.name):
            continue
        ws = Workspace(vdir)
        for base in (ws.uploads, ws.outputs, ws.temp):
            if not base.is_dir():
                continue
            for item in base.iterdir():
                if _age(item, now) > ttl_sec:
                    shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
                    removed["items"] += 1
        has_files = any(b.is_dir() and any(b.iterdir()) for b in (ws.uploads, ws.outputs))
        if not has_files:
            shutil.rmtree(vdir, ignore_errors=True)
            removed["visitors"] += 1
    if removed["items"]:
        logger.info("데모 정리: 오래된 파일 %d개, 빈 방문자 폴더 %d개 삭제", removed["items"], removed["visitors"])
    return removed
