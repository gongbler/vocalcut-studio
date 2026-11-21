import { useRef, useState, type DragEvent } from "react";
import { uploadFile, type MediaFile } from "../../api/files";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.mp3,.wav,.m4a,.aac,.flac,.ogg";

type Status =
  | { kind: "idle" }
  | { kind: "uploading"; name: string; percent: number }
  | { kind: "error"; message: string };

type Props = { onUploaded: (media: MediaFile) => void };

export default function UploadPanel({ onUploaded }: Props) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const start = async (file: File) => {
    setStatus({ kind: "uploading", name: file.name, percent: 0 });
    try {
      const media = await uploadFile(file, (percent) =>
        setStatus({ kind: "uploading", name: file.name, percent }),
      );
      setStatus({ kind: "idle" });
      onUploaded(media);
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) start(file);
  };

  const busy = status.kind === "uploading";

  return (
    <section className="card">
      <h2>파일 올리기</h2>

      <div
        className={`dropzone ${dragOver ? "over" : ""} ${busy ? "busy" : ""}`}
        onClick={() => !busy && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={busy ? undefined : onDrop}
      >
        {busy ? (
          <>
            <p>⏫ {status.name} 업로드 중… {status.percent}%</p>
            <div className="progress">
              <div className="bar" style={{ width: `${status.percent}%` }} />
            </div>
            {status.percent === 100 && <p className="hint">서버에서 파일 분석 중…</p>}
          </>
        ) : (
          <>
            <p>🎵 영상/오디오 파일을 끌어다 놓거나 클릭해서 선택</p>
            <p className="hint">MP4, MOV, MKV, WEBM, MP3, WAV, M4A, FLAC 등 · 최대 2GB</p>
          </>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) start(file);
          e.target.value = ""; // 같은 파일을 다시 골라도 onChange 가 동작하도록
        }}
      />

      {status.kind === "error" && <p className="bad">❌ {status.message}</p>}
    </section>
  );
}
