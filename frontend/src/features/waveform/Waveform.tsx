import { useEffect, useRef, useState, type RefObject } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import { getPeaks } from "../../api/peaks";

type Props = {
  fileId: string;
  /** 이미 화면에 있는 <audio>/<video> 플레이어. 파형은 이 플레이어와 '같은 시계'를 쓴다 */
  playerRef: RefObject<HTMLMediaElement | null>;
  start: number;
  end: number;
  /** 사용자가 파형 위 구간을 끌어서 바꾸면 호출 */
  onRangeChange: (start: number, end: number) => void;
};

const REGION_COLOR = "rgba(124, 92, 255, 0.22)";

/**
 * 파형 + 구간 선택.
 *
 * 핵심 아이디어: wavesurfer 에게 소리 파일을 주지 않는다.
 *  - 소리 재생은 기존 플레이어(media)가 하고,
 *  - 파형 모양은 서버가 미리 계산한 peaks 숫자로 그린다.
 * → 브라우저가 노래 전체를 해석(디코딩)하느라 메모리를 수백 MB 쓰는 일을 피한다.
 */
export default function Waveform({ fileId, playerRef, start, end, onRangeChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const regionRef = useRef<Region | null>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(0);

  // 최신 콜백을 ref 에 보관 → 아래 effect 를 콜백이 바뀔 때마다 다시 만들지 않아도 됨
  const onChangeRef = useRef(onRangeChange);
  onChangeRef.current = onRangeChange;
  const initialRange = useRef({ start, end });

  // ---- 1) 파일이 바뀔 때마다 파형을 새로 만든다 ----
  useEffect(() => {
    const container = containerRef.current;
    const media = playerRef.current;
    if (!container || !media) return;

    let cancelled = false;
    let ws: WaveSurfer | null = null;
    setStatus("loading");

    getPeaks(fileId)
      .then((peaks) => {
        if (cancelled) return; // 기다리는 동안 다른 파일로 바뀌었으면 무시
        const regions = RegionsPlugin.create();
        ws = WaveSurfer.create({
          container,
          media,                      // 기존 플레이어와 연결 (재생 위치 공유)
          peaks: [peaks.values],      // 서버가 계산한 파형 데이터
          duration: peaks.duration_sec,
          height: 96,
          normalize: true,            // 조용한 노래도 파형이 잘 보이게 최대 높이에 맞춤
          waveColor: "#4a5266",
          progressColor: "#7c5cff",
          cursorColor: "#e6e8ee",
          barWidth: 2,
          barGap: 1,
          barRadius: 2,
          dragToSeek: true,
          plugins: [regions],
        });
        wsRef.current = ws;

        ws.on("ready", () => {
          const region = regions.addRegion({
            start: initialRange.current.start,
            end: initialRange.current.end,
            color: REGION_COLOR,
            drag: true,
            resize: true,
          });
          regionRef.current = region;
          setStatus("ready");
        });

        // 구간을 끄는 '중'에도 숫자가 따라 바뀌도록 region-update 사용
        regions.on("region-update", (r) => onChangeRef.current(r.start, r.end));
        regions.on("region-updated", (r) => onChangeRef.current(r.start, r.end));
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
        setStatus("error");
      });

    // 정리(clean-up): 파일이 바뀌거나 화면에서 사라지면 파형을 없앤다
    // (플레이어는 바깥 것이라 wavesurfer 가 지우지 않는다)
    return () => {
      cancelled = true;
      ws?.destroy();
      wsRef.current = null;
      regionRef.current = null;
    };
  }, [fileId, playerRef]);

  // ---- 2) 숫자 입력칸이 바뀌면 파형 위 구간도 따라 움직인다 ----
  useEffect(() => {
    const region = regionRef.current;
    if (!region) return;
    // 0.05초 이상 차이 날 때만 → 드래그 중 '숫자 → 구간 → 숫자' 무한 반복 방지
    if (Math.abs(region.start - start) > 0.05 || Math.abs(region.end - end) > 0.05) {
      if (end > start) region.setOptions({ start, end });
    }
  }, [start, end]);

  // ---- 3) 확대/축소 ----
  useEffect(() => {
    if (status === "ready") wsRef.current?.zoom(zoom);
  }, [zoom, status]);

  return (
    <div className="waveform">
      <div ref={containerRef} className="waveform-canvas" />
      {status === "loading" && <p className="hint">파형 불러오는 중… (처음 한 번은 몇 초 걸려요)</p>}
      {status === "error" && <p className="bad">파형을 표시할 수 없습니다: {error}</p>}
      {status === "ready" && (
        <div className="row space-between hint">
          <span>보라색 구간의 가장자리를 끌어서 시작/끝을 정하고, 가운데를 끌면 구간이 통째로 움직여요</span>
          <label className="row">
            🔍
            <input
              type="range"
              min={0}
              max={200}
              step={10}
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
              aria-label="파형 확대"
              style={{ width: 100 }}
            />
          </label>
        </div>
      )}
    </div>
  );
}
