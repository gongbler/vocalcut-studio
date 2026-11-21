"""AI 실행기(별도 프로세스)들이 같이 쓰는 도구 — 표준 라이브러리만 사용한다.

실행기는 서버와 'JSON 한 줄씩' 대화하고, 끝날 때 자기가 쓴 최대 메모리를 보고한다.
Demucs 실행기와 Whisper 실행기가 똑같은 규칙을 쓰도록 여기 한 곳에 모아 둔다.
"""
from __future__ import annotations

import json
import sys


def emit(**data) -> None:
    """서버에게 보내는 메시지 한 줄.

    ⚠️ print() 를 쓰면 안 된다: 출력이 파이프(다른 프로그램)로 갈 때 윈도우는 한국어 기본 인코딩(cp949)으로
       내보내서, UTF-8 로 읽는 서버 쪽에서 한글이 든 줄이 통째로 '읽을 수 없는 줄'이 되어 버려진다.
       → 항상 UTF-8 바이트로 직접 쓴다. flush 가 없으면 버퍼에 쌓여 늦게 도착한다.
    """
    line = json.dumps(data, ensure_ascii=False) + "\n"
    sys.stdout.flush()  # 혹시 print 로 먼저 나간 글이 있으면 순서가 섞이지 않게
    sys.stdout.buffer.write(line.encode("utf-8"))
    sys.stdout.buffer.flush()


def peak_memory_mb() -> float:
    """이 프로세스가 지금까지 사용한 '최대' 메모리(MB)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        # 함수의 인자/반환 '자료형'을 꼭 알려줘야 한다.
        # 안 그러면 ctypes 가 64비트 핸들을 32비트 정수로 잘라 보내서 호출이 조용히 실패한다 (→ 0MB 로 보임)
        get_current = ctypes.windll.kernel32.GetCurrentProcess
        get_current.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        get_info.restype = wintypes.BOOL

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        if not get_info(get_current(), ctypes.byref(counters), counters.cb):
            return -1.0  # 측정 실패를 0과 구분
        return counters.PeakWorkingSetSize / 1024**2
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB 단위
