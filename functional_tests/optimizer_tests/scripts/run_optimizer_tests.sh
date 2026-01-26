#!/bin/bash

# =============================================================================
# Universal Pipeline Test Script
# Host: dlstreamer-test-repo/functional_tests/optimizer/tests/scripts/
# Docker: runs with mounted volumes
# =============================================================================

set -e

# =============================================================================
# Auto-detect environment and set paths
# =============================================================================

if [ -f /.dockerenv ]; then
    RUNNING_IN_DOCKER=true
    ENV_PREFIX="[DOCKER]"
    
    # Docker paths
    SEARCH_DURATION=${SEARCH_DURATION:-30}
    RESULTS_DIR=${RESULTS_DIR:-/workspace/test_results}
    MODELS_PATH=${MODELS_PATH:-/home/dlstreamer/models}
    GOLDEN_DIR=${GOLDEN_DIR:-/workspace/goldens}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-/workspace/test_scripts/compare_results.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/home/dlstreamer/dlstreamer/scripts/optimizer}
else
    RUNNING_IN_DOCKER=false
    ENV_PREFIX="[HOST]"
    
    # Host paths (relative to dlstreamer-test-repo)
    SEARCH_DURATION=${SEARCH_DURATION:-30}
    RESULTS_DIR=${RESULTS_DIR:-./test_results}
    MODELS_PATH=${MODELS_PATH:-/home/labrat/models}
    GOLDEN_DIR=${GOLDEN_DIR:-../goldens}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-./compare_results.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}
fi

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
# Pipeline Definitions
# =============================================================================

declare -A PIPELINES
declare -A GOLDEN_FILES

# Pipeline 1: TGL YOLO11s CPU
PIPELINES["yolo11s_cpu"]="urisourcebin buffer-size=4096 uri=https://videos.pexels.com/video-files/1192116/1192116-sd_640_360_30fps.mp4 ! decodebin ! gvadetect model=$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml device=CPU ! queue ! gvawatermark ! vah264enc ! h264parse ! mp4mux ! fakesink"
GOLDEN_FILES["yolo11s_cpu"]="$GOLDEN_DIR/TGL/yolo11s_cpu_golden.txt"

# Pipeline 2: TGL YOLO11s GPU
PIPELINES["yolo11s_gpu"]="urisourcebin buffer-size=4096 uri=https://videos.pexels.com/video-files/1192116/1192116-sd_640_360_30fps.mp4 ! decodebin ! gvadetect model=$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml device=GPU ! queue ! gvawatermark ! vah264enc ! h264parse ! mp4mux ! fakesink"
GOLDEN_FILES["yolo11s_gpu"]="$GOLDEN_DIR/TGL/yolo11s_gpu_golden.txt"

# =============================================================================
# Functions
# =============================================================================

show_environment() {
    print_info "=========================================="
    print_info "Environment: $([ "$RUNNING_IN_DOCKER" = true ] && echo "Docker Container" || echo "Host System")"
    print_info "=========================================="
    print_info "Optimizer directory: $OPTIMIZER_DIR"
    print_info "Models path: $MODELS_PATH"
    print_info "Golden directory: $GOLDEN_DIR"
    print_info "Results directory: $RESULTS_DIR"
    print_info "Compare script: $COMPARE_SCRIPT"
    print_info "Search duration: ${SEARCH_DURATION}s"
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
    
    # Check golden directory
    if [ ! -d "$GOLDEN_DIR" ]; then
        print_error "Golden directory not found: $GOLDEN_DIR"
        exit 1
    fi
    
    print_success "Prerequisites OK"
}

test_pipeline() {
    local name=$1
    local pipeline=$2
    local golden_file=$3
    
    print_info "Testing pipeline: $name"
    
    local output_file="$RESULTS_DIR/${name}_reports/${name}_output.txt"
    local report_dir="$RESULTS_DIR/${name}_reports"
    
    mkdir -p "$report_dir"
    
    # Run optimizer
    print_info "Running optimizer (${SEARCH_DURATION}s search)..."
    print_info "Working directory: $OPTIMIZER_DIR"
    
    cd "$OPTIMIZER_DIR"
    if timeout 600 python3 . --search-duration "$SEARCH_DURATION" -- $pipeline > "$output_file" 2>&1; then
        print_success "Optimizer completed for $name"
    else
        print_error "Optimizer failed for $name"
        if [ -f "$output_file" ]; then
            print_info "Last 10 lines of output:"
            tail -10 "$output_file"
        fi
        return 1
    fi
    
    # Check if golden file exists
    if [ ! -f "$golden_file" ]; then
        print_error "Golden file not found: $golden_file"
        return 1
    fi
    
    # Compare results
    print_info "Comparing results with golden values..."
    if python3 "$COMPARE_SCRIPT" \
        --full-output "$output_file" \
        --golden "$golden_file" \
        --tolerance 1 \
        --output-dir "$report_dir"; then
        print_success "Test PASSED for $name"
        return 0
    else
        print_error "Test FAILED for $name"
        return 1
    fi
}

# =============================================================================
# Main Execution
# =============================================================================

show_environment
check_prerequisites

# Create results directory
mkdir -p "$RESULTS_DIR"

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
    
    if test_pipeline "$pipeline_name" "${PIPELINES[$pipeline_name]}" "${GOLDEN_FILES[$pipeline_name]}"; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
done

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
    exit 0
else
    print_error "SOME TESTS FAILED! 💥"
    exit 1
fi
