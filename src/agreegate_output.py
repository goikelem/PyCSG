
"""
AgMIP DSSAT weather data processor
-----------------------------------
1. Reads the date range from the metadata header.
2. Reads daily weather observations.
3. Corrects DATE and YEAR using the metadata date range.
4. Handles the extra source year when necessary.
5. Aggregates daily data into monthly and annual values.
6. Exports three CSV files.
"""

import os
import re
import pandas as pd
import numpy as np

# ============================================================
# 1. USER SETTINGS
# ============================================================

INPUT_FILE = (
    r"/home/goitomk/AI/cloud/PyCSG/output/ETAD_ssp126_access-cm2_end_mandv.AgMIP"
)

OUTPUT_DIR = r"/home/goitomk/AI/cloud/PyCSG/agreegate/AgMIP_Processed"

# If the source contains one extra initial year, remove it.
# For the uploaded file, this removes 1980 and retains 1981-2010.
DROP_EXTRA_FIRST_YEAR = True

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# 2. READ METADATA HEADER
# ============================================================

with open(INPUT_FILE, "r") as f:
    lines = f.readlines()

metadata = lines[0].strip()

print("Metadata:")
print(metadata)

# Extract date range from metadata
match = re.search(
    r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})",
    metadata
)

if not match:
    raise ValueError("Date range not found in metadata header.")

START_DATE = pd.Timestamp(match.group(1))
END_DATE = pd.Timestamp(match.group(2))

print("\nTarget period:")
print(START_DATE, "to", END_DATE)


# ============================================================
# 3. FIND WEATHER DATA HEADER
# ============================================================

header_index = next(
    i for i, line in enumerate(lines)
    if line.strip().startswith("@DATE")
)

columns = lines[header_index].strip().split()

# Remove @ from the first column
columns[0] = columns[0].replace("@", "")

# Read daily observations
df = pd.read_csv(
    INPUT_FILE,
    sep=r"\s+",
    skiprows=header_index + 1,
    names=columns,
    engine="python"
)

print("\nOriginal data shape:", df.shape)
print(df.head())


# ============================================================
# 4. IDENTIFY SOURCE YEARS
# ============================================================

df["YYYY"] = pd.to_numeric(df["YYYY"], errors="coerce")

df = df.dropna(subset=["YYYY"]).copy()
df["YYYY"] = df["YYYY"].astype(int)

source_years = sorted(df["YYYY"].unique())

print("\nSource years:")
print(source_years[0], "to", source_years[-1])

# Expected number of daily observations
target_dates = pd.date_range(
    start=START_DATE,
    end=END_DATE,
    freq="D"
)

expected_days = len(target_dates)

print("\nExpected daily records:", expected_days)
print("Available daily records:", len(df))


# ============================================================
# 5. CORRECT SOURCE PERIOD IF NECESSARY
# ============================================================

if len(df) != expected_days:

    # Check whether there is exactly one additional initial year
    if (
        DROP_EXTRA_FIRST_YEAR
        and len(source_years) > 1
        and source_years[1] - source_years[0] == 1
    ):

        first_year = source_years[0]

        candidate = df[df["YYYY"] != first_year].copy()

        if len(candidate) == expected_days:
            print(
                f"\nRemoving extra source year: {first_year}"
            )
            df = candidate.reset_index(drop=True)

        else:
            raise ValueError(
                "Removing the first source year does not "
                "produce the expected number of records. "
                "Check the source data and target period."
            )

    else:
        raise ValueError(
            f"Date mismatch: expected {expected_days} "
            f"records but found {len(df)}. "
            "Check the metadata and source data."
        )


# ============================================================
# 6. RECONSTRUCT DATE AND YEAR
# ============================================================

# Assign dates sequentially according to metadata.
df = df.reset_index(drop=True)

df["DATE"] = target_dates

# Replace original year, month and day
df["YYYY"] = df["DATE"].dt.year
df["MM"] = df["DATE"].dt.month
df["DD"] = df["DATE"].dt.day

# Standardize column names
df = df.rename(columns={
    "YYYY": "YEAR",
    "MM": "MONTH",
    "DD": "DAY"
})

# Convert weather variables to numeric
weather_columns = [
    "SRAD", "TMAX", "TMIN", "RAIN",
    "WIND", "DEWP", "VPRS", "RHUM"
]

for col in weather_columns:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

print("\nCorrected daily data:")
print(df[["DATE", "YEAR", "MONTH", "DAY"]].head())

print("\nCorrected period:")
print(df["DATE"].min(), "to", df["DATE"].max())


# ============================================================
# 7. SAVE DAILY DATA
# ============================================================

daily_file = os.path.join(
    OUTPUT_DIR,
    "ETAD_ssp126_access-cm2_end_mandv_Weather_Daily.csv"
)

df.to_csv(daily_file, index=False)


# ============================================================
# 8. MONTHLY AGGREGATION
# ============================================================

# Variables accumulated over time
sum_variables = ["SRAD", "RAIN"]

# Variables averaged over time
mean_variables = [
    "TMAX", "TMIN", "WIND",
    "DEWP", "VPRS", "RHUM"
]

monthly_aggregation = {}

for col in sum_variables:
    if col in df.columns:
        monthly_aggregation[col] = "sum"

for col in mean_variables:
    if col in df.columns:
        monthly_aggregation[col] = "mean"

monthly = (
    df.set_index("DATE")
      .resample("MS")
      .agg(monthly_aggregation)
      .reset_index()
)

monthly["YEAR"] = monthly["DATE"].dt.year
monthly["MONTH"] = monthly["DATE"].dt.month

monthly = monthly[
    ["DATE", "YEAR", "MONTH"] +
    list(monthly_aggregation.keys())
]

monthly_file = os.path.join(
    OUTPUT_DIR,
    "ETAD_ssp126_access-cm2_end_mandv_Weather_Monthly.csv"
)

monthly.to_csv(monthly_file, index=False)


# ============================================================
# 9. ANNUAL AGGREGATION
# ============================================================

annual = (
    df.set_index("DATE")
      .resample("YS")
      .agg(monthly_aggregation)
      .reset_index()
)

annual["YEAR"] = annual["DATE"].dt.year

annual = annual[
    ["YEAR"] + list(monthly_aggregation.keys())
]

annual_file = os.path.join(
    OUTPUT_DIR,
    "ETAD_ssp126_access-cm2_end_mandv_Weather_Annual.csv"
)

annual.to_csv(annual_file, index=False)


# ============================================================
# 10. SUMMARY
# ============================================================

print("\n========================================")
print("WEATHER DATA PROCESSING COMPLETED")
print("========================================")

print("\nDaily records:", len(df))
print("Monthly records:", len(monthly))
print("Annual records:", len(annual))

print("\nTarget period:")
print(df["DATE"].min(), "to", df["DATE"].max())

print("\nOutput files:")
print(daily_file)
print(monthly_file)
print(annual_file)

print("\nMonthly preview:")
print(monthly.head())

print("\nAnnual preview:")
print(annual.head())
