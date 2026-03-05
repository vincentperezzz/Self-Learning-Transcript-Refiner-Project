"""
Whisper Transcription Server (FastAPI)

Runs Whisper large-v3-turbo on local GPU (optimized for RTX 3050 Ti 4GB VRAM).

Docker:      docker compose up whisper
Standalone:  python app_fastapi.py
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

import torch
import uvicorn
import whisper
from fastapi import FastAPI, File, Query, UploadFile

app = FastAPI(title="Phoenix Whisper API", version="1.0.0")

# ---------------------------------------------------------------------------
# Model loading (happens once at startup)
# ---------------------------------------------------------------------------
MODEL_SIZE = os.getenv("WHISPER_MODEL", "large-v3-turbo")
print(f"Loading Whisper {MODEL_SIZE}...")
device = "cuda" if torch.cuda.is_available() else "cpu"
model = whisper.load_model(MODEL_SIZE, device=device)
# Free CUDA cache after load to maximize available VRAM for inference
if device == "cuda":
    torch.cuda.empty_cache()
print(f"Whisper {MODEL_SIZE} loaded on {device}. VRAM free: {torch.cuda.mem_get_info()[0] // 1024**2}MB" if device == "cuda" else f"Whisper {MODEL_SIZE} loaded on {device}.")


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    word_timestamps: bool = Query(True),
    language: Optional[str] = Query(None),
):
    """
    Accept an audio file, run Whisper, return segments with word-level
    timestamps and per-word probability scores.

    This matches the exact response shape that Phoenix backend's
    whisper_client.py expects.
    """
    audio_bytes = await file.read()

    # Whisper requires a file path
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        result = model.transcribe(
            tmp_path,
            word_timestamps=word_timestamps,
            language=language,
            fp16=torch.cuda.is_available(),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Format response
    segments = []
    for seg in result.get("segments", []):
        segment_data = {
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "avg_logprob": seg.get("avg_logprob", -0.5),
        }
        if "words" in seg:
            segment_data["words"] = [
                {
                    "word": w["word"],
                    "start": w["start"],
                    "end": w["end"],
                    "probability": round(w.get("probability", 0.0), 4),
                }
                for w in seg["words"]
            ]
        segments.append(segment_data)

    return {"segments": segments}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_SIZE,
        "device": device,
        "cuda_available": torch.cuda.is_available(),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
