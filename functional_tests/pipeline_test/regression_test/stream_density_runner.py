# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================
import subprocess
import time
import logging
import re
import string
import threading
import math
import os
import signal
import numpy as np
from collections import defaultdict
from config_keys import *

logging.basicConfig(level=logging.INFO)

class DotNameFormatter(string.Formatter):
    """Custom formatter that handles dot notation in field names"""
    def get_field(self, field_name, args, kwargs):
        return self.get_value(field_name, args, kwargs), field_name

def parse_fps_from_output(stdout, stderr, stream_count):
    """
    Parse FPS using same method as bash script:
    - Look for FpsCounter lines with per-stream=Y fps (val1, val2, val3, ...)
    - Each value in brackets is FPS for one stream
    - Skip lines where number of values != stream_count
    - Build 2D table [sample][stream]
    - 90th percentile per column (stream)
    - Minimum of all percentiles = guaranteed minimum FPS
    Example log line:
    FpsCounter(last 1sec): total=105.3 fps, number-streams=4, per-stream=26.3 fps (26.1, 27.2, 25.9, 26.0)
    """

    full_output = stdout + "\n" + stderr
    print(f"DEBUG_PRINT: Parsing FPS for {stream_count} streams")

    # Pattern matching bash awk:
    # /^FpsCounter\(last [0-9.]*sec\):.*, number-streams=[0-9].*, per-stream=/ 
    # split(gensub(/^.*, per-stream=[0-9.]* fps \(([0-9., ]*)\)/,"\\1",1),fields,",")
    pattern = (
        r'FpsCounter\(last [\d.]*sec\):'
        r'.*number-streams=(\d+)'
        r'.*per-stream=[\d.]+ fps \(([\d., ]+)\)'
    )

    # 2D table: stream_id -> list of FPS values
    # Same as bash: throughput[i][fps_data_ct] = fields[i]
    stream_fps_table = defaultdict(list)

    for line in full_output.split('\n'):
        match = re.search(pattern, line, re.IGNORECASE)
        if not match:
            continue

        num_streams = int(match.group(1))
        values_str  = match.group(2)

        # Filter: only lines matching our stream count
        # Same as bash: -v ns=$PIPELINE_COUNT
        if num_streams != stream_count:
            print(f"DEBUG_PRINT: Skipping line - streams={num_streams} != {stream_count}")
            continue

        # Parse individual stream values from brackets
        # Same as bash: split(..., fields, ",")
        values = []
        for v in values_str.split(','):
            v = v.strip()
            if v:
                try:
                    values.append(float(v))
                except ValueError:
                    continue

        # Skip if number of values doesn't match stream count
        if len(values) != stream_count:
            print(f"DEBUG_PRINT: Skipping line - got {len(values)} values, expected {stream_count}")
            continue

        # Add to table: throughput[i][fps_data_ct] = fields[i]
        for i, fps in enumerate(values):
            stream_fps_table[i].append(fps)

        print(f"DEBUG_PRINT: Added sample with values: {values}")

    # Validate we have data
    if not stream_fps_table:
        print("DEBUG_PRINT: No valid FPS data found in output")
        return None

    print(f"DEBUG_PRINT: FPS table has {len(stream_fps_table)} streams")

    # Calculate percentile for each stream
    # Same as bash: throughput_p[i]=calc_percentile(throughput[i], throughput_percentile)
    throughput_percentile = 0.90
    percentile_per_stream = {}

    for stream_id, fps_values in stream_fps_table.items():
        if not fps_values:
            continue

        p90 = float(np.percentile(fps_values, throughput_percentile * 100))
        avg = float(np.mean(fps_values))
        std = float(np.std(fps_values, ddof=1)) if len(fps_values) > 1 else 0.0

        percentile_per_stream[stream_id] = p90

        # Same output as bash:
        # print "throughput #"i" p90: "throughput_p[i]" avg: "calc_avg" std: "stdev
        print(f"DEBUG_PRINT: throughput #{stream_id+1} "
              f"p{int(throughput_percentile*100)}: {p90:.2f} "
              f"avg: {avg:.2f} "
              f"std: {std:.2f}")

    if not percentile_per_stream:
        print("DEBUG_PRINT: No percentile data calculated")
        return None

    # Calculate all stats same as bash script
    all_p90_values = list(percentile_per_stream.values())

    throughput_min        = min(all_p90_values)
    throughput_median     = float(np.median(all_p90_values))
    throughput_average    = float(np.mean(all_p90_values))
    throughput_stdev_max  = max(
        float(np.std(stream_fps_table[i], ddof=1)) if len(stream_fps_table[i]) > 1 else 0.0
        for i in stream_fps_table
    )
    throughput_cumulative = sum(all_p90_values)

    # Print same as bash kpi.txt output
    print(f"throughput min: {throughput_min:.2f}")
    print(f"throughput median: {throughput_median:.2f}")
    print(f"throughput average: {throughput_average:.2f}")
    print(f"throughput stdev max: {throughput_stdev_max:.2f}")
    print(f"throughput cumulative: {throughput_cumulative:.2f}")

    # Return min same as bash: grep "throughput min:" kpi.txt
    return throughput_min


class StreamDensityTester:
    """Stream density tester using binary search algorithm"""

    def __init__(self, logger):
        self.logger = logger
        self.test_duration = None
        self.process_hard_timeout = None
        self.target_fps = None
        self.min_fps = None
        self.stdout_buffer = ""
        self.stderr_buffer = ""
        self.test_results = {}  # Cache results: {stream_count: fps}

    def _terminate_process_tree(self, process, stream_count, reason, graceful_timeout=5):
        """Terminate gst-launch process and all children spawned in its session."""
        if process is None or process.poll() is not None:
            return

        pid = process.pid
        self.logger.warning(
            f"Stopping pipeline for {stream_count} streams (pid={pid}): {reason}"
        )

        try:
            os.killpg(pid, signal.SIGTERM)
            process.wait(timeout=graceful_timeout)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            self.logger.warning(
                f"Process group pid={pid} did not stop after SIGTERM, sending SIGKILL"
            )
        except Exception as e:
            self.logger.warning(
                f"Failed to terminate process group pid={pid} with SIGTERM: {e}; trying process.terminate()"
            )
            try:
                process.terminate()
                process.wait(timeout=graceful_timeout)
                return
            except Exception:
                pass

        try:
            os.killpg(pid, signal.SIGKILL)
            process.wait(timeout=graceful_timeout)
        except ProcessLookupError:
            pass
        except Exception as e:
            self.logger.warning(f"Failed to SIGKILL process group pid={pid}: {e}")
            try:
                process.kill()
            except Exception:
                pass

    def read_output_thread(self, pipe, buffer_attr, prefix):
        """Thread function to read output from pipe and display it in real-time"""
        try:
            while True:
                line = pipe.readline()
                if not line:
                    break
                line = line.strip()
                if line:
                    # Add to buffer
                    current_buffer = getattr(self, buffer_attr)
                    setattr(self, buffer_attr, current_buffer + line + "\n")

                    # Print in real-time with prefix
                    print(f"[{prefix}] {line}")

                    # Also log important lines
                    if any(keyword in line.lower() for keyword in ['fps', 'error', 'warning', 'failed']):
                        self.logger.info(f"[{prefix}] {line}")
        except Exception as e:
            print(f"DEBUG_PRINT: Error in read_output_thread ({prefix}): {e}")
            self.logger.error(f"Error in read_output_thread ({prefix}): {e}")

    def run_stream_density_test(self, test_case):
        """Run stream density test using binary search algorithm"""
        try:
            print("DEBUG_PRINT: === STREAM DENSITY TEST START ===")
            self.logger.info("=== STREAM DENSITY TEST START ===")

            # Get parameters
            base_command = test_case.input.get(BENCHMARK_STREAM_DENSITY_BASE_COMMAND, '')
            self.target_fps = float(test_case.input.get('stream_density.target_fps', '28.5'))
            fps_tolerance = float(test_case.input.get('stream_density.fps_tolerance', '0.0'))
            self.min_fps = self.target_fps - fps_tolerance
            # Hard watchdog timeout for a single gst-launch run.
            # Protects CI from hangs when high stream counts overload the machine.
            hard_timeout_cfg = test_case.input.get('stream_density.process_timeout_sec', '900')
            self.process_hard_timeout = int(hard_timeout_cfg) if hard_timeout_cfg else None
            # None means: wait for pipeline to finish naturally (same as bash)
            duration_cfg = test_case.input.get('stream_density.gst_test_duration', None)
            self.test_duration = int(duration_cfg) if duration_cfg else None

            # Binary search parameters
            min_streams = int(test_case.input.get('stream_density.min_streams', '2'))
            max_streams = int(test_case.input.get('stream_density.max_streams', '128'))
            start_streams = int(test_case.input.get('stream_density.start_streams', '4'))

            self.logger.info("Stream Density Test Configuration:")
            self.logger.info("=" * 60)
            self.logger.info(f"   Target FPS: {self.target_fps}")
            self.logger.info(f"   Minimum FPS: {self.min_fps}")
            self.logger.info(f"   Test duration: {self.test_duration if self.test_duration else 'until video ends'}")
            self.logger.info(
                f"   Hard timeout/run: {self.process_hard_timeout if self.process_hard_timeout else 'disabled'} sec"
            )
            self.logger.info(f"   Stream range: [{min_streams}, {max_streams}]")
            self.logger.info(f"   Starting streams: {start_streams}")
            self.logger.info("=" * 60)

            if not base_command:
                raise ValueError(f"{BENCHMARK_STREAM_DENSITY_BASE_COMMAND} not found in test configuration")

            # Run binary search
            max_successful_streams = self.binary_search_stream_density(
                test_case, base_command, min_streams, max_streams, start_streams
            )

            # Save final results
            test_case.result.max_stream_density = max_successful_streams
            test_case.result.target_fps = self.target_fps
            test_case.result.min_fps = self.min_fps
            test_case.result.method = "binary_search_stream_density"

            # Populate generic benchmark KPI fields so downstream xlsx/final report
            # shows consistent values for stream density executions as well.
            test_case.result.fps_target = self.target_fps
            if self.target_fps > 0:
                pass_percent = max(0.0, round((self.target_fps - self.min_fps) / self.target_fps * 100, 1))
            else:
                pass_percent = 0.0
            test_case.result.fps_pass_threshold = pass_percent
            test_case.result.fps_pass_threshold_lower = self.min_fps
            test_case.result.fps_pass_threshold_upper = round((100 + pass_percent) / 100 * self.target_fps, 1)

            passing_samples = [(s, fps) for s, fps in self.test_results.items() if fps >= self.min_fps]
            failing_samples = [(s, fps) for s, fps in self.test_results.items() if fps < self.min_fps]
            if passing_samples:
                ps, pf = max(passing_samples, key=lambda x: x[0])
                test_case.result.highest_pass_sample = f"{ps} streams: {pf:.2f} FPS"
            else:
                test_case.result.highest_pass_sample = "n/a"
            if failing_samples:
                fs, ff = min(failing_samples, key=lambda x: x[0])
                test_case.result.lowest_fail_sample = f"{fs} streams: {ff:.2f} FPS"
            else:
                test_case.result.lowest_fail_sample = "n/a"

            # Log final results
            self.logger.info("=" * 60)
            self.logger.info("STREAM DENSITY TEST RESULTS:")
            self.logger.info(f"   Maximum stream density: {max_successful_streams}")
            self.logger.info(f"   Target FPS per stream: {self.target_fps}")
            self.logger.info(f"   Minimum FPS per stream: {self.min_fps}")

            # Show all test results
            self.logger.info("   Test history:")
            for streams in sorted(self.test_results.keys()):
                fps = self.test_results[streams]
                status = "PASS" if fps >= self.min_fps else "FAIL"
                self.logger.info(f"     {streams} streams: {fps:.2f} FPS [{status}]")
            self.logger.info("=" * 60)

            return max_successful_streams > 0

        except Exception as e:
            self.logger.error(f"FATAL ERROR in stream density test: {e}")
            import traceback
            self.logger.error(f"Full traceback:\n{traceback.format_exc()}")
            return False



    def binary_search_stream_density(self, test_case, base_command, min_streams, max_streams, start_streams):
        """Binary search algorithm to find maximum stream density"""

        lower_bound = min_streams
        upper_bound = max_streams
        current_streams = start_streams
        max_successful_streams = 0

        self.logger.info(f"Starting binary search: range=[{lower_bound}, {upper_bound}], start={current_streams}")

        iteration = 0
        max_iterations = 20

        while (upper_bound - lower_bound) > 1 and iteration < max_iterations:
            iteration += 1

            self.logger.info(f"Binary search iteration {iteration}: testing {current_streams} streams")
            self.logger.info(f"Current range: [{lower_bound}, {upper_bound}]")

            if current_streams in self.test_results:
                fps = self.test_results[current_streams]
                self.logger.info(f"Using cached result for {current_streams} streams: {fps:.2f} FPS")
            else:
                fps = self.run_single_stream_test(test_case, base_command, current_streams)
                self.test_results[current_streams] = fps

            if fps >= self.min_fps:
                max_successful_streams = max(max_successful_streams, current_streams)
                lower_bound = current_streams
                self.logger.info(f"✓ {current_streams} streams PASSED ({fps:.2f} >= {self.min_fps:.2f} FPS)")

                # Same as bash: n=int(($1+$2)/2+0.5); m=$1*2; print (n>m?m:n)
                n = int((current_streams + upper_bound) / 2 + 0.5)
                m = current_streams * 2
                current_streams = min(n, m)
                if current_streams > upper_bound:
                    current_streams = upper_bound

            else:
                upper_bound = current_streams
                self.logger.info(f"✗ {current_streams} streams FAILED ({fps:.2f} < {self.min_fps:.2f} FPS)")

                # Same as bash: n=int(($1+$2)/2); m=int($2/2); n=(n<m?m:n); print (n<1?1:n)
                n = int((lower_bound + current_streams) / 2)
                m = int(current_streams / 2)
                n = max(n, m)
                current_streams = max(n, 1)
                if current_streams < lower_bound:
                    current_streams = lower_bound

            self.logger.info(f"Next test will be {current_streams} streams, max successful so far: {max_successful_streams}")

        # Test boundary cases
        boundary_tests = [lower_bound, upper_bound]
        for streams in boundary_tests:
            if streams not in self.test_results:
                self.logger.info(f"Testing boundary case: {streams} streams")
                fps = self.run_single_stream_test(test_case, base_command, streams)
                self.test_results[streams] = fps

                if fps >= self.min_fps:
                    max_successful_streams = max(max_successful_streams, streams)
                    self.logger.info(f"✓ Boundary test {streams} streams PASSED ({fps:.2f} FPS)")
                else:
                    self.logger.info(f"✗ Boundary test {streams} streams FAILED ({fps:.2f} FPS)")

        self.logger.info(f"Binary search completed after {iteration} iterations")
        self.logger.info(f"Maximum successful stream density: {max_successful_streams}")

        return max_successful_streams

    def run_single_stream_test(self, test_case, base_command, stream_count):
        """Run test for specific number of streams"""

        self.logger.info(f"Running test with {stream_count} streams...")

        try:
            test_input = test_case.input.copy()
            test_input[BENCHMARK_STREAM_DENSITY_TARGET_STREAMS] = stream_count

            formatter = DotNameFormatter()
            command = formatter.vformat(base_command, [], test_input)

            multi_pipeline = self.create_multi_source_pipeline(command, stream_count)
            fps = self.execute_pipeline_test(multi_pipeline, stream_count)

            self.logger.info(f"Test with {stream_count} streams completed: {fps:.2f} FPS")
            return fps

        except Exception as e:
            self.logger.error(f"Error testing {stream_count} streams: {e}")
            return 0.0

    def create_multi_source_pipeline(self, base_command, stream_count):
        """Create a single pipeline with multiple video sources"""

        if base_command.startswith('gst-launch-1.0'):
            base_pipeline = base_command[14:].strip()
        else:
            base_pipeline = base_command

        pipeline_parts = []
        for i in range(stream_count):
            pipeline_with_instance = base_pipeline.replace('{{stream_id}}', str(i % 4))
            pipeline_parts.append(pipeline_with_instance)

        result = ' '.join(pipeline_parts)
        self.logger.debug(f"Created multi-stream pipeline with {stream_count} streams")
        return result

    def execute_pipeline_test(self, pipeline_command, stream_count):
        """
        Execute the pipeline and return minimum FPS.
        If test_duration is None: wait for pipeline to finish naturally.
        If test_duration is set: terminate after that many seconds.
        In both modes, process_hard_timeout acts as a watchdog timeout.
        """

        process = None

        try:
            start_time = time.time()

            # Reset buffers
            self.stdout_buffer = ""
            self.stderr_buffer = ""

            cmd_parts = ['gst-launch-1.0'] + pipeline_command.split()

            self.logger.debug(f"Starting pipeline execution for {stream_count} streams...")

            process = subprocess.Popen(
                cmd_parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                start_new_session=True
            )

            # Start threads to read output
            stdout_thread = threading.Thread(
                target=self.read_output_thread,
                args=(process.stdout, 'stdout_buffer', f'STDOUT-{stream_count}'),
                daemon=True
            )
            stderr_thread = threading.Thread(
                target=self.read_output_thread,
                args=(process.stderr, 'stderr_buffer', f'STDERR-{stream_count}'),
                daemon=True
            )

            stdout_thread.start()
            stderr_thread.start()

            timed_out = False
            while True:
                if process.poll() is not None:
                    break

                elapsed = time.time() - start_time

                if self.process_hard_timeout is not None and elapsed >= self.process_hard_timeout:
                    timed_out = True
                    self.logger.error(
                        f"Hard timeout reached after {elapsed:.1f}s for {stream_count} streams"
                    )
                    self._terminate_process_tree(
                        process,
                        stream_count,
                        reason=f"hard timeout {self.process_hard_timeout}s reached",
                    )
                    break

                if self.test_duration is not None and elapsed >= self.test_duration:
                    self._terminate_process_tree(
                        process,
                        stream_count,
                        reason=f"configured test duration {self.test_duration}s reached",
                    )
                    break

                time.sleep(1)

            # Wait for output threads to flush
            time.sleep(2)

            if timed_out:
                # Treat timeout as failed sample so binary search backs off.
                return 0.0

            # Parse FPS same as bash
            fps = parse_fps_from_output(self.stdout_buffer, self.stderr_buffer, stream_count)
            return fps if fps is not None else 0.0

        except Exception as e:
            self.logger.error(f"Error executing pipeline test: {e}")
            return 0.0
        finally:
            if process and process.poll() is None:
                self._terminate_process_tree(process, stream_count, reason="cleanup in finally")


def run_stream_density_test(test_case, logger):
    """Run stream density test with binary search algorithm"""

    logger.info("Running STREAM DENSITY TEST with binary search...")
    try:
        density_tester = StreamDensityTester(logger)
        result = density_tester.run_stream_density_test(test_case)
        return result
    except Exception as e:
        logger.error(f"Stream density test failed: {e}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return False
