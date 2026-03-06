import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { deleteSession, listSessions } from "../api";
import type { SessionSummary } from "../types";

export default function DashboardPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    loadSessions();
    // Always poll — covers returning from upload page
    pollRef.current = setInterval(() => {
      listSessions()
        .then((data) => {
          setSessions(data.sessions ?? []);
        })
        .catch(() => {});
    }, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function loadSessions() {
    setLoading(true);
    try {
      const data = await listSessions();
      setSessions(data.sessions ?? []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this session?")) return;
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Past Refinements</h1>
        <button
          onClick={() => navigate("/upload")}
          className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-sm font-medium transition-colors"
        >
          + New Upload
        </button>
      </div>

      {loading ? (
        <p className="text-gray-500 text-sm">Loading sessions...</p>
      ) : sessions.length === 0 ? (
        <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-10 text-center">
          <p className="text-gray-400 mb-3">No refinement sessions yet.</p>
          <button
            onClick={() => navigate("/upload")}
            className="text-sky-400 hover:text-sky-300 text-sm font-medium"
          >
            Upload your first audio file →
          </button>
        </div>
      ) : (
        <div className="bg-gray-900/60 border border-gray-800 rounded-xl overflow-hidden">
          {/* Table header */}
          <div className="grid grid-cols-12 gap-2 px-5 py-3 text-[11px] uppercase tracking-wider text-gray-500 border-b border-gray-800">
            <div className="col-span-4">File</div>
            <div className="col-span-2">Speaker</div>
            <div className="col-span-1 text-center">Segments</div>
            <div className="col-span-1 text-center">Fixes</div>
            <div className="col-span-3">Date</div>
            <div className="col-span-1"></div>
          </div>

          {/* Rows */}
          {sessions.map((s) => (
            <div
              key={s.id}
              className="grid grid-cols-12 gap-2 px-5 py-3 items-center border-b border-gray-800/50
                         hover:bg-gray-800/40 transition-colors cursor-pointer"
              onClick={() => navigate(`/sessions/${s.id}`)}
            >
              <div className="col-span-4 text-sm text-gray-200 truncate font-medium">
                {s.filename}
              </div>
              <div className="col-span-2 text-sm text-gray-400">
                {s.speaker ? (
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${
                      s.speaker === "agent"
                        ? "bg-sky-900/40 text-sky-300"
                        : "bg-amber-900/40 text-amber-300"
                    }`}
                  >
                    {s.speaker}
                  </span>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </div>
              <div className="col-span-1 text-center text-sm text-gray-400">
                {s.status === "processing" ? (
                  <span className="inline-flex items-center gap-1 text-xs text-sky-400">
                    <span className="h-2 w-2 bg-sky-500 rounded-full animate-pulse" />
                  </span>
                ) : s.status === "failed" ? (
                  <span className="text-xs text-red-400">✗</span>
                ) : (
                  s.total_segments
                )}
              </div>
              <div className="col-span-1 text-center">
                {s.status === "processing" ? (
                  <span className="text-xs text-sky-400 animate-pulse">Processing...</span>
                ) : s.status === "failed" ? (
                  <span className="text-xs text-red-400">Failed</span>
                ) : s.total_corrections > 0 ? (
                  <span className="text-sm text-emerald-400 font-medium">
                    {s.total_corrections}
                  </span>
                ) : (
                  <span className="text-sm text-gray-600">0</span>
                )}
              </div>
              <div className="col-span-3 text-xs text-gray-500">
                {new Date(s.created_at).toLocaleString()}
              </div>
              <div className="col-span-1 text-right">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(s.id);
                  }}
                  className="text-xs text-gray-600 hover:text-red-400 transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
