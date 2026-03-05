import { useEffect, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import { deleteSession, listSessions, transcribeAudio } from "../api";
import type { RefinementResponse, SessionSummary } from "../types";
import ResultsPanel from "../components/ResultsPanel";

export default function DashboardPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadResult, setUploadResult] = useState<RefinementResponse | null>(null);
  const [error, setError] = useState("");
  const [speaker, setSpeaker] = useState("agent");

  useEffect(() => {
    loadSessions();
  }, []);

  async function loadSessions() {
    try {
      const data = await listSessions();
      setSessions(data.sessions);
    } catch {}
  }

  async function handleUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError("");
    setUploadResult(null);
    try {
      const res = await transcribeAudio(file, speaker);
      setUploadResult(res);
      loadSessions(); // refresh history
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch {}
  }

  return (
    <div className="space-y-8">
      {/* Upload section */}
      <section className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h2 className="text-lg font-semibold mb-4">Upload Audio</h2>
        <div className="flex items-center gap-4">
          <select
            value={speaker}
            onChange={(e) => setSpeaker(e.target.value)}
            className="rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
          >
            <option value="agent">Agent</option>
            <option value="client">Client</option>
          </select>

          <label
            className={`px-5 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors
              ${loading ? "bg-gray-700 opacity-50 cursor-wait" : "bg-sky-600 hover:bg-sky-500"}`}
          >
            {loading ? "Transcribing..." : "Choose Audio File"}
            <input
              type="file"
              accept="audio/*"
              onChange={handleUpload}
              disabled={loading}
              className="hidden"
            />
          </label>
        </div>

        {error && (
          <div className="mt-4 rounded-lg bg-red-900/30 border border-red-800 p-3 text-sm text-red-300">
            {error}
          </div>
        )}
      </section>

      {/* Latest result */}
      {uploadResult && (
        <ResultsPanel
          segments={uploadResult.segments}
          totalCorrections={uploadResult.total_corrections}
        />
      )}

      {/* Session history */}
      <section>
        <h2 className="text-lg font-semibold mb-4">Past Refinements</h2>
        {sessions.length === 0 ? (
          <p className="text-gray-500 text-sm">No sessions yet. Upload an audio file above.</p>
        ) : (
          <div className="space-y-2">
            {sessions.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between bg-gray-900 rounded-lg border border-gray-800 px-4 py-3"
              >
                <button
                  onClick={() => navigate(`/sessions/${s.id}`)}
                  className="flex-1 text-left hover:text-sky-400 transition-colors"
                >
                  <div className="text-sm font-medium">{s.filename}</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {new Date(s.created_at).toLocaleString()} &middot;{" "}
                    {s.total_segments} segments &middot; {s.total_corrections} corrections
                    {s.speaker && <> &middot; {s.speaker}</>}
                  </div>
                </button>
                <button
                  onClick={() => handleDelete(s.id)}
                  className="ml-3 text-xs text-gray-600 hover:text-red-400 transition-colors"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
