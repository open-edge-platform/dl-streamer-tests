#!/bin/bash
# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================

set -e

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --results-dir) CUSTOM_RESULTS_DIR="$2"; shift 2 ;;
        --search-duration) SEARCH_DURATION="$2"; shift 2 ;;
        --tolerance) CUSTOM_TOLERANCE="$2"; shift 2 ;;
        --models-path) MODELS_PATH="$2"; shift 2 ;;
        --golden-file) GOLDEN_FILE="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--results-dir PATH] [--search-duration SECONDS] [--tolerance PERCENT] [--models-path PATH] [--golden-file PATH]"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Auto-detect environment and set paths
if [ -f /.dockerenv ]; then
    ENV_PREFIX="[DOCKER]"
    SEARCH_DURATION=${SEARCH_DURATION:-300}
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-${RESULTS_DIR:-/workspace/optimizer_results}}
    MODELS_PATH=${MODELS_PATH:-/home/dlstreamer/models}
    GOLDEN_FILE=${GOLDEN_FILE:-/workspace/goldens/golden_values.json}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-/workspace/test_scripts/compare_results.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/home/dlstreamer/dlstreamer/scripts/optimizer}
else
    ENV_PREFIX="[HOST]"
    SEARCH_DURATION=${SEARCH_DURATION:-30}
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-${RESULTS_DIR:-/home/runner/optimizer_results}}
    MODELS_PATH=${MODELS_PATH:-/home/runner/models}
    GOLDEN_FILE=${GOLDEN_FILE:-/home/runner/dlstreamer/tests/functional_tests/optimizer_tests/goldens/golden_values.json}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-/home/runner/dlstreamer/tests/functional_tests/optimizer_tests/scripts/compare_results.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}
    
    # Set environment variables for host
    export LIBVA_DRIVER_NAME=iHD
    export GST_VA_ALL_DRIVERS=1
    export LIBVA_DRIVERS_PATH=/usr/lib/x86_64-linux-gnu/dri
    export GST_PLUGIN_PATH=/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0:/opt/intel/dlstreamer/gstreamer/lib/
    export LD_LIBRARY_PATH=/opt/intel/dlstreamer/gstreamer/lib:/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/lib/gstreamer-1.0:/usr/lib:/opt/intel/dlstreamer/lib:/opt/opencv:/opt/openh264:/opt/rdkafka:/opt/ffmpeg:/usr/local/lib/gstreamer-1.0:/usr/local/lib
    export PYTHONPATH=/opt/intel/dlstreamer/gstreamer/lib/python3/dist-packages:/opt/intel/dlstreamer/python:/opt/intel/dlstreamer/gstreamer/lib/python3/dist-packages:
    export PATH=/home/runner/.virtualenvs/dlstreamer/bin:/opt/intel/dlstreamer/gstreamer/bin:/opt/intel/dlstreamer/bin:$PATH
    export GI_TYPELIB_PATH=/opt/intel/dlstreamer/gstreamer/lib/girepository-1.0:/usr/lib/x86_64-linux-gnu/girepository-1.0
    export MODELS_PATH=$MODELS_PATH
    export ZE_ENABLE_ALT_DRIVERS=libze_intel_npu.so
fi

TOLERANCE=${CUSTOM_TOLERANCE:-5.0}
FINAL_REPORT="$RESULTS_DIR/FINAL_TEST_REPORT.txt"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
print_info() { echo -e "${BLUE}${ENV_PREFIX} [INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}${ENV_PREFIX} [SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}${ENV_PREFIX} [ERROR]${NC} $1"; }

# Pipeline definitions
declare -A PIPELINES TEST_PATHS
PIPELINES["yolo11s_cpu"]="urisourcebin buffer-size=4096 uri=https://videos.pexels.com/video-files/1192116/1192116-sd_640_360_30fps.mp4 ! decodebin ! gvadetect model=$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml device=CPU ! queue ! gvawatermark ! vah264enc ! h264parse ! mp4mux ! fakesink"
TEST_PATHS["yolo11s_cpu"]="TGL.yolo11s_cpu"
PIPELINES["yolo11s_gpu"]="urisourcebin buffer-size=4096 uri=https://videos.pexels.com/video-files/1192116/1192116-sd_640_360_30fps.mp4 ! decodebin ! gvadetect model=$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml device=GPU ! queue ! gvawatermark ! vah264enc ! h264parse ! mp4mux ! fakesink"
TEST_PATHS["yolo11s_gpu"]="TGL.yolo11s_gpu"

# Basic checks
check_prerequisites() {
    print_info "Checking prerequisites..."
    [ -d "$OPTIMIZER_DIR" ] || { print_error "Optimizer directory not found: $OPTIMIZER_DIR"; exit 1; }
    [ -f "$OPTIMIZER_DIR/__main__.py" ] || { print_error "Optimizer __main__.py not found"; exit 1; }
    [ -f "$COMPARE_SCRIPT" ] || { print_error "Compare script not found: $COMPARE_SCRIPT"; exit 1; }
    [ -f "$GOLDEN_FILE" ] || { print_error "Golden file not found: $GOLDEN_FILE"; exit 1; }
    command -v python3 >/dev/null || { print_error "Python3 not found"; exit 1; }
    print_success "Prerequisites OK"
}

test_pipeline() {
    local name=$1 pipeline=$2 test_path=$3
    local output_file="$RESULTS_DIR/${name}_full_output.txt"
    
    print_info "Testing pipeline: $name"
    print_info "Search duration: ${SEARCH_DURATION}s"
    
    cd "$OPTIMIZER_DIR"
    if python3 . --search-duration "$SEARCH_DURATION" -- $pipeline > "$output_file" 2>&1; then
        print_success "Optimizer completed for $name"
    else
        local exit_code=$?
        print_error "Optimizer failed for $name (exit code: $exit_code)"
        [ -f "$output_file" ] && tail -10 "$output_file"
        return 1
    fi
    
    [ -s "$output_file" ] || { print_error "Output file is empty"; return 1; }
    
    if python3 "$COMPARE_SCRIPT" --full-output "$output_file" --golden "$GOLDEN_FILE" --test-name "$test_path" --tolerance "$TOLERANCE" --final-report "$FINAL_REPORT"; then
        print_success "Test PASSED for $name"
        return 0
    else
        print_error "Test FAILED for $name"
        return 1
    fi
}

# Main execution
print_info "Environment: $([ -f /.dockerenv ] && echo "Docker" || echo "Host")"
print_info "Results: $RESULTS_DIR | Duration: ${SEARCH_DURATION}s | Tolerance: ${TOLERANCE}%"

check_prerequisites
mkdir -p "$RESULTS_DIR"
rm -f "$FINAL_REPORT"

TOTAL_TESTS=0 PASSED_TESTS=0 FAILED_TESTS=0

for pipeline_name in "${!PIPELINES[@]}"; do
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    print_info "========== Test $TOTAL_TESTS: $pipeline_name =========="
    
    if test_pipeline "$pipeline_name" "${PIPELINES[$pipeline_name]}" "${TEST_PATHS[$pipeline_name]}"; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
done

# Summary
print_info "========== SUMMARY =========="
print_info "Total: $TOTAL_TESTS | Passed: $PASSED_TESTS | Failed: $FAILED_TESTS"

if [ $FAILED_TESTS -eq 0 ]; then
    print_success "ALL TESTS PASSED! 🎉"
    exit 0
else
    print_error "SOME TESTS FAILED! 💥"
    exit 1
fi
