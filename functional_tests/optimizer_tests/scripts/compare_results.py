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
    print(f"🔍 DEBUG: Starting extraction from file: {filename}")
    
    try:
        with open(filename, 'r') as f:
            content = f.read()
        
        print(f"🔍 DEBUG: File size: {len(content)} characters")
        
        lines = content.split('\n')
        print(f"🔍 DEBUG: Total lines: {len(lines)}")
        
        pipeline = None
        fps = None
        initial_fps = None
        
        # Extract initial FPS
        print("🔍 DEBUG: Searching for initial FPS...")
        initial_patterns = ['Initial pipeline FPS:', 'Original pipeline FPS:', 'Baseline FPS:']
        for line_num, line in enumerate(lines):
            for pattern in initial_patterns:
                if pattern in line:
                    print(f"🔍 DEBUG: Found initial FPS pattern '{pattern}' at line {line_num}: {line.strip()}")
                    match = re.search(r'FPS:\s*([\d.]+)', line)
                    if match:
                        initial_fps = float(match.group(1))
                        print(f"🔍 DEBUG: Extracted initial FPS: {initial_fps}")
                        break
            if initial_fps:
                break
        
        if initial_fps is None:
            print("🔍 DEBUG: No initial FPS found")
        
        # Extract best pipeline and FPS
        print("🔍 DEBUG: Searching for best pipeline and FPS...")
        best_patterns = ['Best found pipeline:', 'Optimized pipeline:', 'Best pipeline:']
        for i, line in enumerate(lines):
            for pattern in best_patterns:
                if pattern in line:
                    print(f"🔍 DEBUG: Found best pipeline pattern '{pattern}' at line {i}: {line.strip()}")
                    pipeline = line.split(pattern, 1)[1].strip()
                    print(f"🔍 DEBUG: Extracted pipeline: {pipeline[:100]}...")
                    
                    # Look for FPS in next few lines
                    print(f"🔍 DEBUG: Searching for FPS in next 5 lines after line {i}...")
                    for j in range(i+1, min(i+5, len(lines))):
                        print(f"🔍 DEBUG: Checking line {j}: {lines[j].strip()}")
                        fps_patterns = [r'with fps:\s*([\d.]+)', r'FPS:\s*([\d.]+)', r'(\d+\.?\d*)\s*fps']
                        for fps_pattern in fps_patterns:
                            match = re.search(fps_pattern, lines[j], re.IGNORECASE)
                            if match:
                                fps = float(match.group(1))
                                print(f"🔍 DEBUG: Found FPS with pattern '{fps_pattern}': {fps}")
                                break
                        if fps:
                            break
                    
                    if fps is None:
                        print(f"🔍 DEBUG: No FPS found in lines {i+1} to {min(i+5, len(lines))}")
                    break
            if pipeline and fps:
                break
        
        if pipeline is None:
            print("🔍 DEBUG: No best pipeline found")
        if fps is None:
            print("🔍 DEBUG: No current FPS found")
            
        # Show some sample lines for debugging
        print("🔍 DEBUG: Sample lines from file:")
        for i, line in enumerate(lines[:10]):
            if line.strip():
                print(f"🔍 DEBUG: Line {i}: {line.strip()}")
        
        print("🔍 DEBUG: Last 10 lines from file:")
        for i, line in enumerate(lines[-10:], len(lines)-10):
            if line.strip():
                print(f"🔍 DEBUG: Line {i}: {line.strip()}")
        
        print(f"🔍 DEBUG: Final results - Pipeline: {'Found' if pipeline else 'None'}, FPS: {fps}, Initial FPS: {initial_fps}")
        
        return pipeline, fps, initial_fps
        
    except Exception as e:
        print(f"❌ DEBUG: Error extracting from {filename}: {e}")
        import traceback
        traceback.print_exc()
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
    print(f"🔍 DEBUG: append_to_final_report called with path: {final_report_path}")
    print(f"🔍 DEBUG: File exists before: {os.path.exists(final_report_path)}")
    try:
        if not os.path.exists(final_report_path):
            print(f"🔍 DEBUG: Creating new final report file")
            with open(final_report_path, 'w') as f:
                f.write("OPTIMIZER TESTS - FINAL REPORT\n")
                f.write("="*50 + "\n")
            print(f"🔍 DEBUG: Header written successfully")
        
        print(f"🔍 DEBUG: Appending test results for: {test_name}")
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
            
            # Add pipeline information to report
            f.write(f"\nPIPELINE INFORMATION:\n")
            f.write(f"Golden Pipeline: {result.get('golden_pipeline', 'N/A')}\n")
            f.write(f"Current Pipeline: {result.get('current_pipeline', 'N/A')}\n")
            f.write("-" * 30 + "\n")

        print(f"🔍 DEBUG: Final report updated successfully")
        print(f"🔍 DEBUG: File exists after: {os.path.exists(final_report_path)}")

    except Exception as e:
        print(f"Warning: Could not write to final report: {e}")

def compare_results(full_output_path, config_file, test_name, fps_tolerance=1, final_report_path=None):
    """Compare current results with golden values"""
    
    print(f"🔍 DEBUG: Starting comparison for test: {test_name}")
    print(f"🔍 DEBUG: Full output path: {full_output_path}")
    print(f"🔍 DEBUG: Config file: {config_file}")
    
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
    
    # Display pipeline information
    print(f"\nPIPELINE INFORMATION:")
    print(f"Golden Pipeline:  {golden_pipeline}")
    print(f"Current Pipeline: {current_pipeline if current_pipeline else 'N/A'}")
    
    print(f"\nOVERALL: {'✅ PASS' if overall_pass else '❌ FAIL'}")
    print("="*50)
    
    # Save to final report
    if final_report_path:
        result = {
            'status': 'PASS' if overall_pass else 'FAIL',
            'golden_fps': golden_fps,
            'current_fps': current_fps,
            'initial_fps': initial_fps,
            'tolerance': fps_tolerance,
            'fps_match': fps_match,
            'golden_pipeline': golden_pipeline,
            'current_pipeline': current_pipeline if current_pipeline else 'N/A'
        }
        append_to_final_report(final_report_path, test_name, result)
    
    return overall_pass

def main():
    parser = argparse.ArgumentParser(description='Compare optimizer FPS results')
    parser.add_argument('--full-output', '-f', required=True, help='Full output file')
    parser.add_argument('--config-file', '-c', required=True, help='Test configuration file (JSON)')
    parser.add_argument('--test-name', '-n', required=True, help='Test name')
    parser.add_argument('--tolerance', '-t', type=float, default=0.01, help='FPS tolerance')
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
    print(f"🔍 DEBUG: final_report argument received: {args.final_report}")
    success = compare_results(args.full_output, args.config_file, args.test_name, args.tolerance, args.final_report)

    if args.final_report:
        print(f"🔍 DEBUG: Checking if final report was created: {args.final_report}")
        print(f"🔍 DEBUG: File exists: {os.path.exists(args.final_report)}")

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
