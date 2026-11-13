#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

# =============================================================================
# 1. COMMAND-LINE OPTIONS AND REQUIREMENTS
# =============================================================================

DECODER=all
MODE=all
INFERENCE_MODE=CPU
GPU_TELEMETRY=intel_gpu_top
OUTPUT=none
DESCRIPTION=false
GPU_INTERVAL_MS=${GPU_INTERVAL_MS:-100}
GPU_DEVICE=${GPU_DEVICE:-}

show_help() {
  cat << 'HELP'
Usage: ./benchmark.sh [OPTIONS]

Benchmark GStreamer / Intel DL Streamer video decoders at 360p and 1080p.

Options:
  --decoder NAME          avdec_h264 | openh264dec | vah264dec | vavp9dec |
                          vaav1dec | all                       (default: all)
  --mode NAME             decode | decode-inference | all      (default: all)
  --inference-device NAME   CPU | GPU | ALL                       (default: CPU)
                          CPU: all decoders run inference on CPU.
                          GPU: vah264dec, vavp9dec and vaav1dec run inference
                               on GPU; other decoders still use CPU.
                          ALL: run CPU inference for every decoder, plus GPU
                               inference for those three hardware decoders.
                          Applies only to decode-inference; case-insensitive.
  --gpu-telemetry NAME    intel_gpu_top | qmassa                (default: intel_gpu_top)
  --output NAME           none | xlsx                          (default: none)
  --description           Show codec descriptions and exit
  --help                  Show this message and exit

Examples:
  ./benchmark.sh
  ./benchmark.sh --decoder vah264dec --mode decode
  ./benchmark.sh --mode decode-inference --inference-device ALL --output xlsx
  ./benchmark.sh --description
  ./benchmark.sh --gpu-telemetry qmassa --mode decode-inference
  ./benchmark.sh --decoder all --gpu-telemetry intel_gpu_top --output xlsx

Requirements: source the DL Streamer setup script before running this tool.
For inference, export MODELS_PATH to the models directory. See README.md.
HELP
}

parse_arguments() {
  while (($# > 0)); do
    case "$1" in
      --help | -h)
        show_help
        exit 0
        ;;
      --description)
        DESCRIPTION=true
        shift
        ;;
      --decoder | --mode | --inference-device | --gpu-telemetry | --output)
        if (($# < 2)) || [[ "$2" == --* ]]; then
          echo "Missing value for $1 (see --help)" >&2
          exit 2
        fi
        case "$1" in
          --decoder) DECODER=$2 ;;
          --mode) MODE=$2 ;;
          --inference-device) INFERENCE_MODE=$2 ;;
          --gpu-telemetry) GPU_TELEMETRY=$2 ;;
          --output) OUTPUT=$2 ;;
        esac
        shift 2
        ;;
      *)
        echo "Unknown argument: $1 (see --help)" >&2
        exit 2
        ;;
    esac
  done

  if [[ "$DESCRIPTION" == true ]]; then
    show_codec_descriptions
    exit 0
  fi

  case "$DECODER" in
    avdec_h264 | openh264dec | vah264dec | vavp9dec | vaav1dec | all) ;;
    *)
      echo "Invalid --decoder: $DECODER" >&2
      exit 2
      ;;
  esac
  case "$MODE" in
    decode | decode-inference | all) ;;
    *)
      echo "Invalid --mode: $MODE" >&2
      exit 2
      ;;
  esac
  INFERENCE_MODE=${INFERENCE_MODE^^}
  case "$INFERENCE_MODE" in
    CPU | GPU | ALL) ;;
    *)
      echo "Invalid --inference-device: $INFERENCE_MODE (use CPU, GPU or ALL)" >&2
      exit 2
      ;;
  esac
  case "$GPU_TELEMETRY" in
    intel_gpu_top | qmassa) ;;
    *)
      echo "Invalid --gpu-telemetry: $GPU_TELEMETRY" >&2
      exit 2
      ;;
  esac
  case "$OUTPUT" in
    none | xlsx) ;;
    *)
      echo "Invalid --output: $OUTPUT" >&2
      exit 2
      ;;
  esac
  if ! [[ "$GPU_INTERVAL_MS" =~ ^[1-9][0-9]*$ ]]; then
    echo 'GPU_INTERVAL_MS must be a positive integer' >&2
    exit 2
  fi
}

check_requirements() {
  local cmd
  for cmd in gst-launch-1.0 gst-inspect-1.0 awk setsid date mkfifo ps; do
    command -v "$cmd" > /dev/null || {
      echo "Missing: $cmd (see README.md)" >&2
      exit 1
    }
  done
  gst-inspect-1.0 gvafpscounter > /dev/null 2>&1 || {
    echo 'DL Streamer not configured: source setup_dls_env.sh (see README.md)' >&2
    exit 1
  }

  if [[ "$MODE" != decode ]]; then
    : "${MODELS_PATH:?Export MODELS_PATH before running inference (see README.md)}"
    MODEL_XML="$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml"
    [[ -f "$MODEL_XML" ]] || {
      echo "Model not found: $MODEL_XML" >&2
      exit 1
    }
    gst-inspect-1.0 gvadetect > /dev/null 2>&1 || {
      echo 'Missing DL Streamer plugin: gvadetect' >&2
      exit 1
    }
  fi

  if [[ "$GPU_TELEMETRY" == intel_gpu_top ]]; then
    for cmd in intel_gpu_top sudo stdbuf; do
      command -v "$cmd" > /dev/null || {
        echo "Missing: $cmd" >&2
        exit 1
      }
    done
  else
    for cmd in qmassa jq; do
      command -v "$cmd" > /dev/null || {
        echo "Missing: $cmd (see README.md)" >&2
        exit 1
      }
    done
  fi

  if [[ "$OUTPUT" == xlsx ]]; then
    [[ -f generate_report.py ]] || {
      echo 'Missing generate_report.py' >&2
      exit 1
    }
    REPORT_PYTHON=python3
    [[ ! -x .venv/bin/python ]] || REPORT_PYTHON=.venv/bin/python
    command -v "$REPORT_PYTHON" > /dev/null || {
      echo 'Missing Python 3 for XLSX output' >&2
      exit 1
    }
    "$REPORT_PYTHON" -c 'import openpyxl' > /dev/null 2>&1 || {
      echo 'Missing openpyxl for XLSX output (see README.md)' >&2
      exit 1
    }
  fi
}

prepare_runtime() {
  cd "$(dirname "$0")"
  TMP_DIR=$(mktemp -d)
  GST_PID= GPU_PID= GPU_READER_PID= TIMER_PID=
  GPU_MONITOR_PID_FILE= GPU_QMASSA_PID_FILE=
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  # Append _02, _03, etc. only if another run used the same timestamp.
  local folder_name suffix=2
  folder_name="$(date +%Y-%m-%d_%H-%M-%S)_${GPU_TELEMETRY}"
  mkdir -p results
  RESULTS_DIR="results/$folder_name"
  while ! mkdir "$RESULTS_DIR" 2> /dev/null; do
    RESULTS_DIR=$(printf 'results/%s_%02d' "$folder_name" "$suffix")
    ((suffix += 1))
  done
  mkdir -p "$RESULTS_DIR/logs"
  GST_LOG="$RESULTS_DIR/logs/pipeline.log"
  GPU_FILE="$RESULTS_DIR/logs/gpu.tsv"
  : > "$GST_LOG"
  printf 'pipeline\ttimestamp_ms\tdevice\tvcs\tvecs\n' > "$GPU_FILE"

  if [[ "$OUTPUT" == xlsx ]]; then
    CSV="$RESULTS_DIR/benchmark.csv"
    printf '%s\n' 'resolution,codec,decoder,mode,inference_device,gpu_telemetry,status,elapsed_s,fps_avg,cpu_avg_pct,vcs_avg_pct,vcs_max_pct,vecs_avg_pct,vecs_max_pct,gpu_samples,gpu_status,log_file,gpu_file' > "$CSV"
  fi

  if [[ "$GPU_TELEMETRY" == intel_gpu_top ]]; then
    # GPU performance counters may require elevated privileges.
    sudo -v
  fi
}

# Print basic codec information only when requested. This does not change tests.
show_codec_descriptions() {
  [[ "$DESCRIPTION" == true ]] || return 0

  printf '\nVideo codec descriptions:\n'
  if [[ "$DECODER" == all || "$DECODER" == avdec_h264 ||
    "$DECODER" == openh264dec || "$DECODER" == vah264dec ]]; then
    printf '  H.264 (AVC):\n'
    printf '    A widely supported video compression standard used in streaming,\n'
    printf '    video conferencing, cameras, and MP4 files. It offers broad device\n'
    printf '    compatibility and can be decoded in software or by dedicated hardware.\n'
    printf '    This benchmark compares avdec_h264 and openh264dec (CPU) with\n'
    printf '    vah264dec (Intel GPU via VA-API).\n\n'
  fi
  if [[ "$DECODER" == all || "$DECODER" == vavp9dec ]]; then
    printf '  VP9:\n'
    printf '    An open, royalty-free video codec developed by Google and commonly\n'
    printf '    used for online video, including high-resolution streaming. It generally\n'
    printf '    compresses more efficiently than H.264, but decoding can be more\n'
    printf '    computationally demanding without hardware acceleration.\n'
    printf '    This benchmark uses vavp9dec (Intel GPU via VA-API).\n\n'
  fi
  if [[ "$DECODER" == all || "$DECODER" == vaav1dec ]]; then
    printf '  AV1:\n'
    printf '    A modern, open, royalty-free video codec developed by the Alliance\n'
    printf '    for Open Media. It targets high compression efficiency, especially\n'
    printf '    for high-resolution streaming, typically requiring more decoding work\n'
    printf '    than older codecs when hardware acceleration is unavailable.\n'
    printf '    This benchmark uses vaav1dec (Intel GPU via VA-API).\n'
  fi
  printf '\n'
}

# =============================================================================
# 2. GSTREAMER PIPELINES AND FPS
# =============================================================================

build_pipeline() {
  local input="$1" codec="$2" decoder="$3" mode="$4" inference_device="$5"
  # An array keeps each argument separate (including paths with spaces).
  PIPELINE=(gst-launch-1.0 filesrc "location=$input" '!' qtdemux '!')
  PIPELINE+=("${codec}parse" '!' "$decoder" '!')

  if [[ "$mode" == decode ]]; then
    PIPELINE+=(gvafpscounter '!' fakesink sync=false)
  else
    PIPELINE+=(gvadetect "model=$MODEL_XML" "device=$inference_device" '!' queue '!')
    if [[ "$codec" == h264 ]]; then
      PIPELINE+=(vapostproc '!')
    fi
    PIPELINE+=(gvawatermark '!' videoconvertscale '!' gvafpscounter '!' fakesink sync=false)
  fi
}

read_fps() {
  # gvafpscounter prints an overall FPS value with 'total=' in the log.
  awk '/FpsCounter\(overall / && /total=/ {
        value=$0
        sub(/.*total=/, "", value)
        sub(/[^0-9.].*/, "", value)
        fps=value
    } END {if (fps != "") print fps; else print "NA"}' "$RUN_LOG"
}

# =============================================================================
# 3. CPU MONITORING (/proc/stat)
# =============================================================================

get_cpu_counters() {
  # /proc/stat contains cumulative CPU time counters since boot.
  # The first line aggregates all logical CPU cores (whole-system usage).
  # Fields 2-9: user, nice, system, idle, iowait, irq, softirq, steal.
  # Exclude guest and guest_nice (fields 10-11): Linux already includes
  # these times in user and nice, so summing them would count time twice.
  # Fields 5-6 (idle + iowait) are treated as non-busy time.
  awk '/^cpu / {
        total=0
        for (i=2; i<=9; i++) total+=$i
        print total, $5+$6
        exit
    }' /proc/stat
}

calculate_cpu_usage() {
  local start_total="$1" start_idle="$2" end_total="$3" end_idle="$4"
  # Two counter snapshots give the mean CPU usage over the pipeline runtime.
  # CPU % = 100 * (delta_total - delta_idle) / delta_total.
  # This includes OTHER system processes, not only GStreamer.
  awk -v total="$((end_total - start_total))" -v idle="$((end_idle - start_idle))" \
    'BEGIN {if (total > 0) printf "%.2f", 100*(total-idle)/total; else print "NA"}'
}

# =============================================================================
# 4. GPU MONITORING: intel_gpu_top OR qmassa
# Both backends normalize samples to: pipeline, timestamp_ms, device, vcs, vecs.
# intel_gpu_top: timestamp_ms is the local time when each CSV row is received.
# This is a reception timestamp, not the exact GPU measurement time.
# =============================================================================

start_intel_gpu_top() {
  sudo -v # Long tests may outlast the sudo credential cache.
  GPU_RAW="$TMP_DIR/intel_gpu_top.csv"
  GPU_ERROR="$TMP_DIR/gpu.error"
  GPU_PIPE="$TMP_DIR/intel_gpu_top.fifo"
  GPU_MONITOR_PID_FILE="$TMP_DIR/intel_gpu_top.pid"
  : > "$GPU_RAW"
  : > "$GPU_ERROR"
  rm -f "$GPU_PIPE" "$GPU_MONITOR_PID_FILE"
  mkfifo "$GPU_PIPE"

  # Timestamp each row as it reaches the reader, without estimating
  # timestamps from the total monitoring duration. stdbuf ensures that
  # intel_gpu_top sends complete CSV lines as they become available.
  (
    while IFS= read -r line; do
      printf '%s\t%s\n' "$(date +%s%3N)" "$line"
    done < "$GPU_PIPE"
  ) > "$GPU_RAW" &
  GPU_READER_PID=$!

  # Keep the previous privileged process wrapper so TERM stops the GPU
  # monitor cleanly. The FIFO feeds the timestamping reader above.
  sudo -n bash -c '
        stdbuf -oL intel_gpu_top -c -s "$1" -o - &
        monitor=$!
        printf "%s\n" "$monitor" > "$2"
        trap "kill -TERM $monitor 2>/dev/null || true; wait $monitor 2>/dev/null || true; exit" TERM INT
        wait "$monitor" || true
    ' bash "$GPU_INTERVAL_MS" "$GPU_MONITOR_PID_FILE" > "$GPU_PIPE" 2> "$GPU_ERROR" &
  GPU_PID=$!
  sleep 0.3
}

finish_intel_gpu_top() {
  # Stop both the sudo wrapper and its privileged child, with a time limit.
  stop_intel_processes
  # The FIFO reader finishes once the writer closes its end.
  if [[ -n "${GPU_READER_PID:-}" ]]; then
    if ! wait_for_exit "$GPU_READER_PID" 3; then
      kill -TERM "$GPU_READER_PID" 2> /dev/null || true
      if ! wait_for_exit "$GPU_READER_PID" 1; then
        kill -KILL "$GPU_READER_PID" 2> /dev/null || true
      fi
    fi
    wait "$GPU_READER_PID" 2> /dev/null || true
    GPU_READER_PID=
  fi
  rm -f "$GPU_PIPE"

  # Raw format: reception_timestamp_ms<TAB>original intel_gpu_top CSV row.
  # Discover VCS/VECS columns from the header, rather than fixed indices.
  awk -F '\t' -v id="$ID" '
        NF >= 2 {
            timestamp=$1
            n=split($2, csv, ",")
            if (!vcs_col || !vecs_col) {
                for (i=1; i<=n; i++) {
                    gsub(/^[[:space:]]+|[[:space:]]+$/, "", csv[i])
                    if (csv[i]=="VCS %") vcs_col=i
                    if (csv[i]=="VECS %") vecs_col=i
                }
                next
            }
            if (vcs_col<=n && vecs_col<=n) {
                vcs=csv[vcs_col]
                vecs=csv[vecs_col]
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", vcs)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", vecs)
                if (vcs ~ /^[0-9.]+$/ && vecs ~ /^[0-9.]+$/)
                    printf "%s\t%s\tintel_gpu_top\t%s\t%s\n", id, timestamp, vcs, vecs
            }
        }
    ' "$GPU_RAW" >> "$GPU_FILE"

  if [[ ! -s "$GPU_RAW" && ! -s "$GPU_ERROR" ]]; then
    printf 'intel_gpu_top produced no output\n' > "$GPU_ERROR"
  fi
}

# qmassa writes complete 30-sample batches to avoid truncated JSON on exit.
collect_qmassa_batch() {
  local batch_start
  batch_start=$(date +%s%3N)
  rm -f "$GPU_PART"
  # Track the actual qmassa PID so cleanup can stop it if a batch hangs.
  # Give qmassa its own process group so forced cleanup also stops children.
  setsid qmassa -x -m "$GPU_INTERVAL_MS" -n 30 -t "$GPU_PART" \
    > /dev/null 2>> "$GPU_ERROR" &
  local qmassa_pid=$!
  printf '%s\n' "$qmassa_pid" > "$GPU_QMASSA_PID_FILE"
  local batch_rc=0
  wait "$qmassa_pid" || batch_rc=$?
  rm -f "$GPU_QMASSA_PID_FILE"
  if ((batch_rc != 0)); then
    echo 'qmassa failed' >> "$GPU_ERROR"
    return 1
  fi
  if ! extract_qmassa_samples "$GPU_PART" "$batch_start"; then
    echo 'Invalid qmassa JSON batch' >> "$GPU_ERROR"
    return 1
  fi
  rm -f "$GPU_PART"
}

extract_qmassa_samples() {
  local part="$1" batch_start="$2"
  # The last object contains cumulative history for this complete batch.
  # Keep those samples once, rather than duplicating earlier snapshots.
  if ! jq -sr --argjson start "$batch_start" --arg id "$ID" '
        ([.[] | objects | select(.devs_state? | type == "array")] | last) as $data
        | if $data == null then error("No GPU snapshots") else $data end
        | . as $data
        | .devs_state[] as $device
        | select($device.dev_stats.eng_usage.video != null)
        | range(0; ($data.timestamps | length)) as $i
        | [$id, ($start + $data.timestamps[$i]), ($device.pci_id | tostring),
           $device.dev_stats.eng_usage.video[$i],
           ($device.dev_stats.eng_usage["video-enhance"][$i] // 0)]
        | @tsv
    ' "$part" > "$TMP_DIR/qmassa.batch.tsv"; then
    return 1
  fi
  cat "$TMP_DIR/qmassa.batch.tsv" >> "$GPU_FILE"
}

start_qmassa() {
  GPU_ERROR="$TMP_DIR/gpu.error"
  GPU_STOP="$TMP_DIR/qmassa.stop"
  GPU_PART="$TMP_DIR/qmassa.part.json"
  GPU_QMASSA_PID_FILE="$TMP_DIR/qmassa.pid"
  : > "$GPU_ERROR"
  rm -f "$GPU_STOP" "$GPU_PART" "$GPU_QMASSA_PID_FILE"
  (
    while [[ ! -e "$GPU_STOP" ]]; do
      collect_qmassa_batch || break
    done
  ) &
  GPU_PID=$!
}

finish_qmassa() {
  # Normally finish the current batch so jq sees complete JSON.
  touch "$GPU_STOP"
  if ! wait_for_exit "$GPU_PID" 5; then
    echo 'qmassa did not finish its batch within 5 seconds' >> "$GPU_ERROR"
    terminate_qmassa_processes
  fi
  wait "$GPU_PID" 2> /dev/null || true
  GPU_PID=
  rm -f "$GPU_STOP" "$GPU_QMASSA_PID_FILE"
}

start_gpu_monitoring() {
  if [[ "$GPU_TELEMETRY" == intel_gpu_top ]]; then
    start_intel_gpu_top
  else
    start_qmassa
  fi
}

stop_gpu_monitoring() {
  [[ -n "${GPU_PID:-}" ]] || return 0
  if [[ "$GPU_TELEMETRY" == intel_gpu_top ]]; then
    finish_intel_gpu_top
  else
    finish_qmassa
  fi
}

read_gpu_usage() {
  # Use only samples from this pipeline's measured time window.
  # GPU_DEVICE optionally selects a qmassa PCI device when more than one exists.
  # intel_gpu_top uses its own device label: do not filter by a qmassa PCI ID.
  local device_filter=
  [[ "$GPU_TELEMETRY" != qmassa ]] || device_filter="$GPU_DEVICE"
  # Both backends now have sample timestamps: qmassa uses its recorded
  # sample history; intel_gpu_top uses the CSV row reception time.
  # Keep only samples received within the measured pipeline time window.
  awk -F '\t' -v id="$ID" -v start="$PIPELINE_START" -v end="$PIPELINE_END" \
    -v device="$device_filter" '
        $1==id && $2>=start && $2<=end {
            if (device!="" && $3!=device) next
            if (device=="" && gpu!="" && gpu!=$3) {mixed=1; next}
            gpu=$3
            vcs+=$4; vecs+=$5
            if ($4>vmax) vmax=$4
            if ($5>emax) emax=$5
            count++
        }
        END {
            if (count==0 || mixed) print "NA NA NA NA 0"
            else printf "%.2f %.2f %.2f %.2f %d\n", vcs/count,vmax,vecs/count,emax,count
        }
    ' "$GPU_FILE"
}

# =============================================================================
# 5. PROCESS CONTROL AND CLEANUP
# =============================================================================

# Return when a child has exited (including an unreaped zombie), or time out.
# This avoids unlimited waits when a monitor ignores a termination request.
wait_for_exit() {
  local pid="$1" seconds="$2" i state
  [[ -n "$pid" ]] || return 0
  for ((i = 0; i < seconds * 10; i++)); do
    state=$(ps -o stat= -p "$pid" 2> /dev/null) || return 0
    [[ -n "$state" && "$state" != Z* ]] || return 0
    sleep 0.1
  done
  return 1
}

stop_pipeline_process() {
  [[ -n "${GST_PID:-}" ]] || return 0
  # setsid creates a separate process group for the GStreamer pipeline.
  kill -TERM -- "-$GST_PID" 2> /dev/null || true
  kill -TERM "$GST_PID" 2> /dev/null || true
  if ! wait_for_exit "$GST_PID" 2; then
    kill -KILL -- "-$GST_PID" 2> /dev/null || true
    kill -KILL "$GST_PID" 2> /dev/null || true
  fi
  wait "$GST_PID" 2> /dev/null || true
  GST_PID=
}

stop_intel_processes() {
  [[ -n "${GPU_PID:-}" ]] || return 0
  local monitor_pid=
  if [[ -s "${GPU_MONITOR_PID_FILE:-/nonexistent}" ]]; then
    read -r monitor_pid < "$GPU_MONITOR_PID_FILE" || true
  fi
  # The sudo wrapper may not forward signals in every environment.
  # Also signal its tracked privileged child, never all intel_gpu_top instances.
  kill -TERM "$GPU_PID" 2> /dev/null || true
  if [[ "$monitor_pid" =~ ^[0-9]+$ ]]; then
    sudo -n kill -TERM "$monitor_pid" 2> /dev/null || true
  fi
  if ! wait_for_exit "$GPU_PID" 3; then
    if [[ "$monitor_pid" =~ ^[0-9]+$ ]]; then
      sudo -n kill -KILL "$monitor_pid" 2> /dev/null || true
    fi
    kill -KILL "$GPU_PID" 2> /dev/null || true
  fi
  wait "$GPU_PID" 2> /dev/null || true
  GPU_PID=
  rm -f "${GPU_MONITOR_PID_FILE:-/nonexistent}"
}

terminate_qmassa_processes() {
  local qmassa_pid=
  if [[ -s "${GPU_QMASSA_PID_FILE:-/nonexistent}" ]]; then
    read -r qmassa_pid < "$GPU_QMASSA_PID_FILE" || true
  fi
  # Signal the whole qmassa process group, not just the worker shell.
  [[ -z "${GPU_PID:-}" ]] || kill -TERM "$GPU_PID" 2> /dev/null || true
  if [[ "$qmassa_pid" =~ ^[0-9]+$ ]]; then
    kill -TERM -- "-$qmassa_pid" 2> /dev/null || true
  fi
  # The qmassa process can outlive the worker (e.g., while blocked in I/O).
  if [[ "$qmassa_pid" =~ ^[0-9]+$ ]] && ! wait_for_exit "$qmassa_pid" 2; then
    kill -KILL -- "-$qmassa_pid" 2> /dev/null || true
  fi
  if [[ -n "${GPU_PID:-}" ]] && ! wait_for_exit "$GPU_PID" 1; then
    kill -KILL "$GPU_PID" 2> /dev/null || true
  fi
  [[ -z "${GPU_PID:-}" ]] || wait "$GPU_PID" 2> /dev/null || true
  GPU_PID=
  rm -f "${GPU_QMASSA_PID_FILE:-/nonexistent}" "${GPU_STOP:-/nonexistent}"
}

cleanup() {
  # Avoid re-entering cleanup if another signal arrives during shutdown.
  trap - EXIT INT TERM
  if [[ -n "${TIMER_PID:-}" ]]; then
    kill -TERM "$TIMER_PID" 2> /dev/null || true
    wait "$TIMER_PID" 2> /dev/null || true
    TIMER_PID=
  fi
  stop_pipeline_process
  if [[ -n "${GPU_PID:-}" ]]; then
    if [[ "$GPU_TELEMETRY" == qmassa ]]; then
      terminate_qmassa_processes
    else
      stop_intel_processes
    fi
  fi
  if [[ -n "${GPU_READER_PID:-}" ]]; then
    kill -TERM "$GPU_READER_PID" 2> /dev/null || true
    if ! wait_for_exit "$GPU_READER_PID" 1; then
      kill -KILL "$GPU_READER_PID" 2> /dev/null || true
    fi
    wait "$GPU_READER_PID" 2> /dev/null || true
    GPU_READER_PID=
  fi
  [[ -z "${TMP_DIR:-}" ]] || rm -rf "$TMP_DIR"
}

# =============================================================================
# 6. RESULTS AND OUTPUT
# =============================================================================

print_test_result() {
  printf '    FPS: %s | CPU: %s%% | Time: %ss | Status: %s\n' \
    "$FPS" "$CPU" "$ELAPSED" "$STATUS"
  printf '    VCS avg/max: %s%% / %s%% | VECS avg/max: %s%% / %s%% | GPU samples: %s | GPU status: %s\n' \
    "$VCS" "$VCS_MAX" "$VECS" "$VECS_MAX" "$GPU_SAMPLES" "$GPU_STATUS"
}

save_result() {
  if [[ "$OUTPUT" == xlsx ]]; then
    printf '%s\n' "$RES,$CODEC,$CURRENT_DECODER,$CURRENT_MODE,$CURRENT_INFERENCE_DEVICE,$GPU_TELEMETRY,$STATUS,$ELAPSED,$FPS,$CPU,$VCS,$VCS_MAX,$VECS,$VECS_MAX,$GPU_SAMPLES,$GPU_STATUS,$GST_LOG,$GPU_FILE" >> "$CSV"
  fi
  # Save every intel_gpu_top CSV row with its reception timestamp, including
  # samples outside the pipeline window. No filtering or averaging here.
  if [[ "$GPU_TELEMETRY" == intel_gpu_top && "$STATUS" != SKIPPED && -f "${GPU_RAW:-}" ]]; then
    cp "$GPU_RAW" "$RESULTS_DIR/logs/intel_gpu_top_raw_${ID}.tsv"
  fi

  # Append each pipeline log under its test ID in one combined file.
  # Preserve all GStreamer output and GPU monitor diagnostics.
  printf '\n========== %s ==========\n' "$ID" >> "$GST_LOG"
  cat "$RUN_LOG" >> "$GST_LOG"
  if [[ -s "$GPU_ERROR" ]]; then
    printf '\nGPU monitor messages:\n' >> "$GST_LOG"
    cat "$GPU_ERROR" >> "$GST_LOG"
  fi
  local row
  row=$(printf '  %-6s %-5s %-14s %-16s %-7s %9s %7s %8s %8s %8s %8s %8s  %s\n' \
    "$RES" "$CODEC" "$CURRENT_DECODER" "$CURRENT_MODE" "$CURRENT_INFERENCE_DEVICE" "$FPS" "$CPU" "$VCS" "$VCS_MAX" "$VECS" "$VECS_MAX" "$ELAPSED" "$STATUS")
  SUMMARY+="$row"$'\n'
  print_test_result
}

print_summary() {
  printf '\nGPU telemetry: %s | Output: %s\n' "$GPU_TELEMETRY" "$OUTPUT"
  printf '  %-6s %-5s %-14s %-16s %-7s %9s %7s %8s %8s %8s %8s %8s  %s\n' \
    RES CODEC DECODER MODE INFER FPS 'CPU %' 'VCS avg' 'VCS max' 'VECS avg' 'VECS max' 'TIME s' STATUS
  printf '  %s\n' '----------------------------------------------------------------------------------------------------------------------------------'
  printf '%s' "$SUMMARY"
}

create_excel_report() {
  [[ "$OUTPUT" == xlsx ]] || return 0
  "$REPORT_PYTHON" generate_report.py "$CSV" "$RESULTS_DIR/benchmark_report.xlsx"
  echo "Results: $PWD/$RESULTS_DIR"
}

# =============================================================================
# 7. RUN ONE TEST
# =============================================================================

run_test() {
  RES=$1 CODEC=$2 CURRENT_DECODER=$3 CURRENT_MODE=$4 CURRENT_INFERENCE_DEVICE=$5
  local input="$PWD/videos/$RES/$CODEC.mp4"
  ID="${RES}_${CODEC}_${CURRENT_DECODER}_${CURRENT_MODE}_${CURRENT_INFERENCE_DEVICE}"

  if [[ ! -f "$input" ]] || ! gst-inspect-1.0 "$CURRENT_DECODER" > /dev/null 2>&1; then
    echo "SKIP $ID (missing video or decoder)"
    STATUS=SKIPPED FPS=NA CPU=NA ELAPSED=NA
    VCS=NA VCS_MAX=NA VECS=NA VECS_MAX=NA GPU_SAMPLES=0 GPU_STATUS=UNAVAILABLE
    RUN_LOG="$TMP_DIR/pipeline.log"
    printf 'Skipped: missing video or decoder\n' > "$RUN_LOG"
    GPU_ERROR="$TMP_DIR/gpu.error"
    : > "$GPU_ERROR"
    save_result
    return
  fi

  RUN_LOG="$TMP_DIR/pipeline.log"
  : > "$RUN_LOG"
  echo "RUN $ID"
  build_pipeline "$input" "$CODEC" "$CURRENT_DECODER" "$CURRENT_MODE" "$CURRENT_INFERENCE_DEVICE"
  start_gpu_monitoring

  # The CPU and elapsed-time window starts immediately before GStreamer.
  read -r CPU_TOTAL_START CPU_IDLE_START < <(get_cpu_counters)
  PIPELINE_START=$(date +%s%3N)
  (
    while true; do
      printf '\r    Pipeline running: %ds' "$(($(date +%s) - PIPELINE_START / 1000))"
      sleep 1
    done
  ) &
  TIMER_PID=$!

  PIPELINE_RC=0
  setsid "${PIPELINE[@]}" > "$RUN_LOG" 2>&1 &
  GST_PID=$!
  wait "$GST_PID" || PIPELINE_RC=$?
  GST_PID=
  PIPELINE_END=$(date +%s%3N)
  read -r CPU_TOTAL_END CPU_IDLE_END < <(get_cpu_counters)

  kill "$TIMER_PID" 2> /dev/null || true
  wait "$TIMER_PID" 2> /dev/null || true
  TIMER_PID=
  printf '\r\033[K'
  stop_gpu_monitoring

  CPU=$(calculate_cpu_usage "$CPU_TOTAL_START" "$CPU_IDLE_START" "$CPU_TOTAL_END" "$CPU_IDLE_END")
  ELAPSED=$(awk -v start="$PIPELINE_START" -v end="$PIPELINE_END" 'BEGIN {printf "%.2f", (end-start)/1000}')
  FPS=$(read_fps)
  read -r VCS VCS_MAX VECS VECS_MAX GPU_SAMPLES < <(read_gpu_usage)
  GPU_STATUS=OK
  [[ "$GPU_SAMPLES" != 0 ]] || GPU_STATUS=UNAVAILABLE
  [[ ! -s "$GPU_ERROR" ]] || GPU_STATUS=ERROR

  STATUS=OK
  if ((PIPELINE_RC != 0)); then
    STATUS="ERROR_$PIPELINE_RC"
  elif ! grep -q 'Got EOS from element' "$RUN_LOG"; then
    STATUS=NO_EOS
  elif [[ "$FPS" == NA ]]; then
    STATUS=NO_FPS
  fi

  save_result
  if [[ "$GPU_STATUS" != OK ]]; then
    echo "    GPU monitor: $GPU_STATUS $(tail -n 2 "$GPU_ERROR")" >&2
  fi
  if [[ "$STATUS" != OK ]]; then
    printf '    Pipeline log (last 8 lines):\n' >&2
    tail -n 8 "$RUN_LOG" >&2
  fi
}

run_tests() {
  local res codec decoder mode
  local -a decoders
  SUMMARY=''
  printf 'Selected: decoder=%s, mode=%s, inference-device=%s, gpu-telemetry=%s, output=%s\n' \
    "$DECODER" "$MODE" "$INFERENCE_MODE" "$GPU_TELEMETRY" "$OUTPUT"

  for res in 360p 1080p; do
    for codec in h264 vp9 av1; do
      case "$codec" in
        h264) decoders=(avdec_h264 openh264dec vah264dec) ;;
        vp9) decoders=(vavp9dec) ;;
        av1) decoders=(vaav1dec) ;;
      esac
      for decoder in "${decoders[@]}"; do
        [[ "$DECODER" == all || "$DECODER" == "$decoder" ]] || continue
        for mode in decode decode-inference; do
          [[ "$MODE" == all || "$MODE" == "$mode" ]] || continue
          if [[ "$mode" == decode ]]; then
            # Decode-only has no inference device; do not duplicate this test.
            run_test "$res" "$codec" "$decoder" "$mode" NA
          else
            # GPU inference is enabled only with VA-API hardware decoders.
            # ALL adds an extra GPU run for them, keeping all CPU runs.
            if [[ "$INFERENCE_MODE" != GPU && "$INFERENCE_MODE" != ALL ]]; then
              run_test "$res" "$codec" "$decoder" "$mode" CPU
            elif [[ "$decoder" == avdec_h264 || "$decoder" == openh264dec ]]; then
              run_test "$res" "$codec" "$decoder" "$mode" CPU
            fi
            if [[ "$INFERENCE_MODE" == GPU || "$INFERENCE_MODE" == ALL ]]; then
              case "$decoder" in
                vah264dec | vavp9dec | vaav1dec)
                  # ALL includes CPU and GPU for hardware decoders.
                  if [[ "$INFERENCE_MODE" == ALL ]]; then
                    run_test "$res" "$codec" "$decoder" "$mode" CPU
                  fi
                  run_test "$res" "$codec" "$decoder" "$mode" GPU
                  ;;
              esac
            fi
          fi
        done
      done
    done
  done
  print_summary
  create_excel_report
  echo "Logs: $PWD/$RESULTS_DIR/logs"
}

main() {
  parse_arguments "$@"
  cd "$(dirname "$0")"
  check_requirements
  prepare_runtime
  run_tests
}

main "$@"
