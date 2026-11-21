# VocalCut Studio

로컬 PC에서 노래·영상을 편집하는 AI 스튜디오 (React + FastAPI + FFmpeg + Demucs + faster-whisper).

> ✅ Step 1 완료: 업로드 → 구간 자르기 · 볼륨 · 페이드 → MP4 / MP3 / WAV 다운로드
> ✅ Step 2 진행 중: 작업 대기열 · 파형 구간 선택 · **AI 보컬/MR 분리** 완료 → 다음: 믹서

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

### (선택) AI 보컬/MR 분리 설치

서버 자체에는 필요 없고, 분리 기능을 쓸 때만 별도 프로세스에서 사용한다. 설치하지 않으면 화면에 "AI 분리 없음"으로 표시된다.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

모델(`htdemucs`, 약 81MB)은 처음 분리할 때 `backend/models/`에 자동으로 받고, 이후에는 인터넷 없이 동작한다.

## 테스트

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 최초 1회
.\.venv\Scripts\python.exe -m pytest -v
```

- 테스트용 음원·영상은 FFmpeg로 즉석 생성하며, 볼륨/페이드는 `volumedetect`로 실제 음량을 측정해 검증한다.
- 보컬 분리는 같은 통신 규칙(JSON 줄)을 쓰는 **가짜 실행기**로 검사한다 → torch 없이도, 몇 초 안에 테스트가 끝난다.

## 설계 메모

### 보컬 분리: 저사양 PC(RAM 4GB, GPU 없음) 대응

| 방식 | 2분 곡 최대 메모리 | 비고 |
|---|---|---|
| Demucs 기본 (곡 전체를 한 번에) | 약 1.6GB (추정, 곡 길이에 비례) | 30초 753MB · 60초 1,048MB 실측 |
| **30초 조각 처리 + 2초 크로스페이드** | **813MB (실측, 곡 길이와 무관)** | 이음매 오차 = 이음매 없는 구간과 동일 |

- AI는 **별도 프로세스**에서 실행 → 서버는 torch를 불러오지 않으며, 분리가 끝나면 메모리를 전부 돌려받는다.
- 작업 대기열(작업자 1명)로 무거운 작업이 동시에 돌지 않게 하고, 취소 시 1~2초 안에 실행기 프로세스를 종료한다.
- 처리 속도: i5-4200M(CPU) 기준 곡 길이의 약 2.5~3.4배.

### 엔진 교체 구조 (상용화 대비)

`backend/app/services/engines/base.py`의 규격(`MediaEngine`, `SeparatorEngine`)만 지키면 엔진을 바꿔 끼울 수 있다.
설정(`app/core/config.py`)의 `MEDIA_ENGINE`, `SEPARATOR_ENGINE` 값으로 선택한다.

### ⚠️ 라이선스 메모

- Demucs **코드**는 MIT 라이선스.
- 사전학습 **모델 가중치**는 연구용 데이터셋으로 학습되었으므로, 유료 판매 전에 상업 이용이 가능한 모델로 교체를 검토해야 한다.
- FFmpeg full build는 GPL 구성 요소를 포함한다 → 배포 시 LGPL 빌드 또는 대체 엔진 검토 필요.

## 구조

```
frontend/   React + Vite + TypeScript (화면)
backend/    FastAPI (API 서버, 작업 큐, 엔진 서비스 계층)
  app/services/engines/   엔진 규격(base) + FFmpeg 엔진 + Demucs 엔진/실행기
  tools/                  성능 측정 도구 (bench_separation.py)
scripts/    설치·실행 스크립트
```
