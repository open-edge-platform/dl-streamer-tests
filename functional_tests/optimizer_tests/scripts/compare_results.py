# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================

import re
import sys
import os
import argparse
import json
from datetime import datetime

def extract_pipeline_and_fps(filename):
    """Extract pipeline, FPS and initial FPS from logs"""
    try:
        with open(filename, 'r') as f:
            content = f.read()
        
        lines = content.split('\n')
        pipeline = None
        fps = None
        initial_fps = None
        
        # Extract initial FPS
        initial_patterns = ['Initial pipeline FPS:', 'Original pipeline FPS:', 'Baseline FPS:']
        for line in lines:
            for pattern in initial_patterns:
                if pattern in line:
                    match = re.search(r'FPS:\s*([\d.]+)', line)
                    if match:
                        initial_fps = float(match.group(1))
                        break
            if initial_fps:
                break
        
        # Extract best pipeline and FPS
        best_patterns = ['Best found pipeline:', 'Optimized pipeline:', 'Best pipeline:']
        for i, line in enumerate(lines):
            for pattern in best_patterns:
                if pattern in line:
                    pipeline = line.split(pattern, 1)[1].strip()
                    
                    # Look for FPS in next few lines
                    for j in range(i+1, min(i+5, len(lines))):
                        fps_patterns = [r'with fps:\s*([\d.]+)', r'FPS:\s*([\d.]+)', r'(\d+\.?\d*)\s*fps']
                        for fps_pattern in fps_patterns:
                            match = re.search(fps_pattern, lines[j], re.IGNORECASE)
                            if match:
                                fps = float(match.group(1))
                                break
                        if fps:
                            break
                    break
            if pipeline and fps:
                break
        
        return pipeline, fps, initial_fps
        
    except Exception as e:
        print(f"Error extracting from {filename}: {e}")
        return None, None, None

def load_golden_values(config_file, test_name):
    """Load golden values from JSON config file"""
    try:
        with open(config_file, 'r') as f:
            data = json.load(f)
        
        if test_name not in data:
            print(f"Test '{test_name}' not found in config file")
            return None, None, None
        
        test_config = data[test_name]
        
        # Get golden pipeline and FPS
        golden_pipeline = test_config.get('golden_pipeline', 'N/A')
        golden_fps = float(test_config['golden_fps'])
        tolerance = test_config.get('tolerance')
        
        return golden_pipeline, golden_fps, tolerance
                
    except Exception as e:
        print(f"Error loading golden values: {e}")
        return None, None, None

def append_to_final_report(final_report_path, test_name, result):
    """Append test result to final report"""
    try:
        if not os.path.exists(final_report_path):
            with open(final_report_path, 'w') as f:
                f.write("OPTIMIZER TESTS - FINAL REPORT\n")
                f.write("="*50 + "\n")
        
        with open(final_report_path, 'a') as f:
            f.write(f"\nTEST: {test_name}\n")
            f.write(f"Status: {result['status']}\n")
            f.write(f"Golden FPS: {result['golden_fps']}\n")
            f.write(f"Current FPS: {result['current_fps']}\n")
            f.write(f"Tolerance: {result['tolerance']}\n")
            f.write(f"FPS Match: {'PASS' if result['fps_match'] else 'FAIL'}\n")
            if result['initial_fps']:
                improvement = ((result['current_fps'] - result['initial_fps']) / result['initial_fps']) * 100
                f.write(f"Optimization: {improvement:.2f}%\n")
            f.write("-" * 30 + "\n")
            
    except Exception as e:
        print(f"Warning: Could not write to final report: {e}")

def compare_results(full_output_path, config_file, test_name, fps_tolerance=1, final_report_path=None):
    """Compare current results with golden values"""
    
    # Extract current results
    current_pipeline, current_fps, initial_fps = extract_pipeline_and_fps(full_output_path)
    
    if current_fps is None:
        print("❌ Failed to extract current FPS")
        return False
    
    # Load golden values
    golden_pipeline, golden_fps, custom_tolerance = load_golden_values(config_file, test_name)
    
    if golden_fps is None:
        print("❌ Failed to load golden FPS")
        return False
    
    # Use custom tolerance if available
    if custom_tolerance is not None:
        fps_tolerance = custom_tolerance
    
    # Compare results
    fps_diff = abs(current_fps - golden_fps)
    fps_match = fps_diff < fps_tolerance
    
    # Check optimization (if initial FPS available)
    optimization_ok = True
    if initial_fps is not None:
        optimization_ok = current_fps >= initial_fps
    
    overall_pass = fps_match and optimization_ok
    
    # Print results
    print("="*50)
    print(f"TEST: {test_name}")
    print("="*50)
    print(f"Golden FPS:  {golden_fps}")
    print(f"Current FPS: {current_fps}")
    print(f"Difference:  {fps_diff:.6f}")
    print(f"Tolerance:   {fps_tolerance}")
    print(f"FPS Match:   {'✅ PASS' if fps_match else '❌ FAIL'}")
    
    if initial_fps is not None:
        improvement = ((current_fps - initial_fps) / initial_fps) * 100
        print(f"Initial FPS: {initial_fps}")
        print(f"Improvement: {improvement:.2f}%")
        print(f"Optimization: {'✅ PASS' if optimization_ok else '❌ FAIL'}")
    
    print(f"OVERALL: {'✅ PASS' if overall_pass else '❌ FAIL'}")
    print("="*50)
    
    # Save to final report
    if final_report_path:
        result = {
            'status': 'PASS' if overall_pass else 'FAIL',
            'golden_fps': golden_fps,
            'current_fps': current_fps,
            'initial_fps': initial_fps,
            'tolerance': fps_tolerance,
            'fps_match': fps_match
        }
        append_to_final_report(final_report_path, test_name, result)
    
    return overall_pass

def main():
    parser = argparse.ArgumentParser(description='Compare optimizer FPS results')
    parser.add_argument('--full-output', '-f', required=True, help='Full output file')
    parser.add_argument('--config-file', '-c', required=True, help='Test configuration file (JSON)')
    parser.add_argument('--test-name', '-n', required=True, help='Test name')
    parser.add_argument('--tolerance', '-t', type=float, default=0.01, help='FPS tolerance (overridden by config)')
    parser.add_argument('--final-report', '-r', help='Final report file')
    
    args = parser.parse_args()
    
    # Check files exist
    if not os.path.exists(args.full_output):
        print(f"❌ File not found: {args.full_output}")
        sys.exit(1)
    
    if not os.path.exists(args.config_file):
        print(f"❌ Config file not found: {args.config_file}")
        sys.exit(1)
    
    # Run comparison
    success = compare_results(args.full_output, args.config_file, args.test_name, args.tolerance, args.final_report)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
