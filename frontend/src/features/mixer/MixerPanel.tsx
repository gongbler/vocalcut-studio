import { useRef, useState } from "react";
import { getOutput, type EditOutput } from "../../api/edits";
import { uploadFile, type MediaFile } from "../../api/files";
import { cancelJob, JobCancelledError, waitForJob, type Job } from "../../api/jobs";
import { createMix, type MixRequest } from "../../api/mixes";
import JobProgress from "../../components/JobProgress";
import { useElapsed } from "../../hooks/useElapsed";
import { formatDuration } from "../../utils/format";
import type { Stems } from "../separation/SeparationPanel";
import TrackStrip, { type TrackPatch, type TrackState } from "./TrackStrip";

type Props = {
  source: MediaFile;
  stems: Stems | null;
  onRendered: (output: EditOutput) => void;
};

const PREVIEW_SEC = 15;

function newTrack(media: MediaFile, label: string, removable = false): TrackState {
  return { key: media.id, media, label, volumeDb: 0, offsetMs: 0, low: 0, mid: 0, high: 0, muted: false, removable };
}

function initialTracks(source: MediaFile, stems: Stems | null): TrackState[] {
  if (!stems) return [newTrack(source, "🎵 원곡")];
  // 커버곡 기본 구성: MR + 원곡 보컬(가이드용, 기본 음소거) → 내 목소리를 추가해서 섞는다
  return [newTrack(stems.instrumental, "🎹 MR"), { ...newTrack(stems.vocals, "🎤 원곡 보컬"), muted: true }];
}

export default function MixerPanel({ source, stems, onRendered }: Props) {
  const [tracks, setTracks] = useState<TrackState[]>(() => initialTracks(source, stems));
  const [previewStart, setPreviewStart] = useState(0);
  const [fadeIn, setFadeIn] = useState(0);
  const [fadeOut, setFadeOut] = useState(0);
  const [format, setFormat] = useState<"mp3" | "wav">("mp3");

  const [busy, setBusy] = useState<null | "preview" | "final">(null);
  const [job, setJob] = useState<Job | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<EditOutput | null>(null);
  const [adding, setAdding] = useState<number | null>(null); // 트랙 추가 업로드 진행률
  const elapsed = useElapsed(busy !== null);
  const fileInput = useRef<HTMLInputElement>(null);

  // 믹스 전체 길이 = 각 트랙의 (싱크 + 길이) 중 가장 긴 것 (음소거 트랙 제외)
  const active = tracks.filter((t) => !t.muted);
  const mixLength = Math.max(0, ...active.map((t) => t.offsetMs / 1000 + t.media.duration_sec));
  const previewEnd = Math.min(previewStart + PREVIEW_SEC, mixLength);

  // setTracks 에 '함수'를 넘기면 React 가 항상 최신 목록(ts)을 넣어 준다 → 연속 클릭도 정확히 누적
  const update = (key: string, patch: TrackPatch) =>
    setTracks((ts) =>
      ts.map((t) => (t.key === key ? { ...t, ...(typeof patch === "function" ? patch(t) : patch) } : t)),
    );

  const addTrack = async (file: File) => {
    setError(null);
    setAdding(0);
    try {
      const media = await uploadFile(file, setAdding);
      if (!media.audio) throw new Error("소리가 없는 파일은 트랙으로 추가할 수 없습니다.");
      setTracks((ts) => [...ts, newTrack(media, `🎙️ ${media.original_name}`, true)]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAdding(null);
    }
  };

  const run = async (mode: "preview" | "final") => {
    const req: MixRequest = {
      tracks: tracks.map((t) => ({
        file_id: t.media.id,
        volume_db: t.volumeDb,
        offset_sec: t.offsetMs / 1000,
        eq_low_db: t.low,
        eq_mid_db: t.mid,
        eq_high_db: t.high,
        muted: t.muted,
      })),
      start_sec: mode === "preview" ? previewStart : 0,
      end_sec: mode === "preview" ? previewEnd : null,
      fade_in_sec: mode === "preview" ? 0 : fadeIn,
      fade_out_sec: mode === "preview" ? 0 : fadeOut,
      output_format: mode === "preview" ? "mp3" : format,
      preview: mode === "preview",
    };
    setBusy(mode);
    setJob(null);
    setCancelling(false);
    setError(null);
    try {
      const ticket = await createMix(req);
      setJob(ticket);
      const done = await waitForJob(ticket.id, setJob);
      const output = await getOutput(done.result!.output_id);
      if (mode === "preview") setPreview(output);
      else onRendered(output);
    } catch (err) {
      if (!(err instanceof JobCancelledError)) setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    if (!job) return;
    setCancelling(true);
    await cancelJob(job.id).catch(() => undefined);
  };

  return (
    <section className="card">
      <h2>🎚️ 믹서 — 트랙을 섞어 하나로</h2>
      <p className="hint">
        트랙별로 볼륨·싱크·EQ를 맞춘 뒤, 짧게 미리 들어보고 완성하세요. 슬라이더를 더블클릭하면 0으로 돌아가요.
      </p>

      <div className="tracks">
        {tracks.map((t) => (
          <TrackStrip
            key={t.key}
            track={t}
            onChange={(patch) => update(t.key, patch)}
            onRemove={() => setTracks((ts) => ts.filter((x) => x.key !== t.key))}
          />
        ))}
      </div>

      <div className="row">
        <button className="secondary" onClick={() => fileInput.current?.click()} disabled={adding !== null || tracks.length >= 6}>
          {adding !== null ? `트랙 올리는 중… ${adding}%` : "＋ 트랙 추가 (내 목소리 녹음 등)"}
        </button>
        <span className="hint">최대 6개 · 믹스 길이 {formatDuration(mixLength)}</span>
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".mp3,.wav,.m4a,.aac,.flac,.ogg,.mp4,.mov,.mkv,.webm"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) addTrack(f);
          e.target.value = "";
        }}
      />

      <hr />

      {/* ---- 미리듣기 ---- */}
      <div className="row">
        <label className="row">
          미리듣기 시작 (초)
          <input type="number" min={0} max={Math.max(0, mixLength - 0.1)} step={1} value={previewStart}
            onChange={(e) => setPreviewStart(Math.max(0, Number(e.target.value)))} style={{ width: 90 }} />
        </label>
        <button className="secondary" onClick={() => run("preview")} disabled={busy !== null || active.length === 0}>
          ▶ {PREVIEW_SEC}초 미리듣기 만들기
        </button>
        <span className="hint">
          {formatDuration(previewStart)} ~ {formatDuration(previewEnd)}
        </span>
      </div>
      {preview && !busy && (
        <audio key={preview.id} className="player" src={preview.content_url} controls autoPlay />
      )}

      {/* ---- 최종 믹스 ---- */}
      <div className="field-grid" style={{ marginTop: 12 }}>
        <label>
          페이드 인 (초)
          <input type="number" min={0} step={0.5} value={fadeIn} onChange={(e) => setFadeIn(Number(e.target.value))} />
        </label>
        <label>
          페이드 아웃 (초)
          <input type="number" min={0} step={0.5} value={fadeOut} onChange={(e) => setFadeOut(Number(e.target.value))} />
        </label>
        <fieldset className="span-2 formats">
          <legend>출력 형식</legend>
          <div className="row">
            {(["mp3", "wav"] as const).map((f) => (
              <label key={f} className={`chip ${format === f ? "on" : ""}`}>
                <input type="radio" name="mix-format" checked={format === f} onChange={() => setFormat(f)} />
                {f.toUpperCase()}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      <button onClick={() => run("final")} disabled={busy !== null || active.length === 0}>
        🎚️ 믹스 완성하기 ({formatDuration(mixLength)})
      </button>

      {busy && <JobProgress job={job} elapsed={elapsed} onCancel={cancel} cancelling={cancelling} />}
      {active.length === 0 && <p className="bad">⚠️ 모든 트랙이 음소거되어 있어요.</p>}
      {error && <p className="bad">❌ {error}</p>}
    </section>
  );
}
