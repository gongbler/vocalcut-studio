import type { MediaFile } from "../../api/files";
import { formatBytes, formatDuration } from "../../utils/format";

export default function MediaInfoCard({ media }: { media: MediaFile }) {
  const { video, audio } = media;

  return (
    <section className="card">
      <h2>
        {media.kind === "video" ? "🎬" : "🎧"} {media.original_name}
      </h2>

      {/* 미리보기: 서버의 /content 주소를 그대로 재생 */}
      {media.kind === "video" ? (
        <video className="player" src={media.content_url} controls preload="metadata" />
      ) : (
        <audio className="player" src={media.content_url} controls preload="metadata" />
      )}

      <dl className="info">
        <dt>길이</dt>
        <dd>{formatDuration(media.duration_sec)}</dd>
        <dt>크기</dt>
        <dd>{formatBytes(media.size_bytes)}</dd>
        <dt>포맷</dt>
        <dd>{media.format_name}</dd>
        {video && (
          <>
            <dt>영상</dt>
            <dd>
              {video.width}×{video.height} · {video.fps ?? "?"}fps · {video.codec}
            </dd>
          </>
        )}
        {audio && (
          <>
            <dt>오디오</dt>
            <dd>
              {audio.sample_rate.toLocaleString()}Hz · {audio.channels === 2 ? "스테레오" : `${audio.channels}ch`} ·{" "}
              {audio.codec}
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}
