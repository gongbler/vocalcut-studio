import { useEffect, useRef, useState } from "react";
import type { EditOutput } from "./api/edits";
import { getMedia, type MediaFile } from "./api/files";
import { listLibrary, type LibraryItem } from "./api/library";
import ErrorBoundary from "./components/ErrorBoundary";
import EditPanel from "./features/editor/EditPanel";
import ResultCard from "./features/editor/ResultCard";
import ServerStatus from "./features/health/ServerStatus";
import LibraryPanel from "./features/library/LibraryPanel";
import MixerPanel from "./features/mixer/MixerPanel";
import SeparationPanel, { type Stems } from "./features/separation/SeparationPanel";
import SubtitlePanel from "./features/subtitles/SubtitlePanel";
import TrackTabs from "./features/tracks/TrackTabs";
import MediaInfoCard from "./features/upload/MediaInfoCard";
import UploadPanel from "./features/upload/UploadPanel";

// 마지막으로 연 파일을 브라우저에 기억 → 새로고침해도 이어서 작업
// (브라우저가 저장소를 막아 둔 경우에도 앱은 정상 동작해야 하므로 try/catch)
const LAST_FILE_KEY = "vocalcut:lastFileId";
const remember = (id: string | null) => {
  try {
    if (id) localStorage.setItem(LAST_FILE_KEY, id);
    else localStorage.removeItem(LAST_FILE_KEY);
  } catch {
    /* 저장 못 해도 괜찮음 */
  }
};
const recall = () => {
  try {
    return localStorage.getItem(LAST_FILE_KEY);
  } catch {
    return null;
  }
};

export default function App() {
  // source: 사용자가 올린 원곡 / stems: AI 분리 결과 / active: 지금 보고·편집 중인 트랙
  const [source, setSource] = useState<MediaFile | null>(null);
  const [stems, setStems] = useState<Stems | null>(null);
  const [active, setActive] = useState<MediaFile | null>(null);
  const [output, setOutput] = useState<EditOutput | null>(null);
  const [libraryKey, setLibraryKey] = useState(0); // +1 하면 '내 파일' 목록을 다시 불러온다
  const [openError, setOpenError] = useState<string | null>(null);
  const refreshLibrary = () => setLibraryKey((k) => k + 1);

  // 플레이어를 편집 패널·파형과 공유하기 위한 '손잡이'
  const playerRef = useRef<HTMLMediaElement | null>(null);

  const show = (m: MediaFile, s: Stems | null) => {
    setSource(m);
    setActive(m);
    setStems(s);
    setOutput(null); // 다른 파일을 열면 이전 결과물은 치운다
    setOpenError(null);
    remember(m.id);
  };

  const onUploaded = (m: MediaFile) => {
    show(m, null);
    refreshLibrary();
  };

  const onSeparated = (s: Stems) => {
    setStems(s);
    setActive(s.vocals); // 분리가 끝나면 바로 보컬 트랙을 보여준다
    refreshLibrary();
  };

  const onRendered = (o: EditOutput) => {
    setOutput(o);
    refreshLibrary();
  };

  /** '내 파일'에서 열기: 원곡 + (있으면) 분리된 보컬/MR 을 불러온다 */
  const openItem = async (item: LibraryItem) => {
    try {
      const [m, vocals, instrumental] = await Promise.all([
        getMedia(item.id),
        item.stems ? getMedia(item.stems.vocals) : null,
        item.stems ? getMedia(item.stems.instrumental) : null,
      ]);
      show(m, vocals && instrumental ? { vocals, instrumental } : null);
    } catch (err) {
      setOpenError(`파일을 열 수 없어요: ${(err as Error).message}`);
    }
  };

  const onDeleted = (id: string) => {
    if (source?.id !== id) return;
    setSource(null); // 지금 열려 있던 파일을 지웠으면 화면을 비운다
    setActive(null);
    setStems(null);
    setOutput(null);
    remember(null);
  };

  // 처음 열 때: 마지막으로 작업하던 파일이 아직 있으면 다시 연다
  useEffect(() => {
    // 주소에 ?file=<id> 가 있으면 그 파일을 연다 (즐겨찾기·README 화면 캡처용), 없으면 마지막 파일
    const last = new URLSearchParams(location.search).get("file") ?? recall();
    if (!last) return;
    let ignore = false;
    listLibrary()
      .then((items) => {
        const item = items.find((i) => i.id === last);
        if (!ignore && item) void openItem(item);
        else if (!item) remember(null); // 지워진 파일
      })
      .catch(() => undefined); // 서버가 꺼져 있으면 그냥 빈 화면으로 시작
    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="app">
      <header>
        <h1>🎙️ VocalCut Studio</h1>
        <ServerStatus />
      </header>

      {/* 패널마다 '오류 경계'로 감싼다 → 한 패널에서 오류가 나도 그 패널만 안내로 바뀌고 나머지는 계속 쓸 수 있다.
          key 는 경계에 둔다: 다른 파일을 열면 경계도 새로 만들어져 이전 오류 표시가 사라진다. */}
      <ErrorBoundary name="파일 올리기">
        <UploadPanel onUploaded={onUploaded} />
      </ErrorBoundary>
      <ErrorBoundary name="내 파일">
        <LibraryPanel currentId={source?.id ?? null} refreshKey={libraryKey} onOpen={openItem} onDeleted={onDeleted} />
      </ErrorBoundary>
      {openError && <p className="bad">❌ {openError}</p>}
      {source && active && (
        <>
          <ErrorBoundary key={`b-player-${active.id}`} name="플레이어">
            <TrackTabs source={source} stems={stems} activeId={active.id} onSelect={setActive} />
            <MediaInfoCard media={active} playerRef={playerRef} />
          </ErrorBoundary>
          {/* key 가 바뀌면 React 가 패널을 새로 만든다 → 트랙을 바꿀 때마다 입력값 초기화.
              ⚠️ 같은 묶음 안의 key 는 서로 겹치면 안 된다. 원곡 탭에서는 active.id === source.id 라서
              앞에 'edit-' / 'sep-' 를 붙여 구분한다 (안 그러면 이전 패널이 지워지지 않고 쌓인다) */}
          <ErrorBoundary key={`edit-${active.id}`} name="자르기 · 볼륨 · 페이드">
            <EditPanel media={active} playerRef={playerRef} onRendered={onRendered} />
          </ErrorBoundary>
          {source.audio && (
            <ErrorBoundary key={`sep-${source.id}`} name="보컬 / MR 분리">
              <SeparationPanel source={source} stems={stems} onSeparated={onSeparated} />
            </ErrorBoundary>
          )}
          {source.audio && (
            // 분리가 끝나면 key 가 바뀌어 믹서가 'MR + 원곡 보컬' 구성으로 새로 시작한다
            <ErrorBoundary key={`mix-${source.id}-${stems?.vocals.id ?? "none"}`} name="믹서">
              <MixerPanel source={source} stems={stems} onRendered={onRendered} />
            </ErrorBoundary>
          )}
        </>
      )}
      {source && source.audio && (
        <ErrorBoundary key={`sub-${source.id}`} name="자동 자막">
          <SubtitlePanel source={source} stems={stems} playerRef={playerRef} onRendered={onRendered} />
        </ErrorBoundary>
      )}
      {output && (
        <ErrorBoundary key={output.id} name="결과물">
          <ResultCard output={output} />
        </ErrorBoundary>
      )}
    </main>
  );
}
