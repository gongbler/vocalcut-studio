import { useRef, useState } from "react";
import type { EditOutput } from "./api/edits";
import type { MediaFile } from "./api/files";
import EditPanel from "./features/editor/EditPanel";
import ResultCard from "./features/editor/ResultCard";
import ServerStatus from "./features/health/ServerStatus";
import MediaInfoCard from "./features/upload/MediaInfoCard";
import UploadPanel from "./features/upload/UploadPanel";

export default function App() {
  // 지금 작업 중인 원본 파일과, 가장 최근 편집 결과물
  const [media, setMedia] = useState<MediaFile | null>(null);
  const [output, setOutput] = useState<EditOutput | null>(null);

  // 원본 플레이어를 편집 패널과 공유하기 위한 '손잡이'
  const playerRef = useRef<HTMLMediaElement | null>(null);

  const onUploaded = (m: MediaFile) => {
    setMedia(m);
    setOutput(null); // 새 파일을 올리면 이전 결과물은 치운다
  };

  return (
    <main className="app">
      <header>
        <h1>🎙️ VocalCut Studio</h1>
        <ServerStatus />
      </header>

      <UploadPanel onUploaded={onUploaded} />
      {media && (
        <>
          <MediaInfoCard media={media} playerRef={playerRef} />
          {/* key 가 바뀌면 React 가 패널을 새로 만든다 → 새 파일마다 입력값 초기화 */}
          <EditPanel key={media.id} media={media} playerRef={playerRef} onRendered={setOutput} />
        </>
      )}
      {output && <ResultCard key={output.id} output={output} />}
    </main>
  );
}
