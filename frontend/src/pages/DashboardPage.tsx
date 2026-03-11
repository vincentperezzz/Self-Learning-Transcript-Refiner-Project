import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { deleteSession, listSessions } from "../api";
import Pagination from "../components/Pagination";
import type { SessionSummary } from "../types";

function formatDuration(created: string, completed?: string | null): string {
  if (!completed) return "—";
  const ms = new Date(completed).getTime() - new Date(created).getTime();
  if (ms < 1000) return "<1s";
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const rem = secs % 60;
  return `${mins}m ${rem}s`;
}

type StatusFilter = "all" | "completed" | "processing" | "failed";
type DateFilter = "all" | "today" | "week" | "month";

export default function DashboardPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  useEffect(() => {
    loadSessions();
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

  async function handleDelete(key: string) {
    if (!confirm("Delete this session?")) return;
    try {
      await deleteSession(key);
      setSessions((prev) => prev.filter((s) => s.session_key !== key));
      setSelected((prev) => { const next = new Set(prev); next.delete(key); return next; });
    } catch {
      /* ignore */
    }
  }

  async function handleBulkDelete() {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} selected session${selected.size > 1 ? "s" : ""}?`)) return;
    const keys = [...selected];
    for (const key of keys) {
      try { await deleteSession(key); } catch { /* ignore */ }
    }
    setSessions((prev) => prev.filter((s) => !selected.has(s.session_key)));
    setSelected(new Set());
  }

  function toggleSelect(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  function toggleSelectAll() {
    const allKeys = filteredSessions.map((s) => s.session_key);
    const allSelected = allKeys.every((k) => selected.has(k));
    if (allSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        allKeys.forEach((k) => next.delete(k));
        return next;
      });
    } else {
      setSelected((prev) => new Set([...prev, ...allKeys]));
    }
  }

  // Compute filtered sessions in two stages so status counts reflect the date filter
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  
  // Past Week: full calendar week BEFORE current week (Sunday-Saturday)
  const dayOfWeek = now.getDay(); // 0=Sunday
  const startOfThisWeek = new Date(now.getFullYear(), now.getMonth(), now.getDate() - dayOfWeek);
  const startOfPastWeek = new Date(startOfThisWeek.getTime() - 7 * 24 * 60 * 60 * 1000);
  const endOfPastWeek = startOfThisWeek; // exclusive (start of this week)
  
  // Past Month: full calendar month BEFORE current month (1st to last day)
  const startOfThisMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  const startOfPastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const endOfPastMonth = startOfThisMonth; // exclusive (start of this month)

  const passesDateFilter = (s: SessionSummary) => {
    if (dateFilter === "all") return true;
    const created = new Date(s.created_at);
    if (dateFilter === "today") return created >= startOfToday;
    // Past week: exclude current week, show only last calendar week
    if (dateFilter === "week") return created >= startOfPastWeek && created < endOfPastWeek;
    // Past month: exclude current month, show only last calendar month
    if (dateFilter === "month") return created >= startOfPastMonth && created < endOfPastMonth;
    return true;
  };

  // Stage 1: date-filtered set (status counts are derived from this)
  const dateFilteredSessions = sessions.filter(passesDateFilter);

  // Stage 2: apply status filter on top
  const statusFilteredSessions = dateFilteredSessions.filter(
    (s) => statusFilter === "all" || s.status === statusFilter
  );

  // Stage 3: apply search filter
  const searchLower = searchQuery.toLowerCase().trim();
  const filteredSessions = searchLower
    ? statusFilteredSessions.filter(
        (s) =>
          s.filename.toLowerCase().includes(searchLower) ||
          s.speaker?.toLowerCase().includes(searchLower) ||
          s.session_key.toLowerCase().includes(searchLower)
      )
    : statusFilteredSessions;

  const pagedSessions = filteredSessions.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold text-white">Past Refinements</h1>
        <div className="flex items-center gap-3 flex-1 justify-end">
          {/* Search input */}
          <div className="relative">
            <input
              type="text"
              placeholder="Search filename..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
              className="w-56 px-3 py-2 pl-9 bg-gray-800/50 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-gray-600"
            />
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-lg"
              >
                ×
              </button>
            )}
          </div>
          <button
            onClick={() => navigate("/upload")}
            className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-sm font-medium transition-colors"
          >
            + New Upload
          </button>
        </div>
      </div>

      {/* Filters */}
      {sessions.length > 0 && (
        <div className="flex flex-wrap items-center gap-4">
          {/* Status filter */}
          <div className="flex gap-1.5">
            {([
              ["all", "All", "bg-gray-700 text-white", "bg-gray-800/50 text-gray-400 hover:text-gray-200"],
              ["completed", "Completed", "bg-emerald-900/60 text-emerald-400", "bg-gray-800/50 text-gray-400 hover:text-emerald-400"],
              ["processing", "Processing", "bg-sky-900/60 text-sky-400", "bg-gray-800/50 text-gray-400 hover:text-sky-400"],
              ["failed", "Failed", "bg-red-900/60 text-red-400", "bg-gray-800/50 text-gray-400 hover:text-red-400"],
            ] as const).map(([value, label, activeClass, inactiveClass]) => {
              const count = value === "all" ? dateFilteredSessions.length : dateFilteredSessions.filter((s) => s.status === value).length;
              return (
                <button
                  key={value}
                  onClick={() => { setStatusFilter(value); setCurrentPage(1); }}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                    statusFilter === value ? activeClass : inactiveClass
                  }`}
                >
                  {label} ({count})
                </button>
              );
            })}
          </div>

          <div className="h-4 w-px bg-gray-700" />

          {/* Date filter */}
          <div className="flex gap-1.5">
            {([
              ["all", "All Time"],
              ["today", "Today"],
              ["week", "Past Week"],
              ["month", "Past Month"],
            ] as const).map(([value, label]) => {
              const count = sessions.filter((s) => {
                if (value === "all") return true;
                const created = new Date(s.created_at);
                if (value === "today") return created >= startOfToday;
                // Match the main passesDateFilter logic
                if (value === "week") return created >= startOfPastWeek && created < endOfPastWeek;
                if (value === "month") return created >= startOfPastMonth && created < endOfPastMonth;
                return true;
              }).length;
              return (
                <button
                  key={value}
                  onClick={() => { setDateFilter(value); setCurrentPage(1); }}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                    dateFilter === value
                      ? "bg-gray-700 text-white"
                      : "bg-gray-800/50 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {label} ({count})
                </button>
              );
            })}
          </div>
        </div>
      )}

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
      ) : filteredSessions.length === 0 ? (
        <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-10 text-center">
          <p className="text-gray-400">No sessions match the current filters.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Bulk delete bar */}
          {selected.size > 0 && (
            <div className="flex items-center gap-3 px-4 py-2 bg-red-900/20 border border-red-800/40 rounded-lg">
              <span className="text-sm text-red-400">{selected.size} selected</span>
              <button
                onClick={handleBulkDelete}
                className="px-3 py-1 rounded-lg bg-red-600 hover:bg-red-500 text-xs font-medium text-white transition-colors"
              >
                Delete Selected
              </button>
              <button
                onClick={() => setSelected(new Set())}
                className="px-3 py-1 rounded-lg bg-gray-700 hover:bg-gray-600 text-xs font-medium text-gray-300 transition-colors"
              >
                Clear
              </button>
            </div>
          )}

        <div className="bg-gray-900/60 border border-gray-800 rounded-xl overflow-hidden">
          {/* Table header */}
          <div className="flex items-center gap-2 px-5 py-3 border-b border-gray-800">
            <input
              type="checkbox"
              checked={filteredSessions.length > 0 && filteredSessions.every((s) => selected.has(s.session_key))}
              onChange={toggleSelectAll}
              className="h-3.5 w-3.5 rounded border-gray-600 bg-gray-800 text-sky-500 focus:ring-sky-500 focus:ring-offset-0 cursor-pointer"
            />
            <div className="flex flex-1 text-[11px] uppercase tracking-wider text-gray-500">
              <div className="w-[40%] min-w-0">File</div>
              <div className="w-24">Speaker</div>
              <div className="w-24 text-center">Status</div>
              <div className="w-16 text-center">Seg</div>
              <div className="w-14 text-center">Fixes</div>
              <div className="w-16 text-center">Time</div>
              <div className="flex-1 min-w-0">Date</div>
              <div className="w-10"></div>
            </div>
          </div>

          {/* Rows */}
          {pagedSessions.map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-2 px-5 py-3 border-b border-gray-800/50
                         hover:bg-gray-800/40 transition-colors"
            >
              <input
                type="checkbox"
                checked={selected.has(s.session_key)}
                onChange={() => toggleSelect(s.session_key)}
                onClick={(e) => e.stopPropagation()}
                className="h-3.5 w-3.5 rounded border-gray-600 bg-gray-800 text-sky-500 focus:ring-sky-500 focus:ring-offset-0 cursor-pointer"
              />
              <div
                className="flex flex-1 items-center cursor-pointer"
                onClick={() => navigate(`/sessions/${s.session_key}`)}
              >
              {/* File */}
              <div className="w-[40%] min-w-0 text-sm text-gray-200 truncate font-medium pr-2" title={s.filename}>
                {s.filename}
              </div>

              {/* Speaker */}
              <div className="w-24 text-sm text-gray-400">
                {s.speaker ? (
                  <span
                    className={`px-2 py-0.5 rounded text-xs whitespace-nowrap ${
                      s.speaker === "agent"
                        ? "bg-sky-900/40 text-sky-300"
                        : s.speaker === "client"
                        ? "bg-emerald-900/40 text-emerald-300"
                        : s.speaker === "text"
                        ? "bg-violet-900/40 text-violet-300"
                        : "bg-yellow-900/40 text-yellow-300"
                    }`}
                  >
                    {s.speaker === "text" ? "Text Import" : s.speaker}
                  </span>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </div>

              {/* Status */}
              <div className="w-24 text-center">
                {s.status === "processing" ? (
                  <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-sky-900/40 text-sky-400">
                    <span className="h-1.5 w-1.5 bg-sky-400 rounded-full animate-pulse" />
                    Processing
                  </span>
                ) : s.status === "failed" ? (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-red-900/40 text-red-400">
                    Failed
                  </span>
                ) : (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-900/40 text-emerald-400">
                    Completed
                  </span>
                )}
              </div>

              {/* Segments */}
              <div className="w-16 text-center text-sm text-gray-400">
                {s.status === "completed" ? s.total_segments : "—"}
              </div>

              {/* Fixes */}
              <div className="w-14 text-center">
                {s.status === "completed" ? (
                  s.total_corrections > 0 ? (
                    <span className="text-sm text-emerald-400 font-medium">
                      {s.total_corrections}
                    </span>
                  ) : (
                    <span className="text-sm text-gray-600">0</span>
                  )
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </div>

              {/* Duration */}
              <div className="w-16 text-center text-xs text-gray-500 tabular-nums">
                {formatDuration(s.created_at, s.completed_at)}
              </div>

              {/* Date */}
              <div className="flex-1 min-w-0 text-xs text-gray-500 truncate">
                {new Date(s.created_at).toLocaleString()}
              </div>

              {/* Delete */}
              <div className="w-10 text-right">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(s.session_key);
                  }}
                  className="p-1.5 rounded-lg text-gray-600 hover:text-red-400 hover:bg-red-900/20 transition-colors"
                  title="Delete session"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
            </div>
          ))}
        </div>

        <Pagination
          currentPage={currentPage}
          totalItems={filteredSessions.length}
          pageSize={pageSize}
          onPageChange={setCurrentPage}
          onPageSizeChange={(s) => { setPageSize(s); setCurrentPage(1); }}
        />
        </div>
      )}
    </div>
  );
}
