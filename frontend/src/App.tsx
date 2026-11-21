import { useState } from "react";
import type { MediaFile } from "./api/files";
import ServerStatus from "./features/health/ServerStatus";
import MediaInfoCard from "./features/upload/MediaInfoCard";
import UploadPanel from "./features/upload/UploadPanel";

export default function App() {
  // 지금 작업 중인 파일. 업로드가 끝나면 채워진다.
  const [media, setMedia] = useState<MediaFile | null>(null);

  return (
    <main className="app">
      <header>
        <h1>🎙️ VocalCut Studio</h1>
        <ServerStatus />
      </header>

      <UploadPanel onUploaded={setMedia} />
      {media && <MediaInfoCard media={media} />}
    </main>
  );
}
