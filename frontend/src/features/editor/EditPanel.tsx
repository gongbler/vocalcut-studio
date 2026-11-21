import { useEffect, useRef, useState, type RefObject } from "react";
import { createEdit, type EditOutput } from "../../api/edits";
import type { MediaFile } from "../../api/files";
import { formatDuration } from "../../utils/format";

type Props = {
  media: MediaFile;
  playerRef: RefObject<HTMLMediaElement | null>;
  onRendered: (output: EditOutput) => void;
};

const round1 = (n: number) => Math.round(n * 10) / 10;

export default function EditPanel({ media, playerRef, onRendered }: Props) {
  const duration = media.duration_sec;

  // 편집 값 (화면에 입력된 숫자들)
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(round1(duration));
  const [volumeDb, setVolumeDb] = useState(0);
  const [fadeIn, setFadeIn] = useState(0);
  const [fadeOut, setFadeOut] = useState(0);

  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // ---- 화면에서 먼저 하는 간단한 검사 (서버도 똑같이 다시 검사한다) ----
  const length = end - start;
  const problem =
    start < 0 || end > duration + 0.05
      ? `구간은 0 ~ ${formatDuration(duration)} 안에서 정하세요.`
      : length < 0.1
        ? "끝 시간은 시작 시간보다 뒤여야 합니다."
        : fadeIn + fadeOut > length
          ? "페이드 인+아웃이 자른 구간보다 깁니다."
          : null;

  // ---- 렌더링 중 경과 시간 표시 (1초마다 +1) ----
  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(timer); // 정리: 렌더링이 끝나면 타이머 해제
  }, [busy]);

  // ---- 구간 미리듣기: 시작점부터 재생하다가 끝점에서 멈춘다 ----
  const stopAtRef = useRef<number | null>(null);
  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    const onTime = () => {
      if (stopAtRef.current !== null && player.currentTime >= stopAtRef.current) {
        player.pause();
        stopAtRef.current = null;
      }
    };
    player.addEventListener("timeupdate", onTime);
    return () => player.removeEventListener("timeupdate", onTime);
  }, [playerRef, media.id]);

  const previewRange = () => {
    const player = playerRef.current;
    if (!player) return;
    player.currentTime = start;
    stopAtRef.current = end;
    void player.play();
  };

  const currentTime = () => round1(playerRef.current?.currentTime ?? 0);

  const render = async () => {
    setBusy(true);
    setError(null);
    try {
      const output = await createEdit({
        source_id: media.id,
        start_sec: start,
        end_sec: end,
        volume_db: volumeDb,
        fade_in_sec: fadeIn,
        fade_out_sec: fadeOut,
      });
      onRendered(output);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>✂️ 자르기 · 볼륨 · 페이드</h2>

      <div className="field-grid">
        <label>
          시작 (초)
          <div className="row">
            <input type="number" min={0} max={duration} step={0.1} value={start}
              onChange={(e) => setStart(Number(e.target.value))} />
            <button className="small" onClick={() => setStart(currentTime())} title="플레이어의 현재 위치를 시작점으로">
              현재 위치
            </button>
          </div>
        </label>

        <label>
          끝 (초)
          <div className="row">
            <input type="number" min={0} max={duration} step={0.1} value={end}
              onChange={(e) => setEnd(Number(e.target.value))} />
            <button className="small" onClick={() => setEnd(currentTime())} title="플레이어의 현재 위치를 끝점으로">
              현재 위치
            </button>
          </div>
        </label>

        <label className="span-2">
          볼륨 <b>{volumeDb > 0 ? `+${volumeDb}` : volumeDb} dB</b>
          <input type="range" min={-20} max={12} step={0.5} value={volumeDb}
            onChange={(e) => setVolumeDb(Number(e.target.value))} />
          <span className="hint">+6dB ≈ 2배 크게 · −6dB ≈ 절반 · 너무 키우면 소리가 깨질 수 있어요</span>
        </label>

        <label>
          페이드 인 (초)
          <input type="number" min={0} step={0.1} value={fadeIn}
            onChange={(e) => setFadeIn(Number(e.target.value))} />
        </label>

        <label>
          페이드 아웃 (초)
          <input type="number" min={0} step={0.1} value={fadeOut}
            onChange={(e) => setFadeOut(Number(e.target.value))} />
        </label>
      </div>

      <p className="hint">
        결과 길이: <b>{length > 0 ? formatDuration(length) : "-"}</b>
      </p>
      {problem && <p className="bad">⚠️ {problem}</p>}

      <div className="row">
        <button className="secondary" onClick={previewRange} disabled={!!problem}>
          ▶ 구간 미리듣기
        </button>
        <button onClick={render} disabled={busy || !!problem}>
          {busy ? `처리 중… ${elapsed}초` : "편집 결과 만들기"}
        </button>
      </div>
      {busy && media.kind === "video" && (
        <p className="hint">영상은 다시 인코딩하느라 시간이 걸려요. 창을 닫지 마세요.</p>
      )}
      {error && <p className="bad">❌ {error}</p>}
    </section>
  );
}
