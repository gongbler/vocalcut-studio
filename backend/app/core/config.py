"""앱 전체에서 공유하는 설정값.

설정을 한 곳에 모아두면, 나중에 경로나 엔진을 바꿀 때 이 파일만 고치면 된다.
"""
from pathlib import Path

APP_NAME = "VocalCut Studio"
APP_VERSION = "0.1.0"

# backend/ 폴더의 절대 경로 (이 파일 위치 기준으로 계산)
BACKEND_DIR = Path(__file__).resolve().parents[2]

# 업로드/임시/결과 파일이 저장될 작업 폴더 (git에는 올라가지 않음)
WORKSPACE_DIR = BACKEND_DIR / "workspace"
