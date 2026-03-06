import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getSession, downloadSession } from "../api";
import type { SessionDetail, RefinedSegment } from "../types";

type ViewMode = "transcript" | "timestamped" | "results";

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${m}:${s.toString().padStart(2, "0")}.${ms}`;
}

const SOURCE_BADGE: Record<string, string> = {
  lexicon: "bg-emerald-800/60 text-emerald-300",
  ngram_anchor: "bg-sky-800/60 text-sky-300",
  gemini: "bg-violet-800/60 text-violet-300",
};

function confColor(p: number): string {
  if (p >= 0.9) return "text-emerald-400";
  if (p >= 0.7) return "text-yellow-400";
  return "text-red-400";
}

export default function SessionDetailPage() {
  const { key } = useParams<{ key: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewMode>("timestamped");
  const [downloading, setDownloading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [pollCount, setPollCount] = useState(0);

  const loadSession = useCallback(() => {
    if (!key) return;
    getSession(key)
      .then((data) => {
        setSession(data);
        setPollCount((c) => c + 1);
        // Stop polling once processing is done
        if (data.status !== "processing" && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      })
      .catch(() => setError("Session not found"));
  }, [key]);

  useEffect(() => {
    loadSession();
    // Start polling for processing sessions
    pollRef.current = setInterval(loadSession, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadSession]);

  async function handleDownload(format: ViewMode) {
    if (!key) return;
    setDownloading(true);
    try {
      await downloadSession(key, format);
    } catch {
      /* ignore */
    } finally {
      setDownloading(false);
    }
  }

  if (error) {
    return (
      <div>
        <p className="text-red-400">{error}</p>
        <button
          onClick={() => navigate("/")}
          className="mt-2 text-sky-400 text-sm"
        >
          Back to Dashboard
        </button>
      </div>
    );
  }

  if (!session) {
    return <p className="text-gray-500">Loading...</p>;
  }

  // Processing state – show animated waiting screen
  if (session.status === "processing") {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate("/")} className="text-gray-400 hover:text-gray-200 text-sm">
            ← Back
          </button>
          <h1 className="text-xl font-bold text-white">{session.filename}</h1>
        </div>
        <div className="flex flex-col items-center justify-center py-24 space-y-6">
          <div className="relative">
            <div className="h-16 w-16 border-4 border-sky-600/30 border-t-sky-400 rounded-full animate-spin" />
          </div>
          <div className="text-center space-y-2">
            <h2 className="text-lg font-semibold text-white">Processing Audio</h2>
            <p className="text-sm text-gray-400 max-w-sm">
              Transcribing with Whisper and refining through the 3-layer correction pipeline.
              This page will update automatically when complete.
            </p>
            <p className="text-xs text-gray-600 tabular-nums">
              Checking... ({Math.floor(pollCount * 3)}s elapsed)
            </p>
          </div>
          <div className="flex gap-3 text-xs text-gray-600">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 bg-sky-500 rounded-full animate-pulse" />
              Groq Whisper
            </span>
            <span className="text-gray-700">→</span>
            <span>Lexicon</span>
            <span className="text-gray-700">→</span>
            <span>N-Gram</span>
            <span className="text-gray-700">→</span>
            <span>Gemini</span>
          </div>
        </div>
      </div>
    );
  }

  // Failed state
  if (session.status === "failed") {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate("/")} className="text-gray-400 hover:text-gray-200 text-sm">
            ← Back
          </button>
          <h1 className="text-xl font-bold text-white">{session.filename}</h1>
        </div>
        <div className="flex flex-col items-center justify-center py-24 space-y-4">
          <span className="text-5xl">❌</span>
          <h2 className="text-lg font-semibold text-red-400">Processing Failed</h2>
          <p className="text-sm text-gray-400 max-w-md text-center">
            {session.error_message || "An unknown error occurred during transcription."}
          </p>
          <button
            onClick={() => navigate("/upload")}
            className="mt-4 px-5 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-sm font-medium"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  const result = session.result_json;
  const segments: RefinedSegment[] = result?.segments ?? [];
  const correctedCount = segments.filter(
    (s) => s.corrections.length > 0,
  ).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate("/")}
            className="text-gray-400 hover:text-gray-200 text-sm"
          >
            ← Back
          </button>
          <div>
            <h1 className="text-xl font-bold text-white">{session.filename}</h1>
            <p className="text-xs text-gray-500 mt-1">
              {new Date(session.created_at).toLocaleString()} &middot;{" "}
              {session.speaker || "no speaker"} &middot;{" "}
              {session.total_segments} segments &middot;{" "}
              {session.total_corrections} corrections ({correctedCount} segments
              changed)
            </p>
          </div>
        </div>
      </div>

      {/* View mode tabs + download buttons */}
      <div className="flex items-center justify-between border-b border-gray-800 pb-3">
        <div className="flex gap-1">
          {(
            [
              { key: "transcript", label: "Transcript Only" },
              { key: "timestamped", label: "With Timestamps" },
              { key: "results", label: "With Corrections" },
            ] as const
          ).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setView(tab.key)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                view === tab.key
                  ? "bg-sky-600 text-white"
                  : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Downloads */}
        <div className="flex gap-2">
          <button
            onClick={() => handleDownload("transcript")}
            disabled={downloading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-sm text-white font-medium transition-colors disabled:opacity-50"
            title="Download transcript text only"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5m0 0l5-5m-5 5V3" /></svg>
            Transcript
          </button>
          <button
            onClick={() => handleDownload("timestamped")}
            disabled={downloading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-700 hover:bg-sky-600 text-sm text-white font-medium transition-colors disabled:opacity-50"
            title="Download transcript with timestamps"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5m0 0l5-5m-5 5V3" /></svg>
            Timestamps
          </button>
          <button
            onClick={() => handleDownload("results")}
            disabled={downloading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-violet-700 hover:bg-violet-600 text-sm text-white font-medium transition-colors disabled:opacity-50"
            title="Download full results with corrections"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5m0 0l5-5m-5 5V3" /></svg>
            Full Results
          </button>
        </div>
      </div>

      {/* Segments */}
      <div className="space-y-1">
        {segments.map((seg, i) => (
          <SegmentRow key={i} seg={seg} view={view} />
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- */

function SegmentRow({
  seg,
  view,
}: {
  seg: RefinedSegment;
  view: ViewMode;
}) {
  const hasFixes = seg.corrections.length > 0;
  const changed = seg.original_text !== seg.refined_text;

  if (view === "transcript") {
    return (
      <div className="py-1.5 px-3 hover:bg-gray-900/40 rounded transition-colors">
        <p className="text-sm text-gray-200 leading-relaxed">
          {seg.refined_text}
        </p>
      </div>
    );
  }

  if (view === "timestamped") {
    return (
      <div className="flex py-2 px-3 hover:bg-gray-900/40 rounded transition-colors">
        <span className="text-xs text-gray-500 font-mono whitespace-nowrap pt-0.5 w-[130px] shrink-0 text-right pr-4">
          {fmt(seg.start)} – {fmt(seg.end)}
        </span>
        <p className="text-sm text-gray-200 leading-relaxed">
          {seg.refined_text}
        </p>
      </div>
    );
  }

  /* results view */
  return (
    <div className="rounded-lg p-4 mb-2 border bg-gray-800/60 border-gray-700 transition-colors">
      {/* Timestamp + mode badge */}
      <div className="flex items-center gap-3 mb-2 text-xs text-gray-500">
        <span className="font-mono">
          {fmt(seg.start)} – {fmt(seg.end)}
        </span>
        {seg.anchor_mode && (
          <span className="px-2 py-0.5 rounded bg-gray-700/60 uppercase tracking-wide text-[10px]">
            {seg.anchor_mode}
          </span>
        )}
        {changed && (
          <span className="px-2 py-0.5 rounded bg-emerald-900/30 text-emerald-400 text-[10px] font-medium">
            CORRECTED
          </span>
        )}
      </div>

      {/* Text */}
      {hasFixes ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">
              Original
            </div>
            <p className="text-sm text-gray-400 leading-relaxed">
              {seg.original_text}
            </p>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">
              Refined
            </div>
            <p className="text-sm text-gray-100 leading-relaxed font-medium">
              {seg.refined_text}
            </p>
          </div>
        </div>
      ) : (
        <p className="text-sm text-gray-200 leading-relaxed mb-2">
          {seg.refined_text}
        </p>
      )}

      {/* Corrections */}
      {hasFixes && (
        <div className="flex flex-wrap gap-2 mb-2">
          {seg.corrections.map((c, ci) => (
            <span
              key={ci}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-900/60 text-xs"
            >
              <span className="line-through text-red-400/80">{c.original}</span>
              <span className="text-gray-600">→</span>
              <span className="text-emerald-400">{c.corrected}</span>
              <span
                className={`ml-1 px-1.5 py-0 rounded text-[10px] font-medium ${
                  SOURCE_BADGE[c.source] ?? "bg-gray-700 text-gray-300"
                }`}
              >
                {c.source}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* Low-confidence words */}
      {seg.low_confidence_words.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {seg.low_confidence_words.map((w, wi) => (
            <span
              key={wi}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-gray-800/40 text-xs"
            >
              <span className="text-gray-400">{w.word}</span>
              <span
                className={`font-mono text-[10px] ${confColor(w.probability)}`}
              >
                {(w.probability * 100).toFixed(0)}%
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
