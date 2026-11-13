# Video Codec Benchmark

A Bash-based benchmark for evaluating video decoder performance with **GStreamer** and **Intel DL Streamer**. It benchmarks software and hardware decoders, optionally runs YOLO11s inference on CPU or GPU, monitors system CPU and Intel GPU video engines, and can generate an Excel report.

Each selected configuration runs **once** at **360p** and **1080p**. The benchmark is controlled through command-line flags.

## 1. Quick Start

Prepare DL Streamer in the **same terminal session** in which you run the benchmark:

```bash
source /opt/intel/dlstreamer/scripts/setup_dls_env.sh
export MODELS_PATH="/path/to/models"

cd /path/to/video_decoder_benchmark
chmod +x benchmark.sh
./benchmark.sh
```

`MODELS_PATH` must point to the **root models directory**, which must contain:

```text
$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml
```

YOLO11s is required when `--mode` includes inference (`decode-inference` or `all`), but not for `--mode decode`.

The script does **not** install software, generate test videos or models, or configure the DL Streamer environment automatically. Run it as your normal user; the `intel_gpu_top` monitoring backend requests `sudo` authorization.

## 2. Command-Line Options

| Flag | Values | Default | Purpose |
|---|---|---|---|
| `--decoder` | `avdec_h264`, `openh264dec`, `vah264dec`, `vavp9dec`, `vaav1dec`, `all` | `all` | Run one decoder or all supported decoders. |
| `--mode` | `decode`, `decode-inference`, `all` | `all` | Run decode-only, decode with inference, or both. |
| `--inference-device` | `CPU`, `GPU`, `ALL` (case-insensitive) | `CPU` | Select where `gvadetect` performs inference. Applies only to `decode-inference`. |
| `--gpu-telemetry` | `intel_gpu_top`, `qmassa` | `intel_gpu_top` | Choose the Intel GPU monitoring backend. |
| `--output` | `none`, `xlsx` | `none` | Console + logs, or console + logs + CSV/XLSX. |
| `--description` | No argument | — | Display codec descriptions and exit without running tests. |
| `--help`, `-h` | No argument | — | Display help and exit. |

### Inference device selection

`--inference-device` controls **inference**, not video decoding:

- **`CPU`**: all decoders run YOLO11s inference on CPU.
- **`GPU`**: `vah264dec`, `vavp9dec`, and `vaav1dec` run inference on GPU; `avdec_h264` and `openh264dec` still run inference on CPU.
- **`ALL`**: all decoders run inference on CPU, and the three hardware decoders additionally run inference on GPU.

Decode-only tests do not perform inference and are **not duplicated** for `ALL`.

When all decoders and both modes are selected, the maximum number of tests is **20** with `CPU` or `GPU`, and **26** with `ALL` (assuming all inputs and plugins are available).

Examples:

```bash
# Defaults: all decoders, both modes, CPU inference, intel_gpu_top, no Excel
./benchmark.sh

# One hardware decoder, decode-only
./benchmark.sh --decoder vah264dec --mode decode

# Compare CPU and GPU inference for eligible decoders
./benchmark.sh --mode decode-inference --inference-device all --output xlsx

# GPU inference on hardware decoders; software decoders remain on CPU
./benchmark.sh --inference-device GPU --output xlsx

# Use qmassa as the GPU monitor
./benchmark.sh --mode decode-inference --gpu-telemetry qmassa

# Display descriptions without running the benchmark
./benchmark.sh --description

# Display the description for a selected decoder's codec
./benchmark.sh --decoder vavp9dec --description

# Help
./benchmark.sh --help
```

`--inference-device` accepts any letter case (`cpu`, `GPU`, `All`, etc.). Invalid options or missing arguments produce an error. `--description` and `--help` exit without creating results or starting monitoring.

## 3. Requirements

### Operating system and hardware

- **Linux** with **Bash**, `/proc/stat`, and standard GNU/Linux process utilities. The script is not designed for native Windows or macOS execution.
- A supported **Intel GPU** and a working graphics/media driver stack for Intel hardware decoding and GPU telemetry. Hardware decoding availability varies by GPU generation: **H.264, VP9, and AV1 hardware support are not guaranteed on every Intel GPU**.
- Intel GPU inference support when using GPU inference (`--inference-device GPU` or `ALL`), including a compatible OpenVINO/DL Streamer runtime and GPU drivers.
- Access to Intel GPU performance counters for the selected GPU monitoring backend. On some systems, permissions or driver support may prevent monitoring even when decoding works.

The **CPU measurement itself does not depend on an Intel CPU**: `/proc/stat` provides whole-system CPU time counters on Linux. CPU utilization percentages are relative to each machine's total logical CPU capacity and are not directly comparable across systems with different processors.

### GStreamer and DL Streamer

Install and configure:

- `gst-launch-1.0`, `gst-inspect-1.0` and the GStreamer elements needed by the pipelines: `filesrc`, `qtdemux`, `h264parse`, `vp9parse`, `av1parse`, `queue`, `fakesink`, and the selected decoders.
- Decoder plugins: `avdec_h264` (FFmpeg/libav), `openh264dec` (OpenH264), `vah264dec`, `vavp9dec`, and `vaav1dec` (VA-API), as applicable to your hardware.
- **Intel DL Streamer**, with `gvafpscounter`; inference also uses `gvadetect`, `gvawatermark`, `videoconvertscale`, and `vapostproc` for H.264 inference pipelines.
- **YOLO11s** in OpenVINO IR format at `$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml` for inference tests.

The script checks for `gvafpscounter`, and for inference also checks `gvadetect` and the model XML. It checks each selected decoder plugin before running its test. Installing a plugin does not necessarily mean the underlying GPU supports that codec or pipeline.

Useful checks:

```bash
gst-inspect-1.0 gvafpscounter
gst-inspect-1.0 gvadetect
gst-inspect-1.0 vah264dec
gst-inspect-1.0 vavp9dec
gst-inspect-1.0 vaav1dec
```

### Command-line utilities

The script uses tools including `awk`, `setsid`, `date` (with millisecond timestamps), `mkfifo`, `ps`, `mktemp`, and common shell/core utilities such as `grep`, `sed`, `cat`, `cp`, `mkdir`, `sleep`, and `kill`.

**`intel_gpu_top` backend (default):**

- `intel_gpu_top` (typically from `intel-gpu-tools`), `sudo`, and `stdbuf` (GNU coreutils).
- Permission to run `intel_gpu_top` with `sudo` without repeated interactive prompts during individual tests. The script authenticates with `sudo -v` and launches its monitor through `sudo`.
- An `intel_gpu_top` CSV output exposing **`VCS %` and `VECS %`** columns. Availability and naming of video-engine counters may differ between drivers, tool versions, and GPU generations.

**`qmassa` backend:**

- `qmassa` and `jq` on `PATH`.
- A GPU and driver supported by `qmassa`, exposing `video` and `video-enhance` engine usage in its JSON output.
- If `qmassa` was installed using Cargo, ensure it is on `PATH`, for example:

```bash
export PATH="$HOME/.cargo/bin:$PATH"
```

Only the **selected** telemetry backend is needed for a given run; you do not need to install both.

**Excel export (`--output xlsx` only):**

- Python 3, `openpyxl`, and `generate_report.py` in the benchmark directory.
- The script uses `.venv/bin/python` when available, otherwise `python3`.

```bash
python3 -m venv .venv
.venv/bin/pip install openpyxl
```

### Preparing test videos

**FFmpeg** is required to generate the test inputs from the included source clips (it is not required to run the benchmark once the six inputs exist). FFmpeg must support the `libx264`, `libvpx-vp9`, and `libaom-av1` encoders for the commands below.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MODELS_PATH` | Unset | Root directory containing YOLO11s; required for inference. |
| `GPU_INTERVAL_MS` | `100` | Requested GPU sampling interval in milliseconds (positive integer). Actual sampling intervals may differ. |
| `GPU_DEVICE` | Unset | Optional PCI device filter for `qmassa` on multi-GPU systems; does not select an `intel_gpu_top` GPU. |

## 4. Input Files and Tested Decoders

The script expects the following layout **relative to its own directory**. Generate the six benchmark inputs before running it:

```text
video_decoder_benchmark/
├── benchmark.sh
├── generate_report.py       # Required only for --output xlsx
├── README.md
├── videos/
│   ├── source/               # Source clips distributed with the repository
│   │   ├── 1192116-sd_640_360_30fps.mp4
│   │   └── 1192116-hd_1920_1080_30fps.mp4
│   ├── 360p/                # Generated locally (not committed)
│   │   ├── h264.mp4
│   │   ├── vp9.mp4
│   │   └── av1.mp4
│   └── 1080p/               # Generated locally (not committed)
│       ├── h264.mp4
│       ├── vp9.mp4
│       └── av1.mp4
└── results/                 # Created automatically
```

| Codec | Decoder | Decoding |
|---|---|---|
| H.264 (AVC) | `avdec_h264` | Software (CPU) |
| H.264 (AVC) | `openh264dec` | Software (CPU) |
| H.264 (AVC) | `vah264dec` | Hardware (VA-API / Intel GPU) |
| VP9 | `vavp9dec` | Hardware (VA-API / Intel GPU) |
| AV1 | `vaav1dec` | Hardware (VA-API / Intel GPU) |

All input files must use **MP4 containers**, because the pipelines use `qtdemux`. A missing input file or decoder plugin produces `SKIPPED` for the affected test. The benchmark uses the six generated files; the two clips in `videos/source/` are only used to prepare them.

### Generate benchmark inputs

Install FFmpeg with the required encoders, for example on Ubuntu:

```bash
sudo apt install ffmpeg
ffmpeg -hide_banner -encoders | grep -E 'libx264|libvpx-vp9|libaom-av1'
```

From the benchmark directory (`functional_tests/tools/video_codecs_benchmark/`), run:

```bash
mkdir -p videos/360p videos/1080p

for res in 360p 1080p; do
    if [ "$res" = 360p ]; then
        input="videos/source/1192116-sd_640_360_30fps.mp4"
    else
        input="videos/source/1192116-hd_1920_1080_30fps.mp4"
    fi

    ffmpeg -y -stream_loop 4 -i "$input" -map 0:v:0 -an -r 30 \
        -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p \
        "videos/$res/h264.mp4"

    ffmpeg -y -stream_loop 4 -i "$input" -map 0:v:0 -an -r 30 \
        -c:v libvpx-vp9 -b:v 0 -crf 32 -pix_fmt yuv420p \
        "videos/$res/vp9.mp4"

    ffmpeg -y -stream_loop 4 -i "$input" -map 0:v:0 -an -r 30 \
        -c:v libaom-av1 -cpu-used 6 -row-mt 1 -b:v 0 -crf 35 \
        -pix_fmt yuv420p "videos/$res/av1.mp4"
done
```

This generates all six MP4 inputs from the two source clips. The H.264, VP9, and AV1 files at each resolution use the same source clip. Encoding can take some time, particularly with AV1. The generated `videos/360p/` and `videos/1080p/` directories are ignored by Git.

Check the resulting files before running the benchmark:

```bash
find videos/360p videos/1080p -maxdepth 1 -name '*.mp4' -type f
```


## 5. Pipeline Configurations

**`--mode decode` — decoding only:**

```text
filesrc → qtdemux → <codec>parse → <decoder> → gvafpscounter → fakesink sync=false
```

**`--mode decode-inference` — decoding with YOLO11s inference:**

```text
filesrc → qtdemux → <codec>parse → <decoder>
        → gvadetect (YOLO11s, device=CPU/GPU) → queue
        → [vapostproc for H.264 only] → gvawatermark
        → videoconvertscale → gvafpscounter → fakesink sync=false
```

Inference device selection is controlled by `--inference-device`. For the software decoders, inference remains on CPU even when `GPU` is selected. Decode-only mode has no inference device (`NA` in the results).

`sync=false` avoids waiting for real-time playback. Decode-only FPS represents decoder pipeline throughput; decode-inference FPS represents **whole-pipeline throughput** including inference and downstream processing, not standalone decode speed.

## 6. Results, Logs, and Folder Names

After each test the terminal displays FPS, system CPU utilization, elapsed time, GPU VCS/VECS averages and maxima, GPU sample count, and status. A summary table appears when the run finishes.

The `results/` directory is created automatically. Each run gets a unique folder in the format **`YYYY-MM-DD_HH-MM-SS_<gpu-telemetry>`**; `_02`, `_03`, etc. are appended in case of a name collision.

**Default `--output none`:**

```text
results/
└── YYYY-MM-DD_HH-MM-SS_intel_gpu_top/
    └── logs/
        ├── pipeline.log
        ├── gpu.tsv
        ├── intel_gpu_top_raw_<test-id>.tsv
        └── ...                         # One raw GPU file per executed test
```

**With `--output xlsx`:**

```text
results/
└── YYYY-MM-DD_HH-MM-SS_intel_gpu_top/
    ├── benchmark.csv
    ├── benchmark_report.xlsx
    └── logs/
        ├── pipeline.log
        ├── gpu.tsv
        ├── intel_gpu_top_raw_<test-id>.tsv
        └── ...
```

For `--gpu-telemetry qmassa`, the folder suffix is `_qmassa` and the per-test `intel_gpu_top_raw_*.tsv` files are **not** created; `pipeline.log` and `gpu.tsv` are still saved.

- **`logs/pipeline.log`** — one combined file containing the GStreamer output from all tests, in execution order, separated by test identifiers. GPU monitor error messages are included when present.
- **`logs/gpu.tsv`** — normalized GPU samples from the selected backend: `pipeline`, `timestamp_ms`, `device`, `vcs`, `vecs`.
- **`logs/intel_gpu_top_raw_<test-id>.tsv`** — original `intel_gpu_top` CSV rows prefixed by their reception timestamps. These include measurements outside the pipeline time window and are retained separately for each executed test.
- **`benchmark.csv`** (*XLSX mode only*) — test results and status information, including inference device and log paths; used by the Excel generator.
- **`benchmark_report.xlsx`** (*XLSX mode only*) — workbook containing `Results` and `Comparison`.

Temporary intermediate files in the system temporary directory are removed during normal cleanup.

## 7. Excel Report

The Excel workbook contains **two worksheets** generated from the actual test results.

### `Results`

Contains all executed or skipped configurations, including resolution, codec, decoder, pipeline mode, **inference device** (`CPU`, `GPU`, or `NA`), telemetry backend, pipeline status, time, FPS, CPU %, VCS/VECS averages and maxima, GPU sample count, and GPU status. Log paths remain available in `benchmark.csv`, not as columns in `Results`.

### `Comparison`

Contains three separate tables when the corresponding tests are present:

1. **Decode** — decode-only results for the selected decoders.
2. **Decode + Inference (CPU)** — tests using CPU inference.
3. **Decode + Inference (GPU)** — GPU inference results for `vah264dec`, `vavp9dec`, and `vaav1dec` only (up to six rows: three decoders × two resolutions).

The comparison metrics are **FPS**, **whole-system CPU %**, and **average VCS %**. Each has a percentage difference and an adjacent **actual / baseline** value so the underlying measurements can be checked without switching worksheets. VECS remains available in `Results` but is not compared in `Comparison`.

The reference decoder is **`vah264dec`**, matched by **resolution, pipeline mode, inference device, and telemetry backend**. CPU inference is never compared to a GPU inference baseline; decode-only is compared only to decode-only.

```text
Difference (%) = (actual value / vah264dec baseline value − 1) × 100
```

Positive FPS deltas mean higher throughput. Positive CPU/VCS deltas mean higher reported utilization, **not necessarily better performance**. `N/A` is displayed when a valid comparison cannot be calculated, for example because a matching baseline is missing or its value is zero.

The workbook can be regenerated **without rerunning benchmarks** using the saved CSV:

```bash
python3 generate_report.py \
    results/<run-folder>/benchmark.csv \
    results/<run-folder>/benchmark_report.xlsx
```

Use `.venv/bin/python` instead of `python3` if `openpyxl` is installed only in the virtual environment.

## 8. How Measurements Work

| Metric | Method |
|---|---|
| FPS | The last `FpsCounter(overall ...)` `total=` value from GStreamer output. |
| CPU avg % | Two `/proc/stat` snapshots around pipeline execution: `100 × (Δtotal − Δidle) / Δtotal`; idle includes iowait. Measures the **entire system**, not only the pipeline. |
| VCS avg/max % | Mean/maximum of usable Video engine samples matched to the pipeline time window. |
| VECS avg/max % | Mean/maximum of matching Video Enhancement engine samples. |
| Elapsed time | Wall-clock time surrounding the GStreamer run. |
| Pipeline status | `OK`, `SKIPPED` (missing input/decoder), `ERROR_<code>` (GStreamer failure), `NO_EOS`, or `NO_FPS`. |
| GPU status | `OK` (samples present and no monitor error recorded), `UNAVAILABLE` (no usable matching samples), or `ERROR` (monitor error recorded). |

### GPU telemetry backends

**`intel_gpu_top`:** One monitoring process is started for each test. CSV rows are received continuously and timestamped when the script reads them. The parser locates `VCS %` and `VECS %` by column name, saves normalized samples to `gpu.tsv`, and retains the timestamped raw output in per-test files. A sample is included in the statistics only if its **reception timestamp** is within the measured pipeline window.

**`qmassa`:** GPU samples are collected in **batches of 30** at the requested interval, then parsed with `jq`. The script reconstructs sample timestamps from the batch start time and offsets provided by `qmassa`, and selects samples within the pipeline window. The batches are temporary; normalized samples are retained in `gpu.tsv`.

**Timing limitations:** `intel_gpu_top` timestamps represent **when rows are received**, not the exact moment the GPU measured its counters. `qmassa` timestamps are reconstructed from batch timing information. Sampling boundaries are therefore approximate, especially for short tests. A requested 100 ms interval does not guarantee exactly 10 samples per second.

Additional considerations:

- CPU and GPU utilization may include activity from other applications.
- Different processors, GPU generations, drivers, and monitoring tools may report different utilization percentages under otherwise similar workloads.
- Each selected configuration runs once; there is no built-in repetition or statistical aggregation across runs.
- Short runs have relatively few GPU samples, so single spikes can strongly affect averages and maxima.
- A `GPU status` of `OK` indicates available parsed samples without recorded monitor errors; it is **not** an independent guarantee of hardware-counter accuracy.
- The script attempts to terminate active pipeline and monitor processes on interruption and cleans up temporary files.

## 9. Code Organization

`benchmark.sh` contains command-line parsing and dependency checks, pipeline construction, CPU/GPU monitoring, process cleanup, test execution, and result logging. `generate_report.py` converts the CSV into the two-sheet Excel report and runs **only** when `--output xlsx` is selected.
