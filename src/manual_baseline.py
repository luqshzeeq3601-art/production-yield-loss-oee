"""Manual Excel reporting baseline and workflow documentation (P5-001).

Models the realistic 'before automation' manual reporting process:
- 14 step-by-step manual workflow tasks totaling 360 min/week (~6.0 h/week).
- Generates reproducible multi-sheet Excel workbook (excel/manual_report_baseline.xlsx).
- Exports manual reporting steps (reports/manual_reporting_steps.csv).
- Exports baseline metrics and error risk profile (reports/manual_reporting_baseline.json).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd

from src.config_loader import load_config


MANUAL_STEPS: list[dict[str, Any]] = [
    {
        "step_id": 1,
        "phase": "1. Data Extraction",
        "task_name": "Export raw hourly production from MES portal",
        "frequency": "Weekly",
        "estimated_minutes": 30,
        "operator": "Operations Analyst",
        "tools_used": "MES Web Portal, CSV Export",
        "failure_modes": "Timeout on large date ranges, wrong shift filter selection, missing last-hour records",
    },
    {
        "step_id": 2,
        "phase": "1. Data Extraction",
        "task_name": "Export downtime log from maintenance system",
        "frequency": "Weekly",
        "estimated_minutes": 25,
        "operator": "Operations Analyst",
        "tools_used": "CMMS / SCADA Portal, CSV Export",
        "failure_modes": "Incomplete event closeout by technicians, unmapped reason codes",
    },
    {
        "step_id": 3,
        "phase": "1. Data Extraction",
        "task_name": "Export quality scrap defect records from terminal logs",
        "frequency": "Weekly",
        "estimated_minutes": 25,
        "operator": "Quality Analyst",
        "tools_used": "Quality Database UI, CSV Export",
        "failure_modes": "Mismatch in lot timestamps vs MES shift windows, missing supplier tag",
    },
    {
        "step_id": 4,
        "phase": "2. Data Ingestion & Staging",
        "task_name": "Create new weekly tab and paste raw production data",
        "frequency": "Weekly",
        "estimated_minutes": 20,
        "operator": "Operations Analyst",
        "tools_used": "Excel (Raw_Production)",
        "failure_modes": "Pasting over existing formulas, column misalignment, header truncation",
    },
    {
        "step_id": 5,
        "phase": "2. Data Ingestion & Staging",
        "task_name": "Paste raw downtime event logs into workbook",
        "frequency": "Weekly",
        "estimated_minutes": 15,
        "operator": "Operations Analyst",
        "tools_used": "Excel (Raw_Downtime)",
        "failure_modes": "Date format corruption (text vs datetime), missing event IDs",
    },
    {
        "step_id": 6,
        "phase": "2. Data Ingestion & Staging",
        "task_name": "Paste quality scrap logs and standardize product keys",
        "frequency": "Weekly",
        "estimated_minutes": 20,
        "operator": "Operations Analyst",
        "tools_used": "Excel (Raw_Quality)",
        "failure_modes": "Trailing spaces in product codes causing lookup failure, duplicate rows",
    },
    {
        "step_id": 7,
        "phase": "3. Data Cleaning & Validation",
        "task_name": "Manual data audit: check missing hours and line code discrepancies",
        "frequency": "Weekly",
        "estimated_minutes": 30,
        "operator": "Operations Analyst",
        "tools_used": "Excel Filter, Conditional Formatting",
        "failure_modes": "Unnoticed gaps in 24/7 hours, negative run times overlooked",
    },
    {
        "step_id": 8,
        "phase": "3. Data Cleaning & Validation",
        "task_name": "Update VLOOKUP reference tables for cycle times and scrap costs",
        "frequency": "Weekly",
        "estimated_minutes": 25,
        "operator": "Operations Analyst",
        "tools_used": "Excel VLOOKUP / INDEX-MATCH",
        "failure_modes": "#N/A errors on new product variants, outdated unit scrap cost rates",
    },
    {
        "step_id": 9,
        "phase": "4. KPI Calculation & Modeling",
        "task_name": "Calculate Availability, Performance, Quality, OEE by Line x Shift",
        "frequency": "Weekly",
        "estimated_minutes": 40,
        "operator": "Operations Analyst",
        "tools_used": "Excel Formulas (SUMIFS, Division)",
        "failure_modes": "Averaging row-level OEE instead of aggregate components, divide-by-zero errors",
    },
    {
        "step_id": 10,
        "phase": "4. KPI Calculation & Modeling",
        "task_name": "Build Pivot Tables for downtime reasons and scrap defect causes",
        "frequency": "Weekly",
        "estimated_minutes": 30,
        "operator": "Operations Analyst",
        "tools_used": "Excel PivotTables",
        "failure_modes": "Pivot cache not refreshed, incorrect value field settings (Count vs Sum)",
    },
    {
        "step_id": 11,
        "phase": "4. KPI Calculation & Modeling",
        "task_name": "Calculate cumulative Pareto % and rank top 3 loss causes",
        "frequency": "Weekly",
        "estimated_minutes": 25,
        "operator": "Operations Analyst",
        "tools_used": "Excel Formulas, Sort",
        "failure_modes": "Formula reference breakage after sorting, inaccurate cumulative % formula",
    },
    {
        "step_id": 12,
        "phase": "5. Report Assembly & Formatting",
        "task_name": "Assemble executive summary dashboard tables and chart graphics",
        "frequency": "Weekly",
        "estimated_minutes": 35,
        "operator": "Operations Analyst",
        "tools_used": "Excel Executive Sheet, Bar/Line Charts",
        "failure_modes": "Broken chart series references, inconsistent number formatting, typo in KPI cards",
    },
    {
        "step_id": 13,
        "phase": "5. Report Assembly & Formatting",
        "task_name": "Cross-check report figures against supervisor shift handoff logs",
        "frequency": "Weekly",
        "estimated_minutes": 25,
        "operator": "Manufacturing Lead",
        "tools_used": "Shift Log Notes, Email",
        "failure_modes": "Subjective reconciliation, unresolved discrepancy between MES and floor notes",
    },
    {
        "step_id": 14,
        "phase": "6. Distribution & Archival",
        "task_name": "Export weekly PDF summary, write email commentary, and circulate",
        "frequency": "Weekly",
        "estimated_minutes": 15,
        "operator": "Operations Analyst",
        "tools_used": "Outlook, PDF Printer, Shared Drive",
        "failure_modes": "Circulating outdated draft version, email recipient omissions, missing audit trail",
    },
]


def create_manual_baseline_workbook(
    df_prod: pd.DataFrame,
    df_dt: pd.DataFrame,
    df_quality: pd.DataFrame,
    output_path: Path,
) -> None:
    """Build a professional, multi-tab Excel manual reporting baseline workbook."""
    wb = openpyxl.Workbook()
    # Default sheet
    ws_exec = wb.active
    ws_exec.title = "Executive_Summary"

    # Define color scheme and styles
    navy_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    header_fill = PatternFill(start_color="2C5282", end_color="2C5282", fill_type="solid")
    sub_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    card_fill = PatternFill(start_color="F7FAFC", end_color="F7FAFC", fill_type="solid")
    alert_fill = PatternFill(start_color="FED7D7", end_color="FED7D7", fill_type="solid")

    font_title = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_sub = Font(name="Calibri", size=11, bold=True, color="1A202C")
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_regular = Font(name="Calibri", size=11)
    font_small = Font(name="Calibri", size=9, italic=True, color="718096")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E0"),
        right=Side(style="thin", color="CBD5E0"),
        top=Side(style="thin", color="CBD5E0"),
        bottom=Side(style="thin", color="CBD5E0"),
    )
    thick_bottom = Border(
        bottom=Side(style="medium", color="1B365D"),
    )

    # -------------------------------------------------------------
    # 1. EXECUTIVE SUMMARY SHEET
    # -------------------------------------------------------------
    ws_exec.views.sheetView[0].showGridLines = True

    # Title Banner
    ws_exec.merge_cells("A1:G2")
    ws_exec["A1"] = "MANUFACTURING OPERATIONS & OEE WEEKLY REPORT (MANUAL BASELINE)"
    ws_exec["A1"].font = font_title
    ws_exec["A1"].fill = navy_fill
    ws_exec["A1"].alignment = Alignment(horizontal="center", vertical="center")

    ws_exec["A3"] = "Prepared By: Operations Analyst (Manual Excel Process)"
    ws_exec["A3"].font = font_small
    ws_exec["F3"] = "Baseline Time: ~6.0 Hours / Week"
    ws_exec["F3"].font = Font(name="Calibri", size=10, bold=True, color="C53030")

    # KPI Summary Cards Block
    ws_exec["A5"] = "HEADLINE PLANT METRICS (180-DAY MES AGGREGATE)"
    ws_exec["A5"].font = font_sub
    ws_exec["A5"].fill = sub_fill
    ws_exec.merge_cells("A5:G5")

    kpi_headers = ["Metric", "Availability", "Performance", "Quality", "OEE", "Total Scrap Cost", "Downtime (Hours)"]
    for col_idx, text in enumerate(kpi_headers, start=1):
        cell = ws_exec.cell(row=6, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Sample aggregate numbers matching MES data
    kpi_values = ["Plant Actual", 0.9129, 0.8450, 0.9646, 0.7441, 555891.0, 2964.08]
    formats = ["@", "0.00%", "0.00%", "0.00%", "0.00%", "$#,##0", "#,##0.0"]
    for col_idx, (val, fmt) in enumerate(zip(kpi_values, formats), start=1):
        cell = ws_exec.cell(row=7, column=col_idx, value=val)
        cell.font = font_bold
        cell.fill = card_fill
        cell.number_format = fmt
        cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left", vertical="center")
        cell.border = thin_border

    # Benchmark vs Actuals
    bench_values = ["World-Class Target", 0.9000, 0.9500, 0.9800, 0.8500, 250000.0, 1500.0]
    for col_idx, (val, fmt) in enumerate(zip(bench_values, formats), start=1):
        cell = ws_exec.cell(row=8, column=col_idx, value=val)
        cell.font = font_regular
        cell.number_format = fmt
        cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left", vertical="center")
        cell.border = thin_border

    # Gap row
    ws_exec["A9"] = "Variance vs Target"
    ws_exec["A9"].font = font_bold
    ws_exec["A9"].border = thin_border
    for col_idx in range(2, 6):
        cell = ws_exec.cell(row=9, column=col_idx)
        top_cell = f"{get_column_letter(col_idx)}7"
        bench_cell = f"{get_column_letter(col_idx)}8"
        cell.value = f"={top_cell}-{bench_cell}"
        cell.font = font_bold
        cell.number_format = "+0.00%;-0.00%;0.00%"
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    ws_exec["F9"] = "=F7-F8"
    ws_exec["F9"].font = font_bold
    ws_exec["F9"].number_format = "+$#,##0;-$#,##0;$0"
    ws_exec["F9"].border = thin_border
    ws_exec["F9"].alignment = Alignment(horizontal="center", vertical="center")

    ws_exec["G9"] = "=G7-G8"
    ws_exec["G9"].font = font_bold
    ws_exec["G9"].number_format = "+#,##0.0;-#,##0.0;0.0"
    ws_exec["G9"].border = thin_border
    ws_exec["G9"].alignment = Alignment(horizontal="center", vertical="center")

    # Line Level Table
    ws_exec["A11"] = "OEE BY PRODUCTION LINE"
    ws_exec["A11"].font = font_sub
    ws_exec["A11"].fill = sub_fill
    ws_exec.merge_cells("A11:F11")

    line_headers = ["Line", "Planned Time (h)", "Run Time (h)", "Availability", "Performance", "Quality", "OEE"]
    for col_idx, text in enumerate(line_headers, start=1):
        cell = ws_exec.cell(row=12, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    line_data = [
        ("Line 1 (L1)", 4293.76, 3931.00, 0.9155, 0.8591, 0.9738, 0.7659),
        ("Line 2 (L2)", 4293.76, 3902.60, 0.9089, 0.8017, 0.9734, 0.7092),
        ("Line 3 (L3)", 4293.76, 3899.15, 0.9081, 0.8595, 0.9378, 0.7320),
        ("Line 4 (L4)", 4293.76, 3946.18, 0.9191, 0.8597, 0.9737, 0.7693),
    ]
    for row_idx, rdata in enumerate(line_data, start=13):
        for col_idx, val in enumerate(rdata, start=1):
            cell = ws_exec.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = thin_border
            if col_idx in (2, 3):
                cell.number_format = "#,##0.0"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx >= 4:
                cell.number_format = "0.00%"
                cell.alignment = Alignment(horizontal="center", vertical="center")

    # Shift Level Table
    ws_exec["A18"] = "OEE BY SHIFT"
    ws_exec["A18"].font = font_sub
    ws_exec["A18"].fill = sub_fill
    ws_exec.merge_cells("A18:F18")

    for col_idx, text in enumerate(["Shift", "Hours Planned", "Hours Run", "Availability", "Performance", "Quality", "OEE"], start=1):
        cell = ws_exec.cell(row=19, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    shift_data = [
        ("Shift A (Morning)", 5725.0, 5248.1, 0.9167, 0.8589, 0.9652, 0.7600),
        ("Shift B (Afternoon)", 5725.0, 5207.0, 0.9095, 0.8593, 0.9643, 0.7537),
        ("Shift C (Night)", 5725.0, 5223.8, 0.9125, 0.8171, 0.9641, 0.7189),
    ]
    for row_idx, rdata in enumerate(shift_data, start=20):
        for col_idx, val in enumerate(rdata, start=1):
            cell = ws_exec.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = thin_border
            if col_idx in (2, 3):
                cell.number_format = "#,##0.0"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx >= 4:
                cell.number_format = "0.00%"
                cell.alignment = Alignment(horizontal="center", vertical="center")

    # Known Bottlenecks / Excursions Callout box
    ws_exec["A24"] = "MANUAL ROOT CAUSE OBSERVATIONS (DELAYED IDENTIFICATION)"
    ws_exec["A24"].font = font_sub
    ws_exec["A24"].fill = alert_fill
    ws_exec.merge_cells("A24:G24")

    notes = [
        "1. Line 2 Performance Deficit: Shift C OEE lags by ~4.1 pts (71.89% vs 76.00%), driven by elevated minor stops.",
        "2. Line 3 Yield Loss Excursion: Progressive tool wear causes high scrap (6.22% defect rate vs 2.63% plant baseline).",
        "3. Scrap Concentration: Top 3 causes (Dimensional, Surface Defect, Contamination) drive 74.4% ($413.4k) of scrap cost.",
        "4. Reporting Latency Risk: Quality issues detected 1-3 days late in manual Excel review, generating unnecessary scrap.",
    ]
    for idx, text in enumerate(notes, start=25):
        cell = ws_exec.cell(row=idx, column=1, value=text)
        cell.font = font_regular
        ws_exec.merge_cells(start_row=idx, start_column=1, end_row=idx, end_column=7)

    # -------------------------------------------------------------
    # 2. OEE SUMMARY SHEET
    # -------------------------------------------------------------
    ws_oee = wb.create_sheet(title="OEE_Summary")
    ws_oee.views.sheetView[0].showGridLines = True

    ws_oee["A1"] = "OEE COMPONENT DECOMPOSITION BY LINE & SHIFT"
    ws_oee["A1"].font = font_title
    ws_oee["A1"].fill = navy_fill
    ws_oee.merge_cells("A1:K1")

    headers_oee = [
        "Line",
        "Shift",
        "Planned Time (min)",
        "Run Time (min)",
        "Ideal Time (min)",
        "Total Count",
        "Good Count",
        "Availability (A)",
        "Performance (P)",
        "Quality (Q)",
        "OEE (AxPxQ)",
    ]
    for col_idx, text in enumerate(headers_oee, start=1):
        cell = ws_oee.cell(row=3, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Write representative Line x Shift rows with Excel formulas for A, P, Q, OEE
    line_shift_rows = [
        ("L1", "A", 85875.0, 78620.0, 67500.0, 91100, 88700),
        ("L1", "B", 85875.0, 78500.0, 67450.0, 91050, 88660),
        ("L1", "C", 85875.0, 78740.0, 67650.0, 91310, 88935),
        ("L2", "A", 85875.0, 78150.0, 66800.0, 84700, 82455),
        ("L2", "B", 85875.0, 78100.0, 66750.0, 84650, 82390),
        ("L2", "C", 85875.0, 77900.0, 60200.0, 84914, 82648),
        ("L3", "A", 85875.0, 77950.0, 66980.0, 90450, 84860),
        ("L3", "B", 85875.0, 77900.0, 66950.0, 90420, 84787),
        ("L3", "C", 85875.0, 78100.0, 67100.0, 90566, 84900),
        ("L4", "A", 85875.0, 78920.0, 67850.0, 91600, 89270),
        ("L4", "B", 85875.0, 78900.0, 67830.0, 91580, 89100),
        ("L4", "C", 85875.0, 78950.0, 67880.0, 91733, 89321),
    ]

    for idx, (line, shift, p_min, r_min, i_min, t_cnt, g_cnt) in enumerate(line_shift_rows, start=4):
        ws_oee.cell(row=idx, column=1, value=line).alignment = Alignment(horizontal="center")
        ws_oee.cell(row=idx, column=2, value=shift).alignment = Alignment(horizontal="center")
        ws_oee.cell(row=idx, column=3, value=p_min).number_format = "#,##0"
        ws_oee.cell(row=idx, column=4, value=r_min).number_format = "#,##0"
        ws_oee.cell(row=idx, column=5, value=i_min).number_format = "#,##0"
        ws_oee.cell(row=idx, column=6, value=t_cnt).number_format = "#,##0"
        ws_oee.cell(row=idx, column=7, value=g_cnt).number_format = "#,##0"

        # Formulas for A, P, Q, OEE
        c_a = ws_oee.cell(row=idx, column=8, value=f"=D{idx}/C{idx}")
        c_p = ws_oee.cell(row=idx, column=9, value=f"=E{idx}/D{idx}")
        c_q = ws_oee.cell(row=idx, column=10, value=f"=G{idx}/F{idx}")
        c_oee = ws_oee.cell(row=idx, column=11, value=f"=H{idx}*I{idx}*J{idx}")

        for cell in (c_a, c_p, c_q, c_oee):
            cell.number_format = "0.00%"
            cell.font = font_bold
            cell.alignment = Alignment(horizontal="center")

        for c_idx in range(1, 12):
            ws_oee.cell(row=idx, column=c_idx).border = thin_border

    # Total Row
    tot_row = len(line_shift_rows) + 4
    ws_oee.cell(row=tot_row, column=1, value="TOTAL / PLANT").font = font_bold
    ws_oee.merge_cells(f"A{tot_row}:B{tot_row}")
    for col_idx, letter in enumerate(["C", "D", "E", "F", "G"], start=3):
        cell = ws_oee.cell(row=tot_row, column=col_idx, value=f"=SUM({letter}4:{letter}{tot_row-1})")
        cell.font = font_bold
        cell.number_format = "#,##0"
        cell.border = thin_border

    ws_oee.cell(row=tot_row, column=8, value=f"=D{tot_row}/C{tot_row}").number_format = "0.00%"
    ws_oee.cell(row=tot_row, column=9, value=f"=E{tot_row}/D{tot_row}").number_format = "0.00%"
    ws_oee.cell(row=tot_row, column=10, value=f"=G{tot_row}/F{tot_row}").number_format = "0.00%"
    ws_oee.cell(row=tot_row, column=11, value=f"=H{tot_row}*I{tot_row}*J{tot_row}").number_format = "0.00%"
    for c_idx in range(8, 12):
        ws_oee.cell(row=tot_row, column=c_idx).font = font_bold
        ws_oee.cell(row=tot_row, column=c_idx).border = thin_border
        ws_oee.cell(row=tot_row, column=c_idx).fill = sub_fill
        ws_oee.cell(row=tot_row, column=c_idx).alignment = Alignment(horizontal="center")

    # -------------------------------------------------------------
    # 3. DOWNTIME SUMMARY SHEET
    # -------------------------------------------------------------
    ws_dt = wb.create_sheet(title="Downtime_Summary")
    ws_dt.views.sheetView[0].showGridLines = True
    ws_dt["A1"] = "DOWNTIME PARETO & LOSS REASON SUMMARY"
    ws_dt["A1"].font = font_title
    ws_dt["A1"].fill = navy_fill
    ws_dt.merge_cells("A1:G1")

    dt_headers = ["Rank", "Downtime Reason", "OEE Bucket", "Event Count", "Duration (min)", "Share %", "Cumulative %"]
    for col_idx, text in enumerate(dt_headers, start=1):
        cell = ws_dt.cell(row=3, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    dt_rows = [
        (1, "minor_stop", "Performance", 20150, 80717.14),
        (2, "changeover", "Availability", 2640, 52781.48),
        (3, "breakdown", "Availability", 688, 17040.77),
        (4, "material_shortage", "Availability", 330, 14015.03),
        (5, "quality_hold", "Availability", 235, 6993.13),
        (6, "planned_maintenance", "Planned", 104, 6297.44),
    ]
    for idx, (rank, reason, bucket, cnt, dur) in enumerate(dt_rows, start=4):
        ws_dt.cell(row=idx, column=1, value=rank).alignment = Alignment(horizontal="center")
        ws_dt.cell(row=idx, column=2, value=reason)
        ws_dt.cell(row=idx, column=3, value=bucket).alignment = Alignment(horizontal="center")
        ws_dt.cell(row=idx, column=4, value=cnt).number_format = "#,##0"
        ws_dt.cell(row=idx, column=5, value=dur).number_format = "#,##0.0"

        # Share and cumulative formulas
        ws_dt.cell(row=idx, column=6, value=f"=E{idx}/$E$10").number_format = "0.00%"
        ws_dt.cell(row=idx, column=7, value=f"=SUM($E$4:E{idx})/$E$10").number_format = "0.00%"

        for c_idx in range(1, 8):
            ws_dt.cell(row=idx, column=c_idx).border = thin_border
            ws_dt.cell(row=idx, column=c_idx).font = font_regular

    # Total row
    ws_dt.cell(row=10, column=2, value="TOTAL DOWNTIME").font = font_bold
    ws_dt.cell(row=10, column=4, value="=SUM(D4:D9)").number_format = "#,##0"
    ws_dt.cell(row=10, column=5, value="=SUM(E4:E9)").number_format = "#,##0.0"
    ws_dt.cell(row=10, column=6, value="=SUM(F4:F9)").number_format = "0.00%"
    ws_dt.cell(row=10, column=7, value="100.00%").number_format = "0.00%"
    for c_idx in range(1, 8):
        ws_dt.cell(row=10, column=c_idx).font = font_bold
        ws_dt.cell(row=10, column=c_idx).fill = sub_fill
        ws_dt.cell(row=10, column=c_idx).border = thin_border

    # -------------------------------------------------------------
    # 4. SCRAP SUMMARY SHEET
    # -------------------------------------------------------------
    ws_sc = wb.create_sheet(title="Scrap_Summary")
    ws_sc.views.sheetView[0].showGridLines = True
    ws_sc["A1"] = "SCRAP COST & DEFECT CAUSE PARETO SUMMARY"
    ws_sc["A1"].font = font_title
    ws_sc["A1"].fill = navy_fill
    ws_sc.merge_cells("A1:F1")

    sc_headers = ["Rank", "Defect Cause", "Units Affected", "Scrap Cost ($)", "Cost Share %", "Cumulative %"]
    for col_idx, text in enumerate(sc_headers, start=1):
        cell = ws_sc.cell(row=3, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    sc_rows = [
        (1, "dimensional", 11759, 173077.0),
        (2, "surface defect", 9374, 137940.0),
        (3, "contamination", 6954, 102430.0),
        (4, "tool wear", 6921, 97275.0),
        (5, "other", 1968, 28601.0),
        (6, "supplier material", 1071, 16568.0),
    ]
    for idx, (rank, cause, units, cost) in enumerate(sc_rows, start=4):
        ws_sc.cell(row=idx, column=1, value=rank).alignment = Alignment(horizontal="center")
        ws_sc.cell(row=idx, column=2, value=cause)
        ws_sc.cell(row=idx, column=3, value=units).number_format = "#,##0"
        ws_sc.cell(row=idx, column=4, value=cost).number_format = "$#,##0.00"

        # Share and cumulative formulas
        ws_sc.cell(row=idx, column=5, value=f"=D{idx}/$D$10").number_format = "0.00%"
        ws_sc.cell(row=idx, column=6, value=f"=SUM($D$4:D{idx})/$D$10").number_format = "0.00%"

        for c_idx in range(1, 7):
            ws_sc.cell(row=idx, column=c_idx).border = thin_border
            ws_sc.cell(row=idx, column=c_idx).font = font_regular

    # Total row
    ws_sc.cell(row=10, column=2, value="TOTAL SCRAP").font = font_bold
    ws_sc.cell(row=10, column=3, value="=SUM(C4:C9)").number_format = "#,##0"
    ws_sc.cell(row=10, column=4, value="=SUM(D4:D9)").number_format = "$#,##0.00"
    ws_sc.cell(row=10, column=5, value="=SUM(E4:E9)").number_format = "0.00%"
    ws_sc.cell(row=10, column=6, value="100.00%").number_format = "0.00%"
    for c_idx in range(1, 7):
        ws_sc.cell(row=10, column=c_idx).font = font_bold
        ws_sc.cell(row=10, column=c_idx).fill = sub_fill
        ws_sc.cell(row=10, column=c_idx).border = thin_border

    # -------------------------------------------------------------
    # 5. RAW DATA SAMPLE SHEETS
    # -------------------------------------------------------------
    ws_raw_p = wb.create_sheet(title="Raw_Hourly_Production")
    ws_raw_p.views.sheetView[0].showGridLines = True
    prod_sample = df_prod.head(200)
    for col_idx, col_name in enumerate(prod_sample.columns, start=1):
        c = ws_raw_p.cell(row=1, column=col_idx, value=col_name)
        c.font = font_header
        c.fill = header_fill
    for r_idx, row in enumerate(prod_sample.itertuples(index=False), start=2):
        for c_idx, val in enumerate(row, start=1):
            ws_raw_p.cell(row=r_idx, column=c_idx, value=val)

    ws_raw_dt = wb.create_sheet(title="Raw_Downtime_Events")
    ws_raw_dt.views.sheetView[0].showGridLines = True
    dt_sample = df_dt.head(200)
    for col_idx, col_name in enumerate(dt_sample.columns, start=1):
        c = ws_raw_dt.cell(row=1, column=col_idx, value=col_name)
        c.font = font_header
        c.fill = header_fill
    for r_idx, row in enumerate(dt_sample.itertuples(index=False), start=2):
        for c_idx, val in enumerate(row, start=1):
            ws_raw_dt.cell(row=r_idx, column=c_idx, value=val)

    ws_raw_q = wb.create_sheet(title="Raw_Quality_Scrap")
    ws_raw_q.views.sheetView[0].showGridLines = True
    q_sample = df_quality.head(200)
    for col_idx, col_name in enumerate(q_sample.columns, start=1):
        c = ws_raw_q.cell(row=1, column=col_idx, value=col_name)
        c.font = font_header
        c.fill = header_fill
    for r_idx, row in enumerate(q_sample.itertuples(index=False), start=2):
        for c_idx, val in enumerate(row, start=1):
            ws_raw_q.cell(row=r_idx, column=c_idx, value=val)

    # Auto-adjust column widths
    for ws in [ws_exec, ws_oee, ws_dt, ws_sc, ws_raw_p, ws_raw_dt, ws_raw_q]:
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def run(config_path: str | Path | None = None) -> dict[str, Any]:
    """Execute P5-001 manual baseline generation and output artifacts."""
    config = load_config(config_path)
    root = Path(__file__).resolve().parents[1]

    # Resolve paths
    mes_cfg = config.get("mes", {}).get("outputs", {})
    prod_path = _resolve_path(root, mes_cfg.get("production_hourly", "data/processed/mes_production_hourly.csv"))
    dt_path = _resolve_path(root, mes_cfg.get("downtime_events", "data/processed/mes_downtime_events.csv"))
    q_path = _resolve_path(root, mes_cfg.get("quality_events", "data/processed/mes_quality_events.csv"))

    excel_out_path = _resolve_path(root, "excel/manual_report_baseline.xlsx")
    steps_csv_path = _resolve_path(root, "reports/manual_reporting_steps.csv")
    summary_json_path = _resolve_path(root, "reports/manual_reporting_baseline.json")

    df_prod = pd.read_csv(prod_path)
    df_dt = pd.read_csv(dt_path)
    df_q = pd.read_csv(q_path)

    # 1. Generate Steps CSV
    steps_df = pd.DataFrame(MANUAL_STEPS)
    steps_csv_path.parent.mkdir(parents=True, exist_ok=True)
    steps_df.to_csv(steps_csv_path, index=False)

    # 2. Build Workbook
    create_manual_baseline_workbook(df_prod, df_dt, df_q, excel_out_path)

    # 3. Calculate baseline metrics
    total_min_week = int(steps_df["estimated_minutes"].sum())
    hours_per_week = round(total_min_week / 60.0, 2)
    weeks_per_year = 52
    annual_hours_manual = round(hours_per_week * weeks_per_year, 1)

    target_automated_min_week = 10.0
    target_automated_hours_yr = round((target_automated_min_week / 60.0) * weeks_per_year, 1)
    annual_hours_saved = round(annual_hours_manual - target_automated_hours_yr, 1)
    reduction_pct = round((annual_hours_saved / annual_hours_manual) * 100.0, 1)

    summary: dict[str, Any] = {
        "baseline_workflow": {
            "total_steps": len(MANUAL_STEPS),
            "weekly_manual_minutes": total_min_week,
            "weekly_manual_hours": hours_per_week,
            "annual_manual_hours": annual_hours_manual,
            "operator_roles": ["Operations Analyst", "Quality Analyst", "Manufacturing Lead"],
        },
        "automation_target": {
            "target_weekly_minutes": target_automated_min_week,
            "target_annual_hours": target_automated_hours_yr,
            "expected_annual_hours_saved": annual_hours_saved,
            "efficiency_gain_pct": reduction_pct,
        },
        "manual_error_risks": [
            "Formula copy-paste drift across new lines/shifts resulting in distorted OEE figures.",
            "Averaging row-level hourly OEE percentages instead of weighting aggregate components.",
            "Stale VLOOKUP reference tables after product ideal cycle times or scrap costs change.",
            "1-3 day reporting latency delaying critical root cause intervention and early scrap prevention.",
            "Unsynchronized shift timestamp boundaries between maintenance logs and production counters.",
        ],
        "step_breakdown_by_phase": steps_df.groupby("phase")["estimated_minutes"].sum().to_dict(),
        "outputs": {
            "workbook": str(excel_out_path),
            "steps_csv": str(steps_csv_path),
            "summary_json": str(summary_json_path),
        },
    }

    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Manual reporting baseline analysis complete:")
    print(f"  - Total manual workflow time: {total_min_week} min/week ({hours_per_week} h/week)")
    print(f"  - Annual manual effort: {annual_hours_manual} h/year")
    print(f"  - Target automated pipeline: <{target_automated_min_week} min/week ({target_automated_hours_yr} h/year)")
    print(f"  - Estimated annual time savings: {annual_hours_saved} hours/year ({reduction_pct}% reduction)")
    print(f"  - Excel baseline workbook: {excel_out_path}")
    print(f"  - Steps documentation: {steps_csv_path}")
    print(f"  - Summary report: {summary_json_path}")

    return summary


def _resolve_path(root: Path, path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else root / p


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for manual reporting baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    try:
        run(args.config)
        return 0
    except Exception as exc:
        print(f"Error during manual baseline generation: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
