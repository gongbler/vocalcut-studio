/**
 * FastAPI 에러 응답에서 사람이 읽을 메시지를 꺼낸다.
 * - 우리가 직접 낸 에러: {"detail": "문장"}
 * - Pydantic 형식 검사 에러: {"detail": [{"loc": [...], "msg": "..."}, ...]}
 */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${d.loc?.at(-1) ?? ""}: ${d.msg ?? ""}`)
      .join(" / ");
  }
  // 백엔드가 꺼져 있으면 화면 서버(Vite)의 프록시가 '빈 내용의 500'을 돌려준다 → 알아듣는 말로
  if (body === null && status >= 500) {
    return "백엔드 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요 (start.cmd).";
  }
  return `요청 실패 (HTTP ${status})`;
}

/** JSON 요청을 보내고, 실패하면 읽기 쉬운 메시지로 에러를 던진다. */
export async function postJson<T>(url: string, data: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  } catch {
    throw new Error("서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as T;
}
