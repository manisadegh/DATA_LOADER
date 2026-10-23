#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper utility for TPT loader: extracts and sanitizes column headers
from delimited files using standard Python csv parsing.
"""

import csv
import re
import sys


def extract_header_columns(file_path: str, delimiter: str = ","):
    """Reads the first line of a delimited file and sanitizes column headers."""
    with open(file_path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        header = next(csv.reader(fh, delimiter=delimiter))
    cols = []
    for col in header:
        c = re.sub(r"[^A-Za-z0-9_]", "_", col.strip().strip('"').strip("'"))
        c = re.sub(r"_+", "_", c).strip("_").upper()
        if c:
            cols.append(c)
    return cols


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    path = sys.argv[1]
    delim = sys.argv[2]
    for col in extract_header_columns(path, delim):
        print(col)
