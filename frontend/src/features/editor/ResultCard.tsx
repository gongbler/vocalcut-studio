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
      <p className="hint">
        길이 {formatDuration(output.duration_sec)} · {formatBytes(output.size_bytes)}
        {" · "}다운로드 버튼은 다음 단계(1-4)에서 추가됩니다
      </p>
    </section>
  );
}
