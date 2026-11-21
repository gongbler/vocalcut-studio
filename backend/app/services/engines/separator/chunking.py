"""긴 노래를 '조각'으로 나눠 처리하고 다시 이어 붙이는 도구.

왜 필요한가?
  Demucs는 노래 전체를 한 번에 메모리에 올려서, 곡이 길수록 메모리가 계속 늘어난다
  (실측: 30초 753MB → 60초 1,048MB → 4분이면 약 2.8GB 예상).
  조각마다 처리하고 바로 디스크에 쓰면, 곡 길이와 상관없이 '조각 하나' 만큼의 메모리만 쓴다.

이음매 처리 (크로스페이드):
  조각을 딱 붙여 자르면 경계에서 '툭' 소리가 날 수 있다.
  그래서 조각끼리 overlap 만큼 겹치게 처리한 뒤,
  겹친 구간에서 앞 조각은 점점 작게(1→0), 뒤 조각은 점점 크게(0→1) 섞는다.

      조각1: |=========================\\
      조각2:                     /=========================\\
      조각3:                                         /=============|
                                 ↑ 겹친 구간: 두 결과를 비율로 섞음
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int  # 입력에서 읽을 시작 위치 (샘플 프레임 단위)
    end: int    # 끝 위치 (포함하지 않음)

    @property
    def length(self) -> int:
        return self.end - self.start


def plan_chunks(total: int, chunk: int, overlap: int) -> list[Chunk]:
    """전체 길이(total)를 chunk 크기, overlap 만큼 겹치는 조각들로 나눈다.

    보장하는 것:
      - 조각들이 처음부터 끝까지 빈틈없이 덮는다
      - 마지막 조각은 overlap 보다 길다 (겹친 구간을 섞고도 남는 부분이 있음)
    """
    if total <= 0:
        return []
    if overlap < 0 or chunk <= 2 * overlap:
        raise ValueError("chunk 는 overlap 의 2배보다 커야 합니다")
    step = chunk - overlap
    starts = [0]
    while starts[-1] + chunk < total:
        starts.append(starts[-1] + step)
    return [Chunk(i, s, min(s + chunk, total)) for i, s in enumerate(starts)]


class OverlapStitcher:
    """조각별 결과를 받아, 겹친 부분을 섞어서 '바로 저장해도 되는 부분'만 내보낸다.

    메모리에는 다음 조각과 섞을 '꼬리(overlap 길이)'만 남겨 둔다.
    입력/출력 배열 모양: (채널 수, 프레임 수) — numpy 배열
    """

    def __init__(self, overlap: int) -> None:
        self.overlap = overlap
        self._tail = None  # 직전 조각의 마지막 overlap 구간 (아직 저장 안 함)

    def push(self, out, last: bool):
        import numpy as np

        if self._tail is not None:
            o = self._tail.shape[1]
            # 페이드인 가중치: 0에 가까운 값 → 1에 가까운 값 (샘플 가운데 기준)
            w = (np.arange(o, dtype=np.float32) + 0.5) / o
            blended = self._tail * (1 - w) + out[:, :o] * w
            body = out[:, o:]
        else:
            blended = out[:, :0]
            body = out

        if last or self.overlap == 0:
            self._tail = None
            return np.concatenate([blended, body], axis=1)

        self._tail = body[:, -self.overlap:].copy()
        return np.concatenate([blended, body[:, : -self.overlap]], axis=1)

    def finish(self):
        """마지막 조각을 last=True 로 넣었다면 남은 것이 없다. 혹시 남았으면 내보낸다."""
        tail, self._tail = self._tail, None
        return tail
