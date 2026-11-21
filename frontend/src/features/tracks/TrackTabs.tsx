import type { MediaFile } from "../../api/files";
import type { Stems } from "../separation/SeparationPanel";

type Props = {
  source: MediaFile;
  stems: Stems | null;
  activeId: string;
  onSelect: (media: MediaFile) => void;
};

/** 원곡 / 보컬 / MR 중 지금 편집할 트랙을 고르는 탭 */
export default function TrackTabs({ source, stems, activeId, onSelect }: Props) {
  const tabs: { label: string; media: MediaFile }[] = [{ label: "🎵 원곡", media: source }];
  if (stems) {
    tabs.push({ label: "🎤 보컬", media: stems.vocals }, { label: "🎹 MR", media: stems.instrumental });
  }
  if (tabs.length === 1) return null; // 분리 전에는 탭이 필요 없다

  return (
    <nav className="track-tabs" aria-label="편집할 트랙">
      {tabs.map((t) => (
        <button
          key={t.media.id}
          className={`chip ${t.media.id === activeId ? "on" : ""}`}
          aria-pressed={t.media.id === activeId}
          onClick={() => onSelect(t.media)}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}
