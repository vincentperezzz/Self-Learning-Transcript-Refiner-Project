import { useState, type ChangeEvent } from "react";
import type { TranscriptSegment } from "../types";

const PLACEHOLDER = `[
  {
    "start": 0.0,
    "end": 5.0,
    "text": "Good morning maam this is calling from Asti Madrid regarding your credit card account",
    "confidence": 0.75,
    "words": [
      {"word": "Good", "start": 0.0, "end": 0.3, "probability": 0.98},
      {"word": "morning", "start": 0.3, "end": 0.6, "probability": 0.97},
      {"word": "maam", "start": 0.7, "end": 0.9, "probability": 0.65},
      {"word": "Asti", "start": 1.8, "end": 2.1, "probability": 0.42},
      {"word": "Madrid", "start": 2.1, "end": 2.4, "probability": 0.55}
    ]
  }
]`;

interface Props {
  onRefine: (segments: TranscriptSegment[]) => void;
  onUpload: (file: File) => void;
  loading: boolean;
}

export default function TranscriptInput({ onRefine, onUpload, loading }: Props) {
  const [raw, setRaw] = useState("");
  const [error, setError] = useState("");

  function handleRefine() {
    setError("");
    try {
      const parsed = JSON.parse(raw || "[]");
      const segments: TranscriptSegment[] = Array.isArray(parsed) ? parsed : [parsed];
      if (segments.length === 0) {
        setError("Provide at least one segment.");
        return;
      }
      onRefine(segments);
    } catch {
      setError("Invalid JSON – paste a segment array.");
    }
  }

  function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) onUpload(file);
  }

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">Input</h2>

      {/* JSON textarea */}
      <div>
        <label className="block text-xs text-gray-400 mb-1">
          Paste Whisper segments (JSON)
        </label>
        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder={PLACEHOLDER}
          style={{ height: "330px" }}
          className="w-full rounded-lg bg-gray-800 border border-gray-700 p-3 text-sm font-mono
                     text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2
                     focus:ring-sky-600 resize-y"
        />
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="flex items-center gap-3">
        <button
          onClick={handleRefine}
          disabled={loading}
          className="px-5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-50
                     text-sm font-medium transition-colors"
        >
          {loading ? "Refining..." : "Refine Transcript"}
        </button>

        <span className="text-gray-600 text-xs">or</span>

        {/* Audio upload */}
        <label
          className="px-5 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-sm
                     font-medium cursor-pointer transition-colors"
        >
          Upload Audio
          <input
            type="file"
            accept="audio/*"
            onChange={handleFile}
            className="hidden"
          />
        </label>
      </div>
    </section>
  );
}
