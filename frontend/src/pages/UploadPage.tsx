import { useState, useRef, type ChangeEvent, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { transcribeAudio } from "../api";

interface UploadItem {
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  sessionKey?: string;
  error?: string;
}

export default function UploadPage() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [speaker, setSpeaker] = useState("agent");
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  function addFiles(fileList: FileList | File[]) {
    const newItems: UploadItem[] = Array.from(fileList).map((f) => ({
      file: f,
      status: "pending" as const,
    }));
    setItems((prev) => [...prev, ...newItems]);
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files?.length) addFiles(e.target.files);
    e.target.value = "";
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  }

  function removeItem(idx: number) {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleSubmit() {
    if (items.length === 0) return;
    setUploading(true);

    for (let i = 0; i < items.length; i++) {
      if (items[i].status !== "pending") continue;

      setItems((prev) =>
        prev.map((it, j) => (j === i ? { ...it, status: "uploading" } : it))
      );

      try {
        const { session_key } = await transcribeAudio(items[i].file, speaker);
        setItems((prev) =>
          prev.map((it, j) =>
            j === i ? { ...it, status: "done", sessionKey: session_key } : it
          )
        );
      } catch (err) {
        setItems((prev) =>
          prev.map((it, j) =>
            j === i
              ? { ...it, status: "error", error: err instanceof Error ? err.message : "Failed" }
              : it
          )
        );
      }
    }

    setUploading(false);
    // If single file, go to session detail. If multiple, go to dashboard.
    const doneItems = items.filter((it) => it.status === "done" || it.sessionKey);
    if (doneItems.length === 1 && doneItems[0].sessionKey) {
      navigate(`/sessions/${doneItems[0].sessionKey}`);
    } else {
      navigate("/");
    }
  }

  const doneCount = items.filter((it) => it.status === "done").length;

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
            : items.length > 0
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
          multiple
          onChange={handleFileChange}
          className="hidden"
        />
        {items.length > 0 ? (
          <div>
            <p className="text-emerald-400 font-medium">
              {items.length} file{items.length > 1 ? "s" : ""} selected
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Click or drop to add more files
            </p>
          </div>
        ) : (
          <div>
            <p className="text-gray-300 text-lg mb-1">
              Drop audio files here or click to browse
            </p>
            <p className="text-xs text-gray-600">
              Supports WAV, MP3, M4A, FLAC, OGG, WEBM — select multiple files
            </p>
          </div>
        )}
      </div>

      {/* File list */}
      {items.length > 0 && (
        <div className="bg-gray-900/60 border border-gray-800 rounded-xl divide-y divide-gray-800 overflow-hidden">
          {items.map((item, idx) => (
            <div key={idx} className="flex items-center gap-3 px-4 py-2.5">
              {/* Status icon */}
              {item.status === "pending" && (
                <span className="h-2 w-2 rounded-full bg-gray-500 shrink-0" />
              )}
              {item.status === "uploading" && (
                <span className="h-2 w-2 rounded-full bg-sky-500 animate-pulse shrink-0" />
              )}
              {item.status === "done" && (
                <span className="text-emerald-400 shrink-0 text-xs">✓</span>
              )}
              {item.status === "error" && (
                <span className="text-red-400 shrink-0 text-xs">✗</span>
              )}

              <span className="text-sm text-gray-200 truncate flex-1">{item.file.name}</span>
              <span className="text-xs text-gray-500">
                {(item.file.size / (1024 * 1024)).toFixed(1)} MB
              </span>

              {item.status === "error" && (
                <span className="text-xs text-red-400 truncate max-w-[120px]" title={item.error}>
                  {item.error}
                </span>
              )}

              {item.status === "pending" && !uploading && (
                <button
                  onClick={(e) => { e.stopPropagation(); removeItem(idx); }}
                  className="p-1 text-gray-500 hover:text-red-400 transition-colors"
                  title="Remove"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                </button>
              )}
            </div>
          ))}
        </div>
      )}

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

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={items.length === 0 || uploading}
        className={`w-full py-3 rounded-xl text-sm font-semibold transition-colors ${
          items.length === 0 || uploading
            ? "bg-gray-800 text-gray-600 cursor-not-allowed"
            : "bg-sky-600 hover:bg-sky-500 text-white"
        }`}
      >
        {uploading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Uploading {doneCount}/{items.length}...
          </span>
        ) : (
          `Transcribe & Refine ${items.length > 0 ? `(${items.length} file${items.length > 1 ? "s" : ""})` : ""}`
        )}
      </button>
    </div>
  );
}
