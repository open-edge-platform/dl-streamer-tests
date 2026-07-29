# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""AI "first-line judge" for gt-comparison test failures.

Takes the output directory produced by generate_diff_report.py (summary.json +
frames/*.png) and asks a vision-capable LLM (by default via GitHub Models,
https://docs.github.com/en/rest/models/inference) to classify the failure as
either a cosmetic/expected drift (e.g. slightly shifted bbox, tiny confidence
change) or a real regression (missed/extra detection, wrong label, large
confidence swing).

This is strictly advisory: it NEVER modifies groundtruth, NEVER decides the
CI pass/fail status, and NEVER opens/merges a PR by itself. It only writes a
structured verdict (ai_verdict.json) and, if an HTML report is present, adds
a banner summarizing the verdict for a human reviewer. A human must always
review and approve any groundtruth update.

Auth: a GitHub fine-grained personal access token (or GitHub App token) with
the `models: read` permission, passed via --token or the GITHUB_TOKEN /
MODELS_TOKEN environment variable.

Usage
-----
    python ai_verdict.py --report-dir /tmp/diff_report_detection_yolov5su_GPU \
        --test-name detection_yolov5su_GPU --max-frames 6
"""
import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import List, Optional

DEFAULT_API_BASE = "https://models.github.ai/inference"
DEFAULT_MODEL = "openai/gpt-4o"

SYSTEM_PROMPT = """You are a strict but pragmatic reviewer for a video-analytics (object \
detection/classification) regression test suite based on DL Streamer / GStreamer pipelines.

You will be shown, for a single failing test case, the most divergent video frames. On each \
image, GREEN boxes are the groundtruth (GT, i.e. the expected/reference result) and RED boxes \
are the newly produced (predicted) result. Each image also carries a legend in the top-left \
corner confirming the color mapping. Below each image you get the numeric diff for that frame \
(matched pairs with IoU and confidence, plus counts of unmatched/missing/extra boxes).

Classify the OVERALL failure using these rules of thumb:
- "cosmetic_drift": boxes for the same label are only slightly shifted (still clearly the same \
object, IoU noticeably above 0), confidence differs only slightly, no boxes are entirely missing \
or entirely new, no label changed. This looks like normal model/version numeric drift.
- "regression": a box is completely missing or completely new (a real object was not detected, \
or a false positive appeared), a label changed to a different class, or confidence changed \
drastically (e.g. a real detection became near-zero confidence or vice versa).
- "uncertain": evidence is mixed, images are inconclusive, or you are not confident either way.

Always err on the side of "regression" or "uncertain" when in doubt - false negatives (missing a \
real bug) are much worse than asking a human to double check a cosmetic change.

Respond ONLY with a JSON object matching the provided schema. Do not include any other text."""

RESPONSE_SCHEMA = {
    "name": "gt_diff_verdict",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": ["cosmetic_drift", "regression", "uncertain"]},
            "confidence": {"type": "number", "description": "0.0-1.0"},
            "rationale": {"type": "string", "description": "Short, concrete justification referencing what is seen in the frames."},
            "per_frame_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "timestamp": {"type": "integer"},
                        "note": {"type": "string"},
                    },
                    "required": ["timestamp", "note"],
                },
            },
        },
        "required": ["verdict", "confidence", "rationale", "per_frame_notes"],
    },
}


def _load_top_frames(report_dir: str, max_frames: int) -> List[dict]:
    with open(os.path.join(report_dir, "summary.json"), "r") as f:
        summary = json.load(f)
    diffing = [s for s in summary if s["severity"] > 0]
    diffing.sort(key=lambda s: s["severity"], reverse=True)
    top = diffing[:max_frames]
    frames = []
    for entry in top:
        img_path = os.path.join(report_dir, "frames", f"frame_{entry['timestamp']}.png")
        if os.path.exists(img_path):
            frames.append({**entry, "image_path": img_path})
    return frames


def _frame_stats_text(entry: dict) -> str:
    lines = [f"timestamp={entry['timestamp']} severity={entry['severity']:.3f}"]
    if entry["unmatched_gt"]:
        lines.append(f"  - {entry['unmatched_gt']} GT box(es) with no matching prediction (possible missed detection)")
    if entry["unmatched_pred"]:
        lines.append(f"  - {entry['unmatched_pred']} predicted box(es) with no matching GT (possible false positive)")
    for p in entry["pairs"]:
        lines.append(f"  - label={p['label']} gt_conf={p['gt_prob']} pred_conf={p['pred_prob']} iou={p['iou']:.3f}")
    return "\n".join(lines)


def _build_messages(test_name: str, frames: List[dict]) -> list:
    content = [{"type": "text", "text": f"Test case: {test_name}\n"
                                        f"Showing the {len(frames)} most divergent frames "
                                        f"(sorted worst first)."}]
    for entry in frames:
        with open(entry["image_path"], "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        content.append({"type": "text", "text": _frame_stats_text(entry)})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def call_model(messages: list, api_base: str, model: str, token: str, org: Optional[str] = None) -> dict:
    url = f"{api_base}/orgs/{org}/inference/chat/completions" if org else f"{api_base}/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub Models request failed ({e.code}): {e.read().decode('utf-8', 'ignore')}") from e
    return json.loads(payload["choices"][0]["message"]["content"])


VERDICT_COLORS = {
    "cosmetic_drift": "#2e7d32",
    "regression": "#b33",
    "uncertain": "#b8860b",
}


def inject_verdict_banner(report_dir: str, verdict: dict):
    index_path = os.path.join(report_dir, "index.html")
    if not os.path.exists(index_path):
        return
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    color = VERDICT_COLORS.get(verdict["verdict"], "#555")
    banner = f"""
<div class="ai-verdict" style="border-left:6px solid {color}; background:#fff;
     border:1px solid #ddd; border-radius:6px; padding:12px 16px; margin-bottom:20px;">
  <h2 style="margin:0 0 6px 0; color:{color};">AI verdict: {verdict['verdict']}
      (confidence {verdict['confidence']:.2f})</h2>
  <p>{verdict['rationale']}</p>
  <p><em>This is an automated, advisory-only assessment. A human must review and approve any
     groundtruth change.</em></p>
</div>
"""
    updated = re.sub(r"(<body[^>]*>)", r"\1" + banner, html_content, count=1)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(updated)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report-dir", required=True, help="Output dir of generate_diff_report.py")
    parser.add_argument("--test-name", required=True, help="Name of the failing test case, for context")
    parser.add_argument("--max-frames", type=int, default=6, help="Max number of frames sent to the model (cost control)")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="OpenAI-compatible API base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model id, e.g. openai/gpt-4o")
    parser.add_argument("--org", default=None, help="Optional GitHub org for attributed usage")
    parser.add_argument("--token", default=None, help="Auth token (defaults to GITHUB_TOKEN/MODELS_TOKEN env var)")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("MODELS_TOKEN")
    if not token:
        raise SystemExit("No token provided. Set --token or GITHUB_TOKEN/MODELS_TOKEN env var "
                         "(needs 'models: read' permission).")

    frames = _load_top_frames(args.report_dir, args.max_frames)
    if not frames:
        print("No diffing frames found in summary.json - nothing to send to the model.")
        return

    messages = _build_messages(args.test_name, frames)
    verdict = call_model(messages, args.api_base, args.model, token, args.org)

    out_path = os.path.join(args.report_dir, "ai_verdict.json")
    with open(out_path, "w") as f:
        json.dump(verdict, f, indent=2)

    inject_verdict_banner(args.report_dir, verdict)

    print(f"Verdict: {verdict['verdict']} (confidence={verdict['confidence']:.2f})")
    print(verdict["rationale"])
    print(f"Full result written to {out_path}")


if __name__ == "__main__":
    main()
