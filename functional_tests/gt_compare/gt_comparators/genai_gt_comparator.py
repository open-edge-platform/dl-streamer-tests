# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
import json
import logging
import os
import re

from tabulate import tabulate

from gt_comparators.base_gt_comparator import BaseGTComparator, RuntimeTestCase

COMPARE_TEXT_FIELD = "dataset.genai.compare_text"
ALLOWED_RESULTS_FIELD = "dataset.genai.allowed_results"
COMPARE_TIMESTAMPS_FIELD = "dataset.genai.compare_timestamps"
CONFIDENCE_THR_FIELD = "dataset.genai.confidence_thr"

DEFAULT_CONFIDENCE_THR = 0.05
ERRORS_TO_REPORT = 10


def normalize_text(text: str) -> str:
    """Return text comparable across runs: lowercase, single spaces, no edge punctuation."""
    normalized = re.sub(r"\s+", " ", str(text)).strip().lower()
    return normalized.strip(" .,;:!?\"'")


class GenAIGTComparator(BaseGTComparator):
    """Compares JSON Lines produced by the gvagenai element.

    Each record holds a generated text ('result'), an optional 'confidence', frame
    timestamps and an optional 'metrics' block. Metrics are performance data and are
    never compared.
    """

    def __init__(self, test_case: RuntimeTestCase, logger: logging.Logger = None):
        super().__init__(test_case, logger if logger else logging.getLogger())
        test_input = self._test_case.input
        self._compare_text = test_input.get(COMPARE_TEXT_FIELD, True)
        self._compare_timestamps = test_input.get(COMPARE_TIMESTAMPS_FIELD, True)
        self._confidence_thr = float(test_input.get(CONFIDENCE_THR_FIELD, DEFAULT_CONFIDENCE_THR))
        allowed_results = test_input.get(ALLOWED_RESULTS_FIELD, [])
        self._allowed_results = [normalize_text(result) for result in allowed_results]

    def _load_json_lines(self, file_path: str) -> list:
        # Unlike the base implementation, every non-empty line is parsed: gvametapublish
        # writes no trailing empty line and VLM pipelines produce few records per run.
        if not os.path.exists(file_path):
            raise FileExistsError("The {} path to json file not found".format(file_path))
        records = []
        with open(file_path, 'r') as json_file:
            for line_number, line in enumerate(json_file, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError("Invalid JSON in {} at line {}: {}".format(
                        file_path, line_number, error)) from error
        return records

    def _check_record_keys(self, records: list, file_path: str) -> bool:
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                self._test_case.result.add_error(
                    "Record {} in {} is not a JSON object".format(index, file_path))
                return False
            if "result" not in record:
                self._test_case.result.add_error(
                    "Record {} in {} has no 'result' key: {}".format(index, file_path, record))
                return False
        return True

    def _compare_record(self, index: int, target: dict, predicted: dict) -> list:
        errors = []
        if self._compare_timestamps:
            for key in ("timestamp", "timestamp_seconds"):
                if key not in target and key not in predicted:
                    continue
                if target.get(key) != predicted.get(key):
                    errors.append([index, key, target.get(key), predicted.get(key)])

        if self._compare_text:
            target_text = normalize_text(target["result"])
            predicted_text = normalize_text(predicted["result"])
            if target_text != predicted_text:
                errors.append([index, "result", target["result"], predicted["result"]])

        if self._confidence_thr:
            target_confidence = target.get("confidence")
            predicted_confidence = predicted.get("confidence")
            if (target_confidence is None) != (predicted_confidence is None):
                errors.append([index, "confidence", target_confidence, predicted_confidence])
            elif target_confidence is not None and \
                    abs(float(target_confidence) - float(predicted_confidence)) > self._confidence_thr:
                errors.append([index, "confidence", target_confidence, predicted_confidence])

        return errors

    def _check_allowed_results(self, records: list) -> list:
        errors = []
        if not self._allowed_results:
            return errors
        for index, record in enumerate(records):
            if normalize_text(record["result"]) not in self._allowed_results:
                errors.append([index, "result not allowed", self._allowed_results, record["result"]])
        return errors

    def _report_errors(self, errors: list):
        rows = errors[:ERRORS_TO_REPORT]
        tail = "\n ...<truncated, {} errors total>".format(len(errors)) \
            if len(errors) > ERRORS_TO_REPORT else ""
        table = tabulate(rows, headers=["record", "field", "groundtruth", "predicted"],
                         tablefmt='orgtbl')
        self._test_case.result.add_error("GenAI results do not match ground truth:\n{}{}".format(
            table, tail))

    def _compare_internal(self, origin_gt_path: str, dumped_gt_path: str):
        target_gt = self._load_json_lines(origin_gt_path)
        test_results = self._load_json_lines(dumped_gt_path)

        if not self._check_record_keys(target_gt, origin_gt_path) or \
                not self._check_record_keys(test_results, dumped_gt_path):
            return

        if not target_gt:
            self._test_case.result.add_error(
                "Ground truth file {} contains no records".format(origin_gt_path))
            return

        if len(target_gt) != len(test_results):
            self._test_case.result.add_error(
                "Number of generated results doesn't match: {} /// {}".format(
                    len(target_gt), len(test_results)))
            return

        errors = self._check_allowed_results(test_results)
        for index, (target, predicted) in enumerate(zip(target_gt, test_results)):
            errors.extend(self._compare_record(index, target, predicted))

        if errors:
            self._report_errors(errors)
