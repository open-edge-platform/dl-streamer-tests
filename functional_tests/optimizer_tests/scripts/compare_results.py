import re
import sys
import os
import argparse
import json

def normalize_pipeline_for_comparison(pipeline):
    """Normalize pipeline by removing model paths for comparison"""
    if not pipeline:
        return pipeline
    
    print(f"DEBUG: Original pipeline: {pipeline}")
    
    # Replace model paths with normalized placeholder
    # Pattern matches: model=/any/path/to/model.xml
    normalized = re.sub(r'model=[^\s!]+/([^/\s!]+\.xml)', r'model=MODEL_PATH/\1', pipeline)
    
    # Also handle cases where model path might be quoted
    normalized = re.sub(r'model="[^"]+/([^"/]+\.xml)"', r'model="MODEL_PATH/\1"', normalized)
    normalized = re.sub(r"model='[^']+/([^'/]+\.xml)'", r"model='MODEL_PATH/\1'", normalized)
    
    print(f"DEBUG: Normalized pipeline: {normalized}")
    
    return normalized

def extract_pipeline_and_fps(filename):
    """Extract pipeline, FPS, and initial FPS from logs"""
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
        
        # Debug: Show first 10 and last 10 lines
        print("DEBUG: First 10 lines:")
        for i, line in enumerate(lines[:10]):
            print(f"  {i+1}: {repr(line)}")
        
        print("DEBUG: Last 10 lines:")
        for i, line in enumerate(lines[-10:]):
            print(f"  {len(lines)-10+i+1}: {repr(line)}")
        
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
        
        if initial_fps is None:
            print("DEBUG: Initial FPS not found, searching for any FPS pattern...")
            for line_num, line in enumerate(lines[:50]):  # Check first 50 lines
                if 'fps' in line.lower() or 'FPS' in line:
                    print(f"DEBUG: Found FPS-related line {line_num+1}: {repr(line)}")
        
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
        
        if pipeline is None:
            print("DEBUG: Best pipeline not found, searching for any pipeline pattern...")
            for line_num, line in enumerate(lines):
                if 'pipeline' in line.lower() and ('!' in line or 'gst' in line.lower()):
                    print(f"DEBUG: Found pipeline-like line {line_num+1}: {repr(line)}")
        
        if fps is None:
            print("DEBUG: Best FPS not found, searching for any FPS pattern in entire file...")
            for line_num, line in enumerate(lines):
                if re.search(r'(\d+\.?\d*)\s*(fps|FPS)', line):
                    print(f"DEBUG: Found FPS-like line {line_num+1}: {repr(line)}")
        
        # Summary
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
        if 'pipeline' not in test_data or 'fps' not in test_data:
            print(f"❌ Test data missing required fields (pipeline, fps)")
            print(f"Available fields: {list(test_data.keys())}")
            return None, None, None
        
        golden_pipeline = test_data['pipeline']
        golden_fps = float(test_data['fps'])
        
        # Get tolerance if specified
        tolerance = test_data.get('tolerance', None)
        
        print(f"DEBUG: Golden pipeline: {golden_pipeline[:100]}{'...' if len(golden_pipeline) > 100 else ''}")
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
        
        if len(lines) < 2:
            print(f"❌ Error: {golden_file} should have 2 lines (pipeline and FPS)")
            return None, None, None
        
        golden_pipeline = lines[0].strip()
        golden_fps = float(lines[1].strip())
        
        print(f"DEBUG: Golden pipeline: {golden_pipeline[:100]}{'...' if len(golden_pipeline) > 100 else ''}")
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

def compare_results(full_output_path, golden_path, test_name=None, fps_tolerance=1, output_dir=".", ignore_model_paths=True):
    """Compare current results with golden values"""
    
    print(f"DEBUG: Starting comparison")
    print(f"DEBUG: Full output path: {full_output_path}")
    print(f"DEBUG: Golden path: {golden_path}")
    print(f"DEBUG: Test name: {test_name}")
    print(f"DEBUG: FPS tolerance: {fps_tolerance}")
    print(f"DEBUG: Output directory: {output_dir}")
    print(f"DEBUG: Ignore model paths: {ignore_model_paths}")
    
    print(f"Extracting current results from: {full_output_path}")
    current_pipeline, current_fps, initial_fps = extract_pipeline_and_fps(full_output_path)
    
    print(f"DEBUG: Extraction results:")
    print(f"  current_pipeline: {current_pipeline is not None}")
    print(f"  current_fps: {current_fps}")
    print(f"  initial_fps: {initial_fps}")
    
    if not current_pipeline or current_fps is None:
        print("❌ Failed to extract current results")
        print("DEBUG: Extraction failed - showing file content sample...")
        try:
            with open(full_output_path, 'r') as f:
                content = f.read()
                print(f"DEBUG: File size: {len(content)} characters")
                print("DEBUG: File content (first 1000 chars):")
                print(content[:1000])
                print("DEBUG: File content (last 1000 chars):")
                print(content[-1000:])
        except Exception as e:
            print(f"DEBUG: Could not read file for debugging: {e}")
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
    
    if not golden_pipeline or golden_fps is None:
        print("❌ Failed to load golden values")
        return False
    
    # Normalize pipelines for comparison if ignore_model_paths is True
    if ignore_model_paths:
        print("DEBUG: Normalizing pipelines (ignoring model paths)")
        current_pipeline_normalized = normalize_pipeline_for_comparison(current_pipeline)
        golden_pipeline_normalized = normalize_pipeline_for_comparison(golden_pipeline)
        
        pipeline_match = current_pipeline_normalized.strip() == golden_pipeline_normalized.strip()
        
        print(f"DEBUG: Pipeline comparison (normalized):")
        print(f"  Golden normalized:  {golden_pipeline_normalized}")
        print(f"  Current normalized: {current_pipeline_normalized}")
    else:
        print("DEBUG: Comparing pipelines exactly (including model paths)")
        pipeline_match = current_pipeline.strip() == golden_pipeline.strip()
        
        print(f"DEBUG: Pipeline comparison (exact):")
        print(f"  Golden:  {golden_pipeline}")
        print(f"  Current: {current_pipeline}")
    
    fps_diff = abs(current_fps - golden_fps)
    fps_match = fps_diff < fps_tolerance
    
    print(f"DEBUG: Comparison details:")
    print(f"  Pipeline match: {pipeline_match}")
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
    
    print(f"PIPELINE:")
    print(f"  Golden:  {golden_pipeline}")
    print(f"  Current: {current_pipeline}")
    if ignore_model_paths:
        print(f"  Note: Model paths ignored in comparison")
    print(f"  Match:   {'✅ PASS' if pipeline_match else '❌ FAIL'}")
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
        overall_match = pipeline_match and fps_match and initial_fps_check
    else:
        overall_match = pipeline_match and fps_match
        print("DEBUG: No initial FPS found - optimization check excluded from overall result")
    
    print(f"OVERALL RESULT: {'✅ PASS' if overall_match else '❌ FAIL'}")
    print("="*80)
    
    # Save current results for debugging
    test_suffix = f"_{test_name}" if test_name else ""
    current_values_path = os.path.join(output_dir, f'current_values{test_suffix}.txt')
    try:
        with open(current_values_path, 'w') as f:
            f.write(f"{current_pipeline}\n")
            f.write(f"{current_fps}\n")
            if initial_fps is not None:
                f.write(f"{initial_fps}\n")
        print(f"Current values saved to: {current_values_path}")
    except Exception as e:
        print(f"Warning: Could not save current values: {e}")
    
    # Save comparison report
    report_path = os.path.join(output_dir, f'comparison_report{test_suffix}.txt')
    try:
        with open(report_path, 'w') as f:
            f.write("COMPARISON REPORT\n")
            f.write("="*50 + "\n\n")
            if test_name:
                f.write(f"Test name: {test_name}\n")
            f.write(f"Golden file: {golden_path}\n")
            f.write(f"Full output file: {full_output_path}\n")
            f.write(f"FPS tolerance: {fps_tolerance}\n")
            f.write(f"Ignore model paths: {ignore_model_paths}\n\n")
            f.write(f"Pipeline Match: {'PASS' if pipeline_match else 'FAIL'}\n")
            f.write(f"FPS Match: {'PASS' if fps_match else 'FAIL'}\n")
            if show_optimization_check:
                f.write(f"Optimization Check: {'PASS' if initial_fps_check else 'FAIL'}\n")
            else:
                f.write(f"Optimization Check: SKIP (no initial FPS)\n")
            f.write(f"Overall: {'PASS' if overall_match else 'FAIL'}\n\n")
            f.write("GOLDEN VALUES:\n")
            f.write(f"Pipeline: {golden_pipeline}\n")
            f.write(f"FPS: {golden_fps}\n\n")
            f.write("CURRENT VALUES:\n")
            f.write(f"Pipeline: {current_pipeline}\n")
            f.write(f"FPS: {current_fps}\n")
            if initial_fps is not None:
                f.write(f"Initial FPS: {initial_fps}\n")
                f.write(f"\nFPS Difference (vs Golden): {fps_diff:.6f}\n")
                f.write(f"FPS Difference (vs Initial): {current_fps - initial_fps:.6f}\n")
                improvement = ((current_fps - initial_fps) / initial_fps) * 100 if initial_fps > 0 else 0
                f.write(f"Optimization Improvement: {improvement:.2f}%\n")
            else:
                f.write(f"Initial FPS: Not found\n")
                f.write(f"\nFPS Difference (vs Golden): {fps_diff:.6f}\n")
        print(f"Comparison report saved to: {report_path}")
    except Exception as e:
        print(f"Warning: Could not save report: {e}")
    
    return overall_match

def main():
    parser = argparse.ArgumentParser(description='Compare optimizer results with golden values')
    parser.add_argument('--full-output', '-f', required=True, 
                       help='Path to full_output.txt file')
    parser.add_argument('--golden', '-g', required=True,
                       help='Path to golden values file (.txt or .json)')
    parser.add_argument('--test-name', '-n', 
                       help='Test name (required for JSON golden files)')
    parser.add_argument('--tolerance', '-t', type=float, default=0.01,
                       help='FPS tolerance for comparison (default: 0.01)')
    parser.add_argument('--output-dir', '-o', default='.',
                       help='Directory to save output files (default: current directory)')
    parser.add_argument('--ignore-model-paths', action='store_true', default=True,
                       help='Ignore model paths when comparing pipelines (default: True)')
    parser.add_argument('--exact-match', action='store_true',
                       help='Require exact pipeline match including model paths')
    parser.add_argument('--debug', '-d', action='store_true',
                       help='Enable extra debug output')
    
    args = parser.parse_args()
    
    if args.debug:
        print("DEBUG: Debug mode enabled")
    
    # Handle exact match flag
    ignore_model_paths = not args.exact_match
    
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
    
    # Create output directory if it doesn't exist
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    print(f"Comparing results...")
    print(f"Full output: {args.full_output}")
    print(f"Golden file: {args.golden}")
    if args.test_name:
        print(f"Test name: {args.test_name}")
    print(f"FPS tolerance: {args.tolerance}")
    print(f"Output directory: {args.output_dir}")
    print(f"Ignore model paths: {ignore_model_paths}")
    print()
    
    # Run comparison
    success = compare_results(args.full_output, args.golden, args.test_name, args.tolerance, args.output_dir, ignore_model_paths)
    
    # Exit with appropriate code for CI
    if success:
        print("\n🎉 All tests PASSED")
        sys.exit(0)
    else:
        print("\n💥 Tests FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
