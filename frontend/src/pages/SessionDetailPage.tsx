import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getSession, downloadSession, correctSegmentWithGemini, overrideSegmentAnchor, downvoteCorrection } from "../api";
import type { SessionDetail, RefinedSegment } from "../types";

type ViewMode = "transcript" | "timestamped" | "results";

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${m}:${s.toString().padStart(2, "0")}.${ms}`;
}

const ANCHOR_BADGE: Record<string, string> = {
  greeting: "bg-blue-900/50 text-blue-300",
  introduction: "bg-indigo-900/50 text-indigo-300",
  consent_to_record: "bg-slate-700/50 text-slate-300",
  verification: "bg-cyan-900/50 text-cyan-300",
  account_status: "bg-amber-900/50 text-amber-300",
  probing_rfd: "bg-orange-900/50 text-orange-300",
  probing_sof: "bg-orange-900/50 text-orange-300",
  negotiation: "bg-yellow-900/50 text-yellow-300",
  benefits: "bg-emerald-900/50 text-emerald-300",
  consequences: "bg-red-900/50 text-red-300",
  ptp_commitment: "bg-lime-900/50 text-lime-300",
  payment_channel: "bg-teal-900/50 text-teal-300",
  contact_info: "bg-sky-900/50 text-sky-300",
  recap: "bg-violet-900/50 text-violet-300",
  empathy: "bg-pink-900/50 text-pink-300",
  objection_handling: "bg-rose-900/50 text-rose-300",
  closing: "bg-gray-700/50 text-gray-300",
  third_party: "bg-fuchsia-900/50 text-fuchsia-300",
  general: "bg-gray-800/50 text-gray-400",
};

const ANCHOR_LABEL: Record<string, string> = {
  greeting: "Greeting",
  introduction: "Introduction",
  consent_to_record: "Consent to Record",
  verification: "Verification",
  account_status: "Account Status",
  probing_rfd: "Probing: RFD",
  probing_sof: "Probing: SOF/SOI",
  negotiation: "Negotiation",
  benefits: "Benefits",
  consequences: "Consequences",
  ptp_commitment: "PTP / Commitment",
  payment_channel: "Payment Channel",
  contact_info: "Contact Info",
  recap: "Recap",
  empathy: "Empathy",
  objection_handling: "Objection Handling",
  closing: "Closing",
  third_party: "3rd Party Contact",
  general: "General",
};

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

  // Forward-only stage tracking (skip whisper for text imports)
  const isTextImport = session?.filename?.startsWith("text_import_") ?? false;
  const STAGES = isTextImport
    ? (["lexicon", "ngram", "gemini"] as const)
    : (["whisper", "lexicon", "ngram", "gemini"] as const);
  const [highestStageIdx, setHighestStageIdx] = useState(0);

  const loadSession = useCallback(() => {
    if (!key) return;
    getSession(key)
      .then((data) => {
        setSession(data);
        // Update highest stage (forward-only)
        if (data.processing_stage) {
          const idx = (STAGES as readonly string[]).indexOf(data.processing_stage);
          if (idx >= 0) {
            setHighestStageIdx((prev) => Math.max(prev, idx));
          }
        }
        // Stop polling once processing is done
        if (data.status !== "processing") {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        }
      })
      .catch(() => setError("Session not found"));
  }, [key]);

  useEffect(() => {
    loadSession();
    // Poll every 1s for real-time stage updates
    pollRef.current = setInterval(loadSession, 1000);
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
            <h2 className="text-lg font-semibold text-white">
              {isTextImport ? "Processing Text" : "Processing Audio"}
            </h2>
            <p className="text-sm text-gray-400 max-w-sm">
              {isTextImport
                ? "Refining through the 3-layer correction pipeline. This page will update automatically when complete."
                : "Transcribing with Whisper and refining through the 3-layer correction pipeline. This page will update automatically when complete."
              }
            </p>
          </div>
          <div className="flex gap-3 text-xs text-gray-600">
            {STAGES.map((stage, i, arr) => {
              const labels: Record<string, string> = {
                whisper: "Groq Whisper",
                lexicon: "Lexicon",
                ngram: "N-Gram",
                gemini: "Gemini",
              };
              const isActive = i === highestStageIdx;
              const isPast = i < highestStageIdx;
              return (
                <span key={stage} className="flex items-center gap-1.5">
                  {isPast && (
                    <span className="h-2 w-2 bg-emerald-500 rounded-full" />
                  )}
                  {isActive && (
                    <span className="h-2 w-2 bg-sky-500 rounded-full animate-pulse" />
                  )}
                  <span className={
                    isActive ? "text-sky-400 font-medium" :
                    isPast ? "text-emerald-400/70" : ""
                  }>{labels[stage]}</span>
                  {i < arr.length - 1 && (
                    <span className="text-gray-700 ml-1.5">→</span>
                  )}
                </span>
              );
            })}
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
              {session.tokens_used > 0 && (
                <>
                  {" "}&middot;{" "}
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-violet-900/40 text-violet-400 text-[10px] font-medium" title={`Prompt: ${session.prompt_tokens?.toLocaleString() || 0}, Completion: ${session.completion_tokens?.toLocaleString() || 0}`}>
                    {session.tokens_used >= 1000 
                      ? `${(session.tokens_used / 1000).toFixed(1)}K tokens` 
                      : `${session.tokens_used} tokens`}
                  </span>
                </>
              )}
              {session.completed_at && (
                <>
                  {" "}&middot;{" "}
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-sky-900/40 text-sky-400 text-[10px] font-medium">
                    {(() => {
                      const ms = new Date(session.completed_at).getTime() - new Date(session.created_at).getTime();
                      const sec = Math.round(ms / 1000);
                      return sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`;
                    })()}
                  </span>
                </>
              )}
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
          <SegmentRow key={i} seg={seg} view={view} segIndex={i} sessionKey={key!} onCorrected={loadSession} />
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- */

function SegmentRow({
  seg,
  view,
  segIndex,
  sessionKey,
  onCorrected,
}: {
  seg: RefinedSegment;
  view: ViewMode;
  segIndex: number;
  sessionKey: string;
  onCorrected: () => void;
}) {
  const [showChat, setShowChat] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState("");
  const [showModeOverride, setShowModeOverride] = useState(false);
  const [downvotingIdx, setDownvotingIdx] = useState<number | null>(null);
  const [showDownvoteMenu, setShowDownvoteMenu] = useState<number | null>(null);

  const hasFixes = seg.corrections.length > 0;
  const changed = seg.original_text !== seg.refined_text;

  async function handleDownvote(original: string, corrected: string, action: "blocklist" | "demote", corrIdx: number) {
    setDownvotingIdx(corrIdx);
    setShowDownvoteMenu(null);
    try {
      await downvoteCorrection({ original, corrected, action, sessionKey, segIndex });
      onCorrected();
    } catch {
      // ignore
    } finally {
      setDownvotingIdx(null);
    }
  }

  async function handleSendCorrection() {
    // If empty, use default refinement instruction
    const finalInstruction = instruction.trim() || "Refine and correct this segment";
    setSending(true);
    setChatError("");
    try {
      await correctSegmentWithGemini(sessionKey, segIndex, finalInstruction);
      setInstruction("");
      setShowChat(false);
      onCorrected();
    } catch (e: unknown) {
      setChatError(e instanceof Error ? e.message : "Correction failed");
    } finally {
      setSending(false);
    }
  }

  // Speaker styling
  const speakerStyles: Record<string, string> = {
    agent: "text-sky-400 font-medium",
    client: "text-emerald-400 font-medium",
    mixed: "text-yellow-400 font-medium",
  };
  const speakerLabels: Record<string, string> = {
    agent: "Agent",
    client: "Client",
    mixed: "Mixed",
  };

  if (view === "transcript") {
    return (
      <div className="py-1.5 px-3 hover:bg-gray-900/40 rounded transition-colors">
        <p className="text-sm text-gray-200 leading-relaxed">
          {seg.speaker && (
            <span className={`${speakerStyles[seg.speaker] || "text-gray-400"} mr-1`}>
              {speakerLabels[seg.speaker] || seg.speaker}:
            </span>
          )}
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
          {seg.speaker && (
            <span className={`${speakerStyles[seg.speaker] || "text-gray-400"} mr-1`}>
              {speakerLabels[seg.speaker] || seg.speaker}:
            </span>
          )}
          {seg.refined_text}
        </p>
      </div>
    );
  }

  /* results view */
  return (
    <div className="rounded-lg p-4 mb-2 border bg-gray-800/60 border-gray-700 transition-colors">
      {/* Timestamp + speaker + mode badge */}
      <div className="flex items-center gap-3 mb-2 text-xs text-gray-500">
        <span className="font-mono">
          {fmt(seg.start)} – {fmt(seg.end)}
        </span>
        {seg.speaker && (
          <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
            seg.speaker === "agent" ? "bg-sky-900/50 text-sky-300" :
            seg.speaker === "client" ? "bg-emerald-900/50 text-emerald-300" :
            "bg-yellow-900/50 text-yellow-300"
          }`}>
            {speakerLabels[seg.speaker] || seg.speaker}
          </span>
        )}
        {seg.anchor_mode && (
          <span className="relative inline-block">
            <button
              onClick={() => setShowModeOverride(!showModeOverride)}
              title="Click to change mode"
              className={`px-2 py-0.5 rounded tracking-wide text-[10px] font-medium cursor-pointer hover:ring-1 hover:ring-white/20 ${
                ANCHOR_BADGE[seg.anchor_mode] ?? "bg-gray-700/50 text-gray-400"
              }`}
            >
              {ANCHOR_LABEL[seg.anchor_mode] ?? seg.anchor_mode}
            </button>
            {showModeOverride && (
              <div className="absolute z-50 top-full left-0 mt-1 bg-gray-800 border border-gray-600 rounded-lg shadow-xl py-1 w-48 max-h-60 overflow-y-auto">
                {Object.entries(ANCHOR_LABEL).map(([mode, label]) => (
                  <button
                    key={mode}
                    onClick={async () => {
                      setShowModeOverride(false);
                      if (mode === seg.anchor_mode) return;
                      try {
                        await overrideSegmentAnchor(sessionKey, segIndex, mode);
                        onCorrected();
                      } catch {}
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-gray-700 flex items-center gap-2 ${
                      mode === seg.anchor_mode ? "text-sky-400 font-medium" : "text-gray-300"
                    }`}
                  >
                    <span className={`w-2 h-2 rounded-full shrink-0 ${
                      ANCHOR_BADGE[mode]?.split(" ")[0] ?? "bg-gray-700"
                    }`} />
                    {label}
                  </button>
                ))}
              </div>
            )}
          </span>
        )}
        {changed && (
          <span className="px-2 py-0.5 rounded bg-emerald-900/30 text-emerald-400 text-[10px] font-medium">
            CORRECTED
          </span>
        )}
        <button
          onClick={() => setShowChat(!showChat)}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md shadow-violet-900/30 transition-all hover:shadow-lg hover:shadow-violet-800/40 active:scale-95"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2L14.09 8.26L20 9.27L15.55 13.97L16.91 20L12 16.9L7.09 20L8.45 13.97L4 9.27L9.91 8.26L12 2Z" />
          </svg>
          {showChat ? "Cancel" : "Correct with Gemini"}
        </button>
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

      {/* Gemini correction chat form */}
      {showChat && (
        <div className="mb-3 p-3 rounded-lg bg-gray-900/80 border border-violet-800/40 space-y-2">
          <p className="text-[11px] text-gray-500">
            Describe what needs to be corrected, or leave empty to let Gemini refine the segment.
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !sending && handleSendCorrection()}
              placeholder='e.g. "3,293 pesos and 10 centavos" should be ₱3,293.10'
              className="flex-1 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-600"
              disabled={sending}
            />
            <button
              onClick={handleSendCorrection}
              disabled={sending}
              className="px-4 py-2 rounded-lg bg-violet-700 hover:bg-violet-600 text-white text-sm font-medium transition-colors disabled:opacity-50 whitespace-nowrap"
            >
              {sending ? "Sending..." : instruction.trim() ? "Send" : "Refine Segment"}
            </button>
          </div>
          {chatError && <p className="text-xs text-red-400">{chatError}</p>}
        </div>
      )}

      {/* Corrections */}
      {hasFixes && (
        <div className="flex flex-wrap gap-2 mb-2">
          {seg.corrections.map((c, ci) => (
            <span
              key={ci}
              className="relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-900/60 text-xs group"
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
              {/* Downvote button */}
              <button
                onClick={() => setShowDownvoteMenu(showDownvoteMenu === ci ? null : ci)}
                disabled={downvotingIdx === ci}
                className="ml-1 p-0.5 text-gray-500 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                title="Downvote this correction"
              >
                {downvotingIdx === ci ? (
                  <span className="h-3 w-3 border border-red-400 border-t-transparent rounded-full animate-spin inline-block" />
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                )}
              </button>
              {/* Downvote menu dropdown */}
              {showDownvoteMenu === ci && (
                <div className="absolute top-full right-0 mt-1 z-20 bg-gray-800 border border-gray-700 rounded-lg shadow-xl min-w-[160px] py-1 text-left">
                  <button
                    onClick={() => handleDownvote(c.original, c.corrected, "blocklist", ci)}
                    className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-red-900/30 flex items-center gap-2"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M13.477 14.89A6 6 0 015.11 6.524l8.367 8.368zm1.414-1.414L6.524 5.11a6 6 0 018.367 8.367zM18 10a8 8 0 11-16 0 8 8 0 0116 0z" clipRule="evenodd" />
                    </svg>
                    Blocklist (ban forever)
                  </button>
                  <button
                    onClick={() => handleDownvote(c.original, c.corrected, "demote", ci)}
                    className="w-full text-left px-3 py-1.5 text-xs text-amber-400 hover:bg-amber-900/30 flex items-center gap-2"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                    Demote / Delete rule
                  </button>
                </div>
              )}
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
