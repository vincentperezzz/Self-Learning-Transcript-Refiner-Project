import { useState } from "react";
import TranscriptInput from "./components/TranscriptInput";
import ResultsPanel from "./components/ResultsPanel";
import StatusBar from "./components/StatusBar";
import { refineSegments, transcribeAudio } from "./api";
import type { RefinementResponse, TranscriptSegment } from "./types";

export default function App() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RefinementResponse | null>(null);
  const [error, setError] = useState("");

  async function handleRefine(segments: TranscriptSegment[]) {
    setLoading(true);
    setError("");
    try {
      const res = await refineSegments(segments);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refinement failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload(file: File) {
    setLoading(true);
    setError("");
    try {
      const res = await transcribeAudio(file);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transcription failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <header className="flex items-end justify-between border-b border-gray-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Phoenix <span className="text-sky-400">3.0</span>
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Self-Learning Transcript Refiner
          </p>
        </div>
        <StatusBar />
      </header>

      {/* Input */}
      <TranscriptInput
        onRefine={handleRefine}
        onUpload={handleUpload}
        loading={loading}
      />

      {/* Error */}
      {error && (
        <div className="rounded-lg bg-red-900/30 border border-red-800 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

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
