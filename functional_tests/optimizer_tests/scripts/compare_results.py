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

def extract_pipeline_and_fps_from_json(filename):
    """Extract pipeline and FPS from JSON output"""
    print(f"🔍 DEBUG: Extracting from JSON file: {filename}")
    
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Extract from JSON structure
        pipeline = data.get('best_pipeline', data.get('optimized_pipeline'))
        fps = data.get('best_fps', data.get('optimized_fps'))
        initial_fps = data.get('initial_fps', data.get('baseline_fps'))
        no_optimization_found = data.get('no_optimization_found', False)
        
        print(f"🔍 DEBUG: JSON extraction - Pipeline: {'Found' if pipeline else 'None'}, FPS: {fps}, Initial FPS: {initial_fps}")
        
        return pipeline, fps, initial_fps, no_optimization_found
        
    except json.JSONDecodeError as e:
        print(f"❌ DEBUG: Invalid JSON in {filename}: {e}")
        return None, None, None, False
    except Exception as e:
        print(f"❌ DEBUG: Error extracting from JSON {filename}: {e}")
        return None, None, None, False

def extract_pipeline_and_fps_from_json(filename):
    """Extract pipeline and FPS from JSON output"""
    print(f"🔍 DEBUG: Extracting from JSON file: {filename}")
    
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        pipeline = None
        fps = None
        initial_fps = None
        no_optimization_found = False
        
        # Extract baseline (initial) FPS
        if 'baseline' in data and isinstance(data['baseline'], dict):
            initial_fps = data['baseline'].get('fps')
            print(f"🔍 DEBUG: Found baseline FPS: {initial_fps}")
        
        # Extract optimal (best) pipeline and FPS
        if 'optimal' in data and isinstance(data['optimal'], dict):
            pipeline = data['optimal'].get('pipeline')
            fps = data['optimal'].get('fps')
            print(f"🔍 DEBUG: Found optimal pipeline and FPS: {fps}")
        
        # If no optimal found, check if there are candidates
        if fps is None and 'candidates' in data and isinstance(data['candidates'], list) and len(data['candidates']) > 0:
            # Find the candidate with highest FPS
            best_candidate = max(data['candidates'], key=lambda x: x.get('fps', 0))
            pipeline = best_candidate.get('pipeline')
            fps = best_candidate.get('fps')
            print(f"🔍 DEBUG: Using best candidate FPS: {fps}")
        
        # Check if no optimization was found (optimal FPS <= baseline FPS)
        if initial_fps is not None and fps is not None:
            if fps <= initial_fps:
                no_optimization_found = True
                print(f"🔍 DEBUG: No optimization found - optimal FPS ({fps}) <= baseline FPS ({initial_fps})")
        
        # If still no FPS found, try legacy field names
        if fps is None:
            fps = data.get('best_fps', data.get('optimized_fps'))
            pipeline = data.get('best_pipeline', data.get('optimized_pipeline'))
            print(f"🔍 DEBUG: Using legacy fields - FPS: {fps}")
        
        # Check for explicit no_optimization_found flag
        if data.get('no_optimization_found', False):
            no_optimization_found = True
            print(f"🔍 DEBUG: Explicit no_optimization_found flag set")
        
        print(f"🔍 DEBUG: JSON extraction - Pipeline: {'Found' if pipeline else 'None'}, FPS: {fps}, Initial FPS: {initial_fps}, No optimization: {no_optimization_found}")
        
        return pipeline, fps, initial_fps, no_optimization_found
        
    except json.JSONDecodeError as e:
        print(f"❌ DEBUG: Invalid JSON in {filename}: {e}")
        return None, None, None, False
    except Exception as e:
        print(f"❌ DEBUG: Error extracting from JSON {filename}: {e}")
        return None, None, None, False

def extract_pipeline_and_fps(filename):
    """Extract pipeline and FPS - auto-detect JSON vs log format"""
    
    # First try JSON format
    if filename.endswith('.json'):
        result = extract_pipeline_and_fps_from_json(filename)
        if result[1] is not None:  # If FPS was found
            return result
        else:
            print(f"🔍 DEBUG: JSON extraction failed, trying log format fallback")
    
    # Fallback to log format
    return extract_pipeline_and_fps_from_logs(filename)

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
    print(f"🔍 DEBUG: Writing to final report: {final_report_path}")
    
    try:
        if not os.path.exists(final_report_path):
            with open(final_report_path, 'w') as f:
                f.write("OPTIMIZER TESTS - FINAL REPORT\n")
                f.write("="*50 + "\n")
        
        with open(final_report_path, 'a') as f:
            f.write(f"\nTEST: {test_name}\n")
            f.write(f"Status: {result['status']}\n")
            f.write(f"Golden FPS: {result['golden_fps']}\n")
            f.write(f"Initial FPS: {result['initial_fps'] if result['initial_fps'] else 'N/A'}\n")
            f.write(f"Current FPS: {result['current_fps']}\n")
            f.write(f"Tolerance: {result['tolerance']}\n")
            f.write(f"FPS Match: {'PASS' if result['fps_match'] else 'FAIL'}\n")
            f.write(f"File Type: {result.get('file_type', 'Unknown')}\n")
            
            # Add no optimization info
            if result.get('no_optimization_found'):
                f.write(f"Optimization Result: No optimized pipeline found that outperforms the original pipeline (ACCEPTABLE)\n")
            elif result['initial_fps']:
                improvement = ((result['current_fps'] - result['initial_fps']) / result['initial_fps']) * 100
                f.write(f"Optimization: {improvement:.2f}%\n")
            
            # Add pipeline information to report
            f.write(f"\nPIPELINE INFORMATION:\n")
            f.write(f"Golden Pipeline: {result.get('golden_pipeline', 'N/A')}\n")
            f.write(f"Current Pipeline: {result.get('current_pipeline', 'N/A')}\n")
            f.write("-" * 30 + "\n")

        print(f"🔍 DEBUG: Final report updated successfully")

    except Exception as e:
        print(f"❌ ERROR: Could not write to final report: {e}")
        import traceback
        traceback.print_exc()

def compare_results(output_file, config_file, test_name, fps_tolerance=1, final_report_path=None):
    """Compare current results with golden values"""
    
    print(f"🔍 DEBUG: Starting comparison for test: {test_name}")
    print(f"🔍 DEBUG: Using output file: {output_file}")
    
    # Determine file type
    file_type = "JSON" if output_file.endswith('.json') else "LOG"
    print(f"🔍 DEBUG: Detected file type: {file_type}")
    
    # Extract current results
    current_pipeline, current_fps, initial_fps, no_optimization_found = extract_pipeline_and_fps(output_file)
    
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
    if initial_fps is not None and not no_optimization_found:
        optimization_ok = current_fps >= initial_fps
    elif no_optimization_found:
        # If the exact phrase was found, it's acceptable as long as FPS matches golden
        optimization_ok = True
        print("🔍 DEBUG: Found exact phrase 'No optimized pipeline found that outperforms the original pipeline' - treating as acceptable scenario")
    
    overall_pass = fps_match and optimization_ok
    
    # Print results
    print("="*50)
    print(f"TEST: {test_name}")
    print(f"FILE TYPE: {file_type}")
    print("="*50)
    print(f"Golden FPS:  {golden_fps}")
    print(f"Current FPS: {current_fps}")
    print(f"Difference:  {fps_diff:.6f}")
    print(f"Tolerance:   {fps_tolerance}")
    print(f"FPS Match:   {'✅ PASS' if fps_match else '❌ FAIL'}")
    
    if no_optimization_found:
        print(f"Optimization: ✅ ACCEPTABLE (No optimized pipeline found that outperforms the original pipeline)")
    elif initial_fps is not None:
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
            'current_pipeline': current_pipeline if current_pipeline else 'N/A',
            'no_optimization_found': no_optimization_found,
            'file_type': file_type
        }
        append_to_final_report(final_report_path, test_name, result)
    
    return overall_pass

def main():
    parser = argparse.ArgumentParser(description='Compare optimizer FPS results')
    parser.add_argument('--output-file', '-f', required=True, help='Output file (JSON or log)')
    parser.add_argument('--config-file', '-c', required=True, help='Test configuration file (JSON)')
    parser.add_argument('--test-name', '-n', required=True, help='Test name')
    parser.add_argument('--tolerance', '-t', type=float, default=0.01, help='FPS tolerance')
    parser.add_argument('--final-report', '-r', help='Final report file')
    
    # Legacy support
    parser.add_argument('--full-output', help='Legacy: same as --output-file')
    
    args = parser.parse_args()
    
    # Handle legacy argument
    output_file = args.output_file or args.full_output
    if not output_file:
        print("❌ Either --output-file or --full-output must be specified")
        sys.exit(1)
    
    # Check files exist
    if not os.path.exists(output_file):
        print(f"❌ File not found: {output_file}")
        sys.exit(1)
    
    if not os.path.exists(args.config_file):
        print(f"❌ Config file not found: {args.config_file}")
        sys.exit(1)
    
    # Run comparison
    print(f"🔍 DEBUG: Final report will be saved to: {args.final_report}")
    success = compare_results(output_file, args.config_file, args.test_name, args.tolerance, args.final_report)

    if args.final_report:
        print(f"🔍 DEBUG: Final report exists: {os.path.exists(args.final_report)}")

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
