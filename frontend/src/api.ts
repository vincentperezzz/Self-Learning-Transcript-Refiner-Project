import type {
  HealthResponse,
  LexiconRule,
  RefinementResponse,
  SessionDetail,
  SessionSummary,
  TokenResponse,
  TranscriptSegment,
  User,
} from "./types";

const API_BASE = "/api/v1";

// ---------------------------------------------------------------------------
// Token storage
// ---------------------------------------------------------------------------

export function getToken(): string | null {
  return localStorage.getItem("phoenix_token");
}

export function setToken(token: string): void {
  localStorage.setItem("phoenix_token", token);
}

export function clearToken(): void {
  localStorage.removeItem("phoenix_token");
}

// ---------------------------------------------------------------------------
// Generic request helper
// ---------------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export async function login(username: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams({ username, password });
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) throw new Error("Invalid credentials");
  const data = (await res.json()) as TokenResponse;
  setToken(data.access_token);
  return data;
}

export function getMe(): Promise<User> {
  return request<User>("/auth/me");
}

export function changePassword(current_password: string, new_password: string) {
  return request<{ status: string }>("/auth/password", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password, new_password }),
  });
}

export function listUsers() {
  return request<{ users: (User & { created_at: string })[] }>("/auth/users");
}

export function createUser(username: string, password: string, role: string) {
  return request<User>("/auth/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, role }),
  });
}

export function deleteUser(userId: number) {
  return request<{ status: string }>(`/auth/users/${userId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Transcription
// ---------------------------------------------------------------------------

export function healthCheck() {
  return request<HealthResponse>("/health");
}

export function refineSegments(segments: TranscriptSegment[]) {
  return request<RefinementResponse>("/refine", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ segments }),
  });
}

export async function transcribeAudio(file: File, speaker?: string): Promise<RefinementResponse> {
  const form = new FormData();
  form.append("file", file);
  const token = getToken();
  const url = speaker
    ? `${API_BASE}/transcribe?speaker=${encodeURIComponent(speaker)}`
    : `${API_BASE}/transcribe`;
  const res = await fetch(url, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<RefinementResponse>;
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export function listSessions() {
  return request<{ sessions: SessionSummary[] }>("/sessions");
}

export function getSession(id: number) {
  return request<SessionDetail>(`/sessions/${id}`);
}

export function deleteSession(id: number) {
  return request<{ status: string }>(`/sessions/${id}`, { method: "DELETE" });
}

export async function downloadSession(
  id: number,
  format: "transcript" | "timestamped" | "results",
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/sessions/${id}/download?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] || `session_${id}_${format}.txt`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Lexicon
// ---------------------------------------------------------------------------

export function listLexicon() {
  return request<{ rules: LexiconRule[] }>("/lexicon");
}

export function addLexiconRule(rule: {
  wrong_phrase: string;
  correct_phrase: string;
  context_hint?: string;
  anchor_mode?: string;
}) {
  return request<{ status: string }>("/lexicon", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  });
}

export function updateLexiconRule(
  id: number,
  rule: {
    wrong_phrase: string;
    correct_phrase: string;
    context_hint?: string;
    anchor_mode?: string;
  },
) {
  return request<{ status: string }>(`/lexicon/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  });
}

export function deleteLexiconRule(id: number) {
  return request<{ status: string }>(`/lexicon/${id}`, { method: "DELETE" });
}
