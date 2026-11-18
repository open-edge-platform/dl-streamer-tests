#!/usr/bin/env python3
"""Export benchmark measurements and a separate comparison against vah264dec."""
import csv
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

NUMERIC = {"elapsed_s", "fps_avg", "cpu_avg_pct", "vcs_avg_pct", "vcs_max_pct",
           "vecs_avg_pct", "vecs_max_pct", "gpu_samples"}
LABELS = {"resolution": "Resolution", "codec": "Codec", "decoder": "Decoder",
          "mode": "Pipeline", "inference_device": "Inference device", "gpu_telemetry": "GPU telemetry", "status": "Status",
          "elapsed_s": "Time (s)", "fps_avg": "FPS", "cpu_avg_pct": "CPU %",
          "vcs_avg_pct": "VCS avg %", "vcs_max_pct": "VCS max %",
          "vecs_avg_pct": "VECS avg %", "vecs_max_pct": "VECS max %",
          "gpu_samples": "GPU samples", "gpu_status": "GPU status"}
COMPARISONS = (
    ("fps_avg", "FPS vs vah264dec (%)"),
    ("cpu_avg_pct", "CPU vs vah264dec (%)"),
    ("vcs_avg_pct", "VCS avg vs vah264dec (%)"),
)
DARK = PatternFill("solid", fgColor="20384F")
STRIPE = PatternFill("solid", fgColor="F1F5F9")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        return reader.fieldnames, list(reader)


def cell_value(name, text):
    if name in NUMERIC and text not in (None, "", "NA", "UNAVAILABLE"):
        try:
            return int(float(text)) if name == "gpu_samples" else float(text)
        except ValueError:
            pass
    return text if text is not None else ""


def format_header(sheet, headers, widths=None):
    sheet.sheet_view.showGridLines = False
    for column, label in enumerate(headers, 1):
        cell = sheet.cell(1, column, label)
        cell.fill = DARK
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(column)].width = (
            widths[column-1] if widths else 17
        )
    sheet.row_dimensions[1].height = 32


def finish_sheet(sheet, columns, row_count):
    sheet.freeze_panes = "D2" if columns >= 3 else "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(columns)}{row_count + 1}"


def create_report(columns, rows, output):
    # Original Results worksheet: keep every measurement, except log file paths.
    columns = [name for name in columns if name not in ("log_file", "gpu_file")]
    required = {"resolution", "decoder", "mode", "status"}
    if not required.issubset(columns):
        raise ValueError(f"Missing CSV columns: {', '.join(sorted(required-set(columns)))}")

    book = Workbook()
    results = book.active
    results.title = "Results"
    format_header(results, [LABELS.get(c, c) for c in columns],
                  [22 if c == "decoder" else 16 for c in columns])
    for row_idx, record in enumerate(rows, 2):
        for col_idx, name in enumerate(columns, 1):
            cell = results.cell(row_idx, col_idx, cell_value(name, record.get(name)))
            if row_idx % 2 == 0:
                cell.fill = STRIPE
            if name in NUMERIC and isinstance(cell.value, (float, int)):
                cell.number_format = "0" if name == "gpu_samples" else "0.00"
    finish_sheet(results, len(columns), len(rows))

    # Comparison: separate Decode, CPU inference and GPU inference tables.
    # Every metric has a percentage change and a compact actual/baseline reference.
    comparison = book.create_sheet("Comparison")
    comparison.sheet_view.showGridLines = False
    comparison.column_dimensions["A"].width = 15  # Resolution
    comparison.column_dimensions["B"].width = 12  # Codec
    comparison.column_dimensions["C"].width = 20  # Decoder
    comparison.column_dimensions["D"].width = 17  # Inference device
    comparison.column_dimensions["E"].width = 17  # FPS delta
    comparison.column_dimensions["F"].width = 25  # FPS actual/baseline
    comparison.column_dimensions["G"].width = 17  # CPU delta
    comparison.column_dimensions["H"].width = 25  # CPU actual/baseline
    comparison.column_dimensions["I"].width = 17  # VCS delta
    comparison.column_dimensions["J"].width = 25  # VCS actual/baseline
    comparison.column_dimensions["K"].width = 14  # Status
    if "gpu_telemetry" in columns:
        comparison.column_dimensions["L"].width = 19

    comparison.merge_cells("A1:L1")
    title = comparison.cell(1, 1, "Decoder comparison — baseline: vah264dec")
    title.font = Font(bold=True, size=15, color="20384F")
    comparison.row_dimensions[1].height = 30
    comparison.merge_cells("A2:L2")
    comparison.cell(2, 1, "Δ% = (actual / baseline − 1) × 100. Parentheses show: actual / baseline. Comparisons use the same resolution, pipeline mode and inference device.")
    comparison.cell(2, 1).font = Font(size=10, color="64748B")
    comparison.row_dimensions[2].height = 23

    # Source references keep this sheet linked to the original Results measurements.
    source_columns = {field: get_column_letter(index) for index, field in enumerate(columns, 1)}
    metrics = [field for field in ("fps_avg", "cpu_avg_pct", "vcs_avg_pct") if field in columns]

    def mode_key(mode):
        return {"A": "decode", "C": "decode-inference"}.get(mode, mode)

    def group(record):
        return (record.get("resolution"), mode_key(record.get("mode")),
                record.get("inference_device", "NA") if "inference_device" in columns else "NA",
                record.get("gpu_telemetry") if "gpu_telemetry" in columns else None)

    baselines = {}
    for source_row, record in enumerate(rows, 2):
        if record.get("decoder") == "vah264dec" and record.get("status") == "OK":
            baselines.setdefault(group(record), source_row)

    percent_format = '+0.00%;-0.00%;0.00%'
    current_row = 4
    headers = ["Resolution", "Codec", "Decoder", "Inference device", "FPS Δ%", "FPS (actual / vah264dec)",
               "CPU Δ%", "CPU % (actual / vah264dec)", "VCS Δ%", "VCS % (actual / vah264dec)", "Status"]
    if "gpu_telemetry" in columns:
        headers.append("GPU telemetry")

    sections = (
        ("decode", None, "Decode"),
        ("decode-inference", "CPU", "Decode + Inference (CPU)"),
        ("decode-inference", "GPU", "Decode + Inference (GPU)"),
    )
    for mode, device, label in sections:
        selected = [(idx, record) for idx, record in enumerate(rows, 2)
                    if mode_key(record.get("mode")) == mode
                    and (device is None or record.get("inference_device", "NA") == device)]
        if not selected:
            continue

        end_col = get_column_letter(len(headers))
        comparison.merge_cells(start_row=current_row, start_column=1,
                               end_row=current_row, end_column=len(headers))
        section = comparison.cell(current_row, 1, label)
        section.fill = DARK
        section.font = Font(color="FFFFFF", bold=True, size=12)
        section.alignment = Alignment(vertical="center")
        comparison.row_dimensions[current_row].height = 27
        current_row += 1

        for col_idx, header in enumerate(headers, 1):
            cell = comparison.cell(current_row, col_idx, header)
            cell.fill = PatternFill("solid", fgColor="DDE7F0")
            cell.font = Font(color="20384F", bold=True)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        comparison.row_dimensions[current_row].height = 31
        current_row += 1

        for source_row, record in selected:
            baseline_row = baselines.get(group(record))
            fields = ("resolution", "codec", "decoder")
            for col_idx, field in enumerate(fields, 1):
                comparison.cell(current_row, col_idx, record.get(field, ""))
            comparison.cell(current_row, 4, record.get("inference_device", "NA"))
            comparison.cell(current_row, 11, record.get("status", ""))
            if "gpu_telemetry" in columns:
                comparison.cell(current_row, len(headers), record.get("gpu_telemetry", ""))

            for metric_idx, field in enumerate(("fps_avg", "cpu_avg_pct", "vcs_avg_pct")):
                pct_cell = comparison.cell(current_row, 5 + 2 * metric_idx)
                raw_cell = comparison.cell(current_row, 6 + 2 * metric_idx)
                pct_cell.number_format = percent_format
                if field not in columns or baseline_row is None or record.get("status") != "OK":
                    pct_cell.value = "N/A"
                    raw_cell.value = "N/A"
                    continue

                current = f"'Results'!{source_columns[field]}{source_row}"
                baseline = f"'Results'!{source_columns[field]}{baseline_row}"
                if baseline_row == source_row:
                    pct_cell.value = f'=IF(ISNUMBER({current}),0,"N/A")'
                else:
                    pct_cell.value = (f'=IF(OR(NOT(ISNUMBER({current})),'
                                      f'NOT(ISNUMBER({baseline})),{baseline}=0),'
                                      f'"N/A",{current}/{baseline}-1)')

                # Always show the actual measured numbers, including a zero baseline.
                # e.g. "48.85 / 76.47" next to "-36.12%".
                raw_cell.value = (f'=IF(OR(NOT(ISNUMBER({current})),'
                                  f'NOT(ISNUMBER({baseline}))),"N/A",'
                                  f'"("&TEXT({current},"0.00")&" / "&TEXT({baseline},"0.00")&")")')
                raw_cell.font = Font(size=10, color="52657A")

            if current_row % 2 == 0:
                for cell in comparison[current_row][:len(headers)]:
                    cell.fill = STRIPE
            if record.get("decoder") == "vah264dec":
                for cell in comparison[current_row][:len(headers)]:
                    cell.font = Font(bold=True, color="20384F")
            current_row += 1

        current_row += 2

    comparison.freeze_panes = "E6"
    comparison.sheet_properties.pageSetUpPr.fitToPage = True
    comparison.page_setup.fitToWidth = 1
    comparison.print_options.horizontalCentered = True

    output.parent.mkdir(parents=True, exist_ok=True)
    book.save(output)
    print(f"Report saved: {output} ({len(rows)} tests, 2 sheets)")


def main():
    base = Path(__file__).resolve().parent
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "results/benchmark.csv"
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else base / "results/benchmark_report.xlsx"
    columns, rows = read_csv(source)
    create_report(columns, rows, output)


if __name__ == "__main__":
    main()
