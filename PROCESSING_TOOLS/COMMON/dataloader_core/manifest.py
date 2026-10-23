"""
dataloader_core/manifest.py - Unified Manifest Filename & Content Handler

Consolidates all 4 manifest filename regex conventions, payload batch ID extraction,
delimiter-agnostic manifest entry parsing, and standardized manifest generation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .checksum import compute_file_checksum

_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

MANIFEST_PATTERNS = [
    # 1. Standard: MANIFEST_<SOURCE>_<TIMESTAMP>_<BATCH_ID>.MF
    re.compile(r"^MANIFEST[-_]([A-Za-z0-9_]+)[-_](\d{8}_\d{6})[-_]([A-Za-z0-9_-]+)\.MF$", re.IGNORECASE),
    # 2. Oracle BICC with Timestamp: *MANIFEST-YYYYMMDD_HHMMSS.MF (e.g. DT2_MANIFEST-20261013_131116.MF)
    re.compile(r"^.*MANIFEST[-_](\d{8}_\d{6})\.MF$", re.IGNORECASE),
]


@dataclass
class ManifestMetadata:
    """Parsed metadata from a manifest filename with dict-compatible access."""

    source: str
    extract_timestamp_raw: str
    extract_timestamp_iso: str
    batch_id: str
    sort_key: Tuple[float, Any]
    batch_id_from_manifest: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "extract_timestamp": self.extract_timestamp_raw,
            "extract_timestamp_raw": self.extract_timestamp_raw,
            "extract_timestamp_iso": self.extract_timestamp_iso,
            "raw_timestamp": self.extract_timestamp_raw,
            "batch_id": self.batch_id,
            "sort_key": self.sort_key,
            "batch_id_from_manifest": self.batch_id_from_manifest,
        }

    def __getitem__(self, key: str) -> Any:
        mapping = self.to_dict()
        if key in mapping:
            return mapping[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass
class ManifestEntry:
    """Represents a single file entry inside a manifest with dict-compatible access."""

    filename: str
    checksum: Optional[str] = None
    ucm_doc_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "filename": self.filename,
            "checksum": self.checksum,
            "ucm_doc_id": self.ucm_doc_id,
        }

    def __getitem__(self, key: str) -> Any:
        mapping = self.to_dict()
        if key in mapping:
            return mapping[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def extract_batch_id_from_filenames(declared_files: List[str]) -> Optional[str]:
    """
    Extracts batch_id from declared filenames following the pattern:
      *<signature>-batch<batch_id>-*
    """
    for fname in declared_files:
        m = re.search(r"-batch([A-Za-z0-9_-]+?)-", fname, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _raw_ts_to_iso_and_epoch(extract_ts_raw: str) -> Tuple[str, float]:
    try:
        dt = datetime.strptime(extract_ts_raw, "%Y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.timestamp()
    except ValueError as exc:
        raise ValueError(f"Unparseable extract timestamp token '{extract_ts_raw}': {exc}") from exc


def parse_manifest_filename(
    filename_or_path: str,
    default_source: str = "ORACLE_FUSION",
    custom_regex: Optional[str] = None,
    strict: bool = True,
) -> ManifestMetadata:
    """
    Parses a manifest filename into `ManifestMetadata`.
    Supports custom regexes and canonical standard / BICC timestamp patterns.
    Strictly raises ValueError on unparseable names without timestamp fabrication (F2.6).
    """
    filename = os.path.basename(filename_or_path)

    if custom_regex:
        m_custom = re.match(custom_regex, filename)
        if m_custom:
            source = m_custom.group(1)
            extract_ts_raw = m_custom.group(2)
            batch_id = m_custom.group(3)
            iso_ts, ts_epoch = _raw_ts_to_iso_and_epoch(extract_ts_raw)
            return ManifestMetadata(
                source=source,
                extract_timestamp_raw=extract_ts_raw,
                extract_timestamp_iso=iso_ts,
                batch_id=batch_id,
                sort_key=(ts_epoch, batch_id),
                batch_id_from_manifest=True,
            )

    # 1. Standard: MANIFEST_<SOURCE>_<TIMESTAMP>_<BATCH_ID>.MF
    m1 = MANIFEST_PATTERNS[0].match(filename)
    if m1:
        source = m1.group(1).upper()
        extract_ts_raw = m1.group(2)
        batch_id = m1.group(3)
        iso_ts, ts_epoch = _raw_ts_to_iso_and_epoch(extract_ts_raw)
        return ManifestMetadata(
            source=source,
            extract_timestamp_raw=extract_ts_raw,
            extract_timestamp_iso=iso_ts,
            batch_id=batch_id,
            sort_key=(ts_epoch, batch_id),
            batch_id_from_manifest=True,
        )

    # 2. Oracle BICC with Timestamp: *MANIFEST-YYYYMMDD_HHMMSS.MF
    m2 = MANIFEST_PATTERNS[1].match(filename)
    if m2:
        extract_ts_raw = m2.group(1)
        iso_ts, ts_epoch = _raw_ts_to_iso_and_epoch(extract_ts_raw)
        return ManifestMetadata(
            source=default_source,
            extract_timestamp_raw=extract_ts_raw,
            extract_timestamp_iso=iso_ts,
            batch_id=extract_ts_raw,
            sort_key=(ts_epoch, extract_ts_raw),
            batch_id_from_manifest=False,
        )

    raise ValueError(
        f"Manifest filename '{filename}' does not adhere to standard naming: "
        "MANIFEST_<SOURCE>_<EXTRACT_TIMESTAMP>_<BATCH_ID>.MF or recognizable timestamp pattern."
    )


def read_manifest_entries(
    manifest_path: str,
    require_non_empty: bool = False,
) -> List[ManifestEntry]:
    """
    Parses manifest file content supporting `;`, `\\t`, and `,` delimiters,
    optional header line (`filename,checksum`), and ignoring comments (`#`)
    and `KEY=VALUE` metadata lines (e.g. `PLV_KEY=`).

    F2.5 Semicolon parsing rules:
      - 2 fields: (filename, X) -> X is checksum if 32 or 64 hex chars, else ucm_doc_id
      - 3 fields: (filename, ucm_doc_id, checksum)
    """
    entries: List[ManifestEntry] = []
    raw_lines: List[str] = []

    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith("#") or re.match(r"^[A-Za-z0-9_]+=", line_str):
                continue
            raw_lines.append(line_str)

    if not raw_lines:
        if require_non_empty:
            raise ValueError(f"Manifest '{manifest_path}' is empty or has no entries.")
        return []

    for line_str in raw_lines:
        checksum: Optional[str] = None
        ucm_doc_id: Optional[str] = None

        if ";" in line_str:
            parts = line_str.split(";")
            fname = parts[0].strip().strip('"').strip("'")
            if fname.lower() in ("filename", "file_name", "file"):
                continue
            if len(parts) == 2:
                val = parts[1].strip().strip('"').strip("'")
                if _HEX32.match(val) or _HEX64.match(val):
                    checksum = val
                    ucm_doc_id = None
                else:
                    checksum = None
                    ucm_doc_id = val if val else None
            elif len(parts) >= 3:
                ucm_val = parts[1].strip().strip('"').strip("'")
                cs_val = parts[2].strip().strip('"').strip("'")
                ucm_doc_id = ucm_val if ucm_val else None
                checksum = cs_val if cs_val else None
        elif "\t" in line_str or "," in line_str:
            sep = "\t" if "\t" in line_str else ","
            parts = line_str.split(sep)
            fname = parts[0].strip().strip('"').strip("'")
            if fname.lower() in ("filename", "file_name", "file"):
                continue
            checksum = (
                parts[1].strip().strip('"').strip("'")
                if len(parts) > 1 and parts[1].strip()
                else None
            )
        else:
            fname = line_str.strip().strip('"').strip("'")
            if fname.lower() in ("filename", "file_name", "file"):
                continue

        if fname:
            entries.append(ManifestEntry(filename=fname, checksum=checksum, ucm_doc_id=ucm_doc_id))

    if require_non_empty and not entries:
        raise ValueError(f"Manifest '{manifest_path}' contains 0 file entries after parsing.")

    return entries


def write_standardized_manifest(
    output_dir: str,
    source: str,
    extract_timestamp: str,
    batch_id: str,
    file_checksum_pairs: List[Tuple[str, str]],
) -> str:
    """
    Generates an orchestrator-compliant standardized manifest:
      MANIFEST_<SOURCE>_<EXTRACT_TIMESTAMP>_<BATCH_ID>.MF
    Returns the absolute path of the created manifest.
    """
    os.makedirs(output_dir, exist_ok=True)
    manifest_name = f"MANIFEST_{source}_{extract_timestamp}_{batch_id}.MF"
    manifest_path = os.path.join(output_dir, manifest_name)

    lines = ["filename,checksum\n"]
    for fname, cs in file_checksum_pairs:
        lines.append(f"{fname},{cs}\n")

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return manifest_path


class ManifestHandler:
    """Unified facade for manifest filename parsing, entry reading, and creation."""

    parse_filename = staticmethod(parse_manifest_filename)
    extract_batch_id_from_filenames = staticmethod(extract_batch_id_from_filenames)
    read_entries = staticmethod(read_manifest_entries)
    write_standardized_manifest = staticmethod(write_standardized_manifest)
    compute_file_checksum = staticmethod(compute_file_checksum)
