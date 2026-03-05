import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getSession } from "../api";
import type { SessionDetail } from "../types";
import ResultsPanel from "../components/ResultsPanel";

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    getSession(Number(id))
      .then(setSession)
      .catch(() => setError("Session not found"));
  }, [id]);

  if (error) {
    return (
      <div>
        <p className="text-red-400">{error}</p>
        <button onClick={() => navigate("/")} className="mt-2 text-sky-400 text-sm">
          Back to Dashboard
        </button>
      </div>
    );
  }

  if (!session) {
    return <p className="text-gray-500">Loading...</p>;
  }

  const result = session.result_json;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate("/")}
          className="text-gray-400 hover:text-gray-200 text-sm"
        >
          ← Back
        </button>
        <div>
          <h2 className="text-lg font-semibold">{session.filename}</h2>
          <p className="text-xs text-gray-500">
            {new Date(session.created_at).toLocaleString()} &middot;{" "}
            {session.speaker || "no speaker"} &middot;{" "}
            {session.total_segments} segments &middot; {session.total_corrections} corrections
          </p>
        </div>
      </div>

      {/* Results */}
      {result && (
        <ResultsPanel
          segments={result.segments}
          totalCorrections={result.total_corrections}
        />
      )}
    </div>
  );
}
