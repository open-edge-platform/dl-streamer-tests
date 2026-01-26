import re
import sys
import os
import argparse

def extract_pipeline_and_fps(filename):
    """Extract pipeline, FPS, and initial FPS from logs"""
    try:
        with open(filename, 'r') as f:
            content = f.read()
        
        lines = content.split('\n')
        pipeline = None
        fps = None
        initial_fps = None
        
        # Extract initial FPS
        for line in lines:
            if 'Initial pipeline FPS:' in line:
                initial_match = re.search(r'Initial pipeline FPS: ([\d.]+)', line)
                if initial_match:
                    initial_fps = float(initial_match.group(1))
                    print(f"DEBUG: Found Initial FPS: {initial_fps}")  # Debug print
                break
        
        # Extract best pipeline and FPS
        for i, line in enumerate(lines):
            if 'Best found pipeline:' in line:
                pipeline = line.split('Best found pipeline: ', 1)[1].strip()
                
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    fps_match = re.search(r'with fps: ([\d.]+)', next_line)
                    if fps_match:
                        fps = float(fps_match.group(1))
                        print(f"DEBUG: Found Best FPS: {fps}")  # Debug print
                break
        
        if initial_fps is None:
            print("DEBUG: Initial FPS not found in logs")  # Debug print
        
        return pipeline, fps, initial_fps
    except Exception as e:
        print(f"❌ Error extracting from {filename}: {e}")
        return None, None, None

def load_golden_values(golden_file):
    """Load golden values from file (line 1: pipeline, line 2: FPS)"""
    try:
        with open(golden_file, 'r') as f:
            lines = f.readlines()
        
        if len(lines) < 2:
            print(f"❌ Error: {golden_file} should have 2 lines (pipeline and FPS)")
            return None, None
        
        golden_pipeline = lines[0].strip()
        golden_fps = float(lines[1].strip())
        
        return golden_pipeline, golden_fps
    except FileNotFoundError:
        print(f"❌ Golden file {golden_file} not found")
        return None, None
    except Exception as e:
        print(f"❌ Error loading golden values from {golden_file}: {e}")
        return None, None

def compare_results(full_output_path, golden_path, fps_tolerance=0.01, output_dir="."):
    """Compare current results with golden values"""
    
    print(f"Extracting current results from: {full_output_path}")
    current_pipeline, current_fps, initial_fps = extract_pipeline_and_fps(full_output_path)
    
    if not current_pipeline or current_fps is None:
        print("❌ Failed to extract current results")
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
    
    # Check if current FPS >= initial FPS (optimization improvement)
    initial_fps_check = True  # Default to True if no initial FPS found
    show_optimization_check = False
    
    if initial_fps is not None:
        show_optimization_check = True
        initial_fps_check = current_fps >= initial_fps
    
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
    
    args = parser.parse_args()
    
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
