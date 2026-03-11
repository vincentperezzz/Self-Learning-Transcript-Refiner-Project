import type {
  AnchorOverride,
  BlocklistRule,
  DomainGlossaryTerm,
  HealthResponse,
  LexiconRule,
  NGramEntry,
  RefinementResponse,
  SemanticAnchor,
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
    // Try to parse JSON error response for better messages
    try {
      const json = JSON.parse(body);
      if (json.detail) {
        throw new Error(json.detail);
      }
    } catch {
      // Not JSON or no detail, fall through
    }
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

export function importPlainText(text: string): Promise<{ session_key: string; status: string; segment_count: number }> {
  return request<{ session_key: string; status: string; segment_count: number }>("/import-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
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

export function deleteLexiconRule(id: number, reason = "") {
  const params = reason ? `?reason=${encodeURIComponent(reason)}` : "";
  return request<{ status: string }>(`/lexicon/${id}${params}`, { method: "DELETE" });
}

export function promoteLexiconRule(id: number) {
  return request<{ status: string; id: number }>(`/lexicon/${id}/promote`, {
    method: "PATCH",
  });
}

export function demoteLexiconRule(id: number) {
  return request<{ status: string; id: number }>(`/lexicon/${id}/demote`, {
    method: "PATCH",
  });
}

// ---------------------------------------------------------------------------
// Correction Downvote (from session detail)
// ---------------------------------------------------------------------------

export function downvoteCorrection(payload: {
  original: string;
  corrected: string;
  action: "blocklist" | "demote" | "both";
  reason?: string;
}) {
  return request<{ status: string; blocklisted: boolean; demoted: boolean; deleted: boolean }>(
    "/corrections/downvote",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

// ---------------------------------------------------------------------------
// Blocklist (Banned Corrections)
// ---------------------------------------------------------------------------

export function listBlocklist(search = "") {
  const params = search ? `?search=${encodeURIComponent(search)}` : "";
  return request<{ rules: BlocklistRule[] }>(`/blocklist${params}`);
}

export function addBlocklistRule(payload: {
  wrong_phrase: string;
  correct_phrase: string;
  reason?: string;
}) {
  return request<{ status: string }>("/blocklist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteBlocklistRule(id: number) {
  return request<{ status: string }>(`/blocklist/${id}`, { method: "DELETE" });
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
    promotion_threshold: number;
  }>("/corrections/log");
}

// ---------------------------------------------------------------------------
// Semantic Anchors
// ---------------------------------------------------------------------------

export function listAnchors(search = "", mode = "") {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (mode) params.set("mode", mode);
  const qs = params.toString();
  return request<{ anchors: SemanticAnchor[] }>(`/anchors${qs ? `?${qs}` : ""}`);
}

export function addAnchor(payload: {
  mode: string;
  label: string;
  pattern: string;
  weight?: number;
}) {
  return request<{ status: string; id: number }>("/anchors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateAnchor(
  id: number,
  payload: {
    mode: string;
    label: string;
    pattern: string;
    weight?: number;
    is_active?: boolean;
  },
) {
  return request<{ status: string }>(`/anchors/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteAnchor(id: number) {
  return request<{ status: string }>(`/anchors/${id}`, { method: "DELETE" });
}

export function toggleAnchor(id: number) {
  return request<{ status: string; id: number; is_active: boolean }>(
    `/anchors/${id}/toggle`,
    { method: "PATCH" },
  );
}

export function overrideSegmentAnchor(
  sessionKey: string,
  segmentIndex: number,
  correctedMode: string,
) {
  return request<{
    status: string;
    segment_index: number;
    original_mode: string;
    corrected_mode: string;
  }>(`/sessions/${sessionKey}/override-anchor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      segment_index: segmentIndex,
      corrected_mode: correctedMode,
    }),
  });
}

export function listAnchorOverrides() {
  return request<{ overrides: AnchorOverride[] }>("/anchor-overrides");
}

// ── Domain Glossary ──

export function listGlossary(search?: string, mode?: string) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (mode) params.set("mode", mode);
  const qs = params.toString();
  return request<{ terms: DomainGlossaryTerm[] }>(`/glossary${qs ? `?${qs}` : ""}`);
}

export function addGlossaryTerm(payload: { anchor_mode: string; term: string }) {
  return request<{ term: DomainGlossaryTerm }>("/glossary", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateGlossaryTerm(id: number, payload: { anchor_mode: string; term: string }) {
  return request<{ term: DomainGlossaryTerm }>(`/glossary/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteGlossaryTerm(id: number) {
  return request<{ deleted: boolean }>(`/glossary/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Co-Word Network
// ---------------------------------------------------------------------------

export interface CoWordNode {
  id: string;
  label: string;
  size: number;
  frequency: number;
  cluster: string;
  color: string;
}

export interface CoWordEdge {
  source: string;
  target: string;
  weight: number;
  width: number;
}

export interface CoWordCluster {
  id: string;
  label: string;
  color: string;
  nodeCount: number;
}

export interface CoWordNetworkData {
  nodes: CoWordNode[];
  edges: CoWordEdge[];
  clusters: CoWordCluster[];
  stats: {
    totalNodes: number;
    totalEdges: number;
    totalClusters: number;
    minFrequency: number;
  };
}

export function getCoWordNetwork(minFrequency = 50, maxNodes = 150) {
  return request<CoWordNetworkData>(
    `/coword-network?min_frequency=${minFrequency}&max_nodes=${maxNodes}`
  );
}
