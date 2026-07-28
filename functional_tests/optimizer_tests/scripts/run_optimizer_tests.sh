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
    STREAMS_TIMEOUT=${STREAMS_TIMEOUT:-600}
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-/workspace/optimizer_results}
    MODELS_PATH=${MODELS_PATH:-/home/dlstreamer/models}
    VIDEOS_PATH=${VIDEOS_PATH:-/home/dlstreamer/videos}
    CONFIG_FILE=${CONFIG_FILE:-/workspace/optimizer_tests/test_config.json}
    VALIDATION_SCRIPT=${VALIDATION_SCRIPT:-/workspace/optimizer_tests/scripts/validate_advanced_features.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}
else
    ENV_PREFIX="[HOST]"
    SEARCH_DURATION=${SEARCH_DURATION:-30}
    STREAMS_TIMEOUT=${STREAMS_TIMEOUT:-300}
    RESULTS_DIR=${CUSTOM_RESULTS_DIR:-/home/runner/optimizer/optimizer_results/host}
    MODELS_PATH=${MODELS_PATH:-/home/runner/models}
    VIDEOS_PATH=${VIDEOS_PATH:-/home/runner/videos}
    CONFIG_FILE=${CONFIG_FILE:-/home/runner/optimizer/functional_tests/optimizer_tests/test_config.json}
    VALIDATION_SCRIPT=${VALIDATION_SCRIPT:-/home/runner/optimizer/functional_tests/optimizer_tests/scripts/validate_advanced_features.py}
    OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}

    # Set environment variables for host using the DL Streamer setup script
    DLS_ENV_SCRIPT=${DLS_ENV_SCRIPT:-/opt/intel/dlstreamer/scripts/setup_dls_env.sh}
    if [ -f "$DLS_ENV_SCRIPT" ]; then
        # shellcheck source=/dev/null
        source "$DLS_ENV_SCRIPT"
    else
        echo "DL Streamer environment script not found: $DLS_ENV_SCRIPT" >&2
        exit 1
    fi

    # Test-specific overrides not covered by the setup script
    export PATH=/home/runner/.virtualenvs/dlstreamer/bin:$PATH
fi

mkdir -p "$RESULTS_DIR"
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

# Validate JSON output
validate_json_output() {
    local json_file=$1
    local test_name=$2
    
    if [ ! -f "$json_file" ]; then
        print_error "JSON output file not found: $json_file"
        return 1
    fi
    
    if ! jq empty "$json_file" 2>/dev/null; then
        print_error "Invalid JSON in output file for test $test_name - treating as BUG"
        print_error "JSON file: $json_file"
        if [ "$DEBUG_MODE" = true ]; then
            print_error "=== INVALID JSON CONTENT ==="
            head -20 "$json_file" | while IFS= read -r line; do
                echo -e "${RED}  $line${NC}"
            done
            print_error "=== END INVALID JSON ==="
        fi
        return 1
    fi
    
    print_success "JSON output is valid for test: $test_name"
    return 0
}

# Show error details if debug mode
show_error_details() {
    local test_name=$1
    local log_file="$RESULTS_DIR/${test_name}_log.txt"

    if [ "$DEBUG_MODE" = true ] && [ -f "$log_file" ]; then
        print_error "=== ERROR DETAILS for $test_name ==="
        print_error "Last 10 lines of log:"
        tail -10 "$log_file" | while IFS= read -r line; do
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
    pipeline=${pipeline//\$VIDEOS_PATH/$VIDEOS_PATH}
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

# Run test - separate JSON and log files
run_test() {
    local test_name=$1
    local pipeline=$2
    local json_file="$RESULTS_DIR/${test_name}.json"
    local log_file="$RESULTS_DIR/${test_name}_log.txt"
    local timing_file="$RESULTS_DIR/${test_name}_timing.txt"

    # Get test configuration
    local search_duration=$(get_search_duration "$test_name")
    local sample_duration=$(get_sample_duration "$test_name")
    local mode=$(get_mode "$test_name")
    local additional_flags=$(get_additional_flags "$test_name")
    local test_type=$(get_test_type "$test_name")
    local streams_timeout=$(get_streams_timeout "$test_name")

    print_info "Testing: $test_name (type: $test_type, mode: $mode)"
    print_info "Search duration: ${search_duration}s"
    print_info "JSON output: $json_file"
    print_info "Log output: $log_file"
    print_info "Timing file: $timing_file"

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

    # Always add JSON output flag
    optimizer_cmd="$optimizer_cmd --output $json_file"

    # Add verbose flag for verbose tests
    if [[ "$test_type" == "verbose_flag" ]]; then
        optimizer_cmd="$optimizer_cmd --verbose"
    fi

    # Add pipeline
    optimizer_cmd="$optimizer_cmd -- $pipeline"

    print_info "Running: $optimizer_cmd"

    # Record start time
    local start_time=$(date +%s.%N)
    
    # Execute based on test type
    local exit_code=0
    if [ "$test_type" = "streams_modifications" ]; then
        # Streams modifications - capture logs with timeout
        print_info "Running $test_type test with FORCED timeout of ${streams_timeout}s"

        if timeout --preserve-status -s KILL "$streams_timeout" bash -c "eval '$optimizer_cmd'" > "$log_file" 2>&1; then
            print_success "Test completed normally: $test_name"
            exit_code=0
        else
            local timeout_exit_code=$?
            if [ $timeout_exit_code -eq 137 ] || [ $timeout_exit_code -eq 124 ]; then
                print_warning "Test was terminated by timeout after ${streams_timeout}s: $test_name"
                echo "" >> "$log_file"
                echo "=== TEST TERMINATED BY TIMEOUT ===" >> "$log_file"
                echo "Test was killed after ${streams_timeout}s timeout" >> "$log_file"
                echo "Timestamp: $(date)" >> "$log_file"
                print_info "$test_type test timeout termination is treated as successful completion"
                exit_code=0
            else
                print_error "Test failed: $test_name (exit code: $timeout_exit_code)"
                show_error_details "$test_name"
                exit_code=1
            fi
        fi
    else
        # Regular execution - hide FpsCounter from console completely
        if eval "$optimizer_cmd" 2> "$log_file" >/dev/null; then
            print_success "Test completed: $test_name"
            exit_code=0
            
            # Validate JSON output for non-streams tests
            if ! validate_json_output "$json_file" "$test_name"; then
                print_error "JSON validation failed - treating as BUG"
                exit_code=1
            fi
        else
            print_error "Test failed: $test_name"
            show_error_details "$test_name"
            exit_code=1
        fi
    fi

    # Record end time and calculate duration using Python (no bc needed!)
    local end_time=$(date +%s.%N)
    local duration=$(python3 -c "print($end_time - $start_time)")
    
    # Save timing information
    cat > "$timing_file" << EOF
{
  "test_name": "$test_name",
  "start_time": $start_time,
  "end_time": $end_time,
  "duration_seconds": $duration,
  "search_duration_config": $search_duration,
  "sample_duration_config": "$sample_duration",
  "mode": "$mode",
  "test_type": "$test_type",
  "exit_code": $exit_code,
  "json_file": "$json_file",
  "log_file": "$log_file",
  "timestamp": "$(date -Iseconds)"
}
EOF
    
    print_info "Test duration: ${duration}s (saved to $timing_file)"

    return $exit_code
}

# Run validation using the new validator
run_validation() {
    local test_name=$1
    local test_type=$(get_test_type "$test_name")
    local json_file="$RESULTS_DIR/${test_name}.json"
    local log_file="$RESULTS_DIR/${test_name}_log.txt"

    print_debug "Running validation for $test_name (type: $test_type)"

    if [ -f "$VALIDATION_SCRIPT" ]; then
        local validation_cmd="python3 $VALIDATION_SCRIPT --config-file $CONFIG_FILE --test-name $test_name"
        
        # Choose appropriate file based on test type
        if [[ "$test_type" == "streams_modifications" ]]; then
            # For streams modifications, use log file
            validation_cmd="$validation_cmd --output-file $log_file"
        else
            # For other tests, use JSON file
            validation_cmd="$validation_cmd --output-file $json_file"
        fi
        
        # Add log file for verbose tests
        if [[ "$test_type" == "verbose_flag" ]]; then
            validation_cmd="$validation_cmd --log-file $log_file"
        fi
        
        print_info "Running validation: $validation_cmd"
        
        if eval "$validation_cmd"; then
            print_success "Validation passed for $test_name"
            return 0
        else
            print_error "Validation failed for $test_name"
            return 1
        fi
    else
        print_warning "Validation script not found: $VALIDATION_SCRIPT"
        # Basic validation - check if appropriate file exists and has content
        local file_to_check
        if [[ "$test_type" == "streams_modifications" ]]; then
            file_to_check="$log_file"
        else
            file_to_check="$json_file"
        fi
        
        if [ -f "$file_to_check" ] && [ -s "$file_to_check" ]; then
            print_success "Basic validation passed for $test_name (file exists and not empty)"
            return 0
        else
            print_error "Basic validation failed for $test_name (file missing or empty: $file_to_check)"
            return 1
        fi
    fi
}

# Generate final report
generate_final_report() {
    local report_file="$RESULTS_DIR/FINAL_TEST_REPORT.txt"
    
    echo "========================================" > "$report_file"
    echo "       OPTIMIZER TEST FINAL REPORT      " >> "$report_file"
    echo "========================================" >> "$report_file"
    echo "Environment: $([ -f /.dockerenv ] && echo "Docker" || echo "Host")" >> "$report_file"
    echo "Timestamp: $(date)" >> "$report_file"
    echo "Results Directory: $RESULTS_DIR" >> "$report_file"
    echo "" >> "$report_file"
    
    echo "SUMMARY:" >> "$report_file"
    echo "--------" >> "$report_file"
    echo "Total tests: $TOTAL_TESTS" >> "$report_file"
    echo "Passed: $PASSED_TESTS" >> "$report_file"
    echo "Failed: $FAILED_TESTS" >> "$report_file"
    echo "" >> "$report_file"
    
    if [ $FAILED_TESTS -eq 0 ]; then
        echo "OVERALL RESULT: ✅ ALL TESTS PASSED" >> "$report_file"
    else
        echo "OVERALL RESULT: ❌ SOME TESTS FAILED" >> "$report_file"
    fi
    echo "" >> "$report_file"
    
    echo "DETAILED RESULTS:" >> "$report_file"
    echo "-----------------" >> "$report_file"
    
    # Process timing files to show individual test results
    for timing_file in "$RESULTS_DIR"/*_timing.txt; do
        if [ -f "$timing_file" ]; then
            test_name=$(jq -r '.test_name' "$timing_file" 2>/dev/null || echo "Unknown")
            exit_code=$(jq -r '.exit_code' "$timing_file" 2>/dev/null || echo "1")
            duration=$(jq -r '.duration_seconds' "$timing_file" 2>/dev/null || echo "0")
            test_type=$(jq -r '.test_type' "$timing_file" 2>/dev/null || echo "standard")
            
            if [ "$exit_code" = "0" ]; then
                printf "✅ %-30s PASSED (%.2fs, %s)\n" "$test_name" "$duration" "$test_type" >> "$report_file"
            else
                printf "❌ %-30s FAILED (%.2fs, %s)\n" "$test_name" "$duration" "$test_type" >> "$report_file"
            fi
        fi
    done
    
    echo "" >> "$report_file"
    echo "========================================" >> "$report_file"
    
    print_info "Final report generated: $report_file"
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
    if [ -z "$pipeline" ]; then
        print_error "No pipeline found for test: $test_name"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    # Run test
    if run_test "$test_name" "$pipeline"; then
        # Run validation
        if run_validation "$test_name"; then
            PASSED_TESTS=$((PASSED_TESTS + 1))
        else
            FAILED_TESTS=$((FAILED_TESTS + 1))
        fi
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi

    print_info "Progress: $TOTAL_TESTS tests completed"

done < <(get_all_test_names)

# Call the function before final summary
generate_final_report

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
