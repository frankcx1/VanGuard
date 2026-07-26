"""INT4 export helper (PLAN.md §6).

Wraps ``optimum-cli export openvino`` with the flags this project uses, so
the export is reproducible and documented rather than a shell one-liner lost
to history.

Run:  .venv\\Scripts\\python.exe inference\\export.py [--model <hf-id>] [--npu]

NPU note [verified-external — OpenVINO GenAI NPU docs]: the NPU pipeline
wants **symmetric, channel-wise** INT4 weights (``--sym --group-size -1
--ratio 1.0``). That trades a little accuracy against group-wise
quantisation; if P4 shows quality problems on the cooktop question,
re-export without ``--npu`` and serve that variant on GPU instead.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Primary model (PLAN.md §6): modern 3-4B instruct with NATIVE tool calling.
# Qwen3-4B-Instruct-2507: Apache-2.0, native function calling, no forced
# thinking mode. The model is a config value — swapping it is one flag.
DEFAULT_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
# Fallback exactly as the brief specifies, if 4B can't hold the reasoning:
FALLBACK_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"


def out_dir_for(model_id: str, npu: bool) -> Path:
    slug = model_id.split("/")[-1].lower().replace(".", "").replace("-", "_")
    return REPO_ROOT / f"ov_{slug}_int4{'_npu' if npu else ''}"


def export(model_id: str, npu: bool = True, force: bool = False) -> Path:
    out = out_dir_for(model_id, npu)
    if (out / "openvino_model.xml").exists() and not force:
        print(f"already exported: {out}")
        return out
    optimum_cli = Path(sys.executable).parent / "optimum-cli.exe"
    cmd = [
        str(optimum_cli), "export", "openvino",
        "--model", model_id,
        "--task", "text-generation-with-past",
        "--weight-format", "int4",
    ]
    if npu:
        cmd += ["--sym", "--group-size", "-1", "--ratio", "1.0"]
    cmd += [str(out)]
    print("running:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    if not (out / "openvino_model.xml").exists():
        raise RuntimeError(
            f"exporter exited 0 but {out / 'openvino_model.xml'} is missing — "
            "do not trust a silent exit; check the exporter output")
    print(f"exported: {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--npu", action="store_true", default=True,
                    help="NPU-friendly quantisation (sym, channel-wise; default)")
    ap.add_argument("--no-npu", dest="npu", action="store_false")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    export(a.model, npu=a.npu, force=a.force)
