#!/bin/bash

# =============================================================================
# Universal Pipeline Test Script with Final Report
# Host: dlstreamer-test-repo/functional_tests/optimizer/tests/scripts/
# Docker: runs with mounted volumes
# =============================================================================

set -e
while [[ $# -gt 0 ]]; do
    case $1 in
        --results-dir)
            CUSTOM_RESULTS_DIR="$2"
            shift 2
            ;;
        --search-duration)
            SEARCH_DURATION="$2"
            shift 2
            ;;
        --tolerance)
            CUSTOM_TOLERANCE="$2"
            shift 2
            ;;
        --models-path)
            MODELS_PATH="$2"
            shift 2
            ;;
        --golden-file)
            GOLDEN_FILE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --results-dir PATH        Directory for test results"
            echo "  --search-duration SECONDS Duration for optimizer search (default: 300 for Docker, 30 for Host)"
            echo "  --tolerance PERCENT       Tolerance percentage for comparisons (default: 5.0)"
            echo "  --models-path PATH        Path to models directory"
            echo "  --golden-file PATH        Path to golden values JSON file"
            echo "  -h, --help               Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --results-dir /tmp/my_results --tolerance 10.0"
            echo "  $0 --search-duration 120 --tolerance 3.5"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# =============================================================================
# Auto-detect environment and set paths
# =============================================================================

if [ -f /.dockerenv ]; then
    RUNNING_IN_DOCKER=true
    ENV_PREFIX="[DOCKER]"
    
    # Docker paths
    SEARCH_DURATION=${SEARCH_DURATION:-300}
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-${RESULTS_DIR:-/workspace/optimizer_results}}
    MODELS_PATH=${MODELS_PATH:-/home/dlstreamer/models}
    GOLDEN_FILE=${GOLDEN_FILE:-/workspace/goldens/golden_values.json}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-/workspace/test_scripts/compare_results.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/home/dlstreamer/dlstreamer/scripts/optimizer}
    TOLERANCE=${CUSTOM_TOLERANCE:-5.0}
else
    RUNNING_IN_DOCKER=false
    ENV_PREFIX="[HOST]"
    
    # Host paths (relative to dlstreamer-test-repo)
    SEARCH_DURATION=${SEARCH_DURATION:-30}
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-${RESULTS_DIR:-/home/runner/dlstreamer/tests/functional_tests/optimizer_tests/optimizer_results}}
    MODELS_PATH=${MODELS_PATH:-/home/runner/models}
    GOLDEN_FILE=${GOLDEN_FILE:-/home/runner/dlstreamer/tests/functional_tests/optimizer_tests/goldens/golden_values.json}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-/home/runner/dlstreamer/tests/functional_tests/optimizer_tests/scripts/compare_results.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}
    TOLERANCE=${CUSTOM_TOLERANCE:-5.0}
    
    #set envs
    export LIBVA_DRIVER_NAME=iHD
    export GST_VA_ALL_DRIVERS=1
    export LIBVA_DRIVERS_PATH=/usr/lib/x86_64-linux-gnu/dri
    export TERM=xterm
    export GST_PLUGIN_PATH=/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0:/opt/intel/dlstreamer/gstreamer/lib/
    export LD_LIBRARY_PATH=/opt/intel/dlstreamer/gstreamer/lib:/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/lib/gstreamer-1.0:/usr/lib:/opt/intel/dlstreamer/lib:/opt/opencv:/opt/openh264:/opt/rdkafka:/opt/ffmpeg:/usr/local/lib/gstreamer-1.0:/usr/local/lib
    export PYTHONPATH=/opt/intel/dlstreamer/gstreamer/lib/python3/dist-packages:/opt/intel/dlstreamer/python:/opt/intel/dlstreamer/gstreamer/lib/python3/dist-packages:
    export PATH=/home/runner/.virtualenvs/dlstreamer/bin:/opt/intel/dlstreamer/gstreamer/bin:/opt/intel/dlstreamer/bin:$PATH
    export GI_TYPELIB_PATH=/opt/intel/dlstreamer/gstreamer/lib/girepository-1.0:/usr/lib/x86_64-linux-gnu/girepository-1.0
    export LABELS_PATH=/opt/intel/dlstreamer/samples/labels
    export MODEL_PROC_PATH=/opt/intel/dlstreamer/samples/gstreamer/model_proc
    export MODEL_PROCS_PATH=/opt/intel/dlstreamer/samples/gstreamer/model_proc
    export MODELS_PATH=$MODELS_PATH
    export ZE_ENABLE_ALT_DRIVERS=libze_intel_npu.so
    export EnableDirectSubmission=0
    export NEOReadDebugKeys=1
fi

# Final report file
FINAL_REPORT="$RESULTS_DIR/FINAL_TEST_REPORT.txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info() { echo -e "${BLUE}${ENV_PREFIX} [INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}${ENV_PREFIX} [SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}${ENV_PREFIX} [ERROR]${NC} $1"; }
print_warning() { echo -e "${YELLOW}${ENV_PREFIX} [WARNING]${NC} $1"; }

# =============================================================================
# Pipeline Definitions with JSON paths
# =============================================================================

declare -A PIPELINES
declare -A TEST_PATHS

# Pipeline 1: TGL YOLO11s CPU
PIPELINES["yolo11s_cpu"]="urisourcebin buffer-size=4096 uri=https://videos.pexels.com/video-files/1192116/1192116-sd_640_360_30fps.mp4 ! decodebin ! gvadetect model=$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml device=CPU ! queue ! gvawatermark ! vah264enc ! h264parse ! mp4mux ! fakesink"
TEST_PATHS["yolo11s_cpu"]="TGL.yolo11s_cpu"

# Pipeline 2: TGL YOLO11s GPU
PIPELINES["yolo11s_gpu"]="urisourcebin buffer-size=4096 uri=https://videos.pexels.com/video-files/1192116/1192116-sd_640_360_30fps.mp4 ! decodebin ! gvadetect model=$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml device=GPU ! queue ! gvawatermark ! vah264enc ! h264parse ! mp4mux ! fakesink"
TEST_PATHS["yolo11s_gpu"]="TGL.yolo11s_gpu"

# =============================================================================
# Functions
# =============================================================================

show_environment() {
    print_info "=========================================="
    print_info "Environment: $([ "$RUNNING_IN_DOCKER" = true ] && echo "Docker Container" || echo "Host System")"
    print_info "=========================================="
    print_info "Optimizer directory: $OPTIMIZER_DIR"
    print_info "Models path: $MODELS_PATH"
    print_info "Golden file: $GOLDEN_FILE"
    print_info "Results directory: $RESULTS_DIR"
    print_info "Compare script: $COMPARE_SCRIPT"
    print_info "Search duration: ${SEARCH_DURATION}s"
    print_info "Tolerance: ${TOLERANCE}%"
    print_info "Final report: $FINAL_REPORT"
}

initialize_final_report() {
    print_info "Initializing final report..."
    
    # Remove old final report if exists
    if [ -f "$FINAL_REPORT" ]; then
        rm -f "$FINAL_REPORT"
        print_info "Removed old final report"
    fi
    
    # Create directory if needed
    mkdir -p "$(dirname "$FINAL_REPORT")"
    
    print_success "Final report will be created at: $FINAL_REPORT"
}

check_prerequisites() {
    print_info "Checking prerequisites..."
    
    # Check Python
    if ! command -v python3 >/dev/null 2>&1; then
        print_error "Python3 not found"
        exit 1
    fi
    
    # Check optimizer directory
    if [ ! -d "$OPTIMIZER_DIR" ]; then
        print_error "Optimizer directory not found: $OPTIMIZER_DIR"
        exit 1
    fi
    
    if [ ! -f "$OPTIMIZER_DIR/__main__.py" ]; then
        print_error "Optimizer __main__.py not found in: $OPTIMIZER_DIR"
        exit 1
    fi
    
    # Check compare script
    if [ ! -f "$COMPARE_SCRIPT" ]; then
        print_error "Compare script not found: $COMPARE_SCRIPT"
        exit 1
    fi
    
    # Check golden file
    if [ ! -f "$GOLDEN_FILE" ]; then
        print_error "Golden file not found: $GOLDEN_FILE"
        exit 1
    fi
    
    # Validate JSON structure
    print_info "Validating golden JSON structure..."
    
    # Create temporary validation script
    local validation_script="/tmp/validate_json_$$"
    cat > "$validation_script" << 'EOF'
import json
import sys

try:
    with open(sys.argv[1], 'r') as f:
        data = json.load(f)
    
    # Check if it's a valid structure
    if not isinstance(data, dict):
        print('ERROR: Root should be a dictionary')
        sys.exit(1)
    
    print('Golden JSON structure:')
    def print_structure(obj, indent=0):
        spaces = '  ' * indent
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, dict):
                    print(f'{spaces}{key}:')
                    print_structure(value, indent + 1)
                else:
                    print(f'{spaces}{key}: {type(value).__name__}')
        
    print_structure(data)
    print('JSON validation: OK')
    
except json.JSONDecodeError as e:
    print(f'ERROR: Invalid JSON: {e}')
    sys.exit(1)
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
EOF
    
    if python3 "$validation_script" "$GOLDEN_FILE"; then
        print_success "Golden JSON validation OK"
        rm -f "$validation_script"
    else
        print_error "Golden JSON validation failed"
        rm -f "$validation_script"
        exit 1
    fi
    
    print_success "Prerequisites OK"
}

test_pipeline() {
    local name=$1
    local pipeline=$2
    local test_path=$3
    
    print_info "Testing pipeline: $name"
    print_info "JSON test path: $test_path"
    
    local output_file="$RESULTS_DIR/${name}_full_output.txt"
    
    # Run optimizer
    print_info "Running optimizer (${SEARCH_DURATION}s search)..."
    print_info "Working directory: $OPTIMIZER_DIR"
    print_info "Pipeline: ${pipeline:0:100}..."
    
    cd "$OPTIMIZER_DIR"
    
    # Create a temporary script to run the optimizer with proper output capture
    local temp_script="$RESULTS_DIR/run_optimizer_${name}.sh"
    cat > "$temp_script" << EOF
#!/bin/bash
set -e
cd "$OPTIMIZER_DIR"
exec python3 . --search-duration "$SEARCH_DURATION" -- $pipeline
EOF
    chmod +x "$temp_script"
    
    print_info "Starting optimizer..."
    if timeout 600 bash "$temp_script" > "$output_file" 2>&1; then
        print_success "Optimizer completed for $name"
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            print_warning "Optimizer timed out for $name (600s limit)"
        else
            print_error "Optimizer failed for $name (exit code: $exit_code)"
        fi
        
        if [ -f "$output_file" ]; then
            print_info "Output file size: $(wc -l < "$output_file") lines"
            print_info "Last 20 lines of output:"
            tail -20 "$output_file"
        else
            print_error "No output file generated"
        fi
        return 1
    fi
    
    # Check if output file has content
    if [ ! -s "$output_file" ]; then
        print_error "Output file is empty: $output_file"
        return 1
    fi
    
    print_info "Output file generated: $(wc -l < "$output_file") lines"
    
    # Compare results using the JSON golden file and append to final report
    print_info "Comparing results with golden values..."
    print_info "Using golden file: $GOLDEN_FILE"
    print_info "Test path: $test_path"
    print_info "Results will be appended to final report: $FINAL_REPORT"
    
    # Run comparison with final report
    if python3 "$COMPARE_SCRIPT" \
        --full-output "$output_file" \
        --golden "$GOLDEN_FILE" \
        --test-name "$test_path" \
        --tolerance "$TOLERANCE" \
        --final-report "$FINAL_REPORT" \
        --debug; then
        print_success "Test PASSED for $name"
        return 0
    else
        print_error "Test FAILED for $name"
        return 1
    fi
}

validate_test_paths() {
    print_info "Validating test paths in golden JSON..."
    
    # Create temporary validation script
    local validation_script="/tmp/validate_paths_$$"
    cat > "$validation_script" << 'EOF'
import json
import sys

try:
    with open(sys.argv[1], 'r') as f:
        data = json.load(f)
    
    # Get test paths from command line arguments (starting from argv[2])
    test_paths = sys.argv[2:]
    
    for test_path in test_paths:
        print(f'Checking path: {test_path}')
        
        # Navigate through nested structure using dot notation
        current_data = data
        path_parts = test_path.split('.')
        
        for i, part in enumerate(path_parts):
            if part not in current_data:
                print(f'ERROR: Path part "{part}" not found at level {i}')
                print(f'Available keys at this level: {list(current_data.keys())}')
                sys.exit(1)
            current_data = current_data[part]
        
        # Check required fields
        if 'fps' not in current_data:
            print(f'ERROR: Missing "fps" field in {test_path}')
            sys.exit(1)
        
        print(f'Path validation OK: {test_path}')
        print(f'  FPS: {current_data["fps"]}')
        if 'tolerance' in current_data:
            print(f'  Tolerance: {current_data["tolerance"]}')
        print()
    
    print('All test paths validated successfully')
    
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
EOF
    
    # Collect all test paths
    local all_paths=()
    for pipeline_name in "${!TEST_PATHS[@]}"; do
        all_paths+=("${TEST_PATHS[$pipeline_name]}")
    done
    
    if python3 "$validation_script" "$GOLDEN_FILE" "${all_paths[@]}"; then
        print_success "All test paths validated"
        rm -f "$validation_script"
    else
        print_error "Test path validation failed"
        rm -f "$validation_script"
        exit 1
    fi
}

finalize_final_report() {
    print_info "Finalizing final report..."
    
    # Create finalization script
    local finalize_script="/tmp/finalize_report_$$"
    cat > "$finalize_script" << EOF
import sys
sys.path.append('$(dirname "$COMPARE_SCRIPT")')
from compare_results import finalize_final_report

finalize_final_report('$FINAL_REPORT', $TOTAL_TESTS, $PASSED_TESTS, $FAILED_TESTS)
EOF
    
    python3 "$finalize_script"
    rm -f "$finalize_script"
    
    print_success "Final report finalized: $FINAL_REPORT"
    
    # Show final report summary
    if [ -f "$FINAL_REPORT" ]; then
        print_info "Final report summary:"
        echo "----------------------------------------"
        tail -20 "$FINAL_REPORT"
        echo "----------------------------------------"
        print_info "Full report available at: $FINAL_REPORT"
    fi
}

# =============================================================================
# Main Execution
# =============================================================================

show_environment
check_prerequisites
validate_test_paths

# Create results directory and initialize final report
mkdir -p "$RESULTS_DIR"
initialize_final_report

# Test all pipelines
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

for pipeline_name in "${!PIPELINES[@]}"; do
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo ""
    print_info "=========================================="
    print_info "Test $TOTAL_TESTS: $pipeline_name"
    print_info "=========================================="
    
    if test_pipeline "$pipeline_name" "${PIPELINES[$pipeline_name]}" "${TEST_PATHS[$pipeline_name]}"; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
done

# Finalize final report
finalize_final_report

# Summary
echo ""
print_info "=========================================="
print_info "TEST SUMMARY"
print_info "=========================================="
print_info "Total tests: $TOTAL_TESTS"
print_success "Passed: $PASSED_TESTS"
[ $FAILED_TESTS -gt 0 ] && print_error "Failed: $FAILED_TESTS"

if [ $FAILED_TESTS -eq 0 ]; then
    print_success "ALL TESTS PASSED! 🎉"
    print_success "Final report: $FINAL_REPORT"
    exit 0
else
    print_error "SOME TESTS FAILED! 💥"
    print_error "Check final report: $FINAL_REPORT"
    exit 1
fi
