import type { CreatedSession, Report, SessionSetup, SessionSummary } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, `Can't reach the interview server at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const createSession = (setup: SessionSetup) =>
  request<CreatedSession>("/api/sessions", { method: "POST", body: JSON.stringify(setup) });

export const getReport = (id: string) => request<Report>(`/api/sessions/${id}/report`);

export const retryReport = (id: string) =>
  request<{ status: string }>(`/api/sessions/${id}/report/retry`, { method: "POST" });

export const listSessions = () => request<SessionSummary[]>("/api/sessions");

const storageKey = (id: string) => `coach:${id}`;

export function saveConnection(session: CreatedSession) {
  sessionStorage.setItem(
    storageKey(session.session_id),
    JSON.stringify({ token: session.token, livekit_url: session.livekit_url }),
  );
}

export function loadConnection(id: string): { token: string; livekit_url: string } | null {
  try {
    const raw = sessionStorage.getItem(storageKey(id));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
