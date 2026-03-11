import { useEffect, useState } from "react";
import { getCorrectionLog } from "../api";
import Pagination from "../components/Pagination";

interface LogEntry {
  original_phrase: string;
  corrected_phrase: string;
  source: string;
  occurrences: number;
  promoted: boolean;
  blocklisted?: boolean;  
  last_seen_at: string;
}

export default function SelfLearningPage() {
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");  
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [promotionThreshold, setPromotionThreshold] = useState(3);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const logData = await getCorrectionLog();
      setLogEntries(logData.entries);
      if (logData.promotion_threshold) setPromotionThreshold(logData.promotion_threshold);
    } catch (e) {
      console.error("Failed to load self-learning data:", e);
    } finally {
      setLoading(false);
    }
  }

  const sourceCounts = logEntries.reduce<Record<string, number>>((acc, e) => {
    acc[e.source] = (acc[e.source] || 0) + 1;
    return acc;
  }, {});

  const filtered = logEntries.filter((e) => {
    // Source filter
    if (filter !== "all" && e.source !== filter) return false;
    // Status filter
    if (statusFilter === "probationary" && (e.promoted || e.blocklisted)) return false;
    if (statusFilter === "promoted" && !e.promoted) return false;
    if (statusFilter === "blocklisted" && !e.blocklisted) return false;
    return true;
  });

  const paged = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  function statusBadge(entry: LogEntry) {
    // Show blocklisted status first (takes priority)
    if (entry.blocklisted) {
      return (
        <span className="text-xs bg-red-900/50 text-red-400 px-2 py-0.5 rounded-full">
          Blocklisted
        </span>
      );
    }
    if (entry.source === "lexicon") {
      return (
        <span className="text-xs bg-blue-900/50 text-blue-400 px-2 py-0.5 rounded-full">
          Known Rule
        </span>
      );
    }
    // gemini and ngram_anchor both start as probationary
    if (entry.promoted) {
      return (
        <span className="text-xs bg-emerald-900/50 text-emerald-400 px-2 py-0.5 rounded-full">
          Promoted → Permanent
        </span>
      );
    }
    return (
      <span className="text-xs bg-amber-900/50 text-amber-400 px-2 py-0.5 rounded-full">
        Probationary ({entry.occurrences}/{promotionThreshold})
      </span>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Self-Learning</h1>
        <p className="text-sm text-gray-400 mt-1">
          All corrections are logged automatically. Both Gemini and N-Gram corrections
          start as probationary lexicon rules. After {promotionThreshold} occurrences, they are
          auto-promoted to permanent.
        </p>
      </div>

      {/* Source filter cards */}
      <div className="flex gap-3">
        <button
          onClick={() => { setFilter("all"); setStatusFilter("all"); setCurrentPage(1); }}
          className={`flex-1 rounded-lg border p-3 text-center transition-colors ${
            filter === "all"
              ? "bg-gray-700/60 border-gray-500"
              : "bg-gray-900/40 border-gray-700 hover:border-gray-600"
          }`}
        >
          <div className="text-2xl font-bold text-white">{logEntries.length}</div>
          <div className="text-[10px] text-gray-400 mt-0.5">All Sources</div>
        </button>
        {[
          { key: "lexicon", label: "Lexicon (Known)", color: "text-blue-400" },
          { key: "ngram_anchor", label: "N-Gram (Auto)", color: "text-purple-400" },
          { key: "gemini", label: "Gemini (Auto)", color: "text-violet-400" },
        ].map((s) => (
          <button
            key={s.key}
            onClick={() => { setFilter(filter === s.key ? "all" : s.key); setStatusFilter("all"); setCurrentPage(1); }}
            className={`flex-1 rounded-lg border p-3 text-center transition-colors ${
              filter === s.key
                ? "bg-gray-700/60 border-gray-500"
                : "bg-gray-900/40 border-gray-700 hover:border-gray-600"
            }`}
          >
            <div className={`text-2xl font-bold ${s.color}`}>
              {sourceCounts[s.key] || 0}
            </div>
            <div className="text-[10px] text-gray-400 mt-0.5">{s.label}</div>
          </button>
        ))}
      </div>

      {/* Status filter (only show when Gemini or N-Gram selected) */}
      {(filter === "gemini" || filter === "ngram_anchor") && (
        <div className="flex gap-2 items-center">
          <span className="text-xs text-gray-500 mr-2">Status:</span>
          {[
            { key: "all", label: "All", color: "gray" },
            { key: "probationary", label: "Probationary", color: "amber" },
            { key: "promoted", label: "Promoted", color: "emerald" },
            { key: "blocklisted", label: "Blocklisted", color: "red" },
          ].map((s) => (
            <button
              key={s.key}
              onClick={() => { setStatusFilter(statusFilter === s.key ? "all" : s.key); setCurrentPage(1); }}
              className={`text-xs px-3 py-1 rounded-full transition-colors ${
                statusFilter === s.key
                  ? `bg-${s.color}-900/60 text-${s.color}-400 border border-${s.color}-700`
                  : "bg-gray-800/40 text-gray-400 border border-gray-700 hover:border-gray-600"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading...</div>
      ) : logEntries.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <div className="text-4xl mb-3">📝</div>
          <p>No corrections logged yet.</p>
          <p className="text-xs mt-1">Process some transcripts to see correction data here.</p>
        </div>
      ) : (
        <>
        <div className="bg-gray-900/60 border border-gray-700 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left">Original</th>
                <th className="px-4 py-3 text-left">Corrected</th>
                <th className="px-4 py-3 text-left">Source</th>
                <th className="px-4 py-3 text-right">Count</th>
                <th className="px-4 py-3 text-center">Lexicon Status</th>
                <th className="px-4 py-3 text-right">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {paged.map((e, i) => (
                <tr
                  key={i}
                  className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-red-400 text-xs">
                    "{e.original_phrase}"
                  </td>
                  <td className="px-4 py-3 font-mono text-emerald-400 text-xs">
                    "{e.corrected_phrase}"
                  </td>
                  <td className="px-4 py-3">
                    <SourceBadge source={e.source} />
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{e.occurrences}</td>
                  <td className="px-4 py-3 text-center">
                    {statusBadge(e)}
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-gray-500">
                    {new Date(e.last_seen_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <Pagination
          currentPage={currentPage}
          totalItems={filtered.length}
          pageSize={pageSize}
          onPageChange={setCurrentPage}
          onPageSizeChange={(s) => { setPageSize(s); setCurrentPage(1); }}
        />
        </>
      )}
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const colors: Record<string, string> = {
    lexicon: "bg-blue-900/50 text-blue-400",
    ngram_anchor: "bg-purple-900/50 text-purple-400",
    gemini: "bg-violet-900/50 text-violet-400",
  };
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${colors[source] || "bg-gray-800 text-gray-400"}`}
    >
      {source}
    </span>
  );
}
