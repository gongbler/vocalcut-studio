import { refreshHealth, useHealth } from "../../hooks/useHealth";

/** 화면 상단의 작은 서버 상태 표시줄 + 서버가 꺼졌을 때 켜는 방법 안내 */
export default function ServerStatus() {
  const state = useHealth();

  return (
    <>
      <div className="status-bar">
        {state.kind === "loading" && <span>서버 확인 중…</span>}
        {state.kind === "offline" && <span className="bad">❌ 서버 꺼짐 (3초마다 다시 확인 중)</span>}
        {state.kind === "ok" && (
          <>
            <span className="good">● 서버 v{state.data.version}</span>
            <span className={state.data.ffmpeg.available ? "good" : "bad"}>
              ● FFmpeg {state.data.ffmpeg.available ? "OK" : "없음"}
            </span>
            <span
              className={state.data.separator.available ? "good" : "bad"}
              title={state.data.separator.reason ?? undefined}
            >
              ● AI 분리 {state.data.separator.available ? "OK" : "없음"}
            </span>
            <span
              className={state.data.transcriber.available ? "good" : "bad"}
              title={state.data.transcriber.reason ?? undefined}
            >
              ● AI 자막 {state.data.transcriber.available ? "OK" : "없음"}
            </span>
          </>
        )}
        <button className="small" onClick={() => void refreshHealth()}>
          새로고침
        </button>
      </div>
      {state.kind === "offline" && (
        <div className="offline-banner" role="alert">
          <b>백엔드 서버가 꺼져 있어요.</b> 프로젝트 폴더의 <code>start.cmd</code>를 더블클릭하거나, 터미널에서{" "}
          <code>.\scripts\start.ps1</code>을 실행하세요. 서버가 켜지면 이 안내는 자동으로 사라지고, 하던 작업은 그대로
          이어서 할 수 있어요.
        </div>
      )}
    </>
  );
}
