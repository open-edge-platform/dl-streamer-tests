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

def quick_validate(output_file_path, test_config, test_type):
    """Quick validation for all test types"""
    print(f"🔍 Quick validation for {test_type}")
    
    try:
        with open(output_file_path, 'r') as f:
            content = f.read()
        
        validation = test_config.get('validation', {})
        
        if test_type == 'output_flag':
            # Check for key sections
            has_baseline = any(word in content.lower() for word in ['baseline', 'original', 'initial'])
            has_optimal = any(word in content.lower() for word in ['optimal', 'best', 'final'])
            has_candidates = 'candidate' in content.lower()
            
            success = has_baseline and has_optimal and has_candidates
            print(f"  Structure check: {'✅' if success else '❌'} (baseline:{has_baseline}, optimal:{has_optimal}, candidates:{has_candidates})")
            return success
            
        elif test_type in ['fps_modifications', 'streams_modifications']:
            # Check for parameter modifications
            has_device = re.search(r'device=(CPU|GPU|NPU)', content, re.IGNORECASE)
            has_batch = re.search(r'batch-size=\d+', content, re.IGNORECASE)
            has_nireq = re.search(r'nireq=\d+', content, re.IGNORECASE)
            
            success = bool(has_device and has_batch and has_nireq)
            
            # Additional check for streams mode
            if test_type == 'streams_modifications':
                has_streams = any(word in content.lower() for word in ['stream', 'concurrent', 'parallel'])
                success = success and has_streams
                print(f"  Streams check: {'✅' if has_streams else '❌'}")
            
            print(f"  Modifications: {'✅' if success else '❌'} (device:{bool(has_device)}, batch:{bool(has_batch)}, nireq:{bool(has_nireq)})")
            return success
            
        elif test_type == 'cross_stream_batching':
            # Look for shared inference instances
            instance_ids = re.findall(r'inference-instance-id=(\w+)', content, re.IGNORECASE)
            has_shared = len(instance_ids) > len(set(instance_ids)) if instance_ids else False
            
            print(f"  Cross-stream batching: {'✅' if has_shared else '❌'} (found {len(instance_ids)} instances)")
            return has_shared
            
        elif test_type == 'allowed_devices':
            # Check device restrictions
            allowed = validation.get('allowed_devices', [])
            found_devices = set(re.findall(r'device=(\w+)', content, re.IGNORECASE))
            unauthorized = found_devices - set(d.upper() for d in allowed)
            
            success = len(unauthorized) == 0
            print(f"  Device restriction: {'✅' if success else '❌'} (allowed:{allowed}, found:{list(found_devices)})")
            return success
            
        return True
        
    except Exception as e:
        print(f"❌ Validation error: {e}")
        return False

def validate_verbose_logs(log_file_path, expected_pattern='CANDIDATE'):
    """Quick verbose log validation"""
    try:
        with open(log_file_path, 'r') as f:
            content = f.read()
        
        count = len(re.findall(expected_pattern, content, re.IGNORECASE))
        success = count > 0
        print(f"🔍 Verbose logs: {'✅' if success else '❌'} (found {count} '{expected_pattern}' entries)")
        return success
        
    except Exception as e:
        print(f"❌ Log validation error: {e}")
        return False

def compare_candidate_counts(file1, file2, name1, name2):
    """Quick candidate count comparison"""
    try:
        def get_count(file_path):
            with open(file_path, 'r') as f:
                return len(re.findall(r'candidate', f.read(), re.IGNORECASE))
        
        count1, count2 = get_count(file1), get_count(file2)
        different = count1 != count2
        
        print(f"🔍 Candidate comparison: {'✅' if different else '❌'} ({name1}:{count1} vs {name2}:{count2})")
        return different
        
    except Exception as e:
        print(f"❌ Comparison error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Quick validation for optimizer features')
    parser.add_argument('--output-file', required=True, help='Optimizer output file')
    parser.add_argument('--config-file', required=True, help='Test configuration file')
    parser.add_argument('--test-name', required=True, help='Test name')
    parser.add_argument('--log-file', help='Log file for verbose validation')
    parser.add_argument('--compare-with', help='Second output file for comparison')
    parser.add_argument('--compare-test-name', help='Second test name for comparison')
    
    args = parser.parse_args()
    
    # Load config
    with open(args.config_file, 'r') as f:
        config = json.load(f)
    
    test_config = config.get(args.test_name, {})
    test_type = test_config.get('test_type', '')
    
    # Quick validation based on test type
    if test_type == 'verbose_flag':
        success = validate_verbose_logs(args.log_file or args.output_file)
    elif test_type == 'sample_duration_candidates' and args.compare_with:
        success = compare_candidate_counts(
            args.output_file, args.compare_with, 
            args.test_name, args.compare_test_name
        )
    else:
        success = quick_validate(args.output_file, test_config, test_type)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
