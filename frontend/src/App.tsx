import { useRef, useState } from "react";
import type { EditOutput } from "./api/edits";
import type { MediaFile } from "./api/files";
import EditPanel from "./features/editor/EditPanel";
import ResultCard from "./features/editor/ResultCard";
import ServerStatus from "./features/health/ServerStatus";
import MixerPanel from "./features/mixer/MixerPanel";
import SeparationPanel, { type Stems } from "./features/separation/SeparationPanel";
import TrackTabs from "./features/tracks/TrackTabs";
import MediaInfoCard from "./features/upload/MediaInfoCard";
import UploadPanel from "./features/upload/UploadPanel";

export default function App() {
  // source: 사용자가 올린 원곡 / stems: AI 분리 결과 / active: 지금 보고·편집 중인 트랙
  const [source, setSource] = useState<MediaFile | null>(null);
  const [stems, setStems] = useState<Stems | null>(null);
  const [active, setActive] = useState<MediaFile | null>(null);
  const [output, setOutput] = useState<EditOutput | null>(null);

  // 플레이어를 편집 패널·파형과 공유하기 위한 '손잡이'
  const playerRef = useRef<HTMLMediaElement | null>(null);

  const onUploaded = (m: MediaFile) => {
    setSource(m);
    setActive(m);
    setStems(null);
    setOutput(null); // 새 파일을 올리면 이전 결과물은 치운다
  };

  const onSeparated = (s: Stems) => {
    setStems(s);
    setActive(s.vocals); // 분리가 끝나면 바로 보컬 트랙을 보여준다
  };

  return (
    <main className="app">
      <header>
        <h1>🎙️ VocalCut Studio</h1>
        <ServerStatus />
      </header>

      <UploadPanel onUploaded={onUploaded} />
      {source && active && (
        <>
          <TrackTabs source={source} stems={stems} activeId={active.id} onSelect={setActive} />
          <MediaInfoCard media={active} playerRef={playerRef} />
          {/* key 가 바뀌면 React 가 패널을 새로 만든다 → 트랙을 바꿀 때마다 입력값 초기화.
              ⚠️ 같은 묶음 안의 key 는 서로 겹치면 안 된다. 원곡 탭에서는 active.id === source.id 라서
              앞에 'edit-' / 'sep-' 를 붙여 구분한다 (안 그러면 이전 패널이 지워지지 않고 쌓인다) */}
          <EditPanel key={`edit-${active.id}`} media={active} playerRef={playerRef} onRendered={setOutput} />
          {source.audio && (
            <SeparationPanel key={`sep-${source.id}`} source={source} stems={stems} onSeparated={onSeparated} />
          )}
          {source.audio && (
            // 분리가 끝나면 key 가 바뀌어 믹서가 'MR + 원곡 보컬' 구성으로 새로 시작한다
            <MixerPanel
              key={`mix-${source.id}-${stems?.vocals.id ?? "none"}`}
              source={source}
              stems={stems}
              onRendered={setOutput}
            />
          )}
        </>
      )}
      {output && <ResultCard key={output.id} output={output} />}
    </main>
  );
}
