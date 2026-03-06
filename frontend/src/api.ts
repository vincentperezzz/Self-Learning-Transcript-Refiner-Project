import type {
  HealthResponse,
  LexiconRule,
  NGramEntry,
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

export async function transcribeAudio(file: File, speaker?: string): Promise<{ session_key: string; status: string }> {
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
  return res.json() as Promise<{ session_key: string; status: string }>;
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export function listSessions() {
  return request<{ sessions: SessionSummary[] }>("/sessions");
}

export function getSession(key: string) {
  return request<SessionDetail>(`/sessions/${key}`);
}

export function deleteSession(key: string) {
  return request<{ status: string }>(`/sessions/${key}`, { method: "DELETE" });
}

export function correctSegmentWithGemini(
  key: string,
  segmentIndex: number,
  instruction: string,
) {
  return request<{
    corrected_text: string;
    changes: { original: string; corrected: string }[];
    segment_index: number;
  }>(`/sessions/${key}/correct-segment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ segment_index: segmentIndex, instruction }),
  });
}

export async function downloadSession(
  key: string,
  format: "transcript" | "timestamped" | "results",
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/sessions/${key}/download?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] || `session_${key}_${format}.txt`;
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

// ---------------------------------------------------------------------------
// N-Gram
// ---------------------------------------------------------------------------

export function listNgrams(search = "", limit = 200, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (search) params.set("search", search);
  return request<{ total: number; ngrams: NGramEntry[] }>(`/ngram?${params}`);
}

export function deleteNgram(id: number) {
  return request<{ status: string }>(`/ngram/${id}`, { method: "DELETE" });
}

export function updateNgramFrequency(id: number, frequency: number) {
  return request<{ status: string }>(`/ngram/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ frequency }),
  });
}

// ---------------------------------------------------------------------------
// Self-Learning / Corrections
// ---------------------------------------------------------------------------

export function getPromotionCandidates() {
  return request<{
    count: number;
    candidates: {
      original: string;
      corrected: string;
      source: string;
      occurrences: number;
    }[];
  }>("/corrections/candidates");
}

export function triggerAutoPromote() {
  return request<{
    promoted: number;
    rejected: number;
    results: {
      original: string;
      corrected: string;
      approved: boolean;
      reason: string;
    }[];
  }>("/corrections/promote", { method: "POST" });
}

export function getCorrectionLog() {
  return request<{
    entries: {
      original_phrase: string;
      corrected_phrase: string;
      source: string;
      occurrences: number;
      promoted: boolean;
      last_seen_at: string;
    }[];
  }>("/corrections/log");
}
