#!/bin/bash
# ==============================================================================
# Copyright (C) 2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================

set -e

# Parse arguments
SKIP_ADVANCED=false
ONLY_ADVANCED=false
PARALLEL_TESTS=false
VERBOSE_OUTPUT=false
DRY_RUN=false
TEST_FILTER=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --results-dir) CUSTOM_RESULTS_DIR="$2"; shift 2 ;;
        --search-duration) SEARCH_DURATION="$2"; shift 2 ;;
        --tolerance) CUSTOM_TOLERANCE="$2"; shift 2 ;;
        --models-path) MODELS_PATH="$2"; shift 2 ;;
        --config-file) CONFIG_FILE="$2"; shift 2 ;;
        --skip-advanced) SKIP_ADVANCED=true; shift ;;
        --only-advanced) ONLY_ADVANCED=true; shift ;;
        --parallel) PARALLEL_TESTS=true; shift ;;
        --verbose) VERBOSE_OUTPUT=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --filter) TEST_FILTER="$2"; shift 2 ;;
        --version) echo "$SCRIPT_NAME v$SCRIPT_VERSION"; exit 0 ;;
        -h|--help)
            cat << EOF
$SCRIPT_NAME v$SCRIPT_VERSION

Usage: $0 [OPTIONS]

OPTIONS:
  --results-dir PATH      Custom results directory
  --search-duration SEC   Default search duration for tests
  --tolerance PERCENT     FPS tolerance percentage
  --models-path PATH      Path to models directory
  --config-file PATH      Test configuration JSON file
  --skip-advanced         Skip advanced feature tests
  --only-advanced         Run only advanced feature tests
  --parallel              Run tests in parallel (experimental)
  --verbose               Enable verbose output
  --dry-run               Show what would be executed without running
  --filter PATTERN        Run only tests matching pattern
  --version               Show version information
  -h, --help              Show this help message

EXAMPLES:
  $0                                    # Run all tests
  $0 --only-advanced                    # Run only advanced tests
  $0 --filter "yolo11s"                 # Run tests containing "yolo11s"
  $0 --dry-run --verbose                # Show execution plan
  $0 --skip-advanced --parallel         # Run standard tests in parallel

EOF
            exit 0 ;;
        *) echo "Unknown option: $1. Use --help for usage."; exit 1 ;;
    esac
done

# Auto-detect environment and set paths
detect_environment() {
    if [ -f /.dockerenv ]; then
        ENV_TYPE="DOCKER"
        ENV_PREFIX="[DOCKER]"
        SEARCH_DURATION=${SEARCH_DURATION:-300}
        RESULTS_DIR=${CUSTOM_RESULTS_DIR:-/workspace/optimizer_results}
        MODELS_PATH=${MODELS_PATH:-/home/dlstreamer/models}
        CONFIG_FILE=${CONFIG_FILE:-/workspace/optimizer_tests/test_config.json}
        COMPARE_SCRIPT=${COMPARE_SCRIPT:-/workspace/optimizer_tests/scripts/compare_results.py}
        VALIDATION_SCRIPT=${VALIDATION_SCRIPT:-/workspace/optimizer_tests/scripts/validate_advanced_features.py}
        OPTIMIZER_DIR=${OPTIMIZER_DIR:-/home/dlstreamer/dlstreamer/scripts/optimizer}
    else
        ENV_TYPE="HOST"
        ENV_PREFIX="[HOST]"
        SEARCH_DURATION=${SEARCH_DURATION:-30}
        RESULTS_DIR=${CUSTOM_RESULTS_DIR:-/home/runner/optimizer/optimizer_results/host}
        MODELS_PATH=${MODELS_PATH:-/home/runner/models}
        CONFIG_FILE=${CONFIG_FILE:-/home/runner/optimizer/functional_tests/optimizer_tests/test_config.json}
        COMPARE_SCRIPT=${COMPARE_SCRIPT:-/home/runner/optimizer/functional_tests/optimizer_tests/scripts/compare_results.py}
        VALIDATION_SCRIPT=${VALIDATION_SCRIPT:-/home/runner/optimizer/functional_tests/optimizer_tests/scripts/validate_advanced_features.py}
        OPTIMIZER_DIR=${OPTIMIZER_DIR:-/opt/intel/dlstreamer/scripts/optimizer}

        # Set environment variables for host
        setup_host_environment
    fi
}

setup_host_environment() {
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
}

# Initialize environment
detect_environment

TOLERANCE=${CUSTOM_TOLERANCE:-5.0}
FINAL_REPORT="$RESULTS_DIR/FINAL_TEST_REPORT.txt"
EXECUTION_LOG="$RESULTS_DIR/execution.log"

# Enhanced colors and logging
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'
PURPLE='\033[0;35m'; CYAN='\033[0;36m'; NC='\033[0m'

# Logging functions
log_to_file() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$EXECUTION_LOG"
}

print_info() { 
    local msg="${BLUE}${ENV_PREFIX} [INFO]${NC} $1"
    echo -e "$msg"
    log_to_file "INFO: $1"
}

print_success() { 
    local msg="${GREEN}${ENV_PREFIX} [SUCCESS]${NC} $1"
    echo -e "$msg"
    log_to_file "SUCCESS: $1"
}

print_error() { 
    local msg="${RED}${ENV_PREFIX} [ERROR]${NC} $1"
    echo -e "$msg"
    log_to_file "ERROR: $1"
}

print_warning() { 
    local msg="${YELLOW}${ENV_PREFIX} [WARNING]${NC} $1"
    echo -e "$msg"
    log_to_file "WARNING: $1"
}

print_debug() {
    if [ "$VERBOSE_OUTPUT" = true ]; then
        local msg="${PURPLE}${ENV_PREFIX} [DEBUG]${NC} $1"
        echo -e "$msg"
        log_to_file "DEBUG: $1"
    fi
}

# Progress tracking
show_progress() {
    local current=$1
    local total=$2
    local test_name=$3
    local width=50
    local percentage=$((current * 100 / total))
    local filled=$((current * width / total))
    
    printf "\r${CYAN}Progress: [${NC}"
    printf "%*s" $filled | tr ' ' '█'
    printf "%*s" $((width - filled)) | tr ' ' '░'
    printf "${CYAN}] %d%% (%d/%d) %s${NC}" $percentage $current $total "$test_name"
    
    if [ $current -eq $total ]; then
        echo ""
    fi
}

# Enhanced configuration functions
load_test_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        print_error "Config file not found: $CONFIG_FILE"
        exit 1
    fi
    
    if ! command -v jq >/dev/null 2>&1; then
        print_error "jq is required to parse JSON config file"
        exit 1
    fi
    
    # Validate JSON syntax
    if ! jq empty "$CONFIG_FILE" 2>/dev/null; then
        print_error "Invalid JSON syntax in config file: $CONFIG_FILE"
        exit 1
    fi
    
    print_info "Loading test configuration from: $CONFIG_FILE"
    
    # Show config summary if verbose
    if [ "$VERBOSE_OUTPUT" = true ]; then
        local test_count=$(jq 'length' "$CONFIG_FILE")
        print_debug "Found $test_count test configurations"
    fi
}

get_test_names() {
    local all_tests=$(jq -r 'keys[]' "$CONFIG_FILE")
    
    # Apply filter if specified
    if [ -n "$TEST_FILTER" ]; then
        echo "$all_tests" | grep -i "$TEST_FILTER" || true
    else
        echo "$all_tests"
    fi
}

get_pipeline_to_test() {
    local test_name=$1
    local pipeline=$(jq -r ".[\"$test_name\"].pipeline_to_test" "$CONFIG_FILE")
    
    # Replace placeholders
    pipeline=${pipeline//\$MODELS_PATH/$MODELS_PATH}
    echo "$pipeline"
}

get_search_duration() {
    local test_name=$1
    local search_duration=$(jq -r ".[\"$test_name\"].search_duration // null" "$CONFIG_FILE")
    
    if [ "$search_duration" = "null" ] || [ -z "$search_duration" ]; then
        echo "$SEARCH_DURATION default"
    else
        echo "$search_duration config"
    fi
}

get_sample_duration() {
    local test_name=$1
    local sample_duration=$(jq -r ".[\"$test_name\"].sample_duration // null" "$CONFIG_FILE")
    
    if [ "$sample_duration" = "null" ] || [ -z "$sample_duration" ]; then
        echo ""
    else
        echo "$sample_duration"
    fi
}

get_test_type() {
    local test_name=$1
    local test_type=$(jq -r ".[\"$test_name\"].test_type // \"standard\"" "$CONFIG_FILE")
    echo "$test_type"
}

get_additional_flags() {
    local test_name=$1
    local flags=$(jq -r ".[\"$test_name\"].additional_flags[]? // empty" "$CONFIG_FILE" | tr '\n' ' ')
    echo "$flags"
}

get_mode() {
    local test_name=$1
    local mode=$(jq -r ".[\"$test_name\"].mode // \"fps\"" "$CONFIG_FILE")
    echo "$mode"
}

# Enhanced prerequisite checks
check_prerequisites() {
    print_info "Checking prerequisites..."
    
    local errors=0
    
    # Check directories
    if [ ! -d "$OPTIMIZER_DIR" ]; then
        print_error "Optimizer directory not found: $OPTIMIZER_DIR"
        ((errors++))
    fi
    
    if [ ! -f "$OPTIMIZER_DIR/__main__.py" ]; then
        print_error "Optimizer __main__.py not found"
        ((errors++))
    fi
    
    # Check scripts
    if [ ! -f "$COMPARE_SCRIPT" ]; then
        print_error "Compare script not found: $COMPARE_SCRIPT"
        ((errors++))
    fi
    
    if [ ! -f "$CONFIG_FILE" ]; then
        print_error "Config file not found: $CONFIG_FILE"
        ((errors++))
    fi
    
    # Check commands
    local required_commands=("python3" "jq")
    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" >/dev/null; then
            print_error "$cmd not found"
            ((errors++))
        fi
    done
    
    # Check models path for non-videotestsrc tests
    if [ ! -d "$MODELS_PATH" ]; then
        print_warning "Models path not found: $MODELS_PATH (videotestsrc tests will still work)"
    fi
    
    if [ $errors -gt 0 ]; then
        print_error "Found $errors prerequisite errors. Exiting."
        exit 1
    fi
    
    print_success "Prerequisites OK"
}

# Enhanced test execution with timeout and retry
execute_with_timeout() {
    local timeout_duration=$1
    local command="$2"
    local output_file="$3"
    
    print_debug "Executing with timeout ${timeout_duration}s: $command"
    
    if [ "$DRY_RUN" = true ]; then
        print_info "[DRY RUN] Would execute: $command"
        echo "# DRY RUN - Command would be executed here" > "$output_file"
        return 0
    fi
    
    # Use timeout command if available
    if command -v timeout >/dev/null 2>&1; then
        timeout "$timeout_duration" bash -c "$command" > "$output_file" 2>&1
    else
        eval "$command" > "$output_file" 2>&1
    fi
}

test_pipeline() {
    local test_name=$1
    local pipeline=$2
    local output_file="$RESULTS_DIR/${test_name}_full_output.txt"
    
    local search_duration_raw=$(get_search_duration "$test_name")
    local search_duration=$(echo "$search_duration_raw" | awk '{print $1}')
    local search_duration_src=$(echo "$search_duration_raw" | awk '{print $2}')
    local sample_duration=$(get_sample_duration "$test_name")
    
    print_info "Testing pipeline: $test_name"
    print_debug "Search duration: ${search_duration}s (from ${search_duration_src})"
    
    if [ -n "$sample_duration" ]; then
        print_debug "Sample duration: ${sample_duration}s (from config)"
    fi
    
    print_debug "Pipeline: $pipeline"
    
    cd "$OPTIMIZER_DIR"
    
    local optimizer_cmd="python3 . fps --search-duration $search_duration"
    
    if [ -n "$sample_duration" ]; then
        optimizer_cmd="$optimizer_cmd --sample-duration $sample_duration"
    fi
    
    optimizer_cmd="$optimizer_cmd -- $pipeline"
    
    print_debug "Running: $optimizer_cmd"
    
    # Calculate timeout (search_duration + 60s buffer)
    local timeout_duration=$((search_duration + 60))
    
    if execute_with_timeout "$timeout_duration" "$optimizer_cmd" "$output_file"; then
        print_success "Optimizer completed for $test_name"
        return 0
    else
        print_error "Optimizer failed for $test_name"
        return 1
    fi
}

test_pipeline_advanced() {
    local test_name=$1
    local pipeline=$2
    local output_file="$RESULTS_DIR/${test_name}_full_output.txt"
    local timing_file="$RESULTS_DIR/${test_name}_timing.txt"
    
    local search_duration_raw=$(get_search_duration "$test_name")
    local search_duration=$(echo "$search_duration_raw" | awk '{print $1}')
    local search_duration_src=$(echo "$search_duration_raw" | awk '{print $2}')
    local sample_duration=$(get_sample_duration "$test_name")
    local test_type=$(get_test_type "$test_name")
    local additional_flags=$(get_additional_flags "$test_name")
    local mode=$(get_mode "$test_name")
    
    print_info "Testing pipeline: $test_name (type: $test_type)"
    print_debug "Mode: $mode | Duration: ${search_duration}s (${search_duration_src})"
    
    if [ -n "$sample_duration" ]; then
        print_debug "Sample duration: ${sample_duration}s"
    fi
    
    if [ -n "$additional_flags" ]; then
        print_debug "Additional flags: $additional_flags"
    fi
    
    cd "$OPTIMIZER_DIR"
    
    local optimizer_cmd="python3 . $mode --search-duration $search_duration"
    
    if [ -n "$sample_duration" ]; then
        optimizer_cmd="$optimizer_cmd --sample-duration $sample_duration"
    fi
    
    if [ -n "$additional_flags" ]; then
        optimizer_cmd="$optimizer_cmd $additional_flags"
    fi
    
    # Add output flag for tests that need it
    if [[ "$test_type" == *"output"* ]] || [[ "$test_type" == *"modifications"* ]] || [[ "$test_type" == *"cross_stream"* ]] || [[ "$test_type" == *"allowed_devices"* ]]; then
        local json_output_file="$RESULTS_DIR/${test_name}_output.json"
        optimizer_cmd="$optimizer_cmd --output $json_output_file"
    fi
    
    if [[ "$test_type" == "verbose_flag" ]]; then
        optimizer_cmd="$optimizer_cmd --verbose"
    fi
    
    optimizer_cmd="$optimizer_cmd -- $pipeline"
    
    print_debug "Running: $optimizer_cmd"
    
    local timeout_duration=$((search_duration + 60))
    
    if [[ "$test_type" == "search_duration_timing" ]]; then
        local start_time=$(date +%s)
        if execute_with_timeout "$timeout_duration" "$optimizer_cmd" "$output_file"; then
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            echo "$duration" > "$timing_file"
            echo "$test_name:$duration" >> "$RESULTS_DIR/timing_results.txt"
            print_success "Optimizer completed for $test_name in ${duration}s"
            return 0
        else
            print_error "Optimizer failed for $test_name"
            return 1
        fi
    else
        if execute_with_timeout "$timeout_duration" "$optimizer_cmd" "$output_file"; then
            print_success "Optimizer completed for $test_name"
            return 0
        else
            print_error "Optimizer failed for $test_name"
            return 1
        fi
    fi
}

run_comparison() {
    local test_name=$1
    local output_file="$RESULTS_DIR/${test_name}_full_output.txt"
    
    print_debug "Running comparison for $test_name"
    
    if [ "$DRY_RUN" = true ]; then
        print_info "[DRY RUN] Would run comparison for $test_name"
        return 0
    fi
    
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
}

run_comparison_advanced() {
    local test_name=$1
    local output_file="$RESULTS_DIR/${test_name}_full_output.txt"
    local test_type=$(get_test_type "$test_name")
    
    print_debug "Running comparison for $test_name (type: $test_type)"
    
    if [ "$DRY_RUN" = true ]; then
        print_info "[DRY RUN] Would run advanced comparison for $test_name"
        return 0
    fi
    
    case "$test_type" in
        "search_duration_timing")
            local timing_file="$RESULTS_DIR/${test_name}_timing.txt"
            if [ -f "$timing_file" ]; then
                local duration=$(cat "$timing_file")
                print_debug "Test $test_name completed in ${duration}s"
                return 0
            else
                print_error "Timing file not found for $test_name"
                return 1
            fi
            ;;
        "sample_duration_candidates")
            print_success "Sample duration test $test_name completed"
            return 0
            ;;
        *)
            local json_output_file="$RESULTS_DIR/${test_name}_output.json"
            
            if [ ! -f "$VALIDATION_SCRIPT" ]; then
                print_debug "Advanced validation script not found, using basic validation"
                return run_basic_advanced_validation "$test_name" "$json_output_file" "$test_type"
            fi
            
            local validation_cmd="python3 $VALIDATION_SCRIPT \
                --output-file $json_output_file \
                --config-file $CONFIG_FILE \
                --test-name $test_name"
            
            if [[ "$test_type" == "verbose_flag" ]]; then
                validation_cmd="$validation_cmd --log-file $output_file"
            fi
            
            if eval "$validation_cmd"; then
                print_success "Advanced validation passed for $test_name"
                return 0
            else
                print_error "Advanced validation failed for $test_name"
                return 1
            fi
            ;;
    esac
}

run_basic_advanced_validation() {
    local test_name=$1
    local json_output_file=$2
    local test_type=$3
    
    if [ -f "$json_output_file" ] || [ -f "$RESULTS_DIR/${test_name}_full_output.txt" ]; then
        print_success "Basic validation passed for $test_name (output file exists)"
        return 0
    else
        print_error "Basic validation failed for $test_name (no output file)"
        return 1
    fi
}

run_quick_advanced_tests() {
    print_info "========== QUICK ADVANCED TESTS =========="
    
    local advanced_tests=(
        "output_flag_basic"
        "fps_mode_modifications" 
        "streams_mode_modifications"
        "verbose_flag_test"
        "search_duration_short"
        "search_duration_long"
        "sample_duration_short"
        "sample_duration_long"
        "cross_stream_batching"
        "allowed_devices_cpu_only"
    )
    
    local advanced_count=0
    for test_name in "${advanced_tests[@]}"; do
        if jq -e ".[\"$test_name\"]" "$CONFIG_FILE" >/dev/null 2>&1; then
            ((advanced_count++))
        fi
    done
    
    local current_advanced=0
    
    for test_name in "${advanced_tests[@]}"; do
        if ! jq -e ".[\"$test_name\"]" "$CONFIG_FILE" >/dev/null 2>&1; then
            print_debug "Skipping $test_name (not in config)"
            continue
        fi
        
        ((current_advanced++))
        TOTAL_TESTS=$((TOTAL_TESTS + 1))
        
        show_progress $current_advanced $advanced_count "$test_name"
        print_info "========== Test $TOTAL_TESTS: $test_name (Advanced) =========="
        
        pipeline=$(get_pipeline_to_test "$test_name")
        if [ -z "$pipeline" ] || [ "$pipeline" = "null" ]; then
            print_error "No pipeline found for test: $test_name"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            continue
        fi
        
        if test_pipeline_advanced "$test_name" "$pipeline"; then
            if run_comparison_advanced "$test_name"; then
                PASSED_TESTS=$((PASSED_TESTS + 1))
            else
                FAILED_TESTS=$((FAILED_TESTS + 1))
            fi
        else
            FAILED_TESTS=$((FAILED_TESTS + 1))
        fi
    done
    
    run_quick_post_processing
}

run_quick_post_processing() {
    print_info "Running post-processing comparisons..."
    
    if [ "$DRY_RUN" = true ]; then
        print_info "[DRY RUN] Would run post-processing comparisons"
        return
    fi
    
    # Timing comparison
    local timing_file="$RESULTS_DIR/timing_results.txt"
    if [ -f "$timing_file" ]; then
        local short_time=$(grep "search_duration_short:" "$timing_file" 2>/dev/null | cut -d: -f2)
        local long_time=$(grep "search_duration_long:" "$timing_file" 2>/dev/null | cut -d: -f2)
        
        if [ -n "$short_time" ] && [ -n "$long_time" ]; then
            if [ "$long_time" -gt "$short_time" ]; then
                print_success "Timing validation: ✅ (${short_time}s < ${long_time}s)"
            else
                print_error "Timing validation: ❌ (${short_time}s >= ${long_time}s)"
                FAILED_TESTS=$((FAILED_TESTS + 1))
            fi
        fi
    fi
    
    # Sample duration comparison
    local short_out="$RESULTS_DIR/sample_duration_short_output.json"
    local long_out="$RESULTS_DIR/sample_duration_long_output.json"
    
    if [ -f "$short_out" ] && [ -f "$long_out" ]; then
        local short_size=$(wc -c < "$short_out" 2>/dev/null || echo "0")
        local long_size=$(wc -c < "$long_out" 2>/dev/null || echo "0")
        
        if [ "$short_size" != "$long_size" ]; then
            print_success "Sample duration validation: ✅ (different output sizes)"
        else
            print_info "Sample duration validation: ⚠️  (same output sizes - may be OK)"
        fi
    fi
}

# Enhanced summary with detailed statistics
generate_summary() {
    local end_time=$(date +%s)
    local duration=$((end_time - START_TIME))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))
    
    print_info "========== FINAL SUMMARY =========="
    print_info "Environment: $ENV_TYPE"
    print_info "Execution time: ${minutes}m ${seconds}s"
    print_info "Total tests: $TOTAL_TESTS"
    print_info "Passed: $PASSED_TESTS"
    print_info "Failed: $FAILED_TESTS"
    
    if [ $TOTAL_TESTS -gt 0 ]; then
        local success_rate=$(( (PASSED_TESTS * 100) / TOTAL_TESTS ))
        print_info "Success rate: ${success_rate}%"
    fi
    
    print_info "Results directory: $RESULTS_DIR"
    print_info "Final report: $FINAL_REPORT"
    print_info "Execution log: $EXECUTION_LOG"
    
    if [ $FAILED_TESTS -eq 0 ]; then
        print_success "ALL TESTS PASSED! 🎉"
        return 0
    else
        print_error "SOME TESTS FAILED! 💥"
        return 1
    fi
}

# Main execution
main() {
    local START_TIME=$(date +%s)
    
    print_info "Environment: $ENV_TYPE"
    print_info "Results: $RESULTS_DIR"
    print_info "Default Duration: ${SEARCH_DURATION}s"
    print_info "Tolerance: ${TOLERANCE}%"
    print_info "Config file: $CONFIG_FILE"
    
    if [ "$DRY_RUN" = true ]; then
        print_warning "DRY RUN MODE - No actual tests will be executed"
    fi
    
    if [ -n "$TEST_FILTER" ]; then
        print_info "Test filter: $TEST_FILTER"
    fi
    
    check_prerequisites
    load_test_config
    mkdir -p "$RESULTS_DIR"
    rm -f "$FINAL_REPORT" "$EXECUTION_LOG"
    
    # Initialize counters
    TOTAL_TESTS=0 PASSED_TESTS=0 FAILED_TESTS=0
    
    # Run standard tests (unless only-advanced is specified)
    if [ "$ONLY_ADVANCED" = false ]; then
        local standard_tests=()
        while IFS= read -r test_name; do
            local test_type=$(get_test_type "$test_name")
            if [[ "$test_type" == "standard" ]]; then
                standard_tests+=("$test_name")
            fi
        done < <(get_test_names)
        
        local standard_count=${#standard_tests[@]}
        local current_standard=0
        
        if [ $standard_count -gt 0 ]; then
            print_info "========== STANDARD TESTS ($standard_count tests) =========="
            
            for test_name in "${standard_tests[@]}"; do
                ((current_standard++))
                TOTAL_TESTS=$((TOTAL_TESTS + 1))
                
                show_progress $current_standard $standard_count "$test_name"
                print_info "========== Test $TOTAL_TESTS: $test_name =========="
                
                pipeline=$(get_pipeline_to_test "$test_name")
                if [ -z "$pipeline" ] || [ "$pipeline" = "null" ]; then
                    print_error "No pipeline found for test: $test_name"
                    FAILED_TESTS=$((FAILED_TESTS + 1))
                    continue
                fi
                
                if test_pipeline "$test_name" "$pipeline"; then
                    if run_comparison "$test_name"; then
                        PASSED_TESTS=$((PASSED_TESTS + 1))
                    else
                        FAILED_TESTS=$((FAILED_TESTS + 1))
                    fi
                else
                    FAILED_TESTS=$((FAILED_TESTS + 1))
                fi
            done
        fi
    fi
    
    # Run advanced tests (unless skip-advanced is specified)
    if [ "$SKIP_ADVANCED" = false ]; then
        run_quick_advanced_tests
    fi
    
    # Generate final summary
    generate_summary
}

# Execute main function
main "$@"
