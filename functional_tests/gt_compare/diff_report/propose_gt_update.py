# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Decide whether an ai_verdict.json result is trustworthy enough to
auto-stage a groundtruth update, and if so, copy the predicted file over the
groundtruth file.

This is intentionally narrow and conservative:
- Only "cosmetic_drift" verdicts at/above --min-confidence are eligible.
- Defense in depth: re-checks *every* frame in summary.json (not just the
  handful of frames actually shown to the model), and refuses if even a
  single frame has an unmatched (missing/extra) box - a real detection
  change should never be waved through just because the model only saw a
  sample of frames.

This script never touches git, never opens a PR, and never talks to an LLM -
it only decides eligibility and copies one file. The CI workflow calls this
once per failed test's report directory and handles branch/PR creation for
the whole batch. Paths are read from paths.json (written by
generate_diff_report.py) so this always operates on the exact files that
were actually compared/rendered - never re-derived/guessed.

Exit codes: 0 = groundtruth updated, 2 = not eligible (expected/normal
outcome for the CI loop, not an error).

Usage
-----
    python propose_gt_update.py --report-dir /tmp/diff_report_detection_yolov5su_GPU \
        --min-confidence 0.8
"""
import argparse
import json
import os
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report-dir", required=True,
                        help="Output dir of generate_diff_report.py (must contain paths.json, "
                             "ai_verdict.json and summary.json)")
    parser.add_argument("--min-confidence", type=float, default=0.8,
                        help="Minimum ai_verdict.json confidence required (default: 0.8)")
    args = parser.parse_args()

    verdict_path = os.path.join(args.report_dir, "ai_verdict.json")
    if not os.path.exists(verdict_path):
        print(f"No ai_verdict.json in {args.report_dir}", file=sys.stderr)
        sys.exit(2)
    with open(verdict_path) as f:
        verdict = json.load(f)

    if verdict.get("verdict") != "cosmetic_drift":
        print(f"Verdict is '{verdict.get('verdict')}', not eligible for auto-update.")
        sys.exit(2)
    confidence = verdict.get("confidence", 0)
    if confidence < args.min_confidence:
        print(f"Confidence {confidence} is below the {args.min_confidence} threshold.")
        sys.exit(2)

    summary_path = os.path.join(args.report_dir, "summary.json")
    with open(summary_path) as f:
        summary = json.load(f)
    for entry in summary:
        if entry.get("unmatched_gt") or entry.get("unmatched_pred"):
            print(f"Frame {entry['timestamp']} has an unmatched (missing/extra) box - refusing "
                  f"auto-update despite the '{verdict['verdict']}' verdict.", file=sys.stderr)
            sys.exit(2)

    paths_path = os.path.join(args.report_dir, "paths.json")
    if not os.path.exists(paths_path):
        print(f"No paths.json in {args.report_dir} (needs a generate_diff_report.py from after "
              f"this feature was added)", file=sys.stderr)
        sys.exit(2)
    with open(paths_path) as f:
        paths = json.load(f)
    gt_path, pred_path = paths["gt_path"], paths["pred_path"]
    if not os.path.exists(pred_path):
        print(f"Predicted file not found: {pred_path}", file=sys.stderr)
        sys.exit(2)

    shutil.copyfile(pred_path, gt_path)
    print(f"Updated groundtruth: {gt_path}")


if __name__ == "__main__":
    main()
