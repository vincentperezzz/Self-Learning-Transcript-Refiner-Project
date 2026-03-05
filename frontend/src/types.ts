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
  source: "lexicon" | "ngram_anchor" | "distilbert";
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
