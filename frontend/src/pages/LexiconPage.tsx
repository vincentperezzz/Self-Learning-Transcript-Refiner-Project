import { useEffect, useState, type FormEvent } from "react";
import {
  addLexiconRule,
  deleteLexiconRule,
  listLexicon,
  updateLexiconRule,
} from "../api";
import type { LexiconRule } from "../types";

export default function LexiconPage() {
  const [rules, setRules] = useState<LexiconRule[]>([]);
  const [editId, setEditId] = useState<number | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [search, setSearch] = useState("");

  // Form state
  const [wrongPhrase, setWrongPhrase] = useState("");
  const [correctPhrase, setCorrectPhrase] = useState("");
  const [contextHint, setContextHint] = useState("");
  const [anchorMode, setAnchorMode] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    loadRules();
  }, []);

  async function loadRules() {
    try {
      const data = await listLexicon();
      setRules(data.rules);
    } catch {}
  }

  function resetForm() {
    setWrongPhrase("");
    setCorrectPhrase("");
    setContextHint("");
    setAnchorMode("");
    setEditId(null);
    setShowAdd(false);
    setError("");
  }

  function startEdit(rule: LexiconRule) {
    setEditId(rule.id);
    setWrongPhrase(rule.wrong_phrase);
    setCorrectPhrase(rule.correct_phrase);
    setContextHint(rule.context_hint || "");
    setAnchorMode(rule.anchor_mode || "");
    setShowAdd(true);
    setError("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const payload = {
      wrong_phrase: wrongPhrase,
      correct_phrase: correctPhrase,
      context_hint: contextHint || undefined,
      anchor_mode: anchorMode || undefined,
    };

    try {
      if (editId) {
        await updateLexiconRule(editId, payload);
      } else {
        await addLexiconRule(payload);
      }
      resetForm();
      loadRules();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save rule");
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteLexiconRule(id);
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
        <h2 className="text-lg font-semibold">Lexicon Rules ({rules.length})</h2>
        <button
          onClick={() => {
            resetForm();
            setShowAdd(true);
          }}
          className="px-4 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-sm font-medium transition-colors"
        >
          + Add Rule
        </button>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search rules..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm
                   text-gray-200 focus:outline-none focus:ring-2 focus:ring-sky-600"
      />

      {/* Add/Edit Form */}
      {showAdd && (
        <form
          onSubmit={handleSubmit}
          className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-3"
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Wrong Phrase</label>
              <input
                value={wrongPhrase}
                onChange={(e) => setWrongPhrase(e.target.value)}
                required
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Correct Phrase</label>
              <input
                value={correctPhrase}
                onChange={(e) => setCorrectPhrase(e.target.value)}
                required
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Context Hint</label>
              <input
                value={contextHint}
                onChange={(e) => setContextHint(e.target.value)}
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Anchor Mode</label>
              <select
                value={anchorMode}
                onChange={(e) => setAnchorMode(e.target.value)}
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              >
                <option value="">Any / None</option>
                <option value="banking">Banking</option>
                <option value="collections">Collections</option>
                <option value="verification">Verification</option>
                <option value="general">General</option>
              </select>
            </div>
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <div className="flex gap-2">
            <button
              type="submit"
              className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm font-medium transition-colors"
            >
              {editId ? "Update" : "Add"} Rule
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

      {/* Rules table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
              <th className="pb-2 pr-3">Wrong Phrase</th>
              <th className="pb-2 pr-3">Correct Phrase</th>
              <th className="pb-2 pr-3">Context</th>
              <th className="pb-2 pr-3">Mode</th>
              <th className="pb-2 w-20">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {filtered.map((rule) => (
              <tr key={rule.id} className="hover:bg-gray-900/50">
                <td className="py-2 pr-3 text-red-400">{rule.wrong_phrase}</td>
                <td className="py-2 pr-3 text-emerald-400">{rule.correct_phrase}</td>
                <td className="py-2 pr-3 text-gray-500">{rule.context_hint || "—"}</td>
                <td className="py-2 pr-3">
                  {rule.anchor_mode ? (
                    <span className="px-1.5 py-0.5 rounded bg-gray-800 text-xs text-gray-300 uppercase">
                      {rule.anchor_mode}
                    </span>
                  ) : (
                    <span className="text-gray-600">any</span>
                  )}
                </td>
                <td className="py-2">
                  <div className="flex gap-2">
                    <button
                      onClick={() => startEdit(rule)}
                      className="text-xs text-sky-400 hover:text-sky-300"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(rule.id)}
                      className="text-xs text-gray-500 hover:text-red-400"
                    >
                      Del
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
