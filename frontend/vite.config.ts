import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.VOCALCUT_WEB_PORT ?? 5173),
    // 5173 이 이미 쓰이고 있으면 다른 번호(5174…)로 슬쩍 바꾸지 말고 멈춘다.
    // (바뀐 번호로 켜지면 즐겨찾기·start.ps1 이 여는 주소가 '안 열리는 사이트'가 된다)
    strictPort: true,
    // 프록시: 화면(5173)에서 /api 로 보낸 요청을 백엔드(8000)로 대신 전달한다.
    // 덕분에 브라우저 입장에서는 "같은 주소"로 통신하는 것처럼 보여 CORS 문제가 없다.
    proxy: {
      // VOCALCUT_API 로 다른 백엔드 주소를 쓸 수 있다 (예: 데모 모드 시험용 서버)
      "/api": process.env.VOCALCUT_API ?? "http://127.0.0.1:8000",
    },
  },
});
