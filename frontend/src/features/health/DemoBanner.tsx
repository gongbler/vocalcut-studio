import { getSession } from "../../session";

/** 데모 사이트 안내 띠: 무엇을 올려도 되는지, 언제 지워지는지 (평소 모드에서는 안 보임) */
export default function DemoBanner() {
  const { demo, limits } = getSession();
  if (!demo || !limits) return null;
  return (
    <div className="demo-banner" role="note">
      <b>🧪 체험용 데모</b> · <b>본인에게 권리가 있는 파일만</b> 올려 주세요 (직접 녹음한 노래, 무료 음원 등). 올린 파일은
      나만 볼 수 있고 <b>약 {limits.file_ttl_minutes}분 뒤 자동으로 삭제</b>돼요.
      <br />
      <small>
        파일은 {limits.upload_mb}MB · {limits.media_minutes}분 이하, 보컬 분리와 자동 자막은 {limits.ai_minutes}분 이하.
        무료 서버(CPU)라 AI 작업은 몇 분 걸릴 수 있어요. 작업은 한 번에 하나씩 할 수 있어요.
      </small>
    </div>
  );
}
