import type { RefinedSegment } from "../types";

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const SOURCE_BADGE: Record<string, string> = {
  lexicon: "bg-emerald-700 text-emerald-100",
  ngram_anchor: "bg-sky-700 text-sky-100",
  gemini: "bg-violet-700 text-violet-100",
};

function confColor(p: number): string {
  if (p >= 0.9) return "text-emerald-400";
  if (p >= 0.7) return "text-yellow-400";
  return "text-red-400";
}

interface Props {
  segments: RefinedSegment[];
  totalCorrections: number;
}

export default function ResultsPanel({ segments, totalCorrections }: Props) {
  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Refined Output</h2>
        <span className="text-sm text-gray-400">
          {totalCorrections} correction{totalCorrections !== 1 && "s"} applied
        </span>
      </div>

      <div className="space-y-4">
        {segments.map((seg, i) => (
          <div
            key={i}
            className="bg-gray-800 rounded-lg border border-gray-700 p-4"
          >
            {/* Header */}
            <div className="flex items-center gap-3 mb-3 text-xs text-gray-400">
              <span className="font-mono">
                {fmt(seg.start)} – {fmt(seg.end)}
              </span>
              {seg.anchor_mode && (
                <span className="px-2 py-0.5 rounded bg-gray-700 uppercase tracking-wide">
                  {seg.anchor_mode}
                </span>
              )}
            </div>

            {/* Original vs Refined */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
                  Original
                </div>
                <p className="text-gray-300 text-sm leading-relaxed">
                  {seg.original_text}
                </p>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
                  Refined
                </div>
                <p className="text-gray-100 text-sm leading-relaxed font-medium">
                  {seg.refined_text}
                </p>
              </div>
            </div>

            {/* Corrections */}
            {seg.corrections.length > 0 && (
              <div className="mb-3">
                <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
                  Corrections
                </div>
                <div className="flex flex-wrap gap-2">
                  {seg.corrections.map((c, ci) => (
                    <span
                      key={ci}
                      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs"
                    >
                      <span className="line-through text-red-400">
                        {c.original}
                      </span>
                      <span className="text-gray-500">→</span>
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
              </div>
            )}

            {/* Low-confidence words */}
            {seg.low_confidence_words.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
                  Low-Confidence Words
                </div>
                <div className="flex flex-wrap gap-2">
                  {seg.low_confidence_words.map((w, wi) => (
                    <span
                      key={wi}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-gray-700/50 text-xs"
                    >
                      <span className="font-medium">{w.word}</span>
                      <span className={`font-mono text-[11px] ${confColor(w.probability)}`}>
                        {(w.probability * 100).toFixed(0)}%
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
