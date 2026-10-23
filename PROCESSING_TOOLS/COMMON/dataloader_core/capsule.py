"""
dataloader_core/capsule.py - Canonical Batch Capsule Path, Descriptor & Queue Publisher

Centralizes timestamp normalization (YYYYMMDD_HHMMSS <-> YYYY-MM-DD HH:MM:SS),
constructs deterministic Batch Capsule directory paths in LANDING_ZONE, LOADING_ZONE,
ARCHIVE_ZONE, and LOGS using strict path-segment inspection, and implements the
`BatchDescriptor` (`batch_descriptor.json`) and atomic `.staging_BATCH_*` -> `BATCH_*`
queue capsule publisher.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .manifest import write_standardized_manifest


class CapsulePublishResult(str):
    """String subclass representing the published capsule folder, unpackable as (final_dir, descriptor)."""

    def __new__(cls, path: str, descriptor: "BatchDescriptor"):
        obj = super().__new__(cls, path)
        obj.path = path
        obj.descriptor = descriptor
        return obj

    @property
    def capsule_dir(self) -> str:
        return self.path

    def __iter__(self):
        return iter((str(self), self.descriptor))


@dataclass
class BatchDescriptor:
    """
    Canonical `batch_descriptor.json` contract bridging BICC_INTAKE_CONTROLLER
    (pure producer) and DATA_INGESTION_ORCHESTRATOR (FIFO queue consumer).
    """

    schema_version: str = "1.0"
    batch_id: str = ""
    source: str = ""
    extract_timestamp_raw: str = ""
    extract_timestamp_iso: str = ""
    intake_timestamp_iso: str = ""
    standardized_manifest: str = ""
    raw_manifest: str = ""
    receipt_file: str = ""
    entities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    manifest_checksum: Optional[str] = None

    def __init__(
        self,
        schema_version: str = "1.0",
        batch_id: str = "",
        source: str = "",
        extract_timestamp_raw: str = "",
        extract_timestamp_iso: str = "",
        intake_timestamp_iso: str = "",
        standardized_manifest: str = "",
        raw_manifest: str = "",
        receipt_file: str = "",
        entities: Optional[Dict[str, Dict[str, Any]]] = None,
        **kwargs,
    ):
        self.schema_version = str(schema_version or kwargs.get("schema_version", "1.0"))
        self.batch_id = str(batch_id or kwargs.get("batch_id", ""))
        self.source = str(source or kwargs.get("source", ""))
        self.extract_timestamp_raw = str(
            extract_timestamp_raw or kwargs.get("extract_timestamp_raw", "")
        )
        self.extract_timestamp_iso = str(
            extract_timestamp_iso
            or kwargs.get("extract_timestamp")
            or kwargs.get("extract_timestamp_iso", "")
        )
        self.intake_timestamp_iso = str(
            intake_timestamp_iso
            or kwargs.get("created_at_utc")
            or kwargs.get("intake_timestamp_iso", "")
        )
        self.standardized_manifest = str(
            standardized_manifest
            or kwargs.get("manifest_filename")
            or kwargs.get("standardized_manifest", "")
        )
        self.raw_manifest = str(raw_manifest or kwargs.get("raw_manifest", ""))
        self.receipt_file = str(receipt_file or kwargs.get("receipt_file", ""))
        self.entities = dict(entities or kwargs.get("entities") or {})
        self.manifest_checksum = kwargs.get("manifest_checksum")

    @property
    def extract_timestamp(self) -> str:
        return self.extract_timestamp_iso

    @property
    def manifest_filename(self) -> str:
        return self.standardized_manifest

    @property
    def created_at_utc(self) -> str:
        return self.intake_timestamp_iso

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "source": self.source,
            "extract_timestamp_raw": self.extract_timestamp_raw,
            "extract_timestamp_iso": self.extract_timestamp_iso,
            "extract_timestamp": self.extract_timestamp_iso,
            "intake_timestamp_iso": self.intake_timestamp_iso,
            "created_at_utc": self.intake_timestamp_iso,
            "standardized_manifest": self.standardized_manifest,
            "manifest_filename": self.standardized_manifest,
            "raw_manifest": self.raw_manifest,
            "receipt_file": self.receipt_file,
            "entities": self.entities,
        }

    def to_json_file(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchDescriptor":
        return cls(
            schema_version=str(data.get("schema_version", "1.0")),
            batch_id=str(data["batch_id"]),
            source=str(data["source"]),
            extract_timestamp_raw=str(data.get("extract_timestamp_raw", "")),
            extract_timestamp_iso=str(data.get("extract_timestamp_iso") or data.get("extract_timestamp", "")),
            intake_timestamp_iso=str(data.get("intake_timestamp_iso") or data.get("created_at_utc", "")),
            standardized_manifest=str(data.get("standardized_manifest") or data.get("manifest_filename", "")),
            raw_manifest=str(data.get("raw_manifest", "")),
            receipt_file=str(data.get("receipt_file", "")),
            entities=dict(data.get("entities", {})),
        )

    @classmethod
    def from_json_file(cls, path: str) -> "BatchDescriptor":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


class CapsulePathResolver:
    """Resolves canonical Batch Capsule paths, normalizes extract timestamps, and publishes queue capsules."""

    @staticmethod
    def sanitize_token(value: str) -> str:
        """Sanitizes path tokens against directory traversal separators."""
        return str(value).strip().replace("/", "_").replace("\\", "_")

    @staticmethod
    def normalize_timestamp_token(ts: str) -> str:
        """
        Converts an ISO or raw timestamp into a compact filename-safe token:
        '2026-10-16 10:00:00' -> '20261016_100000'
        '20261016_100000'     -> '20261016_100000'
        """
        return (
            str(ts)
            .strip()
            .replace(":", "")
            .replace("-", "")
            .replace(" ", "_")
        )

    @classmethod
    def normalize_iso_timestamp(cls, ts: str) -> str:
        """
        Converts a compact timestamp token ('YYYYMMDD_HHMMSS') or ISO string
        into Teradata TIMESTAMP(0) format ('YYYY-MM-DD HH:MM:SS').
        """
        raw = str(ts).strip()
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

        clean_tok = cls.normalize_timestamp_token(raw)
        try:
            dt = datetime.strptime(clean_tok, "%Y%m%d_%H%M%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError(f"Unparseable timestamp: {ts!r}") from exc

    @classmethod
    def get_year_month(cls, ts: str) -> str:
        """
        Extracts 'YYYY-MM' partition folder name from an extract timestamp.
        Returns 'UNKNOWN_DATE' if the timestamp does not begin with YYYYMM digits.
        """
        clean_ts = cls.normalize_timestamp_token(ts)
        if len(clean_ts) >= 6 and clean_ts[:6].isdigit():
            return f"{clean_ts[:4]}-{clean_ts[4:6]}"
        return "UNKNOWN_DATE"

    @classmethod
    def get_capsule_folder_name(cls, batch_id: str, ts: str) -> str:
        """Returns 'BATCH_<BATCH_ID>_<CLEAN_TS>' (used in ARCHIVE_ZONE and LOGS)."""
        clean_batch = cls.sanitize_token(batch_id)
        clean_ts = cls.normalize_timestamp_token(ts)
        return f"BATCH_{clean_batch}_{clean_ts}"

    @classmethod
    def get_queue_capsule_folder_name(cls, batch_id: str, ts: str) -> str:
        """Returns 'BATCH_<CLEAN_TS>_<BATCH_ID>' (used in LANDING_ZONE and LOADING_ZONE FIFO queue)."""
        clean_batch = cls.sanitize_token(batch_id)
        clean_ts = cls.normalize_timestamp_token(ts)
        return f"BATCH_{clean_ts}_{clean_batch}"

    @classmethod
    def get_staging_queue_capsule_folder_name(cls, batch_id: str, ts: str) -> str:
        """Returns '.staging_BATCH_<CLEAN_TS>_<BATCH_ID>' for atomic staging in LANDING_ZONE."""
        clean_batch = cls.sanitize_token(batch_id)
        clean_ts = cls.normalize_timestamp_token(ts)
        return f".staging_BATCH_{clean_ts}_{clean_batch}"

    @classmethod
    def _build_capsule_path(
        cls,
        base_dir: str,
        source: str,
        batch_id: str,
        ts: str,
        ensure_exists: bool = False,
    ) -> str:
        """
        Constructs '<base_dir>/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>' using exact
        path-segment matching so parent folders containing `source` as a substring
        never suppress the `<SOURCE>` partition directory.
        """
        norm_base = os.path.normpath(base_dir)
        clean_src = cls.sanitize_token(source) if source else ""
        year_month = cls.get_year_month(ts)
        capsule_folder = cls.get_capsule_folder_name(batch_id, ts)

        last_segment = os.path.basename(norm_base)
        if last_segment.lower() == capsule_folder.lower():
            target_dir = norm_base
        elif clean_src and last_segment.lower() == clean_src.lower():
            target_dir = os.path.join(norm_base, year_month, capsule_folder)
        elif clean_src:
            target_dir = os.path.join(norm_base, clean_src, year_month, capsule_folder)
        else:
            target_dir = os.path.join(norm_base, year_month, capsule_folder)

        if ensure_exists:
            os.makedirs(target_dir, exist_ok=True)
        return target_dir

    @classmethod
    def get_archive_capsule_dir(
        cls,
        archive_base: str,
        source: str,
        batch_id: str,
        ts: str,
        ensure_exists: bool = False,
    ) -> str:
        """Returns '<archive_base>/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>'."""
        return cls._build_capsule_path(archive_base, source, batch_id, ts, ensure_exists=ensure_exists)

    @classmethod
    def get_raw_vault_dir(
        cls,
        archive_base: str,
        source: str,
        batch_id: str,
        ts: str,
        ensure_exists: bool = False,
    ) -> str:
        """Returns '<archive_base>/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/RAW'."""
        capsule_dir = cls.get_archive_capsule_dir(archive_base, source, batch_id, ts, ensure_exists=False)
        vault_dir = os.path.join(capsule_dir, "RAW")
        if ensure_exists:
            os.makedirs(vault_dir, exist_ok=True)
        return vault_dir

    @classmethod
    def get_log_capsule_dir(
        cls,
        logs_base: str,
        source: str,
        batch_id: str,
        ts: str,
        ensure_exists: bool = False,
    ) -> str:
        """Returns '<logs_base>/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>'."""
        return cls._build_capsule_path(logs_base, source, batch_id, ts, ensure_exists=ensure_exists)

    @classmethod
    def stage_and_publish_queue_capsule(
        cls,
        landing_zone_dir: Optional[str] = None,
        drop_zone_dir: Optional[str] = None,
        raw_manifest_path: Optional[str] = None,
        source: Optional[str] = None,
        extract_timestamp: Optional[str] = None,
        batch_id: Optional[str] = None,
        entities_descriptor: Optional[Dict[str, Dict[str, Any]]] = None,
        file_checksum_pairs: Optional[List[Tuple[str, str]]] = None,
        receipt_payload: Optional[List[Dict[str, Any]]] = None,
        declared_files: Optional[List[str]] = None,
        conflict_check_dirs: Optional[List[str]] = None,
        archive_root: Optional[str] = None,
        **kwargs,
    ) -> CapsulePublishResult:
        """
        Assembles a self-contained Batch Capsule inside
          `<landing_zone_dir>/.staging_BATCH_<CLEAN_TS>_<BATCH_ID>/`
        containing:
          - `RAW/<raw_manifest_filename>`
          - `RAW/RECEIPT_<SOURCE>_<CLEAN_TS>_<BATCH_ID>.json`
          - `MANIFEST_<SOURCE>_<CLEAN_TS>_<BATCH_ID>.MF`
          - `batch_descriptor.json`
          - payload data files moved from `drop_zone_dir`
        and atomically renames `.staging_BATCH_<CLEAN_TS>_<BATCH_ID>` -> `BATCH_<CLEAN_TS>_<BATCH_ID>`.
        """
        lz_dir = landing_zone_dir or kwargs.get("landing_zone") or kwargs.get("landing_zone_base")
        if not lz_dir:
            raise ValueError("landing_zone_dir (or landing_zone) must be provided.")
        src = str(source or kwargs.get("source", ""))
        clean_src = cls.sanitize_token(src)
        norm_lz = os.path.normpath(lz_dir)
        if clean_src and os.path.basename(norm_lz).lower() != clean_src.lower():
            if "landing_zone" in os.path.basename(norm_lz).lower():
                lz_dir = os.path.join(lz_dir, clean_src)
        os.makedirs(lz_dir, exist_ok=True)

        raw_mf = raw_manifest_path or kwargs.get("raw_manifest_path", "")
        b_id = str(batch_id or kwargs.get("batch_id", ""))
        raw_ts = str(
            extract_timestamp
            or kwargs.get("raw_ts")
            or kwargs.get("clean_ts")
            or kwargs.get("extract_timestamp", "")
        )
        clean_ts = kwargs.get("clean_ts") or cls.normalize_timestamp_token(raw_ts)
        iso_ts = cls.normalize_iso_timestamp(raw_ts)
        clean_src = cls.sanitize_token(src)
        clean_batch = cls.sanitize_token(b_id)

        staging_folder = cls.get_staging_queue_capsule_folder_name(clean_batch, clean_ts)
        final_folder = cls.get_queue_capsule_folder_name(clean_batch, clean_ts)
        staging_dir = os.path.join(lz_dir, staging_folder)
        final_dir = os.path.join(lz_dir, final_folder)

        # Conflict checks (F2.1): prevent duplicate deliveries across LANDING, LOADING, and ARCHIVE
        conflict_dirs = conflict_check_dirs or kwargs.get("conflict_check_dirs")
        arch_root = archive_root or kwargs.get("archive_root")
        conflicts = [final_dir]
        if conflict_dirs:
            for d in conflict_dirs:
                if d:
                    conflicts.append(os.path.join(d, final_folder))
        if arch_root:
            archive_dir = cls.get_archive_capsule_dir(arch_root, clean_src, clean_batch, clean_ts, ensure_exists=False)
            conflicts.append(archive_dir)

        existing = [p for p in conflicts if os.path.exists(p)]
        if existing:
            from dataloader_core.exceptions import BatchValidationError
            raise BatchValidationError(f"Batch {clean_batch}@{clean_ts} already exists: {existing}")

        os.makedirs(staging_dir, exist_ok=True)
        raw_dir = os.path.join(staging_dir, "RAW")
        os.makedirs(raw_dir, exist_ok=True)

        # 1. Move raw manifest into RAW/
        raw_basename = os.path.basename(raw_mf) if raw_mf else ""
        if raw_mf and os.path.exists(raw_mf):
            vault_manifest_path = os.path.join(raw_dir, raw_basename)
            if os.path.abspath(raw_mf) != os.path.abspath(vault_manifest_path):
                shutil.move(raw_mf, vault_manifest_path)

        # 2. Write canonical intake receipt into RAW/
        intake_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        std_receipt_name = f"RECEIPT_{clean_src}_{clean_ts}_{clean_batch}.json"
        std_receipt_path = os.path.join(raw_dir, std_receipt_name)
        if "receipt_dict" in kwargs:
            receipt_data = kwargs["receipt_dict"]
        else:
            receipt_data = {
                "batch_id": b_id,
                "source": src,
                "extract_timestamp": raw_ts,
                "intake_timestamp": intake_now,
                "raw_manifest_vaulted": raw_basename,
                "receipt_file": std_receipt_name,
                "payload": receipt_payload or [],
            }
        with open(std_receipt_path, "w", encoding="utf-8") as rf:
            json.dump(receipt_data, rf, indent=2)

        # 3. Write standardized manifest into staging_dir
        if "manifest_content" in kwargs:
            std_mf_name = f"MANIFEST_{clean_src}_{clean_ts}_{clean_batch}.MF"
            std_mf_path = os.path.join(staging_dir, std_mf_name)
            with open(std_mf_path, "w", encoding="utf-8") as f:
                f.write(kwargs["manifest_content"])
        else:
            std_mf_path = write_standardized_manifest(
                output_dir=staging_dir,
                source=clean_src,
                extract_timestamp=clean_ts,
                batch_id=clean_batch,
                file_checksum_pairs=file_checksum_pairs or [],
            )
            std_mf_name = os.path.basename(std_mf_path)

        # 4. Write batch_descriptor.json into staging_dir
        if "batch_descriptor" in kwargs:
            descriptor = kwargs["batch_descriptor"]
        else:
            descriptor = BatchDescriptor(
                schema_version="1.0",
                batch_id=b_id,
                source=src,
                extract_timestamp_raw=clean_ts,
                extract_timestamp_iso=iso_ts,
                intake_timestamp_iso=intake_now,
                standardized_manifest=std_mf_name,
                raw_manifest=f"RAW/{raw_basename}" if raw_basename else "",
                receipt_file=f"RAW/{std_receipt_name}",
                entities=entities_descriptor or {},
            )
        descriptor.to_json_file(os.path.join(staging_dir, "batch_descriptor.json"))

        # 5. Move payload data files
        if "payload_files" in kwargs:
            for item in kwargs["payload_files"]:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    src_f, dst_f = item
                    target_dst = os.path.join(staging_dir, dst_f)
                    if os.path.abspath(src_f) != os.path.abspath(target_dst):
                        if os.path.exists(target_dst):
                            os.remove(target_dst)
                        shutil.move(src_f, target_dst)
                else:
                    target_dst = os.path.join(staging_dir, os.path.basename(str(item)))
                    if os.path.abspath(str(item)) != os.path.abspath(target_dst):
                        if os.path.exists(target_dst):
                            os.remove(target_dst)
                        shutil.move(str(item), target_dst)
        elif drop_zone_dir and declared_files:
            for fname in declared_files:
                src_file = os.path.join(drop_zone_dir, fname)
                dst_file = os.path.join(staging_dir, fname)
                if os.path.exists(src_file) and os.path.abspath(src_file) != os.path.abspath(dst_file):
                    shutil.move(src_file, dst_file)

        # 6. Atomic publish: .staging_BATCH_<TS>_<ID> -> BATCH_<TS>_<ID>
        try:
            os.replace(staging_dir, final_dir)
        except (FileExistsError, OSError) as exc:
            if os.path.exists(staging_dir):
                for root, dirs, files in os.walk(staging_dir, topdown=False):
                    for f in files:
                        try:
                            os.remove(os.path.join(root, f))
                        except OSError:
                            pass
                    for d in dirs:
                        try:
                            os.rmdir(os.path.join(root, d))
                        except OSError:
                            pass
                try:
                    os.rmdir(staging_dir)
                except OSError:
                    pass
            from dataloader_core.exceptions import BatchValidationError
            raise BatchValidationError(f"Batch {clean_batch}@{clean_ts} already exists: {final_dir}") from exc

        return CapsulePublishResult(final_dir, descriptor)
