import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "../../api/client";

type State =
  | { kind: "loading" }
  | { kind: "ok"; data: HealthResponse }
  | { kind: "error"; message: string };

/** 화면 상단의 작은 서버 상태 표시줄 */
export default function ServerStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const check = () => {
    setState({ kind: "loading" });
    getHealth()
      .then((data) => setState({ kind: "ok", data }))
      .catch((err: Error) => setState({ kind: "error", message: err.message }));
  };

  useEffect(check, []);

  return (
    <div className="status-bar">
      {state.kind === "loading" && <span>서버 확인 중…</span>}
      {state.kind === "error" && (
        <span className="bad" title={state.message}>
          ❌ 서버 연결 안 됨 — <code>.\scripts\run-backend.ps1</code> 실행 확인
        </span>
      )}
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
        </>
      )}
      <button className="small" onClick={check}>
        새로고침
      </button>
    </div>
  );
}
