import { useEffect, useState, type FormEvent } from "react";
import {
  addAnchor,
  addGlossaryTerm,
  deleteAnchor,
  deleteGlossaryTerm,
  listAnchorOverrides,
  listAnchors,
  listGlossary,
  toggleAnchor,
  updateAnchor,
  updateGlossaryTerm,
} from "../api";
import Pagination from "../components/Pagination";
import type { AnchorOverride, DomainGlossaryTerm, SemanticAnchor } from "../types";

const ANCHOR_MODES = [
  "greeting",
  "introduction",
  "consent_to_record",
  "verification",
  "account_status",
  "probing_rfd",
  "probing_sof",
  "negotiation",
  "benefits",
  "consequences",
  "ptp_commitment",
  "payment_channel",
  "contact_info",
  "recap",
  "empathy",
  "objection_handling",
  "closing",
  "third_party",
  "general",
];

const MODE_LABELS: Record<string, string> = {
  greeting: "Greeting",
  introduction: "Introduction",
  consent_to_record: "Consent to Record",
  verification: "Verification",
  account_status: "Account Status",
  probing_rfd: "Probing: RFD",
  probing_sof: "Probing: SOF",
  negotiation: "Negotiation",
  benefits: "Benefits",
  consequences: "Consequences",
  ptp_commitment: "PTP Commitment",
  payment_channel: "Payment Channel",
  contact_info: "Contact Info",
  recap: "Recap",
  empathy: "Empathy",
  objection_handling: "Objection Handling",
  closing: "Closing",
  third_party: "Third Party",
  general: "General",
};

const MODE_COLORS: Record<string, string> = {
  greeting: "bg-green-900/40 text-green-300",
  introduction: "bg-blue-900/40 text-blue-300",
  consent_to_record: "bg-purple-900/40 text-purple-300",
  verification: "bg-cyan-900/40 text-cyan-300",
  account_status: "bg-orange-900/40 text-orange-300",
  probing_rfd: "bg-yellow-900/40 text-yellow-300",
  probing_sof: "bg-yellow-900/40 text-yellow-300",
  negotiation: "bg-red-900/40 text-red-300",
  benefits: "bg-emerald-900/40 text-emerald-300",
  consequences: "bg-rose-900/40 text-rose-300",
  ptp_commitment: "bg-amber-900/40 text-amber-300",
  payment_channel: "bg-indigo-900/40 text-indigo-300",
  contact_info: "bg-sky-900/40 text-sky-300",
  recap: "bg-teal-900/40 text-teal-300",
  empathy: "bg-pink-900/40 text-pink-300",
  objection_handling: "bg-fuchsia-900/40 text-fuchsia-300",
  closing: "bg-lime-900/40 text-lime-300",
  third_party: "bg-violet-900/40 text-violet-300",
  general: "bg-gray-700/40 text-gray-300",
};

type Tab = "patterns" | "overrides" | "glossary";

export default function AnchorsPage() {
  const [anchors, setAnchors] = useState<SemanticAnchor[]>([]);
  const [overrides, setOverrides] = useState<AnchorOverride[]>([]);
  const [glossaryTerms, setGlossaryTerms] = useState<DomainGlossaryTerm[]>([]);
  const [tab, setTab] = useState<Tab>("patterns");
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState("");

  // Form state (patterns)
  const [formMode, setFormMode] = useState("");
  const [formLabel, setFormLabel] = useState("");
  const [formPattern, setFormPattern] = useState("");
  const [formWeight, setFormWeight] = useState(1);

  // Form state (glossary)
  const [showGlossaryAdd, setShowGlossaryAdd] = useState(false);
  const [glossaryEditId, setGlossaryEditId] = useState<number | null>(null);
  const [gFormMode, setGFormMode] = useState("");
  const [gFormTerm, setGFormTerm] = useState("");
  const [glossarySearch, setGlossarySearch] = useState("");
  const [glossaryFilterMode, setGlossaryFilterMode] = useState("");
  const [glossaryError, setGlossaryError] = useState("");

  // Pagination state
  const [patternsPage, setPatternsPage] = useState(1);
  const [patternsPageSize, setPatternsPageSize] = useState(25);
  const [overridesPage, setOverridesPage] = useState(1);
  const [overridesPageSize, setOverridesPageSize] = useState(25);
  const [glossaryPage, setGlossaryPage] = useState(1);
  const [glossaryPageSize, setGlossaryPageSize] = useState(25);

  useEffect(() => {
    loadAnchors();
  }, []);

  async function loadAnchors() {
    try {
      const data = await listAnchors();
      setAnchors(data.anchors);
    } catch {}
  }

  async function loadOverrides() {
    try {
      const data = await listAnchorOverrides();
      setOverrides(data.overrides);
    } catch {}
  }

  function resetForm() {
    setFormMode("");
    setFormLabel("");
    setFormPattern("");
    setFormWeight(1);
    setEditId(null);
    setShowAdd(false);
    setError("");
  }

  function startEdit(anchor: SemanticAnchor) {
    setEditId(anchor.id);
    setFormMode(anchor.mode);
    setFormLabel(anchor.label);
    setFormPattern(anchor.pattern);
    setFormWeight(anchor.weight);
    setShowAdd(true);
    setError("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      if (editId) {
        await updateAnchor(editId, {
          mode: formMode,
          label: formLabel,
          pattern: formPattern,
          weight: formWeight,
        });
      } else {
        await addAnchor({
          mode: formMode,
          label: formLabel,
          pattern: formPattern,
          weight: formWeight,
        });
      }
      resetForm();
      loadAnchors();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save anchor");
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this anchor pattern?")) return;
    try {
      await deleteAnchor(id);
      setAnchors((prev) => prev.filter((a) => a.id !== id));
    } catch {}
  }

  async function handleToggle(id: number) {
    try {
      const result = await toggleAnchor(id);
      setAnchors((prev) =>
        prev.map((a) =>
          a.id === id ? { ...a, is_active: result.is_active } : a,
        ),
      );
    } catch {}
  }

  // ── Glossary handlers ──

  async function loadGlossary() {
    try {
      const data = await listGlossary();
      setGlossaryTerms(data.terms);
    } catch {}
  }

  function resetGlossaryForm() {
    setGFormMode("");
    setGFormTerm("");
    setGlossaryEditId(null);
    setShowGlossaryAdd(false);
    setGlossaryError("");
  }

  function startGlossaryEdit(t: DomainGlossaryTerm) {
    setGlossaryEditId(t.id);
    setGFormMode(t.anchor_mode);
    setGFormTerm(t.term);
    setShowGlossaryAdd(true);
    setGlossaryError("");
  }

  async function handleGlossarySubmit(e: FormEvent) {
    e.preventDefault();
    setGlossaryError("");
    try {
      if (glossaryEditId) {
        await updateGlossaryTerm(glossaryEditId, { anchor_mode: gFormMode, term: gFormTerm });
      } else {
        await addGlossaryTerm({ anchor_mode: gFormMode, term: gFormTerm });
      }
      resetGlossaryForm();
      loadGlossary();
    } catch (err) {
      setGlossaryError(err instanceof Error ? err.message : "Failed to save term");
    }
  }

  async function handleGlossaryDelete(id: number) {
    if (!confirm("Delete this glossary term?")) return;
    try {
      await deleteGlossaryTerm(id);
      setGlossaryTerms((prev) => prev.filter((t) => t.id !== id));
    } catch {}
  }

  // Filter glossary
  const filteredGlossary = glossaryTerms.filter((t) => {
    if (glossaryFilterMode && t.anchor_mode !== glossaryFilterMode) return false;
    if (glossarySearch) {
      return t.term.toLowerCase().includes(glossarySearch.toLowerCase());
    }
    return true;
  });

  // Group glossary by mode
  const pagedGlossary = filteredGlossary.slice((glossaryPage - 1) * glossaryPageSize, glossaryPage * glossaryPageSize);

  const glossaryGrouped = pagedGlossary.reduce(
    (acc, t) => {
      (acc[t.anchor_mode] = acc[t.anchor_mode] || []).push(t);
      return acc;
    },
    {} as Record<string, DomainGlossaryTerm[]>,
  );

  // Filter anchors
  const filtered = anchors.filter((a) => {
    if (filterMode && a.mode !== filterMode) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        a.label.toLowerCase().includes(q) ||
        a.pattern.toLowerCase().includes(q) ||
        a.mode.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const pagedPatterns = filtered.slice((patternsPage - 1) * patternsPageSize, patternsPage * patternsPageSize);

  // Group by mode
  const grouped = pagedPatterns.reduce(
    (acc, a) => {
      (acc[a.mode] = acc[a.mode] || []).push(a);
      return acc;
    },
    {} as Record<string, SemanticAnchor[]>,
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Semantic Anchors</h1>
          <p className="text-sm text-gray-400 mt-1">
            {anchors.length} patterns across {new Set(anchors.map((a) => a.mode)).size} modes
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4">
        <button
          onClick={() => setTab("patterns")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === "patterns"
              ? "bg-sky-600/20 text-sky-300"
              : "text-gray-400 hover:bg-gray-800"
          }`}
        >
          Patterns
        </button>
        <button
          onClick={() => {
            setTab("overrides");
            loadOverrides();
          }}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === "overrides"
              ? "bg-sky-600/20 text-sky-300"
              : "text-gray-400 hover:bg-gray-800"
          }`}
        >
          Override Log
        </button>
        <button
          onClick={() => {
            setTab("glossary");
            loadGlossary();
          }}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === "glossary"
              ? "bg-sky-600/20 text-sky-300"
              : "text-gray-400 hover:bg-gray-800"
          }`}
        >
          Domain Glossary
        </button>
      </div>

      {tab === "patterns" && (
        <>
          {/* Toolbar */}
          <div className="flex flex-wrap gap-3 mb-4">
            <input
              type="text"
              placeholder="Search patterns..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPatternsPage(1); }}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]"
            />
            <select
              value={filterMode}
              onChange={(e) => { setFilterMode(e.target.value); setPatternsPage(1); }}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All Modes</option>
              {ANCHOR_MODES.map((m) => (
                <option key={m} value={m}>
                  {MODE_LABELS[m] || m}
                </option>
              ))}
            </select>
            <button
              onClick={() => {
                resetForm();
                setShowAdd(true);
              }}
              className="bg-sky-600 hover:bg-sky-500 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              + Add Pattern
            </button>
          </div>

          {/* Add/Edit form */}
          {showAdd && (
            <form
              onSubmit={handleSubmit}
              className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mb-6 space-y-3"
            >
              <div className="text-sm font-medium text-gray-300 mb-2">
                {editId ? "Edit Anchor Pattern" : "New Anchor Pattern"}
              </div>
              {error && (
                <div className="text-red-400 text-xs bg-red-900/20 px-3 py-2 rounded">
                  {error}
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-400 block mb-1">Mode</label>
                  <select
                    value={formMode}
                    onChange={(e) => setFormMode(e.target.value)}
                    required
                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm"
                  >
                    <option value="">Select mode...</option>
                    {ANCHOR_MODES.map((m) => (
                      <option key={m} value={m}>
                        {MODE_LABELS[m] || m}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-400 block mb-1">Label</label>
                  <input
                    type="text"
                    value={formLabel}
                    onChange={(e) => setFormLabel(e.target.value)}
                    required
                    placeholder="e.g. greeting_hello"
                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">
                  Regex Pattern
                </label>
                <input
                  type="text"
                  value={formPattern}
                  onChange={(e) => setFormPattern(e.target.value)}
                  required
                  placeholder="e.g. (hello|hi|good\s*(morning|afternoon))"
                  className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm font-mono"
                />
              </div>
              <div className="flex items-center gap-4">
                <div>
                  <label className="text-xs text-gray-400 block mb-1">
                    Weight (1-5)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={formWeight}
                    onChange={(e) => setFormWeight(Number(e.target.value))}
                    className="w-20 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm"
                  />
                </div>
                <div className="flex gap-2 ml-auto mt-4">
                  <button
                    type="button"
                    onClick={resetForm}
                    className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="bg-sky-600 hover:bg-sky-500 text-white px-4 py-2 rounded-lg text-sm font-medium"
                  >
                    {editId ? "Update" : "Create"}
                  </button>
                </div>
              </div>
            </form>
          )}

          {/* Grouped anchor list */}
          <div className="space-y-4">
            {Object.entries(grouped)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([mode, items]) => (
                <div
                  key={mode}
                  className="bg-gray-800/30 border border-gray-700/50 rounded-lg overflow-hidden"
                >
                  <div className="px-4 py-2 border-b border-gray-700/50 flex items-center gap-2">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${MODE_COLORS[mode] || MODE_COLORS.general}`}
                    >
                      {MODE_LABELS[mode] || mode}
                    </span>
                    <span className="text-xs text-gray-500">
                      {items.length} pattern{items.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="divide-y divide-gray-700/30">
                    {items.map((anchor) => (
                      <div
                        key={anchor.id}
                        className={`px-4 py-2.5 flex items-center gap-3 text-sm ${
                          !anchor.is_active ? "opacity-40" : ""
                        }`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-gray-300 font-medium">
                              {anchor.label}
                            </span>
                            {anchor.weight > 1 && (
                              <span className="text-xs text-amber-400">
                                ×{anchor.weight}
                              </span>
                            )}
                            <span
                              className={`text-[10px] px-1.5 py-0.5 rounded ${
                                anchor.source === "seed"
                                  ? "bg-gray-700 text-gray-400"
                                  : anchor.source === "manual"
                                    ? "bg-sky-900/50 text-sky-400"
                                    : "bg-green-900/50 text-green-400"
                              }`}
                            >
                              {anchor.source}
                            </span>
                          </div>
                          <code className="text-xs text-gray-500 block mt-0.5 truncate">
                            {anchor.pattern}
                          </code>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={() => handleToggle(anchor.id)}
                            title={anchor.is_active ? "Disable" : "Enable"}
                            className={`px-2 py-1 rounded text-xs ${
                              anchor.is_active
                                ? "bg-green-900/30 text-green-400 hover:bg-green-900/50"
                                : "bg-gray-700 text-gray-500 hover:bg-gray-600"
                            }`}
                          >
                            {anchor.is_active ? "ON" : "OFF"}
                          </button>
                          <button
                            onClick={() => startEdit(anchor)}
                            className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300 hover:bg-gray-600"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDelete(anchor.id)}
                            className="px-2 py-1 rounded text-xs text-red-400 hover:bg-red-900/30"
                          >
                            ×
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
          </div>

          <Pagination
            currentPage={patternsPage}
            totalItems={filtered.length}
            pageSize={patternsPageSize}
            onPageChange={setPatternsPage}
            onPageSizeChange={(s) => { setPatternsPageSize(s); setPatternsPage(1); }}
          />

          {filtered.length === 0 && (
            <div className="text-center text-gray-500 py-12">
              No anchor patterns found.
            </div>
          )}
        </>
      )}

      {tab === "overrides" && (
        <div>
          <p className="text-sm text-gray-400 mb-4">
            Log of manual anchor mode corrections. These are used for learning
            and pattern improvement.
          </p>
          {overrides.length === 0 ? (
            <div className="text-center text-gray-500 py-12">
              No overrides recorded yet.
            </div>
          ) : (
            <>
            <div className="bg-gray-800/30 border border-gray-700/50 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-gray-400 text-xs">
                    <th className="px-4 py-2 text-left">Segment Text</th>
                    <th className="px-4 py-2 text-left">Original</th>
                    <th className="px-4 py-2 text-left">Corrected</th>
                    <th className="px-4 py-2 text-left">Source</th>
                    <th className="px-4 py-2 text-left">File</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/30">
                  {overrides.slice((overridesPage - 1) * overridesPageSize, overridesPage * overridesPageSize).map((o) => (
                    <tr key={o.id}>
                      <td className="px-4 py-2 text-gray-300 max-w-xs truncate">
                        {o.segment_text}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`px-2 py-0.5 rounded text-xs ${MODE_COLORS[o.original_mode] || MODE_COLORS.general}`}
                        >
                          {MODE_LABELS[o.original_mode] || o.original_mode}
                        </span>
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`px-2 py-0.5 rounded text-xs ${MODE_COLORS[o.corrected_mode] || MODE_COLORS.general}`}
                        >
                          {MODE_LABELS[o.corrected_mode] || o.corrected_mode}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-gray-500 text-xs">
                        {o.source}
                      </td>
                      <td className="px-4 py-2 text-gray-500 text-xs truncate max-w-[120px]">
                        {o.filename}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Pagination
              currentPage={overridesPage}
              totalItems={overrides.length}
              pageSize={overridesPageSize}
              onPageChange={setOverridesPage}
              onPageSizeChange={(s) => { setOverridesPageSize(s); setOverridesPage(1); }}
            />
            </>
          )}
        </div>
      )}

      {tab === "glossary" && (
        <>
          <p className="text-sm text-gray-400 mb-4">
            Domain-specific terms for each anchor mode. Fed to Gemini and used for
            N-gram domain boost to improve correction accuracy.
          </p>

          {/* Toolbar */}
          <div className="flex flex-wrap gap-3 mb-4">
            <input
              type="text"
              placeholder="Search terms..."
              value={glossarySearch}
              onChange={(e) => { setGlossarySearch(e.target.value); setGlossaryPage(1); }}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]"
            />
            <select
              value={glossaryFilterMode}
              onChange={(e) => { setGlossaryFilterMode(e.target.value); setGlossaryPage(1); }}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All Modes</option>
              {ANCHOR_MODES.map((m) => (
                <option key={m} value={m}>
                  {MODE_LABELS[m] || m}
                </option>
              ))}
            </select>
            <button
              onClick={() => {
                resetGlossaryForm();
                setShowGlossaryAdd(true);
              }}
              className="bg-sky-600 hover:bg-sky-500 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              + Add Term
            </button>
          </div>

          {/* Add/Edit form */}
          {showGlossaryAdd && (
            <form
              onSubmit={handleGlossarySubmit}
              className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mb-6 space-y-3"
            >
              <div className="text-sm font-medium text-gray-300 mb-2">
                {glossaryEditId ? "Edit Glossary Term" : "New Glossary Term"}
              </div>
              {glossaryError && (
                <div className="text-red-400 text-xs bg-red-900/20 px-3 py-2 rounded">
                  {glossaryError}
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-400 block mb-1">Anchor Mode</label>
                  <select
                    value={gFormMode}
                    onChange={(e) => setGFormMode(e.target.value)}
                    required
                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm"
                  >
                    <option value="">Select mode...</option>
                    {ANCHOR_MODES.map((m) => (
                      <option key={m} value={m}>
                        {MODE_LABELS[m] || m}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-400 block mb-1">Term</label>
                  <input
                    type="text"
                    value={gFormTerm}
                    onChange={(e) => setGFormTerm(e.target.value)}
                    required
                    placeholder="e.g. minimum amount due"
                    className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={resetGlossaryForm}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="bg-sky-600 hover:bg-sky-500 text-white px-4 py-2 rounded-lg text-sm font-medium"
                >
                  {glossaryEditId ? "Update" : "Create"}
                </button>
              </div>
            </form>
          )}

          {/* Grouped glossary terms */}
          <div className="space-y-4">
            {Object.entries(glossaryGrouped)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([mode, terms]) => (
                <div
                  key={mode}
                  className="bg-gray-800/30 border border-gray-700/50 rounded-lg overflow-hidden"
                >
                  <div className="px-4 py-2 border-b border-gray-700/50 flex items-center gap-2">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${MODE_COLORS[mode] || MODE_COLORS.general}`}
                    >
                      {MODE_LABELS[mode] || mode}
                    </span>
                    <span className="text-xs text-gray-500">
                      {terms.length} term{terms.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="divide-y divide-gray-700/30">
                    {terms.map((t) => (
                      <div
                        key={t.id}
                        className="px-4 py-2.5 flex items-center gap-3 text-sm"
                      >
                        <span className="flex-1 text-gray-300">{t.term}</span>
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={() => startGlossaryEdit(t)}
                            className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300 hover:bg-gray-600"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleGlossaryDelete(t.id)}
                            className="px-2 py-1 rounded text-xs text-red-400 hover:bg-red-900/30"
                          >
                            ×
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
          </div>

          <Pagination
            currentPage={glossaryPage}
            totalItems={filteredGlossary.length}
            pageSize={glossaryPageSize}
            onPageChange={setGlossaryPage}
            onPageSizeChange={(s) => { setGlossaryPageSize(s); setGlossaryPage(1); }}
          />

          {filteredGlossary.length === 0 && (
            <div className="text-center text-gray-500 py-12">
              No glossary terms found.
            </div>
          )}
        </>
      )}
    </div>
  );
}
