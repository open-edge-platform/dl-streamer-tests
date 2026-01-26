import re
import sys
import os
import argparse

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

def load_golden_values(golden_file):
    """Load golden values from file (line 1: pipeline, line 2: FPS)"""
    print(f"DEBUG: Loading golden values from: {golden_file}")
    
    try:
        with open(golden_file, 'r') as f:
            lines = f.readlines()
        
        print(f"DEBUG: Golden file has {len(lines)} lines")
        for i, line in enumerate(lines):
            print(f"DEBUG: Golden line {i+1}: {repr(line)}")
        
        if len(lines) < 2:
            print(f"❌ Error: {golden_file} should have 2 lines (pipeline and FPS)")
            return None, None
        
        golden_pipeline = lines[0].strip()
        golden_fps = float(lines[1].strip())
        
        print(f"DEBUG: Golden pipeline: {golden_pipeline[:100]}{'...' if len(golden_pipeline) > 100 else ''}")
        print(f"DEBUG: Golden FPS: {golden_fps}")
        
        return golden_pipeline, golden_fps
    except FileNotFoundError:
        print(f"❌ Golden file {golden_file} not found")
        return None, None
    except Exception as e:
        print(f"❌ Error loading golden values from {golden_file}: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def compare_results(full_output_path, golden_path, fps_tolerance=1, output_dir="."):
    """Compare current results with golden values"""
    
    print(f"DEBUG: Starting comparison")
    print(f"DEBUG: Full output path: {full_output_path}")
    print(f"DEBUG: Golden path: {golden_path}")
    print(f"DEBUG: FPS tolerance: {fps_tolerance}")
    print(f"DEBUG: Output directory: {output_dir}")
    
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
    golden_pipeline, golden_fps = load_golden_values(golden_path)
    
    if not golden_pipeline or golden_fps is None:
        print("❌ Failed to load golden values")
        return False
    
    # Compare pipeline and FPS
    pipeline_match = current_pipeline.strip() == golden_pipeline.strip()
    fps_diff = abs(current_fps - golden_fps)
    fps_match = fps_diff < fps_tolerance
    
    print(f"DEBUG: Comparison details:")
    print(f"  Pipeline match: {pipeline_match}")
    print(f"  FPS diff: {fps_diff}")
    print(f"  FPS match: {fps_match}")
    
    # Check if current FPS >= initial FPS (optimization improvement)
    initial_fps_check = True  # Default to True if no initial FPS found
    show_optimization_check = False
    
    if initial_fps is not None:
        show_optimization_check = True
        initial_fps_check = current_fps >= initial_fps
        print(f"DEBUG: Optimization check: current({current_fps}) >= initial({initial_fps}) = {initial_fps_check}")
    
    print("="*80)
    print("COMPARISON RESULTS")
    print("="*80)
    
    print(f"PIPELINE:")
    print(f"  Golden:  {golden_pipeline}")
    print(f"  Current: {current_pipeline}")
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
    
    # Overall result includes all checks
    overall_match = pipeline_match and fps_match and initial_fps_check
    print(f"OVERALL RESULT: {'✅ PASS' if overall_match else '❌ FAIL'}")
    print("="*80)
    
    # Save current results for debugging
    current_values_path = os.path.join(output_dir, 'current_values.txt')
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
    report_path = os.path.join(output_dir, 'comparison_report.txt')
    try:
        with open(report_path, 'w') as f:
            f.write("COMPARISON REPORT\n")
            f.write("="*50 + "\n\n")
            f.write(f"Golden file: {golden_path}\n")
            f.write(f"Full output file: {full_output_path}\n")
            f.write(f"FPS tolerance: {fps_tolerance}\n\n")
            f.write(f"Pipeline Match: {'PASS' if pipeline_match else 'FAIL'}\n")
            f.write(f"FPS Match: {'PASS' if fps_match else 'FAIL'}\n")
            f.write(f"Optimization Check: {'PASS' if initial_fps_check else 'FAIL'}\n")
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
                       help='Path to golden_values.txt file')
    parser.add_argument('--tolerance', '-t', type=float, default=0.01,
                       help='FPS tolerance for comparison (default: 0.01)')
    parser.add_argument('--output-dir', '-o', default='.',
                       help='Directory to save output files (default: current directory)')
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
    
    # Create output directory if it doesn't exist
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    print(f"Comparing results...")
    print(f"Full output: {args.full_output}")
    print(f"Golden file: {args.golden}")
    print(f"FPS tolerance: {args.tolerance}")
    print(f"Output directory: {args.output_dir}")
    print()
    
    # Run comparison
    success = compare_results(args.full_output, args.golden, args.tolerance, args.output_dir)
    
    # Exit with appropriate code for CI
    if success:
        print("\n🎉 All tests PASSED")
        sys.exit(0)
    else:
        print("\n💥 Tests FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
