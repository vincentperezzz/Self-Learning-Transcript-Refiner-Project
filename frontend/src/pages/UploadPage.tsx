import { useState, useRef, type ChangeEvent, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { transcribeAudio } from "../api";

export default function UploadPage() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [speaker, setSpeaker] = useState("agent");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  }

  async function handleSubmit() {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const { session_id } = await transcribeAudio(file, speaker);
      navigate(`/sessions/${session_id}`); // redirect immediately to session page
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate("/")}
          className="text-gray-400 hover:text-gray-200 text-sm"
        >
          ← Back
        </button>
        <h1 className="text-2xl font-bold text-white">Upload Audio</h1>
      </div>

      {/* Drop zone */}
      <div
        className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer ${
          dragOver
            ? "border-sky-500 bg-sky-900/10"
            : file
            ? "border-emerald-600 bg-emerald-900/10"
            : "border-gray-700 hover:border-gray-600 bg-gray-900/40"
        }`}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          ref={fileRef}
          type="file"
          accept="audio/*"
          onChange={handleFileChange}
          className="hidden"
        />
        {file ? (
          <div>
            <p className="text-emerald-400 font-medium">{file.name}</p>
            <p className="text-xs text-gray-500 mt-1">
              {(file.size / (1024 * 1024)).toFixed(2)} MB &middot; Click or drop to replace
            </p>
          </div>
        ) : (
          <div>
            <p className="text-gray-300 text-lg mb-1">
              Drop audio file here or click to browse
            </p>
            <p className="text-xs text-gray-600">
              Supports WAV, MP3, M4A, FLAC, OGG, WEBM
            </p>
          </div>
        )}
      </div>

      {/* Options */}
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-5">
        <label className="block text-sm text-gray-400 mb-2">Speaker Role</label>
        <div className="flex gap-3">
          {["agent", "client"].map((role) => (
            <button
              key={role}
              onClick={() => setSpeaker(role)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                speaker === role
                  ? "bg-sky-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              {role.charAt(0).toUpperCase() + role.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg bg-red-900/30 border border-red-800 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={!file || loading}
        className={`w-full py-3 rounded-xl text-sm font-semibold transition-colors ${
          !file || loading
            ? "bg-gray-800 text-gray-600 cursor-not-allowed"
            : "bg-sky-600 hover:bg-sky-500 text-white"
        }`}
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Uploading...
          </span>
        ) : (
          "Transcribe & Refine"
        )}
      </button>
    </div>
  );
}
