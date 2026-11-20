# ==============================================================================
# Copyright (C) 2025 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
import logging
from config_keys import *
from video_gt_comparator import VideoCompareStats
from base_gt_comparator import BaseGTComparator, RuntimeTestCase, CaseResultInfo, TestType, extract_gt_path_from_pipeline_cmd


DEFAUL_FPS_PASS_PERCENTAGE = 100


class BenchmarkComparator(BaseGTComparator):
    def __init__(self, test_case: RuntimeTestCase, logger: logging.Logger = None):
        super().__init__(test_case, logger if logger else logging.getLogger())
        self._logger = logger if logger else logging.getLogger()
        self._test_case = test_case

    def _init_prediction_path(self):
        pipeline_cmd = self._test_case.input.get(PIPELINE_CMD_FIELD)
        # Stream density tests have no pipeline.cmd - skip inference output collection
        if not pipeline_cmd or 'gvametapublish' not in pipeline_cmd:
            self._pred_path = None
            self._logger.info("No gvametapublish element found in pipeline - inference statistics will not be collected")
            return
        self._pred_path = extract_gt_path_from_pipeline_cmd(pipeline_cmd)
        super()._prepare_prediction_folder()

    def _init_gt_path(self):
        self._gt_path = "" # No GT file for benchmarking performance tests

    def _get_target_fps(self):
        return round(float(self._test_case.input[BENCHMARK_PERFORMANCE_FPS_FPI]), 1)

    def _get_achieved_fps(self):
        return round(float(self._test_case.result.fps), 1)

    def _get_pass_fps_threshold_percent(self):
        try:
            return int(self._test_case.input[BENCHMARK_PERFORMANCE_FPS_PASS_THRESHOLD])
        except:
            return DEFAUL_FPS_PASS_PERCENTAGE

    def _is_minimum_fps_only(self):
        return str(self._test_case.input.get(BENCHMARK_PERFORMANCE_FPS_MINIMUM_ONLY, "false")).lower() == "true"

    def _get_pass_fps_thresholds(self):
        if self._is_minimum_fps_only():
            return self._get_target_fps(), None
        lower_threshold = round((100 - self._get_pass_fps_threshold_percent()) / 100 * self._get_target_fps(), 1)
        upper_threshold = round((100 + self._get_pass_fps_threshold_percent()) / 100 * self._get_target_fps(), 1)
        return lower_threshold, upper_threshold

    def _is_stream_density_test(self):
        """Check if this is a stream density test"""
        test_type = self._test_case.input.get('test.type', '')
        return test_type == TestType.benchmark_stream_density

    def _get_target_streams(self):
        """Get target number of streams"""
        try:
            return int(self._test_case.input.get(BENCHMARK_STREAM_DENSITY_TARGET_STREAMS, 0))
        except:
            return 0

    def _get_achieved_streams(self):
        """Get achieved number of streams"""
        try:
            # runner saves result as max_stream_density
            achieved = getattr(self._test_case.result, 'max_stream_density',
                               getattr(self._test_case.result, 'achieved_streams', None))
            return int(achieved) if achieved is not None else 0
        except:
            return 0

    def _save_stream_density_results(self):
        """Save stream density results"""
        self._test_case.result.streams_target = self._get_target_streams()
        self._test_case.result.streams_achieved = self._get_achieved_streams()

    def _compare_stream_density(self):
        """Compare stream density results"""
        achieved_streams = self._get_achieved_streams()
        target_streams = self._get_target_streams()

        self._logger.info("Stream density benchmark results:")
        self._logger.info(f"\t- achieved streams: {achieved_streams}")
        self._logger.info(f"\t- target streams (KPI): {target_streams}")

        if achieved_streams < target_streams:
            self._test_case.result.add_error(
                f"Stream density KPI NOT met: achieved {achieved_streams} streams, required {target_streams} streams"
            )
        else:
            self._logger.info(f"\t- KPI PASSED: {achieved_streams} >= {target_streams} streams")

        self._save_stream_density_results()

    def _save_fps_results(self):
        self._test_case.result.fps_target = self._get_target_fps()
        self._test_case.result.fps_pass_threshold = 0 if self._is_minimum_fps_only() else self._get_pass_fps_threshold_percent()
        lower_threshold, upper_threshold = self._get_pass_fps_thresholds()
        self._test_case.result.fps_pass_threshold_lower = lower_threshold
        self._test_case.result.fps_pass_threshold_upper = upper_threshold

    def _save_inference_results(self, prediction_path_json: str):
        predicted_frames = super()._extract_data_from_json_file(prediction_path_json)
        num_frames = len(predicted_frames)
        num_objects = 0
        for frame in predicted_frames:
            try:
                objects_in_frame = frame["objects"]
                num_objects += len(objects_in_frame)
            except:
                continue # No objects detected
        stats = VideoCompareStats()
        stats.num_frames_failed = 0
        stats.failed_pairs = {}
        stats.num_frames = num_frames
        stats.num_pairs = num_objects
        self._test_case.result.add_info(CaseResultInfo.VIDEO_STATS, stats)        

    def _compare_internal(self, gt_path_json: str, prediction_path_json: str):
        if self._is_stream_density_test():
            self._compare_stream_density()
        else:
            self._compare_fps_performance()
        
        # Only save inference results if prediction path is available
        if prediction_path_json:
            self._save_inference_results(prediction_path_json)

    def _compare_fps_performance(self):
        """Original FPS comparison code"""
        fps_value = self._get_achieved_fps()
        fps_target_value = self._get_target_fps()
        fps_vs_target_percent = round((fps_value / fps_target_value) * 100, 1)
        pass_threshold_percent = self._get_pass_fps_threshold_percent()
        lower_threshold, upper_threshold = self._get_pass_fps_thresholds()
        
        self._logger.info("Test performance benchmark results:")
        self._logger.info("\t- achieved FPS: {} FPS".format(fps_value))
        self._logger.info("\t- target KPI: {} FPS".format(fps_target_value))
        if self._is_minimum_fps_only():
            self._logger.info("\t- pass FPS range: >= {} FPS (no upper limit)".format(lower_threshold))
            if fps_value < lower_threshold:
                self._test_case.result.add_error("Achieved {} FPS which is BELOW minimum KPI of {} FPS"
                                                 .format(fps_value, lower_threshold))
            self._save_fps_results()
            return
        self._logger.info("\t- pass FPS range: +/- {}% of {} FPS KPI: [{} FPS - {} FPS]".format(pass_threshold_percent, fps_target_value, lower_threshold, upper_threshold))

        if fps_value < lower_threshold:
            self._test_case.result.add_error("Achieved {} FPS which is BELOW expectation. Pass range: +/- {}% of {} KPI FPS = [{} FPS - {} FPS]"
                                             .format(fps_value, pass_threshold_percent, fps_target_value, lower_threshold, upper_threshold))
        if fps_value > upper_threshold:
            self._test_case.result.add_error("Achieved {} FPS which is ABOVE expectation. Pass range: +/- {}% of {} KPI FPS = [{} FPS - {} FPS]"
                                             .format(fps_value, pass_threshold_percent, fps_target_value, lower_threshold, upper_threshold))

        self._save_fps_results()
