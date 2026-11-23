import { useCallback, useEffect, useState } from "react";
import { deleteLibraryItem, getStorage, listLibrary, type LibraryItem, type Storage } from "../../api/library";
import { formatBytes, formatDuration } from "../../utils/format";

type Props = {
  currentId: string | null;
  refreshKey: number; // 바뀌면 목록을 다시 불러온다 (새 업로드·분리·결과물 생성 후)
  onOpen: (item: LibraryItem) => void;
  onDeleted: (id: string) => void;
};

const formatDate = (sec: number) =>
  new Date(sec * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** 내 파일: 예전에 올린 파일 다시 열기 · 삭제 · 용량 보기 */
export default function LibraryPanel({ currentId, refreshKey, onOpen, onDeleted }: Props) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [storage, setStorage] = useState<Storage | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, usage] = await Promise.all([listLibrary(), getStorage()]);
      setItems(list);
      setStorage(usage);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const remove = async (item: LibraryItem) => {
    // 되돌릴 수 없으니, 무엇이 함께 지워지는지 보여주고 한 번 더 묻는다
    const extra = [
      item.stems && "분리된 보컬 · MR",
      item.output_count > 0 && `만든 결과물 ${item.output_count}개`,
      item.has_subtitles && "자막",
    ].filter(Boolean);
    const message =
      `'${item.original_name}'을(를) 삭제할까요?\n\n` +
      (extra.length ? `함께 삭제: ${extra.join(", ")}\n` : "") +
      `확보되는 용량: ${formatBytes(item.size_bytes)}\n\n⚠️ 삭제하면 되돌릴 수 없어요.`;
    if (!confirm(message)) return;

    setBusyId(item.id);
    setError(null);
    try {
      const r = await deleteLibraryItem(item.id);
      setNotice(`🗑 '${item.original_name}' 삭제 완료 · ${formatBytes(r.freed_bytes)} 확보`);
      onDeleted(item.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="card">
      <button className="library-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <h2>
          {open ? "▾" : "▸"} 📂 내 파일
          {items && (
            <span className="hint">
              {" "}
              · {items.length}개{storage && ` · 작업 공간 ${formatBytes(storage.workspace_bytes)}`}
            </span>
          )}
        </h2>
      </button>

      {open && (
        <>
          {storage && (
            <p className="hint">
              올린 파일 {formatBytes(storage.uploads_bytes)} · 결과물 {formatBytes(storage.outputs_bytes)} · AI 모델{" "}
              {formatBytes(storage.models_bytes)} · 디스크 남은 공간 {formatBytes(storage.disk_free_bytes)}
            </p>
          )}
          {notice && <p className="good">{notice}</p>}
          {error && <p className="bad">❌ {error}</p>}
          {items?.length === 0 && <p className="hint">아직 올린 파일이 없어요.</p>}

          <ul className="library-list">
            {items?.map((item) => (
              <li key={item.id} className={item.id === currentId ? "current" : ""}>
                <div className="library-name">
                  <b title={item.original_name}>
                    {item.kind === "video" ? "🎬" : "🎧"} {item.original_name}
                  </b>
                  <span className="hint">
                    {formatDuration(item.duration_sec)} · {formatDate(item.created_at)} · {formatBytes(item.size_bytes)}
                    {item.stems && " · 🎤 분리됨"}
                    {item.has_subtitles && " · 💬 자막"}
                    {item.output_count > 0 && ` · 결과물 ${item.output_count}`}
                  </span>
                </div>
                <span className="row">
                  {item.id === currentId ? (
                    <span className="good hint">열려 있음</span>
                  ) : (
                    <button className="small" onClick={() => onOpen(item)}>
                      열기
                    </button>
                  )}
                  <button className="small danger" onClick={() => remove(item)} disabled={busyId !== null}>
                    {busyId === item.id ? "삭제 중…" : "삭제"}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
