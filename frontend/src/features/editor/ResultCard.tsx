import type { EditOutput } from "../../api/edits";
import { formatBytes, formatDuration } from "../../utils/format";

export default function ResultCard({ output }: { output: EditOutput }) {
  return (
    <section className="card result">
      <h2>✅ 편집 결과 · {output.download_name}</h2>
      {output.kind === "video" ? (
        <video className="player" src={output.content_url} controls preload="metadata" />
      ) : (
        <audio className="player" src={output.content_url} controls preload="metadata" />
      )}

      <div className="row space-between">
        <span className="hint">
          {output.format.toUpperCase()} · 길이 {formatDuration(output.duration_sec)} · {formatBytes(output.size_bytes)}
        </span>
        {/* 서버가 'attachment' 로 보내주므로, 링크만 눌러도 브라우저가 파일로 저장한다.
            저장되는 이름은 서버가 정한 download_name (한글 그대로) */}
        <a className="button" href={output.download_url} download>
          ⬇ 다운로드
        </a>
      </div>
    </section>
  );
}
