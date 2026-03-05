import { useEffect, useState } from "react";
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
  distilbert: "bg-violet-800/60 text-violet-300",
};

function confColor(p: number): string {
  if (p >= 0.9) return "text-emerald-400";
  if (p >= 0.7) return "text-yellow-400";
  return "text-red-400";
}

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewMode>("timestamped");
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!id) return;
    getSession(Number(id))
      .then(setSession)
      .catch(() => setError("Session not found"));
  }, [id]);

  async function handleDownload(format: ViewMode) {
    if (!id) return;
    setDownloading(true);
    try {
      await downloadSession(Number(id), format);
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
