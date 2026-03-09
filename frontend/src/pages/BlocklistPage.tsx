import { useEffect, useState, type FormEvent } from "react";
import {
  addBlocklistRule,
  deleteBlocklistRule,
  listBlocklist,
} from "../api";
import type { BlocklistRule } from "../types";

export default function BlocklistPage() {
  const [rules, setRules] = useState<BlocklistRule[]>([]);
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  // Form state
  const [wrongPhrase, setWrongPhrase] = useState("");
  const [correctPhrase, setCorrectPhrase] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    loadRules();
  }, []);

  async function loadRules() {
    try {
      const data = await listBlocklist();
      setRules(data.rules);
    } catch {}
  }

  function resetForm() {
    setWrongPhrase("");
    setCorrectPhrase("");
    setReason("");
    setShowAdd(false);
    setError("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await addBlocklistRule({
        wrong_phrase: wrongPhrase,
        correct_phrase: correctPhrase,
        reason: reason || undefined,
      });
      resetForm();
      loadRules();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add ban");
    }
  }

  async function handleUnban(id: number) {
    if (!confirm("Remove this ban? The system will be able to learn this correction again.")) return;
    try {
      await deleteBlocklistRule(id);
      setRules((prev) => prev.filter((r) => r.id !== id));
    } catch {}
  }

  const filtered = rules.filter(
    (r) =>
      !search ||
      r.wrong_phrase.toLowerCase().includes(search.toLowerCase()) ||
      r.correct_phrase.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            Blocklist{" "}
            <span className="text-gray-500 font-normal">({rules.length})</span>
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Permanently banned correction pairs. The system will never learn, apply, or promote these.
          </p>
        </div>
        <button
          onClick={() => {
            resetForm();
            setShowAdd(true);
          }}
          className="px-4 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-sm font-medium transition-colors"
        >
          + Add Ban
        </button>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search banned pairs..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm
                   text-gray-200 focus:outline-none focus:ring-2 focus:ring-red-600"
      />

      {/* Add Form */}
      {showAdd && (
        <form
          onSubmit={handleSubmit}
          className="bg-gray-900 rounded-xl border border-red-900/40 p-4 space-y-3"
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Wrong Phrase</label>
              <input
                value={wrongPhrase}
                onChange={(e) => setWrongPhrase(e.target.value)}
                required
                placeholder='e.g. "suspension"'
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Incorrect Correction</label>
              <input
                value={correctPhrase}
                onChange={(e) => setCorrectPhrase(e.target.value)}
                required
                placeholder='e.g. "suspensions"'
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Reason (optional)</label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this banned?"
              className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <div className="flex gap-2">
            <button
              type="submit"
              className="px-4 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-sm font-medium transition-colors"
            >
              Ban Pair
            </button>
            <button
              type="button"
              onClick={resetForm}
              className="px-4 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-sm font-medium transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
              <th className="pb-2 pr-3">Wrong Phrase</th>
              <th className="pb-2 pr-3">Banned Correction</th>
              <th className="pb-2 pr-3">Reason</th>
              <th className="pb-2 pr-3">Banned By</th>
              <th className="pb-2 pr-3">Date</th>
              <th className="pb-2 w-16">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-gray-600">
                  {search ? "No matching bans found" : "No banned correction pairs yet"}
                </td>
              </tr>
            )}
            {filtered.map((rule) => (
              <tr key={rule.id} className="hover:bg-gray-900/50">
                <td className="py-2 pr-3 text-red-400">{rule.wrong_phrase}</td>
                <td className="py-2 pr-3">
                  <span className="line-through text-gray-500">{rule.correct_phrase}</span>
                </td>
                <td className="py-2 pr-3 text-gray-500 text-xs">{rule.reason || "—"}</td>
                <td className="py-2 pr-3">
                  <span className={`px-1.5 py-0.5 rounded-full text-xs ${
                    rule.banned_by === "manual"
                      ? "bg-red-900/50 text-red-400"
                      : "bg-amber-900/50 text-amber-400"
                  }`}>
                    {rule.banned_by}
                  </span>
                </td>
                <td className="py-2 pr-3 text-gray-600 text-xs">
                  {new Date(rule.created_at).toLocaleDateString()}
                </td>
                <td className="py-2">
                  <button
                    onClick={() => handleUnban(rule.id)}
                    title="Unban (allow re-learning)"
                    className="p-1 rounded hover:bg-emerald-700/50 text-gray-400 hover:text-emerald-400 transition-colors"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
