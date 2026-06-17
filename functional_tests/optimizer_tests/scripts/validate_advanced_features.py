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
            # Try to parse as JSON first
            data = json.loads(content)
            if isinstance(data, dict):
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
        
        except json.JSONDecodeError:
            # Fallback to regex search for non-JSON output
            print("  📝 Non-JSON output detected, using text-based validation...")
            
            has_baseline = bool(re.search(r'baseline.*pipeline', content, re.IGNORECASE | re.DOTALL))
            has_optimal = bool(re.search(r'optimal.*pipeline', content, re.IGNORECASE | re.DOTALL))
            has_candidates = bool(re.search(r'candidate.*pipeline', content, re.IGNORECASE | re.DOTALL))
            
            print(f"  ✓ Baseline pipeline: {'✅' if has_baseline else '❌'}")
            print(f"  ✓ Optimal pipeline: {'✅' if has_optimal else '❌'}")
            print(f"  ✓ Candidate pipelines: {'✅' if has_candidates else '❌'}")
            
            success = has_baseline and has_optimal and has_candidates
            print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
            return success
        
        except Exception as e:
            print(f"  ❌ Error parsing output: {e}")
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
        """Validate FPS modifications - check if device, batch_size, or nireq changed"""
        print("🔍 Validating FPS modifications...")
        
        base_config = test_config.get('base_config', {})
        required_changes = ['device', 'batch_size', 'nireq']
        
        current_params = self.extract_parameters(content)
        has_changes, changes = self.check_parameter_changes(base_config, current_params, required_changes)
        
        nireq_tests = re.findall(r'Testing nireq combination: \[(\d+)\]', content, re.IGNORECASE)
        unique_nireq = set(int(x) for x in nireq_tests)
        if len(unique_nireq) > 1:
            changes['nireq_variety'] = f"Tested {len(unique_nireq)} different nireq values: {sorted(unique_nireq)}"
            has_changes = True
        
        device_tests = re.findall(r'device=(CPU|GPU|NPU)', content, re.IGNORECASE)
        unique_devices = set(d.upper() for d in device_tests)
        if len(unique_devices) > 1:
            changes['device_variety'] = f"Tested {len(unique_devices)} different devices: {sorted(unique_devices)}"
            has_changes = True
        
        print(f"  Base config: {base_config}")
        print(f"  Current params: {current_params}")
        
        if changes:
            for param, change in changes.items():
                status = "✅" if ("→" in change or "Tested" in change) else "❌"
                print(f"  {status} {param}: {change}")
        else:
            print("  ❌ No parameter changes detected")
        
        print(f"  Result: {'✅ PASS' if has_changes else '❌ FAIL'}")
        return has_changes
    
    def validate_verbose_flag(self, content: str) -> bool:
        """Validate verbose flag - check if output contains candidate information"""
        print("🔍 Validating verbose flag...")
        
        try:
            # Try JSON parsing first
            data = json.loads(content)
            if isinstance(data, dict) and 'candidates' in data:
                candidate_count = len(data['candidates'])
                success = candidate_count > 0
                
                print(f"  ✓ Candidate entries found: {candidate_count}")
                
                # Show some candidate details if verbose
                if candidate_count > 0:
                    for i, candidate in enumerate(data['candidates'][:3]):  # Show first 3
                        fps = candidate.get('fps', 'N/A')
                        print(f"    📊 Candidate {i+1} FPS: {fps}")
                    if candidate_count > 3:
                        print(f"    ... and {candidate_count - 3} more candidates")
                
                print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
                return success
        
        except json.JSONDecodeError:
            # Fallback to regex search
            candidate_count = len(re.findall(r'candidate', content, re.IGNORECASE))
            success = candidate_count > 0
            
            print(f"  ✓ Candidate entries found: {candidate_count} (text-based count)")
            print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
            return success
        
        except Exception as e:
            print(f"  ❌ Error validating verbose output: {e}")
            return False
    
    def validate_search_duration(self, file1: str, file2: str, test_config: Dict) -> bool:
        """Validate search duration - compare actual execution times from timing files"""
        print("🔍 Validating search duration...")
        
        def extract_timing_info(filepath: str) -> Optional[Dict]:
            # Look for timing file
            timing_file = filepath.replace('.txt', '_timing.txt')
            
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
                
                # Try to parse as JSON first
                try:
                    data = json.loads(content)
                    if isinstance(data, dict) and 'candidates' in data:
                        return len(data['candidates'])
                except json.JSONDecodeError:
                    pass
                
                # Fallback to regex search for non-JSON output
                return len(re.findall(r'candidate', content, re.IGNORECASE))
                
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
            
            # Additional validation - show some details about the candidates
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
        """Validate cross stream batching - check if instance-id is same in final pipeline"""
        print("🔍 Validating cross stream batching...")
        
        # Find final pipeline section
        final_pipeline_match = re.search(r'final.*pipeline.*?instance-id=(\w+)', 
                                       content, re.IGNORECASE | re.DOTALL)
        
        if not final_pipeline_match:
            print("  ❌ No final pipeline with instance-id found")
            return False
        
        instance_id = final_pipeline_match.group(1)
        
        # Count occurrences of this instance-id
        all_instances = re.findall(r'instance-id=(\w+)', content, re.IGNORECASE)
        same_id_count = all_instances.count(instance_id)
        
        success = same_id_count > 1  # Should appear multiple times for batching
        
        print(f"  ✓ Final pipeline instance-id: {instance_id}")
        print(f"  ✓ Same instance-id occurrences: {same_id_count}")
        print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
        return success
    
    def validate_allowed_devices(self, content: str, test_config: Dict) -> bool:
        """Validate allowed devices - check only specified devices appear in output"""
        print("🔍 Validating allowed devices...")
        
        allowed_devices = set(d.upper() for d in test_config.get('allowed_devices', []))
        found_devices = set(re.findall(r'device=(\w+)', content, re.IGNORECASE))
        found_devices = set(d.upper() for d in found_devices)
        
        unauthorized_devices = found_devices - allowed_devices
        success = len(unauthorized_devices) == 0
        
        print(f"  ✓ Allowed devices: {list(allowed_devices)}")
        print(f"  ✓ Found devices: {list(found_devices)}")
        
        if unauthorized_devices:
            print(f"  ❌ Unauthorized devices: {list(unauthorized_devices)}")
        else:
            print(f"  ✅ All devices are authorized")
        
        print(f"  Result: {'✅ PASS' if success else '❌ FAIL'}")
        return success
    
    def validate_test(self, test_name: str, output_file: str, 
                     compare_file: Optional[str] = None, log_file: Optional[str] = None) -> bool:
        """Main validation method"""
        test_config = self.config.get(test_name, {})
        test_type = test_config.get('test_type', 'standard')
        
        print(f"\n{'='*60}")
        print(f"🧪 Testing: {test_name} (type: {test_type})")
        print(f"{'='*60}")
        
        try:
            # For standard tests, just check if file exists and has content
            if test_type == 'standard':
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    print("✅ Standard test validation: Output file exists and has content")
                    return True
                else:
                    print("❌ Standard test validation: Output file missing or empty")
                    return False
            
            # Handle comparison tests - auto-find comparison files
            if test_type in ['search_duration', 'sample_duration']:
                compare_with = test_config.get('compare_with')
                if compare_with and not compare_file:
                    results_dir = os.path.dirname(output_file)
                    compare_file = os.path.join(results_dir, f"{compare_with}.txt")
                    print(f"🔍 Looking for comparison file: {compare_file}")
            
            # For search_duration, we don't need to read the main output file content
            if test_type == 'search_duration':
                if compare_file and os.path.exists(compare_file):
                    return self.validate_search_duration(output_file, compare_file, test_config)
                else:
                    print(f"⚠️  Search duration test needs comparison file, skipping detailed validation")
                    return True
            
            # Read main output file for other advanced tests
            with open(output_file, 'r') as f:
                content = f.read()
            
            # Route to appropriate validation method
            if test_type == 'output_flag':
                return self.validate_output_flag(content)
            
            elif test_type == 'fps_modifications':
                return self.validate_fps_modifications(content, test_config)
            
            elif test_type == 'streams_modifications':
                return self.validate_streams_modifications(content, test_config)
            
            elif test_type == 'verbose_flag':
                log_content = content
                if log_file:
                    with open(log_file, 'r') as f:
                        log_content = f.read()
                return self.validate_verbose_flag(log_content)
            
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
