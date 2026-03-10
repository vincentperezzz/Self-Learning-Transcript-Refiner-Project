/* Types mirroring the Phoenix 3.0 backend schemas */

export interface WordInfo {
  word: string;
  start: number;
  end: number;
  probability: number;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  confidence?: number;
  words?: WordInfo[];
}

export interface CorrectionDetail {
  original: string;
  corrected: string;
  source: "lexicon" | "ngram_anchor" | "gemini";
  confidence_delta?: number;
}

export interface FlaggedWord {
  word: string;
  probability: number;
  start: number;
  end: number;
}

export interface RefinedSegment {
  start: number;
  end: number;
  original_text: string;
  refined_text: string;
  corrections: CorrectionDetail[];
  anchor_mode?: string;
  low_confidence_words: FlaggedWord[];
}

export interface RefinementResponse {
  segments: RefinedSegment[];
  total_corrections: number;
}

export interface HealthResponse {
  status: string;
  service: string;
}

// Auth
export interface User {
  id: number;
  username: string;
  role: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

// Sessions
export interface SessionSummary {
  id: number;
  session_key: string;
  filename: string;
  speaker: string | null;
  status: "processing" | "completed" | "failed";
  processing_stage?: string | null;
  total_segments: number;
  total_corrections: number;
  created_at: string;
  completed_at?: string | null;
}

export interface SessionDetail extends SessionSummary {
  processing_stage?: string | null;
  completed_at?: string | null;
  result_json: RefinementResponse;
  error_message: string | null;
}

// Lexicon
export interface LexiconRule {
  id: number;
  wrong_phrase: string;
  correct_phrase: string;
  context_hint: string | null;
  anchor_mode: string | null;
  is_permanent: boolean;
  created_at: string;
}

// N-Gram
export interface NGramEntry {
  id: number;
  word1: string;
  word2: string;
  word3: string;
  frequency: number;
}

// Blocklist
export interface BlocklistRule {
  id: number;
  wrong_phrase: string;
  correct_phrase: string;
  reason: string | null;
  banned_by: string;
  created_at: string;
}

// Semantic Anchors
export interface SemanticAnchor {
  id: number;
  mode: string;
  label: string;
  pattern: string;
  weight: number;
  is_active: boolean;
  source: string;
  created_at: string;
  updated_at: string;
}

// Anchor Overrides
export interface AnchorOverride {
  id: number;
  segment_text: string;
  original_mode: string;
  corrected_mode: string;
  source: string;
  created_at: string;
  filename: string;
}
