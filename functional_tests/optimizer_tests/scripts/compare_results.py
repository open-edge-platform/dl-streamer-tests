import re
import sys
import os
import argparse
import json
from datetime import datetime

def extract_pipeline_and_fps(filename):
    """Extract pipeline, FPS and initial FPS from logs"""
    print(f"DEBUG: Starting extraction from file: {filename}")
    
    try:
        with open(filename, 'r') as f:
            content = f.read()
        
        print(f"DEBUG: File read successfully, content length: {len(content)} characters")
        
        lines = content.split('\n')
        print(f"DEBUG: Split into {len(lines)} lines")
        
        pipeline = None
        fps = None
        initial_fps = None
        
        # Extract initial FPS
        print("DEBUG: Searching for Initial FPS...")
        initial_fps_patterns = [
            'Initial pipeline FPS:',
            'Original pipeline FPS:',
            'Baseline FPS:',
            'Starting FPS:'
        ]
        
        for line_num, line in enumerate(lines):
            for pattern in initial_fps_patterns:
                if pattern in line:
                    print(f"DEBUG: Found pattern '{pattern}' in line {line_num+1}: {repr(line)}")
                    initial_match = re.search(r'FPS:\s*([\d.]+)', line)
                    if initial_match:
                        initial_fps = float(initial_match.group(1))
                        print(f"DEBUG: Extracted Initial FPS: {initial_fps}")
                        break
            if initial_fps is not None:
                break
        
        # Extract best pipeline and FPS
        print("DEBUG: Searching for Best pipeline...")
        best_pipeline_patterns = [
            'Best found pipeline:',
            'Optimized pipeline:',
            'Final pipeline:',
            'Best pipeline:'
        ]
        
        for line_num, line in enumerate(lines):
            for pattern in best_pipeline_patterns:
                if pattern in line:
                    print(f"DEBUG: Found pattern '{pattern}' in line {line_num+1}: {repr(line)}")
                    pipeline = line.split(pattern, 1)[1].strip()
                    print(f"DEBUG: Extracted pipeline: {repr(pipeline)}")
                    
                    # Look for FPS in next few lines
                    for next_line_offset in range(1, 5):  # Check next 4 lines
                        if line_num + next_line_offset < len(lines):
                            next_line = lines[line_num + next_line_offset]
                            print(f"DEBUG: Checking line {line_num + next_line_offset + 1} for FPS: {repr(next_line)}")
                            
                            fps_patterns = [
                                r'with fps:\s*([\d.]+)',
                                r'FPS:\s*([\d.]+)',
                                r'fps:\s*([\d.]+)',
                                r'(\d+\.?\d*)\s*fps'
                            ]
                            
                            for fps_pattern in fps_patterns:
                                fps_match = re.search(fps_pattern, next_line, re.IGNORECASE)
                                if fps_match:
                                    fps = float(fps_match.group(1))
                                    print(f"DEBUG: Found Best FPS with pattern '{fps_pattern}': {fps}")
                                    break
                            
                            if fps is not None:
                                break
                    break
            if pipeline is not None:
                break
        
        print("DEBUG: Extraction summary:")
        print(f"  Pipeline found: {pipeline is not None}")
        print(f"  Best FPS found: {fps is not None}")
        print(f"  Initial FPS found: {initial_fps is not None}")
        
        if pipeline:
            print(f"  Pipeline: {pipeline[:100]}{'...' if len(pipeline) > 100 else ''}")
        if fps:
            print(f"  Best FPS: {fps}")
        if initial_fps:
            print(f"  Initial FPS: {initial_fps}")
        
        return pipeline, fps, initial_fps
        
    except FileNotFoundError:
        print(f"DEBUG: File not found: {filename}")
        return None, None, None
    except Exception as e:
        print(f"DEBUG: Exception during extraction: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def load_golden_values_json(golden_file, test_path):
    """Load golden values from JSON file using dot notation path"""
    print(f"DEBUG: Loading golden values from JSON: {golden_file}")
    print(f"DEBUG: Looking for test path: {test_path}")
    
    try:
        with open(golden_file, 'r') as f:
            golden_data = json.load(f)
        
        print(f"DEBUG: JSON loaded successfully")
        
        # Navigate through nested structure using dot notation
        current_data = golden_data
        path_parts = test_path.split('.')
        
        print(f"DEBUG: Navigating path: {path_parts}")
        
        for i, part in enumerate(path_parts):
            if part not in current_data:
                print(f"❌ Path part '{part}' not found at level {i}")
                print(f"Available keys at this level: {list(current_data.keys())}")
                return None, None, None
            current_data = current_data[part]
            print(f"DEBUG: Found '{part}', continuing...")
        
        test_data = current_data
        print(f"DEBUG: Final test data: {test_data}")
        
        # Validate test data structure
        if 'fps' not in test_data:
            print(f"❌ Test data missing required field (fps)")
            print(f"Available fields: {list(test_data.keys())}")
            return None, None, None
        
        golden_pipeline = test_data.get('pipeline', 'N/A')  # Pipeline is optional for info only
        golden_fps = float(test_data['fps'])
        
        # Get tolerance if specified
        tolerance = test_data.get('tolerance', None)
        
        print(f"DEBUG: Golden pipeline: {golden_pipeline[:100] if golden_pipeline != 'N/A' else 'N/A'}{'...' if golden_pipeline != 'N/A' and len(golden_pipeline) > 100 else ''}")
        print(f"DEBUG: Golden FPS: {golden_fps}")
        if tolerance:
            print(f"DEBUG: Custom tolerance: {tolerance}")
        
        return golden_pipeline, golden_fps, tolerance
        
    except FileNotFoundError:
        print(f"❌ Golden JSON file {golden_file} not found")
        return None, None, None
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing JSON file {golden_file}: {e}")
        return None, None, None
    except Exception as e:
        print(f"❌ Error loading golden values from {golden_file}: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def load_golden_values_txt(golden_file):
    """Load golden values from text file (line 1: pipeline, line 2: FPS)"""
    print(f"DEBUG: Loading golden values from text file: {golden_file}")
    
    try:
        with open(golden_file, 'r') as f:
            lines = f.readlines()
        
        print(f"DEBUG: Golden file has {len(lines)} lines")
        for i, line in enumerate(lines):
            print(f"DEBUG: Golden line {i+1}: {repr(line)}")
        
        if len(lines) < 1:
            print(f"❌ Error: {golden_file} should have at least 1 line (FPS)")
            return None, None, None
        
        # Try to get pipeline from first line if it looks like a pipeline, otherwise assume FPS only
        if len(lines) >= 2 and ('!' in lines[0] or 'gst' in lines[0].lower()):
            golden_pipeline = lines[0].strip()
            golden_fps = float(lines[1].strip())
        else:
            golden_pipeline = 'N/A'
            golden_fps = float(lines[0].strip())
        
        print(f"DEBUG: Golden pipeline: {golden_pipeline[:100] if golden_pipeline != 'N/A' else 'N/A'}{'...' if golden_pipeline != 'N/A' and len(golden_pipeline) > 100 else ''}")
        print(f"DEBUG: Golden FPS: {golden_fps}")
        
        return golden_pipeline, golden_fps, None
    except FileNotFoundError:
        print(f"❌ Golden file {golden_file} not found")
        return None, None, None
    except Exception as e:
        print(f"❌ Error loading golden values from {golden_file}: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def append_to_final_report(final_report_path, test_name, test_result):
    """Append test result to final report file"""
    try:
        # Create final report if it doesn't exist
        if not os.path.exists(final_report_path):
            with open(final_report_path, 'w') as f:
                f.write("="*80 + "\n")
                f.write("OPTIMIZER TESTS - FINAL REPORT\n")
                f.write("="*80 + "\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("="*80 + "\n\n")
        
        # Append test result
        with open(final_report_path, 'a') as f:
            f.write(f"TEST: {test_name}\n")
            f.write("-" * 40 + "\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Status: {test_result['status']}\n")
            f.write("\n")
            
            # Pipeline information (for reference only)
            f.write("PIPELINE INFORMATION:\n")
            f.write(f"Golden Pipeline: {test_result['golden_pipeline']}\n")
            f.write(f"Current Pipeline: {test_result['current_pipeline']}\n")
            f.write("\n")
            
            # FPS comparison
            f.write("FPS COMPARISON:\n")
            f.write(f"Golden FPS: {test_result['golden_fps']}\n")
            f.write(f"Current FPS: {test_result['current_fps']}\n")
            if test_result['initial_fps'] is not None:
                f.write(f"Initial FPS: {test_result['initial_fps']}\n")
                improvement = ((test_result['current_fps'] - test_result['initial_fps']) / test_result['initial_fps']) * 100 if test_result['initial_fps'] > 0 else 0
                f.write(f"Optimization: {improvement:.2f}%\n")
            f.write(f"FPS Difference: {test_result['fps_diff']:.6f}\n")
            f.write(f"FPS Tolerance: {test_result['tolerance']}\n")
            f.write(f"FPS Match: {'PASS' if test_result['fps_match'] else 'FAIL'}\n")
            if test_result['initial_fps'] is not None:
                f.write(f"Optimization Check: {'PASS' if test_result['optimization_check'] else 'FAIL'}\n")
            else:
                f.write(f"Optimization Check: SKIP (no initial FPS)\n")
            f.write(f"Overall Result: {test_result['status']}\n")
            f.write("\n" + "="*80 + "\n\n")
        
        print(f"Test result appended to final report: {final_report_path}")
        
    except Exception as e:
        print(f"Warning: Could not append to final report: {e}")

def compare_results(full_output_path, golden_path, test_name=None, fps_tolerance=1, final_report_path=None):
    """Compare current results with golden values and append to final report"""
    
    print(f"DEBUG: Starting comparison")
    print(f"DEBUG: Full output path: {full_output_path}")
    print(f"DEBUG: Golden path: {golden_path}")
    print(f"DEBUG: Test name: {test_name}")
    print(f"DEBUG: FPS tolerance: {fps_tolerance}")
    print(f"DEBUG: Final report path: {final_report_path}")
    
    print(f"Extracting current results from: {full_output_path}")
    current_pipeline, current_fps, initial_fps = extract_pipeline_and_fps(full_output_path)
    
    print(f"DEBUG: Extraction results:")
    print(f"  current_pipeline: {current_pipeline is not None}")
    print(f"  current_fps: {current_fps}")
    print(f"  initial_fps: {initial_fps}")
    
    if current_fps is None:
        print("❌ Failed to extract current FPS")
        
        # Still append failure to final report
        if final_report_path:
            test_result = {
                'status': 'FAIL - NO FPS EXTRACTED',
                'golden_pipeline': 'N/A',
                'current_pipeline': current_pipeline or 'N/A',
                'golden_fps': 'N/A',
                'current_fps': 'N/A',
                'initial_fps': initial_fps,
                'fps_diff': 'N/A',
                'tolerance': fps_tolerance,
                'fps_match': False,
                'optimization_check': False
            }
            append_to_final_report(final_report_path, test_name or 'UNKNOWN', test_result)
        
        return False
    
    print(f"Loading golden values from: {golden_path}")
    
    # Determine if golden file is JSON or text based on extension
    if golden_path.lower().endswith('.json'):
        if test_name is None:
            print("❌ Test name is required when using JSON golden file")
            return False
        golden_pipeline, golden_fps, custom_tolerance = load_golden_values_json(golden_path, test_name)
        
        # Use custom tolerance if specified in JSON
        if custom_tolerance is not None:
            fps_tolerance = custom_tolerance
            print(f"DEBUG: Using custom tolerance from JSON: {fps_tolerance}")
    else:
        golden_pipeline, golden_fps, _ = load_golden_values_txt(golden_path)
    
    if golden_fps is None:
        print("❌ Failed to load golden FPS")
        
        # Still append failure to final report
        if final_report_path:
            test_result = {
                'status': 'FAIL - NO GOLDEN FPS',
                'golden_pipeline': golden_pipeline or 'N/A',
                'current_pipeline': current_pipeline or 'N/A',
                'golden_fps': 'N/A',
                'current_fps': current_fps,
                'initial_fps': initial_fps,
                'fps_diff': 'N/A',
                'tolerance': fps_tolerance,
                'fps_match': False,
                'optimization_check': False
            }
            append_to_final_report(final_report_path, test_name or 'UNKNOWN', test_result)
        
        return False
    
    fps_diff = abs(current_fps - golden_fps)
    fps_match = fps_diff < fps_tolerance
    
    print(f"DEBUG: Comparison details:")
    print(f"  FPS diff: {fps_diff}")
    print(f"  FPS match: {fps_match}")
    
    initial_fps_check = True  # Default to True if no initial FPS found
    show_optimization_check = False
    
    if initial_fps is not None:
        show_optimization_check = True
        initial_fps_check = current_fps >= initial_fps
        print(f"DEBUG: Optimization check: current({current_fps}) >= initial({initial_fps}) = {initial_fps_check}")
    else:
        print(f"DEBUG: No initial FPS found - optimization check will be skipped")
    
    print("="*80)
    print("COMPARISON RESULTS")
    if test_name:
        print(f"Test: {test_name}")
    print("="*80)
    
    print(f"PIPELINE INFORMATION:")
    print(f"  Golden:  {golden_pipeline}")
    print(f"  Current: {current_pipeline}")
    print(f"  Note: Pipelines shown for information only (not compared)")
    print()
    
    print(f"FPS:")
    print(f"  Golden:  {golden_fps}")
    print(f"  Current: {current_fps}")
    print(f"  Diff:    {fps_diff:.6f}")
    print(f"  Tolerance: {fps_tolerance}")
    print(f"  Match:   {'✅ PASS' if fps_match else '❌ FAIL'}")
    print()
    
    # Always show optimization check if we have initial FPS
    if show_optimization_check:
        print(f"OPTIMIZATION CHECK:")
        print(f"  Initial: {initial_fps}")
        print(f"  Current: {current_fps}")
        
        if initial_fps_check:
            improvement = ((current_fps - initial_fps) / initial_fps) * 100 if initial_fps > 0 else 0
            print(f"  Check:   ✅ PASS (improved by {improvement:.2f}%)")
        else:
            degradation = ((initial_fps - current_fps) / initial_fps) * 100 if initial_fps > 0 else 0
            print(f"  Check:   ❌ FAIL (degraded by {degradation:.2f}%)")
        print()
    else:
        print(f"OPTIMIZATION CHECK:")
        print(f"  Check:   ⚠️  SKIP (Initial FPS not found in logs)")
        print()
    
    if show_optimization_check:
        overall_match = fps_match and initial_fps_check
    else:
        overall_match = fps_match
        print("DEBUG: No initial FPS found - optimization check excluded from overall result")
    
    print(f"OVERALL RESULT: {'✅ PASS' if overall_match else '❌ FAIL'}")
    print("="*80)
    
    # Prepare test result for final report
    test_result = {
        'status': 'PASS' if overall_match else 'FAIL',
        'golden_pipeline': golden_pipeline or 'N/A',
        'current_pipeline': current_pipeline or 'N/A',
        'golden_fps': golden_fps,
        'current_fps': current_fps,
        'initial_fps': initial_fps,
        'fps_diff': fps_diff,
        'tolerance': fps_tolerance,
        'fps_match': fps_match,
        'optimization_check': initial_fps_check if show_optimization_check else None
    }
    
    # Append to final report
    if final_report_path:
        append_to_final_report(final_report_path, test_name or 'UNKNOWN', test_result)
    
    return overall_match

def finalize_final_report(final_report_path, total_tests, passed_tests, failed_tests):
    """Add final summary to final report"""
    try:
        if not os.path.exists(final_report_path):
            print(f"Warning: Final report file does not exist: {final_report_path}")
            return
        
        with open(final_report_path, 'a') as f:
            f.write("="*80 + "\n")
            f.write("FINAL SUMMARY\n")
            f.write("="*80 + "\n")
            f.write(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Tests: {total_tests}\n")
            f.write(f"Passed: {passed_tests}\n")
            f.write(f"Failed: {failed_tests}\n")
            f.write(f"Success Rate: {(passed_tests * 100 // total_tests) if total_tests > 0 else 0}%\n")
            f.write(f"Final Status: {'✅ ALL TESTS PASSED' if failed_tests == 0 else '❌ SOME TESTS FAILED'}\n")
            f.write("="*80 + "\n")
        
        print(f"Final summary added to final report: {final_report_path}")
        
    except Exception as e:
        print(f"Warning: Could not finalize final report: {e}")

def main():
    parser = argparse.ArgumentParser(description='Compare optimizer FPS results with golden values')
    parser.add_argument('--full-output', '-f', required=True, 
                       help='Path to full_output.txt file')
    parser.add_argument('--golden', '-g', required=True,
                       help='Path to golden values file (.txt or .json)')
    parser.add_argument('--test-name', '-n', 
                       help='Test name (required for JSON golden files)')
    parser.add_argument('--tolerance', '-t', type=float, default=0.01,
                       help='FPS tolerance for comparison (default: 0.01)')
    parser.add_argument('--final-report', '-r',
                       help='Path to final report file (will be created/appended)')
    parser.add_argument('--debug', '-d', action='store_true',
                       help='Enable extra debug output')
    
    args = parser.parse_args()
    
    if args.debug:
        print("DEBUG: Debug mode enabled")
    
    # Check if files exist
    if not os.path.exists(args.full_output):
        print(f"❌ Full output file not found: {args.full_output}")
        sys.exit(1)
    
    if not os.path.exists(args.golden):
        print(f"❌ Golden file not found: {args.golden}")
        sys.exit(1)
    
    # Check if test name is provided for JSON files
    if args.golden.lower().endswith('.json') and not args.test_name:
        print("❌ Test name (--test-name) is required when using JSON golden file")
        sys.exit(1)
    
    print(f"Comparing FPS results...")
    print(f"Full output: {args.full_output}")
    print(f"Golden file: {args.golden}")
    if args.test_name:
        print(f"Test name: {args.test_name}")
    print(f"FPS tolerance: {args.tolerance}")
    if args.final_report:
        print(f"Final report: {args.final_report}")
    print()
    
    # Run comparison
    success = compare_results(args.full_output, args.golden, args.test_name, args.tolerance, args.final_report)
    
    # Exit with appropriate code for CI
    if success:
        print("\n🎉 Test PASSED")
        sys.exit(0)
    else:
        print("\n💥 Test FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
