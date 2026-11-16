# Video Decoder Benchmark

Bash benchmark for video decoding with **GStreamer** and **Intel DL Streamer**. Tests H.264, VP9, and AV1 at **360p** and **1080p**, with optional **YOLO11s inference** on CPU or GPU.

Measures pipeline **FPS**, whole-system **CPU usage**, Intel GPU **VCS/VECS utilization** (average/max), and execution time. Supports `intel_gpu_top` or `qmassa` telemetry, logs, and optional CSV/XLSX reports. Each configuration runs once.

## Requirements

- **Linux** with Bash and standard system utilities; a supported **Intel GPU** and drivers/VA-API for hardware decoding and GPU telemetry. Codec and GPU inference support depend on the hardware.
- **GStreamer** (`gst-launch-1.0`, `gst-inspect-1.0`) with MP4 parsers and the selected decoders: `avdec_h264`, `openh264dec`, `vah264dec`, `vavp9dec`, `vaav1dec`.
- **Intel DL Streamer** configured in the terminal (`gvafpscounter`; `gvadetect`, `gvawatermark`, `videoconvertscale`, and `vapostproc` for inference).
- **YOLO11s** OpenVINO model for inference at `$MODELS_PATH/public/yolo11s/INT8/yolo11s.xml`.
- **GPU telemetry:** `intel_gpu_top` and `sudo` access to GPU counters, **or** `qmassa` and `jq`.
- **Video preparation only:** `ffmpeg` and `ffprobe`, with `libx264`, `libvpx-vp9`, and `libaom-av1` encoders.
- **XLSX output only:** Python 3, `openpyxl`, and `generate_report.py` (the script uses `.venv/bin/python` if present).

## Usage

### 1. Prepare test videos

Provide an **H.264 MP4** at either **640×360** or **1920×1080**:

```bash
./benchmark.sh --prepare-videos /path/to/video.mp4
```

The script detects the resolution, repeats the video **5 times**, and encodes **H.264, VP9, and AV1** into `videos/360p/` or `videos/1080p/`. It does **not** resize the input. Run this command once per resolution. FFmpeg displays encoding progress in the terminal.

Expected files before running the full benchmark:

```text
videos/
├── 360p/{h264,vp9,av1}.mp4
└── 1080p/{h264,vp9,av1}.mp4
```

### 2. Run the benchmark

```bash
source /opt/intel/dlstreamer/scripts/setup_dls_env.sh
export MODELS_PATH="/path/to/models"

./benchmark.sh
./benchmark.sh --inference-device ALL --output xlsx
```

`MODELS_PATH` is required for inference (`--mode decode-inference` or `all`), not for decode-only tests. Run the benchmark as a normal user; `intel_gpu_top` may request `sudo` authorization.

| Option | Values | Default |
|---|---|---|
| `--decoder` | `avdec_h264`, `openh264dec`, `vah264dec`, `vavp9dec`, `vaav1dec`, `all` | `all` |
| `--mode` | `decode`, `decode-inference`, `all` | `all` |
| `--inference-device` | `CPU`, `GPU`, `ALL` | `CPU` |
| `--gpu-telemetry` | `intel_gpu_top`, `qmassa` | `intel_gpu_top` |
| `--output` | `none`, `xlsx` | `none` |
| `--prepare-videos PATH` | Convert one supported H.264 MP4 and exit | — |
| `--description` | Show codec descriptions and exit | — |
| `--help` | Show all options | — |

`GPU` inference applies to `vah264dec`, `vavp9dec`, and `vaav1dec`; software decoders still use CPU. `ALL` runs CPU inference for every decoder plus GPU inference for the three hardware decoders. Decode-only tests are not duplicated.

### 3. Results

Every run creates `results/<timestamp>_<gpu-telemetry>/logs/` containing a combined `pipeline.log` and normalized `gpu.tsv`. With `intel_gpu_top`, per-test raw GPU logs are also saved. Use `--output xlsx` to additionally generate `benchmark.csv` and `benchmark_report.xlsx` (`Results` and `Comparison` worksheets, compared against `vah264dec`).

FPS in inference mode measures **the entire pipeline**, not decoding alone. CPU usage is measured for **the whole system** via `/proc/stat`; GPU utilization is sampled during each pipeline run. Missing videos or decoder plugins are marked `SKIPPED`.
