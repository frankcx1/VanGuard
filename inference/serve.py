"""OpenVINO GenAI wrapper with device-order fallback (PLAN.md §6).

Tries devices in the configured order (default NPU → GPU → CPU), remembers
which one actually loaded, and reports the serving device + perf metrics for
every request — the audit trail and the benchmark both depend on that.

Do not assume the NPU wins: token generation is memory-bandwidth-bound, so
expect the Arc iGPU to win tokens/sec and the NPU to win watts-per-token
(PLAN.md §5). This wrapper exists so that question can be answered with
measurements instead of vibes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import openvino_genai as ov_genai

DEFAULT_DEVICE_ORDER = ("NPU", "GPU", "CPU")

# NPU pipelines use static shapes; these bound them (PLAN.md §6 context
# discipline: system + tools ≤ 800 tokens, tool results ≤ 400, history rest).
NPU_PIPELINE_CONFIG = {
    # 4096: headroom over the ~2.3k prompts seen after a morning of filmed
    # takes fattened the snapshot's guardian log (2048 overflowed mid-shoot).
    "MAX_PROMPT_LEN": 4096,
    "MIN_RESPONSE_LEN": 128,
}


@dataclass
class GenResult:
    text: str
    device: str
    ttft_ms: float
    tokens_per_s: float
    n_new_tokens: int
    duration_ms: float


class InferenceEngine:
    """Loads once on the first device that accepts the model."""

    def __init__(self, model_dir: str | Path,
                 device_order=DEFAULT_DEVICE_ORDER):
        self.model_dir = str(model_dir)
        self.device: str | None = None
        self.load_s: float | None = None
        self.pipe = None
        errors: list[str] = []
        for device in device_order:
            t0 = time.perf_counter()
            try:
                kwargs = dict(NPU_PIPELINE_CONFIG) if device == "NPU" else {}
                self.pipe = ov_genai.LLMPipeline(self.model_dir, device, **kwargs)
                self.load_s = time.perf_counter() - t0
                self.device = device
                break
            except Exception as e:  # try the next device; record why
                errors.append(f"{device}: {type(e).__name__}: {e}")
        if self.pipe is None:
            raise RuntimeError(
                "no device could load the model:\n  " + "\n  ".join(errors))
        self.load_errors = errors    # devices that were tried and failed

    def generate(self, prompt: str, max_new_tokens: int = 128,
                 temperature: float = 0.0) -> GenResult:
        cfg = ov_genai.GenerationConfig()
        # Callers hand us fully-rendered prompts (chat template + tools
        # already applied). ov_genai defaults to re-applying the model's
        # template to raw strings, which double-wraps the prompt and buries
        # the tool definitions inside a quoted user turn — turn that off.
        cfg.apply_chat_template = False
        cfg.max_new_tokens = max_new_tokens
        # Greedy INT4 4B models loop on their own phrasing; a mild penalty
        # stops the "verdict restated five ways" failure mode.
        cfg.repetition_penalty = 1.1
        if temperature > 0:
            cfg.do_sample = True
            cfg.temperature = temperature
        res = self.pipe.generate([prompt], cfg)
        pm = res.perf_metrics
        return GenResult(
            text=res.texts[0],
            device=self.device,
            ttft_ms=pm.get_ttft().mean,
            tokens_per_s=pm.get_throughput().mean,
            n_new_tokens=pm.get_num_generated_tokens(),
            duration_ms=pm.get_generate_duration().mean,
        )
