import { useEffect, useRef, useState, type RefObject } from "react";
import { createEdit, getOutput, type EditOutput, type OutputFormat } from "../../api/edits";
import type { MediaFile } from "../../api/files";
import { waitForJob, type Job } from "../../api/jobs";
import JobProgress from "../../components/JobProgress";
import { formatDuration } from "../../utils/format";

type Props = {
  media: MediaFile;
  playerRef: RefObject<HTMLMediaElement | null>;
  onRendered: (output: EditOutput) => void;
};

const round1 = (n: number) => Math.round(n * 10) / 10;

const FORMAT_INFO: Record<OutputFormat, { label: string; hint: string }> = {
  mp4: { label: "MP4 영상", hint: "영상 + 소리 (H.264 / AAC)" },
  mp3: { label: "MP3", hint: "소리만 · 작은 용량 (192kbps)" },
  wav: { label: "WAV", hint: "소리만 · 무손실 · 용량 큼 (다른 편집 프로그램용)" },
};

export default function EditPanel({ media, playerRef, onRendered }: Props) {
  const duration = media.duration_sec;

  // 편집 값 (화면에 입력된 숫자들)
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(round1(duration));
  const [volumeDb, setVolumeDb] = useState(0);
  const [fadeIn, setFadeIn] = useState(0);
  const [fadeOut, setFadeOut] = useState(0);

  // 고를 수 있는 출력 형식: 영상이면 mp4/mp3/wav, 오디오면 mp3/wav
  const formats: OutputFormat[] = media.kind === "video" ? ["mp4", "mp3", "wav"] : ["mp3", "wav"];
  const [format, setFormat] = useState<OutputFormat>(formats[0]);

  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
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
    setJob(null);
    setError(null);
    try {
      // ① 주문 → 번호표를 바로 받음 (잘못된 값이면 여기서 바로 에러)
      const ticket = await createEdit({
        source_id: media.id,
        start_sec: start,
        end_sec: end,
        volume_db: volumeDb,
        fade_in_sec: fadeIn,
        fade_out_sec: fadeOut,
        output_format: format,
      });
      setJob(ticket);
      // ② 끝날 때까지 1초마다 진행 상황 확인
      const done = await waitForJob(ticket.id, setJob);
      // ③ 완료되면 결과물 정보를 받아 화면에 표시
      onRendered(await getOutput(done.result!.output_id));
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

        <fieldset className="span-2 formats">
          <legend>출력 형식</legend>
          <div className="row">
            {formats.map((f) => (
              <label key={f} className={`chip ${format === f ? "on" : ""}`}>
                <input type="radio" name="format" value={f} checked={format === f}
                  onChange={() => setFormat(f)} />
                {FORMAT_INFO[f].label}
              </label>
            ))}
          </div>
          <span className="hint">
            {FORMAT_INFO[format].hint}
            {media.kind === "video" && format !== "mp4" && " · 영상에서 소리만 추출합니다"}
          </span>
        </fieldset>
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
          {busy ? "처리 중…" : "편집 결과 만들기"}
        </button>
      </div>
      {busy && <JobProgress job={job} elapsed={elapsed} />}
      {error && <p className="bad">❌ {error}</p>}
    </section>
  );
}
