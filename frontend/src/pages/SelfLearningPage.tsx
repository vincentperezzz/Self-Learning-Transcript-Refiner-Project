import { useEffect, useState } from "react";
import {
  getCorrectionLog,
  getPromotionCandidates,
  triggerAutoPromote,
} from "../api";

interface Candidate {
  original: string;
  corrected: string;
  source: string;
  occurrences: number;
}

interface LogEntry {
  original_phrase: string;
  corrected_phrase: string;
  source: string;
  occurrences: number;
  promoted: boolean;
  last_seen_at: string;
}

interface PromoteResult {
  original: string;
  corrected: string;
  approved: boolean;
  reason: string;
}

type Tab = "candidates" | "log" | "results";

export default function SelfLearningPage() {
  const [tab, setTab] = useState<Tab>("candidates");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [results, setResults] = useState<PromoteResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [stats, setStats] = useState({ promoted: 0, rejected: 0 });

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [candData, logData] = await Promise.all([
        getPromotionCandidates(),
        getCorrectionLog(),
      ]);
      setCandidates(candData.candidates);
      setLogEntries(logData.entries);
    } catch (e) {
      console.error("Failed to load self-learning data:", e);
    } finally {
      setLoading(false);
    }
  }

  async function handlePromote() {
    setPromoting(true);
    try {
      const data = await triggerAutoPromote();
      setResults(data.results);
      setStats({ promoted: data.promoted, rejected: data.rejected });
      setTab("results");
      // Reload candidates and log after promotion
      await loadData();
    } catch (e) {
      console.error("Promotion failed:", e);
    } finally {
      setPromoting(false);
    }
  }

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "candidates", label: "Promotion Candidates", count: candidates.length },
    { key: "log", label: "Correction Log", count: logEntries.length },
    { key: "results", label: "Audit Results", count: results.length },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Self-Learning</h1>
          <p className="text-sm text-gray-400 mt-1">
            Corrections that reach 5 occurrences are audited by Gemini 2.5 Flash
            and promoted to permanent lexicon rules.
          </p>
        </div>
        <button
          onClick={handlePromote}
          disabled={promoting || candidates.length === 0}
          className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 
                     disabled:text-gray-500 text-white rounded-lg font-medium transition-colors
                     flex items-center gap-2"
        >
          {promoting ? (
            <>
              <span className="animate-spin">⚙️</span> Auditing...
            </>
          ) : (
            <>🧠 Run Gemini Audit</>
          )}
        </button>
      </div>

      {/* Stats banner */}
      {results.length > 0 && (
        <div className="flex gap-4">
          <div className="flex-1 bg-emerald-900/30 border border-emerald-700/50 rounded-lg p-4 text-center">
            <div className="text-3xl font-bold text-emerald-400">{stats.promoted}</div>
            <div className="text-xs text-emerald-300/70 mt-1">Promoted to Lexicon</div>
          </div>
          <div className="flex-1 bg-red-900/30 border border-red-700/50 rounded-lg p-4 text-center">
            <div className="text-3xl font-bold text-red-400">{stats.rejected}</div>
            <div className="text-xs text-red-300/70 mt-1">Rejected by Gemini</div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-900/50 rounded-lg p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
              tab === t.key
                ? "bg-gray-700 text-white"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="ml-1.5 text-xs opacity-60">({t.count})</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading...</div>
      ) : (
        <>
          {tab === "candidates" && <CandidatesTab candidates={candidates} />}
          {tab === "log" && <LogTab entries={logEntries} />}
          {tab === "results" && <ResultsTab results={results} />}
        </>
      )}
    </div>
  );
}

function CandidatesTab({ candidates }: { candidates: Candidate[] }) {
  if (candidates.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <div className="text-4xl mb-3">✅</div>
        <p>No candidates ready for promotion.</p>
        <p className="text-xs mt-1">
          Corrections need at least 5 occurrences to become candidates.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900/60 border border-gray-700 rounded-xl overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase tracking-wider">
            <th className="px-4 py-3 text-left">Original</th>
            <th className="px-4 py-3 text-left">Corrected</th>
            <th className="px-4 py-3 text-left">Source</th>
            <th className="px-4 py-3 text-right">Occurrences</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c, i) => (
            <tr
              key={i}
              className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors"
            >
              <td className="px-4 py-3 font-mono text-red-400">"{c.original}"</td>
              <td className="px-4 py-3 font-mono text-emerald-400">"{c.corrected}"</td>
              <td className="px-4 py-3">
                <SourceBadge source={c.source} />
              </td>
              <td className="px-4 py-3 text-right font-mono">{c.occurrences}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogTab({ entries }: { entries: LogEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p>No corrections logged yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900/60 border border-gray-700 rounded-xl overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700 text-gray-400 text-xs uppercase tracking-wider">
            <th className="px-4 py-3 text-left">Original</th>
            <th className="px-4 py-3 text-left">Corrected</th>
            <th className="px-4 py-3 text-left">Source</th>
            <th className="px-4 py-3 text-right">Count</th>
            <th className="px-4 py-3 text-center">Status</th>
            <th className="px-4 py-3 text-right">Last Seen</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
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
                {e.promoted ? (
                  <span className="text-xs bg-emerald-900/50 text-emerald-400 px-2 py-0.5 rounded-full">
                    Promoted
                  </span>
                ) : e.occurrences >= 5 ? (
                  <span className="text-xs bg-amber-900/50 text-amber-400 px-2 py-0.5 rounded-full">
                    Ready
                  </span>
                ) : (
                  <span className="text-xs bg-gray-800 text-gray-500 px-2 py-0.5 rounded-full">
                    {e.occurrences}/5
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-right text-xs text-gray-500">
                {new Date(e.last_seen_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultsTab({ results }: { results: PromoteResult[] }) {
  if (results.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p>No audit results yet. Click "Run Gemini Audit" to start.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {results.map((r, i) => (
        <div
          key={i}
          className={`border rounded-xl p-4 ${
            r.approved
              ? "bg-emerald-900/20 border-emerald-700/50"
              : "bg-red-900/20 border-red-700/50"
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <span className={`text-lg ${r.approved ? "text-emerald-400" : "text-red-400"}`}>
                {r.approved ? "✅" : "❌"}
              </span>
              <span className="font-mono text-sm">
                <span className="text-red-400">"{r.original}"</span>
                <span className="text-gray-500 mx-2">→</span>
                <span className="text-emerald-400">"{r.corrected}"</span>
              </span>
            </div>
            <span
              className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                r.approved
                  ? "bg-emerald-800/50 text-emerald-300"
                  : "bg-red-800/50 text-red-300"
              }`}
            >
              {r.approved ? "PROMOTED" : "REJECTED"}
            </span>
          </div>
          <p className="text-xs text-gray-400 ml-9">{r.reason}</p>
        </div>
      ))}
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const colors: Record<string, string> = {
    lexicon: "bg-blue-900/50 text-blue-400",
    ngram_anchor: "bg-purple-900/50 text-purple-400",
    distilbert: "bg-amber-900/50 text-amber-400",
  };
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${colors[source] || "bg-gray-800 text-gray-400"}`}
    >
      {source}
    </span>
  );
}
