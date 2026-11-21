# VocalCut Studio

로컬 PC에서 노래·영상을 편집하는 AI 스튜디오 (React + FastAPI + FFmpeg + Demucs + faster-whisper).

> 🚧 Step 0: 프로젝트 뼈대 + 프론트엔드 ↔ 백엔드 연결

## 실행 방법

필수: Python 3.11, Node.js 20+, FFmpeg (PATH 등록)

```powershell
# 1) 백엔드 최초 설치 (한 번만)
powershell -ExecutionPolicy Bypass -File .\scripts\setup-backend.ps1

# 2) 백엔드 실행 → http://127.0.0.1:8000/docs
powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1

# 3) 프론트엔드 (새 터미널)
cd frontend
npm install
npm run dev   # → http://localhost:5173
```

## 구조

```
frontend/   React + Vite + TypeScript (화면)
backend/    FastAPI (API 서버, 작업 큐, 엔진 서비스 계층)
scripts/    설치·실행 스크립트
```
