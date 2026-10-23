"""
dataloader_core/schema_reader.py - In-Memory Delimited & Archive Header Inspector

Provides zero-database-dependency CSV/PECSV header extraction (including streaming
from .zip and .gz archives without writing uncompressed files to disk) and Teradata
column identifier sanitization (`clean_column_name`).
"""

from __future__ import annotations

import csv
import gzip
import io
import re
import zipfile
from typing import List, Optional


def validate_column_type(col_type: str) -> str:
    """Validates that the default column data type matches VARCHAR(N)."""
    cleaned = str(col_type).strip().upper() if col_type else ""
    if not re.match(r"^VARCHAR\(\d+\)$", cleaned):
        raise ValueError(f"Invalid column type specification: '{col_type}'")
    return cleaned


def clean_column_name(col_raw: str) -> str:
    """
    Sanitizes raw CSV column header strings into valid Teradata identifiers:
      - Trims whitespace and surrounding single/double quotes
      - Converts non-alphanumeric characters to underscores
      - Deduplicates consecutive underscores and strips leading/trailing underscores
      - Converts to UPPERCASE
    Matches `clean_column_name()` in `TPT_LOADER/lib/env_and_helpers.sh` 100%.
    """
    col = str(col_raw).strip().strip('"').strip("'")
    col = re.sub(r"[^A-Za-z0-9_]", "_", col)
    col = re.sub(r"_+", "_", col).strip("_")
    return col.upper()


def select_header_chunk_file(file_list: List[str]) -> str:
    """
    Among a list of chunk files for an entity, returns the file containing the header.
    In BICC multi-chunk conventions, the first alphabetical chunk contains line 1 header.
    """
    if not file_list:
        raise ValueError("Cannot select header chunk from an empty file list.")
    return sorted(file_list)[0]


def extract_csv_columns(file_path: str, delimiter: Optional[str] = None) -> List[str]:
    """
    Reads the header line (line 1) from a delimited text file or archive (.zip, .gz)
    and returns an ordered list of sanitized uppercase column names.
    Streams directly from memory for archives without writing uncompressed files to disk.
    Supports both .csv and .pecsv members inside archives.
    """
    first_line = ""
    lower_path = file_path.lower()

    if lower_path.endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zf:
            delimited_members = sorted(
                n for n in zf.namelist() if n.lower().endswith((".csv", ".pecsv")) and not n.endswith("/")
            )
            if not delimited_members:
                raise ValueError(f"No CSV or PECSV file found inside ZIP archive '{file_path}'.")
            with zf.open(delimited_members[0], "r") as member_stream:
                first_line = io.TextIOWrapper(member_stream, encoding="utf-8", errors="replace").readline().strip()
    elif lower_path.endswith(".gz"):
        with gzip.open(file_path, "rt", encoding="utf-8", errors="replace") as gf:
            first_line = gf.readline().strip()
    else:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline().strip()

    if first_line.startswith("\ufeff"):
        first_line = first_line.lstrip("\ufeff")

    if not first_line:
        raise ValueError(f"File '{file_path}' has an empty header line.")

    if delimiter is None:
        if ";" in first_line:
            delimiter = ";"
        elif "\t" in first_line:
            delimiter = "\t"
        else:
            delimiter = ","

    reader = csv.reader([first_line], delimiter=delimiter)
    raw_columns = next(reader)

    clean_cols = [clean_column_name(c) for c in raw_columns if clean_column_name(c)]
    if not clean_cols:
        raise ValueError(f"Could not extract any valid columns from header of '{file_path}'.")

    return clean_cols
