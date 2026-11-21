import type { RefObject } from "react";
import type { MediaFile } from "../../api/files";
import { formatBytes, formatDuration } from "../../utils/format";

type Props = {
  media: MediaFile;
  /** 편집 패널이 '현재 재생 위치'를 읽고 구간 미리듣기를 할 수 있도록 플레이어를 공유한다 */
  playerRef: RefObject<HTMLMediaElement | null>;
};

export default function MediaInfoCard({ media, playerRef }: Props) {
  const { video, audio } = media;

  return (
    <section className="card">
      <h2>
        {media.kind === "video" ? "🎬" : "🎧"} {media.original_name}
      </h2>

      {/* 미리보기: 서버의 /content 주소를 그대로 재생 */}
      {media.kind === "video" ? (
        <video
          ref={playerRef as RefObject<HTMLVideoElement>}
          className="player"
          src={media.content_url}
          controls
          preload="metadata"
        />
      ) : (
        <audio
          ref={playerRef as RefObject<HTMLAudioElement>}
          className="player"
          src={media.content_url}
          controls
          preload="metadata"
        />
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
