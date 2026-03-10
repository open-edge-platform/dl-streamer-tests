# ==============================================================================
# Copyright (C) 2025-2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
import glob
import os
import logging
import shutil

import cv2
import numpy as np

from gt_comparators.base_gt_comparator import BaseGTComparator
from gt_comparators.base_gt_comparator import RuntimeTestCase
from pipeline_test.regression_test.config_keys import *


PIXEL_THRESHOLD_DEFAULT = 2
BAD_PIXEL_FRACTION_DEFAULT = 0.001


class PngFrameComparator(BaseGTComparator):
    """Compares rendered watermark frames (PNG) against GT PNG frames stored per test case.

    Each test case has its own GT subdirectory named after the test (e.g.
    ``groundtruth_ov2/watermark_TGL/watermark_keypoints_ff_BGRA_sysmem_gvawatermark/``).
    The pipeline writes output frames directly as PNG via ``multifilesink``.

    Two configurable thresholds control pass/fail per frame:
    - ``dataset.pixel_threshold``    – max per-pixel difference (across BGR channels) that is
                                       still considered acceptable (default: 2).
    - ``dataset.bad_pixel_fraction`` – max fraction of pixels that may exceed the pixel
                                       threshold before the frame is marked as failed
                                       (default: 0.001, i.e. 0.1 %).

    On failure a 10× amplified diff image is saved next to the test frames.
    """

    def __init__(self, test_case: RuntimeTestCase, logger: logging.Logger = None):
        super().__init__(test_case, logger if logger else logging.getLogger())

    # ------------------------------------------------------------------
    # Path initialisation
    # ------------------------------------------------------------------

    def _init_gt_path(self):
        gt_folder = self._test_case.input[GT_BASE_FOLDER_FIELD]
        gt_dir_name = self._test_case.input[GT_FILE_NAME_FIELD]
        gt_path = os.path.join(gt_folder, self._test_case.gt_specific, gt_dir_name)
        if not os.path.exists(gt_path):
            gt_path = os.path.join(gt_folder, gt_dir_name)
            if not os.path.exists(gt_path):
                raise FileNotFoundError("GT directory not found: {}".format(gt_path))
        self._gt_path = gt_path

    def _init_prediction_path(self):
        out_frames_dir = self._test_case.input[OUT_FRAMES_DIR]
        pred_dir = os.path.join(self._test_case.input[ARTIFACTS_PATH_FIELD], out_frames_dir)
        if os.path.exists(pred_dir):
            shutil.rmtree(pred_dir)
            self._logger.debug("Removed old frames directory: {}".format(pred_dir))
        os.makedirs(pred_dir)
        self._pred_path = pred_dir

    # ------------------------------------------------------------------
    # Pipeline post-processing
    # ------------------------------------------------------------------

    def pipeline_results_processing(self):
        """Frames are already written as PNGs by multifilesink — nothing to convert."""
        return self._pred_path

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def _compare_internal(self, gt_dir: str, prediction_dir: str):
        if not os.path.isdir(gt_dir) or not os.path.isdir(prediction_dir):
            raise FileNotFoundError(
                "GT or prediction directory not found:\n  GT:   {}\n  test: {}".format(
                    gt_dir, prediction_dir))

        gt_frames = sorted(glob.glob(os.path.join(gt_dir, "frame_*.png")))
        pred_frames = sorted(glob.glob(os.path.join(prediction_dir, "frame_*.png")))

        if len(gt_frames) != len(pred_frames):
            self._test_case.result.add_error(
                "Frame count mismatch: GT={}, test={}".format(len(gt_frames), len(pred_frames)))
            return

        pixel_threshold = self._test_case.input.get("dataset.pixel_threshold", PIXEL_THRESHOLD_DEFAULT)
        bad_pixel_fraction = self._test_case.input.get("dataset.bad_pixel_fraction", BAD_PIXEL_FRACTION_DEFAULT)

        for idx, (gt_path, pred_path) in enumerate(zip(gt_frames, pred_frames)):
            gt_frame = cv2.imread(gt_path)
            pred_frame = cv2.imread(pred_path)

            if gt_frame is None or pred_frame is None:
                self._test_case.result.add_error("Frame {:05d}: could not read PNG".format(idx))
                continue

            if gt_frame.shape != pred_frame.shape:
                self._test_case.result.add_error(
                    "Frame {:05d}: shape mismatch GT={} test={}".format(
                        idx, gt_frame.shape, pred_frame.shape))
                continue

            diff = np.abs(gt_frame.astype(np.int16) - pred_frame.astype(np.int16))
            per_pixel_max_diff = diff.max(axis=2)   # max diff across BGR channels → (H, W)
            bad_pixels = int((per_pixel_max_diff > pixel_threshold).sum())
            total_pixels = gt_frame.shape[0] * gt_frame.shape[1]
            fraction = bad_pixels / total_pixels

            self._logger.debug(
                "Frame {:05d}: bad_pixels={}/{} ({:.4%}), max_diff={}".format(
                    idx, bad_pixels, total_pixels, fraction, int(per_pixel_max_diff.max())))

            if fraction > bad_pixel_fraction:
                self._test_case.result.add_error(
                    "Frame {:05d}: bad_pixels={}/{} ({:.4%}) > threshold ({:.4%}), "
                    "max_diff={}".format(
                        idx, bad_pixels, total_pixels, fraction, bad_pixel_fraction,
                        int(per_pixel_max_diff.max())))
                diff_vis = np.clip(diff * 10, 0, 255).astype(np.uint8)
                diff_path = os.path.join(prediction_dir, "DIFF_frame_{:05d}.png".format(idx))
                cv2.imwrite(diff_path, diff_vis)
                self._logger.info("Diff image saved: {}".format(diff_path))
