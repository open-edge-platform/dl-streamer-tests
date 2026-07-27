#!/bin/bash
# ==============================================================================
# Copyright (C) 2025-2026 Intel Corporation
#
# SPDX-License-Identifier: MIT
# ==============================================================================

set -e

SCRIPTDIR="$(dirname "$(readlink -fm "$0")")"
RUN_PREFIX=""
OUTPUT_TYPE="json"
TEST_CONFIG_DIR="pipeline_test/configs_ov2"
TOOL_DEFAULT_PARAMS="-f --disable_tqdm --edistance_thr=0"
RUN_LOCAL_APTGET=false

show_help() {
    echo "usage: ./run_tests_new.sh --video-examples-path=<path> --models-path=<path> --meta-configs=<json> --platform-type=<type> [-- <additional tool parameters>]"
    echo "  --video-examples-path Path to folder with media files"
    echo "  --models-path         Path to folder with NN models"
    echo "  --meta-configs        Meta-configuration file(s) containing platform definitions"
    echo "                        Can be single file or space-separated list of files"
    echo "                        Should be located inside '$TEST_CONFIG_DIR' relative to this script"
    echo "                        Example: \"ri_tests_config.json\" or \"samples_config.json ri_tests_config.json\""
    echo "  --platform-type       Platform type to select from meta-config"
    echo "                        Example: \"icx\", \"tgl\", \"common\""
    echo "  --timeout             Timeout for tests"
    echo ""
    echo "  [--image-name]          Name of docker image"
    echo "  [--results-path=<path>] Path to folder for tests results"
    echo "  [--report-name=<name>]  Base name for test reports"
    echo "  [--on-host]             Run tests on local host, without docker image. DLS installed via apt on bare metal system."
    exit 0
}

error() {
    red=`tput -T xterm-256color setaf 1`
    reset=`tput -T xterm-256color sgr0`

    printf "${red}%s ${reset}%s\n" "$1" "$2" >&2
    exit 1
}

for i in "$@"
do
case $i in
    -h|--help)
        show_help
        exit 0
    ;;
    --video-examples-path=*)
        VIDEO_EXAMPLES_PATH="${i#*=}"
        shift
    ;;
    --models-path=*)
        MODELS_PATH="${i#*=}"
        shift
    ;;
    --image-name=*)
        IMAGE_NAME="${i#*=}"
        shift
    ;;
    --timeout=*)
        TIMEOUT="${i#*=}"
        shift
    ;;
    --meta-configs=*)
        META_CONFIGS="${i#*=}"
        shift
    ;;
    --platform-type=*)
        PLATFORM_TYPE="${i#*=}"
        shift
    ;;
    --results-path=*)
        RESULTS_PATH="${i#*=}"
        shift
    ;;
    --report-name=*)
        BASE_REPORT_NAME="${i#*=}"
        shift
    ;;
    --on-host)
        RUN_LOCAL_APTGET=true
        shift
    ;;
    --) # End of input
        shift; break
    ;;
    *) # unknown option
        error 'ERROR: Unknown option: ' $i
    ;;
esac
done

# Check required parameters
[ -z "$MODELS_PATH" ] && error 'ERROR: Path to models is not provided'
[ -z "$VIDEO_EXAMPLES_PATH" ] && error 'ERROR: Path to video examples is not provided'
[ -z "$META_CONFIGS" ] && error 'ERROR: Meta-configs file is not provided'
[ -z "$PLATFORM_TYPE" ] && error 'ERROR: Platform type is not provided'
if [[ "$RUN_LOCAL_APTGET" = false ]]; then
    [ -z "$IMAGE_NAME" ] && error 'ERROR: Target docker image name is not provided'
fi

# Set paths
# HOME_DIR - main DL Streamer directory
# TESTS_DIR - main DL Streamer test directory
# RESULTS_PATH - main results path (for XLSX report)
# RESULTS_METADATA_PATH - path for tests output json files
if [[ "$RUN_LOCAL_APTGET" = true ]]; then
    HOME_DIR=$SCRIPTDIR/../../../dlstreamer
    TESTS_DIR=$SCRIPTDIR

    [[ -z "$RESULTS_PATH" ]] && RESULTS_PATH="$TESTS_DIR/functional_tests_results"
    RESULTS_METADATA_PATH="$RESULTS_PATH/metadata"
    if [[ ! -d "$RESULTS_METADATA_PATH" ]]; then
        echo "Creating folder for results and metadata: $RESULTS_METADATA_PATH"
        $RUN_PREFIX mkdir -m 777 -p $RESULTS_METADATA_PATH
        $RUN_PREFIX chmod -R 777 $RESULTS_PATH
    fi
else
    # Docker paths
    HOME_DIR=/home/dlstreamer/dlstreamer
    TESTS_DIR=/home/dlstreamer/dlstreamer/functional_tests

    # Localhost paths
    LOCALHOST_TESTS_DIR=$SCRIPTDIR
    LOCALHOST_RESULTS_PATH=$RESULTS_PATH # Script's input arg RESULTS_PATH is a path on localhost, not in Docker
    [[ -z "$LOCALHOST_RESULTS_PATH" ]] && LOCALHOST_RESULTS_PATH="$LOCALHOST_TESTS_DIR/functional_tests_results"
    LOCALHOST_RESULTS_METADATA_PATH="$LOCALHOST_RESULTS_PATH/metadata"
    if [[ ! -d "$LOCALHOST_RESULTS_METADATA_PATH" ]]; then
        echo "Creating localhost folder for results and metadata: $LOCALHOST_RESULTS_METADATA_PATH"
        $RUN_PREFIX mkdir -p $LOCALHOST_RESULTS_METADATA_PATH
        $RUN_PREFIX chmod -R 777 $LOCALHOST_RESULTS_PATH
    fi

    # Docker paths
    RESULTS_PATH=/tmp/results
    RESULTS_METADATA_PATH=/tmp/results/metadata
fi
if [[ -z "$BASE_REPORT_NAME" ]]; then
    BASE_REPORT_NAME="test-results-report"
fi
echo "HOME_DIR: ${HOME_DIR}"
echo "TESTS_DIR: ${TESTS_DIR}"
echo "RESULTS_PATH: ${RESULTS_PATH}"
echo "RESULTS_METADATA_PATH: ${RESULTS_METADATA_PATH}"
echo "BASE_REPORT_NAME: ${BASE_REPORT_NAME}"

# Process meta-configs and generate final test configurations
echo "Platform type: $PLATFORM_TYPE"

# Create directory for modified configs (always on host)
if [[ "$RUN_LOCAL_APTGET" = true ]]; then
    HOST_MODIFIED_CONFIG_DIR="$TESTS_DIR/$TEST_CONFIG_DIR/generated_configs"
    DOCKER_MODIFIED_CONFIG_DIR="$TESTS_DIR/$TEST_CONFIG_DIR/generated_configs"
else
    HOST_MODIFIED_CONFIG_DIR="$LOCALHOST_TESTS_DIR/$TEST_CONFIG_DIR/generated_configs"
    DOCKER_MODIFIED_CONFIG_DIR="$TESTS_DIR/$TEST_CONFIG_DIR/generated_configs"
fi
MODIFIED_CONFIG_DIR="$HOST_MODIFIED_CONFIG_DIR"
mkdir -p "$MODIFIED_CONFIG_DIR"

# Initialize configs to run
CONFIGS_TO_RUN=""

# Parse space-separated meta-config files
read -ra meta_configs_arr <<<"$META_CONFIGS"
for meta_cfg in "${meta_configs_arr[@]}"; do
    # Always use host paths for meta-config processing
    if [[ "$RUN_LOCAL_APTGET" = true ]]; then
        META_CONFIGS_PATH="$TESTS_DIR/$TEST_CONFIG_DIR/$meta_cfg"
        BASE_CONFIG_BASE_DIR="$TESTS_DIR/$TEST_CONFIG_DIR"
    else
        META_CONFIGS_PATH="$LOCALHOST_TESTS_DIR/$TEST_CONFIG_DIR/$meta_cfg"
        BASE_CONFIG_BASE_DIR="$LOCALHOST_TESTS_DIR/$TEST_CONFIG_DIR"
    fi

    if [[ ! -f "$META_CONFIGS_PATH" ]]; then
        error "ERROR: Meta-config file ($meta_cfg) is not found at: " $'\n\t'"$META_CONFIGS_PATH"
    fi

    echo "Processing meta-config: $meta_cfg"

    # Extract platform configuration from meta-config JSON
    PLATFORM_CONFIG=$(jq --arg platform "$PLATFORM_TYPE" '.[$platform]' "$META_CONFIGS_PATH")

    if [ "$PLATFORM_CONFIG" = "null" ]; then
        error "ERROR: Platform type '$PLATFORM_TYPE' not found in meta-config file: $meta_cfg"
    fi

    # Extract base test config path
    BASE_TEST_CONFIG=$(echo "$PLATFORM_CONFIG" | jq -r '.test_config')

    if [ "$BASE_TEST_CONFIG" = "null" ] || [ -z "$BASE_TEST_CONFIG" ]; then
        error "ERROR: 'test_config' not defined for platform '$PLATFORM_TYPE' in meta-config: $meta_cfg"
    fi

    BASE_CONFIG_PATH="$BASE_CONFIG_BASE_DIR/$BASE_TEST_CONFIG"
    if [[ ! -f "$BASE_CONFIG_PATH" ]]; then
        error "ERROR: Base test config file ($BASE_TEST_CONFIG) is not found at: " $'\n\t'"$BASE_CONFIG_PATH"
    fi

    echo "  Base test config: $BASE_TEST_CONFIG"

    # Generate final config file name (include meta-config name to avoid conflicts)
    FINAL_CONFIG_NAME="${meta_cfg%.json}_${PLATFORM_TYPE}_final.json"
    HOST_FINAL_CONFIG_PATH="$MODIFIED_CONFIG_DIR/$FINAL_CONFIG_NAME"

    # For Docker, use Docker paths in CONFIGS_TO_RUN
    if [[ "$RUN_LOCAL_APTGET" = true ]]; then
        FINAL_CONFIG_PATH="$HOST_FINAL_CONFIG_PATH"
    else
        FINAL_CONFIG_PATH="$DOCKER_MODIFIED_CONFIG_DIR/$FINAL_CONFIG_NAME"
    fi

    echo "  Generating final config: $FINAL_CONFIG_NAME"

    # Copy base config to final config (always use host path for file operations)
    cp "$BASE_CONFIG_PATH" "$HOST_FINAL_CONFIG_PATH"

    # Apply additions to test_set_properties
    ADDITIONS=$(echo "$PLATFORM_CONFIG" | jq -r '.test_set_properties_additions // {}')
    if [ "$ADDITIONS" != "{}" ] && [ "$ADDITIONS" != "null" ]; then
        echo "  Applying test_set_properties additions..."

        # Add each key-value pair from additions
        echo "$ADDITIONS" | jq -r 'to_entries[] | "\(.key)=\(.value|tostring)"' | while IFS='=' read -r key value; do
            echo "    Adding: $key = $value"
            # Use --argjson for proper JSON value handling (arrays, objects, etc.)
            jq --arg key "$key" --argjson value "$(echo "$ADDITIONS" | jq ".\"$key\"")" \
               '.test_set_properties[$key] = $value' \
               "$HOST_FINAL_CONFIG_PATH" > "$HOST_FINAL_CONFIG_PATH.tmp" && mv "$HOST_FINAL_CONFIG_PATH.tmp" "$HOST_FINAL_CONFIG_PATH"
        done
    fi

    # Apply removals from test_set_properties
    REMOVALS=$(echo "$PLATFORM_CONFIG" | jq -r '.test_set_properties_removals // []')
    if [ "$REMOVALS" != "[]" ] && [ "$REMOVALS" != "null" ]; then
        echo "  Applying test_set_properties removals..."

        # Remove each key from removals array
        echo "$REMOVALS" | jq -r '.[]' | while read -r key; do
            echo "    Removing: $key"
            jq --arg key "$key" \
               'del(.test_set_properties[$key])' \
               "$HOST_FINAL_CONFIG_PATH" > "$HOST_FINAL_CONFIG_PATH.tmp" && mv "$HOST_FINAL_CONFIG_PATH.tmp" "$HOST_FINAL_CONFIG_PATH"
        done
    fi

    # Apply test exclusions by name
    EXCLUDED_TESTS=$(echo "$PLATFORM_CONFIG" | jq -r '.excluded_tests // []')
    if [ "$EXCLUDED_TESTS" != "[]" ] && [ "$EXCLUDED_TESTS" != "null" ]; then
        echo "  Applying test exclusions..."

        # Remove each test by name from test_sets
        echo "$EXCLUDED_TESTS" | jq -r '.[]' | while read -r test_name; do
            echo "    Excluding test: $test_name"
            jq --arg test_name "$test_name" \
               'del(.test_sets[] | select(.name == $test_name))' \
               "$HOST_FINAL_CONFIG_PATH" > "$HOST_FINAL_CONFIG_PATH.tmp" && mv "$HOST_FINAL_CONFIG_PATH.tmp" "$HOST_FINAL_CONFIG_PATH"
        done
    fi

    # Add final config to the list
    CONFIGS_TO_RUN+="$FINAL_CONFIG_PATH "
    echo "  Generated: $HOST_FINAL_CONFIG_PATH"
done

echo "Final configs to run: $CONFIGS_TO_RUN"

# Run command for tool
RUN_CMD="$TESTS_DIR/pipeline_test/entry_point.sh -c ${CONFIGS_TO_RUN} "
RUN_CMD+="--xml-report $RESULTS_PATH/$BASE_REPORT_NAME.xml "
RUN_CMD+="--xlsx-report $RESULTS_PATH/$BASE_REPORT_NAME.xlsx "
RUN_CMD+="$TOOL_DEFAULT_PARAMS "
RUN_CMD+="--results-path $RESULTS_METADATA_PATH "

# Add environment context flag for config processing
if [[ "$RUN_LOCAL_APTGET" = true ]]; then
    RUN_CMD+="--env-context host "
else
    RUN_CMD+="--env-context docker "
fi

if [[ -n "$TIMEOUT" ]]; then
    if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]]; then
        error "Incorrectly defined timeout"
    fi
    RUN_CMD+="--timeout $TIMEOUT "
fi
RUN_CMD+="$*" # Remaining options

# Check if NPU device acceleration is available
DEVICE_ACCEL=""
if ls /dev/accel* >/dev/null 2>&1; then
    DEVICE_ACCEL="--device /dev/accel"
    echo "NPU device acceleration enabled"
else
    echo "NPU device acceleration not enabled"
fi
echo ""

# Extra parameters for docker run
EXTRA_PARAMS=""
RENDER_GROUP_ID=$(getent group render | awk -F: '{printf "%s\n", $3}')
if [[ -n "$RENDER_GROUP_ID" ]]; then
    EXTRA_PARAMS+="--group-add $RENDER_GROUP_ID "
fi


# Run tests in local host enviroment without docker image
if [[ "$RUN_LOCAL_APTGET" = true ]]; then
    echo "*************************** RUNNING ON HOST TESTS ***************************"

    # create symbolic links
    echo "Creating symbolic link to: $RESULTS_PATH"
    if [ -L /tmp/results ]; then
        rm -r /tmp/results
    fi
    if [ ! -d "$RESULTS_METADATA_PATH" ]; then
        error "ERROR: Results path does not exist: $RESULTS_METADATA_PATH"
    fi
    ln -s $RESULTS_METADATA_PATH /tmp/results

    echo "Creating symbolic link to: $VIDEO_EXAMPLES_PATH"
    if [ -L /tmp/video-examples ]; then
        rm -r /tmp/video-examples
    fi
    if [ ! -d "$VIDEO_EXAMPLES_PATH" ]; then
        error "ERROR: Video examples path does not exist: $VIDEO_EXAMPLES_PATH"
    fi
    ln -s $VIDEO_EXAMPLES_PATH /tmp/video-examples

    # adjust directories to local enviroment as necessary
    echo "Running tests at local system with DLS installed via apt-get"

    # Set base environment variables using the DL Streamer setup script
    DLS_ENV_SCRIPT=${DLS_ENV_SCRIPT:-/opt/intel/dlstreamer/scripts/setup_dls_env.sh}
    if [ -f "$DLS_ENV_SCRIPT" ]; then
        # shellcheck source=/dev/null
        source "$DLS_ENV_SCRIPT"
    else
        error "ERROR: DL Streamer environment script not found: " $'\n\t'"$DLS_ENV_SCRIPT"
    fi

    # Test-specific overrides not covered by the setup script
    export TERM=xterm
    export PYTHONPATH=$HOME_DIR/python:$PYTHONPATH
    export PATH=$HOME_DIR/.virtualenvs/dlstreamer/bin:$PATH
    export LABELS_PATH=/opt/intel/dlstreamer/samples/labels
    export MODEL_PROC_PATH=/opt/intel/dlstreamer/samples/gstreamer/model_proc
    export MODEL_PROCS_PATH=/opt/intel/dlstreamer/samples/gstreamer/model_proc
    export MODELS_PATH=$MODELS_PATH
    echo "LIBVA_DRIVER_NAME: ${LIBVA_DRIVER_NAME}"
    echo "GST_PLUGIN_PATH: ${GST_PLUGIN_PATH}"
    echo "LD_LIBRARY_PATH: ${LD_LIBRARY_PATH}"
    echo "LIBVA_DRIVERS_PATH: ${LIBVA_DRIVERS_PATH}"
    echo "GST_VA_ALL_DRIVERS: ${GST_VA_ALL_DRIVERS}"
    echo "MODEL_PROCS_PATH: ${MODEL_PROC_PATH}"
    echo "LABELS_PATH: ${LABELS_PATH}"
    echo "PYTHONPATH: ${PYTHONPATH}"
    echo "PATH: ${PATH}"
    echo "TERM: ${TERM}"
    echo "MODELS_PATH: ${MODELS_PATH}"
    echo "GST_VAAPI_DRM_DEVICE: ${GST_VAAPI_DRM_DEVICE}"
    echo "GST_VAAPI_ALL_DRIVERS: ${GST_VAAPI_ALL_DRIVERS}"
    echo "GI_TYPELIB_PATH: ${GI_TYPELIB_PATH}"
    echo "Starting test in local host mode"

    # Run on host tests
    bash $RUN_CMD
    echo "*************************** EXECUTION FINISHED ***************************"

    # Clean-up
    if [ -L /tmp/results ]; then
        rm -r /tmp/results
        echo "Removed symbolic link /tmp/results"
    fi
    if [ -L /tmp/video-examples ]; then
        rm -r /tmp/video-examples
        echo "Removed symbolic link /tmp/video-examples"
    fi
    exit
else
    echo "*************************** RUNNING DOCKER TESTS ***************************"

    # Run Docker
    echo "Starting Docker..."
    [ -z "$RUN_PREFIX" ] && set -x
    $RUN_PREFIX docker run --rm \
        --device=/dev/dri \
        $DEVICE_ACCEL \
        -v $VIDEO_EXAMPLES_PATH:/tmp/video-examples \
        -v $LOCALHOST_RESULTS_PATH:/tmp/results \
        -v $MODELS_PATH:/tmp/models \
        -v $(dirname "$(realpath "${BASH_SOURCE[0]}")")/:$TESTS_DIR \
        -v $HOST_MODIFIED_CONFIG_DIR:$DOCKER_MODIFIED_CONFIG_DIR \
        -e MODELS_PATH=/tmp/models \
        -e MODEL_PROC_PATH=/home/dlstreamer/dlstreamer/samples/gstreamer/model_proc \
        -e MODEL_PROCS_PATH=/home/dlstreamer/dlstreamer/samples/gstreamer/model_proc \
        -e LABELS_PATH=/home/dlstreamer/dlstreamer/samples/labels \
        $EXTRA_PARAMS \
        $IMAGE_NAME \
        $RUN_CMD

    echo "*************************** EXECUTION FINISHED ***************************"
fi
