// 파일 업로드/조회 API 호출 함수

export type MediaFile = {
  id: string;
  original_name: string;
  kind: "video" | "audio";
  format_name: string;
  duration_sec: number;
  size_bytes: number;
  video: { codec: string; width: number; height: number; fps: number | null } | null;
  audio: { codec: string; sample_rate: number; channels: number } | null;
  content_url: string;
};

/**
 * 파일을 서버에 올린다.
 * fetch 는 '업로드 진행률'을 알려주지 않아서, 진행률 이벤트가 있는 XMLHttpRequest 를 쓴다.
 */
export function uploadFile(
  file: File,
  onProgress: (percent: number) => void,
): Promise<MediaFile> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file); // 백엔드의 `file: UploadFile` 이름과 일치해야 함

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/files");

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };

    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* JSON 이 아닌 응답 */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as MediaFile);
      } else {
        // FastAPI 에러 응답은 {"detail": "..."} 모양
        const detail = (body as { detail?: string } | null)?.detail;
        reject(new Error(detail ?? `업로드 실패 (HTTP ${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요."));

    xhr.send(form);
  });
}
