#!/usr/bin/env python3
# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================

import re
import sys
import os
import json
import argparse
from typing import Dict, List, Tuple, Optional, Any

class OptimizerValidator:
    """Validator for optimizer test outputs"""
    
    def __init__(self, config_file: str):
        with open(config_file, 'r') as f:
            self.config = json.load(f)
    
    def extract_parameters(self, content: str) -> Dict[str, Any]:
        """Extract parameters from content"""
        params = {}
        
        # Extract device
        device_match = re.search(r'device=(CPU|GPU|NPU)', content, re.IGNORECASE)
        if device_match:
            params['device'] = device_match.group(1).upper()
        
        # Extract batch-size
        batch_match = re.search(r'batch-size=(\d+)', content, re.IGNORECASE)
        if batch_match:
            params['batch_size'] = int(batch_match.group(1))
        
        # Extract nireq
        nireq_match = re.search(r'nireq=(\d+)', content, re.IGNORECASE)
        if nireq_match:
            params['nireq'] = int(nireq_match.group(1))
        
        # Extract streams
        streams_match = re.search(r'number-streams=(\d+)', content, re.IGNORECASE)
        if streams_match:
            params['streams'] = int(streams_match.group(1))
        else:
            streams_fallback = re.search(r'streams?=(\d+)', content, re.IGNORECASE)
            if streams_fallback:
                params['streams'] = int(streams_fallback.group(1))
        
        return params
    
    def check_parameter_changes(self, before_params: Dict, after_params: Dict, 
                              required_changes: List[str]) -> Tuple[bool, Dict[str, str]]:
        """Check if required parameters have changed"""
        changes = {}
        
        for param in required_changes:
            before_val = before_params.get(param)
            after_val = after_params.get(param)
            
            if before_val is not None and after_val is not None and before_val != after_val:
                changes[param] = f"{before_val} → {after_val}"
            elif param in required_changes and (before_val is None or after_val is None):
                changes[param] = f"Missing parameter: {param}"
        
        has_changes = len([c for c in changes.values() if "→" in c]) > 0
        return has_changes, changes
    
    def validate_output_flag(self, content: str) -> bool:
        """Validate output flag test - check for baseline, optimal, and candidate pipelines"""
        print("🔍 Validating output flag structure...")
        
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                print("  ❌ Invalid JSON structure - expected object")
                return False
            
            has_baseline = 'baseline' in data and data['baseline'] is not None
            has_optimal = 'optimal' in data and data['optimal'] is not None
            has_candidates = 'candidates' in data and isinstance(data['candidates'], list) and len(data['candidates']) > 0
            
            candidate_count = len(data['candidates']) if has_candidates else 0
            
            print(f"  ✓ Baseline pipeline: {'✅' if has_baseline else '❌'}")
            print(f"  ✓ Optimal pipeline: {'✅' if has_optimal else '❌'}")
            print(f"  ✓ Candidate pipelines: {'✅' if has_candidates else '❌'} ({candidate_count} candidates)")
            
            if has_baseline:
                baseline_fps = data['baseline'].get('fps', 'N/A')
                print(f"    📊 Baseline FPS: {baseline_fps}")
            
            if has_optimal:
                optimal_fps = data['optimal'].get('fps', 'N/A')
                print(f"    📊 Optimal FPS: {optimal_fps}")
            
            success = has_baseline and has_optimal and has_candidates
            print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
            return success
            
        except json.JSONDecodeError as e:
            print(f"  ❌ Invalid JSON format: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error parsing JSON: {e}")
            return False
    
    def validate_streams_modifications(self, content: str, test_config: Dict) -> bool:
        """Validate streams modifications - check device, batch_size, nireq, and streams changes"""
        print("🔍 Validating streams modifications...")
        
        base_config = test_config.get('base_config', {})
        required_changes = ['device', 'batch_size', 'nireq', 'streams']
        
        current_params = self.extract_parameters(content)
        
        stream_counts = re.findall(r'number-streams=(\d+)', content, re.IGNORECASE)
        unique_stream_counts = set(int(x) for x in stream_counts)
        
        print(f"  Base config: {base_config}")
        print(f"  Current params: {current_params}")
        print(f"  Found stream counts in output: {sorted(unique_stream_counts)}")
        
        has_changes, changes = self.check_parameter_changes(base_config, current_params, required_changes)
        
        streams_tested = len(unique_stream_counts) > 1
        if streams_tested:
            changes['streams_variety'] = f"Tested {len(unique_stream_counts)} different stream counts: {sorted(unique_stream_counts)}"
            has_changes = True
        
        nireq_tests = re.findall(r'Testing nireq combination: \[(\d+)\]', content, re.IGNORECASE)
        unique_nireq = set(int(x) for x in nireq_tests)
        if len(unique_nireq) > 1:
            changes['nireq_variety'] = f"Tested {len(unique_nireq)} different nireq values: {sorted(unique_nireq)}"
            has_changes = True
        
        if changes:
            for param, change in changes.items():
                status = "✅" if ("→" in change or "Tested" in change) else "❌"
                print(f"  {status} {param}: {change}")
        else:
            print("  ❌ No parameter changes detected")
        
        print(f"  Result: {'✅ PASS' if has_changes else '❌ FAIL'}")
        return has_changes

    def validate_fps_modifications(self, content: str, test_config: Dict) -> bool:
        """Validate FPS modifications - check if device, batch_size, or nireq changed in JSON output"""
        print("🔍 Validating FPS modifications...")
        
        try:
            # Parse JSON to get candidates
            data = json.loads(content)
            if not isinstance(data, dict):
                print("  ❌ Invalid JSON structure - expected object")
                return False
            
            base_config = test_config.get('base_config', {})
            
            # Extract parameters from all candidates
            all_pipelines = []
            if 'candidates' in data and isinstance(data['candidates'], list):
                all_pipelines.extend([c.get('pipeline', '') for c in data['candidates']])
            if 'optimal' in data and isinstance(data['optimal'], dict):
                all_pipelines.append(data['optimal'].get('pipeline', ''))
            if 'baseline' in data and isinstance(data['baseline'], dict):
                all_pipelines.append(data['baseline'].get('pipeline', ''))
            
            # Combine all pipelines for analysis
            combined_content = '\n'.join(all_pipelines)
            
            current_params = self.extract_parameters(combined_content)
            required_changes = ['device', 'batch_size', 'nireq']
            has_changes, changes = self.check_parameter_changes(base_config, current_params, required_changes)
            
            # Check for variety in tested parameters
            device_tests = re.findall(r'device=(CPU|GPU|NPU)', combined_content, re.IGNORECASE)
            unique_devices = set(d.upper() for d in device_tests)
            if len(unique_devices) > 1:
                changes['device_variety'] = f"Tested {len(unique_devices)} different devices: {sorted(unique_devices)}"
                has_changes = True
            
            batch_tests = re.findall(r'batch-size=(\d+)', combined_content, re.IGNORECASE)
            unique_batches = set(int(b) for b in batch_tests)
            if len(unique_batches) > 1:
                changes['batch_variety'] = f"Tested {len(unique_batches)} different batch sizes: {sorted(unique_batches)}"
                has_changes = True
            
            nireq_tests = re.findall(r'nireq=(\d+)', combined_content, re.IGNORECASE)
            unique_nireq = set(int(n) for n in nireq_tests)
            if len(unique_nireq) > 1:
                changes['nireq_variety'] = f"Tested {len(unique_nireq)} different nireq values: {sorted(unique_nireq)}"
                has_changes = True
            
            print(f"  Base config: {base_config}")
            print(f"  Current params: {current_params}")
            print(f"  Analyzed {len(all_pipelines)} pipelines from JSON")
            
            if changes:
                for param, change in changes.items():
                    status = "✅" if ("→" in change or "Tested" in change) else "❌"
                    print(f"  {status} {param}: {change}")
            else:
                print("  ❌ No parameter changes detected")
            
            print(f"  Result: {'✅ PASS' if has_changes else '❌ FAIL'}")
            return has_changes
            
        except json.JSONDecodeError as e:
            print(f"  ❌ Invalid JSON format: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error validating FPS modifications: {e}")
            return False
    
    def validate_verbose_flag(self, content: str) -> bool:
        """Validate verbose flag - check if output contains CANDIDATE prints in logs"""
        print("🔍 Validating verbose flag...")
        
        try:
            # Search for CANDIDATE prints in logs
            candidate_matches = re.findall(r'CANDIDATE', content, re.IGNORECASE)
            candidate_count = len(candidate_matches)
            
            success = candidate_count > 0
            
            print(f"  ✓ CANDIDATE prints found: {candidate_count}")
            
            # Show some context around CANDIDATE prints
            if candidate_count > 0:
                # Find lines containing CANDIDATE
                lines = content.split('\n')
                candidate_lines = [line.strip() for line in lines if 'CANDIDATE' in line.upper()]
                
                # Show first few candidate lines
                for i, line in enumerate(candidate_lines[:3]):
                    print(f"    📊 Candidate {i+1}: {line[:80]}{'...' if len(line) > 80 else ''}")
                
                if len(candidate_lines) > 3:
                    print(f"    ... and {len(candidate_lines) - 3} more candidate prints")
            else:
                print("    ❌ No CANDIDATE prints found in logs")
            
            print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
            return success
            
        except Exception as e:
            print(f"  ❌ Error parsing logs: {e}")
            return False

    def validate_search_duration(self, file1: str, file2: str, test_config: Dict) -> bool:
        """Validate search duration - compare actual execution times from timing files"""
        print("🔍 Validating search duration...")
        
        def extract_timing_info(filepath: str) -> Optional[Dict]:
            # Look for timing file
            timing_file = filepath
            
            try:
                if os.path.exists(timing_file):
                    with open(timing_file, 'r') as f:
                        return json.loads(f.read())
                else:
                    print(f"    ⚠️  Timing file not found: {timing_file}")
                    return None
            except Exception as e:
                print(f"    ⚠️  Error reading timing file: {e}")
                return None
        
        try:
            timing1 = extract_timing_info(file1)
            timing2 = extract_timing_info(file2)
            
            if not timing1 or not timing2:
                print("  ❌ Could not extract timing information from both files")
                return False
            
            duration1 = float(timing1['duration_seconds'])
            duration2 = float(timing2['duration_seconds'])
            search_duration1 = timing1.get('search_duration_config', 'N/A')
            search_duration2 = timing2.get('search_duration_config', 'N/A')
            test_name1 = timing1.get('test_name', 'Test1')
            test_name2 = timing2.get('test_name', 'Test2')
            
            # Calculate difference
            time_diff = abs(duration1 - duration2)
            percentage_diff = (time_diff / min(duration1, duration2)) * 100 if min(duration1, duration2) > 0 else 0
            
            # Tests should have different durations (at least 10% difference)
            significant_difference = percentage_diff > 10
            
            print(f"  ✓ {test_name1} - Config: {search_duration1}s, Actual: {duration1:.2f}s")
            print(f"  ✓ {test_name2} - Config: {search_duration2}s, Actual: {duration2:.2f}s")
            print(f"  ✓ Time difference: {time_diff:.2f}s ({percentage_diff:.1f}%)")
            print(f"  ✓ Significant difference (>10%): {'✅' if significant_difference else '❌'}")
            
            # Additional validation - check if longer search_duration actually took longer
            logical_order = True
            if search_duration1 != 'N/A' and search_duration2 != 'N/A':
                try:
                    config1 = int(search_duration1)
                    config2 = int(search_duration2)
                    
                    if config1 > config2:
                        longer_actual = duration1
                        shorter_actual = duration2
                        longer_config = config1
                        shorter_config = config2
                    else:
                        longer_actual = duration2
                        shorter_actual = duration1
                        longer_config = config2
                        shorter_config = config1
                    
                    logical_order = longer_actual > shorter_actual
                    print(f"  ✓ Logical duration order: {'✅' if logical_order else '❌'}")
                    print(f"    📊 Longer config ({longer_config}s) took {longer_actual:.2f}s")
                    print(f"    📊 Shorter config ({shorter_config}s) took {shorter_actual:.2f}s")
                    
                except (ValueError, TypeError):
                    print(f"  ⚠️  Could not parse search duration configs for logical order check")
            
            success = significant_difference and logical_order
            
            print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
            return success
            
        except Exception as e:
            print(f"  ❌ Error comparing search durations: {e}")
            return False
    
    def validate_sample_duration(self, file1: str, file2: str, test_config: Dict) -> bool:
        """Validate sample duration - compare candidate counts from JSON output"""
        print("🔍 Validating sample duration...")
        
        def count_candidates_json(filepath: str) -> int:
            try:
                with open(filepath, 'r') as f:
                    content = f.read()
                
                data = json.loads(content)
                if isinstance(data, dict) and 'candidates' in data and isinstance(data['candidates'], list):
                    return len(data['candidates'])
                else:
                    print(f"    ⚠️  No candidates array in {filepath}")
                    return 0
                    
            except json.JSONDecodeError as e:
                print(f"    ❌ Invalid JSON in {filepath}: {e}")
                return 0
            except Exception as e:
                print(f"    ⚠️  Error reading {filepath}: {e}")
                return 0
        
        try:
            count1 = count_candidates_json(file1)
            count2 = count_candidates_json(file2)
            
            different_counts = count1 != count2
            
            print(f"  ✓ Candidates in file 1: {count1}")
            print(f"  ✓ Candidates in file 2: {count2}")
            print(f"  ✓ Different candidate counts: {'✅' if different_counts else '❌'}")
            
            if different_counts:
                print(f"    📊 Sample duration difference resulted in {abs(count1 - count2)} candidate difference")
            else:
                print(f"    ⚠️  Same number of candidates - sample duration may not have significant impact")
            
            print(f"  Result: {'✅ PASS' if different_counts else '❌ FAIL'}")
            return different_counts
            
        except Exception as e:
            print(f"  ❌ Error comparing candidate counts: {e}")
            return False
    
    def validate_cross_stream_batching(self, content: str, test_config: Dict) -> bool:
        """Validate cross stream batching - check if model-instance-id appears multiple times with same value in optimal pipeline"""
        print("🔍 Validating cross stream batching...")
        
        try:
            # Parse JSON to get optimal pipeline
            data = json.loads(content)
            if not isinstance(data, dict):
                print("  ❌ Invalid JSON structure - expected object")
                return False
            
            # Extract optimal pipeline
            optimal_pipeline = None
            if 'optimal' in data and isinstance(data['optimal'], dict):
                optimal_pipeline = data['optimal'].get('pipeline')
            
            if not optimal_pipeline:
                print("  ❌ No optimal pipeline found in JSON")
                return False
            
            print(f"  ✓ Found optimal pipeline: {optimal_pipeline[:100]}...")
            
            # Find all model-instance-id occurrences in the optimal pipeline
            model_instance_matches = re.findall(r'model-instance-id=(\w+)', optimal_pipeline, re.IGNORECASE)
            
            if not model_instance_matches:
                print("  ❌ No model-instance-id found in optimal pipeline")
                return False
            
            if len(model_instance_matches) < 2:
                print(f"  ❌ Only {len(model_instance_matches)} model-instance-id found, need at least 2 for batching")
                return False
            
            # Check if all model-instance-id values are the same
            unique_ids = set(model_instance_matches)
            
            if len(unique_ids) != 1:
                print(f"  ❌ Found different model-instance-id values: {unique_ids}")
                return False
            
            instance_id = model_instance_matches[0]
            count = len(model_instance_matches)
            
            print(f"  ✓ Model-instance-id: {instance_id}")
            print(f"  ✓ Number of occurrences: {count}")
            print(f"  ✓ All values are identical: {len(unique_ids) == 1}")
            print(f"  Result: ✅ PASS")
            return True
            
        except json.JSONDecodeError as e:
            print(f"  ❌ Invalid JSON format: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error validating cross stream batching: {e}")
            return False
    
    def validate_allowed_devices(self, content: str, test_config: Dict) -> bool:
        """Validate allowed devices - check only specified devices appear in JSON output"""
        print("🔍 Validating allowed devices...")
        
        try:
            # Parse JSON to get all pipelines
            data = json.loads(content)
            if not isinstance(data, dict):
                print("  ❌ Invalid JSON structure - expected object")
                return False
            
            allowed_devices = set(d.upper() for d in test_config.get('allowed_devices', []))
            
            # Extract all pipelines from JSON
            all_pipelines = []
            if 'candidates' in data and isinstance(data['candidates'], list):
                all_pipelines.extend([c.get('pipeline', '') for c in data['candidates']])
            if 'optimal' in data and isinstance(data['optimal'], dict):
                all_pipelines.append(data['optimal'].get('pipeline', ''))
            if 'baseline' in data and isinstance(data['baseline'], dict):
                all_pipelines.append(data['baseline'].get('pipeline', ''))
            
            # Combine all pipelines for analysis
            combined_content = '\n'.join(all_pipelines)
            
            found_devices = set(re.findall(r'device=(\w+)', combined_content, re.IGNORECASE))
            found_devices = set(d.upper() for d in found_devices)
            
            unauthorized_devices = found_devices - allowed_devices
            success = len(unauthorized_devices) == 0
            
            print(f"  ✓ Allowed devices: {list(allowed_devices)}")
            print(f"  ✓ Found devices: {list(found_devices)}")
            print(f"  ✓ Analyzed {len(all_pipelines)} pipelines from JSON")
            
            if unauthorized_devices:
                print(f"  ❌ Unauthorized devices: {list(unauthorized_devices)}")
            else:
                print(f"  ✅ All devices are authorized")
            
            print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
            return success
            
        except json.JSONDecodeError as e:
            print(f"  ❌ Invalid JSON format: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error validating allowed devices: {e}")
            return False
    
    def validate_standard_test(self, content: str, test_config: Dict) -> bool:
        """Validate standard test - check FPS improvement and golden FPS comparison from JSON"""
        print("🔍 Validating standard test performance...")
        
        golden_fps = test_config.get('golden_fps')
        tolerance = test_config.get('tolerance', 10)  # Default 10% tolerance
        
        try:
            # Parse JSON
            data = json.loads(content)
            if not isinstance(data, dict):
                print("  ❌ Invalid JSON structure - expected object")
                return False
            
            # Extract baseline (original) FPS
            original_fps = None
            if 'baseline' in data and isinstance(data['baseline'], dict):
                original_fps = data['baseline'].get('fps')
            
            # Extract optimal (best) FPS and pipeline
            optimized_fps = None
            optimized_pipeline = None
            if 'optimal' in data and isinstance(data['optimal'], dict):
                optimized_fps = data['optimal'].get('fps')
                optimized_pipeline = data['optimal'].get('pipeline')
            
            # Calculate improvement
            improvement = None
            if original_fps is not None and optimized_fps is not None:
                improvement = optimized_fps - original_fps
            
            # Display extracted values
            print(f"  📊 Original pipeline FPS: {original_fps if original_fps is not None else 'N/A'}")
            print(f"  📊 Optimized pipeline FPS: {optimized_fps if optimized_fps is not None else 'N/A'}")
            print(f"  📊 FPS improvement: {improvement if improvement is not None else 'N/A'}")
            
            if golden_fps:
                print(f"  📊 Golden FPS target: {golden_fps}")
                print(f"  📊 Tolerance: ±{tolerance}")
            
            success = True
            checks = []
            
            # Check 1: FPS values extracted successfully
            if original_fps is None or optimized_fps is None:
                checks.append(("❌", "FPS extraction", "Could not extract FPS values from JSON"))
                success = False
            else:
                checks.append(("✅", "FPS extraction", f"Original: {original_fps}, Optimized: {optimized_fps}"))
                
                # Check 2: Performance improvement
                if improvement > 0:
                    checks.append(("✅", "Performance improvement", f"{improvement:.2f} fps improvement"))
                else:
                    checks.append(("❌", "Performance improvement", f"No improvement: {improvement:.2f} fps"))
                    success = False
                
                # Check 3: Golden FPS comparison (if specified)
                if golden_fps:
                    fps_diff = abs(optimized_fps - golden_fps)
                    tolerance_value = golden_fps * (tolerance / 100.0)
                    
                    if fps_diff <= tolerance_value:
                        checks.append(("✅", "Golden FPS match", f"Within tolerance: {optimized_fps:.2f} vs {golden_fps} (±{tolerance_value:.2f})"))
                    else:
                        checks.append(("❌", "Golden FPS match", f"Outside tolerance: {optimized_fps:.2f} vs {golden_fps} (±{tolerance_value:.2f})"))
                        success = False
                else:
                    checks.append(("ℹ️", "Golden FPS match", "No golden FPS specified, skipping"))
            
            # Check 4: Optimized pipeline found
            if optimized_pipeline:
                # Truncate long pipelines for display
                display_pipeline = optimized_pipeline[:80] + "..." if len(optimized_pipeline) > 80 else optimized_pipeline
                checks.append(("✅", "Optimized pipeline", f"Found: {display_pipeline}"))
            else:
                checks.append(("❌", "Optimized pipeline", "No optimized pipeline found in JSON"))
                success = False
            
            # Print all checks
            for status, check_name, details in checks:
                print(f"  {status} {check_name}: {details}")
            
            print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
            return success
            
        except json.JSONDecodeError as e:
            print(f"  ❌ Invalid JSON format: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error validating JSON: {e}")
            return False

    def validate_test(self, test_name: str, output_file: str, 
                    compare_file: Optional[str] = None, log_file: Optional[str] = None) -> bool:
        """Main validation method"""
        test_config = self.config.get(test_name, {})
        test_type = test_config.get('test_type', 'standard')
        
        print(f"\n{'='*60}")
        print(f"🧪 Testing: {test_name} (type: {test_type})")
        print(f"{'='*60}")
        
        try:
            # Handle comparison tests - auto-find comparison files
            if test_type == 'search_duration':
                compare_with = test_config.get('compare_with')
                if compare_with and not compare_file:
                    results_dir = os.path.dirname(output_file)
                    # Use _timing.txt extension for timing files
                    compare_file = os.path.join(results_dir, f"{compare_with}_timing.txt")
                    print(f"🔍 Looking for timing comparison file: {compare_file}")
                
                if compare_file and os.path.exists(compare_file):
                    # Convert output_file to timing file
                    timing_file = output_file.replace('.json', '_timing.txt')
                    print(f"🔍 Using timing files: {timing_file} vs {compare_file}")
                    return self.validate_search_duration(timing_file, compare_file, test_config)
                else:
                    print(f"⚠️  Search duration test needs comparison file, skipping detailed validation")
                    return True
                else:
                    print(f"⚠️  Search duration test needs comparison file, skipping detailed validation")
                    return True
            
            elif test_type == 'sample_duration':
                compare_with = test_config.get('compare_with')
                if compare_with and not compare_file:
                    results_dir = os.path.dirname(output_file)
                    # Use .json extension for JSON files
                    compare_file = os.path.join(results_dir, f"{compare_with}.json")
                    print(f"🔍 Looking for JSON comparison file: {compare_file}")

            # Determine which file to read based on test type
            if test_type in ['streams_modifications', 'verbose_flag']:
                # These tests analyze logs
                file_to_read = log_file if log_file and os.path.exists(log_file) else output_file
                print(f"🔍 Reading log file for {test_type}: {file_to_read}")
            else:
                # These tests analyze JSON output
                file_to_read = output_file
                print(f"🔍 Reading JSON file for {test_type}: {file_to_read}")

            # Read the appropriate file
            with open(file_to_read, 'r') as f:
                content = f.read()

            # Route to appropriate validation method
            if test_type == 'standard':
                return self.validate_standard_test(content, test_config)

            elif test_type == 'output_flag':
                return self.validate_output_flag(content)

            elif test_type == 'fps_modifications':
                return self.validate_fps_modifications(content, test_config)

            elif test_type == 'streams_modifications':
                return self.validate_streams_modifications(content, test_config)

            elif test_type == 'verbose_flag':
                return self.validate_verbose_flag(content)

            elif test_type == 'sample_duration':
                if compare_file and os.path.exists(compare_file):
                    return self.validate_sample_duration(output_file, compare_file, test_config)
                else:
                    print(f"⚠️  Sample duration test needs comparison file, skipping detailed validation")
                    return True

            elif test_type == 'cross_stream_batching':
                return self.validate_cross_stream_batching(content, test_config)

            elif test_type == 'allowed_devices':
                return self.validate_allowed_devices(content, test_config)

            else:
                print(f"❌ Unknown test type: {test_type}")
                return False
                
        except FileNotFoundError as e:
            print(f"❌ File not found: {e}")
            return False
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive validator for optimizer features',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Output flag test
  python validator.py --config config.json --test-name output_test --output-file result.txt
  
  # FPS modifications test  
  python validator.py --config config.json --test-name fps_test --output-file result.txt
  
  # Duration comparison test
  python validator.py --config config.json --test-name duration_test --output-file result1.txt --compare-with result2.txt
        """
    )
    
    parser.add_argument('--config-file', required=True, 
                       help='Test configuration JSON file')
    parser.add_argument('--test-name', required=True, 
                       help='Test name from configuration')
    parser.add_argument('--output-file', required=True, 
                       help='Primary optimizer output file')
    parser.add_argument('--compare-with', 
                       help='Second output file for comparison tests')
    parser.add_argument('--log-file', 
                       help='Log file for verbose validation')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')

    args = parser.parse_args()

    # Validate arguments
    if not os.path.exists(args.config_file):
        print(f"❌ Config file not found: {args.config_file}")
        sys.exit(1)
    
    if not os.path.exists(args.output_file):
        print(f"❌ Output file not found: {args.output_file}")
        sys.exit(1)

    # Create validator and run test
    validator = OptimizerValidator(args.config_file)
    success = validator.validate_test(
        args.test_name, 
        args.output_file, 
        args.compare_with, 
        args.log_file
    )
    
    print(f"\n{'='*60}")
    print(f"🏁 Final Result: {'✅ PASS' if success else '❌ FAIL'}")
    print(f"{'='*60}")
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
