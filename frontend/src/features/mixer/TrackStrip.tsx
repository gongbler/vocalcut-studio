import type { MediaFile } from "../../api/files";

export type TrackState = {
  key: string;
  media: MediaFile;
  label: string;
  volumeDb: number;
  offsetMs: number; // 싱크: + 늦게(밀기) / − 일찍(당기기), 밀리초 단위
  low: number;
  mid: number;
  high: number;
  muted: boolean;
  removable: boolean; // 사용자가 추가한 트랙만 지울 수 있다
};

/** 바꿀 값을 직접 주거나, '최신 값을 받아 바꿀 값을 계산하는 함수'를 준다 */
export type TrackPatch = Partial<TrackState> | ((current: TrackState) => Partial<TrackState>);

type Props = {
  track: TrackState;
  onChange: (patch: TrackPatch) => void;
  onRemove: () => void;
};

const fmtDb = (v: number) => `${v > 0 ? "+" : ""}${v} dB`;

function Slider(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  hint?: string;
}) {
  return (
    <label className="slider" title={props.hint}>
      <span className="row space-between">
        <span>{props.label}</span>
        <b>{fmtDb(props.value)}</b>
      </span>
      <input
        type="range"
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
        onDoubleClick={() => props.onChange(0)} // 더블클릭하면 0으로 되돌리기
      />
    </label>
  );
}

/** 믹서의 트랙 한 줄: 음소거 · 볼륨 · 싱크 · 3밴드 EQ */
export default function TrackStrip({ track, onChange, onRemove }: Props) {
  // ⚠️ track.offsetMs + ms 로 계산하면 안 된다: 버튼을 빠르게 연달아 누르면 화면이 다시 그려지기 전이라
  //    매번 '옛날 값'을 보고 계산해서 마지막 클릭만 남는다(stale closure).
  //    대신 '최신 값을 받아서 계산하는 함수'를 넘겨, React 가 차례대로 적용하게 한다.
  const nudge = (ms: number) =>
    onChange((cur) => ({ offsetMs: Math.max(-30000, Math.min(30000, cur.offsetMs + ms)) }));

  return (
    <div className={`track-strip ${track.muted ? "muted" : ""}`}>
      <div className="row space-between">
        <b className="track-name" title={track.media.original_name}>
          {track.label}
        </b>
        <span className="row">
          <button
            className={`small ${track.muted ? "danger" : ""}`}
            aria-pressed={track.muted}
            onClick={() => onChange({ muted: !track.muted })}
          >
            {track.muted ? "🔇 음소거됨" : "🔊 음소거"}
          </button>
          {track.removable && (
            <button className="small" onClick={onRemove} aria-label={`${track.label} 트랙 제거`}>
              ✕
            </button>
          )}
        </span>
      </div>

      <div className="strip-grid">
        <Slider label="볼륨" value={track.volumeDb} min={-30} max={12} step={0.5}
          onChange={(v) => onChange({ volumeDb: v })} hint="더블클릭하면 0dB" />

        <div className="sync">
          <span className="row space-between">
            <span>싱크</span>
            <b>
              {track.offsetMs > 0 ? "+" : ""}
              {track.offsetMs} ms
            </b>
          </span>
          <div className="row nudge">
            <button className="small" onClick={() => nudge(-100)}>−100</button>
            <button className="small" onClick={() => nudge(-10)}>−10</button>
            <input
              type="number"
              step={10}
              value={track.offsetMs}
              onChange={(e) => onChange({ offsetMs: Math.round(Number(e.target.value)) })}
              aria-label={`${track.label} 싱크 (밀리초)`}
            />
            <button className="small" onClick={() => nudge(10)}>+10</button>
            <button className="small" onClick={() => nudge(100)}>+100</button>
          </div>
          <span className="hint">+ 늦게 시작(밀기) · − 일찍 시작(당기기)</span>
        </div>

        <Slider label="저음 (100Hz↓)" value={track.low} min={-12} max={12} step={1}
          onChange={(v) => onChange({ low: v })} hint="웅웅거림이 심하면 줄이세요. 더블클릭하면 0" />
        <Slider label="중음 (1kHz)" value={track.mid} min={-12} max={12} step={1}
          onChange={(v) => onChange({ mid: v })} hint="목소리의 몸통. 더블클릭하면 0" />
        <Slider label="고음 (8kHz↑)" value={track.high} min={-12} max={12} step={1}
          onChange={(v) => onChange({ high: v })} hint="선명함·숨소리. 더블클릭하면 0" />
      </div>
    </div>
  );
}
