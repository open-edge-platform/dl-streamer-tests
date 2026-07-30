# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Visual diff report generator for DL Streamer functional (video) tests.

When a pipeline_test video comparison fails (or is close to the failure
threshold) it is currently very hard to tell *why* just from the reported
"X% of frames differ" number. This tool renders the actual video frames for
the most divergent timestamps with both the groundtruth (GT) and the
predicted bounding boxes drawn on top, and produces a single self-contained
HTML report sorted from "worst" to "least bad" frame.

It is intentionally CI-agnostic and safe: it never modifies the groundtruth
or test results, it only reads the two JSON-lines files produced by
gvametapublish plus the source video and renders a report for a human (or an
AI reviewer) to look at.

Two ways to point it at its inputs:

1. Generic / recommended - resolve everything from the existing test-suite
   config (e.g. pipeline_test/configs_ov2/common/samples.json), just like
   the real test runner would, by test name:

    python generate_diff_report.py \
        --config pipeline_test/configs_ov2/common/samples.json \
        --test-name detection_yolov5su_GPU \
        --gt-dir pipeline_test/groundtruth_ov2/samples_TGL \
        --pred-dir /tmp/results/metadata \
        --output-dir /tmp/diff_report_detection_yolov5su_GPU \
        --top-percent 20

   This works both in CI (paths point at the checked-out repo / uploaded
   artifacts) and locally on a developer machine investigating a failure -
   only --video-dir needs overriding if the video isn't at the path baked
   into the config (e.g. not on a CI runner).

2. Direct / low-level - pass the three file paths explicitly:

    python generate_diff_report.py \
        --gt groundtruth_ov2/samples_TGL/detection_yolov5su_GPU.json \
        --pred /tmp/results/detection_yolov5su_GPU.json \
        --video /tmp/video-examples/Cars.mp4 \
        --output-dir /tmp/diff_report_detection_yolov5su_GPU \
        --top-percent 20

The report (index.html + frames/*.png + summary.json) can then be published
as a CI artifact / attached to a PR or issue comment.
"""
import argparse
import html
import itertools
import json
import os
import platform
import re
import shutil
import string
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

GT_COLOR = (0, 200, 0)      # green (BGR) - groundtruth
PRED_COLOR = (0, 0, 230)    # red (BGR) - predicted


def detect_cpu_info() -> str:
    """Best-effort CPU model string; platform.processor() is often empty on
    Linux, so fall back to parsing /proc/cpuinfo's 'model name'."""
    proc = platform.processor()
    if proc:
        return proc
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


@dataclass
class Box:
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    label: str
    prob: float


@dataclass
class BoxPairDiff:
    label: str
    gt_prob: Optional[float]
    pred_prob: Optional[float]
    iou: float


@dataclass
class FrameDiff:
    timestamp: int  # nanoseconds, as found in the json
    severity: float
    unmatched_gt: int
    unmatched_pred: int
    pairs: List[BoxPairDiff] = field(default_factory=list)
    gt_boxes: List[Box] = field(default_factory=list)
    pred_boxes: List[Box] = field(default_factory=list)


def _read_jsonl(path: str) -> List[dict]:
    frames = []
    with open(path, "r") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                line = line[1:-1]
            if not line:
                continue
            try:
                frames.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return frames


def _object_to_box(obj: dict, frame_width: Optional[float] = None,
                   frame_height: Optional[float] = None) -> Optional[Box]:
    """Extract a drawable pixel-space box + label + confidence from one
    'objects[]' entry of a gvametapublish json line. Mirrors the real
    comparator (gt_comparators/video_gt_comparator.py::_filtered_meta_objects),
    which reads the *normalized* 'detection.bounding_box' /
    'classification.bounding_box' (x_min/y_min/x_max/y_max in [0, 1]) - NOT
    the root-level pixel 'x'/'y'/'w'/'h' fields. Those two can disagree (e.g.
    after any cropping/scaling), so using the wrong one here would make this
    tool blind to differences the real test framework actually flags. Falls
    back to the root pixel box only when there is no nested bounding_box
    (e.g. some classification-only full-frame entries)."""
    label, prob, bbox = "?", -1, None
    if "detection" in obj:
        det = obj["detection"]
        label = det.get("label") or str(det.get("label_id", "?"))
        prob = det.get("confidence", -1)
        bbox = det.get("bounding_box")
    elif "classification" in obj:
        cls = obj["classification"]
        label = cls.get("label") or str(cls.get("label_id", "?"))
        prob = cls.get("confidence", -1)
        bbox = cls.get("bounding_box")

    if bbox and frame_width and frame_height:
        xmin = bbox.get("x_min", 0) * frame_width
        ymin = bbox.get("y_min", 0) * frame_height
        xmax = bbox.get("x_max", 0) * frame_width
        ymax = bbox.get("y_max", 0) * frame_height
        return Box(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, label=label, prob=prob)

    x, y, w, h = obj.get("x"), obj.get("y"), obj.get("w"), obj.get("h")
    if x is None or y is None or w is None or h is None:
        return None
    return Box(xmin=x, ymin=y, xmax=x + w, ymax=y + h, label=label, prob=prob)


def load_frames(path: str) -> Dict[int, List[Box]]:
    result: Dict[int, List[Box]] = {}
    for frame in _read_jsonl(path):
        if "timestamp" not in frame:
            continue
        resolution = frame.get("resolution", {})
        frame_width, frame_height = resolution.get("width"), resolution.get("height")
        boxes = [b for b in (_object_to_box(o, frame_width, frame_height) for o in frame.get("objects", []))
                if b is not None]
        result[frame["timestamp"]] = boxes
    return result


def _iou(a: Box, b: Box) -> float:
    ixmin, iymin = max(a.xmin, b.xmin), max(a.ymin, b.ymin)
    ixmax, iymax = min(a.xmax, b.xmax), min(a.ymax, b.ymax)
    iw, ih = max(0.0, ixmax - ixmin), max(0.0, iymax - iymin)
    inter = iw * ih
    area_a = max(0.0, a.xmax - a.xmin) * max(0.0, a.ymax - a.ymin)
    area_b = max(0.0, b.xmax - b.xmin) * max(0.0, b.ymax - b.ymin)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _match_boxes(gt_boxes: List[Box], pred_boxes: List[Box]) -> Tuple[List[BoxPairDiff], int, int]:
    """Greedy best-IoU matching, restricted to same label, mirroring the
    approach used by the real ObjectDetectionComparator."""
    pairs: List[BoxPairDiff] = []
    gt_remaining = list(gt_boxes)
    pred_remaining = list(pred_boxes)

    labels = {b.label for b in gt_boxes} | {b.label for b in pred_boxes}
    for label in labels:
        gt_of_label = [b for b in gt_remaining if b.label == label]
        pred_of_label = [b for b in pred_remaining if b.label == label]
        n_pairs = min(len(gt_of_label), len(pred_of_label))
        for _ in range(n_pairs):
            best = max(
                ((g, p, _iou(g, p)) for g in gt_of_label for p in pred_of_label),
                key=lambda t: t[2],
                default=None,
            )
            if best is None:
                break
            g, p, iou_val = best
            pairs.append(BoxPairDiff(label=label, gt_prob=g.prob, pred_prob=p.prob, iou=iou_val))
            gt_of_label.remove(g)
            pred_of_label.remove(p)
            gt_remaining.remove(g)
            pred_remaining.remove(p)

    return pairs, len(gt_remaining), len(pred_remaining)


def compute_frame_diffs(gt: Dict[int, List[Box]], pred: Dict[int, List[Box]],
                         iou_weight: float = 1.0, prob_weight: float = 0.5,
                         missing_weight: float = 1.5) -> List[FrameDiff]:
    diffs = []
    all_ts = sorted(set(gt.keys()) | set(pred.keys()))
    for ts in all_ts:
        gt_boxes = gt.get(ts, [])
        pred_boxes = pred.get(ts, [])
        pairs, unmatched_gt, unmatched_pred = _match_boxes(gt_boxes, pred_boxes)

        severity = missing_weight * (unmatched_gt + unmatched_pred)
        for pair in pairs:
            severity += iou_weight * (1.0 - pair.iou)
            if pair.gt_prob is not None and pair.pred_prob is not None and pair.gt_prob >= 0 and pair.pred_prob >= 0:
                severity += prob_weight * abs(pair.gt_prob - pair.pred_prob)

        diffs.append(FrameDiff(
            timestamp=ts,
            severity=severity,
            unmatched_gt=unmatched_gt,
            unmatched_pred=unmatched_pred,
            pairs=pairs,
            gt_boxes=gt_boxes,
            pred_boxes=pred_boxes,
        ))
    return diffs


def _draw_boxes(frame: np.ndarray, boxes: List[Box], color: Tuple[int, int, int], label_at_top: bool):
    for box in boxes:
        p1 = (int(box.xmin), int(box.ymin))
        p2 = (int(box.xmax), int(box.ymax))
        cv2.rectangle(frame, p1, p2, color, 2)
        text = f"{box.label} {box.prob:.2f}" if box.prob is not None and box.prob >= 0 else str(box.label)
        ty = p1[1] - 6 if label_at_top else min(p2[1] + 16, frame.shape[0] - 4)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (p1[0], ty - th - 2), (p1[0] + tw + 2, ty + 2), color, -1)
        cv2.putText(frame, text, (p1[0] + 1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


def _draw_legend(frame: np.ndarray):
    """Burns a small 'GT' / 'Predicted' color legend into the top-left corner
    of the frame, so the image is self-explanatory even without the HTML
    report around it (e.g. when shared standalone)."""
    entries = [("GT", GT_COLOR), ("Predicted", PRED_COLOR)]
    pad, swatch, line_h = 6, 14, 20
    text_w = max(cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0] for text, _ in entries)
    box_w = pad * 3 + swatch + text_w
    box_h = pad * 2 + line_h * len(entries)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (box_w, box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    for i, (text, color) in enumerate(entries):
        y = pad + i * line_h
        cv2.rectangle(frame, (pad, y), (pad + swatch, y + swatch), color, -1)
        cv2.putText(frame, text, (pad * 2 + swatch, y + swatch - 2),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


def render_frame(video_path: str, timestamp_ns: int, gt_boxes: List[Box], pred_boxes: List[Box],
                  out_path: str, fps_hint: Optional[float] = None) -> bool:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False
    ts_ms = timestamp_ns / 1e6
    cap.set(cv2.CAP_PROP_POS_MSEC, ts_ms)
    ok, frame = cap.read()
    if not ok:
        # Fallback: seek by frame index using the container's own fps
        fps = fps_hint or cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_idx = int(round((ts_ms / 1000.0) * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return False

    _draw_boxes(frame, gt_boxes, GT_COLOR, label_at_top=True)
    _draw_boxes(frame, pred_boxes, PRED_COLOR, label_at_top=False)
    _draw_legend(frame)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, frame)
    return True


def _pairs_table_html(diff: FrameDiff) -> str:
    if not diff.pairs and not diff.unmatched_gt and not diff.unmatched_pred:
        return "<p><em>No differences for this frame.</em></p>"
    rows = []
    for pair in diff.pairs:
        gt_p = f"{pair.gt_prob:.3f}" if pair.gt_prob is not None else "-"
        pred_p = f"{pair.pred_prob:.3f}" if pair.pred_prob is not None else "-"
        rows.append(
            f"<tr><td>{html.escape(str(pair.label))}</td><td>{gt_p}</td>"
            f"<td>{pred_p}</td><td>{pair.iou:.3f}</td></tr>"
        )
    extra = ""
    if diff.unmatched_gt:
        extra += f"<p>{diff.unmatched_gt} GT box(es) with no matching prediction (missed detection).</p>"
    if diff.unmatched_pred:
        extra += f"<p>{diff.unmatched_pred} predicted box(es) with no matching GT (false positive).</p>"
    table = (
        "<table><tr><th>label</th><th>GT conf</th><th>pred conf</th><th>IoU</th></tr>"
        + "".join(rows) + "</table>"
    ) if rows else ""
    return table + extra


REPORT_CSS = """
body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 24px; background:#fafafa; }
h1 { font-size: 20px; }
.summary { background:#fff; border:1px solid #ddd; border-radius:6px; padding:12px 16px; margin-bottom:20px; }
.frame-card { background:#fff; border:1px solid #ddd; border-radius:6px; padding:16px; margin-bottom:20px; }
.frame-card img { max-width: 100%; border:1px solid #ccc; }
.legend span { display:inline-block; width:12px; height:12px; margin-right:6px; vertical-align:middle; }
table { border-collapse: collapse; margin-top: 8px; }
td, th { border:1px solid #ccc; padding:4px 8px; font-size: 13px; }
.severity { font-weight:bold; color:#b33; }
"""


def build_html_report(diffs: List[FrameDiff], rendered: Dict[int, str], output_dir: str,
                       gt_path: str, pred_path: str, video_path: str, top_percent: float,
                       gt_update_proposal_path: Optional[str] = None,
                       report_metadata: Optional[Dict[str, str]] = None) -> str:
    rendered_diffs = [d for d in diffs if d.timestamp in rendered]
    rendered_diffs.sort(key=lambda d: d.severity, reverse=True)

    total_frames = len(diffs)
    diffing_frames = len([d for d in diffs if d.severity > 0])

    metadata_rows = "".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in (report_metadata or {}).items() if value
    )
    metadata_block = f'<table class="metadata">{metadata_rows}</table>' if metadata_rows else ""

    cards = []
    for d in rendered_diffs:
        img_rel = os.path.relpath(rendered[d.timestamp], output_dir)
        cards.append(f"""
        <div class="frame-card">
          <h3>timestamp = {d.timestamp} ns ({d.timestamp / 1e6:.1f} ms)
              &nbsp;<span class="severity">severity={d.severity:.3f}</span></h3>
          <img src="{html.escape(img_rel)}"/>
          {_pairs_table_html(d)}
        </div>
        """)

    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>GT diff report</title><style>{REPORT_CSS}</style></head>
<body>
<h1>Groundtruth vs. predicted - visual diff report</h1>
<div class="summary">
  {metadata_block}
  <p><b>GT file:</b> {html.escape(gt_path)}<br/>
     <b>Predicted file:</b> {html.escape(pred_path)}<br/>
     <b>Video:</b> {html.escape(video_path)}</p>
  <p><b>Total compared frames:</b> {total_frames}, <b>frames with any diff:</b> {diffing_frames},
     <b>rendered (top {top_percent:.0f}% of diffing frames):</b> {len(rendered_diffs)}</p>
  {f'<p><b>Groundtruth update proposal:</b> <a href="{html.escape(os.path.relpath(gt_update_proposal_path, output_dir))}">{html.escape(os.path.relpath(gt_update_proposal_path, output_dir))}</a> (copy of the predicted file, drop-in replacement for the current GT if this diff turns out to be an intentional/cosmetic change)</p>' if gt_update_proposal_path else ''}
  <p class="legend"><span style="background:rgb(0,200,0)"></span>GT box
     &nbsp;&nbsp;<span style="background:rgb(230,0,0)"></span>Predicted box</p>
</div>
{''.join(cards)}
</body></html>
"""
    report_path = os.path.join(output_dir, "index.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(body)
    return report_path


def write_summary_json(diffs: List[FrameDiff], output_dir: str) -> str:
    summary = [
        {
            "timestamp": d.timestamp,
            "severity": d.severity,
            "unmatched_gt": d.unmatched_gt,
            "unmatched_pred": d.unmatched_pred,
            "pairs": [
                {"label": p.label, "gt_prob": p.gt_prob, "pred_prob": p.pred_prob, "iou": p.iou}
                for p in d.pairs
            ],
        }
        for d in sorted(diffs, key=lambda d: d.severity, reverse=True)
    ]
    path = os.path.join(output_dir, "summary.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    return path


def write_gt_update_proposal(gt_path: str, pred_path: str, output_dir: str) -> str:
    # Mirrors the groundtruth's own category subfolder (e.g. samples_ARL,
    # aliveness_ARL) so a reviewer can drop the file straight into repo's
    # groundtruth_ov2/<category>/ if it looks right.
    category = os.path.basename(os.path.dirname(gt_path)) or "misc"
    dest_dir = os.path.join(output_dir, "gt_update_proposal", category)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, os.path.basename(gt_path))
    shutil.copyfile(pred_path, dest_path)
    return dest_path


# ----------------------------------------------------------------------------
# Generic resolution of (gt_path, pred_path, video_path) from an existing
# functional_tests test-suite config (e.g. pipeline_test/configs_ov2/common/
# samples.json), by test name. This intentionally re-implements the two small,
# dependency-free building blocks used by regression_test/case_parser.py and
# regression_test/case_generator.py (case matrix expansion + '{dotted.key}'
# template substitution) instead of importing that package, so this tool
# stays fully standalone and usable outside of the test runner / CI.
# ----------------------------------------------------------------------------
GT_FILE_NAME_FIELD = "dataset.groundtruth"
GT_FILE_NAME_TEMPLATE_FIELD = "dataset.groundtruth.template"
VIDEO_DIR_FIELD = "dataset.video"
TEST_TYPE_FIELD = "test.type"
TEMPLATE_FIELD_BY_TYPE = {
    "sample": "sample.command",
    "pipeline": "pipeline.template",
    "benchmark_performance": "benchmark_performance.command",
}
# Config keys that may come in docker.<key> / host.<key> variants (mirrors
# ENVIRONMENT_SPECIFIC_KEYS in regression_test/config_keys.py).
ENV_SPECIFIC_KEYS = [
    "sample.dir",
    "dataset.groundtruth.base",
    "cpp_samples_output.dir",
    "pipeline.params.gvapython.callback_module.detection_ssd_postproc",
    "pipeline.params.gvapython.callback_module.classification_age_gender_postproc",
]


class _CaseGenerator:
    """Verbatim port of regression_test/case_generator.py::CaseGenerator.
    Supports both shapes seen in real configs:
      - a plain dict of key -> value (or key -> [value, ...] for a matrix axis)
      - a list of [key, val] pairs, where key/val may themselves be lists to
        express grouped/coupled fields (e.g. samples_config.json-style and
        regression.json-style test_sets entries).
    Only depends on itertools/functools/operator (stdlib), so this stays
    fully standalone."""

    @staticmethod
    def get_keys_and_values(container):
        if isinstance(container, dict):
            return container.keys(), [val if isinstance(val, list) else [val] for val in container.values()]

        def _remove_duplicates(values):
            values.sort()
            return [val for val, _ in itertools.groupby(values)]

        keys = set()
        result_keys = []
        result_values = []
        for (key, val) in container[::-1]:
            if not isinstance(key, list):
                key = [key]
                if not isinstance(val, list):
                    val = [val]
                val = [[v] for v in val]
            selection = []
            for i, k in enumerate(key):
                if k not in keys:
                    selection.append(i)
                keys.add(k)
            if selection:
                result_keys.append([key[i] for i in selection])
                result_values.append(_remove_duplicates([[v[i] for i in selection] for v in val]))
        return result_keys[::-1], result_values[::-1]

    @staticmethod
    def flatten(container):
        res = []
        for (key, val) in container:
            if isinstance(key, tuple) or isinstance(key, list):
                for elem in zip(key, val):
                    res.append(elem)
            else:
                res.append((key, val))
        return res

    @staticmethod
    def generate(test_set_descriptor):
        keys, values = _CaseGenerator.get_keys_and_values(test_set_descriptor)
        for element in itertools.product(*values):
            yield dict(_CaseGenerator.flatten(zip(keys, element)))


class _SafeDict(dict):
    """Dict that leaves unknown '{missing.key}' placeholders untouched instead
    of raising KeyError, so we don't need to fully replicate every optional
    config key just to resolve the two fields we actually care about."""

    def __missing__(self, key):
        return "{" + key + "}"


class _DotNameFormatter(string.Formatter):
    """Mirrors regression_test/case_parser.py::DotNameFormatter - treats a
    dotted field name like 'dataset.video' as one flat dict key instead of
    doing attribute/index traversal."""

    def get_field(self, field_name, args, kwargs):
        return self.get_value(field_name, args, kwargs), field_name


def _resolve_env_specific_keys(data: dict, env_context: str):
    other_context = "docker" if env_context == "host" else "host"
    for key in ENV_SPECIFIC_KEYS:
        if key in data:
            continue
        if f"{env_context}.{key}" in data:
            data[key] = data[f"{env_context}.{key}"]
        elif f"{other_context}.{key}" in data:
            data[key] = data[f"{other_context}.{key}"]


def _find_test_case(config_path: str, test_name: str, env_context: str, video_dir: Optional[str]) -> dict:
    with open(config_path, "r") as f:
        test_suite = json.load(f)
    test_sets = test_suite.get("test_sets")
    if not isinstance(test_sets, dict):
        raise ValueError(f"'{config_path}' has no top-level 'test_sets' dictionary")
    global_props = dict(test_suite.get("test_set_properties", {}))

    for test_set in test_sets.values():
        if not isinstance(test_set, (dict, list)):
            continue
        for generated in _CaseGenerator.generate(test_set):
            merged = {**global_props, **generated}
            if merged.get("name") != test_name:
                continue
            _resolve_env_specific_keys(merged, env_context)
            if video_dir:
                merged[VIDEO_DIR_FIELD] = video_dir
            return merged
    raise KeyError(f"Test case '{test_name}' not found in '{config_path}'")


def resolve_test_paths(config_path: str, test_name: str, gt_dir: str, pred_dir: str,
                       env_context: str = "host", video_dir: Optional[str] = None) -> Tuple[str, str, str]:
    """Resolves (gt_path, pred_path, video_path) for `test_name` as defined in
    `config_path` (a functional_tests test-suite config, e.g.
    pipeline_test/configs_ov2/common/samples.json), without running any of
    the actual test-runner machinery (no model/label/proc resolution needed
    for this)."""
    merged = _find_test_case(config_path, test_name, env_context, video_dir)
    safe = _SafeDict(merged)
    formatter = _DotNameFormatter()

    gt_template = merged.get(GT_FILE_NAME_TEMPLATE_FIELD)
    gt_filename = formatter.vformat(gt_template, [], safe) if gt_template else merged.get(GT_FILE_NAME_FIELD)
    if not gt_filename:
        raise KeyError(f"Test case '{test_name}' does not define '{GT_FILE_NAME_FIELD}'")

    test_type = merged.get(TEST_TYPE_FIELD, "pipeline")
    template_field = TEMPLATE_FIELD_BY_TYPE.get(test_type)
    if not template_field or template_field not in merged:
        raise KeyError(f"Test case '{test_name}' (test.type={test_type!r}) has no '{template_field}' "
                       f"field to resolve the source video from")
    raw_template = merged[template_field]

    # Anchor on the literal '{dataset.video}/<filename>' placeholder in the
    # *unresolved* template rather than regex-matching a file extension out of
    # the fully-formatted command. The latter breaks for templates like
    # GStreamer's 'filesrc location={dataset.video}/foo.mp4' where there is no
    # whitespace/comma separating an option name from the path, so a plain
    # extension-based scan would incorrectly capture 'location=/tmp/.../foo.mp4'.
    video_dir_value = merged.get(VIDEO_DIR_FIELD)
    if not video_dir_value:
        raise KeyError(f"Test case '{test_name}' does not define '{VIDEO_DIR_FIELD}'")
    placeholder = "{" + VIDEO_DIR_FIELD + "}/"
    anchor = raw_template.find(placeholder)
    if anchor == -1:
        raise ValueError(f"Test case '{test_name}': template field '{template_field}' does not "
                         f"reference '{placeholder}' - cannot locate the source video path:\n{raw_template}")
    remainder = raw_template[anchor + len(placeholder):]

    # What follows '{dataset.video}/' is either another placeholder (e.g.
    # regression.json-style '{dataset.video}/{dataset.video.name}') or a
    # literal filename (e.g. samples.json-style '{dataset.video}/foo.mp4').
    nested_field_match = re.match(r"\{([^{}]+)\}", remainder)
    if nested_field_match:
        field_name = nested_field_match.group(1)
        filename = merged.get(field_name)
        if not filename:
            raise KeyError(f"Test case '{test_name}': template field '{template_field}' references "
                           f"'{{{field_name}}}' after '{placeholder}', but '{field_name}' is not "
                           f"defined for this test case")
    else:
        literal_match = re.match(r"[^\s,\{\}\"']+", remainder)
        if not literal_match:
            raise ValueError(f"Test case '{test_name}': could not extract a filename right after "
                             f"'{placeholder}' in template field '{template_field}':\n{raw_template}")
        filename = literal_match.group(0)
    video_path = f"{video_dir_value}/{filename}"

    return (
        os.path.join(gt_dir, gt_filename),
        os.path.join(pred_dir, gt_filename),
        video_path,
    )


def generate_report(gt_path: str, pred_path: str, video_path: str, output_dir: str,
                     top_percent: float = 20.0, max_frames: Optional[int] = None,
                     dls_branch: Optional[str] = None, dls_commit: Optional[str] = None,
                     test_repo_branch: Optional[str] = None) -> str:
    gt = load_frames(gt_path)
    pred = load_frames(pred_path)
    diffs = compute_frame_diffs(gt, pred)

    diffing = sorted((d for d in diffs if d.severity > 0), key=lambda d: d.severity, reverse=True)
    n_to_render = max(1, int(round(len(diffing) * top_percent / 100.0))) if diffing else 0
    if max_frames is not None:
        n_to_render = min(n_to_render, max_frames)
    selected = diffing[:n_to_render]

    os.makedirs(output_dir, exist_ok=True)
    rendered: Dict[int, str] = {}
    for d in selected:
        out_path = os.path.join(output_dir, "frames", f"frame_{d.timestamp}.png")
        if render_frame(video_path, d.timestamp, d.gt_boxes, d.pred_boxes, out_path):
            rendered[d.timestamp] = out_path

    write_summary_json(diffs, output_dir)
    gt_update_proposal_path = write_gt_update_proposal(gt_path, pred_path, output_dir)
    report_metadata = {
        "Generated at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "CPU": detect_cpu_info(),
        "DLS repo branch": dls_branch,
        "DLS test repo branch": test_repo_branch,
        "DLS commit ID": dls_commit,
    }
    return build_html_report(diffs, rendered, output_dir, gt_path, pred_path, video_path, top_percent,
                             gt_update_proposal_path, report_metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    generic = parser.add_argument_group(
        "generic mode (resolve everything from an existing test-suite config, by test name)")
    generic.add_argument("--config", help="Path to the test-suite config json "
                                          "(e.g. pipeline_test/configs_ov2/common/samples.json)")
    generic.add_argument("--test-name", help="Name of the test case as defined in --config")
    generic.add_argument("--gt-dir", help="Directory containing groundtruth json files "
                                          "(e.g. pipeline_test/groundtruth_ov2/samples_TGL)")
    generic.add_argument("--pred-dir", help="Directory containing predicted (test output) json files "
                                            "(e.g. the test run's results/metadata folder)")
    generic.add_argument("--video-dir", default=None,
                         help="Override the video root directory baked into the config "
                              "(config's 'dataset.video' is normally an absolute CI path "
                              "like /tmp/video-examples; override this when running locally)")
    generic.add_argument("--env-context", choices=["host", "docker"], default="host",
                         help="Which docker.*/host.* config key variant to prefer (default: host)")

    direct = parser.add_argument_group("direct mode (pass the three file paths explicitly)")
    direct.add_argument("--gt", help="Path to groundtruth json-lines file")
    direct.add_argument("--pred", help="Path to predicted (test output) json-lines file")
    direct.add_argument("--video", help="Path to the source input video")

    parser.add_argument("--output-dir", required=True, help="Directory to write the HTML report into")
    parser.add_argument("--top-percent", type=float, default=20.0,
                        help="Percent of the most divergent frames to render (default: 20)")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="Optional hard cap on number of rendered frames")

    metadata = parser.add_argument_group("report metadata (optional, shown in the HTML report header)")
    metadata.add_argument("--dls-branch", help="dlstreamer repo branch/ref the build was run from")
    metadata.add_argument("--dls-commit", help="dlstreamer repo commit SHA the build was run from")
    metadata.add_argument("--test-repo-branch", help="dl-streamer-tests repo branch used for this run")
    args = parser.parse_args()

    if args.config or args.test_name or args.gt_dir or args.pred_dir:
        missing = [name for name, val in [("--config", args.config), ("--test-name", args.test_name),
                                          ("--gt-dir", args.gt_dir), ("--pred-dir", args.pred_dir)] if not val]
        if missing:
            parser.error(f"Generic mode requires all of --config/--test-name/--gt-dir/--pred-dir "
                        f"(missing: {', '.join(missing)})")
        try:
            gt_path, pred_path, video_path = resolve_test_paths(
                args.config, args.test_name, args.gt_dir, args.pred_dir,
                env_context=args.env_context, video_dir=args.video_dir)
        except KeyError as err:
            # Expected/normal when a caller (e.g. a CI step) probes multiple
            # *_final.json configs looking for the one that defines this test
            # case - print a short message instead of a full traceback and
            # use a distinct exit code so it's clearly "not in this config",
            # not a real bug.
            print(f"Test not found in this config: {err}", file=sys.stderr)
            sys.exit(2)
        print(f"Resolved from config: gt={gt_path} pred={pred_path} video={video_path}")
    elif args.gt or args.pred or args.video:
        missing = [name for name, val in [("--gt", args.gt), ("--pred", args.pred), ("--video", args.video)] if not val]
        if missing:
            parser.error(f"Direct mode requires all of --gt/--pred/--video (missing: {', '.join(missing)})")
        gt_path, pred_path, video_path = args.gt, args.pred, args.video
    else:
        parser.error("Provide either --config/--test-name/--gt-dir/--pred-dir (generic mode) "
                    "or --gt/--pred/--video (direct mode)")

    try:
        report_path = generate_report(gt_path, pred_path, video_path, args.output_dir,
                                      top_percent=args.top_percent, max_frames=args.max_frames,
                                      dls_branch=args.dls_branch, dls_commit=args.dls_commit,
                                      test_repo_branch=args.test_repo_branch)
    except Exception as err:
        print(f"Failed to generate diff report: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(1)

    # Written so downstream tooling (e.g. ai_verdict.py / propose_gt_update.py)
    # can reuse the exact resolved paths instead of re-deriving them.
    with open(os.path.join(args.output_dir, "paths.json"), "w") as f:
        json.dump({"gt_path": gt_path, "pred_path": pred_path, "video_path": video_path}, f, indent=2)

    print(f"Report generated: {report_path}")


if __name__ == "__main__":
    main()
