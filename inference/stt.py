"""Offline speech-to-text: Whisper on OpenVINO (P5 demo mode).

Same silicon, same no-cloud rule as the LLM: whisper-base.en exported to
OpenVINO serves from GPU (CPU fallback). The browser records raw 16kHz PCM
and posts a WAV — no browser speech APIs, which are cloud-backed.
"""
from __future__ import annotations

import io
import time
import wave
from pathlib import Path

import openvino_genai as ov_genai

SAMPLE_RATE = 16_000


class SttEngine:
    def __init__(self, model_dir: str | Path,
                 device_order=("GPU", "CPU")):
        self.model_dir = str(model_dir)
        errors = []
        t0 = time.perf_counter()
        for device in device_order:
            try:
                self.pipe = ov_genai.WhisperPipeline(self.model_dir, device)
                self.device = device
                break
            except Exception as e:
                errors.append(f"{device}: {type(e).__name__}: {e}")
        else:
            raise RuntimeError("whisper load failed:\n  " + "\n  ".join(errors))
        self.load_s = time.perf_counter() - t0

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        pcm = self._decode_wav(wav_bytes)
        result = self.pipe.generate(pcm)
        return " ".join(t.strip() for t in result.texts).strip()

    @staticmethod
    def _decode_wav(wav_bytes: bytes) -> list[float]:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            if w.getframerate() != SAMPLE_RATE:
                raise ValueError(f"expected {SAMPLE_RATE}Hz, got {w.getframerate()}")
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                raise ValueError("expected 16-bit mono PCM")
            raw = w.readframes(w.getnframes())
        return [int.from_bytes(raw[i:i + 2], "little", signed=True) / 32768.0
                for i in range(0, len(raw), 2)]
