"""OpenAI-compatible chat with a native tool-calling loop (PLAN.md §7, P4).

POST /v1/chat/completions — the seam the Master Index app will eventually
point at (PLAN.md §11). Non-streaming, greedy by default (deterministic on
camera).

Flow per request:
  render (system + history + tool schemas) via the model's own chat
  template → generate → parse ``<tool_call>`` blocks (Qwen3 emits
  Hermes-style JSON) → execute via ToolRunner (audited) → feed results back
  as ``tool`` messages → repeat, max ``MAX_TOOL_ROUNDS`` → final text.

The engine loads lazily on the first request (NPU compile can take ~85s)
and generation runs in a worker thread so telemetry routes stay responsive.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api.tools import TOOL_SCHEMAS, ToolRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_TOOL_ROUNDS = 3
MAX_NEW_TOKENS = 512

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

SYSTEM_PROMPT = (
    "You are VanGuard, the offline power advisor for a Sprinter camper van "
    "(12V 300Ah LiFePO4, 400W solar, 3000W inverter; induction cooktop "
    "~1500W AC = ~1700W DC through the inverter).\n"
    "Rules:\n"
    "- Use tools for any current number - never guess telemetry.\n"
    "- For runtime/energy questions call estimate_runtime (pass "
    "duration_min when the user names a duration) and quote its numbers "
    "and verdict verbatim - never recompute or second-guess them.\n"
    "- Decide your verdict from the tool numbers BEFORE writing. Then "
    "answer: one verdict sentence first, then 2-4 short lines of supporting "
    "arithmetic. State the verdict exactly once; never contradict or repeat "
    "yourself.\n"
    "- Plain sentences, max ~100 words, no markdown headers or tables - "
    "this renders on a small dashboard.\n"
    "- If data is unavailable, say so plainly - never invent a value.\n"
    "- Never mention tool names or field names in the answer - speak in "
    "plain English quantities.\n"
    "- You are read-only: you can see everything and touch nothing."
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None          # informational; the loaded model serves
    max_tokens: int | None = None
    temperature: float | None = None


router = APIRouter()

_engine_lock = asyncio.Lock()


async def get_engine(request: Request):
    """Lazy singleton: load once, on first use, off the event loop."""
    app = request.app
    async with _engine_lock:
        if getattr(app.state, "engine", None) is None:
            from inference.serve import InferenceEngine
            cfg = app.state.cfg.get("inference", {})
            model_dir = REPO_ROOT / cfg.get(
                "model_dir", "ov_qwen3_4b_instruct_2507_int4_npu")
            order = tuple(cfg.get("device_order", ["GPU", "NPU", "CPU"]))
            if not (model_dir / "openvino_model.xml").exists():
                raise HTTPException(503, f"model not exported: {model_dir}")
            app.state.engine = await run_in_threadpool(
                InferenceEngine, str(model_dir), order)
            from transformers import AutoTokenizer
            app.state.chat_tokenizer = await run_in_threadpool(
                AutoTokenizer.from_pretrained, str(model_dir))
    return app.state.engine, app.state.chat_tokenizer


def parse_tool_calls(text: str) -> list[dict]:
    calls = []
    for raw in TOOL_CALL_RE.findall(text):
        try:
            d = json.loads(raw)
            if isinstance(d, dict) and "name" in d:
                calls.append({"name": d["name"],
                              "arguments": d.get("arguments") or {}})
        except json.JSONDecodeError:
            calls.append({"name": "_malformed", "arguments": {"raw": raw[:200]}})
    return calls


@router.post("/v1/chat/completions")
async def chat_completions(body: ChatRequest, request: Request):
    engine, tokenizer = await get_engine(request)
    runner = ToolRunner(request.app.state.store)
    simulated = request.app.state.simulated

    history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    history += [m.model_dump() for m in body.messages if m.role != "system"]

    trace: list[dict] = []
    t_start = time.perf_counter()
    final_text = ""
    for round_no in range(MAX_TOOL_ROUNDS + 1):
        allow_tools = round_no < MAX_TOOL_ROUNDS
        prompt = tokenizer.apply_chat_template(
            history,
            tools=TOOL_SCHEMAS if allow_tools else None,
            add_generation_prompt=True,
            tokenize=False,
        )
        gen = await run_in_threadpool(
            engine.generate, prompt,
            body.max_tokens or MAX_NEW_TOKENS,
            body.temperature or 0.0,
        )
        text = gen.text
        calls = parse_tool_calls(text) if allow_tools else []
        if not calls:
            final_text = TOOL_CALL_RE.sub("", text).strip()
            break
        history.append({"role": "assistant", "content": text})
        for call in calls:
            if call["name"] == "_malformed":
                result = {"error": "malformed tool_call JSON; fix and retry"}
            else:
                result = await runner.call(call["name"], call["arguments"],
                                           device=engine.device)
            trace.append({"tool": call["name"], "args": call["arguments"],
                          "result": result})
            history.append({
                "role": "tool",
                "content": json.dumps(result, separators=(",", ":")),
            })
    total_ms = int((time.perf_counter() - t_start) * 1000)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"vanguard/{Path(engine.model_dir).name}",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": final_text},
            "finish_reason": "stop",
        }],
        "usage": {"total_time_ms": total_ms},
        "vanguard": {
            "simulated": simulated,
            "device": engine.device,
            "tokens_per_s": round(gen.tokens_per_s, 1),
            "ttft_ms": round(gen.ttft_ms),
            "tool_calls": trace,
            "rounds": round_no + 1,
        },
    }
