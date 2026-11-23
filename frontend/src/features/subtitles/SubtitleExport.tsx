import { useState } from "react";
import { getOutput, type EditOutput } from "../../api/edits";
import { postJson } from "../../api/errors";
import type { MediaFile } from "../../api/files";
import { cancelJob, JobCancelledError, waitForJob, type Job } from "../../api/jobs";
import JobProgress from "../../components/JobProgress";
import { useElapsed } from "../../hooks/useElapsed";

type Props = {
  media: MediaFile;
  dirty: boolean; // 저장 안 한 수정이 있으면 내보내기 전에 저장부터
  onRendered: (output: EditOutput) => void;
};

const SIZES = [
  { id: "small", label: "작게" },
  { id: "medium", label: "보통" },
  { id: "large", label: "크게" },
] as const;
const POSITIONS = [
  { id: "bottom", label: "아래" },
  { id: "middle", label: "가운데" },
  { id: "top", label: "위" },
] as const;

/** 자막 내보내기: SRT 파일 저장 / 영상에 자막 입히기 */
export default function SubtitleExport({ media, dirty, onRendered }: Props) {
  const [size, setSize] = useState<string>("medium");
  const [position, setPosition] = useState<string>("bottom");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const elapsed = useElapsed(busy);

  const burn = async () => {
    setBusy(true);
    setJob(null);
    setCancelling(false);
    setError(null);
    try {
      const ticket = await postJson<Job>("/api/subtitle-renders", { file_id: media.id, size, position });
      setJob(ticket);
      const done = await waitForJob(ticket.id, setJob);
      onRendered(await getOutput(done.result!.output_id));
    } catch (err) {
      if (!(err instanceof JobCancelledError)) setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!job) return;
    setCancelling(true);
    await cancelJob(job.id).catch(() => undefined);
  };

  const chips = (
    name: string,
    items: readonly { id: string; label: string }[],
    value: string,
    set: (v: string) => void,
  ) => (
    <div className="row">
      {items.map((it) => (
        <label key={it.id} className={`chip ${value === it.id ? "on" : ""}`}>
          <input type="radio" name={name} checked={value === it.id} onChange={() => set(it.id)} />
          {it.label}
        </label>
      ))}
    </div>
  );

  return (
    <div className="sub-export">
      <hr />
      <h3>📤 내보내기</h3>
      {dirty && <p className="bad">⚠️ 저장하지 않은 수정이 있어요. 위에서 💾 저장한 뒤 내보내세요.</p>}

      <div className="row">
        <a
          className={`button ${dirty ? "disabled" : ""}`}
          href={dirty ? undefined : `/api/files/${media.id}/subtitles.srt`}
          download
          aria-disabled={dirty}
        >
          ⬇ SRT 자막 파일 저장
        </a>
        <span className="hint">유튜브 업로드·동영상 플레이어에서 따로 불러오는 자막 파일이에요.</span>
      </div>

      {media.video ? (
        <>
          <div className="field-grid" style={{ marginTop: 14 }}>
            <fieldset className="formats">
              <legend>글자 크기</legend>
              {chips("burn-size", SIZES, size, setSize)}
            </fieldset>
            <fieldset className="formats">
              <legend>위치</legend>
              {chips("burn-pos", POSITIONS, position, setPosition)}
            </fieldset>
          </div>
          {!busy && (
            <button onClick={burn} disabled={dirty}>
              🎬 영상에 자막 입히기 (맑은 고딕 · MP4)
            </button>
          )}
          {busy && <JobProgress job={job} elapsed={elapsed} onCancel={cancel} cancelling={cancelling} />}
          <p className="hint">
            영상을 새로 만들기 때문에 영상 길이 정도의 시간이 걸려요. 원본 영상은 그대로 남아요.
          </p>
        </>
      ) : (
        <p className="hint">🎧 소리만 있는 파일이라 영상에 입히기는 할 수 없어요. SRT 파일로 저장하세요.</p>
      )}
      {error && <p className="bad">❌ {error}</p>}
    </div>
  );
}
