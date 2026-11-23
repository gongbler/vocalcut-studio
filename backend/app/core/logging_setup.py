"""서버 기록(로그) 설정.

- 화면(콘솔): 지금까지처럼 INFO 이상.
- 파일: logs/app.log 에 '계속 쌓이는' 기록 (1MB 넘으면 app.log.1, .2, .3 으로 돌려 쓰기 = 최대 약 4MB).
  start.ps1 이 만드는 logs/backend.log 는 켤 때마다 새로 쓰므로, 지난 오류를 찾으려면 app.log 를 본다.
- 예상 못 한 오류에는 짧은 '오류 번호'를 붙인다 → 사용자가 화면에서 본 번호로 로그에서 원인을 바로 찾는다.
"""
from __future__ import annotations

import logging
import uuid
from logging.handlers import RotatingFileHandler

from app.core import config

FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_vocalcut_configured", False):  # --reload 로 여러 번 불려도 한 번만
        return
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
    if config.LOG_FILE is not None:
        config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(config.LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)
    root._vocalcut_configured = True  # type: ignore[attr-defined]


def new_error_id() -> str:
    """사용자에게 보여줄 짧은 오류 번호 (예: 'a3f9c2d1')."""
    return uuid.uuid4().hex[:8]
