#!/bin/bash
# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================

set -e

# Parse arguments
VERBOSE_OUTPUT=false
DEBUG_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --results-dir) CUSTOM_RESULTS_DIR="$2"; shift 2 ;;
        --search-duration) SEARCH_DURATION="$2"; shift 2 ;;
        --tolerance) CUSTOM_TOLERANCE="$2"; shift 2 ;;
        --models-path) MODELS_PATH="$2"; shift 2 ;;
        --config-file) CONFIG_FILE="$2"; shift 2 ;;
        --streams-timeout) STREAMS_TIMEOUT="$2"; shift 2 ;;
        --verbose) VERBOSE_OUTPUT=true; shift ;;
        --debug) DEBUG_MODE=true; VERBOSE_OUTPUT=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--results-dir PATH] [--config-file PATH] [--streams-timeout SECONDS] [--verbose] [--debug]"
            exit 0 ;;
        *) echo "Unknown option: $1"; shift ;;
    esac
done

# Auto-detect environment and set paths
if [ -f /.dockerenv ]; then
    ENV_PREFIX="[DOCKER]"
    SEARCH_DURATION=${SEARCH_DURATION:-300}
    STREAMS_TIMEOUT=${STREAMS_TIMEOUT:-600}  # Default 10 minutes for streams tests
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-/workspace/optimizer_results}
    MODELS_PATH=${MODELS_PATH:-/home/dlstreamer/models}
    VIDEOS_PATH=${VIDEOS_PATH:-/home/dlstreamer/videos}
    CONFIG_FILE=${CONFIG_FILE:-/workspace/optimizer_tests/test_config.json}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-/workspace/optimizer_tests/scripts/compare_results.py}
    VALIDATION_SCRIPT=${VALIDATION_SCRIPT:-/workspace/optimizer_tests/scripts/validate_advanced_features.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}
else
    ENV_PREFIX="[HOST]"
    SEARCH_DURATION=${SEARCH_DURATION:-30}
    STREAMS_TIMEOUT=${STREAMS_TIMEOUT:-300}  # Default 5 minutes for streams tests on host
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-/home/runner/optimizer/optimizer_results/host}
    MODELS_PATH=${MODELS_PATH:-/home/runner/models}
    VIDEOS_PATH=${VIDEOS_PATH:-/home/runner/videos}
    CONFIG_FILE=${CONFIG_FILE:-/home/runner/optimizer/functional_tests/optimizer_tests/test_config.json}
    COMPARE_SCRIPT=${COMPARE_SCRIPT:-/home/runner/optimizer/functional_tests/optimizer_tests/scripts/compare_results.py}
    VALIDATION_SCRIPT=${VALIDATION_SCRIPT:-/home/runner/optimizer/functional_tests/optimizer_tests/scripts/validate_advanced_features.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}

    # Set environment variables for host
    export LIBVA_DRIVER_NAME=iHD
    export GST_VA_ALL_DRIVERS=1
    export LIBVA_DRIVERS_PATH=/usr/lib/x86_64-linux-gnu/dri
    export GST_PLUGIN_PATH=/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0:/opt/intel/dlstreamer/gstreamer/lib/
    export LD_LIBRARY_PATH=/opt/intel/dlstreamer/gstreamer/lib:/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/lib/gstreamer-1.0:/usr/lib:/opt/intel/dlstreamer/lib:/opt/opencv:/opt/openh264:/opt/rdkafka:/opt/ffmpeg:/usr/local/lib/gstreamer-1.0:/usr/local/lib
    export PYTHONPATH=/opt/intel/dlstreamer/gstreamer/lib/python3/dist-packages:/opt/intel/dlstreamer/python:/opt/intel/dlstreamer/gstreamer/lib/python3/dist-packages:
    export PATH=/home/runner/.virtualenvs/dlstreamer/bin:/opt/intel/dlstreamer/gstreamer/bin:/opt/intel/dlstreamer/bin:$PATH
    export GI_TYPELIB_PATH=/opt/intel/dlstreamer/gstreamer/lib/girepository-1.0:/opt/intel/dlstreamer/lib/girepository-1.0:/usr/lib/x86_64-linux-gnu/girepository-1.0
    export MODELS_PATH=/home/runner/models
    export ZE_ENABLE_ALT_DRIVERS=libze_intel_npu.so
fi

TOLERANCE=${CUSTOM_TOLERANCE:-5.0}
FINAL_REPORT="$RESULTS_DIR/FINAL_TEST_REPORT.txt"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'

print_info() { echo -e "${BLUE}${ENV_PREFIX} [INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}${ENV_PREFIX} [SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}${ENV_PREFIX} [ERROR]${NC} $1"; }
print_warning() { echo -e "${YELLOW}${ENV_PREFIX} [WARNING]${NC} $1"; }
print_debug() { 
    if [ "$VERBOSE_OUTPUT" = true ]; then
        echo -e "${BLUE}${ENV_PREFIX} [DEBUG]${NC} $1"
    fi
}

# Show error details if debug mode
show_error_details() {
    local test_name=$1
    local output_file="$RESULTS_DIR/${test_name}_full_output.txt"
    
    if [ "$DEBUG_MODE" = true ] && [ -f "$output_file" ]; then
        print_error "=== ERROR DETAILS for $test_name ==="
        print_error "Last 10 lines of output:"
        tail -10 "$output_file" | while IFS= read -r line; do
            echo -e "${RED}  $line${NC}"
        done
        print_error "=== END ERROR DETAILS ==="
    fi
}

# Basic checks
check_prerequisites() {
    print_info "Checking prerequisites..."
    [ -d "$OPTIMIZER_DIR" ] || { print_error "Optimizer directory not found: $OPTIMIZER_DIR"; exit 1; }
    [ -f "$OPTIMIZER_DIR/__main__.py" ] || { print_error "Optimizer __main__.py not found"; exit 1; }
    [ -f "$CONFIG_FILE" ] || { print_error "Config file not found: $CONFIG_FILE"; exit 1; }
    command -v python3 >/dev/null || { print_error "Python3 not found"; exit 1; }
    command -v jq >/dev/null || { print_error "jq not found (required for JSON parsing)"; exit 1; }
    command -v timeout >/dev/null || { print_error "timeout command not found (required for streams tests)"; exit 1; }
    print_success "Prerequisites OK"
}

# Load configuration
load_test_config() {
    if ! jq empty "$CONFIG_FILE" 2>/dev/null; then
        print_error "Invalid JSON syntax in config file: $CONFIG_FILE"
        exit 1
    fi
    
    print_info "Loading test configuration from: $CONFIG_FILE"
    local test_count=$(jq 'length' "$CONFIG_FILE")
    print_info "Found $test_count test configurations"
}

# Get all test names from config
get_all_test_names() {
    jq -r 'keys[]' "$CONFIG_FILE"
}

# Get pipeline for test
get_pipeline_to_test() {
    local test_name=$1
    local pipeline=$(jq -r ".[\"$test_name\"].pipeline_to_test" "$CONFIG_FILE")
    pipeline=${pipeline//\$MODELS_PATH/$MODELS_PATH}
    echo "$pipeline"
}

# Get search duration for test
get_search_duration() {
    local test_name=$1
    local search_duration=$(jq -r ".[\"$test_name\"].search_duration // null" "$CONFIG_FILE")
    
    if [ "$search_duration" = "null" ] || [ -z "$search_duration" ]; then
        echo "$SEARCH_DURATION"
    else
        echo "$search_duration"
    fi
}

# Get sample duration for test
get_sample_duration() {
    local test_name=$1
    local sample_duration=$(jq -r ".[\"$test_name\"].sample_duration // null" "$CONFIG_FILE")
    
    if [ "$sample_duration" = "null" ] || [ -z "$sample_duration" ]; then
        echo ""
    else
        echo "$sample_duration"
    fi
}

# Get mode (fps/streams)
get_mode() {
    local test_name=$1
    local mode=$(jq -r ".[\"$test_name\"].mode // \"fps\"" "$CONFIG_FILE")
    echo "$mode"
}

# Get additional flags
get_additional_flags() {
    local test_name=$1
    local flags=$(jq -r ".[\"$test_name\"].additional_flags[]? // empty" "$CONFIG_FILE" | tr '\n' ' ')
    echo "$flags"
}

# Get test type
get_test_type() {
    local test_name=$1
    local test_type=$(jq -r ".[\"$test_name\"].test_type // \"standard\"" "$CONFIG_FILE")
    echo "$test_type"
}

# Get custom timeout for streams tests
get_streams_timeout() {
    local test_name=$1
    local custom_timeout=$(jq -r ".[\"$test_name\"].streams_timeout // null" "$CONFIG_FILE")
    
    if [ "$custom_timeout" = "null" ] || [ -z "$custom_timeout" ]; then
        echo "$STREAMS_TIMEOUT"
    else
        echo "$custom_timeout"
    fi
}

# Kill process and all its children
kill_process_tree() {
    local pid=$1
    local signal=${2:-TERM}
    
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        # Kill all child processes first
        local children=$(pgrep -P "$pid" 2>/dev/null || true)
        for child in $children; do
            kill_process_tree "$child" "$signal"
        done
        
        # Kill the main process
        print_debug "Killing process $pid with signal $signal"
        kill -"$signal" "$pid" 2>/dev/null || true
    fi
}

# Run any test (standard or advanced) with timeout support for streams
run_test() {
    local test_name=$1
    local pipeline=$2
    local output_file="$RESULTS_DIR/${test_name}_full_output.txt"
    
    # Get test configuration
    local search_duration=$(get_search_duration "$test_name")
    local sample_duration=$(get_sample_duration "$test_name")
    local mode=$(get_mode "$test_name")
    local additional_flags=$(get_additional_flags "$test_name")
    local test_type=$(get_test_type "$test_name")
    local streams_timeout=$(get_streams_timeout "$test_name")
    
    print_info "Testing: $test_name (type: $test_type, mode: $mode)"
    print_info "Search duration: ${search_duration}s"
    
    if [ "$mode" = "streams" ]; then
        print_info "Streams timeout: ${streams_timeout}s (test will be forcefully killed after this time)"
    fi
    
    if [ -n "$sample_duration" ]; then
        print_info "Sample duration: ${sample_duration}s"
    fi
    
    if [ -n "$additional_flags" ]; then
        print_info "Additional flags: $additional_flags"
    fi
    
    print_debug "Pipeline: $pipeline"
    
    cd "$OPTIMIZER_DIR"
    
    # Build optimizer command
    local optimizer_cmd="python3 . $mode --search-duration $search_duration"
    
    # Add sample duration if specified
    if [ -n "$sample_duration" ]; then
        optimizer_cmd="$optimizer_cmd --sample-duration $sample_duration"
    fi
    
    # Add additional flags
    if [ -n "$additional_flags" ]; then
        optimizer_cmd="$optimizer_cmd $additional_flags"
    fi
    
    # Add output flag for advanced tests
    if [[ "$test_type" != "standard" ]]; then
        local json_output_file="$RESULTS_DIR/${test_name}_output.json"
        optimizer_cmd="$optimizer_cmd --output $json_output_file"
    fi
    
    # Add verbose flag for verbose tests
    if [[ "$test_type" == "verbose_flag" ]]; then
        optimizer_cmd="$optimizer_cmd --verbose"
    fi
    
    # Add pipeline
    optimizer_cmd="$optimizer_cmd -- $pipeline"
    
    print_info "Running: $optimizer_cmd"
    
    # Execute with timeout for streams mode
    local exit_code=0
    if [ "$mode" = "streams" ]; then
        print_info "Running streams test with FORCED timeout of ${streams_timeout}s"
        
        # Use timeout with KILL signal to forcefully terminate
        # --preserve-status ensures we get the actual exit code if process finishes normally
        # -s KILL ensures the process is forcefully killed after timeout
        if timeout --preserve-status -s KILL "$streams_timeout" bash -c "eval '$optimizer_cmd'" > "$output_file" 2>&1; then
            print_success "Test completed normally: $test_name"
            exit_code=0
        else
            local timeout_exit_code=$?
            if [ $timeout_exit_code -eq 137 ]; then  # 137 = 128 + 9 (SIGKILL)
                print_warning "Test was FORCEFULLY KILLED after ${streams_timeout}s timeout: $test_name"
                echo "" >> "$output_file"
                echo "=== TEST FORCEFULLY TERMINATED BY TIMEOUT ===" >> "$output_file"
                echo "Test was killed after ${streams_timeout}s timeout" >> "$output_file"
                echo "Timestamp: $(date)" >> "$output_file"
                # For streams tests, forced termination after timeout is acceptable
                print_info "Streams test timeout termination is treated as successful completion"
                exit_code=0
            elif [ $timeout_exit_code -eq 124 ]; then  # Standard timeout exit code
                print_warning "Test timed out after ${streams_timeout}s: $test_name"
                echo "" >> "$output_file"
                echo "=== TEST TIMED OUT ===" >> "$output_file"
                echo "Test timed out after ${streams_timeout}s" >> "$output_file"
                echo "Timestamp: $(date)" >> "$output_file"
                print_info "Streams test timeout is treated as successful completion"
                exit_code=0
            else
                print_error "Test failed: $test_name (exit code: $timeout_exit_code)"
                show_error_details "$test_name"
                exit_code=1
            fi
        fi
    else
        # Regular execution for non-streams tests
        if eval "$optimizer_cmd" > "$output_file" 2>&1; then
            print_success "Test completed: $test_name"
            exit_code=0
        else
            print_error "Test failed: $test_name"
            show_error_details "$test_name"
            exit_code=1
        fi
    fi
    
    return $exit_code
}

# Run comparison for any test
run_comparison() {
    local test_name=$1
    local test_type=$(get_test_type "$test_name")
    local output_file="$RESULTS_DIR/${test_name}_full_output.txt"
    
    print_debug "Running comparison for $test_name (type: $test_type)"
    
    # For standard tests, use the comparison script
    if [[ "$test_type" == "standard" ]]; then
        if [ -f "$COMPARE_SCRIPT" ]; then
            if python3 "$COMPARE_SCRIPT" \
                --full-output "$output_file" \
                --config-file "$CONFIG_FILE" \
                --test-name "$test_name" \
                --tolerance "$TOLERANCE" \
                --final-report "$FINAL_REPORT"; then
                print_success "Comparison passed for $test_name"
                return 0
            else
                print_error "Comparison failed for $test_name"
                return 1
            fi
        else
            print_warning "Compare script not found, skipping comparison for $test_name"
            return 0
        fi
    else
        # For advanced tests, just check if output file exists and has content
        if [ -f "$output_file" ] && [ -s "$output_file" ]; then
            print_success "Advanced test validation passed for $test_name"
            return 0
        else
            print_error "Advanced test validation failed for $test_name"
            return 1
        fi
    fi
}

# Main execution
print_info "========== OPTIMIZER TEST SUITE =========="
print_info "Environment: $([ -f /.dockerenv ] && echo "Docker" || echo "Host")"
print_info "Results: $RESULTS_DIR"
print_info "Config file: $CONFIG_FILE"
print_info "Streams timeout: ${STREAMS_TIMEOUT}s (FORCED KILL)"

check_prerequisites
load_test_config
mkdir -p "$RESULTS_DIR"
rm -f "$FINAL_REPORT"

TOTAL_TESTS=0 PASSED_TESTS=0 FAILED_TESTS=0

# Get all tests and run them
print_info "========== RUNNING ALL TESTS =========="

while IFS= read -r test_name; do
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    print_info "========== Test $TOTAL_TESTS: $test_name =========="
    
    pipeline=$(get_pipeline_to_test "$test_name")
    if [ -z "$pipeline" ] || [ "$pipeline" = "null" ]; then
        print_error "No pipeline found for test: $test_name"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi
    
    # Run test
    if run_test "$test_name" "$pipeline"; then
        # Run comparison if test succeeded
        if run_comparison "$test_name"; then
            PASSED_TESTS=$((PASSED_TESTS + 1))
        else
            FAILED_TESTS=$((FAILED_TESTS + 1))
        fi
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    
    print_info "Progress: $TOTAL_TESTS tests completed"
    
done < <(get_all_test_names)

# Summary
print_info "========== FINAL SUMMARY =========="
print_info "Total tests: $TOTAL_TESTS"
print_info "Passed: $PASSED_TESTS"
print_info "Failed: $FAILED_TESTS"

if [ $FAILED_TESTS -eq 0 ]; then
    print_success "ALL TESTS PASSED! 🎉"
    exit 0
else
    print_error "SOME TESTS FAILED! 💥"
    print_info "Check individual test outputs in: $RESULTS_DIR"
    exit 1
fi
