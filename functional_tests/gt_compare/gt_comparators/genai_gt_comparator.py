# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
import json
import logging
import os
import re

from enum import Enum

from tabulate import tabulate

from gt_comparators.base_gt_comparator import BaseGTComparator, RuntimeTestCase

MODE_FIELD = "dataset.genai.mode"
COMPARE_TEXT_FIELD = "dataset.genai.compare_text"
ALLOWED_RESULTS_FIELD = "dataset.genai.allowed_results"
COMPARE_TIMESTAMPS_FIELD = "dataset.genai.compare_timestamps"
CONFIDENCE_THR_FIELD = "dataset.genai.confidence_thr"
MIN_RECORDS_FIELD = "dataset.genai.min_records"
REQUIRED_KEYWORDS_FIELD = "dataset.genai.required_keywords"
MIN_KEYWORD_HITS_FIELD = "dataset.genai.min_keyword_hits"

DEFAULT_CONFIDENCE_THR = 0.05
DEFAULT_MIN_KEYWORD_HITS = 1
ERRORS_TO_REPORT = 10
# Multi-value options are comma-separated strings, never JSON lists: CaseGenerator turns
# every list-valued test case property into a separate test case (a parameter sweep).
LIST_SEPARATOR = ","


class GenAIMode(str, Enum):
    """How a gvagenai prediction is judged against its ground truth."""

    # Match the ground truth record by record: count, text, timestamps, confidence.
    strict = "strict"
    # Ignore the ground truth content and only check that the prediction looks sane.
    smoke = "smoke"

    def __str__(self):
        return self.value


# Options that only have an effect in one of the modes. Used to reject configurations
# that silently do nothing, which would otherwise be easy to misread as active checks.
MODE_SPECIFIC_FIELDS = {
    GenAIMode.strict: (COMPARE_TEXT_FIELD, COMPARE_TIMESTAMPS_FIELD, CONFIDENCE_THR_FIELD),
    GenAIMode.smoke: (MIN_RECORDS_FIELD, REQUIRED_KEYWORDS_FIELD, MIN_KEYWORD_HITS_FIELD),
}


def normalize_text(text: str) -> str:
    """Return text comparable across runs: lowercase, single spaces, no edge punctuation."""
    normalized = re.sub(r"\s+", " ", str(text)).strip().lower()
    return normalized.strip(" .,;:!?\"'")


def parse_text_list(test_input: dict, field: str) -> list:
    """Parse a comma-separated option into a list of normalized, non-empty entries.

    A JSON list must not be used here: CaseGenerator expands every list-valued property
    of a test case into a separate test case, so a list would silently multiply the test
    and hand each copy a single value.
    """
    raw = test_input.get(field, "")
    if isinstance(raw, (list, tuple)):
        raise TypeError(
            "'{}' must be a '{}'-separated string, not a list. List values are expanded by "
            "CaseGenerator into separate test cases instead of being passed through.".format(
                field, LIST_SEPARATOR))
    entries = [normalize_text(entry) for entry in str(raw).split(LIST_SEPARATOR)]
    return [entry for entry in entries if entry]


class GenAIGTComparator(BaseGTComparator):
    """Compares JSON Lines produced by the gvagenai element.

    Each record holds a generated text ('result'), an optional 'confidence', frame
    timestamps and an optional 'metrics' block. Metrics are performance data and are
    never compared.

    Every test must declare 'dataset.genai.mode' explicitly:

    * 'strict' - the prediction must match the ground truth record by record. Use it for
      pipelines whose record count and wording are reproducible. Tuned with
      'compare_text', 'compare_timestamps' and 'confidence_thr'.
    * 'smoke' - the ground truth content is not matched at all; the prediction only has
      to look sane: at least 'min_records' records, no empty generations and at least
      'min_keyword_hits' of 'required_keywords' somewhere in the generated text. Use it
      for pipelines whose record count depends on detection/tracking results and whose
      wording is free-form, where a strict comparison would be flaky by construction.
      The ground truth file must still exist and serves as a reference sample.

    Multi-value options ('allowed_results', 'required_keywords') are comma-separated
    strings. A JSON list must not be used: CaseGenerator expands every list-valued test
    case property into a separate test case, so a list silently multiplies the test and
    passes a single value to each copy.
    """

    def __init__(self, test_case: RuntimeTestCase, logger: logging.Logger = None):
        super().__init__(test_case, logger if logger else logging.getLogger())
        test_input = self._test_case.input
        self._mode = self._parse_mode(test_input)
        self._reject_fields_of_other_mode(test_input)

        self._allowed_results = parse_text_list(test_input, ALLOWED_RESULTS_FIELD)

        if self._mode == GenAIMode.strict:
            self._compare_text = test_input.get(COMPARE_TEXT_FIELD, True)
            self._compare_timestamps = test_input.get(COMPARE_TIMESTAMPS_FIELD, True)
            self._confidence_thr = float(test_input.get(CONFIDENCE_THR_FIELD, DEFAULT_CONFIDENCE_THR))
        else:
            self._min_records = self._parse_min_records(test_input)
            self._required_keywords = parse_text_list(test_input, REQUIRED_KEYWORDS_FIELD)
            self._min_keyword_hits = int(test_input.get(MIN_KEYWORD_HITS_FIELD, DEFAULT_MIN_KEYWORD_HITS))
            if self._min_keyword_hits > len(self._required_keywords):
                raise ValueError(
                    "'{}' is {} but only {} keyword(s) are listed in '{}': the check can never pass".format(
                        MIN_KEYWORD_HITS_FIELD, self._min_keyword_hits,
                        len(self._required_keywords), REQUIRED_KEYWORDS_FIELD))

        self._logger.info("GenAI comparator mode: {}".format(self._mode))

    @staticmethod
    def _parse_mode(test_input: dict) -> GenAIMode:
        if MODE_FIELD not in test_input:
            raise KeyError(
                "The required '{}' key was not found. Every test using the 'genai' comparator must "
                "declare its comparison mode explicitly, one of: {}".format(
                    MODE_FIELD, [str(mode) for mode in GenAIMode]))
        try:
            return GenAIMode(str(test_input[MODE_FIELD]))
        except ValueError:
            raise ValueError("'{}' is not a valid '{}'. Expected one of: {}".format(
                test_input[MODE_FIELD], MODE_FIELD, [str(mode) for mode in GenAIMode])) from None

    @staticmethod
    def _parse_min_records(test_input: dict) -> int:
        if MIN_RECORDS_FIELD not in test_input:
            raise KeyError("The '{}' key is required in '{}' mode: it defines how many records the "
                           "pipeline must generate for the run to count as successful".format(
                               MIN_RECORDS_FIELD, GenAIMode.smoke))
        min_records = int(test_input[MIN_RECORDS_FIELD])
        if min_records < 1:
            raise ValueError("'{}' must be at least 1, got {}".format(MIN_RECORDS_FIELD, min_records))
        return min_records

    def _reject_fields_of_other_mode(self, test_input: dict):
        other_mode = GenAIMode.smoke if self._mode == GenAIMode.strict else GenAIMode.strict
        unexpected = [field for field in MODE_SPECIFIC_FIELDS[other_mode] if field in test_input]
        if unexpected:
            raise KeyError("{} {} only meaningful in '{}' mode, but this test runs in '{}' mode".format(
                unexpected, "is" if len(unexpected) == 1 else "are", other_mode, self._mode))

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

    def _check_empty_results(self, records: list) -> list:
        return [[index, "empty result", "non-empty text", repr(record["result"])]
                for index, record in enumerate(records) if not normalize_text(record["result"])]

    def _check_required_keywords(self, records: list) -> list:
        """Require enough distinct keywords across all generations.

        Guards against a model that runs but produces off-topic or degenerate text,
        which a mere record count check would happily accept.
        """
        if not self._required_keywords:
            return []
        generated_text = " ".join(normalize_text(record["result"]) for record in records)
        matched = sorted({keyword for keyword in self._required_keywords if keyword in generated_text})
        if len(matched) >= self._min_keyword_hits:
            self._logger.info("Matched {}/{} required keywords: {}".format(
                len(matched), self._min_keyword_hits, matched))
            return []
        return [["-", "required keywords",
                 "at least {} of {}".format(self._min_keyword_hits, self._required_keywords),
                 "matched {}".format(matched)]]

    def _compare_smoke(self, records: list):
        """Sanity-check the prediction instead of matching it against the ground truth."""
        if len(records) < self._min_records:
            self._test_case.result.add_error(
                "Too few generated results: expected at least {}, got {}".format(
                    self._min_records, len(records)))
            return

        errors = self._check_empty_results(records)
        errors.extend(self._check_allowed_results(records))
        errors.extend(self._check_required_keywords(records))
        if errors:
            self._report_errors(errors)
            return
        self._logger.info("GenAI smoke check passed: {} records generated".format(len(records)))

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

        if self._mode == GenAIMode.smoke:
            self._compare_smoke(test_results)
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
