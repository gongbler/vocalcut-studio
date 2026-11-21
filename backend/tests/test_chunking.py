"""조각 나누기 / 이어 붙이기 테스트 (torch 불필요 — numpy 만 사용)."""
import numpy as np
import pytest

from app.services.engines.separator.chunking import OverlapStitcher, plan_chunks


@pytest.mark.parametrize("total", [1, 50, 100, 101, 250, 999, 1000, 1001])
def test_chunks_cover_everything_and_last_is_longer_than_overlap(total):
    chunks = plan_chunks(total, chunk=100, overlap=10)

    assert chunks[0].start == 0
    assert chunks[-1].end == total                       # 끝까지 덮는다
    for a, b in zip(chunks, chunks[1:]):
        assert b.start == a.end - 10                     # 정확히 overlap 만큼 겹친다
    if len(chunks) > 1:
        assert chunks[-1].length > 10                    # 마지막 조각도 섞고 남는 부분이 있다


def test_rejects_bad_settings():
    with pytest.raises(ValueError):
        plan_chunks(1000, chunk=20, overlap=10)          # 조각이 겹침의 2배 이하


def _process_in_chunks(signal, chunk, overlap, transform=lambda x: x):
    """실행기와 똑같은 방식으로: 조각마다 처리 → stitcher 로 이어 붙이기"""
    stitcher = OverlapStitcher(overlap)
    chunks = plan_chunks(signal.shape[1], chunk, overlap)
    out = [stitcher.push(transform(signal[:, c.start:c.end]), c.index == len(chunks) - 1) for c in chunks]
    assert stitcher.finish() is None
    return np.concatenate(out, axis=1)


@pytest.mark.parametrize("total", [80, 1000, 4410, 12345])
def test_stitching_reconstructs_signal_exactly(total):
    """'처리'가 아무것도 안 바꾸면, 조각내서 이어 붙인 결과가 원본과 똑같아야 한다.
    (섞는 비율 w 와 1-w 의 합이 항상 1이기 때문)"""
    rng = np.random.default_rng(0)
    signal = rng.standard_normal((2, total)).astype(np.float32)

    out = _process_in_chunks(signal, chunk=1000, overlap=100)

    assert out.shape == signal.shape                     # 길이가 늘거나 줄지 않음
    np.testing.assert_allclose(out, signal, atol=1e-5)


def test_crossfade_hides_jump_between_chunks():
    """조각마다 결과가 조금씩 다르더라도(AI는 조각 경계에서 결과가 약간 달라짐),
    겹친 구간에서 부드럽게 이어져 '툭' 튀는 큰 점프가 생기지 않아야 한다."""
    signal = np.zeros((1, 3000), dtype=np.float32)
    calls = iter(range(100))
    # 조각마다 결과에 다른 값을 더하는 '변덕스러운 처리' (0, 1, 2, ...)
    out = _process_in_chunks(signal, chunk=1000, overlap=200, transform=lambda x: x + next(calls))

    biggest_jump = np.abs(np.diff(out[0])).max()
    assert biggest_jump < 0.02                           # 1씩 다른 조각이 0.005 단위로 서서히 바뀜
