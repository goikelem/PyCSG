
"""
AGMIP DSSAT BATCH WEATHER DATA PROCESSOR
========================================

Supported datasets:
    - AgMERRA historical/reference weather data
    - 59 CMIP6 climate models
    - Multiple SSP scenarios
    - Near, mid and end-century projections
    - Delta and M&V bias-correction products

Processing:
    1. Discover all AgMIP files in the input directory.
    2. Read metadata and simulation date ranges.
    3. Identify GCM, SSP, dataset source and scenario.
    4. Read DSSAT daily weather observations.
    5. Decode DSSAT YYYYDDD dates.
    6. Detect and remove extra initial years when verified.
    7. Reconstruct dates from metadata for projections.
    8. Derive historical dates from the source records.
    9. Aggregate daily observations into monthly and annual data.
   10. Perform data quality checks.
   11. Export daily, monthly and annual CSV files.
   12. Generate individual and master processing reports.

Dependencies:
    pip install pandas numpy

Author: AgMIP Weather Processing
"""

import os
import re
import glob
import traceback
import warnings

import numpy as np
import pandas as pd


# ============================================================
# 1. USER SETTINGS
# ============================================================

INPUT_DIR = (
    "/home/goitomk/AI/cloud/PyCSG/output"
)

OUTPUT_DIR = (
    "/home/goitomk/AI/cloud/PyCSG/agreegate/AgMIP_Processed"
)

# Search recursively for AgMIP files.
RECURSIVE_SEARCH = True

# Recognized extensions (case insensitive).
FILE_EXTENSIONS = {
    ".agmip",
    ".txt"
}

# Remove extra initial source years only when verified.
DROP_EXTRA_FIRST_YEAR = True

# Supported SSP scenarios.
SCENARIOS = [
    "ssp119",
    "ssp126",
    "ssp245",
    "ssp370",
    "ssp434",
    "ssp460",
    "ssp534",
    "ssp585"
]

# Weather variables.
WEATHER_VARIABLES = [
    "SRAD",
    "TMAX",
    "TMIN",
    "RAIN",
    "WIND",
    "DEWP",
    "VPRS",
    "RHUM"
]

# Accumulated variables.
SUM_VARIABLES = [
    "SRAD",
    "RAIN"
]

# Mean variables.
MEAN_VARIABLES = [
    "TMAX",
    "TMIN",
    "WIND",
    "DEWP",
    "VPRS",
    "RHUM"
]

# Output precision.
CSV_FLOAT_FORMAT = "%.4f"

# ============================================================
# 2. SUPPORTED CMIP6 CLIMATE MODELS
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
    "ukesm1_0_ll"
]

# Historical/reference dataset keywords.
HISTORICAL_KEYWORDS = [
    "agmerra",
    "historical",
    "historic",
    "baseline",
    "reference",
    "observed"
]


# ============================================================
# 3. CREATE OUTPUT DIRECTORIES
# ============================================================

OUTPUT_FOLDERS = [
    "Daily",
    "Monthly",
    "Annual",
    "Processing_Summary"
]

for folder in OUTPUT_FOLDERS:

    os.makedirs(
        os.path.join(OUTPUT_DIR, folder),
        exist_ok=True
    )


# ============================================================
# 4. UTILITY FUNCTIONS
# ============================================================

def normalize_name(value):
    """
    Normalize names for GCM and scenario matching.
    Handles underscores, hyphens and spaces.
    """

    return re.sub(
        r"[^a-z0-9]",
        "",
        str(value).lower()
    )


def safe_filename(value):
    """Remove characters unsuitable for output filenames."""

    return re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        str(value)
    ).strip("_")


def get_input_files():

    files = []

    if RECURSIVE_SEARCH:

        for root, _, filenames in os.walk(INPUT_DIR):

            for filename in filenames:

                extension = os.path.splitext(filename)[1].lower()

                if extension in FILE_EXTENSIONS:

                    files.append(
                        os.path.join(root, filename)
                    )

    else:

        for filename in os.listdir(INPUT_DIR):

            filepath = os.path.join(
                INPUT_DIR,
                filename
            )

            extension = os.path.splitext(filename)[1].lower()

            if (
                os.path.isfile(filepath)
                and extension in FILE_EXTENSIONS
            ):

                files.append(filepath)

    return sorted(set(files))


# ============================================================
# 5. IDENTIFY CLIMATE MODEL OR DATA SOURCE
# ============================================================

def identify_gcm(filename, metadata):

    search_text = normalize_name(
        filename + " " + metadata
    )

    # AgMERRA historical dataset.
    if "agmerra" in search_text:

        return "agmerra"

    # Longest model names first.
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
# 6. IDENTIFY CLIMATE SCENARIO
# ============================================================

def identify_scenario(filename, metadata, gcm):

    search_text = (
        filename + " " + metadata
    ).lower()

    # AgMERRA is historical/reference data.
    if gcm == "agmerra":

        return "historical"

    # Check historical keywords.
    for keyword in HISTORICAL_KEYWORDS:

        if keyword in search_text:

            return "historical"

    # Check SSP scenarios.
    normalized = normalize_name(search_text)

    for scenario in SCENARIOS:

        if normalize_name(scenario) in normalized:

            return scenario

    return "unknown_scenario"


# ============================================================
# 7. READ METADATA HEADER
# ============================================================

def read_metadata(filepath):

    with open(
        filepath,
        "r",
        encoding="utf-8",
        errors="replace"
    ) as f:

        lines = f.readlines()

    if not lines:

        raise ValueError("Input file is empty.")

    metadata = lines[0].strip()

    # Metadata date range, e.g.
    # 2071-01-01 to 2100-12-31

    match = re.search(
        r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})",
        metadata
    )

    if match:

        start_date = pd.Timestamp(match.group(1))
        end_date = pd.Timestamp(match.group(2))

        if end_date < start_date:

            raise ValueError(
                "Metadata end date precedes start date."
            )

    else:

        # Historical AgMERRA files may not contain
        # an explicit metadata date range.
        start_date = None
        end_date = None

    return (
        lines,
        metadata,
        start_date,
        end_date
    )


# ============================================================
# 8. FIND DSSAT WEATHER HEADER
# ============================================================

def find_weather_header(lines):

    for i, line in enumerate(lines):

        if line.strip().upper().startswith("@DATE"):

            return i

    raise ValueError(
        "DSSAT weather header (@DATE) not found."
    )


# ============================================================
# 9. READ DAILY WEATHER OBSERVATIONS
# ============================================================

def read_weather_data(filepath, lines):

    header_index = find_weather_header(lines)

    columns = lines[header_index].strip().split()

    columns[0] = columns[0].replace("@", "")

    df = pd.read_csv(
        filepath,
        sep=r"\s+",
        skiprows=header_index + 1,
        names=columns,
        header=None,
        engine="python",
        comment="!",
        on_bad_lines="skip"
    )

    if df.empty:

        raise ValueError(
            "No daily weather observations found."
        )

    if "DATE" not in df.columns:

        raise ValueError(
            "DATE column is missing."
        )

    # Remove footer/header rows that do not contain
    # valid numerical DSSAT dates.
    df["DATE"] = pd.to_numeric(
        df["DATE"],
        errors="coerce"
    )

    df = df.dropna(
        subset=["DATE"]
    ).copy()

    df["DATE"] = df["DATE"].astype(int)

    if df.empty:

        raise ValueError(
            "No valid daily date records found."
        )

    return df.reset_index(drop=True)


# ============================================================
# 10. DECODE DSSAT YYYYDDD DATE FORMAT
# ============================================================

def decode_dssat_dates(date_values):
    """
    Decode DSSAT dates.

    Example:
        1980001 = 1 January 1980
        1980366 = 31 December 1980 (leap year)
        2071001 = 1 January 2071
    """

    values = pd.to_numeric(
        date_values,
        errors="coerce"
    )

    if values.isna().any():

        raise ValueError(
            "Invalid DSSAT date codes detected."
        )

    values = values.astype(int)

    if not values.between(
        1000001,
        9999366
    ).all():

        raise ValueError(
            "Unexpected DSSAT YYYYDDD date format."
        )

    date_strings = values.astype(str).str.zfill(7)

    dates = pd.to_datetime(
        date_strings,
        format="%Y%j",
        errors="coerce"
    )

    if dates.isna().any():

        raise ValueError(
            "Invalid year/day-of-year combinations found."
        )

    return dates


# ============================================================
# 11. CHECK SOURCE DATE SEQUENCE
# ============================================================

def validate_date_sequence(dates, description="Source"):

    dates = pd.DatetimeIndex(dates)

    if dates.duplicated().any():

        raise ValueError(
            f"{description} contains duplicate dates."
        )

    if not dates.is_monotonic_increasing:

        raise ValueError(
            f"{description} dates are not chronological."
        )

    if len(dates) > 1:

        differences = dates.to_series().diff().dropna()

        if not (differences == pd.Timedelta(days=1)).all():

            raise ValueError(
                f"{description} has missing dates or date gaps."
            )

    return True


# ============================================================
# 12. CORRECT DAILY DATES
# ============================================================

def correct_dates(
    df,
    start_date=None,
    end_date=None
):
    """
    For historical data:
        Use actual DSSAT source dates.

    For climate projections:
        Use metadata simulation period.

    If an extra initial source year exists:
        Remove it only when the remaining dates exactly
        match the metadata period.
    """

    df = df.copy()

    # Decode original DSSAT date codes.
    df["_SOURCE_DATE"] = decode_dssat_dates(
        df["DATE"]
    )

    # Sort by source date.
    df = df.sort_values(
        "_SOURCE_DATE"
    ).reset_index(drop=True)

    source_dates = pd.DatetimeIndex(
        df["_SOURCE_DATE"]
    )

    validate_date_sequence(
        source_dates,
        "Original source data"
    )

    # --------------------------------------------------------
    # HISTORICAL DATA: No metadata date range
    # --------------------------------------------------------

    if start_date is None or end_date is None:

        start_date = source_dates.min()
        end_date = source_dates.max()

        target_dates = pd.date_range(
            start=start_date,
            end=end_date,
            freq="D"
        )

        if len(df) != len(target_dates):

            raise ValueError(
                "Historical source dates do not cover "
                "a complete daily sequence."
            )

        df["DATE"] = target_dates

    # --------------------------------------------------------
    # FUTURE CLIMATE PROJECTIONS: Metadata date range
    # --------------------------------------------------------

    else:

        target_dates = pd.date_range(
            start=start_date,
            end=end_date,
            freq="D"
        )

        expected_days = len(target_dates)

        original_count = len(df)

        if original_count == expected_days:

            # Correct source years according to metadata.
            print(
                "Daily record count matches metadata."
            )

        else:

            if not DROP_EXTRA_FIRST_YEAR:

                raise ValueError(
                    f"Expected {expected_days} records, "
                    f"found {original_count}."
                )

            # Identify records within the requested
            # metadata period.
            candidate = df.loc[
                (df["_SOURCE_DATE"] >= start_date)
                &
                (df["_SOURCE_DATE"] <= end_date)
            ].copy()

            candidate_dates = pd.DatetimeIndex(
                candidate["_SOURCE_DATE"]
            )

            if len(candidate) != expected_days:

                raise ValueError(
                    f"Expected {expected_days} records. "
                    f"Found {original_count}; after removing "
                    f"out-of-period dates, found {len(candidate)}. "
                    "Cannot verify an extra initial year."
                )

            validate_date_sequence(
                candidate_dates,
                "Retained source data"
            )

            if (
                candidate_dates.min() != start_date
                or candidate_dates.max() != end_date
            ):

                raise ValueError(
                    "Retained source dates do not match "
                    "the metadata date boundaries."
                )

            removed_records = original_count - len(candidate)

            print(
                "Removed out-of-period initial records:",
                removed_records
            )

            df = candidate.reset_index(drop=True)

        if len(df) != expected_days:

            raise ValueError(
                "Daily record count does not match metadata."
            )

        # Reconstruct dates according to metadata.
        df["DATE"] = target_dates

    # --------------------------------------------------------
    # STANDARDIZE DATE COMPONENTS
    # --------------------------------------------------------

    df = df.drop(
        columns=["_SOURCE_DATE"],
        errors="ignore"
    )

    # Remove old date components.
    for col in [
        "YYYY",
        "YEAR",
        "MM",
        "MONTH",
        "DD",
        "DAY"
    ]:

        if col in df.columns:

            df.drop(
                columns=col,
                inplace=True
            )

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

    return df.reset_index(drop=True)


# ============================================================
# 13. MONTHLY AND ANNUAL AGGREGATION
# ============================================================

def aggregate_weather(df):

    aggregation = {}

    # Sum variables.
    for col in SUM_VARIABLES:

        if col in df.columns:

            aggregation[col] = (
                lambda x: x.sum(min_count=1)
            )

    # Mean variables.
    for col in MEAN_VARIABLES:

        if col in df.columns:

            aggregation[col] = "mean"

    if not aggregation:

        raise ValueError(
            "No recognized weather variables available."
        )

    # --------------------------------------------------------
    # MONTHLY
    # --------------------------------------------------------

    monthly = (
        df.set_index("DATE")
        .resample("MS")
        .agg(aggregation)
        .reset_index()
    )

    monthly["YEAR"] = monthly["DATE"].dt.year
    monthly["MONTH"] = monthly["DATE"].dt.month

    monthly = monthly[
        ["DATE", "YEAR", "MONTH"]
        + list(aggregation.keys())
    ]

    # --------------------------------------------------------
    # ANNUAL
    # --------------------------------------------------------

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
# 14. QUALITY CONTROL
# ============================================================

def quality_control(df):

    report = []

    report.append("DAILY WEATHER DATA QUALITY CONTROL")
    report.append("=" * 55)

    report.append(
        f"Daily records: {len(df)}"
    )

    report.append(
        f"Start date: {df['DATE'].min().date()}"
    )

    report.append(
        f"End date: {df['DATE'].max().date()}"
    )

    report.append(
        f"Duplicate dates: {df['DATE'].duplicated().sum()}"
    )

    expected_dates = pd.date_range(
        df["DATE"].min(),
        df["DATE"].max(),
        freq="D"
    )

    missing_dates = expected_dates.difference(
        pd.DatetimeIndex(df["DATE"])
    )

    report.append(
        f"Missing calendar dates: {len(missing_dates)}"
    )

    report.append("\nMISSING WEATHER VALUES")
    report.append("-" * 55)

    for col in WEATHER_VARIABLES:

        if col in df.columns:

            report.append(
                f"{col}: {df[col].isna().sum()}"
            )

        else:

            report.append(
                f"{col}: COLUMN NOT AVAILABLE"
            )

    report.append("\nWEATHER DATA CHECKS")
    report.append("-" * 55)

    if "RAIN" in df.columns:

        report.append(
            "Negative rainfall records: "
            + str((df["RAIN"] < 0).sum())
        )

    if "SRAD" in df.columns:

        report.append(
            "Negative solar radiation records: "
            + str((df["SRAD"] < 0).sum())
        )

    if "WIND" in df.columns:

        report.append(
            "Negative wind speed records: "
            + str((df["WIND"] < 0).sum())
        )

    if "TMAX" in df.columns and "TMIN" in df.columns:

        report.append(
            "TMIN greater than TMAX: "
            + str((df["TMIN"] > df["TMAX"]).sum())
        )

    # Variable descriptive statistics.
    report.append("\nWEATHER VARIABLE STATISTICS")
    report.append("-" * 55)

    available = [
        col for col in WEATHER_VARIABLES
        if col in df.columns
    ]

    if available:

        report.append(
            df[available].describe().round(3).to_string()
        )

    return report


# ============================================================
# 15. SAVE PROCESSING REPORT
# ============================================================

def save_processing_report(
    report_file,
    filename,
    metadata,
    gcm,
    scenario,
    start_date,
    end_date,
    qc_report,
    output_files
):

    with open(
        report_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "AGMIP DSSAT WEATHER PROCESSING REPORT\n"
        )

        f.write("=" * 65 + "\n\n")

        f.write(f"Input file: {filename}\n")
        f.write(f"Metadata: {metadata}\n")
        f.write(f"Dataset source/GCM: {gcm}\n")
        f.write(f"Scenario: {scenario}\n")

        f.write(
            f"Simulation start: {start_date.date()}\n"
        )

        f.write(
            f"Simulation end: {end_date.date()}\n"
        )

        f.write("\n")

        f.write("\n".join(qc_report))

        f.write("\n\nOUTPUT FILES\n")
        f.write("=" * 65 + "\n")

        for name, path in output_files.items():

            f.write(f"{name}: {path}\n")


# ============================================================
# 16. PROCESS ONE AGMI P FILE
# ============================================================

def process_file(filepath):

    filename = os.path.basename(filepath)

    print("\n" + "=" * 75)
    print("PROCESSING:", filename)
    print("=" * 75)

    # --------------------------------------------------------
    # Read metadata.
    # --------------------------------------------------------

    (
        lines,
        metadata,
        start_date,
        end_date
    ) = read_metadata(filepath)

    # --------------------------------------------------------
    # Identify GCM and scenario.
    # --------------------------------------------------------

    gcm = identify_gcm(
        filename,
        metadata
    )

    scenario = identify_scenario(
        filename,
        metadata,
        gcm
    )

    print("Dataset/GCM:", gcm)
    print("Scenario:", scenario)
    print("Metadata:", metadata)

    if gcm == "unknown_gcm":

        raise ValueError(
            "Climate model or dataset source not recognized."
        )

    if scenario == "unknown_scenario":

        raise ValueError(
            "Climate scenario not recognized."
        )

    if start_date is not None:

        print(
            "Metadata period:",
            start_date.date(),
            "to",
            end_date.date()
        )

    # --------------------------------------------------------
    # Read daily weather observations.
    # --------------------------------------------------------

    df = read_weather_data(
        filepath,
        lines
    )

    print(
        "Original daily records:",
        len(df)
    )

    # --------------------------------------------------------
    # Correct dates.
    # --------------------------------------------------------

    df = correct_dates(
        df,
        start_date,
        end_date
    )

    start_date = df["DATE"].min()
    end_date = df["DATE"].max()

    print(
        "Corrected period:",
        start_date.date(),
        "to",
        end_date.date()
    )

    # --------------------------------------------------------
    # Check station metadata, if available.
    # --------------------------------------------------------

    station_info = {}

    station_header = None

    for i, line in enumerate(lines):

        if line.strip().upper().startswith("@ INSI"):

            station_header = i
            break

    if station_header is not None:

        try:

            station_columns = (
                lines[station_header]
                .strip()
                .replace("@", "")
                .split()
            )

            station_values = (
                lines[station_header + 1]
                .strip()
                .split()
            )

            if len(station_columns) == len(station_values):

                station_info = dict(
                    zip(
                        station_columns,
                        station_values
                    )
                )

        except (IndexError, ValueError):

            pass

    # --------------------------------------------------------
    # Aggregate daily data.
    # --------------------------------------------------------

    monthly, annual = aggregate_weather(df)

    # --------------------------------------------------------
    # Generate unique output filenames.
    # --------------------------------------------------------

    stem = os.path.splitext(filename)[0]

    base_name = safe_filename(
        f"{stem}_{gcm}_{scenario}_"
        f"{start_date.year}_{end_date.year}"
    )

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

    # --------------------------------------------------------
    # Export CSV files.
    # --------------------------------------------------------

    df.to_csv(
        daily_file,
        index=False,
        float_format=CSV_FLOAT_FORMAT
    )

    monthly.to_csv(
        monthly_file,
        index=False,
        float_format=CSV_FLOAT_FORMAT
    )

    annual.to_csv(
        annual_file,
        index=False,
        float_format=CSV_FLOAT_FORMAT
    )

    # --------------------------------------------------------
    # Quality control.
    # --------------------------------------------------------

    qc_report = quality_control(df)

    report_file = os.path.join(
        OUTPUT_DIR,
        "Processing_Summary",
        base_name + "_QC_Report.txt"
    )

    output_files = {
        "Daily": daily_file,
        "Monthly": monthly_file,
        "Annual": annual_file
    }

    save_processing_report(
        report_file,
        filename,
        metadata,
        gcm,
        scenario,
        start_date,
        end_date,
        qc_report,
        output_files
    )

    # --------------------------------------------------------
    # Processing summary.
    # --------------------------------------------------------

    result = {

        "Filename": filename,

        "Dataset": gcm,

        "GCM": (
            gcm if gcm != "agmerra" else "AgMERRA"
        ),

        "Scenario": scenario,

        "Start": str(start_date.date()),

        "End": str(end_date.date()),

        "Latitude": station_info.get("LAT", ""),

        "Longitude": station_info.get("LONG", ""),

        "Elevation": station_info.get("ELEV", ""),

        "Daily_records": len(df),

        "Monthly_records": len(monthly),

        "Annual_records": len(annual),

        "Missing_weather_values": int(
            df[
                [
                    c for c in WEATHER_VARIABLES
                    if c in df.columns
                ]
            ].isna().sum().sum()
        ),

        "Status": "SUCCESS",

        "Error": "",

        "Daily_file": daily_file,

        "Monthly_file": monthly_file,

        "Annual_file": annual_file,

        "QC_report": report_file
    }

    print("\nSUCCESS")
    print("Daily:", len(df))
    print("Monthly:", len(monthly))
    print("Annual:", len(annual))

    print("\nOutput files:")
    print(daily_file)
    print(monthly_file)
    print(annual_file)

    return result


# ============================================================
# 17. BATCH PROCESSING
# ============================================================

def main():

    print("\n" + "=" * 75)
    print("AGMIP DSSAT BATCH WEATHER PROCESSOR")
    print("=" * 75)

    print("Supported CMIP6 GCMs:", len(GCM_MODELS))
    print("Supported SSP scenarios:", len(SCENARIOS))
    print("Historical source: AgMERRA")
    print("Input directory:", INPUT_DIR)
    print("Output directory:", OUTPUT_DIR)

    # --------------------------------------------------------
    # Find files.
    # --------------------------------------------------------

    input_files = get_input_files()

    if not input_files:

        raise FileNotFoundError(
            f"No AgMIP files found in {INPUT_DIR}"
        )

    print(
        "\nTotal input files:",
        len(input_files)
    )

    results = []

    # --------------------------------------------------------
    # Process every input file.
    # --------------------------------------------------------

    for i, filepath in enumerate(input_files, start=1):

        print(
            f"\n\nFILE {i} OF {len(input_files)}"
        )

        try:

            result = process_file(filepath)

        except Exception as error:

            print("\nPROCESSING FAILED:")
            print(str(error))

            traceback.print_exc()

            result = {

                "Filename": os.path.basename(filepath),

                "Dataset": "",

                "GCM": "",

                "Scenario": "",

                "Start": "",

                "End": "",

                "Latitude": "",

                "Longitude": "",

                "Elevation": "",

                "Daily_records": 0,

                "Monthly_records": 0,

                "Annual_records": 0,

                "Missing_weather_values": 0,

                "Status": "FAILED",

                "Error": str(error),

                "Daily_file": "",

                "Monthly_file": "",

                "Annual_file": "",

                "QC_report": ""
            }

        results.append(result)

    # --------------------------------------------------------
    # Save master processing summary.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Calculate final statistics.
    # --------------------------------------------------------

    successful = (
        summary["Status"] == "SUCCESS"
    ).sum()

    failed = (
        summary["Status"] == "FAILED"
    ).sum()

    print("\n" + "=" * 75)
    print("AGMIP PROCESSING COMPLETED")
    print("=" * 75)

    print("Total files:", len(input_files))
    print("Successful:", successful)
    print("Failed:", failed)

    print(
        "\nHistorical datasets:",
        (summary["Scenario"] == "historical").sum()
    )

    print(
        "\nFuture SSP datasets:",
        summary["Scenario"].isin(SCENARIOS).sum()
    )

    print("\nProcessing summary:")
    print(
        summary[
            [
                "Filename",
                "GCM",
                "Scenario",
                "Start",
                "End",
                "Status"
            ]
        ].to_string(index=False)
    )

    print("\nMaster summary:")
    print(summary_file)

    print("\nOutput directory:")
    print(OUTPUT_DIR)

    print("\nAll processing tasks finished.")


# ============================================================
# 18. EXECUTE
# ============================================================

if __name__ == "__main__":

    warnings.filterwarnings(
        "ignore",
        category=FutureWarning
    )

    main()
