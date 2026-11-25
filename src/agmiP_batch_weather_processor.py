
"""
BATCH AgMIP DSSAT WEATHER DATA PROCESSOR
========================================

Processes multiple CMIP6/AgMIP climate models and SSP scenarios.

Functions:
1. Automatically identifies GCMs from filenames and metadata.
2. Detects SSP scenarios.
3. Reads simulation dates from metadata.
4. Corrects daily dates and years.
5. Detects and removes an extra initial source year when verified.
6. Handles leap years.
7. Aggregates daily data into monthly and annual datasets.
8. Performs basic weather-data quality checks.
9. Exports Daily, Monthly, Annual CSV files.
10. Generates a processing QC report.

Requirements:
    pip install pandas numpy
"""

import os
import re
import glob
import traceback
import pandas as pd
import numpy as np


# ============================================================
# 1. USER SETTINGS
# ============================================================

INPUT_DIR = (
    "/home/goitomk/AI/cloud/PyCSG/output"
)

OUTPUT_DIR = (
    "/home/goitomk/AI/cloud/PyCSG/agreegate/AgMIP_Processed"
)

# Process only these file extensions.
FILE_PATTERNS = ["*.AgMIP", "*.agMIP", "*.txt"]

# Available scenarios
SCENARIOS = [
    "ssp119",
    "ssp126",
    "ssp245",
    "ssp370",
    "ssp434",
    "ssp460",
    "ssp534",
    "ssp585",
]

# Remove an extra initial year only when verified.
DROP_EXTRA_FIRST_YEAR = True

# Expected DSSAT weather variables
WEATHER_VARIABLES = [
    "SRAD", "TMAX", "TMIN", "RAIN",
    "WIND", "DEWP", "VPRS", "RHUM"
]

# Aggregation methods
SUM_VARIABLES = ["SRAD", "RAIN"]

MEAN_VARIABLES = [
    "TMAX", "TMIN", "WIND",
    "DEWP", "VPRS", "RHUM"
]

# ============================================================
# 2. SUPPORTED CLIMATE MODELS
# ============================================================

GCM_MODELS = [
    "access_cm2",
    "access_esm1_5",
    "awi_cm_1_1_mr",
    "awi_esm_1_1_lr",
    "bcc_csm2_mr",
    "bcc_esm1",
    "cams_csm1_0",
    "canesm5",
    "canesm5_canoe",
    "cesm2",
    "cesm2_fv2",
    "cesm2_waccm",
    "cesm2_waccm_fv2",
    "ciesm",
    "cmcc_cm2_hr4",
    "cmcc_cm2_sr5",
    "cmcc_esm2",
    "cnrm_cm6_1",
    "cnrm_cm6_1_hr",
    "cnrm_esm2_1",
    "e3sm_1_0",
    "e3sm_1_1",
    "e3sm_1_1_eca",
    "ec_earth3",
    "ec_earth3_aerchem",
    "ec_earth3_cc",
    "ec_earth3_veg",
    "ec_earth3_veg_lr",
    "fgoals_f3_l",
    "fgoals_g3",
    "fio_esm_2_0",
    "gfdl_esm4",
    "giss_e2_1_g",
    "giss_e2_1_h",
    "hadgem3_gc31_ll",
    "hadgem3_gc31_mm",
    "iitm_esm",
    "inm_cm4_8",
    "inm_cm5_0",
    "ipsl_cm5a2_inca",
    "ipsl_cm6a_lr",
    "kace_1_0_g",
    "kiost_esm",
    "mcm_ua_1_0",
    "miroc6",
    "miroc_es2h",
    "miroc_es2l",
    "mpi_esm_1_2_ham",
    "mpi_esm1_2_hr",
    "mpi_esm1_2_lr",
    "mri_esm2_0",
    "nesm3",
    "norcp1",
    "noresm2_lm",
    "noresm2_mm",
    "sam0_unicon",
    "taiesm1",
    "ukesm1_0_ll",
]


# ============================================================
# 3. CREATE OUTPUT DIRECTORIES
# ============================================================

for folder in [
    "Daily",
    "Monthly",
    "Annual",
    "Processing_Summary",
]:
    os.makedirs(
        os.path.join(OUTPUT_DIR, folder),
        exist_ok=True
    )


# ============================================================
# 4. IDENTIFY CLIMATE MODEL
# ============================================================

def normalize_name(value):
    """Remove punctuation and separators for model matching."""
    return re.sub(
        r"[^a-z0-9]",
        "",
        str(value).lower()
    )


def identify_gcm(filename, metadata):

    search_text = normalize_name(
        filename + " " + metadata
    )

    # Longest names first to prevent partial matches.
    models = sorted(
        GCM_MODELS,
        key=len,
        reverse=True
    )

    for model in models:

        if normalize_name(model) in search_text:
            return model

    return "unknown_gcm"


# ============================================================
# 5. IDENTIFY SSP SCENARIO
# ============================================================

def identify_scenario(filename, metadata):

    search_text = (
        filename + " " + metadata
    ).lower()

    for scenario in SCENARIOS:

        if re.search(
            rf"(?<![a-z0-9]){scenario}(?![a-z0-9])",
            search_text
        ):
            return scenario

    # Also allow scenario names separated by punctuation.
    normalized = normalize_name(search_text)

    for scenario in SCENARIOS:

        if normalize_name(scenario) in normalized:
            return scenario

    return "unknown_ssp"


# ============================================================
# 6. READ METADATA
# ============================================================

def read_metadata(filepath):

    with open(
        filepath,
        "r",
        encoding="utf-8",
        errors="replace"
    ) as f:

        lines = f.readlines()

    metadata = lines[0].strip()

    match = re.search(
        r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})",
        metadata
    )

    if not match:

        raise ValueError(
            "Simulation date range not found in metadata."
        )

    start_date = pd.Timestamp(match.group(1))
    end_date = pd.Timestamp(match.group(2))

    if end_date < start_date:
        raise ValueError("End date precedes start date.")

    return lines, metadata, start_date, end_date


# ============================================================
# 7. READ DAILY WEATHER DATA
# ============================================================

def read_weather_data(filepath, lines):

    header_index = None

    for i, line in enumerate(lines):

        if line.strip().upper().startswith("@DATE"):

            header_index = i
            break

    if header_index is None:

        raise ValueError(
            "Weather data header (@DATE) not found."
        )

    columns = lines[header_index].strip().split()

    columns[0] = columns[0].replace("@", "")

    df = pd.read_csv(
        filepath,
        sep=r"\s+",
        skiprows=header_index + 1,
        names=columns,
        engine="python",
        comment="!"
    )

    df = df.dropna(how="all").reset_index(drop=True)

    if df.empty:
        raise ValueError("No daily weather observations found.")

    return df


# ============================================================
# 8. DETERMINE SOURCE YEAR
# ============================================================

def get_source_years(df):

    # DSSAT date format YYYYDDD, e.g. 1981001.
    if "DATE" in df.columns:

        date_values = pd.to_numeric(
            df["DATE"],
            errors="coerce"
        )

        valid = date_values.dropna()

        if len(valid) and (
            valid.astype(int).between(1000001, 9999366).all()
        ):
            return (
                valid.astype(int) // 1000
            )

        parsed = pd.to_datetime(
            df["DATE"],
            errors="coerce"
        )

        if parsed.notna().any():
            return parsed.dropna().dt.year

    # Alternative source with separate year column.
    for col in ["YYYY", "YEAR"]:

        if col in df.columns:

            years = pd.to_numeric(
                df[col],
                errors="coerce"
            )

            return years.dropna().astype(int)

    return None


# ============================================================
# 9. CORRECT DAILY DATE AND YEAR
# ============================================================

def correct_dates(df, start_date, end_date):

    df = df.copy()

    target_dates = pd.date_range(
        start=start_date,
        end=end_date,
        freq="D"
    )

    expected_days = len(target_dates)

    original_count = len(df)

    if original_count != expected_days:

        source_years = get_source_years(df)

        if source_years is None:

            raise ValueError(
                "Record count differs from metadata, "
                "and source years cannot be identified."
            )

        source_years = sorted(source_years.unique())

        removed_year = None

        if (
            DROP_EXTRA_FIRST_YEAR
            and len(source_years) > 1
            and source_years[1] - source_years[0] == 1
            and source_years[0] < start_date.year
        ):

            first_year = source_years[0]

            # Verify the first year is an extra initial year.
            candidate = df.copy()

            candidate_years = get_source_years(candidate)

            if candidate_years is not None:

                candidate = candidate.loc[
                    candidate_years.values != first_year
                ].copy()

                if len(candidate) == expected_days:

                    df = candidate.reset_index(drop=True)
                    removed_year = first_year

        if len(df) != expected_days:

            raise ValueError(
                f"Record mismatch: expected {expected_days}, "
                f"found {original_count}. "
                "Extra-year removal could not be verified."
            )

        if removed_year is not None:
            print(f"Removed extra source year: {removed_year}")

    df = df.reset_index(drop=True)

    # Reconstruct dates from metadata.
    df["DATE"] = target_dates

    # Remove original date components to avoid conflicts.
    for col in ["YYYY", "YEAR", "MM", "MONTH", "DD", "DAY"]:
        if col in df.columns:
            df.drop(columns=col, inplace=True)

    # Standardized date columns.
    df["YEAR"] = df["DATE"].dt.year
    df["MONTH"] = df["DATE"].dt.month
    df["DAY"] = df["DATE"].dt.day

    # Convert weather variables to numeric.
    for col in WEATHER_VARIABLES:

        if col in df.columns:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    return df


# ============================================================
# 10. AGGREGATE DAILY DATA
# ============================================================

def aggregate_weather(df):

    aggregation = {}

    for col in SUM_VARIABLES:

        if col in df.columns:
            aggregation[col] = "sum"

    for col in MEAN_VARIABLES:

        if col in df.columns:
            aggregation[col] = "mean"

    if not aggregation:

        raise ValueError(
            "No recognized weather variables found."
        )

    # Monthly aggregation.
    monthly = (
        df.set_index("DATE")
        .resample("MS")
        .agg(aggregation)
        .reset_index()
    )

    monthly["YEAR"] = monthly["DATE"].dt.year
    monthly["MONTH"] = monthly["DATE"].dt.month

    monthly = monthly[
        ["DATE", "YEAR", "MONTH"] +
        list(aggregation.keys())
    ]

    # Annual aggregation.
    annual = (
        df.set_index("DATE")
        .resample("YS")
        .agg(aggregation)
        .reset_index()
    )

    annual["YEAR"] = annual["DATE"].dt.year

    annual = annual[
        ["YEAR"] + list(aggregation.keys())
    ]

    return monthly, annual


# ============================================================
# 11. QUALITY CONTROL
# ============================================================

def quality_control(df):

    report = []

    report.append(
        f"Daily records: {len(df)}"
    )

    report.append(
        f"Start date: {df['DATE'].min()}"
    )

    report.append(
        f"End date: {df['DATE'].max()}"
    )

    report.append(
        f"Duplicate dates: {df['DATE'].duplicated().sum()}"
    )

    report.append(
        f"Missing dates: "
        f"{df['DATE'].diff().dt.days.fillna(1).ne(1).sum()}"
    )

    report.append("\nMissing values:")

    for col in WEATHER_VARIABLES:

        if col in df.columns:

            report.append(
                f"{col}: {df[col].isna().sum()}"
            )

    if "RAIN" in df.columns:

        report.append(
            f"Negative rainfall records: "
            f"{(df['RAIN'] < 0).sum()}"
        )

    if "TMAX" in df.columns and "TMIN" in df.columns:

        report.append(
            f"TMIN greater than TMAX: "
            f"{(df['TMIN'] > df['TMAX']).sum()}"
        )

    return report


# ============================================================
# 12. PROCESS ONE AGMI P FILE
# ============================================================

def process_file(filepath):

    filename = os.path.basename(filepath)

    print("\n" + "=" * 65)
    print("PROCESSING:", filename)
    print("=" * 65)

    lines, metadata, start_date, end_date = (
        read_metadata(filepath)
    )

    gcm = identify_gcm(filename, metadata)

    scenario = identify_scenario(filename, metadata)

    print("GCM:", gcm)
    print("Scenario:", scenario)
    print("Metadata:", metadata)
    print("Period:", start_date.date(), "to", end_date.date())

    if gcm == "unknown_gcm":
        raise ValueError("Climate model not recognized.")

    if scenario == "unknown_ssp":
        raise ValueError("SSP scenario not recognized.")

    # Read source weather observations.
    df = read_weather_data(filepath, lines)

    print("Original records:", len(df))

    # Correct dates.
    df = correct_dates(
        df,
        start_date,
        end_date
    )

    # Aggregate.
    monthly, annual = aggregate_weather(df)

    # Output naming.
    base_name = (
        f"{gcm}_{scenario}_"
        f"{start_date.year}_{end_date.year}"
    )

    # Export folders.
    daily_file = os.path.join(
        OUTPUT_DIR,
        "Daily",
        base_name + "_Daily.csv"
    )

    monthly_file = os.path.join(
        OUTPUT_DIR,
        "Monthly",
        base_name + "_Monthly.csv"
    )

    annual_file = os.path.join(
        OUTPUT_DIR,
        "Annual",
        base_name + "_Annual.csv"
    )

    # Save CSV files.
    df.to_csv(daily_file, index=False)

    monthly.to_csv(monthly_file, index=False)

    annual.to_csv(annual_file, index=False)

    # Quality-control report.
    qc = quality_control(df)

    report_file = os.path.join(
        OUTPUT_DIR,
        "Processing_Summary",
        base_name + "_QC_Report.txt"
    )

    with open(
        report_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("AgMIP DSSAT WEATHER PROCESSING REPORT\n")
        f.write("=" * 50 + "\n\n")

        f.write(f"Input file: {filename}\n")
        f.write(f"GCM: {gcm}\n")
        f.write(f"Scenario: {scenario}\n")
        f.write(f"Metadata: {metadata}\n")
        f.write(f"Simulation period: {start_date} to {end_date}\n")

        f.write("\nQUALITY CONTROL\n")
        f.write("=" * 50 + "\n")

        f.write("\n".join(qc))

        f.write("\n\nOUTPUT FILES\n")
        f.write(daily_file + "\n")
        f.write(monthly_file + "\n")
        f.write(annual_file + "\n")

    print("\nProcessing completed successfully.")

    print("Daily records:", len(df))
    print("Monthly records:", len(monthly))
    print("Annual records:", len(annual))

    return {
        "Filename": filename,
        "GCM": gcm,
        "Scenario": scenario,
        "Start": str(start_date.date()),
        "End": str(end_date.date()),
        "Daily_records": len(df),
        "Monthly_records": len(monthly),
        "Annual_records": len(annual),
        "Status": "SUCCESS",
        "Error": ""
    }


# ============================================================
# 13. BATCH PROCESS ALL FILES
# ============================================================

def main():

    input_files = []

    for pattern in FILE_PATTERNS:

        input_files.extend(
            glob.glob(
                os.path.join(INPUT_DIR, pattern)
            )
        )

    input_files = sorted(set(input_files))

    if not input_files:

        raise FileNotFoundError(
            f"No AgMIP files found in {INPUT_DIR}"
        )

    print("\n==============================================")
    print("AgMIP DSSAT BATCH WEATHER PROCESSOR")
    print("==============================================")

    print("Supported GCMs:", len(GCM_MODELS))
    print("Input files found:", len(input_files))
    print("Output directory:", OUTPUT_DIR)

    results = []

    for i, filepath in enumerate(input_files, 1):

        print(
            f"\nFILE {i} OF {len(input_files)}"
        )

        try:

            result = process_file(filepath)

        except Exception as error:

            print("\nPROCESSING ERROR:")
            print(error)

            result = {
                "Filename": os.path.basename(filepath),
                "GCM": "",
                "Scenario": "",
                "Start": "",
                "End": "",
                "Daily_records": 0,
                "Monthly_records": 0,
                "Annual_records": 0,
                "Status": "FAILED",
                "Error": str(error)
            }

            traceback.print_exc()

        results.append(result)

    # Save master processing summary.
    summary = pd.DataFrame(results)

    summary_file = os.path.join(
        OUTPUT_DIR,
        "Processing_Summary",
        "AgMIP_Master_Processing_Summary.csv"
    )

    summary.to_csv(
        summary_file,
        index=False
    )

    # Final report.
    successful = (
        summary["Status"] == "SUCCESS"
    ).sum()

    failed = (
        summary["Status"] == "FAILED"
    ).sum()

    print("\n" + "=" * 65)
    print("AGMIP BATCH PROCESSING FINISHED")
    print("=" * 65)

    print("Total files:", len(input_files))
    print("Successful:", successful)
    print("Failed:", failed)

    print("\nMaster summary:")
    print(summary_file)

    print("\nOutput directory:")
    print(OUTPUT_DIR)

    print("\nProcessing results:")
    print(
        summary[
            ["Filename", "GCM", "Scenario", "Status"]
        ].to_string(index=False)
    )


# ============================================================
# 14. RUN PROCESSOR
# ============================================================

if __name__ == "__main__":

    main()
