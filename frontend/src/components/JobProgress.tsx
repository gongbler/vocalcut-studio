import type { Job } from "../api/jobs";

type Props = {
  job: Job | null;
  elapsed: number;
  /** 주어지면 '취소' 버튼을 보여준다 */
  onCancel?: () => void;
  cancelling?: boolean;
};

function formatElapsed(sec: number): string {
  return sec < 60 ? `${sec}초` : `${Math.floor(sec / 60)}분 ${sec % 60}초`;
}

/** 작업 진행 상태 표시줄 (편집·보컬 분리·믹싱에서 공통으로 사용) */
export default function JobProgress({ job, elapsed, onCancel, cancelling }: Props) {
  const percent = Math.round((job?.progress ?? 0) * 100);
  const label =
    !job || job.status === "queued"
      ? "대기 중… (앞 작업이 끝나면 시작)"
      : `${job.message ?? "처리 중"} ${percent}%`;

  return (
    <div className="job-progress" role="status" aria-live="polite">
      <div className="row space-between">
        <span>⏳ {label}</span>
        <span className="row">
          <span className="hint">{formatElapsed(elapsed)} 경과</span>
          {onCancel && (
            <button className="small" onClick={onCancel} disabled={cancelling}>
              {cancelling ? "취소하는 중…" : "취소"}
            </button>
          )}
        </span>
      </div>
      <div className="progress">
        <div className="bar" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
