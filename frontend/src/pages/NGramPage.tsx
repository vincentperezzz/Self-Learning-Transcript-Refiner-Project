import { useEffect, useState } from "react";
import { listNgrams } from "../api";
import type { NGramEntry } from "../types";

const PAGE_SIZE = 50;

export default function NGramPage() {
  const [ngrams, setNgrams] = useState<NGramEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search]);

  async function load() {
    setLoading(true);
    try {
      const data = await listNgrams(search, PAGE_SIZE, page * PAGE_SIZE);
      setNgrams(data.ngrams);
      setTotal(data.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function handleSearch(val: string) {
    setSearch(val);
    setPage(0);
  }

  // bar width relative to max frequency in current page
  const maxFreq = ngrams.reduce((m, n) => Math.max(m, n.frequency), 1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          N-Gram Database{" "}
          <span className="text-gray-500 text-sm font-normal">
            ({total.toLocaleString()} trigrams)
          </span>
        </h2>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search trigrams..."
        value={search}
        onChange={(e) => handleSearch(e.target.value)}
        className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm
                   text-gray-200 focus:outline-none focus:ring-2 focus:ring-sky-600"
      />

      {/* Table */}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : ngrams.length === 0 ? (
        <p className="text-gray-500 text-sm">No trigrams found.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
                <th className="pb-2 pr-3 w-8">#</th>
                <th className="pb-2 pr-3">Word 1</th>
                <th className="pb-2 pr-3">Word 2</th>
                <th className="pb-2 pr-3">Word 3</th>
                <th className="pb-2 pr-3 w-24 text-right">Freq</th>
                <th className="pb-2 w-40"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {ngrams.map((ng, i) => (
                <tr key={ng.id} className="hover:bg-gray-900/50">
                  <td className="py-2 pr-3 text-gray-600 tabular-nums">
                    {page * PAGE_SIZE + i + 1}
                  </td>
                  <td className="py-2 pr-3 text-sky-300 font-mono text-xs">{ng.word1}</td>
                  <td className="py-2 pr-3 text-sky-300 font-mono text-xs">{ng.word2}</td>
                  <td className="py-2 pr-3 text-sky-300 font-mono text-xs">{ng.word3}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-gray-300">
                    {ng.frequency.toLocaleString()}
                  </td>
                  <td className="py-2">
                    <div className="h-2 rounded-full bg-gray-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-violet-500/70"
                        style={{ width: `${(ng.frequency / maxFreq) * 100}%` }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ← Prev
          </button>
          <span>
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
