import { useEffect, useState, type FormEvent } from "react";
import {
  addLexiconRule,
  deleteLexiconRule,
  demoteLexiconRule,
  listLexicon,
  promoteLexiconRule,
  updateLexiconRule,
} from "../api";
import type { LexiconRule } from "../types";

type StatusFilter = "all" | "permanent" | "probationary";

export default function LexiconPage() {
  const [rules, setRules] = useState<LexiconRule[]>([]);
  const [editId, setEditId] = useState<number | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

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
    const reason = prompt("Reason for banning this rule (optional):");
    if (reason === null) return; // user cancelled
    try {
      await deleteLexiconRule(id, reason);
      setRules((prev) => prev.filter((r) => r.id !== id));
    } catch {}
  }

  async function handlePromote(id: number) {
    try {
      await promoteLexiconRule(id);
      setRules((prev) =>
        prev.map((r) => (r.id === id ? { ...r, is_permanent: true } : r)),
      );
    } catch {}
  }

  async function handleDemote(id: number) {
    try {
      await demoteLexiconRule(id);
      setRules((prev) =>
        prev.map((r) => (r.id === id ? { ...r, is_permanent: false } : r)),
      );
    } catch {}
  }

  const permanentCount = rules.filter((r) => r.is_permanent).length;
  const probationaryCount = rules.filter((r) => !r.is_permanent).length;

  const filtered = rules.filter((r) => {
    const matchesSearch =
      !search ||
      r.wrong_phrase.toLowerCase().includes(search.toLowerCase()) ||
      r.correct_phrase.toLowerCase().includes(search.toLowerCase());
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "permanent" && r.is_permanent) ||
      (statusFilter === "probationary" && !r.is_permanent);
    return matchesSearch && matchesStatus;
  });

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

      {/* Status filter tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => setStatusFilter("all")}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            statusFilter === "all"
              ? "bg-gray-700 text-white"
              : "bg-gray-800/50 text-gray-400 hover:text-gray-200"
          }`}
        >
          All ({rules.length})
        </button>
        <button
          onClick={() => setStatusFilter("permanent")}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            statusFilter === "permanent"
              ? "bg-emerald-900/60 text-emerald-400"
              : "bg-gray-800/50 text-gray-400 hover:text-emerald-400"
          }`}
        >
          Permanent ({permanentCount})
        </button>
        <button
          onClick={() => setStatusFilter("probationary")}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            statusFilter === "probationary"
              ? "bg-amber-900/60 text-amber-400"
              : "bg-gray-800/50 text-gray-400 hover:text-amber-400"
          }`}
        >
          Probationary ({probationaryCount})
        </button>
      </div>

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
                <option value="greeting">Greeting</option>
                <option value="introduction">Introduction</option>
                <option value="consent_to_record">Consent to Record</option>
                <option value="verification">Verification</option>
                <option value="account_status">Account Status</option>
                <option value="probing_rfd">Probing: RFD</option>
                <option value="probing_sof">Probing: SOF/SOI</option>
                <option value="negotiation">Negotiation</option>
                <option value="benefits">Benefits</option>
                <option value="consequences">Consequences</option>
                <option value="ptp_commitment">PTP / Commitment</option>
                <option value="payment_channel">Payment Channel</option>
                <option value="contact_info">Contact Info</option>
                <option value="recap">Recap</option>
                <option value="empathy">Empathy</option>
                <option value="objection_handling">Objection Handling</option>
                <option value="closing">Closing</option>
                <option value="third_party">3rd Party Contact</option>
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
              <th className="pb-2 pr-3">Status</th>
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
                  {rule.is_permanent ? (
                    <span className="px-1.5 py-0.5 rounded-full bg-emerald-900/50 text-xs text-emerald-400">
                      Permanent
                    </span>
                  ) : (
                    <span className="px-1.5 py-0.5 rounded-full bg-amber-900/50 text-xs text-amber-400">
                      Probationary
                    </span>
                  )}
                </td>
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
                  <div className="flex gap-1">
                    {!rule.is_permanent && (
                      <button
                        onClick={() => handlePromote(rule.id)}
                        title="Promote to permanent"
                        className="p-1 rounded hover:bg-emerald-700/50 text-gray-400 hover:text-emerald-400 transition-colors"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-8.707l-3-3a1 1 0 00-1.414 0l-3 3a1 1 0 001.414 1.414L9 9.414V13a1 1 0 102 0V9.414l1.293 1.293a1 1 0 001.414-1.414z" clipRule="evenodd" />
                        </svg>
                      </button>
                    )}
                    {rule.is_permanent && (
                      <button
                        onClick={() => handleDemote(rule.id)}
                        title="Demote to probationary"
                        className="p-1 rounded hover:bg-amber-700/50 text-gray-400 hover:text-amber-400 transition-colors"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v3.586L7.707 9.293a1 1 0 00-1.414 1.414l3 3a1 1 0 001.414 0l3-3a1 1 0 00-1.414-1.414L11 10.586V7z" clipRule="evenodd" />
                        </svg>
                      </button>
                    )}
                    <button
                      onClick={() => startEdit(rule)}
                      title="Edit rule"
                      className="p-1 rounded hover:bg-sky-700/50 text-gray-400 hover:text-sky-300 transition-colors"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => handleDelete(rule.id)}
                      title="Ban rule (delete + blocklist)"
                      className="p-1 rounded hover:bg-red-700/50 text-gray-400 hover:text-red-400 transition-colors"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M13.477 14.89A6 6 0 015.11 6.524l8.367 8.368zm1.414-1.414L6.524 5.11a6 6 0 018.367 8.367zM18 10a8 8 0 11-16 0 8 8 0 0116 0z" clipRule="evenodd" />
                      </svg>
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
